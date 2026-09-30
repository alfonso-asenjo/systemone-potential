"""Print the moments worth clipping from a recorded game: stance changes, threat spikes, fights.

    python highlights.py logs/sc2-XXXX.jsonl
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

recs = [json.loads(l) for l in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if l.strip()]
prev = None
for r in recs:
    d, s = r["decision"], r["state"]
    threat = d["threat"]
    lost, killed = s["last_30s"]["our_units_lost"], s["last_30s"]["enemy_units_killed"]
    key = (d["army_stance"], round(threat))
    notes = []
    if prev and d["army_stance"] != prev[0]:
        notes.append(f"army -> {d['army_stance'].upper()} ({d['confidence'].get('army_stance', 0):.0%})")
    if prev and round(threat) > prev[1]:
        notes.append(f"threat up to {threat:.1f}")
    if lost + killed >= 8:
        notes.append(f"fight: lost {lost}, killed {killed}")
    if notes:
        enemy = s["enemy"]["units_visible"]
        print(f"{s['game_time']:>6}  {' | '.join(notes):<50} ahead={d['ahead']:.0%}  enemy={enemy}")
    prev = key
