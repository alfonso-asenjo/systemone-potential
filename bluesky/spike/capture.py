"""Fase 1: cuánto trae el flujo público de Bluesky (Jetstream, sin clave).

Guarda solo texto, idioma y hora; nunca el autor. Uso: python capture.py [segundos]
"""
import asyncio, json, sys, time, collections
import aiohttp

URL = "wss://jetstream2.us-east.bsky.network/subscribe?wantedCollections=app.bsky.feed.post"

async def main(seconds):
    n, langs, out = 0, collections.Counter(), open("sample.jsonl", "w", encoding="utf-8")
    t0 = time.time()
    async with aiohttp.ClientSession() as s, s.ws_connect(URL, heartbeat=20) as ws:
        async for msg in ws:
            if time.time() - t0 > seconds:
                break
            ev = json.loads(msg.data)
            c = ev.get("commit") or {}
            if ev.get("kind") != "commit" or c.get("operation") != "create":
                continue
            rec = c.get("record") or {}
            text = (rec.get("text") or "").strip()
            if not text:
                continue
            lang = (rec.get("langs") or ["?"])[0].split("-")[0]
            n += 1; langs[lang] += 1
            out.write(json.dumps({"t": round(time.time() - t0, 2), "lang": lang, "text": text}, ensure_ascii=False) + "\n")
    el = time.time() - t0
    print(f"{n} posts con texto en {el:.0f} s = {n/el:.1f} posts/s")
    print("idiomas:", ", ".join(f"{k} {v/n:.0%}" for k, v in langs.most_common(10)))
    print(f"castellano: {langs['es']/el:.2f} posts/s")

asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 60))
