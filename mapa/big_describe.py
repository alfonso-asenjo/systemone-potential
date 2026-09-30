"""El profesor (gpt-6-luna) escribe los rasgos de cada municipio a partir de su Wikipedia.

Solo con lo que dice la fuente: un modelo pequeño que escribe de memoria sobre un pueblo de
300 habitantes inventa. Si la introducción no dice nada que distinga al pueblo, se pide que
lo diga ("sin rasgos destacados") en vez de rellenar.

    python mapa/big_describe.py --sample 8        # prueba: imprime, mide tokens y coste
    python mapa/big_describe.py                   # todos -> data/big/rasgos.jsonl (continúa)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from pathlib import Path

import aiohttp

HERE = Path(__file__).resolve().parent
BIG = HERE / "data" / "big"
MODEL = "gpt-6-luna"
PRICE_IN, PRICE_OUT = 0.10 / 1e6, 0.50 / 1e6      # verificado el 24-09-2026, sin lotes
CONCURRENCY = 8

INSTRUCTIONS = """Eres redactor de un buscador de destinos en España. Te doy la introducción de Wikipedia de un municipio.
Escribe en castellano una lista corta de rasgos que lo distingan para alguien que busca adónde ir:
paisaje (costa, montaña, río, llanura), patrimonio, fiestas, gastronomía, ambiente, actividades.
Reglas:
- Solo lo que diga el texto. No añadas nada que no esté en él.
- Entre 4 y 8 rasgos, separados por comas, sin frases largas. Máximo 25 palabras.
- Nada de población, superficie, gentilicio ni distancias: eso ya lo sabemos.
- Si el texto no dice nada que lo distinga, responde exactamente: sin rasgos destacados
Responde solo con la lista."""


def key() -> str:
    for line in (HERE.parent / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENAI_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("falta OPENAI_API_KEY en .env")


async def describe(session, sem, m, extract, effort):
    body = {"model": MODEL, "instructions": INSTRUCTIONS, "max_output_tokens": 600,
            "input": f"Municipio: {m['name']}\n\n{extract}"}
    if effort:
        body["reasoning"] = {"effort": effort}
    async with sem:
        for attempt in range(4):
            async with session.post("https://api.openai.com/v1/responses", json=body) as r:
                d = await r.json()
                if r.status == 200:
                    break
                if r.status in (429, 500, 502, 503):
                    await asyncio.sleep(2 * (attempt + 1)); continue
                raise RuntimeError(f"HTTP {r.status}: {d.get('error', {}).get('message', '')[:200]}")
    text = "".join(c.get("text", "") for o in d.get("output", []) for c in (o.get("content") or [])
                   if c.get("type") == "output_text").strip()
    u = d.get("usage", {})
    return {"ine": m["ine"], "name": m["name"], "rasgos": text, "in": u.get("input_tokens", 0),
            "out": u.get("output_tokens", 0), "reasoning": (u.get("output_tokens_details") or {}).get("reasoning_tokens", 0)}


async def main(args):
    mun = {m["ine"]: m for m in json.loads((BIG / "municipios.json").read_text(encoding="utf-8"))}
    # Artículo completo recortado a lo útil (big_wiki_full.py): con la introducción sola, 5 de
    # cada 8 pueblos salían "sin rasgos destacados".
    wiki = {}
    for line in (BIG / "wiki_full.jsonl").read_text(encoding="utf-8").splitlines():
        w = json.loads(line); wiki[w["ine"]] = w["text"]
    out_path = BIG / "rasgos.jsonl"
    done = set()
    if out_path.exists() and not args.sample:
        done = {json.loads(l)["ine"] for l in out_path.read_text(encoding="utf-8").splitlines() if l.strip()}
    todo = sorted(i for i in wiki if i not in done)
    if args.sample:   # misma muestra en cada prueba, para comparar variantes con los mismos pueblos
        random.Random(1).shuffle(todo); todo = todo[:args.sample]
    sem = asyncio.Semaphore(CONCURRENCY)
    headers = {"Authorization": f"Bearer {key()}", "Content-Type": "application/json"}
    t0 = time.time()
    async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as s:
        res = await asyncio.gather(*[describe(s, sem, mun[i], wiki[i], args.effort) for i in todo], return_exceptions=True)
    ok = [r for r in res if isinstance(r, dict)]
    errs = [r for r in res if not isinstance(r, dict)]
    tin, tout, treas = sum(r["in"] for r in ok), sum(r["out"] for r in ok), sum(r["reasoning"] for r in ok)
    cost = tin * PRICE_IN + tout * PRICE_OUT
    if args.sample:
        for r in ok:
            print(f"- {r['name']} (pob. {mun[r['ine']]['pop']}): {r['rasgos']}   [{r['out']} salida, {r['reasoning']} razonando]")
    else:
        with out_path.open("a", encoding="utf-8") as f:
            for r in ok:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n = max(1, len(ok))
    print(f"\n{len(ok)} hechos, {len(errs)} errores en {time.time() - t0:.0f} s. Por municipio: {tin / n:.0f} entrada, "
          f"{tout / n:.0f} salida ({treas / n:.0f} razonando). Coste {cost:.4f} $ -> {cost / n * 8131:.2f} $ para 8.131 sin lotes")
    for e in errs[:3]:
        print("error:", e)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--effort", default="none", help="esfuerzo de razonamiento; '' para el del modelo")
    asyncio.run(main(ap.parse_args()))
