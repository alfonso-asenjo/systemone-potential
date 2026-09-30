"""Un reordenador conocido, sin entrenar, contra el alumno: bge-reranker-v2-m3 en el examen del mapa.

La pregunta: antes de destilar un modelo propio, ¿había ya un especialista que lo hacía igual?
Mismas 50 frases del examen y mismos 50 candidatos del buscador que ordena Laya. El reordenador se
prueba con dos textos por municipio: el que ve el juez (nombre, provincia, datos y rasgos) y el
recortado que ve Laya, para separar el efecto del modelo del de los datos. Se juzgan a la vez los 10
primeros de cada sistema con gpt-6-luna, igual que en big_rerank.py.

    .venv-laya/Scripts/python mapa/big_bge.py              # ordena, mide tiempos y juzga (~0,05 $)
    .venv-laya/Scripts/python mapa/big_bge.py --no-judge   # solo ordena y guarda las listas
    .venv-laya/Scripts/python mapa/big_bge.py --tuned models/bge-rerank-mapa   # añade el afinado
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from pathlib import Path

import numpy as np

from big_tree import Tree, load_labels

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BIG = HERE / "data" / "big"
BGE = ROOT / "models" / "bge-reranker-v2-m3"
K = 10


def judge_text(l: dict) -> str:
    """Lo mismo que lee el juez, sin el código INE delante."""
    from big_label import describe
    return describe(l).split(" | ", 1)[1]


class Reranker:
    def __init__(self, path=BGE):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(path)
        self.model = AutoModelForSequenceClassification.from_pretrained(path, dtype=torch.float16).cuda().eval()

    def scores(self, query: str, docs: list[str]) -> list[float]:
        with self.torch.no_grad():
            b = self.tok([[query, d] for d in docs], padding=True, truncation=True, max_length=512, return_tensors="pt")
            return self.model(**{k: v.cuda() for k, v in b.items()}).logits.view(-1).float().tolist()

    def rank(self, query: str, cands: list[str], texts: dict[str, str]) -> list[str]:
        sc = self.scores(query, [texts[c] for c in cands])
        return [c for _, c in sorted(zip(sc, cands), key=lambda t: -t[0])]


def timed(fn, *a):
    import torch
    torch.cuda.synchronize(); t0 = time.perf_counter()
    out = fn(*a)
    torch.cuda.synchronize()
    return out, (time.perf_counter() - t0) * 1000


async def judge_lists(rows, lists_by_row, tree):
    import aiohttp
    from big_judge import judge
    from big_label import PRICE_IN, PRICE_OUT, key
    stats = {"in": 0, "out": 0}
    verdicts = []
    headers = {"Authorization": f"Bearer {key()}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=180)) as s:
        for r, lists in zip(rows, lists_by_row):
            union = list(dict.fromkeys(x for l in lists.values() for x in l))
            random.Random(r["frase"]).shuffle(union)       # el juez no ve de quién viene cada uno
            good = await judge(s, r["frase"], [tree.lug[x] for x in union], stats)
            verdicts.append(sorted(good & set(union)))
    return verdicts, round(stats["in"] * PRICE_IN + stats["out"] * PRICE_OUT, 3)


def paired(a: list[float], b: list[float], n_boot=10000):
    d = np.array(a) - np.array(b)
    rng = np.random.default_rng(0)
    boots = [rng.choice(d, len(d)).mean() for _ in range(n_boot)]
    return {"diferencia": round(float(d.mean()), 3), "ic95": [round(float(np.percentile(boots, 2.5)), 3), round(float(np.percentile(boots, 97.5)), 3)],
            "gana": int((d > 0).sum()), "empata": int((d == 0).sum()), "pierde": int((d < 0).sum())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--tuned", help="reordenador afinado con las etiquetas del profesor (big_bge_train.py)")
    args = ap.parse_args()
    tag = "-afinado" if args.tuned else ""

    import laya
    from big_rerank import OUT, rerank
    tree = Tree()
    rows = load_labels(exam=True)
    agent = laya.load(str(OUT), device="cuda")
    bge = Reranker()
    tuned = Reranker(ROOT / args.tuned) if args.tuned else None
    t_judge = {ine: judge_text(l) for ine, l in tree.lug.items()}
    t_laya = {ine: tree.option(ine) for ine in tree.lug}

    # calentar la GPU antes de medir tiempos
    for _ in range(2):
        bge.rank(rows[0]["frase"], rows[0]["candidatos"], t_judge); rerank(agent, tree, rows[0]["frase"], rows[0]["candidatos"])

    lists_by_row, ms = [], {"alumno": [], "bge": [], "bge_texto_laya": [], **({"bge_afinado": []} if tuned else {})}
    for r in rows:
        f, c = r["frase"], r["candidatos"]
        alumno, t1 = timed(rerank, agent, tree, f, c)
        b1, t2 = timed(bge.rank, f, c, t_judge)
        b2, t3 = timed(bge.rank, f, c, t_laya)
        ms["alumno"].append(t1); ms["bge"].append(t2); ms["bge_texto_laya"].append(t3)
        row = {"alumno": alumno[:K], "bge": b1[:K], "bge_texto_laya": b2[:K],
               "buscador": c[:K], "profesor": [x for x, _ in r["elegidos"]][:K]}
        if tuned:
            b3, t4 = timed(tuned.rank, f, c, t_judge)
            ms["bge_afinado"].append(t4); row["bge_afinado"] = b3[:K]
        lists_by_row.append(row)
    (BIG / f"bge-listas{tag}.json").write_text(json.dumps([{"frase": r["frase"], **l} for r, l in zip(rows, lists_by_row)],
                                                    ensure_ascii=False, indent=1), encoding="utf-8")
    report = {"frases": len(rows), "ms_mediana": {k: round(float(np.median(v))) for k, v in ms.items()}}
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if args.no_judge:
        return

    verdicts, cost = asyncio.run(judge_lists(rows, lists_by_row, tree))
    prec = {name: [len(set(l[name]) & set(v)) / len(l[name]) for l, v in zip(lists_by_row, verdicts)] for name in lists_by_row[0]}
    report["acierto@10 (juez gpt-6-luna)"] = {k: round(float(np.mean(v)), 3) for k, v in prec.items()}
    report["bge - alumno"] = paired(prec["bge"], prec["alumno"])
    report["bge - buscador"] = paired(prec["bge"], prec["buscador"])
    report["bge_texto_laya - alumno"] = paired(prec["bge_texto_laya"], prec["alumno"])
    if tuned:
        report["afinado - alumno"] = paired(prec["bge_afinado"], prec["alumno"])
        report["afinado - bge sin afinar"] = paired(prec["bge_afinado"], prec["bge"])
    report["coste_juez"] = cost
    (BIG / f"bge-veredictos{tag}.json").write_text(json.dumps(verdicts), encoding="utf-8")
    (BIG / f"bge-report{tag}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
