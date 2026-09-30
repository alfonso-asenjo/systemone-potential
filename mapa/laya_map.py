"""Luces de España con Laya: un embudo en vez de una sola pregunta de 255 opciones.

Laya se hunde con muchas opciones (Banking77, 77 categorías: 0,43 frente a 0,87 de jev) y
lee como mucho 48 tokens por opción. Así que se le hacen, en una sola pasada por la GPU,
21 preguntas pequeñas:

  zona      ¿en qué zona de España? 20 opciones.
  z_<zona>  ¿qué lugar de esa zona? 20 opciones como mucho, una pregunta por zona.

y la probabilidad de cada lugar es P(zona) x P(lugar | zona). No se elige zona a ciegas:
el mapa entero se sigue encendiendo y un error en la zona solo baja la luz, no la apaga.

Sin entrenar: es Laya tal cual sale de Hugging Face.
"""
from __future__ import annotations

import os
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MODELS = {"typed": ROOT / "models" / "laya" / "typed-decisions",
          "multilingual": ROOT / "models" / "laya" / "multilingual"}

# Andalucía (39) y Castilla y León (35) pasan de 20 lugares: se parten por provincias.
SPLITS = {
    "Andalucía": {"Andalucía occidental": {"Sevilla", "Cádiz", "Huelva", "Córdoba"},
                  "Andalucía oriental": {"Málaga", "Granada", "Almería", "Jaén"}},
    "Castilla y León": {"Castilla y León norte": {"Burgos", "León", "Palencia", "Soria"},
                        "Castilla y León sur": {"Segovia", "Ávila", "Salamanca", "Valladolid", "Zamora"}},
}

ZONES = {
    "Galicia": "Galicia: costa atlántica y rías, verde y lluviosa, marisco, pulpo, Camino de Santiago",
    "Asturias": "Asturias: montaña verde junto al mar Cantábrico, Picos de Europa, sidra, fabada, pueblos marineros",
    "Cantabria": "Cantabria: costa cantábrica y montaña, playas de surf, cuevas prehistóricas, anchoas",
    "País Vasco": "País Vasco: costa cantábrica, pintxos y alta cocina, surf, ciudades con museos",
    "Navarra": "Navarra: Pirineo y bosques, San Fermín, Bardenas desérticas, verduras",
    "La Rioja": "La Rioja: vino, bodegas y viñedos, pueblos de interior, monasterios",
    "Aragón": "Aragón: Pirineo alto y esquí, pueblos de piedra, desierto y cañones, Zaragoza",
    "Cataluña": "Cataluña: Barcelona, Costa Brava y calas mediterráneas, Pirineo, cava, fiesta",
    "Comunidad Valenciana": "Comunidad Valenciana: playas mediterráneas, paella, Fallas, turismo de sol y fiesta",
    "Murcia": "Murcia: Mar Menor y calas, huerta, sol todo el año, calor",
    "Andalucía occidental": "Andalucía occidental: Sevilla, Córdoba, Cádiz y Huelva; flamenco, playas atlánticas de viento, jamón, fiesta",
    "Andalucía oriental": "Andalucía oriental: Málaga, Granada, Almería y Jaén; Alhambra, Sierra Nevada, Costa del Sol, desierto, olivos",
    "Extremadura": "Extremadura: interior tranquilo, dehesas, historia romana y conquistadores, jamón, cielos oscuros",
    "Castilla-La Mancha": "Castilla-La Mancha: llanuras y molinos, Toledo y Cuenca, queso manchego, interior tranquilo",
    "Madrid": "Madrid: gran ciudad con museos, vida nocturna y fiesta, sierra cercana",
    "Castilla y León norte": "Castilla y León norte: Burgos, León, Palencia y Soria; catedrales góticas, montaña, pueblos y silencio",
    "Castilla y León sur": "Castilla y León sur: Segovia, Ávila, Salamanca, Valladolid y Zamora; murallas, ciudades históricas, asado, vino",
    "Baleares": "Baleares: islas mediterráneas, calas turquesa, fiesta en Ibiza, hay que ir en avión o barco",
    "Canarias": "Canarias: islas volcánicas en el Atlántico, clima cálido todo el año, playas, estrellas, avión",
    "Ceuta y Melilla": "Ceuta y Melilla: ciudades en el norte de África, mezcla de culturas, barco o avión",
}

INSTRUCTIONS_ZONE = "Someone describes, in Spanish, the place in Spain they want to go. Which area of Spain fits best?"
INSTRUCTIONS_PLACE = "Someone describes, in Spanish, the place in Spain they want to go. Which of these places fits best?"


