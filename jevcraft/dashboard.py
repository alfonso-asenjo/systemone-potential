"""Tiny aiohttp server: serves the dashboard page and pushes JSON over a WebSocket."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

HERE = Path(__file__).resolve().parent / "dashboard"


class Dashboard:
    def __init__(self, port: int = 8765):
        self.port = port
        self.clients: set[web.WebSocketResponse] = set()
        self.last: dict[str, Any] | None = None
        self.app = web.Application()
        self.app.router.add_get("/", self._index)
        self.app.router.add_get("/ws", self._ws)
        self.app.router.add_static("/static", HERE)
        self.runner: web.AppRunner | None = None

    async def start(self):
        self.runner = web.AppRunner(self.app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", self.port)
        await site.start()
        print(f"[dashboard] http://127.0.0.1:{self.port}/")

    async def stop(self):
        for ws in list(self.clients):
            await ws.close()
        if self.runner:
            await self.runner.cleanup()

    async def broadcast(self, msg: dict[str, Any]):
        if msg.get("type") == "decision":
            self.last = msg
        data = json.dumps(msg, ensure_ascii=False)
        dead = []
        for ws in self.clients:
            try:
                await ws.send_str(data)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def _index(self, _req):
        return web.FileResponse(HERE / "index.html")

    async def _ws(self, req):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(req)
        self.clients.add(ws)
        if self.last:
            await ws.send_str(json.dumps(self.last, ensure_ascii=False))
        try:
            async for msg in ws:
                if msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                    break
        finally:
            self.clients.discard(ws)
        return ws
