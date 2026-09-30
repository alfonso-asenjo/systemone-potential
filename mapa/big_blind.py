"""Examen a ciegas: 5 municipios del profesor y 5 del buscador, mezclados, y la persona dice sí o no.

El primer examen (marcar entre 30 candidatos en el orden del buscador) salió sesgado: todo lo
marcado estaba entre los 10 primeros de la lista, así que premiaba al buscador por construcción
(profesor 48 % frente a buscador 66 % en sus 5 primeros, con elecciones del profesor que a ojo
eran mejores: Lozoya o Vistabella para "montaña con vistas"). Aquí nadie sabe de quién es cada
municipio y el orden es aleatorio.

    python mapa/big_blind.py prepare      # data/big/ciego_sets.json (20 frases, llama al profesor)
    python mapa/big_blind.py report       # destapa y compara, con data/big/ciego.json
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
from pathlib import Path

import aiohttp

from big_label import CONCURRENCY, N_CAND, key, label
from review import BM25, doc_text, tokens

HERE = Path(__file__).resolve().parent
BIG = HERE / "data" / "big"
N_FRASES = 20
K = 5


async def prepare():
    lugares = json.loads((BIG / "lugares.json").read_text(encoding="utf-8"))
    bm = BM25([tokens(doc_text(l)) for l in lugares])
    frases = json.loads((BIG / "examen_frases.json").read_text(encoding="utf-8"))
    exam = json.loads((BIG / "examen.json").read_text(encoding="utf-8")) if (BIG / "examen.json").exists() else {}
    malas = {r["frase"] for r in exam.values() if r["mala"]}
    frases = [f for f in frases if f not in malas][:N_FRASES]
    sem = asyncio.Semaphore(CONCURRENCY)
    headers = {"Authorization": f"Bearer {key()}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=180)) as s:
        results = await asyncio.gather(*[label(s, sem, f, [lugares[i] for i in bm.top(tokens(f), N_CAND)], "none")
                                         for f in frases])
    rng = random.Random(42)
    sets = []
    for r in results:
        teacher = [x for x, _ in r["elegidos"]][:K]
        search = r["candidatos"][:K]
        items = list(dict.fromkeys(teacher + search))      # sin repetir si coinciden
        rng.shuffle(items)
        sets.append({"frase": r["frase"], "items": items, "profesor": teacher, "buscador": search})
    (BIG / "ciego_sets.json").write_text(json.dumps(sets, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(sets)} frases preparadas; municipios por frase: {[len(s['items']) for s in sets]}")


def report():
    sets = json.loads((BIG / "ciego_sets.json").read_text(encoding="utf-8"))
    votes = json.loads((BIG / "ciego.json").read_text(encoding="utf-8"))
    tp = tb = n = 0
    for i, s in enumerate(sets):
        v = votes.get(str(i))
        if not v:
            continue
        n += 1
        p = sum(v.get(x, 0) for x in s["profesor"]) / max(1, len(s["profesor"]))
        b = sum(v.get(x, 0) for x in s["buscador"]) / max(1, len(s["buscador"]))
        tp += p; tb += b
        print(f"  {s['frase'][:60]:60s} profesor {p:.0%} | buscador {b:.0%}")
    if n:
        print(f"\n{n} frases juzgadas a ciegas: el profesor acierta {tp / n:.0%} de sus 5 primeros; "
              f"el buscador, {tb / n:.0%}")


if __name__ == "__main__":
    asyncio.run(prepare()) if sys.argv[1:] == ["prepare"] else report()
