"""Convertir las respuestas de jev en un movimiento.

Tres guardas, las tres visibles en el panel para que se vea cuándo a jev se le lleva la
contraria:

  umbral de confianza  por debajo del umbral decide la regla de seguridad, que toma la
                       salida cuyo rival activo más cercano queda más lejos.
  listón para volver   dar la vuelta es un juicio propio, un Noul aparte, y necesita
                       superar su listón. El número no se parece al umbral de confianza
                       porque mide otra cosa, y está calibrado sobre lo medido.
  tiempo entre vueltas  el cliente ignora una vuelta si acaba de dar otra; ahí el juicio de
                       jev es razonable pero la secuencia no lo sería.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

CONFIDENCE_MIN = float(os.environ.get("PACMAN_CONFIDENCE_MIN", 0.25))

# El listón para volver está medido, no elegido: en 291 decisiones de tres partidas este
# Noul se movió entre 0,10 y 0,31 y nunca se acercó a un 0,70. Su escala está comprimida,
# pero su orden dice algo: correlaciona 0,64 con el peligro y -0,39 con la distancia al
# rival de delante, y las 16 respuestas por encima de 0,27 tenían peligro medio 1,6 y una
# cuarta parte de píldoras por delante que las bajas. Así que el listón va donde de verdad
# está la cola alta de sus respuestas, no donde estaría si el Noul llegara al 100 %.
TURN_BACK_MIN = float(os.environ.get("PACMAN_TURN_BACK_MIN", 0.28))

# A cuántas casillas del rival de delante la regla de seguridad da la vuelta por su cuenta,
# si el pasillo de delante es una trampa y el de detrás está libre.
FORCED_TURN_GHOST = 3

# Debe coincidir con ESCAPE_ROOM_OPEN de static/jev.js.
ESCAPE_ROOM_OPEN = 12
# Cuánto más sitio tiene que haber detrás para que volver cuente como huida.
TRAP_ROOM_GAP = 3


@dataclass
class Decision:
    direction: str
    confidence: float = 0.0
    danger: float = 0.0
    go_for_power: float = 0.0
    hunt: float = 0.0
    turn_back: float = 0.0
    turned_back: bool = False   # el juicio de volver superó el listón
    at_fork: bool = False       # había una bifurcación de verdad que elegir
    fallback: bool = False      # confianza baja, decidió la regla de seguridad
    forward: str = ""           # la salida hacia delante elegida, antes de mirar si vuelve
    escape: bool = False        # vuelve porque delante hay una trampa y detrás no
    forced: bool = False        # la vuelta la impuso la regla de seguridad, no jev
    vetoed: bool = False        # jev pidió volver hacia una trampa y la regla lo impidió
    probabilities: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "confidence": round(self.confidence, 4),
            "danger": round(self.danger, 3),
            "go_for_power": round(self.go_for_power, 4),
            "hunt": round(self.hunt, 4),
            "turn_back": round(self.turn_back, 4),
            "turned_back": self.turned_back,
            "at_fork": self.at_fork,
            "fallback": self.fallback,
            "forward": self.forward or self.direction,
            "escape": self.escape,
            "forced": self.forced,
            "vetoed": self.vetoed,
            "held": False,      # queda por compatibilidad con las grabaciones antiguas
        }


def safest_exit(state: dict[str, Any], exits: list[str]) -> str:
    """Primero la que deja más sitio para escapar, luego la más lejana del rival activo más
    cercano, y a igualdad la que más comida ofrece."""
    by_exit = state.get("by_exit", {})

    def score(d: str) -> tuple[float, float, float]:
        info = by_exit.get(d, {})
        room = info.get("escape_room")
        nearest = info.get("nearest_pellet_dist")
        return (room if room is not None else ESCAPE_ROOM_OPEN,
                info.get("nearest_ghost", 0) or 0,
                -(nearest if nearest is not None else 99))

    return max(exits, key=score) if exits else "left"


def interpret(answers: dict[str, Any], state: dict[str, Any], exits: list[str]) -> Decision:
    """`exits` son las salidas hacia delante; volver se decide aparte."""
    spain = state.get("spain") or {}
    behind = spain.get("behind")

    danger_ans = answers.get("danger", {}) or {}
    noul = lambda name: float((answers.get(name, {}) or {}).get("noul", 0.0) or 0.0)  # noqa: E731

    d = Decision(
        direction=exits[0] if exits else (behind or "left"),
        danger=float(danger_ans.get("score", 0.0) or 0.0),
        go_for_power=noul("go_for_power"),
        hunt=noul("hunt"),
        turn_back=noul("turn_back"),
    )

    direction = answers.get("direction")
    if direction:
        d.at_fork = True
        probs = {k: float(v) for k, v in (direction.get("probabilities") or {}).items()
                 if k in exits}
        d.probabilities = probs
        choice = direction.get("choice")
        d.confidence = float(direction.get("confidence", 0.0) or 0.0)
        if choice in exits and d.confidence >= CONFIDENCE_MIN:
            d.direction = choice
        else:
            d.direction = safest_exit(state, exits)
            d.fallback = True

    # El navegador la necesita si ignora la vuelta por el tiempo mínimo entre vueltas.
    d.forward = d.direction
    by_exit = state.get("by_exit", {})
    ahead_info = by_exit.get(d.forward) or {}
    ahead = ahead_info.get("escape_room")
    back = (by_exit.get(behind) or {}).get("escape_room") if behind else None
    # Trampa delante: poco sitio para correr, y detrás claramente más.
    trapped_ahead = (ahead is not None and back is not None and ahead < ESCAPE_ROOM_OPEN
                     and back >= ahead + TRAP_ROOM_GAP)

    # Volver hacia una trampa cuando delante hay más sitio: medido, jev lo hizo dos veces
    # seguidas en el túnel y llevó a España contra un rival a dos casillas.
    trapped_behind = (ahead is not None and back is not None and back < ESCAPE_ROOM_OPEN
                      and ahead > back)

    if behind and d.turn_back >= TURN_BACK_MIN and trapped_behind:
        d.vetoed = True
    elif behind and d.turn_back >= TURN_BACK_MIN:
        d.direction = behind
        d.turned_back = True
        # Una huida no espera al tiempo mínimo entre vueltas: medido en una partida, ese
        # tiempo bloqueó 5 de las 9 veces que jev acertó a salir de una trampa.
        d.escape = trapped_ahead
    elif trapped_ahead and (ahead_info.get("nearest_ghost") or 99) <= FORCED_TURN_GHOST:
        # Red de seguridad: jev dejó que España siguiera de frente hacia un rival en un
        # pasillo sin salida (2 de 11 veces medidas). Eso el código lo sabe, no es juicio.
        d.direction = behind
        d.turned_back = True
        d.escape = True
        d.forced = True

    return d
