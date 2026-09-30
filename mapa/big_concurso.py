"""Concurso de profesores: ¿qué receta barata se acerca más a un profesor caro?

Mismas instrucciones, mismo esquema de salida y mismos 50 candidatos por frase que el profesor
original (big_label.py). 100 frases: las 50 del examen y 50 más al azar. Recetas (docs/concurso-profesores.csv):

  R1 luna tal cual (ya pagado: etiquetas.jsonl)    R2 luna x3 con los candidatos barajados, razonando poco
  R3 gpt-5.6-luna                                    R4 voto de R2 y R3 (sin coste)
  R5 Claude Haiku 4.5 (OpenRouter)                   R6 gpt-6-sol razonando poco
  R7 Claude Sonnet 5 (OpenRouter)                    R8 cascada: R4, y R6 donde R2 y R3 discrepan (sin coste)

    python mapa/big_concurso.py probar        # una frase por concursante
    python mapa/big_concurso.py correr        # las 100 frases -> data/big/concurso.jsonl (retoma)
    python mapa/big_concurso.py hoja          # CSV a ciegas para la persona + clave aparte
    python mapa/big_concurso.py resultados    # con la hoja rellenada: acierto de cada receta
"""
from __future__ import annotations

import asyncio
import csv
import json
import random
import sys
import zlib
from pathlib import Path

import aiohttp

from big_label import INSTRUCTIONS, SCHEMA, describe, key as openai_key

HERE = Path(__file__).resolve().parent
BIG = HERE / "data" / "big"
OUT = BIG / "concurso.jsonl"
SHEET = HERE.parent / "docs" / "concurso-examen.csv"
SHEET_KEY = BIG / "concurso-clave.json"
N_SHEET = 30          # frases que juzga la persona
TOP = 5               # de cada receta se juzgan sus 5 primeros

# (nombre, proveedor, modelo, razonamiento, barajar con esta semilla)
CALLS = [
    ("R2a", "openai", "gpt-6-luna", "low", 1), ("R2b", "openai", "gpt-6-luna", "low", 2), ("R2c", "openai", "gpt-6-luna", "low", 3),
    ("R3", "openai", "gpt-5.6-luna", "none", None),
    ("R5", "openrouter", "anthropic/claude-haiku-4.5", None, None),
    ("R6", "openai", "gpt-6-sol", "low", None),
    ("R7", "openrouter", "anthropic/claude-sonnet-5", None, None),
]


