"""Serves the game and puts its questions to jev.

    python pacman/server.py            then open http://127.0.0.1:8770
    .venv-laya/Scripts/python pacman/server.py --brain laya     the distilled student instead
    ... --brain laya --shadow     the student plays and jev labels every state it reaches (DAgger)

The browser runs the whole game; this process only holds the API key, asks jev, applies
the guards in decide.py and records every decision so a game can be replayed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from aiohttp import WSMsgType, web

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from jevcraft.config import settings          # noqa: E402
from jevcraft.jev_client import JevClient, JevError   # noqa: E402

# El alumno tiene sus propios umbrales y decide.py los lee del entorno al importarse.
BRAIN = "laya" if "--brain" in sys.argv and sys.argv[sys.argv.index("--brain") + 1] == "laya" else "jev"
if BRAIN == "laya":
    sys.path.insert(0, str(ROOT / "distill"))
    from laya_client import LayaClient, configure_thresholds  # noqa: E402
    configure_thresholds()

from decide import TURN_BACK_MIN, interpret   # noqa: E402
from questions import build as build_questions  # noqa: E402
from build import bundle  # noqa: E402

STATIC = ROOT / "static"
# PACMAN_LOG_DIR: las partidas de práctica pueden ir a su propia carpeta
LOGS = Path(os.environ["PACMAN_LOG_DIR"]) if os.environ.get("PACMAN_LOG_DIR") else ROOT / "logs"


class Session:
    """One browser tab: its own log file and its own pending records."""

    def __init__(self, client: JevClient, teacher: JevClient | None = None):
        self.client = client
        self.teacher = teacher
        self.seed = None
        self.seq = 0
        self.pending: dict[int, dict] = {}
        self.path = None
        self.file = None

    def open_log(self, seed: int):
        LOGS.mkdir(exist_ok=True)
        self.seed = seed
        # Two games started in the same second used to share, and garble, one file.
        stamp = time.strftime('%Y%m%d-%H%M%S')
        for n in range(1, 100):
            self.path = LOGS / (f"pacman-{stamp}.jsonl" if n == 1 else f"pacman-{stamp}-{n}.jsonl")
            try:
                self.file = self.path.open("x", encoding="utf-8")
                break
            except FileExistsError:
                continue
        self.write({"type": "header", "seed": seed, "started": time.time(), "brain": BRAIN})
        print(f"[log] {self.path.name} (seed {seed})")

    def write(self, record: dict):
        if self.file:
            self.file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.file.flush()

    def close(self):
        for record in self.pending.values():      # never applied, keep them anyway
            self.write(record)
        self.pending.clear()
        if self.file:
            self.file.close()
            self.file = None


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=25)
    await ws.prepare(request)
    session = Session(request.app["jev"], request.app.get("teacher"))

    async for msg in ws:
        if msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
            break
        try:
            data = json.loads(msg.data)
        except ValueError:
            continue

        if data.get("type") == "hello":
            session.open_log(int(data.get("seed", 0)))
            await ws.send_json({"type": "hello", "brain": BRAIN})   # la página rotula con quién juega

        elif data.get("type") == "ask":
            asyncio.create_task(handle_ask(ws, session, data))

        elif data.get("type") == "applied":
            record = session.pending.pop(data.get("seq"), None)
            if record is not None:
                record["recv_tick"] = data.get("recv_tick")
                record["applied"] = data.get("applied")
                record["score_at_recv"] = data.get("score")
                session.write(record)

    session.close()
    return ws


async def handle_ask(ws: web.WebSocketResponse, session: Session, data: dict):
    state = data["state"]
    exits = data["exits"]
    session.seq += 1
    seq = session.seq
    client = session.client

    try:
        resp = await client.decide(state, build_questions(exits, state))
    except (JevError, asyncio.TimeoutError, OSError) as exc:
        if not ws.closed:
            await ws.send_json({"type": "error", "seq": seq, "message": str(exc)[:200]})
        return

    if session.teacher is not None:
        asyncio.create_task(shadow_label(session.teacher, session, seq, state, exits))

    decision = interpret(resp.answers, state, exits)
    record = {
        "type": "decision",
        "seq": seq,
        "ask_tick": data.get("tick"),
        "reason": data.get("reason"),
        "latency_ms": round(resp.latency_ms),
        "model": resp.model,
        "usage": {"input_tokens": resp.input_tokens, "cost_usd": resp.cost_usd},
        "decision": decision.as_dict(),
        "answers": resp.answers,
        "exits": exits,
        "state": state,
    }
    session.pending[seq] = record

    if not ws.closed:
        await ws.send_json({
            "type": "decision",
            "seq": seq,
            "tick": data.get("tick"),
            "reason": data.get("reason"),
            "latency_ms": round(resp.latency_ms),
            "decision": decision.as_dict(),
            "answers": resp.answers,
            "turn_back_min": TURN_BACK_MIN,
            "total_cost_usd": round(client.total_cost, 6),
        })


async def shadow_label(teacher: JevClient, session: Session, seq: int, state: dict, exits: list):
    """DAgger: el alumno se mete en sitios que el profesor nunca pisó (medido: Laya muere
    acorralada, con todas las salidas a 0-1 casillas de sitio). jev contesta aquí a la misma
    pregunta sin mover a España, y su respuesta queda como ejemplo para el siguiente alumno."""
    try:
        resp = await teacher.decide(state, build_questions(exits, state))
    except (JevError, asyncio.TimeoutError, OSError):
        return
    session.write({"type": "teacher", "seq": seq, "model": resp.model, "answers": resp.answers,
                   "exits": exits, "state": state,
                   "usage": {"input_tokens": resp.input_tokens, "cost_usd": resp.cost_usd}})


async def replay_handler(request: web.Request) -> web.Response:
    name = Path(request.match_info["name"]).name       # no directory traversal
    path = LOGS / name
    if not path.exists():
        raise web.HTTPNotFound(text=f"no hay grabación llamada {name}")
    return web.json_response(bundle(path))


async def replays_handler(_request: web.Request) -> web.Response:
    LOGS.mkdir(exist_ok=True)
    names = sorted((p.name for p in LOGS.glob("pacman-*.jsonl")), reverse=True)
    return web.json_response({"replays": names})


def lan_addresses() -> list[str]:
    """Addresses of this machine that another device on the network could use."""
    import socket
    found = []
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))          # no packet is sent, it just picks a route
        found.append(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
        ip = info[4][0]
        if not ip.startswith("127.") and ip not in found:
            found.append(ip)
    return found


async def index_handler(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC / "index.html")


async def no_cache(_request: web.Request, response: web.StreamResponse):
    # Sin esto el navegador se quedaba con un jev.js viejo tras cambiar el código, y una
    # partida entera se jugó sin el margen de huida. Con no-cache revalida por ETag.
    response.headers["Cache-Control"] = "no-cache"


async def on_cleanup(app: web.Application):
    await app["jev"].close()
    if "teacher" in app:
        await app["teacher"].close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--host", default="127.0.0.1",
                    help="0.0.0.0 to reach the game from a phone on the same network")
    ap.add_argument("--brain", choices=("jev", "laya"), default="jev",
                    help="laya: the student distilled from jev, local on the GPU")
    ap.add_argument("--shadow", action="store_true",
                    help="with --brain laya: also ask jev every state, log only (DAgger labels)")
    args = ap.parse_args()

    app = web.Application()
    app["jev"] = LayaClient() if BRAIN == "laya" else JevClient(settings)
    if args.shadow and BRAIN == "laya":
        app["teacher"] = JevClient(settings)
    app.on_cleanup.append(on_cleanup)
    app.on_response_prepare.append(no_cache)
    app.router.add_get("/", index_handler)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/replays", replays_handler)
    app.router.add_get("/replay/{name}", replay_handler)
    app.router.add_static("/", STATIC, show_index=False, name="static")

    print(f"[pacman] brain: {'Laya student, local' if BRAIN == 'laya' else 'jev via ' + settings.provider}"
          + (" + jev labelling in the shadow" if "teacher" in app else ""))
    print(f"[pacman] http://127.0.0.1:{args.port}/")
    if args.host not in ("127.0.0.1", "localhost"):
        for ip in lan_addresses():
            print(f"[pacman] http://{ip}:{args.port}/   (same network)")
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
