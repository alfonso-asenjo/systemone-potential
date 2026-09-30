"""Call jev with a recorded game state, without launching StarCraft.

    python offline_test.py                          # uses fixtures/state_sample.json
    python offline_test.py fixtures/other.json
    python offline_test.py logs/sc2-XXXX.jsonl      # re-asks jev on every state of a recorded game
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from jevcraft.jev_client import JevClient
from jevcraft.questions import COMMANDER_QUESTIONS, LABELS


def show(resp):
    print(f"  model={resp.model}  latency={resp.latency_ms:.0f} ms  tokens_in={resp.input_tokens}  cost=${resp.cost_usd:.6f}")
    for key, ans in resp.answers.items():
        label = LABELS.get(key, key)
        t = ans.get("type")
        if t == "choice":
            probs = "  ".join(f"{k}={v:.2f}" for k, v in sorted(ans["probabilities"].items(), key=lambda kv: -kv[1]))
            print(f"  {label:14} -> {ans['choice']:<11} conf={ans.get('confidence', 0):.2f}   [{probs}]")
        elif t == "score":
            print(f"  {label:14} -> {ans['score']:.2f}        conf={ans.get('confidence', 0):.2f}")
        elif t == "noul":
            print(f"  {label:14} -> {ans['noul']:.2f}")


async def main(path: Path):
    if path.suffix == ".jsonl":
        states = [json.loads(line)["state"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        states = [json.loads(path.read_text(encoding="utf-8"))]
    async with JevClient() as client:
        for i, state in enumerate(states):
            print(f"\n=== state {i + 1}/{len(states)}  game_time={state.get('game_time')} ===")
            resp = await client.decide(state, COMMANDER_QUESTIONS)
            show(resp)
        print(f"\ntotal: {client.total_calls} calls, ${client.total_cost:.5f}, provider={client.provider}")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("fixtures/state_sample.json")
    asyncio.run(main(target))