def openrouter_key() -> str:
    for line in (HERE.parent / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("falta OPENROUTER_API_KEY en .env")


def frases() -> list[dict]:
    rows = [json.loads(l) for l in (BIG / "etiquetas.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if r["elegidos"]]
    exam = [r for r in rows if r.get("examen")]
    rest = [r for r in rows if not r.get("examen")]
    random.Random(2026).shuffle(rest)
    return exam[:50] + rest[:50]


def parse(text: str, valid: set[str]) -> list[tuple[str, int]]:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").split("\n", 1)[1].rsplit("```", 1)[0] if "\n" in t else t
    d = json.loads(t[t.find("{"): t.rfind("}") + 1])
    picks = [(p["id"], int(p["nota"])) for p in d["elegidos"] if p.get("id") in valid and int(p.get("nota", 0)) in (1, 2, 3)]
    picks.sort(key=lambda x: -x[1])
    return picks


async def ask(session, sem, call, frase, cands, lug):
    name, prov, model, effort, seed = call
    order = list(cands)
    if seed is not None:
        random.Random(seed * 7919 + zlib.crc32(frase.encode())).shuffle(order)
    user = f"Búsqueda: {frase}\n\nCandidatos:\n" + "\n".join(describe(lug[c]) for c in order)
    async with sem:
        for attempt in range(5):
            try:
                if prov == "openai":
                    body = {"model": model, "instructions": INSTRUCTIONS, "input": user, "max_output_tokens": 4000,
                            "text": {"format": SCHEMA}}
                    if effort:
                        body["reasoning"] = {"effort": effort}
                    async with session.post("https://api.openai.com/v1/responses", json=body,
                                            headers={"Authorization": f"Bearer {openai_key()}"}) as r:
                        d = await r.json()
                        if r.status != 200:
                            raise RuntimeError(f"{r.status} {str(d.get('error', {}).get('message', ''))[:160]}")
                    text = "".join(c.get("text", "") for o in d.get("output", []) for c in (o.get("content") or [])
                                   if c.get("type") == "output_text")
                    u = d.get("usage", {})
                    usage = {"in": u.get("input_tokens", 0), "out": u.get("output_tokens", 0), "cost": None}
                else:
                    body = {"model": model, "max_tokens": 3000, "usage": {"include": True}, "reasoning": {"enabled": False},
                            "messages": [{"role": "system", "content": INSTRUCTIONS}, {"role": "user", "content": user}],
                            "response_format": {"type": "json_schema", "json_schema": {"name": SCHEMA["name"], "strict": True, "schema": SCHEMA["schema"]}}}
                    async with session.post("https://openrouter.ai/api/v1/chat/completions", json=body,
                                            headers={"Authorization": f"Bearer {openrouter_key()}"}) as r:
                        d = await r.json()
                        if r.status != 200 or "choices" not in d:
                            raise RuntimeError(f"{r.status} {str(d.get('error', d))[:160]}")
                    text = d["choices"][0]["message"]["content"] or ""
                    u = d.get("usage", {})
                    usage = {"in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0), "cost": u.get("cost")}
                return {"frase": frase, "receta": name, "elegidos": parse(text, set(cands)), **usage}
            except Exception as e:  # noqa: BLE001
                if attempt == 4:
                    return {"frase": frase, "receta": name, "error": str(e)[:200]}
                await asyncio.sleep(3 * (attempt + 1))


PRICES = {"gpt-6-luna": (0.10, 0.50), "gpt-5.6-luna": (0.20, 1.20), "gpt-6-sol": (2.00, 10.00)}


def cost_of(r, call_by_name):
    if r.get("cost") is not None:
        return float(r["cost"])
    model = call_by_name[r["receta"]][2]
    pin, pout = PRICES.get(model, (0, 0))
    return (r.get("in", 0) * pin + r.get("out", 0) * pout) / 1e6


async def run(only_first=False):
    lug = {l["ine"]: l for l in json.loads((BIG / "lugares.json").read_text(encoding="utf-8"))}
    fr = frases()[:1] if only_first else frases()
    done = set()
    if OUT.exists() and not only_first:
        done = {(r["frase"], r["receta"]) for r in map(json.loads, OUT.read_text(encoding="utf-8").splitlines()) if "error" not in r}
    todo = [(c, r) for r in fr for c in CALLS if (r["frase"], c[0]) not in done]
    sem = asyncio.Semaphore(6)
    by_name = {c[0]: c for c in CALLS}
    spent, errs = 0.0, 0
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as s:
        tasks = [asyncio.ensure_future(ask(s, sem, c, r["frase"], r["candidatos"], lug)) for c, r in todo]
        out = OUT.open("a", encoding="utf-8") if not only_first else None
        for k, fut in enumerate(asyncio.as_completed(tasks), 1):
            res = await fut
            if "error" in res:
                errs += 1
                print("error", res["receta"], res["error"], flush=True)
            else:
                spent += cost_of(res, by_name)
                if only_first:
                    print(f"{res['receta']:4s} {len(res['elegidos'])} elegidos, primeros {res['elegidos'][:3]} "
                          f"(tokens {res.get('in')}/{res.get('out')}, {cost_of(res, by_name):.4f} $)", flush=True)
            if out:
                out.write(json.dumps(res, ensure_ascii=False) + "\n"); out.flush()
            if k % 50 == 0:
                print(f"  {k}/{len(todo)} · gastado {spent:.2f} $ · errores {errs}", flush=True)
        if out:
            out.close()
    print(f"hecho: {len(todo)} llamadas, {spent:.3f} $, {errs} errores")


# ---------------------------------------------------------------- recetas finales (listas ordenadas)
def recipes() -> dict[str, dict[str, list[str]]]:
    """frase -> receta -> municipios ordenados de mejor a peor."""
    raw: dict[str, dict[str, list]] = {}
    for r in map(json.loads, OUT.read_text(encoding="utf-8").splitlines()):
        if "error" not in r:
            raw.setdefault(r["frase"], {})[r["receta"]] = r["elegidos"]
    out = {}
    for f in frases():
        got = raw.get(f["frase"], {})
        rec = {"R1": [x for x, _ in f["elegidos"]]}

        def mean(names):
            sc: dict[str, float] = {}
            for n in names:
                for x, nota in got.get(n, []):
                    sc[x] = sc.get(x, 0) + nota / len(names)
            return sc
        r2 = mean(["R2a", "R2b", "R2c"])
        rec["R2"] = sorted(r2, key=lambda x: -r2[x])
        for n in ("R3", "R5", "R6", "R7"):
            rec[n] = [x for x, _ in got.get(n, [])]
        r3 = {x: n for x, n in got.get("R3", [])}
        r4 = {x: (r2.get(x, 0) + r3.get(x, 0)) / 2 for x in set(r2) | set(r3)}
        rec["R4"] = sorted(r4, key=lambda x: -r4[x])
        a, b = set(rec["R2"][:TOP]), set(rec["R3"][:TOP])
        disagree = len(a & b) / max(1, len(a | b)) < 0.4
        rec["R8"] = rec["R6"] if disagree else rec["R4"]
        out[f["frase"]] = rec
    return out


def sheet():
    lug = {l["ine"]: l for l in json.loads((BIG / "lugares.json").read_text(encoding="utf-8"))}
    rec = recipes()
    fr = frases()
    pick = fr[:N_SHEET // 2] + fr[50:50 + N_SHEET - N_SHEET // 2]      # mitad del examen, mitad del resto
    rng = random.Random(99)
    rows, key = [], {}
    for f in pick:
        items = list(dict.fromkeys(x for lst in rec[f["frase"]].values() for x in lst[:TOP]))
        rng.shuffle(items)
        for ine in items:
            rows.append((f["frase"], ine))
    with SHEET.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["n", "busqueda", "municipio", "provincia", "habitantes", "altitud_m", "desde_madrid", "costa", "rasgos", "encaja (sí/no)"])
        for n, (frase, ine) in enumerate(rows, 1):
            l = lug[ine]
            where = {"island": "isla", "africa": "norte de África"}.get(l["reach"], f"{l['hours']} h en coche".replace(".", ","))
            w.writerow([n, frase, l["name"], l["prov"], l["pop"], l["elev"] or "", where, "sí" if l["costero"] else "no", l["rasgos"] or "", ""])
            key[n] = {"frase": frase, "ine": ine}
    SHEET_KEY.write_text(json.dumps(key, ensure_ascii=False), encoding="utf-8")
    print(f"{SHEET}: {len(rows)} filas de {len(pick)} búsquedas")


def results():
    rec = recipes()
    key = json.loads(SHEET_KEY.read_text(encoding="utf-8"))
    verdict = {}
    with SHEET.open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            v = (row.get("encaja (sí/no)") or "").strip().lower()
            if v in ("sí", "si", "s", "1", "x"):
                verdict[(key[row["n"]]["frase"], key[row["n"]]["ine"])] = True
            elif v in ("no", "n", "0"):
                verdict[(key[row["n"]]["frase"], key[row["n"]]["ine"])] = False
    frases_hoja = {k["frase"] for k in key.values()}
    names = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
    print(f"juzgadas {len(verdict)} de {len(key)} filas")
    for n in names:
        hits = tot = 0
        for f in frases_hoja:
            for x in rec[f][n][:TOP]:
                if (f, x) in verdict:
                    hits += verdict[(f, x)]; tot += 1
        print(f"{n}: {hits}/{tot} = {hits / max(1, tot):.0%} de sus 5 primeros encajan")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "probar"
    if cmd == "probar":
        asyncio.run(run(only_first=True))
    elif cmd == "correr":
        asyncio.run(run())
    elif cmd == "hoja":
        sheet()
    else:
        results()
