"""Descarga el artículo completo de Wikipedia (es) de cada municipio y se queda con lo útil.

La introducción sola no basta: medido con 8 pueblos, gpt-6-luna respondía "sin rasgos
destacados" en 5, porque la introducción de un pueblo pequeño solo dice dónde está y cuánta
gente vive. El patrimonio, las fiestas y la gastronomía están en sus secciones. Se guarda la
introducción más esas secciones, recortado a ~5.000 caracteres.

    python mapa/big_wiki_full.py   ->  mapa/data/big/wiki_full.jsonl  (se puede relanzar: continúa)
"""
import json, re, time, urllib.parse, urllib.request
from pathlib import Path

from wiki_ua import user_agent

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "big" / "wiki_full.jsonl"
API = "https://es.wikipedia.org/w/api.php"
UA = {"User-Agent": user_agent()}
KEEP = re.compile(r"patrimonio|monumento|lugares de inter|fiesta|gastronom|turismo|cultura|naturaleza|"
                  r"espacios naturales|paraje|geograf|playa|arquitectura|tradici|folclore|ocio|deporte", re.I)
MAX_CHARS = 5000


def useful(text: str) -> str:
    """Introducción + secciones que interesan a quien busca adónde ir."""
    parts = re.split(r"\n(=={1,3}[^=].*?=={1,3})\n", "\n" + text)
    keep = [parts[0].strip()]
    for head, body in zip(parts[1::2], parts[2::2]):
        if KEEP.search(head) and body.strip():
            keep.append(head.strip("= ").strip() + ": " + re.sub(r"\s+", " ", body).strip())
    return "\n".join(keep)[:MAX_CHARS]


mun = json.loads((HERE / "data" / "big" / "municipios.json").read_text(encoding="utf-8"))
done = set()
if OUT.exists():
    done = {json.loads(l)["ine"] for l in OUT.read_text(encoding="utf-8").splitlines() if l.strip()}
todo = [m for m in mun if m["ine"] not in done and m["eswiki"]]
out = OUT.open("a", encoding="utf-8")
for n, m in enumerate(todo):
    q = {"action": "query", "format": "json", "prop": "extracts", "explaintext": 1,
         "exsectionformat": "wiki", "redirects": 1, "titles": m["eswiki"]}
    for attempt in range(4):
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request(API + "?" + urllib.parse.urlencode(q), headers=UA), timeout=60))
            break
        except Exception:
            time.sleep(2 * (attempt + 1))
    else:
        continue
    page = next(iter(d.get("query", {}).get("pages", {}).values()), {})
    if page.get("extract"):
        out.write(json.dumps({"ine": m["ine"], "title": page["title"], "text": useful(page["extract"])}, ensure_ascii=False) + "\n")
        out.flush()
    if n % 500 == 0:
        print(f"{n}/{len(todo)}", flush=True)
    time.sleep(0.1)
print("hecho")
