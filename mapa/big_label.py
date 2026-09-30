"""El profesor etiqueta: para cada frase, qué municipios de entre los candidatos son buenas respuestas.

Candidatos: los 50 mejores del buscador de palabras (BM25 de review.py). El profesor los
puntúa de 1 a 3 (hasta 15) con salida estructurada, sin texto que interpretar.

    python mapa/big_label.py --pilot [--effort none]   # tus frases del examen: mide contra tus marcas
    python mapa/big_label.py --n 5000                   # todas -> data/big/etiquetas.jsonl (continúa)

Métricas del piloto, solo sobre lo que la persona llegó a juzgar (vio 30 candidatos y buscó
otros; los puestos 31-50 que no vio no cuentan como fallo del profesor):
  buscador: qué parte de lo que marcó la persona está entre los 50 candidatos
  acierto@5: de los 5 primeros del profesor que la persona juzgó, cuántos marcó
  cobertura: de lo que marcó la persona y estaba entre los candidatos, cuánto eligió el profesor
Se comparan con el propio orden del buscador, que es lo que habría sin profesor.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import aiohttp

from review import BM25, doc_text, tokens

HERE = Path(__file__).resolve().parent
BIG = HERE / "data" / "big"
MODEL = "gpt-6-luna"
PRICE_IN, PRICE_OUT = 0.10 / 1e6, 0.50 / 1e6
N_CAND = 50
CONCURRENCY = 8

INSTRUCTIONS = """Eres el motor de un mapa de España que encuentra municipios a partir de lo que alguien busca.
Te doy una búsqueda y una lista de municipios candidatos con sus datos y rasgos.
Elige los que de verdad encajan con la búsqueda (hasta 15) y puntúa cada uno:
3 = encaja muy bien con casi todo lo que pide, 2 = encaja bien, 1 = encaja en parte.
No incluyas los que no encajan. Si la búsqueda pide cerca de Madrid, horas o sin avión, respétalo con los datos.
Usa solo los datos dados; no inventes rasgos."""

SCHEMA = {"type": "json_schema", "name": "ranking", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["elegidos"],
    "properties": {"elegidos": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "nota"],
        "properties": {"id": {"type": "string"}, "nota": {"type": "integer", "enum": [1, 2, 3]}}}}}}}


def key() -> str:
    for line in (HERE.parent / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENAI_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("falta OPENAI_API_KEY en .env")


def describe(l: dict) -> str:
    where = {"island": "isla (avión o barco)", "africa": "norte de África (barco o avión)"}.get(
        l["reach"], f"{l['hours']} h en coche desde Madrid")
    coast = "costero" if l["costero"] else f"costa a {l['coast_km']:.0f} km"
    return (f"{l['ine']} | {l['name']} ({l['prov']}) | {l['pop']} hab., {l['elev'] or '?'} m, {where}, {coast} | "
            f"{l['rasgos'] or 'sin rasgos destacados'}")


async def label(session, sem, frase, cands, effort):
    body = {"model": MODEL, "instructions": INSTRUCTIONS, "max_output_tokens": 2000,
            "input": f"Búsqueda: {frase}\n\nCandidatos:\n" + "\n".join(describe(c) for c in cands),
            "text": {"format": SCHEMA}}
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
                   if c.get("type") == "output_text")
    valid = {c["ine"] for c in cands}
    picks = [(p["id"], p["nota"]) for p in json.loads(text)["elegidos"] if p["id"] in valid]
    picks.sort(key=lambda x: -x[1])      # estable: dentro de cada nota, el orden que dio el profesor
    u = d.get("usage", {})
    return {"frase": frase, "candidatos": [c["ine"] for c in cands], "elegidos": picks,
            "in": u.get("input_tokens", 0), "out": u.get("output_tokens", 0)}


def pilot_report(results, exam):
    rows = []
    for r in results:
        rec = exam[r["frase"]]
        human = rec["marcas"]                        # ine -> 1 vale / 2 muy buena
        judged = set(r["candidatos"][:30]) | set(human)   # lo que la persona vio o buscó
        in_cands = [x for x in human if x in r["candidatos"]]
        teacher = [x for x, _ in r["elegidos"]]
        t_top = [x for x in teacher if x in judged][:5]
        b_top = [x for x in r["candidatos"] if x in judged][:5]
        rows.append({
            "frase": r["frase"][:50], "marcados": len(human),
            "buscador": len(in_cands) / max(1, len(human)),
            "prof@5": sum(x in human for x in t_top) / max(1, len(t_top)),
            "busc@5": sum(x in human for x in b_top) / max(1, len(b_top)),
            "cobertura": sum(x in teacher for x in in_cands) / max(1, len(in_cands)),
            "elige": len(teacher),
        })
    for x in rows:
        print(f"  {x['frase']:50s} marcados {x['marcados']:2d} | buscador {x['buscador']:.0%} | "
              f"profesor@5 {x['prof@5']:.0%} vs buscador@5 {x['busc@5']:.0%} | cobertura {x['cobertura']:.0%} | elige {x['elige']}")
    n = len(rows)
    avg = lambda k: sum(x[k] for x in rows) / n  # noqa: E731
    print(f"\nMEDIA ({n} frases): buscador encuentra {avg('buscador'):.0%} de lo marcado | acierto@5 profesor "
          f"{avg('prof@5'):.0%} frente a {avg('busc@5'):.0%} del buscador solo | cobertura del profesor {avg('cobertura'):.0%}")


async def label_all(frases, lugares, bm, sem, headers, effort):
    """Todas las frases, guardando cada una según termina y retomando donde se quedó.

    Las 50 frases del examen humano también se etiquetan, marcadas con "examen": nunca
    entran en el entrenamiento del alumno, porque son con lo que se le examina.
    """
    path = BIG / "etiquetas.jsonl"
    done = set()
    if path.exists():
        done = {json.loads(l)["frase"] for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}
    exam = set(json.loads((BIG / "examen_frases.json").read_text(encoding="utf-8")))
    todo = [f for f in frases if f not in done]
    t0, n, cin, cout, errs = time.time(), 0, 0, 0, 0
    with path.open("a", encoding="utf-8") as out:
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=180)) as s:
            tasks = [asyncio.ensure_future(label(s, sem, f, [lugares[i] for i in bm.top(tokens(f), N_CAND)], effort))
                     for f in todo]
            for fut in asyncio.as_completed(tasks):
                try:
                    r = await fut
                except Exception as e:  # noqa: BLE001  una frase fallida no para el resto
                    errs += 1
                    if errs <= 3:
                        print("error:", e, flush=True)
                    continue
                r["examen"] = r["frase"] in exam
                out.write(json.dumps(r, ensure_ascii=False) + "\n"); out.flush()
                n += 1; cin += r["in"]; cout += r["out"]
                if n % 500 == 0:
                    print(f"  {n}/{len(todo)}  {cin * PRICE_IN + cout * PRICE_OUT:.3f} $  ({time.time() - t0:.0f} s)", flush=True)
    print(f"{n} frases nuevas etiquetadas ({len(done) + n} en total), {errs} errores, "
          f"coste {cin * PRICE_IN + cout * PRICE_OUT:.3f} $, {time.time() - t0:.0f} s")


async def main(args):
    lugares = json.loads((BIG / "lugares.json").read_text(encoding="utf-8"))
    bm = BM25([tokens(doc_text(l)) for l in lugares])
    if args.pilot:
        exam_raw = json.loads((BIG / "examen.json").read_text(encoding="utf-8"))
        exam = {r["frase"]: r for r in exam_raw.values() if not r["mala"] and r["marcas"]}
        frases = list(exam)
    else:
        frases = [json.loads(l)["frase"] for l in (BIG / "frases.jsonl").read_text(encoding="utf-8").splitlines()][:args.n]
    sem = asyncio.Semaphore(CONCURRENCY)
    headers = {"Authorization": f"Bearer {key()}", "Content-Type": "application/json"}
    t0 = time.time()
    if not args.pilot:
        await label_all(frases, lugares, bm, sem, headers, args.effort)
        return
    async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=180)) as s:
        tasks = [label(s, sem, f, [lugares[i] for i in bm.top(tokens(f), N_CAND)], args.effort) for f in frases]
        results = [r for r in await asyncio.gather(*tasks, return_exceptions=True) if isinstance(r, dict)]
    cost = sum(r["in"] for r in results) * PRICE_IN + sum(r["out"] for r in results) * PRICE_OUT
    print(f"{len(results)}/{len(frases)} frases en {time.time() - t0:.0f} s, coste {cost:.4f} $ "
          f"({cost / max(1, len(results)) * 5000:.2f} $ para 5.000)")
    if args.pilot:
        pilot_report(results, exam)
        (BIG / f"piloto-{args.effort or 'defecto'}.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--n", type=int, default=5000)
    ap.add_argument("--effort", default="none")
    asyncio.run(main(ap.parse_args()))
