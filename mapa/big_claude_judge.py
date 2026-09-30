"""Claude juzga a ciegas las 50 frases del examen.

Hasta ahora el juez era gpt-6-luna, el mismo modelo que eligió las etiquetas: se juzgaba a sí
mismo. Aquí se mezclan los 10 primeros del alumno (buscador + Laya), del buscador solo y del
profesor, y la clave de quién propuso cada municipio queda en otro fichero que no se abre
hasta tener los votos.

    .venv-laya/Scripts/python mapa/big_claude_judge.py prepare     # sets + clave
    python mapa/big_claude_judge.py show 0 10                      # frases 0-9, sin clave
    python mapa/big_claude_judge.py report                         # con data/big/claude_votos.json
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIG = HERE / "data" / "big"
SETS = BIG / "claude_sets.json"
KEYS = BIG / "claude_clave.json"      # no se abre hasta el informe
VOTES = BIG / "claude_votos.json"


def prepare():
    import laya
    from big_rerank import OUT, rerank
    from big_tree import Tree, load_labels
    tree = Tree()
    agent = laya.load(str(OUT), device="cuda")
    rng = random.Random(99)
    sets, keys = [], []
    for r in load_labels(exam=True):
        lists = {"alumno": rerank(agent, tree, r["frase"], r["candidatos"])[:10],
                 "buscador": r["candidatos"][:10],
                 "profesor": [x for x, _ in r["elegidos"]][:10]}
        items = list(dict.fromkeys(x for l in lists.values() for x in l))
        rng.shuffle(items)
        sets.append({"frase": r["frase"], "items": items})
        keys.append(lists)
    SETS.write_text(json.dumps(sets, ensure_ascii=False, indent=1), encoding="utf-8")
    KEYS.write_text(json.dumps(keys, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(sets)} frases, {sum(len(s['items']) for s in sets)} municipios a juzgar")


def show(a: int, b: int):
    lug = {l["ine"]: l for l in json.loads((BIG / "lugares.json").read_text(encoding="utf-8"))}
    sets = json.loads(SETS.read_text(encoding="utf-8"))
    for i in range(a, min(b, len(sets))):
        s = sets[i]
        print(f"\n## {i}. {s['frase']}")
        for j, ine in enumerate(s["items"]):
            l = lug[ine]
            where = {"island": "isla", "africa": "África"}.get(l["reach"], f"{l['hours']}h")
            print(f"{j:2d} {l['name']} ({l['prov']}; {l['pop']} hab; {l['elev']} m; {where}; "
                  f"{'costa' if l['costero'] else 'interior'}) {l['rasgos'] or '-'}")


def report():
    sets = json.loads(SETS.read_text(encoding="utf-8"))
    keys = json.loads(KEYS.read_text(encoding="utf-8"))
    votes = json.loads(VOTES.read_text(encoding="utf-8"))
    acc = {"alumno": [], "buscador": [], "profesor": []}
    for i, (s, k) in enumerate(zip(sets, keys)):
        good = {s["items"][j] for j in votes.get(str(i), [])}
        for name, l in k.items():
            if l:
                acc[name].append(sum(x in good for x in l) / len(l))
    n = len(acc["alumno"])
    for name, v in acc.items():
        print(f"  {name:9s} acierto@10 según Claude: {sum(v) / len(v):.0%}  ({len(v)} frases)")
    diffs = [a - b for a, b in zip(acc["alumno"], acc["buscador"])]
    m = sum(diffs) / n
    sd = (sum((d - m) ** 2 for d in diffs) / (n - 1)) ** 0.5
    print(f"  alumno - buscador: {m:+.0%} ±{1.96 * sd / n ** 0.5:.0%} (95 %); gana {sum(d > 0 for d in diffs)}, "
          f"pierde {sum(d < 0 for d in diffs)}, empata {sum(d == 0 for d in diffs)}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "prepare":
        prepare()
    elif cmd == "show":
        show(int(sys.argv[2]), int(sys.argv[3]))
    else:
        report()
