"""Examen justo del alumno del árbol, y dónde se equivoca.

1. Juez: gpt-6-luna dice sí o no a cada uno de los 10 primeros del alumno y del buscador para
   las 50 frases del examen. El recall contra las etiquetas del profesor favorece al buscador
   por construcción (el profesor solo eligió entre los 50 candidatos del buscador), y aquí se
   miden los dos igual. El profesor ya demostró criterio: a ciegas, una persona le dio por
   buenas el 97 % de sus elecciones.
2. Diagnóstico por niveles: ¿acierta la comunidad? Y si se le da el grupo bueno, ¿acierta el
   municipio? Separa si falla arriba (elegir zona) o abajo (elegir pueblo).

    .venv-laya/Scripts/python mapa/big_judge.py [--model models/laya-mapa]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import aiohttp
import numpy as np

from big_label import MODEL, PRICE_IN, PRICE_OUT, describe, key
from big_tree import OUT, Tree, load_labels, picks_of, rank, state
from review import BM25, doc_text, tokens

HERE = Path(__file__).resolve().parent
K = 10

JUDGE = """Te doy una búsqueda de alguien que quiere encontrar adónde ir en España y una lista de municipios con sus datos.
Devuelve los ids de los que son una respuesta razonable a la búsqueda. Usa solo los datos dados."""
SCHEMA = {"type": "json_schema", "name": "juicio", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["buenos"],
    "properties": {"buenos": {"type": "array", "items": {"type": "string"}}}}}


async def judge(session, frase, cands, stats):
    body = {"model": MODEL, "reasoning": {"effort": "none"}, "instructions": JUDGE, "max_output_tokens": 800,
            "input": f"Búsqueda: {frase}\n\nMunicipios:\n" + "\n".join(describe(c) for c in cands),
            "text": {"format": SCHEMA}}
    for attempt in range(4):
        async with session.post("https://api.openai.com/v1/responses", json=body) as r:
            d = await r.json()
            if r.status == 200:
                break
            await asyncio.sleep(2 * (attempt + 1))
    u = d.get("usage", {})
    stats["in"] += u.get("input_tokens", 0); stats["out"] += u.get("output_tokens", 0)
    text = "".join(c.get("text", "") for o in d.get("output", []) for c in (o.get("content") or [])
                   if c.get("type") == "output_text")
    return set(json.loads(text)["buenos"])


def diagnose(agent, tree: Tree, rows):
    """Comunidad acertada y, dándole el grupo bueno, municipio acertado."""
    ccaa_hit, leaf_hit = [], []
    for r in rows:
        picks = picks_of(r)
        m = tree.masses(picks)
        best_ccaa = max(tree.kids["es"], key=lambda k: m.get(k, 0))
        ans = agent.predict(state(r["frase"]), {"es": tree.question("es")}, head_max_len=1024)["answers"]["es"]
        top3 = sorted(ans["probabilities"], key=ans["probabilities"].get, reverse=True)[:3]
        ccaa_hit.append(best_ccaa in top3)
        best = max(picks, key=picks.get)
        g = tree.parent[best]
        if len(tree.kids[g]) > 1:
            a = agent.predict(state(r["frase"]), {g: tree.question(g)}, head_max_len=1024)["answers"][g]
            top3 = sorted(a["probabilities"], key=a["probabilities"].get, reverse=True)[:3]
            good = {x for x in tree.kids[g] if x in picks}
            leaf_hit.append(bool(good & set(top3)))
    return {"comunidad_del_profesor_en_top3": round(float(np.mean(ccaa_hit)), 3),
            "dado_el_grupo_bueno_municipio_en_top3": round(float(np.mean(leaf_hit)), 3)}


async def main(args):
    import laya
    tree = Tree()
    rows = load_labels(exam=True)
    agent = laya.load(args.model, device="cuda")
    lugares = list(tree.lug.values())
    bm = BM25([tokens(doc_text(l)) for l in lugares])
    stats = {"in": 0, "out": 0}
    prec = {"alumno": [], "buscador": [], "profesor": []}
    ms = []
    headers = {"Authorization": f"Bearer {key()}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=180)) as s:
        for r in rows:
            t0 = time.perf_counter()
            sc = rank(agent, tree, r["frase"], beam=args.beam)
            ms.append((time.perf_counter() - t0) * 1000)
            lists = {"alumno": [x for x, _ in sorted(sc.items(), key=lambda kv: -kv[1])[:K]],
                     "buscador": [lugares[i]["ine"] for i in bm.top(tokens(r["frase"]), K)],
                     "profesor": [x for x, _ in r["elegidos"]][:K]}
            union = list(dict.fromkeys(x for l in lists.values() for x in l))
            good = await judge(s, r["frase"], [tree.lug[x] for x in union], stats)
            for name, l in lists.items():
                if l:
                    prec[name].append(sum(x in good for x in l) / len(l))
    cost = stats["in"] * PRICE_IN + stats["out"] * PRICE_OUT
    print(f"juez gpt-6-luna, {len(rows)} frases del examen, haz {args.beam}, "
          f"alumno {np.median(ms):.0f} ms por búsqueda, coste {cost:.3f} $")
    for name, v in prec.items():
        print(f"  {name:9s} acierto@{K}: {np.mean(v):.0%}")
    if not args.no_diag:
        print("diagnóstico:", json.dumps(diagnose(agent, tree, rows)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=str(OUT))
    ap.add_argument("--beam", type=int, default=3, help="ramas que se siguen en cada nivel")
    ap.add_argument("--no-diag", action="store_true")
    asyncio.run(main(ap.parse_args()))
