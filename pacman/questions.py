"""Las preguntas que se le hacen a jev, una llamada por casilla.

Regla de la documentación de jev, aprendida a base de medir en este proyecto: no preguntar
lo que el código sabe calcular, un solo juicio por pregunta, y describir cada opción por
aquello que de verdad la distingue.

Dos lecciones que costaron una partida entera cada una:

- Con las salidas descritas como "ve a la izquierda" y "ve a la derecha", jev respondía con
  un 4 % de confianza: desde el texto de las opciones no había nada que las separase. Cada
  salida lleva ahora sus propios números.
- Dar la vuelta era una salida más del Choice, así que competía de tú a tú con seguir
  adelante. El resultado era España yendo y viniendo: el 23 % de las decisiones eran medias
  vueltas, casi todas con mucha confianza. Volver es ahora un juicio aparte, un Noul con su
  propio listón, porque deshacer camino cuesta algo que la pregunta anterior no reflejaba.
"""
from __future__ import annotations

from typing import Any

ORDER = ("left", "right", "up", "down")

# Tiene que coincidir con ESCAPE_ROOM_OPEN de static/jev.js: el tope que significa campo abierto.
ESCAPE_ROOM_OPEN = 12

DIRECTION_INSTRUCTIONS = (
    "You steer Spain through a maze while rival ghosts chase her. Touching a chasing rival "
    "costs a life. While a trophy is active the rivals turn frightened and eating one scores "
    "200 to 1600 points. She has already cleared the pellets she has walked over, so the way "
    "to score is to head where pellets are still left. Each option says how many tiles she "
    "can run that way before a chasing rival could cut her off (12 means open ground), "
    "how far the nearest "
    "chasing rival is that way, how far the nearest uneaten pellet is, how many pellets are "
    "within 8 tiles, and how far the nearest trophy and frightened rival are. Keep her alive "
    "first: never take a trapped exit when another has more room to run, because a trap has "
    "no way out; after that avoid exits with a chasing rival close by. Among safe exits prefer the one with "
    "uneaten pellets nearby, take a trophy when rivals are closing in, and chase frightened "
    "rivals while a trophy is running. Which way should she go at this fork?"
)

DANGER_LEVELS = [
    "No chasing rival within 6 tiles of Spain.",
    "A chasing rival 4 to 6 tiles away, or one further off but closing in.",
    "A chasing rival 2 or 3 tiles away, or one closing fast down the same corridor.",
    "A chasing rival is next to Spain, or every exit leads towards one.",
]

GO_FOR_POWER = (
    "Spain should head for the nearest trophy now: rivals are closing in and the trophy is "
    "near enough to reach before they catch her."
)

HUNT = (
    "A trophy is active and chasing a frightened rival is worth more right now than "
    "collecting pellets."
)

# Turning round undoes ground already covered, so it has to earn itself, not merely win a
# comparison against carrying on.
TURN_BACK = (
    "Spain should turn round and go back the way she came. This is only worth it when the "
    "way ahead is clearly worse than the way behind: the way ahead is a trap with little "
    "room to run while the way behind has clearly more, or the road ahead has no pellets left while the road behind leads to some. She "
    "has just walked the way behind, so its pellets are gone; `behind` says what is back "
    "there now. Turning round also costs her the ground she just covered, and doing it "
    "repeatedly leaves her pacing on the spot, so say no unless going on is genuinely worse."
)


def describe_exit(direction: str, info: dict[str, Any], label: str | None = None) -> str:
    """Una opción descrita por los números que la separan de las demás."""
    parts = [f"{label or f'Take the {direction} exit'}."]

    ghost = info.get("nearest_ghost")
    if ghost is None or ghost >= 99:
        parts.append("No chasing rival can be seen that way.")
    elif ghost <= 2:
        parts.append(f"A chasing rival is {ghost} tiles away down there, almost on top of her.")
    else:
        parts.append(f"The nearest chasing rival that way is {ghost} tiles away.")

    nearest = info.get("nearest_pellet_dist")
    if nearest is None:
        parts.append("There are no uneaten pellets left down that way at all.")
    elif nearest <= 2:
        parts.append(f"The nearest uneaten pellet is {nearest} tiles away, right there.")
    else:
        parts.append(f"The nearest uneaten pellet is {nearest} tiles away.")

    room = info.get("escape_room")
    if room is not None:
        if room >= ESCAPE_ROOM_OPEN:
            parts.append("Open ground: no chasing rival can cut her off that way.")
        elif room <= 1:
            parts.append("A trap: a chasing rival cuts her off right away.")
        else:
            parts.append(f"A trap: she can run only {room} tiles before a chasing rival "
                         "cuts her off.")

    pellets = info.get("pellets_within_8") or 0
    parts.append(f"{pellets} pellets lie within 8 tiles of it." if pellets
                 else "No pellets remain within 8 tiles of it.")

    trophy = info.get("power_pellet_dist")
    if trophy is not None:
        parts.append(f"The nearest trophy is {trophy} tiles away.")

    frightened = info.get("frightened_ghost_dist")
    if frightened is not None:
        parts.append(f"A frightened rival is {frightened} tiles away, worth eating.")

    return " ".join(parts)


def build(exits: list[str], state: dict[str, Any] | None = None) -> dict[str, Any]:
    """`exits` son solo las salidas hacia delante. Volver nunca es una de ellas."""
    state = state or {}
    by_exit = state.get("by_exit", {})
    legal = [d for d in ORDER if d in exits]

    questions: dict[str, Any] = {}

    # Sin bifurcación no hay nada que elegir: en un pasillo solo queda seguir o volver.
    if len(legal) >= 2:
        questions["direction"] = {
            "type": "choice",
            "instructions": DIRECTION_INSTRUCTIONS,
            "criteria": {d: describe_exit(d, by_exit.get(d, {})) for d in legal},
        }

    questions["danger"] = {
        "type": "score",
        "instructions": "How dangerous is Spain's situation right now?",
        "criteria": DANGER_LEVELS,
    }
    questions["turn_back"] = {"type": "noul", "instructions": TURN_BACK}
    questions["go_for_power"] = {"type": "noul", "instructions": GO_FOR_POWER}
    questions["hunt"] = {"type": "noul", "instructions": HUNT}
    return questions
