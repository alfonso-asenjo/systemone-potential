"""Laya (sin entrenar) contra jev en el mapa: 30 frases, jev como referencia.

    .venv-laya/Scripts/python mapa/tests/laya_vs_jev.py
Mide, frente a la respuesta de jev (tests/jev_reference.json): misma zona ganadora,
mismo lugar, y si el lugar de jev está en el top 10 de Laya. Prueba varias formas de
preguntar, que es lo único que se puede tocar sin entrenar.
"""
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import laya_map  # noqa: E402

P = json.loads((HERE.parent / "static" / "places.json").read_text(encoding="utf-8"))
REF = json.loads((HERE / "jev_reference.json").read_text(encoding="utf-8"))
NAME = {str(p["id"]): p["name"] for p in P}
IDS = [str(p["id"]) for p in P]

VARIANTS = {
    "instrucciones en inglés": dict(),
    "instrucciones en castellano": dict(
        INSTRUCTIONS_ZONE="Alguien describe el sitio de España al que quiere ir. ¿Qué zona de España encaja mejor?",
        INSTRUCTIONS_PLACE="Alguien describe el sitio de España al que quiere ir. ¿Qué lugar encaja mejor?"),
    "castellano + 'Busco…'": dict(
        INSTRUCTIONS_ZONE="¿Qué zona de España encaja mejor con lo que busca esta persona?",
        INSTRUCTIONS_PLACE="¿Qué lugar encaja mejor con lo que busca esta persona?",
        _state="Busco un sitio en España para: {}"),
    "torneo, castellano + 'Busco…'": dict(
        INSTRUCTIONS_PLACE="¿Qué lugar encaja mejor con lo que busca esta persona?",
        _state="Busco un sitio en España para: {}", _tournament=True),
    "torneo, instrucciones en inglés": dict(_tournament=True),
}


def run(lm, variant):
    orig = {k: getattr(laya_map, k) for k in variant if not k.startswith("_")}
    for k, v in variant.items():
        if not k.startswith("_"):
            setattr(laya_map, k, v)
    fmt = variant.get("_state", "{}")
    zone_hit = place_hit = top10 = 0
    ms, rows = [], []
    for text, ref in REF.items():
        r = (lm.rank_tournament if variant.get("_tournament") else lm.rank)(fmt.format(text), IDS)
        ranked = sorted(r["probs"], key=r["probs"].get, reverse=True)
        top_zone = max(r["zone_probs"], key=r["zone_probs"].get)
        zone_hit += lm.zone_of[int(ref["choice"])] == top_zone
        place_hit += ranked[0] == ref["choice"]
        top10 += ref["choice"] in ranked[:10]
        ms.append(r["latency_ms"])
        rows.append((text, NAME[ref["choice"]], NAME[ranked[0]], top_zone))
    for k, v in orig.items():
        setattr(laya_map, k, v)
    n = len(REF)
    return {"zona": zone_hit / n, "lugar": place_hit / n, "top10": top10 / n,
            "ms": statistics.median(ms)}, rows


if __name__ == "__main__":
    lm = laya_map.LayaMap(P, "multilingual")
    for name, v in VARIANTS.items():
        res, rows = run(lm, v)
        print(f"{name:32s} zona {res['zona']:.0%}  lugar {res['lugar']:.0%}  "
              f"lugar de jev en su top 10 {res['top10']:.0%}  {res['ms']:.0f} ms")
        if "-v" in sys.argv:
            for t, j, l, z in rows:
                print(f"   {t[:34]:34s} jev {j:26s} laya {l:24s} ({z})")
