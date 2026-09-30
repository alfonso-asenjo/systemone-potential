"""Graba unos minutos de «La casa de internet» para publicarla sin servidor.

Se conecta al servidor en marcha como un navegador más y guarda lo que recibe la página: la
historia del arranque y cada tanda de posts con sus contadores. Nunca guarda el texto de los
posts (son de otras personas y el fichero va a ser público), ni el idioma: solo emoción, su
probabilidad y tema. casa.html lo reproduce en bucle con ?grabacion=<fichero>.

    .venv-laya/Scripts/python bluesky/server.py            # en otra consola, en directo
    .venv-laya/Scripts/python bluesky/record.py [minutos]  # -> bluesky/static/grabacion.json

Graba con el equipo holgado de memoria y el servidor ya caliente: si el servidor se atasca, la
grabación se atasca con él y la casa se queda sin gente. El 29-09 el primer minuto salió a 6-17
posts/s con parones de hasta 9 s (el equipo iba sin memoria) y hubo que recortarlo; al terminar
se avisa si hay huecos de más de 2 s.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import aiohttp

OUT = Path(__file__).resolve().parent / "static" / "grabacion.json"
URL = "ws://127.0.0.1:8790/ws"
# lo que usa casa.html de cada tanda; el resto de contadores no hace falta publicarlo
STATS = ("posts_per_s", "classified", "ms_per_decision", "emotions", "topics", "jev_cost_usd")


def slim(stats: dict) -> dict:
    return {k: stats[k] for k in STATS if k in stats}


async def main(minutes: float) -> None:
    rec = {"recorded_at": time.time(), "minutes": minutes, "hello": None, "batches": []}
    t0 = time.perf_counter()
    async with aiohttp.ClientSession() as s, s.ws_connect(URL, heartbeat=20) as ws:
        async for msg in ws:
            m = json.loads(msg.data)
            t = round(time.perf_counter() - t0, 2)
            if m["type"] == "hello":
                rec["hello"] = {"history": m["history"], "stats": slim(m["stats"])}
            elif m["type"] == "batch":
                posts = [[p["emotion"], round(p["emotion_p"], 2), p["topic"]] for p in m["posts"]]
                rec["batches"].append([t, posts, slim(m["stats"])])
            if t > minutes * 60:
                break
    OUT.write_text(json.dumps(rec, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    n = sum(len(b[1]) for b in rec["batches"])
    print(f"{len(rec['batches'])} tandas, {n} posts, {OUT.stat().st_size / 1e6:.1f} MB -> {OUT}")
    ts = [b[0] for b in rec["batches"]]
    gaps = [(ts[i], ts[i + 1] - ts[i]) for i in range(len(ts) - 1) if ts[i + 1] - ts[i] > 2]
    if gaps:
        print(f"AVISO: {len(gaps)} parones de más de 2 s (el primero en t={gaps[0][0]:.0f} s); "
              "conviene recortarlos o volver a grabar con más memoria libre")


if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 10))
