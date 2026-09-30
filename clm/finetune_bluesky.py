"""Afinar las cabezas de CLM-8B con las etiquetas de jev en Bluesky, como hicimos con Laya.

1. Qwen3-8B (4 bits) convierte en vector cada post junto con cada pregunta (emoción y tema) y cada
   opción. Es lo caro: se hace una vez y se guarda en clm/data/.
2. Con los vectores guardados, se entrenan solo las dos cabezas (~20 M parámetros cada una), partiendo
   de las oficiales, para que su reparto entre opciones imite las probabilidades de jev (objetivo
   suave, como --targets soft en el train/finetune.py oficial). Minutos.
3. Examen: los mismos 600 posts que Laya (sin entrenar 48,5 % / 38,8 %; destilada 65,2 % / 65,5 %).

    .venv-laya/Scripts/python -m clm.finetune_bluesky embed     # ~20 min con la gráfica libre
    .venv-laya/Scripts/python -m clm.finetune_bluesky train
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import time
from pathlib import Path

import numpy as np
import torch

from .schema import build_pairs

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "clm" / "data"
OUT = ROOT / "models" / "clm" / "CLM_bluesky.pt"
TEST = 600
QIDS = ("emotion", "topic")


def questions():
    spec = importlib.util.spec_from_file_location("bq", ROOT / "bluesky" / "spike" / "questions.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return {k: m.Q[k] for k in QIDS}


def rows():
    return [json.loads(l) for l in open(ROOT / "bluesky" / "data" / "labels.jsonl", encoding="utf-8")]


def embed():
    from .local import CLM
    DATA.mkdir(parents=True, exist_ok=True)
    qs, rs = questions(), rows()
    clm = CLM()
    # opciones: 15 textos fijos
    opts = {q: build_pairs("x", {q: qs[q]})[q] for q in QIDS}
    opt_emb = {q: clm.embed(opts[q][2]).half().cpu().numpy() for q in QIDS}
    np.savez(DATA / "options.npz", **{q: opt_emb[q] for q in QIDS}, **{f"{q}_keys": np.array(opts[q][1]) for q in QIDS})
    for q in QIDS:
        path = DATA / f"states_{q}.npy"
        if path.exists():
            continue
        texts = [build_pairs(r["text"], {q: qs[q]})[q][0] for r in rs]
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))    # por longitud: menos relleno
        out = np.zeros((len(texts), 4096), np.float16)
        t0 = time.time()
        for k in range(0, len(order), 16):
            idx = order[k:k + 16]
            out[idx] = clm.embed([texts[i] for i in idx], batch=16).half().cpu().numpy()
            if k % 1600 == 0:
                print(f"  {q}: {k}/{len(texts)} ({time.time() - t0:.0f} s)", flush=True)
        np.save(path, out)
        print(f"{q}: {len(texts)} vectores en {time.time() - t0:.0f} s", flush=True)


def train(epochs=8, lr=3e-5, batch=256, val=False, save=True):
    """val=True: se aparta de entrenamiento una validación (posts 600-1199) y se mide en ella, no en el examen."""
    from .local import HEADS, make_head
    rs = rows()
    opts = np.load(DATA / "options.npz")
    ck = torch.load(HEADS, map_location="cpu")
    cfg = dict(ck["cfg"])
    kw = dict(width=cfg["width"], depth=cfg["depth"], proj=ck.get("projection_dim", cfg.get("projection_dim", 512)),
              activation=cfg.get("activation", "gelu"), layernorm=cfg.get("layernorm", False),
              residual=cfg.get("residual", False), hidden=cfg.get("hidden_size", 4096))
    sh, ah = make_head(**kw).cuda(), make_head(**kw).cuda()
    sh.load_state_dict(ck["state_head"]); ah.load_state_dict(ck["action_head"])
    log_scale = torch.nn.Parameter(torch.as_tensor(ck["logit_scale"]).float().cuda())
    data = {}
    for q in QIDS:
        keys = [str(k) for k in opts[f"{q}_keys"]]
        S = torch.from_numpy(np.load(DATA / f"states_{q}.npy")).float().cuda()
        A = torch.from_numpy(opts[q]).float().cuda()
        T = torch.tensor([[r["jev"][q].get(k, 0.0) for k in keys] for r in rs]).float()
        T = (T / T.sum(1, keepdim=True).clamp(min=1e-9)).cuda()
        data[q] = (S, A, T, keys)

    def logits(q, idx):
        S, A, _, _ = data[q]
        zs = torch.nn.functional.normalize(sh(S[idx]), dim=-1)
        za = torch.nn.functional.normalize(ah(A), dim=-1)
        return log_scale.exp().clamp(max=100) * zs @ za.T

    lo = 2 * TEST if val else TEST                  # primer post de entrenamiento

    def evaluate():
        sh.eval(); ah.eval()
        out = {}
        with torch.no_grad():
            idx = torch.arange(TEST, 2 * TEST, device="cuda") if val else torch.arange(TEST, device="cuda")
            for q in QIDS:
                pred = logits(q, idx).argmax(1)
                out[q] = round(float((pred == data[q][2][idx].argmax(1)).float().mean()), 3)
        sh.train(); ah.train()
        return out

    report = {"antes": evaluate()}
    print("sin afinar:", report["antes"], flush=True)
    params = [*sh.parameters(), *ah.parameters(), log_scale]
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.01)
    n = len(rs) - lo
    steps = epochs * len(QIDS) * ((n + batch - 1) // batch)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, s / max(1, steps * 0.06)) * max(0.0, (steps - s) / steps))
    t0 = time.time()
    for ep in range(epochs):
        g = torch.Generator().manual_seed(ep)
        perm = (torch.randperm(n, generator=g) + lo).cuda()
        for k in range(0, n, batch):
            idx = perm[k:k + batch]
            loss = 0.0
            for q in QIDS:
                lg = logits(q, idx)
                loss = loss - (data[q][2][idx] * torch.log_softmax(lg, -1)).sum(-1).mean()
            opt.zero_grad(); loss.backward(); torch.nn.utils.clip_grad_norm_(params, 1.0); opt.step(); sched.step()
        report[f"epoca_{ep + 1}"] = evaluate()
        print(f"época {ep + 1}: {report[f'epoca_{ep + 1}']} pérdida {loss.item():.3f} ({time.time() - t0:.0f} s)", flush=True)
    report["segundos"] = round(time.time() - t0)
    if not save:
        return report
    OUT.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_head": sh.state_dict(), "action_head": ah.state_dict(), "logit_scale": log_scale.detach().cpu(),
                "cfg": cfg, "projection_dim": kw["proj"], "fine_tuned_on": "bluesky jev labels"}, OUT)
    (ROOT / "clm" / "finetune-bluesky-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("embed", "train"))
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--lr", type=float, default=3e-5)
    ap.add_argument("--sweep", action="store_true", help="busca lr y épocas en la validación, no en el examen")
    a = ap.parse_args()
    if a.cmd == "embed":
        embed()
    elif a.sweep:
        res = {}
        for lr in (3e-5, 1e-4, 3e-4, 1e-3):
            r = train(40, lr, val=True, save=False)
            best = max((k for k in r if k.startswith("epoca_")), key=lambda k: sum(r[k].values()))
            res[lr] = (best, r[best])
            print(f"lr {lr}: mejor {best} {r[best]}", flush=True)
        print(json.dumps({str(k): v for k, v in res.items()}))
    else:
        train(a.epochs, a.lr)
