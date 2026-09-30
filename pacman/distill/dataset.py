"""Convierte los logs de partidas con jev en ejemplos para enseñar a Laya.

Cada decisión registrada trae el estado completo y las probabilidades que dio jev. El
objetivo del alumno son esas probabilidades, no solo la opción ganadora: así aprende
también cuánta seguridad tenía el profesor.

Uso: python pacman/distill/dataset.py  ->  pacman/distill/data/{train,test}.jsonl
Las partidas se reparten enteras entre train y test, para que el examen sea con partidas
que el alumno no ha visto.
"""
from __future__ import annotations

import glob
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from compact import ORDER, questions  # noqa: E402

LOGS = os.path.join(HERE, "..", "logs")
OUT = os.path.join(HERE, "data")
TEST_SHARE = 0.2


def targets(answers: dict, qs: dict) -> dict[str, list[float]]:
    out = {}
    for qid, q in qs.items():
        a = answers.get(qid)
        if not a:
            continue
        if q["type"] == "choice":
            p = [float(a.get("probabilities", {}).get(d, 0.0)) for d in q["criteria"]]
        elif q["type"] == "score":
            p = [float(a.get("probabilities", {}).get(str(i), 0.0)) for i in range(len(q["criteria"]))]
        else:
            y = float(a["noul"])
            p = [1.0 - y, y]
        s = sum(p)
        if s > 0:
            out[qid] = [x / s for x in p]
    return out


def main() -> None:
    games: dict[str, list[dict]] = {}
    broken = 0
    for path in sorted(glob.glob(os.path.join(LOGS, "*.jsonl"))):
        game = os.path.basename(path)
        seen = set()
        for line in open(path, encoding="utf-8"):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                broken += 1
                continue
            # "teacher": respuestas de jev a estados a los que llegó Laya jugando (DAgger).
            if rec.get("type") not in ("decision", "teacher") or rec.get("decision", {}).get("fallback"):
                continue
            if not str(rec.get("model", "")).startswith("typesafe/"):
                continue  # solo aprende del profesor, nunca de sus propias partidas
            state, exits = rec.get("state"), rec.get("exits") or []
            if not state:
                continue
            key = json.dumps(state, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            qs = questions(exits, state)
            t = targets(rec.get("answers", {}), qs)
            if t:
                games.setdefault(game, []).append(
                    {"game": game, "seq": rec.get("seq"), "exits": [d for d in ORDER if d in exits],
                     "state": state, "targets": t})

    names = sorted(games)
    fixed = os.path.join(OUT, "test_games.txt")
    if os.path.exists(fixed):
        # El examen no cambia entre versiones del alumno: las partidas nuevas del profesor
        # van todas a entrenamiento, y así v2 y v3 se comparan sobre las mismas 9 partidas.
        test = [g for g in open(fixed).read().split() if g in games]
        split = {"test": test, "train": [g for g in names if g not in test]}
    else:
        random.Random(7).shuffle(names)
        n_test = max(1, round(len(names) * TEST_SHARE))
        split = {"test": names[:n_test], "train": names[n_test:]}
    os.makedirs(OUT, exist_ok=True)
    for part, gs in split.items():
        rows = [r for g in gs for r in games[g]]
        with open(os.path.join(OUT, f"{part}.jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        per_q: dict[str, int] = {}
        for r in rows:
            for q in r["targets"]:
                per_q[q] = per_q.get(q, 0) + 1
        print(f"{part}: {len(gs)} partidas, {len(rows)} decisiones, {per_q}")
    print(f"líneas rotas: {broken}")


if __name__ == "__main__":
    main()
