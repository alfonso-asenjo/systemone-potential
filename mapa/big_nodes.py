"""El profesor describe cada nodo del árbol (comunidad, provincia, mitad, grupo) resumiendo sus municipios.

En el mapa de 255 lugares, las descripciones de las 20 zonas las escribí a mano y fueron el
eslabón débil: Laya sin entrenar solo coincidía con jev en la zona el 27 % de las veces. Aquí
cada nodo se describe a partir de los rasgos reales de sus municipios, en 35 palabras como
mucho, porque Laya lee unos 48 tokens por opción.

    python mapa/big_nodes.py   ->  data/big/nodos.json  (id -> descripción; continúa si se corta)
"""
from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path

import aiohttp

from big_label import key

HERE = Path(__file__).resolve().parent
BIG = HERE / "data" / "big"
MODEL = "gpt-6-luna"
PRICE_IN, PRICE_OUT = 0.10 / 1e6, 0.50 / 1e6
MAX_LINES = 45

INSTRUCTIONS = """Te doy una zona de España y datos reales de sus municipios.
Escribe en castellano qué ofrece la zona a quien busca adónde ir: paisaje (costa, montaña, llanura, ríos), patrimonio,
gastronomía, ambiente y lo más característico. Máximo 35 palabras, sin frases de relleno, sin nombrar la zona.
Usa solo los datos dados."""


def leaves(node, by_ine):
    kids = node.get("children", [])
    if kids and isinstance(kids[0], str):
        return [by_ine[k] for k in kids]
    return [m for k in kids for m in leaves(k, by_ine)]


def walk(node):
    yield node
    for k in node.get("children", []):
        if isinstance(k, dict):
            yield from walk(k)


async def describe(session, sem, node, muns, rng, stats):
    costeros = sum(m["costero"] for m in muns)
    alt = sorted(m["elev"] for m in muns if m["elev"] is not None)
    head = (f"{len(muns)} municipios, {costeros} costeros, altitud mediana {alt[len(alt) // 2] if alt else '?'} m, "
            f"el mayor {max(muns, key=lambda m: m['pop'] or 0)['name']}.")
    rich = [m for m in muns if m["rasgos"]]
    rich.sort(key=lambda m: -(m["pop"] or 0))
    sample = rich[:15] + rng.sample(rich[15:], min(len(rich) - 15, MAX_LINES - 15)) if len(rich) > 15 else rich
    lines = "\n".join(f"- {m['name']}: {' '.join(m['rasgos'].split()[:25])}" for m in sample)
    body = {"model": MODEL, "reasoning": {"effort": "none"}, "max_output_tokens": 300, "instructions": INSTRUCTIONS,
            "input": f"Zona: {node['name']}\n{head}\nMunicipios:\n{lines}"}
    async with sem:
        for attempt in range(4):
            async with session.post("https://api.openai.com/v1/responses", json=body) as r:
                d = await r.json()
                if r.status == 200:
                    break
                await asyncio.sleep(2 * (attempt + 1))
        else:
            return None
    text = "".join(c.get("text", "") for o in d.get("output", []) for c in (o.get("content") or [])
                   if c.get("type") == "output_text").strip()
    u = d.get("usage", {})
    stats["in"] += u.get("input_tokens", 0); stats["out"] += u.get("output_tokens", 0)
    return node["id"], text


async def main():
    tree = json.loads((BIG / "arbol.json").read_text(encoding="utf-8"))
    by_ine = {l["ine"]: l for l in json.loads((BIG / "lugares.json").read_text(encoding="utf-8"))}
    path = BIG / "nodos.json"
    done = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    nodes = [n for n in walk(tree) if n["id"] != "es" and n["id"] not in done]
    rng = random.Random(3)
    stats = {"in": 0, "out": 0}
    sem = asyncio.Semaphore(8)
    headers = {"Authorization": f"Bearer {key()}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as s:
        res = await asyncio.gather(*[describe(s, sem, n, leaves(n, by_ine), rng, stats) for n in nodes])
    for r in res:
        if r:
            done[r[0]] = r[1]
    path.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{sum(r is not None for r in res)} nodos descritos ({len(done)} en total), "
          f"coste {stats['in'] * PRICE_IN + stats['out'] * PRICE_OUT:.3f} $")
    for k in ("c:Asturias", "c:Aragón", "p:Burgos"):
        print(f"  {k}: {done.get(k)}")


if __name__ == "__main__":
    asyncio.run(main())