def load_zones(places: list[dict[str, Any]]) -> dict[int, str]:
    """La comunidad de cada lugar sale de los encabezados de data/places.txt."""
    region, zone_of, i = None, {}, 0
    for line in (HERE / "data" / "places.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("# ") and "|" not in line and not line.startswith(("# nombre", "# Las ")):
            region = line[2:].strip()
            continue
        if not line.strip() or line.startswith("#"):
            continue
        p = places[i]
        zone = region
        for sub, provs in SPLITS.get(region, {}).items():
            if p["prov"] in provs:
                zone = sub
        zone_of[p["id"]] = zone
        i += 1
    return zone_of


def short(p: dict[str, Any]) -> str:
    """Laya lee 48 tokens por opción: lo que distingue al lugar va primero."""
    coast = "interior" if p["coast"] == "interior" else f"costa {p['coast']}"
    reach = {"island": "isla", "africa": "África"}.get(p["reach"], f"{str(p['hours']).replace('.0', '')} h de Madrid")
    return f"{p['traits']}; {coast}; {p['pop']} hab.; {reach}"


def _best(probs: dict[str, float]) -> str:
    return max(probs, key=probs.get)


class LayaMap:
    provider = "laya (local, sin entrenar)"

    def __init__(self, places: list[dict[str, Any]], model: str = "multilingual"):
        import laya
        self.agent = laya.load(str(MODELS[model]), device="cuda")
        self.model = f"laya-{model}"
        self.places = {str(p["id"]): p for p in places}
        self.zone_of = load_zones(places)
        self.total_cost = 0.0
        self.total_calls = 0

    def questions(self, allowed_ids: list[str]) -> dict[str, Any]:
        groups: "OrderedDict[str, list[str]]" = OrderedDict()
        for pid in allowed_ids:
            groups.setdefault(self.zone_of[int(pid)], []).append(pid)
        qs: dict[str, Any] = {}
        if len(groups) > 1:
            qs["zona"] = {"type": "choice", "instructions": INSTRUCTIONS_ZONE,
                          "criteria": {z: ZONES[z] for z in groups}}
        for z, ids in groups.items():
            if len(ids) > 1:
                qs["z:" + z] = {"type": "choice", "instructions": INSTRUCTIONS_PLACE,
                                "criteria": {pid: f"{self.places[pid]['name']}: {short(self.places[pid])}" for pid in ids}}
        return qs, groups

    def rank(self, text: str, allowed_ids: list[str]) -> dict[str, Any]:
        qs, groups = self.questions(allowed_ids)
        t0 = time.perf_counter()
        res = self.agent.predict(text, qs, head_max_len=1000) if qs else {"answers": {}, "usage": {"input_tokens": 0}}
        latency = (time.perf_counter() - t0) * 1000
        ans = res["answers"]
        pz = ans["zona"]["probabilities"] if "zona" in ans else {next(iter(groups)): 1.0}
        probs = {}
        for z, ids in groups.items():
            within = ans["z:" + z]["probabilities"] if "z:" + z in ans else {ids[0]: 1.0}
            for pid in ids:
                probs[pid] = pz.get(z, 0.0) * within.get(pid, 0.0)
        s = sum(probs.values()) or 1.0
        probs = {k: v / s for k, v in probs.items()}
        best = max(probs, key=probs.get)
        self.total_calls += 1
        return {"probs": probs, "choice": best, "zone_probs": pz, "latency_ms": latency,
                "tokens": int(res["usage"]["input_tokens"]), "questions": len(qs),
                "confidence": ans.get("zona", {}).get("confidence")}

    def rank_tournament(self, text: str, allowed_ids: list[str]) -> dict[str, Any]:
        """Torneo: ronda por zona y final entre los campeones, sin descripciones de zona.

        Medido con 30 frases contra jev: la pregunta de la zona era el eslabón débil (Laya
        elegía Baleares o Extremadura para casi todo, 7-27 % de zonas iguales a jev), porque
        decidía sobre resúmenes escritos a mano. En la final compiten lugares reales.
        """
        qs, groups = self.questions(allowed_ids)
        qs.pop("zona", None)
        t0 = time.perf_counter()
        ans = self.agent.predict(text, qs, head_max_len=1000)["answers"] if qs else {}
        within = {z: (ans["z:" + z]["probabilities"] if "z:" + z in ans else {ids[0]: 1.0})
                  for z, ids in groups.items()}
        champions = {z: _best(w) for z, w in within.items()}
        final_q = {"final": {"type": "choice", "instructions": INSTRUCTIONS_PLACE,
                             "criteria": {pid: f"{self.places[pid]['name']}: {short(self.places[pid])}"
                                          for pid in champions.values()}}}
        final = (self.agent.predict(text, final_q, head_max_len=1000)["answers"]["final"]
                 if len(champions) > 1 else {"probabilities": {next(iter(champions.values())): 1.0}, "confidence": 1.0})
        latency = (time.perf_counter() - t0) * 1000
        pz = {z: final["probabilities"].get(pid, 0.0) for z, pid in champions.items()}
        probs = {pid: pz[z] * within[z].get(pid, 0.0) for z, ids in groups.items() for pid in ids}
        s = sum(probs.values()) or 1.0
        probs = {k: v / s for k, v in probs.items()}
        self.total_calls += 1
        return {"probs": probs, "choice": _best(probs), "zone_probs": pz, "latency_ms": latency,
                "questions": len(qs) + 1, "confidence": final.get("confidence")}
