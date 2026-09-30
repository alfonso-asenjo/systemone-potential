"""CLM-8B eligiendo entre los 8.131 municipios de una sola vez, afinado con las etiquetas del profesor.

jev elige entre 255 opciones como mucho y Laya entre ~20; el reordenador del mapa lee 100 candidatos.
CLM puede comparar la frase con los 8.131 municipios a la vez: los vectores de los municipios se
calculan una vez y se guardan, y en cada búsqueda solo se procesa la frase.

1. embed: Qwen3-8B (4 bits) vectoriza las 8.131 fichas (como opciones) y las 5.003 frases (como
   situación + pregunta, la plantilla oficial de CLM).
2. train: se afinan solo las dos cabezas para que cada frase quede cerca de los municipios que eligió
   el profesor (reparto según su nota de 1 a 3) y lejos de todos los demás: softmax sobre los 8.131.
   Ajuste elegido con 300 frases de validación, nunca con el examen.
3. eval: juez gpt-6-luna sobre los 10 primeros de cada sistema en las 50 frases del examen.

    .venv-laya/Scripts/python -m clm.finetune_mapa embed
    .venv-laya/Scripts/python -m clm.finetune_mapa train [--sweep]
    .venv-laya/Scripts/python -m clm.finetune_mapa eval
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

from .schema import state_text

ROOT = Path(__file__).resolve().parent.parent
BIG = ROOT / "mapa" / "data" / "big"
DATA = ROOT / "clm" / "data"
OUT = ROOT / "models" / "clm" / "CLM_mapa.pt"
QUESTION = "¿Qué municipio encaja mejor con lo que busca esta persona?"
VAL = 300
sys.path.insert(0, str(ROOT / "mapa"))


def lugares():
    return json.loads((BIG / "lugares.json").read_text(encoding="utf-8"))


def labels():
    rows = [json.loads(l) for l in (BIG / "etiquetas.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    return [r for r in rows if r["elegidos"]]


def option_text(l: dict) -> str:
    from big_dense import dense_text      # la ficha sin el nombre del pueblo (el nombre despista)
    return dense_text(l)


def embed():
    from .local import CLM
    DATA.mkdir(parents=True, exist_ok=True)
    clm = CLM()
    for name, texts in (("mapa_opciones", [option_text(l) for l in lugares()]),
                        ("mapa_frases", [state_text(r["frase"], QUESTION) for r in labels()])):
        path = DATA / f"{name}.npy"
        if path.exists():
            continue
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        out = np.zeros((len(texts), 4096), np.float16)
        t0 = time.time()
        for k in range(0, len(order), 16):
            idx = order[k:k + 16]
            out[idx] = clm.embed([texts[i] for i in idx], batch=16).half().cpu().numpy()
        np.save(path, out)
        print(f"{name}: {len(texts)} vectores en {time.time() - t0:.0f} s", flush=True)


def load_heads(path):
    from .local import make_head
    ck = torch.load(path, map_location="cpu")
    cfg = dict(ck["cfg"])
    kw = dict(width=cfg["width"], depth=cfg["depth"], proj=ck.get("projection_dim", cfg.get("projection_dim", 512)),
              activation=cfg.get("activation", "gelu"), layernorm=cfg.get("layernorm", False),
              residual=cfg.get("residual", False), hidden=cfg.get("hidden_size", 4096))
    sh, ah = make_head(**kw).cuda(), make_head(**kw).cuda()
    sh.load_state_dict(ck["state_head"]); ah.load_state_dict(ck["action_head"])
    return sh, ah, torch.nn.Parameter(torch.as_tensor(ck["logit_scale"]).float().cuda()), cfg, kw


def data():
    lug, rows = lugares(), labels()
    idx = {l["ine"]: i for i, l in enumerate(lug)}
    A = torch.from_numpy(np.load(DATA / "mapa_opciones.npy")).float().cuda()
    S = torch.from_numpy(np.load(DATA / "mapa_frases.npy")).float().cuda()
    T = torch.zeros(len(rows), len(lug))
    for i, r in enumerate(rows):
        for ine, n in r["elegidos"]:
            if ine in idx:
                T[i, idx[ine]] = float(n)
    T = T / T.sum(1, keepdim=True).clamp(min=1e-9)
    exam = torch.tensor([bool(r.get("examen")) for r in rows])
    return lug, rows, A, S, T.cuda(), exam


def recall_at(sh, ah, scale, A, S, T, idx, k=10):
    """Parte de lo elegido por el profesor que cae en los k primeros de los 8.131."""
    with torch.no_grad():
        za = torch.nn.functional.normalize(ah(A), dim=-1)
        zs = torch.nn.functional.normalize(sh(S[idx]), dim=-1)
        top = (zs @ za.T).topk(k, dim=1).indices
        hit = torch.gather((T[idx] > 0).float(), 1, top).sum(1)
        return float((hit / (T[idx] > 0).float().sum(1).clamp(max=k)).mean())


def train(epochs=20, lr=1e-3, batch=128, val=False, save=True, verbose=True):
    from .local import HEADS
    lug, rows, A, S, T, exam = data()
    sh, ah, log_scale, cfg, kw = load_heads(HEADS)
    pool = torch.nonzero(~exam).squeeze(1)
    g0 = torch.Generator().manual_seed(0)
    pool = pool[torch.randperm(len(pool), generator=g0)]
    val_idx, train_idx = (pool[:VAL], pool[VAL:]) if val else (torch.nonzero(exam).squeeze(1), pool)
    val_idx, train_idx = val_idx.cuda(), train_idx.cuda()
    rep = {"antes_recall@10": round(recall_at(sh, ah, log_scale.exp(), A, S, T, val_idx), 3)}
    params = [*sh.parameters(), *ah.parameters(), log_scale]
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.01)
    steps = epochs * ((len(train_idx) + batch - 1) // batch)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, s / max(1, steps * 0.06)) * max(0.0, (steps - s) / steps))
    t0 = time.time()
    best = (-1, None)
    for ep in range(epochs):
        sh.train(); ah.train()
        perm = train_idx[torch.randperm(len(train_idx), generator=torch.Generator().manual_seed(ep)).cuda()]
        for k in range(0, len(perm), batch):
            b = perm[k:k + batch]
            za = torch.nn.functional.normalize(ah(A), dim=-1)
            zs = torch.nn.functional.normalize(sh(S[b]), dim=-1)
            lg = log_scale.exp().clamp(max=100) * zs @ za.T
            loss = -(T[b] * torch.log_softmax(lg, -1)).sum(-1).mean()
            opt.zero_grad(); loss.backward(); torch.nn.utils.clip_grad_norm_(params, 1.0); opt.step(); sched.step()
        sh.eval(); ah.eval()
        r = recall_at(sh, ah, log_scale.exp(), A, S, T, val_idx)
        rep[f"epoca_{ep + 1}"] = round(r, 3)
        if r > best[0]:
            best = (r, ep + 1)
        if verbose:
            print(f"época {ep + 1}: recall@10 {r:.3f} pérdida {loss.item():.3f} ({time.time() - t0:.0f} s)", flush=True)
    rep["mejor"] = best
    rep["segundos"] = round(time.time() - t0)
    if save:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        torch.save({"state_head": sh.state_dict(), "action_head": ah.state_dict(), "logit_scale": log_scale.detach().cpu(),
                    "cfg": cfg, "projection_dim": kw["proj"], "fine_tuned_on": "mapa: etiquetas de gpt-6-luna"}, OUT)
        (ROOT / "clm" / "finetune-mapa-report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return rep


def evaluate():
    """Juez gpt-6-luna sobre los 10 primeros de cada sistema, en las 50 frases del examen."""
    from big_bge import Reranker, judge_lists, judge_text, paired
    from big_dense import rrf
    from big_server import Search
    from big_tree import Tree, load_labels
    from .local import HEADS
    lug, rows, A, S, T, exam = data()
    exam_rows = load_labels(exam=True)
    frase_idx = {r["frase"]: i for i, r in enumerate(rows)}
    search = Search(lug)
    rr = Reranker(ROOT / "models" / "bge-rerank-mapa")
    texts = {l["ine"]: judge_text(l) for l in lug}
    heads = {"clm_sin_afinar": load_heads(HEADS)[:3], "clm_afinado": load_heads(OUT)[:3]}
    za = {}
    with torch.no_grad():
        for name, (sh, ah, ls) in heads.items():
            sh.eval(); ah.eval()
            za[name] = torch.nn.functional.normalize(ah(A), dim=-1)
    lists, ms = [], []
    for r in exam_rows:
        q, i = r["frase"], frase_idx[r["frase"]]
        out = {}
        with torch.no_grad():
            for name, (sh, ah, ls) in heads.items():
                zs = torch.nn.functional.normalize(sh(S[i:i + 1]), dim=-1)
                order = (zs @ za[name].T)[0].argsort(descending=True).tolist()
                out[name] = [lug[j]["ine"] for j in order[:10]]
                if name == "clm_afinado":
                    clm100 = order[:100]
        bm = search.top(q, 100, None)
        out["palabras"] = [lug[j]["ine"] for j in bm[:10]]
        out["palabras+reordenador"] = rr.rank(q, [lug[j]["ine"] for j in bm], texts)[:10]
        out["clm+reordenador"] = rr.rank(q, [lug[j]["ine"] for j in clm100], texts)[:10]
        out["palabras+clm+reordenador"] = rr.rank(q, [lug[j]["ine"] for j in rrf([bm, clm100])], texts)[:10]
        lists.append(out)
    verdicts, cost = asyncio.run(judge_lists(exam_rows, lists, Tree()))
    prec = {k: [len(set(l[k]) & set(v)) / 10 for l, v in zip(lists, verdicts)] for k in lists[0]}
    rep = {"acierto@10 (juez gpt-6-luna)": {k: round(float(np.mean(v)), 3) for k, v in prec.items()},
           "clm_afinado - palabras": paired(prec["clm_afinado"], prec["palabras"]),
           "clm+reordenador - palabras+reordenador": paired(prec["clm+reordenador"], prec["palabras+reordenador"]),
           "palabras+clm+reordenador - palabras+reordenador": paired(prec["palabras+clm+reordenador"], prec["palabras+reordenador"]),
           "coste_juez": cost}
    (ROOT / "clm" / "mapa-eval-report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / "clm" / "mapa-eval-listas.json").write_text(json.dumps([{"frase": r["frase"], **l} for r, l in zip(exam_rows, lists)], ensure_ascii=False), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("embed", "train", "eval"))
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--lr", type=float, default=1e-3)
    a = ap.parse_args()
    if a.cmd == "embed":
        embed()
    elif a.cmd == "eval":
        evaluate()
    elif a.sweep:
        for lr in (1e-4, 3e-4, 1e-3, 3e-3):
            r = train(40, lr, val=True, save=False, verbose=False)
            print(f"lr {lr}: antes {r['antes_recall@10']}, mejor recall@10 {r['mejor'][0]:.3f} en la época {r['mejor'][1]}", flush=True)
    else:
        print(json.dumps(train(a.epochs, a.lr), ensure_ascii=False))
