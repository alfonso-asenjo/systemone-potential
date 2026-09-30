"""El humor de internet en directo: el flujo mundial de Bluesky, leído por Laya en tu GPU.

    .venv-laya/Scripts/python bluesky/server.py                 # flujo en directo
    .venv-laya/Scripts/python bluesky/server.py --replay spike/corpus-raw.jsonl   # sin red
    y abrir http://127.0.0.1:8790/

Laya es el alumno destilado de jev (bluesky/train.py): emoción, tema, toxicidad y contenido
adulto de cada post, en tandas de 8, a unos 100 ms por tanda.

Nunca sale del servidor quién escribió un post. El texto solo se envía al navegador si el
alumno lo ve limpio en los dos filtros (listones calibrados en train.py para recoger el 95 %
de lo que jev marca), el autor no lo etiquetó como adulto y no es solo un enlace; y se le
quitan menciones y enlaces. Todo lo demás llega como un punto de color, sin texto.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import re
import sys
import time
from pathlib import Path

from aiohttp import WSMsgType, web

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE / "spike"))
from questions import Q  # noqa: E402

JETSTREAM = "wss://jetstream2.us-east.bsky.network/subscribe?wantedCollections=app.bsky.feed.post"
MODEL = ROOT / "models" / "laya-bluesky"
STATIC = HERE / "static"
BATCH = 8
QUEUE_MAX = 400
WINDOW_S = 60
# El río de la pantalla: cubos de 3 s durante 5 minutos. El servidor guarda la historia para
# que un navegador que se conecta vea el río lleno desde el primer instante (medido: sin
# esto, al abrir la página el río era una franja de 25 s pegada al borde derecho).
BIN_S = 3
HISTORY_BINS = 100
# Lo que costaría el mismo trabajo con jev, medido al etiquetar 6.718 posts: 0,212 $.
JEV_COST_PER_POST = 0.212 / 6718
JEV_LATENCY_MS = 300
SELF_LABELS_HIDE = {"porn", "sexual", "nudity", "graphic-media", "gore"}
MENTION = re.compile(r"@[\w.\-]+")
LINK = re.compile(r"(https?://\S+|\b[\w\-]+(\.[\w\-]+)+/\S*)")


class Hub:
    def __init__(self, thresholds: dict):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)
        self.clients: set[web.WebSocketResponse] = set()
        self.toxic_min = thresholds["toxic_min"]
        self.adult_min = thresholds["adult_min"]
        self.started = time.time()
        self.received = self.classified = self.dropped = self.shown = 0
        self.arrivals: collections.deque = collections.deque()
        self.recent: collections.deque = collections.deque()   # (t, emotion, topic)
        self.batch_ms: collections.deque = collections.deque(maxlen=50)
        self.history: "collections.OrderedDict[int, collections.Counter]" = collections.OrderedDict()

    def add_to_history(self, now: float, emotion: str) -> None:
        idx = int(now // BIN_S)
        self.history.setdefault(idx, collections.Counter())[emotion] += 1
        while len(self.history) > HISTORY_BINS + 2:
            self.history.popitem(last=False)

    def history_payload(self) -> dict:
        return {"now_bin": int(time.time() // BIN_S), "bin_s": BIN_S,
                "bins": [[idx, dict(c)] for idx, c in self.history.items()]}

    def offer(self, post: dict) -> None:
        self.received += 1
        self.arrivals.append(time.time())
        if self.queue.full():   # mejor ir al día que ir con retraso
            self.queue.get_nowait()
            self.dropped += 1
        self.queue.put_nowait(post)

    def display_text(self, post: dict, ans: dict) -> str | None:
        if post["self_labels"] & SELF_LABELS_HIDE:
            return None
        if ans["toxic"]["probabilities"]["toxic"] >= self.toxic_min:
            return None
        if ans["adult"]["probabilities"]["adult"] >= self.adult_min:
            return None
        text = LINK.sub("", MENTION.sub("", post["text"])).strip()
        text = re.sub(r"\s+", " ", text)
        if len(text) < 12:
            return None
        return text[:160] + ("…" if len(text) > 160 else "")

    def stats(self) -> dict:
        now = time.time()
        while self.arrivals and now - self.arrivals[0] > 10:
            self.arrivals.popleft()
        while self.recent and now - self.recent[0][0] > WINDOW_S:
            self.recent.popleft()
        emo = collections.Counter(e for _, e, _ in self.recent)
        top = collections.Counter(t for _, _, t in self.recent)
        n = max(1, len(self.recent))
        ms = sorted(self.batch_ms)
        batch_ms = ms[len(ms) // 2] if ms else 0
        return {
            "posts_per_s": round(len(self.arrivals) / 10, 1),
            "classified": self.classified,
            "dropped": self.dropped,
            "shown": self.shown,
            "queue": self.queue.qsize(),
            "batch_ms": round(batch_ms, 1),
            "ms_per_decision": round(batch_ms / (BATCH * len(Q)), 2) if batch_ms else 0,
            "emotions": {k: round(emo[k] / n, 3) for k in Q["emotion"]["criteria"]},
            "topics": {k: round(top[k] / n, 3) for k in Q["topic"]["criteria"]},
            "jev_cost_usd": round(self.classified * JEV_COST_PER_POST, 4),
            "jev_hours_sequential": round(self.classified * len(Q) * JEV_LATENCY_MS / 3.6e6, 2),
            "uptime_s": round(now - self.started),
        }

    async def broadcast(self, msg: dict) -> None:
        dead = []
        for ws in self.clients:
            try:
                await ws.send_json(msg)
            except (ConnectionResetError, RuntimeError):
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


def parse_event(raw: str) -> dict | None:
    ev = json.loads(raw)
    c = ev.get("commit") or {}
    if ev.get("kind") != "commit" or c.get("operation") != "create":
        return None
    rec = c.get("record") or {}
    text = (rec.get("text") or "").strip()
    if not text:
        return None
    labels = {v.get("val") for v in ((rec.get("labels") or {}).get("values") or [])}
    return {"text": text, "lang": (rec.get("langs") or ["?"])[0].split("-")[0], "self_labels": labels}


async def read_live(hub: Hub, session) -> None:
    while True:   # Jetstream corta de vez en cuando: reconectar sin más
        try:
            async with session.ws_connect(JETSTREAM, heartbeat=20) as ws:
                print("[bluesky] conectado al flujo")
                async for msg in ws:
                    if msg.type != WSMsgType.TEXT:
                        continue
                    post = parse_event(msg.data)
                    if post:
                        hub.offer(post)
        except Exception as exc:  # noqa: BLE001
            print(f"[bluesky] flujo caído ({exc}); reconecto en 3 s")
        await asyncio.sleep(3)


async def read_replay(hub: Hub, path: Path) -> None:
    """Reproduce una captura de spike/capture.py a su ritmo original, en bucle."""
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    while True:
        t0 = time.time()
        for r in rows:
            delay = r["t"] - (time.time() - t0)
            if delay > 0:
                await asyncio.sleep(delay)
            hub.offer({"text": r["text"], "lang": r["lang"], "self_labels": set()})


async def classify(hub: Hub, agent) -> None:
    while True:
        posts = [await hub.queue.get()]
        while len(posts) < BATCH and not hub.queue.empty():
            posts.append(hub.queue.get_nowait())
        t0 = time.perf_counter()
        results = await asyncio.to_thread(agent.predict_batch, [p["text"] for p in posts], Q, batch_size=BATCH)
        hub.batch_ms.append((time.perf_counter() - t0) * 1000)
        now = time.time()
        out = []
        for p, r in zip(posts, results):
            a = r["answers"]
            emotion, topic = a["emotion"]["choice"], a["topic"]["choice"]
            text = hub.display_text(p, a)
            hub.shown += text is not None
            hub.recent.append((now, emotion, topic))
            hub.add_to_history(now, emotion)
            out.append({"emotion": emotion, "emotion_p": a["emotion"]["probabilities"][emotion],
                        "topic": topic, "lang": p["lang"], "text": text})
        hub.classified += len(posts)
        if hub.clients:
            await hub.broadcast({"type": "batch", "posts": out, "stats": hub.stats()})


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    hub: Hub = request.app["hub"]
    hub.clients.add(ws)
    await ws.send_json({"type": "hello", "stats": hub.stats(), "history": hub.history_payload(),
                        "emotions": list(Q["emotion"]["criteria"]), "topics": list(Q["topic"]["criteria"])})
    async for _ in ws:
        pass
    hub.clients.discard(ws)
    return ws


async def index(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC / "index.html")


async def no_cache(_request: web.Request, response: web.StreamResponse):
    response.headers["Cache-Control"] = "no-cache"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--replay", help="captura de spike/capture.py, relativa a bluesky/")
    args = ap.parse_args()

    import laya
    agent = laya.load(str(MODEL), device="cuda")
    thresholds = agent.cfg["bluesky"]
    print(f"[bluesky] {MODEL.name}: listón tóxico {thresholds['toxic_min']}, adulto {thresholds['adult_min']}")
    hub = Hub(thresholds)

    app = web.Application()
    app["hub"] = hub

    async def start(app):
        import aiohttp
        app["session"] = aiohttp.ClientSession()
        source = read_replay(hub, HERE / args.replay) if args.replay else read_live(hub, app["session"])
        app["tasks"] = [asyncio.create_task(source), asyncio.create_task(classify(hub, agent))]

    async def stop(app):
        for t in app["tasks"]:
            t.cancel()
        await app["session"].close()

    app.on_startup.append(start)
    app.on_cleanup.append(stop)
    app.on_response_prepare.append(no_cache)
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    STATIC.mkdir(exist_ok=True)
    app.router.add_static("/", STATIC, show_index=False)
    print(f"[bluesky] http://{args.host}:{args.port}/")
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
