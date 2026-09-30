"""Buscador por significado para el mapa: bge-m3 (BAAI, multilingüe) sobre las fichas de los 8.131 municipios.

El buscador de palabras (BM25) solo trae municipios que comparten palabras con la frase: "ver las
estrellas" trae Lasarte-Oria por sus estrellas Michelin y deja fuera los pueblos de cielo oscuro que
no usan esa palabra. Aquí cada ficha y cada frase se convierten en un vector de 1.024 números que
resume lo que significan, y se buscan los más parecidos. En el servidor se mezclan las dos listas
(fusión por puestos, RRF) antes de que el reordenador elija.

    .venv-laya/Scripts/python mapa/big_dense.py build      # modelo en fp16 + vectores de las fichas
    .venv-laya/Scripts/python mapa/big_dense.py eval       # candidatos y acierto con y sin él
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BIG = HERE / "data" / "big"
SRC = ROOT / "models" / "bge-m3-src"
MODEL = ROOT / "models" / "bge-m3"
EMB = BIG / "emb_bge_m3.npy"


def dense_text(l: dict) -> str:
    """Lo que significa el municipio, sin cifras que despisten al vector."""
    where = "municipio costero" if l["costero"] else "municipio de interior"
    alt = f", a {l['elev']} m de altitud" if l.get("elev") else ""
    isla = ", en una isla" if l["reach"] == "island" else ""
    # sin el nombre: "ver las estrellas" no debe traer La Estrella ni Alconchel de la Estrella
    return f"{where.capitalize()}{alt}{isla}, en {l['prov']}. {l['rasgos'] or 'Pueblo sin rasgos destacados.'}"


class Encoder:
    def __init__(self, path=MODEL):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(path)
        self.model = AutoModel.from_pretrained(path, dtype=torch.float16, low_cpu_mem_usage=True).cuda().eval()

    def encode(self, texts: list[str], max_length=256, batch=64) -> np.ndarray:
        out = []
        with self.torch.no_grad():
            for k in range(0, len(texts), batch):
                b = self.tok(texts[k:k + batch], padding=True, truncation=True, max_length=max_length, return_tensors="pt")
                h = self.model(**{x: v.cuda() for x, v in b.items()}).last_hidden_state[:, 0]   # CLS, como bge-m3
                out.append(self.torch.nn.functional.normalize(h.float(), dim=-1).cpu().numpy())
        return np.concatenate(out).astype(np.float16)


def build():
    import torch
    from transformers import AutoModel, AutoTokenizer
    if not (MODEL / "model.safetensors").exists():
        # una sola vez: de 2,3 GB en fp32 a 1,1 GB en fp16 y en safetensors (carga rápida y con poca RAM)
        m = AutoModel.from_pretrained(SRC, dtype=torch.float16, low_cpu_mem_usage=True)
        m.save_pretrained(MODEL)
        AutoTokenizer.from_pretrained(SRC).save_pretrained(MODEL)
        del m
        print(f"modelo en fp16 guardado en {MODEL}", flush=True)
    lugares = json.loads((BIG / "lugares.json").read_text(encoding="utf-8"))
    enc = Encoder()
    t0 = time.time()
    emb = enc.encode([dense_text(l) for l in lugares])
    np.save(EMB, emb)
    print(f"{emb.shape[0]} fichas en {time.time() - t0:.0f} s -> {EMB.name} ({EMB.stat().st_size / 1e6:.0f} MB)", flush=True)


def rrf(lists: list[list[int]], k: int = 60, n: int = 100) -> list[int]:
    """Fusión por puestos: cada lista da 1/(k + puesto); gana quien aparece arriba en alguna."""
    sc: dict[int, float] = {}
    for l in lists:
        for r, i in enumerate(l):
            sc[i] = sc.get(i, 0.0) + 1.0 / (k + r + 1)
    return [i for i, _ in sorted(sc.items(), key=lambda kv: -kv[1])[:n]]


def evaluate():
    """¿Cuántos candidatos de verdad buenos trae cada buscador? Juez: gpt-6-luna sobre los 10 primeros."""
    import asyncio
    sys.path.insert(0, str(HERE))
    from big_bge import Reranker, judge_text, judge_lists, paired
    from big_server import Search
    from big_tree import Tree, load_labels
    lugares = json.loads((BIG / "lugares.json").read_text(encoding="utf-8"))
    idx = {l["ine"]: i for i, l in enumerate(lugares)}
    rows = load_labels(exam=True)
    search = Search(lugares)
    emb = np.load(EMB).astype(np.float32)
    enc = Encoder()
    rr = Reranker(ROOT / "models" / "bge-rerank-mapa")
    texts = {l["ine"]: judge_text(l) for l in lugares}
    lists, ms = [], []
    for r in rows:
        q = r["frase"]
        t0 = time.perf_counter()
        qv = enc.encode([q], max_length=64)[0].astype(np.float32)
        dense = list(np.argsort(-(emb @ qv))[:100])
        t_dense = (time.perf_counter() - t0) * 1000
        bm = search.top(q, 100, None)
        hyb = rrf([bm, dense])
        out = {}
        for name, cand in (("palabras", bm), ("hibrido", hyb), ("significado", dense[:100])):
            ines = [lugares[i]["ine"] for i in cand]
            out[name] = rr.rank(q, ines, texts)[:10]
        out["palabras_solo"] = [lugares[i]["ine"] for i in bm[:10]]
        out["significado_solo"] = [lugares[i]["ine"] for i in dense[:10]]
        lists.append(out)
        ms.append(t_dense)
    tree = Tree()
    verdicts, cost = asyncio.run(judge_lists(rows, lists, tree))
    prec = {k: [len(set(l[k]) & set(v)) / 10 for l, v in zip(lists, verdicts)] for k in lists[0]}
    rep = {"acierto@10 (juez gpt-6-luna)": {k: round(float(np.mean(v)), 3) for k, v in prec.items()},
           "hibrido - palabras (con reordenador)": paired(prec["hibrido"], prec["palabras"]),
           "significado - palabras (con reordenador)": paired(prec["significado"], prec["palabras"]),
           "ms_vector_frase_mediana": round(float(np.median(ms)), 1), "coste_juez": cost}
    (BIG / "dense-report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (BIG / "dense-listas.json").write_text(json.dumps([{"frase": r["frase"], **l} for r, l in zip(rows, lists)], ensure_ascii=False), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("build", "eval"))
    a = ap.parse_args()
    build() if a.cmd == "build" else evaluate()
