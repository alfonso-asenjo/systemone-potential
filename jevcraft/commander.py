"""The commander: asks jev what to do, applies confidence gating, records everything."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from .config import Settings, settings as default_settings
from .jev_client import JevClient, JevError, JevResponse
from .questions import COMMANDER_QUESTIONS, LABELS

Broadcast = Callable[[dict[str, Any]], Awaitable[None] | None]


@dataclass
class Decision:
    macro_focus: str = "workers"
    army_stance: str = "defend"
    threat: float = 0.0
    enemy_rushing: float = 0.0
    ahead: float = 0.5
    confidence: dict[str, float] = field(default_factory=dict)
    fallback: list[str] = field(default_factory=list)   # questions where confidence gating kept the old answer
    held: list[str] = field(default_factory=list)       # questions where hysteresis kept the old answer
    seq: int = 0

    def short(self) -> dict[str, Any]:
        return {"macro_focus": self.macro_focus, "army_stance": self.army_stance, "threat": round(self.threat, 1)}


class Commander:
    def __init__(self, cfg: Settings = default_settings, broadcast: Broadcast | None = None, enabled: bool = True):
        self.cfg = cfg
        self.client = JevClient(cfg)
        self.enabled = enabled
        self.broadcast = broadcast
        self.decision = Decision()
        self.last_call_at = 0.0
        self.task: asyncio.Task | None = None
        self.errors = 0
        self.last_error = ""
        self.history: list[dict[str, Any]] = []
        self._log_file = None
        self.on_change: Callable[[Decision, Decision], Awaitable[None] | None] | None = None

    async def start(self, log_name: str = "game"):
        await self.client.start()
        self.cfg.log_dir.mkdir(exist_ok=True)
        path = self.cfg.log_dir / f"{log_name}-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
        self._log_file = open(path, "a", encoding="utf-8")
        self.log_path = path

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
        await self.client.close()
        if self._log_file:
            self._log_file.close()

    # -- loop entry, called from bot.on_step -------------------------------
    def maybe_tick(self, state: dict[str, Any], game_time: float):
        if not self.enabled:
            return
        now = time.monotonic()
        if self.task and not self.task.done():
            return
        if now - self.last_call_at < self.cfg.decision_interval:
            return
        self.last_call_at = now
        self.task = asyncio.create_task(self._ask(state, game_time))

    async def _ask(self, state: dict[str, Any], game_time: float):
        try:
            resp = await self.client.decide(state, COMMANDER_QUESTIONS)
        except (JevError, asyncio.TimeoutError, OSError) as exc:
            self.errors += 1
            self.last_error = str(exc)[:300]
            await self._emit({"type": "error", "message": self.last_error, "errors": self.errors})
            return
        prev = self.decision
        new = self._interpret(resp, prev)
        self.decision = new
        record = {
            "type": "decision",
            "seq": new.seq,
            "t": time.time(),
            "game_time": game_time,
            "latency_ms": round(resp.latency_ms),
            "model": resp.model,
            "usage": {"input_tokens": resp.input_tokens, "cost_usd": resp.cost_usd},
            "totals": {"calls": self.client.total_calls, "cost_usd": round(self.client.total_cost, 5),
                       "errors": self.errors},
            "decision": asdict(new),
            "answers": resp.answers,
            "labels": LABELS,
            "state": state,
        }
        self.record(record)
        await self._emit(record)
        if self.on_change and (new.macro_focus != prev.macro_focus or new.army_stance != prev.army_stance):
            r = self.on_change(prev, new)
            if asyncio.iscoroutine(r):
                await r

    def record(self, record: dict[str, Any]):
        self.history.append(record)
        if self._log_file:
            self._log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._log_file.flush()

    def _interpret(self, resp: JevResponse, prev: Decision) -> Decision:
        a = resp.answers
        d = Decision(seq=prev.seq + 1)
        d.confidence = {}
        for key in ("macro_focus", "army_stance"):
            ans = a.get(key, {})
            conf = float(ans.get("confidence", 0.0))
            d.confidence[key] = conf
            choice = ans.get("choice")
            probs = ans.get("probabilities") or {}
            current = getattr(prev, key)
            if not choice or conf < self.cfg.confidence_min:
                setattr(d, key, current)
                d.fallback.append(key)
            elif choice != current and probs.get(choice, 1.0) < probs.get(current, 0.0) + self.cfg.switch_margin:
                # near tie with the current decision: keep it, avoids flicker every call
                setattr(d, key, current)
                d.held.append(key)
            else:
                setattr(d, key, choice)
        threat = a.get("threat", {})
        d.threat = float(threat.get("score", prev.threat))
        d.confidence["threat"] = float(threat.get("confidence", 0.0))
        d.enemy_rushing = float(a.get("enemy_rushing", {}).get("noul", prev.enemy_rushing))
        d.ahead = float(a.get("ahead", {}).get("noul", prev.ahead))
        return d

    async def _emit(self, msg: dict[str, Any]):
        if self.broadcast:
            r = self.broadcast(msg)
            if asyncio.iscoroutine(r):
                await r
