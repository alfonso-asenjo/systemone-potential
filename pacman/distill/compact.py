"""El mismo estado y las mismas preguntas que ve jev, en corto, para que quepan en Laya.

jev recibe unos 1.050 tokens por casilla: el estado en JSON con nombres largos y unas
instrucciones pensadas para un modelo que no se ha entrenado en este juego. Laya lee como
mucho 1.024 y va a aprender de ejemplos, así que no necesita la explicación de las reglas:
basta con los números que separan una salida de otra. Objetivo, unos 200 tokens.

Lo usan tanto el conversor de logs (dataset.py) como el proveedor en partida, para que el
alumno vea en juego exactamente el formato con el que se entrenó.
"""
from __future__ import annotations

from typing import Any

ORDER = ("left", "right", "up", "down")
FAR = 99
ESCAPE_ROOM_OPEN = 12


def _dist(v: Any) -> str:
    return "none" if v is None or v >= FAR else str(v)


def describe_exit(info: dict[str, Any], peers: list[dict[str, Any]] | None = None) -> str:
    room = info.get("escape_room")
    room_txt = "?" if room is None else ("open" if room >= ESCAPE_ROOM_OPEN else f"trap {room}")
    parts = [
        f"room {room_txt}",
        f"rival {_dist(info.get('nearest_ghost'))}",
        f"pellet {_dist(info.get('nearest_pellet_dist'))}",
        f"{info.get('pellets_within_8') or 0} near",
    ]
    if info.get("power_pellet_dist") is not None:
        parts.append(f"trophy {info['power_pellet_dist']}")
    if info.get("frightened_ghost_dist") is not None:
        parts.append(f"frightened {info['frightened_ghost_dist']}")
    text = ", ".join(parts)
    tags = compare_tags(info, peers) if peers else []
    return text + (" [" + ", ".join(tags) + "]" if tags else "")


# Medido en el primer alumno: con solo los números sueltos, Laya acertaba la salida de jev
# en el 61 % de los cruces, por debajo de la regla de seguridad (76 %). Un codificador de
# texto compara mal números repartidos entre opciones, así que el código los compara y lo
# dice en palabras. Solo describe; decidir sigue siendo cosa del modelo.
_COMPARE = (
    # (campo, mayor es mejor, etiqueta si es la mejor, etiqueta si es la peor, valor si falta)
    ("escape_room", True, "most room", "least room", ESCAPE_ROOM_OPEN),
    ("nearest_ghost", True, "rival farthest", "rival closest", FAR),
    ("pellets_within_8", True, "most pellets", "fewest pellets", 0),
    ("nearest_pellet_dist", False, "pellet nearest", None, FAR),
    ("power_pellet_dist", False, "trophy nearest", None, FAR),
    ("frightened_ghost_dist", False, "frightened nearest", None, FAR),
)


def compare_tags(info: dict[str, Any], peers: list[dict[str, Any]]) -> list[str]:
    tags = []
    for key, higher, best, worst, missing in _COMPARE:
        vals = [missing if p.get(key) is None else p[key] for p in peers]
        if len(set(vals)) < 2:
            continue  # todas iguales: no distingue nada
        mine = missing if info.get(key) is None else info[key]
        top, bottom = (max(vals), min(vals)) if higher else (min(vals), max(vals))
        if mine == top:
            tags.append(best)
        elif worst and mine == bottom:
            tags.append(worst)
    return tags


