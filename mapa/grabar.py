"""Graba las respuestas a las búsquedas de ejemplo de un mapa, para verlo sin servidor.

Se conecta al servidor en marcha como una página más, pregunta cada búsqueda de ejemplo y guarda
la respuesta tal cual. Con ?grabacion, las páginas responden a esas búsquedas con lo guardado
(GitHub Pages no tiene servidor ni gráfica). El coste que se guarda es el de cada búsqueda, no el
acumulado del servidor.

    python mapa/server.py                               # en otra consola: el mapa de 255 lugares (jev)
    python mapa/grabar.py 8780 mapa/static/grabacion.json
    .venv-laya/Scripts/python mapa/big_server.py        # el de los 8.131 municipios
    python mapa/grabar.py 8781 mapa/static_big/grabacion.json
"""
from __future__ import annotations

import asyncio
import datetime
import json
import re
import sys
from pathlib import Path

import aiohttp

HERE = Path(__file__).resolve().parent


def ejemplos(port: int) -> list[str]:
    """Las búsquedas de ejemplo tal como las tienen las páginas (el 8781 sirve dos: se juntan)."""
    files = [HERE / "static" / "map.js"] if port == 8780 else [HERE / "static_big" / "map.js", HERE / "static_big" / "carreteras.html"]
    out = []
    for f in files:
        block = re.search(r"const EXAMPLES = \[(.*?)\];", f.read_text(encoding="utf-8"), re.S).group(1)
        for s in re.findall(r"""['"]([^'"]+)['"]""", block):
            if s not in out:
                out.append(s)
    return out


async def grabar(port: int, out: Path):
    res, prev_cost = {}, 0.0
    async with aiohttp.ClientSession() as s, s.ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
        # una pregunta de calentamiento que no se guarda: la primera de un modelo recién cargado
        # tardaba 1.255 ms frente a ~370 las demás, y la página parecería lenta
        await ws.send_json({"type": "ask", "seq": 0, "text": "calentar"})
        async for msg in ws:
            if json.loads(msg.data).get("type") == "answer":
                break
        for i, text in enumerate(ejemplos(port), 1):
            await ws.send_json({"type": "ask", "seq": i, "text": text})
            async for msg in ws:
                m = json.loads(msg.data)
                if m.get("type") == "answer" and m.get("seq") == i:
                    break
            m.pop("seq", None)
            if m.get("total_cost_usd") is not None and i == 1:
                prev_cost = m["total_cost_usd"] - (m.get("cost_usd") or 0)   # descontar el calentamiento
            if m.get("total_cost_usd") is not None:
                m["total_cost_usd"], prev_cost = round(m["total_cost_usd"] - prev_cost, 6), m["total_cost_usd"]
            res[text] = m
            print(f"  {text!r}: {len(m.get('probs') or {})} lugares con probabilidad, {m.get('latency_ms')} ms")
    # quién respondió y cuándo: las páginas lo enseñan en el aviso de GRABACIÓN
    brain = next((m.get("brain") for m in res.values() if m.get("brain")), None)
    modelo = ("jev (TypeSafe), por API" if port == 8780 else
              "el reordenador afinado (bge-reranker), en una tarjeta gráfica de casa" if brain == "bge-reranker afinado" else
              "Laya destilada, en una tarjeta gráfica de casa")
    meses = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()
    hoy = datetime.date.today()
    res["_meta"] = {"fecha": f"{hoy.day} de {meses[hoy.month - 1]} de {hoy.year}", "modelo": modelo}
    out.write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(res)} búsquedas -> {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    asyncio.run(grabar(int(sys.argv[1]), Path(sys.argv[2])))
