"""Descarga la introducción de Wikipedia (es) de cada municipio: la fuente de la que el
profesor escribirá su descripción, para que no invente rasgos de los pueblos poco conocidos.

    python mapa/big_wiki.py   ->  mapa/data/big/wiki.jsonl  (se puede relanzar: continúa)
"""
import json, time, urllib.parse, urllib.request
from pathlib import Path

from wiki_ua import user_agent

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "big" / "wiki.jsonl"
API = "https://es.wikipedia.org/w/api.php"
UA = {"User-Agent": user_agent()}

mun = json.loads((HERE / "data" / "big" / "municipios.json").read_text(encoding="utf-8"))
done = set()
if OUT.exists():
    done = {json.loads(l)["ine"] for l in OUT.read_text(encoding="utf-8").splitlines() if l.strip()}
todo = [m for m in mun if m["ine"] not in done and m["eswiki"]]
by_title = {m["eswiki"]: m for m in todo}
out = OUT.open("a", encoding="utf-8")
for i in range(0, len(todo), 20):
    chunk = todo[i:i + 20]
    q = {"action": "query", "format": "json", "prop": "extracts", "exintro": 1, "explaintext": 1,
         "exlimit": 20, "redirects": 1, "titles": "|".join(m["eswiki"] for m in chunk)}
    for attempt in range(4):
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request(API + "?" + urllib.parse.urlencode(q), headers=UA), timeout=60))
            break
        except Exception:
            time.sleep(2 * (attempt + 1))
    else:
        print("falló el bloque", i); continue
    q_ = d.get("query", {})
    redirect = {r["to"]: r["from"] for r in q_.get("redirects", [])}
    norm = {n["to"]: n["from"] for n in q_.get("normalized", [])}
    for page in q_.get("pages", {}).values():
        t = page.get("title"); t = redirect.get(t, t); t = norm.get(t, t)
        m = by_title.get(t)
        if m and page.get("extract"):
            out.write(json.dumps({"ine": m["ine"], "title": page["title"], "extract": page["extract"]}, ensure_ascii=False) + "\n")
    out.flush()
    if i % 1000 == 0:
        print(f"{i}/{len(todo)}", flush=True)
    time.sleep(0.2)
print("hecho")
