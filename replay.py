"""Replay a recorded game's decisions on the dashboard, with the original timing.

    python replay.py logs/sc2-20260922-130000.jsonl [--speed 2] [--port 8765]

Useful to publish the dashboard without spending API calls, or to re-record the panel.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from jevcraft.dashboard import Dashboard


async def main(path: Path, speed: float, port: int):
    records = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    dash = Dashboard(port)
    await dash.start()
    print(f"[replay] {len(records)} records. Open the dashboard, replay starts in 5 s.")
    await asyncio.sleep(5)
    prev_t = records[0]["t"] if records else 0
    for rec in records:
        await asyncio.sleep(max(0.0, (rec["t"] - prev_t) / speed))
        prev_t = rec["t"]
        await dash.broadcast(rec)
    await dash.broadcast({"type": "end", "result": "replay finished"})
    await asyncio.sleep(3600)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("log", type=Path)
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--port", type=int, default=8765)
    a = p.parse_args()
    asyncio.run(main(a.log, a.speed, a.port))
