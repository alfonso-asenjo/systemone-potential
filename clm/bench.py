"""CLM-8B sin entrenar frente a lo que ya medimos con jev y Laya, con los mismos exámenes.

- Comecocos: las decisiones en cruces del examen fijo (pacman/distill/data/test.jsonl), con el estado
  y la pregunta exactamente como se los mandábamos a jev (pacman/questions.py). Se mide cuántas veces
  elige la misma salida que jev. Laya sin entrenar: 48 %; Laya v4 destilada: 92,3 %.
- Bluesky: los 600 posts del examen, con las mismas preguntas que respondió jev (emoción y tema).
  Laya sin entrenar: 48,5 % / 38,8 %; destilada: 65,2 % / 65,5 %.

    .venv-laya/Scripts/python -m clm.bench [--pacman N] [--bluesky N]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pacman"))
sys.path.insert(0, str(ROOT / "pacman" / "distill"))


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(p * len(xs)))], 1) if xs else None


def pacman(clm, n):
    from compact import questions as compact_questions
    from questions import build
    rows = [json.loads(l) for l in open(ROOT / "pacman" / "distill" / "data" / "test.jsonl", encoding="utf-8")]
    rows = [r for r in rows if "direction" in r["targets"]][:n or None]
    hit = sure_hit = sure_n = risky_hit = risky_n = 0
    ms = []
    for r in rows:
        keys = list(compact_questions(r["exits"], r["state"])["direction"]["criteria"])
        teacher = keys[int(np.argmax(r["targets"]["direction"]))]
        q = build(r["exits"], r["state"])["direction"]
        out = clm.answer(r["state"], {"direction": q})
        ms.append(out["latency_ms"])
        ok = out["answers"]["direction"]["choice"] == teacher
        hit += ok
        if max(r["targets"]["direction"]) >= 0.6:
            sure_hit += ok; sure_n += 1
        near = [v.get("nearest_ghost") for v in r["state"].get("by_exit", {}).values()]
        if min([g for g in near if g is not None] or [99]) <= 4:
            risky_hit += ok; risky_n += 1
    return {"cruces": len(rows), "coincide_con_jev": round(hit / len(rows), 3),
            "coincide_cuando_jev_seguro": round(sure_hit / max(1, sure_n), 3),
            "coincide_con_rival_cerca": round(risky_hit / max(1, risky_n), 3), "n_rival_cerca": risky_n,
            "ms_p50": pct(ms, .5), "ms_p90": pct(ms, .9)}


def bluesky(clm, n):
    import importlib.util   # hay dos questions.py (comecocos y Bluesky): este se carga por ruta
    spec = importlib.util.spec_from_file_location("bluesky_questions", ROOT / "bluesky" / "spike" / "questions.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    Q = mod.Q
    rows = [json.loads(l) for l in open(ROOT / "bluesky" / "data" / "labels.jsonl", encoding="utf-8")][:n or 600]
    qs = {k: Q[k] for k in ("emotion", "topic")}
    agree = {k: 0 for k in qs}
    ms = []
    for r in rows:
        out = clm.answer(r["text"], qs)
        ms.append(out["latency_ms"])
        for k in qs:
            jev = max(r["jev"][k], key=r["jev"][k].get)
            agree[k] += out["answers"][k]["choice"] == jev
    return {"posts": len(rows), **{f"{k}_coincide_con_jev": round(v / len(rows), 3) for k, v in agree.items()},
            "ms_p50_por_post": pct(ms, .5), "ms_p90_por_post": pct(ms, .9)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pacman", type=int, default=0, help="0 = todo el examen")
    ap.add_argument("--bluesky", type=int, default=600)
    ap.add_argument("--skip", nargs="*", default=[])
    a = ap.parse_args()
    import torch
    from clm.local import CLM
    t0 = time.time()
    clm = CLM()
    rep = {"carga_s": round(time.time() - t0), "vram_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2)}
    print(json.dumps(rep), flush=True)
    # calentar
    clm.answer("warm up", {"q": {"type": "noul", "instructions": "Is this a test?"}})
    if "pacman" not in a.skip:
        rep["comecocos"] = pacman(clm, a.pacman); print(json.dumps(rep["comecocos"], ensure_ascii=False), flush=True)
    if "bluesky" not in a.skip:
        rep["bluesky"] = bluesky(clm, a.bluesky); print(json.dumps(rep["bluesky"], ensure_ascii=False), flush=True)
    rep["vectores_no_finitos"] = clm.nan
    rep["vram_max_gb"] = round(torch.cuda.max_memory_allocated() / 2**30, 2)
    out = ROOT / "clm" / "report.json"
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
