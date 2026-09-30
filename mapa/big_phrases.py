"""Frases de búsqueda para entrenar y examinar: lo que alguien teclearía en el mapa.

Para que no salgan 5.000 variantes de "pueblo con playa", cada petición mezcla un tipo de
búsqueda, un estilo de escritura y, como inspiración, los rasgos de 6 municipios al azar
(sin sus nombres), para que también haya búsquedas que encajen con pueblos poco conocidos.
Las frases no pueden nombrar el sitio: eso lo tiene que encontrar el mapa.

Cada tanda se guarda según termina (big_describe.py lo guardaba todo al final y una parada a
mitad habría perdido lo ya pagado).

    python mapa/big_phrases.py --calls 250   ->  data/big/frases.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import unicodedata
from pathlib import Path

import aiohttp

HERE = Path(__file__).resolve().parent
BIG = HERE / "data" / "big"
MODEL = "gpt-6-luna"
PRICE_IN, PRICE_OUT = 0.10 / 1e6, 0.50 / 1e6
CONCURRENCY = 8
PER_CALL = 20

KINDS = [
    "escapada de fin de semana", "vacaciones de verano", "plan con niños", "viaje en pareja", "viaje con amigos",
    "paisaje de montaña", "costa y playas", "ríos, lagos y embalses", "bosques y senderismo", "pueblos con encanto",
    "patrimonio e historia", "arte y museos", "gastronomía y vino", "fiestas y tradiciones", "naturaleza y fauna",
    "tranquilidad y desconexión", "deporte y aventura", "invierno y nieve", "limitaciones de tiempo o distancia desde Madrid",
    "sitios poco conocidos", "ciudad grande con ambiente", "clima y época del año", "vivir o teletrabajar",
]
STYLES = [
    "muy cortas, de 2 a 4 palabras, como en un buscador",
    "coloquiales, como hablaría alguien con un amigo",
    "con alguna falta de ortografía o sin tildes, como se escribe en el móvil",
    "largas y detalladas, de 12 a 20 palabras, con varias condiciones",
    "mezcladas: unas cortas, otras largas",
]

PROMPT = """Genera {n} búsquedas distintas que una persona escribiría en un mapa interactivo de España para encontrar un pueblo o ciudad al que ir.
Tipo de búsqueda: {kind}.
Estilo: {style}.
Como inspiración (no tienes que usarlos todos), rasgos reales de algunos municipios, sin sus nombres:
{traits}
Reglas:
- En castellano. No nombres ningún municipio, provincia ni comunidad concretos (se puede decir "cerca de Madrid" o "en el norte").
- Que sean variadas entre sí y realistas.
- Una búsqueda por línea, sin numerar, sin comillas, sin nada más."""


def key() -> str:
    for line in (HERE.parent / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENAI_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("falta OPENAI_API_KEY en .env")


def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]", "", t).strip()


async def one(session, sem, rng, lugares, out, seen, stats):
    kind, style = rng.choice(KINDS), rng.choice(STYLES)
    sample = rng.sample([l for l in lugares if l["rasgos"]], 6)
    traits = "\n".join(f"- {l['rasgos']}" for l in sample)
    body = {"model": MODEL, "reasoning": {"effort": "none"}, "max_output_tokens": 1200,
            "input": PROMPT.format(n=PER_CALL, kind=kind, style=style, traits=traits)}
    async with sem:
        for attempt in range(4):
            async with session.post("https://api.openai.com/v1/responses", json=body) as r:
                d = await r.json()
                if r.status == 200:
                    break
                if r.status in (429, 500, 502, 503):
                    await asyncio.sleep(2 * (attempt + 1)); continue
                stats["errors"] += 1
                return
        else:
            stats["errors"] += 1
            return
    text = "".join(c.get("text", "") for o in d.get("output", []) for c in (o.get("content") or [])
                   if c.get("type") == "output_text")
    u = d.get("usage", {})
    stats["in"] += u.get("input_tokens", 0); stats["out"] += u.get("output_tokens", 0)
    names = {norm(l["name"]) for l in sample}
    for line in text.splitlines():
        p = re.sub(r"^[-*\d.)\s]+", "", line).strip().strip('"«»')
        n = norm(p)
        if len(n) < 3 or n in seen or any(nm and nm in n for nm in names):
            continue
        seen.add(n)
        out.write(json.dumps({"frase": p, "tipo": kind, "estilo": style}, ensure_ascii=False) + "\n")
        stats["kept"] += 1
    out.flush()


async def main(args):
    lugares = json.loads((BIG / "lugares.json").read_text(encoding="utf-8"))
    path = BIG / "frases.jsonl"
    seen = set()
    if path.exists():
        seen = {norm(json.loads(l)["frase"]) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}
    rng = random.Random(args.seed)
    stats = {"in": 0, "out": 0, "kept": 0, "errors": 0}
    sem = asyncio.Semaphore(CONCURRENCY)
    headers = {"Authorization": f"Bearer {key()}", "Content-Type": "application/json"}
    with path.open("a", encoding="utf-8") as out:
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as s:
            await asyncio.gather(*[one(s, sem, rng, lugares, out, seen, stats) for _ in range(args.calls)])
    cost = stats["in"] * PRICE_IN + stats["out"] * PRICE_OUT
    print(f"{stats['kept']} frases nuevas ({len(seen)} en total), {stats['errors']} errores, coste {cost:.4f} $")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--calls", type=int, default=250)
    ap.add_argument("--seed", type=int, default=11)
    asyncio.run(main(ap.parse_args()))
