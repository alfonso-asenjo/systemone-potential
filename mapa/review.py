"""El examen humano: 50 frases en las que una persona marca qué municipios son buenas respuestas.

Sin esto solo sabríamos si los profesores coinciden entre ellos, no si aciertan.

    python mapa/review.py [--host 0.0.0.0]    y abrir http://127.0.0.1:8785/

Para cada frase se enseñan los 30 municipios que mejor encajan según un buscador de palabras
(BM25 sobre nombre, provincia y rasgos) y se puede buscar cualquier otro por su nombre. Las
marcas se guardan al momento en data/big/examen.json: se puede dejar a medias y seguir.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import unicodedata
from collections import Counter
from pathlib import Path

from aiohttp import web

HERE = Path(__file__).resolve().parent
BIG = HERE / "data" / "big"
N_EXAM = 50
N_CAND = 30
STOP = set("""a al algo alguna alguno algun ante bajo con como cual de del desde donde dos el en entre
es esta este esto ha hay hacer la las le lo los mas me mi muy no o para pero poco por que quiero se sea
ser si sin sobre su sus te tener tiene todo tu un una uno unos unas y ya busco buscar lugar lugares sitio
sitios pueblo pueblos ciudad ciudades zona zonas algun quisiera ir pasar dia dias donde encontrar""".split())


def norm(t: str) -> str:
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()


def tokens(t: str) -> list[str]:
    # Prefijo de 5 letras como raíz pobre: "playas" y "playa", "montañoso" y "montaña" casan.
    return [w[:5] for w in re.findall(r"[a-z]+", norm(t)) if w not in STOP and len(w) > 2]


class BM25:
    def __init__(self, docs: list[list[str]], k1=1.4, b=0.75):
        self.docs, self.k1, self.b = [Counter(d) for d in docs], k1, b
        self.len = [len(d) for d in docs]
        self.avg = sum(self.len) / len(self.len)
        df = Counter(w for d in self.docs for w in d)
        n = len(docs)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}

    def top(self, query: list[str], k: int) -> list[int]:
        scores = []
        for i, d in enumerate(self.docs):
            s = 0.0
            for w in query:
                f = d.get(w)
                if f:
                    s += self.idf[w] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
            if s:
                scores.append((s, i))
        scores.sort(reverse=True)
        return [i for _, i in scores[:k]]


def doc_text(l: dict) -> str:
    extra = []
    if l["costero"]:
        extra.append("costa playa mar")
    if (l["elev"] or 0) > 800:
        extra.append("montaña sierra")
    return " ".join([l["name"], l["prov"], l["ccaa"], l["rasgos"], *extra])


def card(l: dict) -> dict:
    return {k: l[k] for k in ("ine", "name", "prov", "ccaa", "pop", "elev", "hours", "reach", "costero", "coast_km", "rasgos")}


def load_exam() -> dict:
    p = BIG / "examen.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_exam(exam: dict) -> None:
    tmp = BIG / "examen.json.tmp"
    tmp.write_text(json.dumps(exam, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(BIG / "examen.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8785)
    args = ap.parse_args()

    lugares = json.loads((BIG / "lugares.json").read_text(encoding="utf-8"))
    by_ine = {l["ine"]: l for l in lugares}
    bm = BM25([tokens(doc_text(l)) for l in lugares])
    frases_path = BIG / "examen_frases.json"
    if frases_path.exists():
        frases = json.loads(frases_path.read_text(encoding="utf-8"))
    else:
        allf = [json.loads(l) for l in (BIG / "frases.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        rng = random.Random(2026)
        by_style: dict[str, list] = {}
        for f in allf:
            by_style.setdefault(f["estilo"], []).append(f)
        frases = []
        for style in sorted(by_style):
            frases += rng.sample(by_style[style], N_EXAM // len(by_style))
        rng.shuffle(frases)
        frases = [f["frase"] for f in frases[:N_EXAM]]
        frases_path.write_text(json.dumps(frases, ensure_ascii=False, indent=1), encoding="utf-8")
    exam = load_exam()

    async def index(_):
        return web.FileResponse(HERE / "static_review" / "index.html")

    async def state(_):
        done = [i for i in range(len(frases)) if str(i) in exam]
        return web.json_response({"total": len(frases), "done": done})

    async def frase(req):
        i = int(req.match_info["i"])
        rec = exam.get(str(i), {})
        cands = [by_ine[lugares[j]["ine"]] for j in bm.top(tokens(frases[i]), N_CAND)]
        extra = [by_ine[x] for x in rec.get("marcas", {}) if x not in {c["ine"] for c in cands}]
        return web.json_response({"i": i, "frase": frases[i], "candidatos": [card(c) for c in extra + cands],
                                  "marcas": rec.get("marcas", {}), "mala": rec.get("mala", False),
                                  "nota": rec.get("nota", "")})

    async def buscar(req):
        q = norm(req.query.get("q", "")).strip()
        if len(q) < 2:
            return web.json_response([])
        hits = [l for l in lugares if q in norm(l["name"])]
        hits.sort(key=lambda l: (not norm(l["name"]).startswith(q), -(l["pop"] or 0)))
        return web.json_response([card(l) for l in hits[:15]])

    async def marcar(req):
        d = await req.json()
        i = int(d["i"])
        exam[str(i)] = {"frase": frases[i], "marcas": {k: int(v) for k, v in d.get("marcas", {}).items() if int(v) > 0},
                        "mala": bool(d.get("mala")), "nota": d.get("nota", "")}
        save_exam(exam)
        return web.json_response({"ok": True, "done": len(exam)})

    # Examen a ciegas (big_blind.py): la página nunca recibe de quién es cada municipio.
    blind_path = BIG / "ciego_sets.json"
    blind = json.loads(blind_path.read_text(encoding="utf-8")) if blind_path.exists() else []
    votes_path = BIG / "ciego.json"
    votes = json.loads(votes_path.read_text(encoding="utf-8")) if votes_path.exists() else {}

    async def ciego_page(_):
        return web.FileResponse(HERE / "static_review" / "ciego.html")

    async def ciego_state(_):
        return web.json_response({"total": len(blind), "done": [int(k) for k in votes]})

    async def ciego_item(req):
        i = int(req.match_info["i"])
        return web.json_response({"i": i, "frase": blind[i]["frase"],
                                  "items": [card(by_ine[x]) for x in blind[i]["items"]],
                                  "votos": votes.get(str(i), {})})

    async def ciego_marcar(req):
        d = await req.json()
        votes[str(int(d["i"]))] = {k: int(v) for k, v in d["votos"].items()}
        tmp = BIG / "ciego.json.tmp"
        tmp.write_text(json.dumps(votes, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(votes_path)
        return web.json_response({"ok": True, "done": len(votes)})

    app = web.Application()
    app.router.add_get("/ciego", ciego_page)
    app.router.add_get("/api/ciego/state", ciego_state)
    app.router.add_get("/api/ciego/{i}", ciego_item)
    app.router.add_post("/api/ciego/marcar", ciego_marcar)
    app.router.add_get("/", index)
    app.router.add_get("/api/state", state)
    app.router.add_get("/api/frase/{i}", frase)
    app.router.add_get("/api/buscar", buscar)
    app.router.add_post("/api/marcar", marcar)
    print(f"[examen] {len(frases)} frases, {len(exam)} hechas -> http://{args.host}:{args.port}/")
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
