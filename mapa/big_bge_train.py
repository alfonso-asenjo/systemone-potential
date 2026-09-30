"""Afinar el reordenador conocido (bge-reranker-v2-m3) con las etiquetas del profesor.

Sin entrenar, bge-reranker empata con el alumno Laya destilado (big_bge.py). Aquí aprende el gusto
del profesor con las mismas 5.003 frases que usó Laya: en cada paso ve un grupo de candidatos de
una frase y aprende a repartir la probabilidad como el profesor, según sus notas de 1 a 3.

No cabe entero en 8 GB (568 M parámetros con AdamW), así que, como con Laya, se congelan en media
precisión la capa de palabras y las capas de abajo, y se entrenan las TOP de arriba y la cabeza.

    .venv-laya/Scripts/python mapa/big_bge_train.py --limit 200 --epochs 1   # prueba
    .venv-laya/Scripts/python mapa/big_bge_train.py                            # completo
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path

import numpy as np

from big_bge import BGE, judge_text
from big_tree import Tree, load_labels, picks_of

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BIG = HERE / "data" / "big"
OUT = ROOT / "models" / "bge-rerank-mapa"
TOP = 8          # capas de arriba que se entrenan (de 24)
GROUP = 32       # candidatos por paso: todos los elegidos (hasta 12) y el resto sin elegir
MAX_LEN = 256


def group_of(r, rng):
    picks = picks_of(r)
    pos = [c for c in r["candidatos"] if c in picks][:12]
    neg = [c for c in r["candidatos"] if c not in picks]
    rng.shuffle(neg)
    items = pos + neg[:GROUP - len(pos)]
    w = np.array([picks.get(c, 0.0) for c in items])
    return items, (w / w.sum()).tolist()


def teacher_recall(model, tok, rows, texts, torch):
    """Parte de los elegidos del profesor que caen en los 10 primeros: una medida gratis, sin juez."""
    model.eval()
    out = []
    with torch.no_grad():
        for r in rows:
            c = r["candidatos"]
            b = tok([[r["frase"], texts[x]] for x in c], padding=True, truncation=True, max_length=MAX_LEN, return_tensors="pt")
            with torch.autocast("cuda", dtype=torch.float16):
                sc = model(**{k: v.cuda() for k, v in b.items()}).logits.view(-1).float().tolist()
            top = {x for _, x in sorted(zip(sc, c), key=lambda t: -t[0])[:10]}
            picks = picks_of(r)
            out.append(len(top & set(picks)) / min(10, len(picks)))
    model.train()
    return round(float(np.mean(out)), 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    tree = Tree()
    texts = {ine: judge_text(l) for ine, l in tree.lug.items()}
    rows = load_labels(exam=False)
    if args.limit:
        rows = rows[:args.limit]
    exam = load_labels(exam=True)

    tok = AutoTokenizer.from_pretrained(BGE)
    model = AutoModelForSequenceClassification.from_pretrained(BGE, dtype=torch.float32).cuda()
    enc = model.roberta.encoder.layer
    for p in model.parameters():
        p.requires_grad = False
    model.roberta.embeddings.half()
    for layer in enc[:len(enc) - TOP]:
        layer.half()
    trainable = [*enc[-TOP:], model.classifier]
    for m in trainable:
        for p in m.parameters():
            p.requires_grad = True
    n_train = sum(p.numel() for m in trainable for p in m.parameters())
    report = {"frases": len(rows), "capas_entrenadas": TOP, "parametros_entrenados_M": round(n_train / 1e6, 1),
              "antes": {"recall_profesor@10": teacher_recall(model, tok, exam, texts, torch)}}
    print(json.dumps(report, ensure_ascii=False), flush=True)

    body = [p for m in trainable[:-1] for p in m.parameters()]
    head = list(model.classifier.parameters())
    opt = torch.optim.AdamW([{"params": body, "lr": 1e-5}, {"params": head, "lr": 5e-5}], weight_decay=0.01)
    steps = args.epochs * len(rows)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, s / max(1, steps * 0.06)) * max(0.0, (steps - s) / steps))
    scaler = torch.amp.GradScaler("cuda")
    t0, step, losses = time.time(), 0, []
    model.train()
    for epoch in range(args.epochs):
        rng = random.Random(epoch)
        order = rows[:]
        rng.shuffle(order)
        for r in order:
            items, target = group_of(r, rng)
            b = tok([[r["frase"], texts[x]] for x in items], padding=True, truncation=True, max_length=MAX_LEN, return_tensors="pt")
            with torch.autocast("cuda", dtype=torch.float16):
                logits = model(**{k: v.cuda() for k, v in b.items()}).logits.view(-1).float()
            loss = -(torch.tensor(target, device="cuda") * torch.log_softmax(logits, -1)).sum()
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(body + head, 1.0)
            scaler.step(opt); scaler.update(); sched.step()
            losses.append(loss.item()); step += 1
            if step % 200 == 0:
                print(f"  época {epoch + 1} paso {step}/{steps} pérdida {np.mean(losses[-200:]):.3f} "
                      f"({time.time() - t0:.0f} s, {torch.cuda.max_memory_allocated() / 2**30:.1f} GB)", flush=True)
        report[f"epoca_{epoch + 1}"] = {"recall_profesor@10": teacher_recall(model, tok, exam, texts, torch),
                                         "perdida": round(float(np.mean(losses[-len(rows):])), 3)}
        print(json.dumps(report[f"epoca_{epoch + 1}"], ensure_ascii=False), flush=True)
        torch.cuda.empty_cache()
    report["segundos"] = round(time.time() - t0)
    if not args.limit:
        model.half().save_pretrained(OUT)
        tok.save_pretrained(OUT)
        print(f"guardado en {OUT}", flush=True)
    (BIG / ("bge-train-report.json" if not args.limit else "bge-train-report-smoke.json")).write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
