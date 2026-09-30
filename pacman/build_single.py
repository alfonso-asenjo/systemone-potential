"""Bake the whole demo into one HTML file with no external anything.

    python build_single.py                       # newest recording
    python build_single.py logs/pacman-XXXX.jsonl --out dist-single/roja.html

Why: some hosts embed the page inside their own and block fetches and scripts from
outside its origin. A single file with the maze, the flags and the recorded
game inlined does not need any of that, and works just as well opened from disk.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path

from build import bundle, newest_log

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"

# Dependency order: each module may only use names defined above it.
MODULES = ["maze.js", "ghosts.js", "game.js", "render.js", "jev.js", "panel.js", "main.js"]
FLAGS = ["es", "uy", "at", "sa", "cv", "ar", "fr", "be", "pt"]


def flatten(js: str) -> str:
    """Turn an ES module into plain script: drop the imports, keep the declarations."""
    js = re.sub(r"^\s*import\s+[^;]+;\s*$", "", js, flags=re.MULTILINE)
    js = re.sub(r"^\s*export\s*\{[^}]*\}\s*;\s*$", "", js, flags=re.MULTILINE)
    js = re.sub(r"^(\s*)export\s+", r"\1", js, flags=re.MULTILINE)
    return js


def data_uri(path: Path) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log", nargs="?", type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "dist-single" / "roja.html")
    ap.add_argument("--body-only", action="store_true",
                    help="leave out the html/head/body wrapper, for hosts that add their own")
    args = ap.parse_args()

    log = args.log or newest_log()
    if not log or not log.exists():
        raise SystemExit("no recordings in logs/: play a game with the server running first")
    replay = bundle(log)
    if not replay["decisions"]:
        raise SystemExit(f"{log.name} has no applied decisions to replay")

    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    maze = (STATIC / "maze.txt").read_text(encoding="utf-8")
    flags = {code: data_uri(STATIC / "flags" / f"{code}.svg") for code in FLAGS}
    script = "\n".join(flatten((STATIC / m).read_text(encoding="utf-8")) for m in MODULES)

    # Keep only what sits inside <body>, then rebuild the page around it.
    body = html.split("<body>", 1)[1].split("</body>", 1)[0]
    body = re.sub(r'<script type="module"[^>]*></script>', "", body)
    body = body.replace('src="flags/es.svg"', f'src="{flags["es"]}"')

    title = re.search(r"<title>(.*?)</title>", html).group(1)
    description = re.search(r'name="description" content="(.*?)"', html).group(1)
    if replay.get("brain") == "laya":      # la descripción también dice quién juega
        description = description.replace("es jev, un modelo de decisión de TypeSafe",
                                          "es Laya, un modelo abierto entrenado con las decisiones de jev")
    fonts = re.search(r'<link href="(https://fonts\.googleapis\.com[^"]+)"', html).group(1)

    head = f"""<title>{title}</title>
<meta name="description" content="{description}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{fonts}" rel="stylesheet">
<style>
{css}
</style>"""

    data = f"""<script>
window.__MAZE_TEXT = {json.dumps(maze)};
window.__FLAGS = {json.dumps(flags)};
window.__REPLAY_DATA = {json.dumps(replay, separators=(",", ":"))};
window.__BUNDLED_REPLAY = "inline";
</script>"""

    page = f"{head}\n{body}\n{data}\n<script>\n{script}\n</script>"
    if not args.body_only:
        page = ('<!doctype html>\n<html lang="es">\n<head>\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                f"{head}\n</head>\n<body>\n{body}\n{data}\n<script>\n{script}\n</script>\n</body>\n</html>\n")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page, encoding="utf-8")

    last = replay["decisions"][-1]
    print(f"{args.out} built from {log.name}")
    print(f"  {len(replay['decisions'])} decisions, {last['recv_tick'] / 60:.0f} s of play, "
          f"{last.get('score_at_recv')} points")
    print(f"  {args.out.stat().st_size / 1024:.0f} kB, one file, nothing to fetch")


if __name__ == "__main__":
    main()
