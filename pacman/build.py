"""Bundle one recorded game into a standalone site that needs no server and no API key.

    python build.py                       # newest recording
    python build.py logs/pacman-XXXX.jsonl
    python build.py --serve               # build, then serve dist/ on 8771 to check it

The result in dist/ is plain static files: open index.html and the recorded game plays
back exactly as it happened, decision by decision, costing nothing.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
LOGS = ROOT / "logs"
DIST = ROOT / "dist"

# Only what the replay and the panel actually need. The rest of the record stays in logs/.
KEEP = ("seq", "recv_tick", "latency_ms", "decision", "answers", "state", "score_at_recv")


def newest_log() -> Path | None:
    logs = sorted(LOGS.glob("pacman-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in logs:                       # skip recordings with nothing in them
        if sum(1 for line in path.read_text(encoding="utf-8").splitlines()
               if '"type": "decision"' in line) > 20:
            return path
    return logs[0] if logs else None


def bundle(log: Path) -> dict:
    seed, played, brain, models, decisions = 0, None, None, set(), []
    for line in log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:          # una línea a medio escribir si el servidor se cortó
            continue
        if rec.get("type") == "header":
            seed = rec.get("seed", 0)
            played = rec.get("started")
            brain = rec.get("brain")
        elif rec.get("type") == "decision" and rec.get("recv_tick") is not None:
            models.add(str(rec.get("model", "")))
            decisions.append({k: rec[k] for k in KEEP if k in rec} | {"type": "decision"})
    decisions.sort(key=lambda d: d["recv_tick"])
    # las grabaciones anteriores al 24 de septiembre no apuntan el cerebro en la cabecera
    brain = brain or ("laya" if any("laya" in m for m in models) else "jev")
    return {"seed": seed, "played": played, "brain": brain, "source": log.name, "decisions": decisions}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log", nargs="?", type=Path)
    ap.add_argument("--serve", action="store_true", help="serve dist/ afterwards to check it")
    ap.add_argument("--port", type=int, default=8771)
    args = ap.parse_args()

    log = args.log or newest_log()
    if not log or not log.exists():
        raise SystemExit("no recordings in logs/: play a game with the server running first")

    data = bundle(log)
    if not data["decisions"]:
        raise SystemExit(f"{log.name} has no applied decisions to replay")

    if DIST.exists():
        shutil.rmtree(DIST)
    shutil.copytree(STATIC, DIST, ignore=shutil.ignore_patterns("package.json"))

    (DIST / "replay.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")

    index = (DIST / "index.html").read_text(encoding="utf-8")
    index = index.replace(
        '<script type="module" src="main.js"></script>',
        '<script>window.__BUNDLED_REPLAY = "replay.json";</script>\n'
        '<script type="module" src="main.js"></script>',
    )
    (DIST / "index.html").write_text(index, encoding="utf-8")

    size = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file())
    last = data["decisions"][-1]
    print(f"dist/ built from {log.name}")
    print(f"  {len(data['decisions'])} decisions, {last['recv_tick'] / 60:.0f} s of play, "
          f"{last.get('score_at_recv')} points")
    print(f"  {size / 1024:.0f} kB total, replay.json is "
          f"{(DIST / 'replay.json').stat().st_size / 1024:.0f} kB")

    if args.serve:
        import functools
        import http.server
        import socketserver
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DIST))
        with socketserver.TCPServer(("127.0.0.1", args.port), handler) as httpd:
            print(f"  serving http://127.0.0.1:{args.port}/  (ctrl-c to stop)")
            httpd.serve_forever()


if __name__ == "__main__":
    main()
