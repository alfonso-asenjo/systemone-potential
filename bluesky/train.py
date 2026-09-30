"""Destilar jev en Laya multilingüe para leer el flujo de Bluesky.

Misma receta que pacman/distill/train.py: objetivo blando (las probabilidades de jev),
solo las capas de arriba del codificador y la cabeza de decisión, lo congelado en fp16.

Sin entrenar, Laya coincidía con jev en la emoción de 22 de 60 posts, ponía "sorpresa" en
un tercio (jev en el 5 %) y su toxicidad y contenido adulto eran ruido (un anuncio de
cruceros, tóxico al 100 %). Los filtros son lo delicado: si el alumno se salta un post
adulto, sale en el vídeo. Por eso esos ejemplos pesan más y el listón se calibra aparte
para que el alumno recoja al menos el 95 % de lo que jev marca.

    .venv-laya/Scripts/python bluesky/train.py [--epochs 3]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import sys
import time

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "spike"))
from questions import Q  # noqa: E402

import laya  # noqa: E402
from laya.agent import Agent  # noqa: E402
from laya.common import collate_items  # noqa: E402

BASE = os.path.join(ROOT, "models", "laya", "multilingual")
OUT = os.path.join(ROOT, "models", "laya-bluesky")
DATA = os.path.join(HERE, "data")
TOP_LAYERS = 8
TEST_POSTS = 600
FILTER_WEIGHT = 3.0      # posts que jev marca como tóxicos o adultos
FILTER_RECALL = 0.95     # el listón del alumno recoge al menos esto de lo que marca jev
INTERNAL = {q: Agent._to_internal(v) for q, v in Q.items()}


def targets(row: dict) -> dict[str, list[float]]:
    return {q: [row["jev"][q].get(k, 0.0) for k in Q[q]["criteria"]] for q in Q}


def encode(agent: Agent, row: dict) -> list[dict]:
    ids = list(Q)
    items = agent._encode_state(row["text"], ids, INTERNAL)
    t = targets(row)
    flagged = t["toxic"][1] >= 0.5 or t["adult"][1] >= 0.5
    for qid, it in zip(ids, items):
        s = sum(t[qid]) or 1.0
        it["target"] = [x / s for x in t[qid]]
        it["qid"] = qid
        it["weight"] = FILTER_WEIGHT if flagged and qid in ("toxic", "adult") else 1.0
    return items


def evaluate(agent: Agent, rows: list[dict]) -> dict:
    agent.model.eval()
    res = agent.predict_batch([r["text"] for r in rows], Q, batch_size=16)
    out = {}
    for q in Q:
        keys = list(Q[q]["criteria"])
        hit = sum(max(r["jev"][q], key=r["jev"][q].get) == x["answers"][q]["choice"] for r, x in zip(rows, res))
        out[f"{q}_agree"] = round(hit / len(rows), 3)
    emo = [x["answers"]["emotion"]["choice"] for x in res]
    out["surprise_share"] = round(emo.count("surprise") / len(emo), 3)
    for q in ("toxic", "adult"):
        teacher = np.array([r["jev"][q].get(q, 0.0) >= 0.5 for r in rows])
        student = np.array([x["answers"][q]["probabilities"][q] for x in res])
        if teacher.sum():
            # El listón más alto que aún recoge el FILTER_RECALL de lo que jev marca.
            thr = float(np.quantile(student[teacher], 1 - FILTER_RECALL))
            flagged = student >= thr
            out[f"{q}_min"] = round(thr, 4)
            out[f"{q}_recall"] = round(float(flagged[teacher].mean()), 3)
            out[f"{q}_false_alarm"] = round(float(flagged[~teacher].mean()), 3)
            out[f"{q}_jev_positives"] = int(teacher.sum())
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--train-limit", type=int, default=None,
                    help="curva de aprendizaje: entrenar solo con los N primeros posts, sin guardar el modelo")
    args = ap.parse_args()

    torch.manual_seed(0)
    rows = [json.loads(l) for l in open(os.path.join(DATA, "labels.jsonl"), encoding="utf-8")]
    random.Random(7).shuffle(rows)
    test, train = rows[:TEST_POSTS], rows[TEST_POSTS:]
    if args.train_limit:
        train = train[:args.train_limit]
    agent = laya.load(BASE, device="cuda")
    report = {"train_posts": len(train), "test_posts": len(test)}
    report["before"] = evaluate(agent, test) if not args.train_limit else None
    if report["before"]:
        print("sin entrenar:", json.dumps(report["before"]), flush=True)
    # Medido: con tandas de 16 y la caché que deja este examen, la gráfica se llenaba
    # (7,7 de 8 GB), Windows desbordaba a RAM y cada paso tardaba 7,8 s. Con tandas de 8
    # y la caché vaciada, pico de 3,3 GB y 0,19 s por paso.
    torch.cuda.empty_cache()

    model = agent.model
    layers = model.encoder.layers
    for p in model.parameters():
        p.requires_grad = False
    model.encoder.embeddings.half()
    for layer in layers[:len(layers) - TOP_LAYERS]:
        layer.half()
    trainable = [*layers[-TOP_LAYERS:], model.encoder.final_norm, model.head, model.type_emb, model.scorer]
    for m in trainable:
        for p in m.parameters():
            p.requires_grad = True
    enc = [p for m in trainable[:TOP_LAYERS + 1] for p in m.parameters()]
    head = [p for m in trainable[TOP_LAYERS + 1:] for p in m.parameters()]
    opt = torch.optim.AdamW([{"params": enc, "lr": 3e-5}, {"params": head, "lr": 1e-4}], weight_decay=0.01)
    steps = args.epochs * math.ceil(len(train) / args.batch)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, s / max(1, steps * 0.06)) * max(0.0, (steps - s) / steps))
    scaler = torch.amp.GradScaler("cuda")
    encoded = [encode(agent, r) for r in train]
    agent.temperature, agent.temperature_by_options = [1.0, 1.0, 1.0], {}
    print(f"entrenando {sum(p.numel() for p in enc + head) / 1e6:.0f} M parámetros, {steps} pasos", flush=True)

    t0, step = time.perf_counter(), 0
    for epoch in range(args.epochs):
        model.train()
        order = list(range(len(encoded)))
        random.shuffle(order)
        for i in range(0, len(order), args.batch):
            b = collate_items([encoded[j] for j in order[i:i + args.batch]], agent.tok.pad_token_id)
            with torch.autocast("cuda", dtype=torch.float16):
                logits, _ = model(b["input_ids"].cuda(), b["attention_mask"].cuda(), b["marker_pos"].cuda(),
                                  b["marker_mask"].cuda(), b["qtype"].cuda())
            mask = b["marker_mask"].cuda()
            logp = torch.log_softmax(logits.float(), -1).masked_fill(~mask, 0)
            w = torch.tensor([m["weight"] for m in b["meta"]], device="cuda")
            loss = ((-(b["target"].cuda() * logp).sum(-1)) * w).sum() / w.sum()
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(enc + head, 1.0)
            scaler.step(opt)
            scaler.update()
            sched.step()
            step += 1
            if step % 100 == 0:
                print(f"  época {epoch + 1} paso {step}/{steps} pérdida {loss.item():.4f} "
                      f"({time.perf_counter() - t0:.0f} s)", flush=True)
        if not args.train_limit or epoch == args.epochs - 1:
            report[f"after_epoch_{epoch + 1}"] = evaluate(agent, test)
            print(f"época {epoch + 1}: {json.dumps(report[f'after_epoch_{epoch + 1}'])}", flush=True)

    report["train_seconds"] = round(time.perf_counter() - t0)
    report["after"] = report[f"after_epoch_{args.epochs}"]
    if args.train_limit:
        with open(os.path.join(DATA, f"curve-{args.train_limit}.json"), "w") as f:
            json.dump(report, f, indent=1)
        print(f"curva: {args.train_limit} posts en {report['train_seconds']} s")
        return
    from safetensors.torch import save_file
    os.makedirs(OUT, exist_ok=True)
    for sub in ("tokenizer", "encoder"):
        shutil.copytree(os.path.join(BASE, sub), os.path.join(OUT, sub), dirs_exist_ok=True)
    cfg = dict(agent.cfg)
    cfg.update({"model_name": "laya-bluesky", "temperature": [1.0, 1.0, 1.0], "temperature_by_options": {},
                "distilled_from": "typesafe/jev-1.13",
                "bluesky": {"toxic_min": report["after"].get("toxic_min"),
                            "adult_min": report["after"].get("adult_min")}})
    with open(os.path.join(OUT, "rl_agent_config.json"), "w") as f:
        json.dump(cfg, f, indent=2)
    save_file({k: (v.detach().half() if v.is_floating_point() else v).contiguous().cpu()
               for k, v in model.state_dict().items()}, os.path.join(OUT, "model.safetensors"))
    with open(os.path.join(DATA, "report.json"), "w") as f:
        json.dump(report, f, indent=1)
    print(f"alumno guardado en {OUT}")


if __name__ == "__main__":
    main()
