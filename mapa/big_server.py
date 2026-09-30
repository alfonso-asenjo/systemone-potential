"""Luces de España con los 8.131 municipios, todo en local y gratis.

    .venv-laya/Scripts/python mapa/big_server.py [--host 0.0.0.0] [--brain bge|laya]
    y abrir http://127.0.0.1:8781/ (o /carreteras.html)

Por cada frase: el código aplica los límites que sabe leer ("a menos de 2 horas", "sin avión",
de questions.py), un buscador de palabras trae los 100 municipios que mejor casan y un modelo
local los reordena en la GPU. Ninguna llamada a una API: 0 € por búsqueda.

El que reordena (--brain):
  bge   bge-reranker-v2-m3 afinado con las etiquetas de gpt-6-luna (big_bge_train.py). El mejor
        en el examen: ~77 % frente a 61 % de Laya con juez a ciegas. Por defecto desde el 28-09.
  laya  Laya destilada (big_rerank.py). Se tragaba trampas como "ver las estrellas" -> Lasarte-Oria,
        cuya ficha habla de un restaurante con tres estrellas Michelin.

Candidatos (--retrieval):
  mezcla    BM25 + buscador por significado (bge-m3, big_dense.py), fusionados por puestos (RRF).
            En el examen de 50 frases empata con BM25 (59,8 % frente a 61,6 %, dentro del ruido: esas
            frases salieron de las propias fichas), pero con búsquedas naturales trae lo que BM25 no
            ve: "ver las estrellas desde un castillo" -> Hornos (planetario en el castillo). Por defecto.
  palabras  solo BM25.

El buscador es BM25 con índice invertido: con 8.131 descripciones, recorrerlas todas en cada
tecla sería lento; así solo se puntúan las que contienen alguna palabra de la frase.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from aiohttp import WSMsgType, web

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import questions  # noqa: E402  límites que sabe leer el código
from review import doc_text, tokens  # noqa: E402

BIG = HERE / "data" / "big"
STATIC = HERE / "static_big"
# 100 candidatos = 6 bloques de ~17 para Laya. Con 50, un pueblo que el buscador de palabras
# dejaba en el puesto 60 no llegaba nunca a Laya. Laya se entrenó con los 50 primeros; con 100
# no está medido (decidido así el 26-09-2026).
N_CAND = 100


class Search:
    """BM25 sobre nombre, provincia y rasgos, con índice invertido."""

    def __init__(self, lugares, k1=1.4, b=0.75):
        docs = [Counter(tokens(doc_text(l))) for l in lugares]
        self.len = [sum(d.values()) for d in docs]
        self.avg = sum(self.len) / len(self.len)
        self.post = defaultdict(list)
        for i, d in enumerate(docs):
            for w, f in d.items():
                self.post[w].append((i, f))
        n = len(docs)
        self.idf = {w: math.log(1 + (n - len(p) + 0.5) / (len(p) + 0.5)) for w, p in self.post.items()}
        self.k1, self.b = k1, b

    def top(self, query: str, k: int, allowed: set[int] | None) -> list[int]:
        score = defaultdict(float)
        for w in set(tokens(query)):
            idf = self.idf.get(w)
            if idf is None:
                continue
            for i, f in self.post[w]:
                if allowed is None or i in allowed:
                    score[i] += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
        return [i for i, _ in sorted(score.items(), key=lambda kv: -kv[1])[:k]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8781)
    ap.add_argument("--brain", choices=("bge", "laya"), default="bge")
    ap.add_argument("--retrieval", choices=("mezcla", "palabras"), default="mezcla")
    args = ap.parse_args()

    lugares = json.loads((BIG / "lugares.json").read_text(encoding="utf-8"))
    search = Search(lugares)
    if args.retrieval == "mezcla":
        import numpy as np
        from big_dense import EMB, Encoder, rrf
        enc = Encoder()
        emb = np.load(EMB).astype(np.float32)

        def candidates(text, allowed):
            bm = search.top(text, N_CAND, allowed)
            sim = emb @ enc.encode([text], max_length=64)[0].astype(np.float32)
            if allowed is not None:
                mask = np.full(len(lugares), -np.inf, np.float32)
                mask[list(allowed)] = 0
                sim = sim + mask
            dense = [int(i) for i in np.argsort(-sim)[:N_CAND] if np.isfinite(sim[i])]
            return rrf([bm, dense], n=N_CAND)
    else:
        def candidates(text, allowed):
            return search.top(text, N_CAND, allowed)
    if args.brain == "laya":
        import laya
        from big_rerank import OUT, scores
        from big_tree import Tree
        tree = Tree()
        agent = laya.load(str(OUT), device="cuda")
        device = agent.device
        name = "Laya destilada"

        def rank(text, ines):
            return scores(agent, tree, text, ines)
    else:
        import torch
        from big_bge import Reranker, judge_text
        rr = Reranker(HERE.parent / "models" / "bge-rerank-mapa")
        texts = {l["ine"]: judge_text(l) for l in lugares}
        device = "cuda"
        name = "bge-reranker afinado"

        def rank(text, ines):
            # cada pareja frase-municipio se puntúa por separado; el reparto entre candidatos es un
            # softmax, igual que en el entrenamiento
            logits = []
            for k in range(0, len(ines), 50):
                logits += rr.scores(text, [texts[x] for x in ines[k:k + 50]])
            p = torch.softmax(torch.tensor(logits), 0).tolist()
            return dict(zip(ines, p))
    # questions.Constraints.allows lee "reach" y "hours", los mismos campos que aquí.
    lock = asyncio.Lock()

    def answer(text: str) -> dict:
        t0 = time.perf_counter()
        c = questions.parse(text)
        allowed = None
        if c.max_hours is not None or c.no_flight:
            allowed = {i for i, l in enumerate(lugares) if c.allows(l)}
        cand = candidates(text, allowed)
        t_search = (time.perf_counter() - t0) * 1000
        if not cand:
            return {"probs": {}, "notes": c.notes, "allowed": sorted(allowed) if allowed is not None else None,
                    "empty": bool(text.strip()), "search_ms": round(t_search)}
        sc = rank(text, [lugares[i]["ine"] for i in cand])
        raw = {i: sc[lugares[i]["ine"]] for i in cand}
        s = sum(raw.values()) or 1.0
        probs = {i: v / s for i, v in raw.items() if v / s >= 0.002}
        return {"probs": probs, "notes": c.notes, "allowed": sorted(allowed) if allowed is not None else None,
                "empty": False, "search_ms": round(t_search), "latency_ms": round((time.perf_counter() - t0) * 1000),
                "candidates": len(cand), "brain": name}

    async def ws_handler(req):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(req)
        latest = {"seq": 0, "text": ""}
        busy = False

        async def run():
            nonlocal busy
            busy = True
            try:
                while True:
                    seq, text = latest["seq"], latest["text"]
                    if not text.strip():
                        out = {"probs": {}, "notes": [], "allowed": None}
                    else:
                        async with lock:     # una GPU: una pregunta a la vez
                            out = await asyncio.to_thread(answer, text)
                    if not ws.closed:
                        await ws.send_json({"type": "answer", "seq": seq, "text": text, **out})
                    if latest["seq"] == seq:   # solo se contesta la última frase
                        break
            finally:
                busy = False

        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            d = json.loads(msg.data)
            if d.get("type") == "log":      # lo que cuenta el navegador: toques, elecciones y errores
                print(f"[cliente {req.remote}] {d.get('kind')}: {json.dumps(d.get('data'), ensure_ascii=False)}", flush=True)
                continue
            if d.get("type") == "ask":
                latest.update(seq=d["seq"], text=d.get("text", ""))
                if not busy:
                    asyncio.create_task(run())
        return ws

    async def index(_):
        return web.FileResponse(STATIC / "index.html")

    async def no_cache(_req, resp):
        resp.headers["Cache-Control"] = "no-cache"

    app = web.Application()
    app.on_response_prepare.append(no_cache)
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    app.router.add_static("/vendor", HERE / "static" / "vendor")
    app.router.add_static("/", STATIC)
    print(f"[luces-8000] {len(lugares)} municipios, {name} en {device} -> http://{args.host}:{args.port}/", flush=True)
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
