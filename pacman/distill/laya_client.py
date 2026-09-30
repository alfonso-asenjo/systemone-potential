"""El alumno en partida: la misma interfaz que JevClient, pero Laya en local.

El servidor le pasa las preguntas de jev; de ellas solo se usan las salidas (las claves de
`direction`), porque el alumno se entrenó con el estado y las preguntas cortas de
compact.py y tiene que verlas igual en juego.

Umbrales propios, medidos sobre las partidas de examen y no copiados de jev, porque la
escala del alumno es otra (misma lección que el listón de dar la vuelta con jev). train.py
los mide y los guarda en rl_agent_config.json, bajo "pacman":
  confidence_min: con él el alumno cae en la regla de seguridad tan a menudo como jev con
      su 0,25 (el 12 % de los cruces). Con 0,25 la v2 habría caído la mitad de las veces.
  turn_back_min: el que le hace decir "vuelve" tan a menudo como jev.
La v2 no los traía: su Noul de dar la vuelta se movía entre 0,22 y 0,23 sin coincidir con
ninguna vuelta de jev, así que jugó con esa pregunta apagada y confianza mínima 0,018.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from compact import questions as compact_questions, state_text  # noqa: E402
from jevcraft.jev_client import JevResponse  # noqa: E402

STUDENT = Path(os.environ.get("LAYA_STUDENT", ROOT / "models" / "laya-pacman"))
V2_THRESHOLDS = {"confidence_min": 0.018, "turn_back_min": 1.01}  # 1,01: nunca
# LAYA_EXPLORE_T > 0: la salida se sortea con sus probabilidades (a esa temperatura) en vez de
# tomar siempre la más probable. Solo para partidas de práctica:
# sin variedad no hay partidas mejores entre las que elegir.
EXPLORE_T = float(os.environ.get("LAYA_EXPLORE_T", 0) or 0)


def explore(direction: dict | None) -> None:
    import random
    if not direction or not direction.get("probabilities"):
        return
    keys = list(direction["probabilities"])
    w = [max(1e-9, float(direction["probabilities"][k])) ** (1.0 / EXPLORE_T) for k in keys]
    pick = random.choices(keys, weights=w)[0]
    if pick != direction.get("choice"):
        direction["choice"], direction["explored"] = pick, True


class LayaClient:
    provider = "laya (local)"

    def __init__(self, model_dir: Path = STUDENT):
        import laya
        self.agent = laya.load(str(model_dir), device="cuda")
        self.model = model_dir.name
        self.total_calls = 0
        self.total_cost = 0.0
        self._lock = asyncio.Lock()

    async def decide(self, state, questions) -> JevResponse:
        exits = list((questions.get("direction") or {}).get("criteria") or {})
        qs = compact_questions(exits, state)
        text = state_text(state)
        async with self._lock:  # una GPU, una pregunta a la vez
            t0 = time.perf_counter()
            res = await asyncio.to_thread(self.agent.predict, text, qs)
            latency = (time.perf_counter() - t0) * 1000
        self.total_calls += 1
        if EXPLORE_T > 0:
            explore(res["answers"].get("direction"))
        return JevResponse(answers=res["answers"], latency_ms=latency, model=self.model,
                           input_tokens=int(res["usage"]["input_tokens"]))

    async def close(self):
        pass


def configure_thresholds(model_dir: Path = STUDENT) -> None:
    """Antes de importar decide.py, que lee los umbrales del entorno al cargarse."""
    with open(model_dir / "rl_agent_config.json") as f:
        th = json.load(f).get("pacman", V2_THRESHOLDS)
    os.environ["PACMAN_CONFIDENCE_MIN"] = str(th["confidence_min"])
    os.environ["PACMAN_TURN_BACK_MIN"] = str(th["turn_back_min"])
    print(f"[laya] {model_dir.name}: confianza mínima {th['confidence_min']}, "
          f"listón para volver {th['turn_back_min']}")
