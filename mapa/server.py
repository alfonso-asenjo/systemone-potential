"""Luces de España: escribes lo que buscas y el mapa se enciende donde jev cree que está.

    python mapa/server.py            # y abrir http://127.0.0.1:8780/

El navegador manda la frase mientras escribes; el servidor aplica los límites que sabe leer,
pregunta a jev y devuelve la probabilidad de cada lugar. Solo hay una pregunta en vuelo por
conexión: si llegan frases nuevas mientras tanto, se contesta únicamente la última.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from aiohttp import WSMsgType, web

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from jevcraft.config import settings                  # noqa: E402
from jevcraft.jev_client import JevClient, JevError   # noqa: E402
import questions                                       # noqa: E402

STATIC = HERE / "static"
LOGS = HERE / "logs"
PLACES = json.loads((STATIC / "places.json").read_text(encoding="utf-8"))


def open_log():
    LOGS.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for n in range(1, 100):
        path = LOGS / (f"mapa-{stamp}.jsonl" if n == 1 else f"mapa-{stamp}-{n}.jsonl")
        try:
            return path.open("x", encoding="utf-8")
        except FileExistsError:
            continue
    raise RuntimeError("no free log name")


async def answer(jev: JevClient, text: str) -> dict:
    c = questions.parse(text)
    allowed = [p for p in PLACES if c.allows(p)]
    base = {"text": text, "notes": c.notes,
            "allowed": None if len(allowed) == len(PLACES) else [p["id"] for p in allowed]}
    if not allowed:
        return {**base, "probs": {}, "empty": True}
    resp = await jev.decide(text, questions.build(allowed))
    a = resp.answers.get("lugar", {}) or {}
    probs = {k: round(float(v), 4) for k, v in (a.get("probabilities") or {}).items() if float(v) > 0}
    return {**base, "probs": probs, "choice": a.get("choice"),
            "confidence": a.get("confidence"), "latency_ms": round(resp.latency_ms),
            "tokens": resp.input_tokens, "cost_usd": resp.cost_usd,
            "total_cost_usd": round(jev.total_cost, 6)}


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    jev: JevClient = request.app["jev"]
    log = open_log()
    latest: dict | None = None
    busy = False

    async def run():
        nonlocal latest, busy
        busy = True
        try:
            while latest is not None:
                msg, latest = latest, None
                text = (msg.get("text") or "").strip()[:300]
                if not text:
                    out = {"probs": {}, "allowed": None, "notes": [], "text": ""}
                else:
                    try:
                        out = await answer(jev, text)
                    except (JevError, asyncio.TimeoutError) as exc:
                        out = {"error": str(exc)[:200], "text": text}
                out.update(type="answer", seq=msg.get("seq"))
                log.write(json.dumps({"t": time.time(), **out}, ensure_ascii=False) + "\n")
                log.flush()
                if not ws.closed:
                    await ws.send_json(out)
        finally:
            busy = False

    try:
        async for raw in ws:
            if raw.type != WSMsgType.TEXT:
                continue
            msg = json.loads(raw.data)
            if msg.get("type") == "ask":
                latest = msg
                if not busy:
                    asyncio.create_task(run())
    finally:
        log.close()
    return ws


async def no_cache(_request: web.Request, response: web.StreamResponse):
    response.headers["Cache-Control"] = "no-cache"


async def index(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC / "index.html")


async def on_startup(app: web.Application):
    await app["jev"].start()


async def on_cleanup(app: web.Application):
    await app["jev"].close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8780)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    app = web.Application()
    app["jev"] = JevClient(settings)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.on_response_prepare.append(no_cache)
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    app.router.add_static("/", STATIC, show_index=False)
    print(f"[mapa] jev via {settings.provider}, {len(PLACES)} lugares")
    print(f"[mapa] http://127.0.0.1:{args.port}/")
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
