"""jev etiqueta los posts capturados: es el profesor del que aprende Laya.

    python bluesky/label.py spike/corpus-raw.jsonl data/labels.jsonl
Guarda, por post, el texto, el idioma y las probabilidades de jev en cada pregunta.
"""
import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE / "spike"))
from jevcraft.config import settings  # noqa: E402
from jevcraft.jev_client import JevClient, JevError  # noqa: E402
from questions import Q  # noqa: E402

CONCURRENCY = 12


async def main(src: Path, dst: Path):
    rows, seen = [], set()
    for line in src.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["text"] not in seen:
            seen.add(r["text"])
            rows.append(r)
    dst.parent.mkdir(parents=True, exist_ok=True)
    sem, done, failed = asyncio.Semaphore(CONCURRENCY), 0, 0
    out = dst.open("w", encoding="utf-8")
    async with JevClient(settings) as c:
        async def one(r):
            nonlocal done, failed
            async with sem:
                for attempt in range(3):
                    try:
                        resp = await c.decide(r["text"], Q)
                        break
                    except (JevError, asyncio.TimeoutError, OSError):
                        await asyncio.sleep(1 + attempt)
                else:
                    failed += 1
                    return
            probs = {q: resp.answers[q]["probabilities"] for q in Q}
            out.write(json.dumps({"lang": r["lang"], "text": r["text"], "jev": probs}, ensure_ascii=False) + "\n")
            done += 1
            if done % 500 == 0:
                print(f"  {done}/{len(rows)}  {c.total_cost:.3f} $", flush=True)
        await asyncio.gather(*[one(r) for r in rows])
        print(f"{done} etiquetados, {failed} fallidos, coste {c.total_cost:.3f} $")
    out.close()


if __name__ == "__main__":
    asyncio.run(main(HERE / sys.argv[1], HERE / sys.argv[2]))