def state_text(state: dict[str, Any]) -> str:
    spain = state.get("spain", {})
    power = state.get("power_mode") or {}
    lines = [
        f"Level {state.get('level', 1)}, lives {state.get('lives', 3)}, "
        f"{state.get('pellets_left', 0)} pellets left, "
        + (f"trophy active {power.get('seconds_left', 0):.0f}s." if power.get("active") else "no trophy active.")
    ]
    heading, behind = spain.get("heading"), spain.get("behind")
    by_exit = state.get("by_exit", {})
    lines.append(f"Heading {heading}.")
    for d in ORDER:
        if d in by_exit:
            tag = " (behind)" if d == behind else ""
            lines.append(f"{d}{tag}: {describe_exit(by_exit[d])}.")
    if behind in by_exit:
        lines.append(behind_vs_ahead(by_exit, behind))
    rivals = []
    for g in state.get("ghosts", []):
        if g.get("state") == "in_house" or (g.get("dist") or FAR) >= FAR:
            continue
        mood = "frightened" if g.get("state") == "frightened" else g.get("role", "")
        rivals.append(f"{g['name']} {mood} {g['dist']}" + (" closing" if g.get("approaching") else ""))
    lines.append("Rivals: " + ("; ".join(rivals) if rivals else "none in sight") + ".")
    since = spain.get("tiles_since_turn_back")
    if since is not None and since < 1000:
        lines.append(f"Turned back {since} tiles ago.")
    return "\n".join(lines)


# Medido en la v2: el Noul de dar la vuelta del alumno se quedaba entre 0,22 y 0,23 y no
# coincidía con ninguna de las 30 vueltas de jev, y en partida jev se dio la vuelta por su
# cuenta 40 veces en 6 partidas. Es la misma trampa que los cruces: la comparación entre
# delante y detrás estaba repartida en números sueltos, así que el código la dice en palabras.
def behind_vs_ahead(by_exit: dict[str, Any], behind: str) -> str:
    back = by_exit[behind]
    ahead = [v for d, v in by_exit.items() if d != behind]
    if not ahead:
        return "Behind vs ahead: dead end ahead."

    def val(info, key, missing):
        return missing if info.get(key) is None else info[key]

    notes = []
    room_b = val(back, "escape_room", ESCAPE_ROOM_OPEN)
    room_a = max(val(a, "escape_room", ESCAPE_ROOM_OPEN) for a in ahead)
    if room_a < ESCAPE_ROOM_OPEN:
        notes.append("every way ahead is a trap")
    notes.append("more room behind" if room_b > room_a else "less room behind" if room_b < room_a
                 else "same room behind")
    ghost_b = val(back, "nearest_ghost", FAR)
    ghost_a = min(val(a, "nearest_ghost", FAR) for a in ahead)
    if ghost_a < ghost_b:
        notes.append("rival closer ahead")
    elif ghost_b < ghost_a:
        notes.append("rival closer behind")
    pel_b = back.get("pellets_within_8") or 0
    pel_a = max(a.get("pellets_within_8") or 0 for a in ahead)
    if pel_a == 0 and pel_b > 0:
        notes.append("pellets only behind")
    elif pel_b > pel_a:
        notes.append("more pellets behind")
    return "Behind vs ahead: " + ", ".join(notes) + "."


DANGER_LEVELS = [
    "no chasing rival within 6 tiles",
    "chasing rival 4-6 tiles away or closing in",
    "chasing rival 2-3 tiles away",
    "chasing rival adjacent or every exit leads to one",
]


def questions(exits: list[str], state: dict[str, Any]) -> dict[str, Any]:
    """Las mismas cinco preguntas que pacman/questions.py, con el mismo reparto."""
    by_exit = state.get("by_exit", {})
    legal = [d for d in ORDER if d in exits]
    qs: dict[str, Any] = {}
    if len(legal) >= 2:
        qs["direction"] = {
            "type": "choice",
            "instructions": "Pac-man at a fork, chased by ghosts. Which exit should Spain take?",
            "criteria": {d: describe_exit(by_exit.get(d, {}), [by_exit.get(e, {}) for e in legal])
                         for d in legal},
        }
    qs["danger"] = {"type": "score", "instructions": "How dangerous is Spain's situation?",
                    "criteria": DANGER_LEVELS}
    qs["turn_back"] = {"type": "noul", "instructions": "Should Spain turn round and go back the way she came?"}
    qs["go_for_power"] = {"type": "noul", "instructions": "Should Spain head for the nearest trophy now?"}
    qs["hunt"] = {"type": "noul", "instructions": "Is chasing a frightened rival worth more now than pellets?"}
    return qs
