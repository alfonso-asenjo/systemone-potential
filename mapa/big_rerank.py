"""Buscador + Laya: el buscador de palabras trae 50 candidatos y Laya los reordena.

El árbol (big_tree.py) no pasó del 23-28 % en el examen justo frente al 34-39 % del buscador:
cada nivel acertaba un 80-84 %, pero cuatro o cinco decisiones seguidas encadenan errores. Aquí
Laya solo hace lo que ya se le daba bien, elegir entre ~20 opciones (84 % dentro de un grupo),
y con las mismas etiquetas: el profesor eligió precisamente entre estos 50 candidatos.

Los 50 se reparten en 3 preguntas alternando puestos (1.º, 4.º, 7.º... en la primera), para que
Laya no aprenda "los primeros del buscador son los buenos" sino a leer los rasgos. Cada pregunta
lleva además "ninguno encaja": si el profesor no eligió a nadie de un bloque, esa es la respuesta.

    .venv-laya/Scripts/python mapa/big_rerank.py train [--epochs 3] [--limit N]
    .venv-laya/Scripts/python mapa/big_rerank.py judge [--model models/laya-rerank]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import shutil
import time
from pathlib import Path

import numpy as np

from big_tree import BASE, TOP_LAYERS, Tree, load_labels, picks_of, state

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BIG = HERE / "data" / "big"
OUT = ROOT / "models" / "laya-rerank"
CHUNKS = 3
NONE = "ninguno"
QUESTION = "¿Qué municipio encaja mejor con lo que busca esta persona?"


def chunks(cands: list[str]) -> list[list[str]]:
    return [cands[k::CHUNKS] for k in range(CHUNKS)]


def question(tree: Tree, part: list[str]) -> dict:
    crit = {x: tree.option(x) for x in part}
    crit[NONE] = "Ninguno de estos encaja con la búsqueda"
    return {"type": "choice", "instructions": QUESTION, "criteria": crit}


def targets(part: list[str], picks: dict[str, float]) -> list[float]:
    w = [picks.get(x, 0.0) for x in part]
    s = sum(w)
    return [x / s for x in w] + [0.0] if s else [0.0] * len(part) + [1.0]


def scores(agent, tree: Tree, frase: str, cands: list[str]) -> dict[str, float]:
    """Probabilidad que Laya da a cada candidato dentro de su bloque (junto a "ninguno encaja")."""
    parts = chunks(cands)
    qs = {f"b{k}": question(tree, p) for k, p in enumerate(parts) if p}
    ans = agent.predict(state(frase), qs, head_max_len=1024)["answers"]
    out = {}
    for k, p in enumerate(parts):
        probs = ans[f"b{k}"]["probabilities"]
        for x in p:
            out[x] = probs.get(x, 0.0)
    return out


def rerank(agent, tree: Tree, frase: str, cands: list[str]) -> list[str]:
    """Los candidatos ordenados por la probabilidad que les da Laya en su bloque."""
    sc = scores(agent, tree, frase, cands)
    return sorted(cands, key=lambda x: -sc[x])


def encode(agent, tree, r):
    from laya.agent import Agent
    parts = [p for p in chunks(r["candidatos"]) if p]
    ids = [f"b{k}" for k in range(len(parts))]
    internal = {i: Agent._to_internal(question(tree, p)) for i, p in zip(ids, parts)}
    items = agent._encode_state(state(r["frase"]), ids, internal, head_max_len=1024)
    picks = picks_of(r)
    for p, it in zip(parts, items):
        it["target"] = targets(p, picks)
        it["qid"] = "b"
    return items


async def judge_all(agent, tree, rows, label):
    import aiohttp
    from big_judge import judge
    from big_label import PRICE_IN, PRICE_OUT, key
    stats = {"in": 0, "out": 0}
    prec = {"alumno": [], "buscador": [], "profesor": []}
    ms = []
    headers = {"Authorization": f"Bearer {key()}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=180)) as s:
        for r in rows:
            t0 = time.perf_counter()
            order = rerank(agent, tree, r["frase"], r["candidatos"])
            ms.append((time.perf_counter() - t0) * 1000)
            lists = {"alumno": order[:10], "buscador": r["candidatos"][:10], "profesor": [x for x, _ in r["elegidos"]][:10]}
            union = list(dict.fromkeys(x for l in lists.values() for x in l))
            good = await judge(s, r["frase"], [tree.lug[x] for x in union], stats)
            for name, l in lists.items():
                if l:
                    prec[name].append(sum(x in good for x in l) / len(l))
    out = {k: round(float(np.mean(v)), 3) for k, v in prec.items()}
    out["ms_mediana"] = round(float(np.median(ms)))
    out["coste_juez"] = round(stats["in"] * PRICE_IN + stats["out"] * PRICE_OUT, 3)
    print(f"{label}: acierto@10 según el juez -> {json.dumps(out)}", flush=True)
    return out


def train(args):
    import torch
    import laya
    from laya.common import collate_items
    tree = Tree()
    rows = load_labels(exam=False)
    if args.limit:
        rows = rows[:args.limit]
    exam = load_labels(exam=True)
    agent = laya.load(str(BASE), device="cuda")
    report = {"train_frases": len(rows), "before": asyncio.run(judge_all(agent, tree, exam, "sin entrenar"))}
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
    items = [it for r in rows for it in encode(agent, tree, r)]
    lens = sorted(len(it["ids"]) for it in items)
    print(f"{len(items)} preguntas, tokens p50 {lens[len(lens) // 2]} p90 {lens[int(len(lens) * .9)]}", flush=True)
    steps = args.epochs * math.ceil(len(items) / args.batch)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, s / max(1, steps * 0.06)) * max(0.0, (steps - s) / steps))
    scaler = torch.amp.GradScaler("cuda")
    agent.temperature, agent.temperature_by_options = [1.0, 1.0, 1.0], {}
    t0, step = time.time(), 0
    for epoch in range(args.epochs):
        model.train()
        random.Random(epoch).shuffle(items)
        for i in range(0, len(items), args.batch):
            b = collate_items([items[i:i + args.batch]], agent.tok.pad_token_id)
            with torch.autocast("cuda", dtype=torch.float16):
                logits, _ = model(b["input_ids"].cuda(), b["attention_mask"].cuda(), b["marker_pos"].cuda(),
                                  b["marker_mask"].cuda(), b["qtype"].cuda())
            mask = b["marker_mask"].cuda()
            logp = torch.log_softmax(logits.float(), -1).masked_fill(~mask, 0)
            loss = -(b["target"].cuda() * logp).sum(-1).mean()
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(enc + head, 1.0)
            scaler.step(opt); scaler.update(); sched.step()
            step += 1
            if step % 200 == 0:
                print(f"  época {epoch + 1} paso {step}/{steps} pérdida {loss.item():.3f} ({time.time() - t0:.0f} s)", flush=True)
        model.eval()
        report[f"epoch_{epoch + 1}"] = asyncio.run(judge_all(agent, tree, exam, f"época {epoch + 1}"))
        torch.cuda.empty_cache()
    report["train_seconds"] = round(time.time() - t0)
    if not args.limit:
        from safetensors.torch import save_file
        os.makedirs(OUT, exist_ok=True)
        for sub in ("tokenizer", "encoder"):
            shutil.copytree(BASE / sub, OUT / sub, dirs_exist_ok=True)
        cfg = dict(agent.cfg)
        cfg.update({"model_name": "laya-rerank", "temperature": [1.0, 1.0, 1.0], "temperature_by_options": {},
                    "distilled_from": "gpt-6-luna"})
        (OUT / "rl_agent_config.json").write_text(json.dumps(cfg, indent=2))
        save_file({k: (v.detach().half() if v.is_floating_point() else v).contiguous().cpu()
                   for k, v in model.state_dict().items()}, str(OUT / "model.safetensors"))
        print(f"alumno guardado en {OUT}", flush=True)
    (BIG / ("rerank-report.json" if not args.limit else "rerank-report-smoke.json")).write_text(json.dumps(report, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("train", "judge"))
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default=str(OUT))
    args = ap.parse_args()
    if args.cmd == "train":
        train(args)
    else:
        import laya
        asyncio.run(judge_all(laya.load(args.model, device="cuda"), Tree(), load_labels(exam=True), args.model))


if __name__ == "__main__":
    main()
