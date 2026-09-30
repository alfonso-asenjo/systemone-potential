"""Segundo juez para el reordenador conocido: Claude, a ciegas, solo con los municipios nuevos.

Los 10 primeros de bge-reranker-v2-m3 que Claude no juzgó en big_claude_judge.py se mezclan, en
cada frase, con 2 que sí juzgó (controles), sin decir cuáles son. La clave queda en otro fichero.
Los controles miden si Claude juzga igual que la primera vez.

    python mapa/big_claude_judge2.py prepare
    python mapa/big_claude_judge2.py show 0 10
    python mapa/big_claude_judge2.py report          # con data/big/claude2_votos.json

Tercera ronda, para el reordenador afinado (los controles vuelven a salir del primer examen):
    python mapa/big_claude_judge2.py prepare 3 bge_afinado bge-listas-afinado.json
    python mapa/big_claude_judge2.py show 0 10 3
    python mapa/big_claude_judge2.py report 3 bge_afinado bge-listas-afinado.json
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BIG = HERE / "data" / "big"
OLD_SETS, OLD_VOTES = BIG / "claude_sets.json", BIG / "claude_votos.json"
ROUND, LIST, LISTS = "2", "bge", "bge-listas.json"


def files():
    return (BIG / f"claude{ROUND}_sets.json", BIG / f"claude{ROUND}_clave.json", BIG / f"claude{ROUND}_votos.json")


def old_verdicts():
    sets = json.loads(OLD_SETS.read_text(encoding="utf-8"))
    votes = json.loads(OLD_VOTES.read_text(encoding="utf-8"))
    return [{x: (j in set(votes[str(i)])) for j, x in enumerate(s["items"])} for i, s in enumerate(sets)]


def prepare():
    SETS, KEYS, _ = files()
    lists = json.loads((BIG / LISTS).read_text(encoding="utf-8"))
    old = old_verdicts()
    rng = random.Random(7)
    sets, keys = [], []
    for i, l in enumerate(lists):
        new = [x for x in l[LIST] if x not in old[i]]
        controls = rng.sample(sorted(old[i]), 2 if ROUND == "2" else 3)
        items = new + controls
        rng.shuffle(items)
        sets.append({"frase": l["frase"], "items": items})
        keys.append({"nuevos": new, "controles": {c: old[i][c] for c in controls}})
    SETS.write_text(json.dumps(sets, ensure_ascii=False, indent=1), encoding="utf-8")
    KEYS.write_text(json.dumps(keys, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(sets)} frases, {sum(len(s['items']) for s in sets)} municipios a juzgar")


def show(a: int, b: int):
    SETS, _, _ = files()
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
    SETS, KEYS, VOTES = files()
    lists = json.loads((BIG / LISTS).read_text(encoding="utf-8"))
    sets = json.loads(SETS.read_text(encoding="utf-8"))
    keys = json.loads(KEYS.read_text(encoding="utf-8"))
    votes = json.loads(VOTES.read_text(encoding="utf-8"))
    old = old_verdicts()
    agree, flips, prec = [], {"si_a_no": 0, "no_a_si": 0, "no_antes": 0}, {k: [] for k in ("alumno", "buscador", "profesor", LIST)}
    for i, (l, s, k) in enumerate(zip(lists, sets, keys)):
        good_now = {s["items"][j] for j in votes[str(i)]}
        for c, was in k["controles"].items():
            agree.append((c in good_now) == was)
            flips["no_antes"] += not was
            flips["si_a_no"] += was and c not in good_now
            flips["no_a_si"] += (not was) and c in good_now
        verdict = {**old[i], **{x: x in good_now for x in k["nuevos"]}}
        for name in prec:
            prec[name].append(np.mean([verdict[x] for x in l[name]]))
    d = np.array(prec[LIST]) - np.array(prec["alumno"])
    rng = np.random.default_rng(0)
    boots = [rng.choice(d, len(d)).mean() for _ in range(10000)]
    out = {"acierto@10 (juez Claude, a ciegas)": {k: round(float(np.mean(v)), 3) for k, v in prec.items()},
           f"{LIST} - alumno": {"diferencia": round(float(d.mean()), 3),
                            "ic95": [round(float(np.percentile(boots, 2.5)), 3), round(float(np.percentile(boots, 97.5)), 3)],
                            "gana": int((d > 0).sum()), "empata": int((d == 0).sum()), "pierde": int((d < 0).sum())},
           "controles_coinciden": f"{sum(agree)}/{len(agree)}", "controles_cambios": flips}
    (BIG / f"claude{ROUND}-report.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd == "show":
        a, b, rest = int(rest[0]), int(rest[1]), rest[2:]
    if rest:
        ROUND, LIST, LISTS = rest[0], rest[1] if len(rest) > 1 else LIST, rest[2] if len(rest) > 2 else LISTS
    if cmd == "prepare":
        prepare()
    elif cmd == "show":
        show(a, b)
    else:
        report()
