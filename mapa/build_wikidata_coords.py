"""Ubicación real del pueblo (no el centro del término) y foto principal de cada municipio, de Wikidata.

lugares.json usa el centroide del polígono del IGN, que a menudo cae en el campo. Wikidata guarda la
coordenada del núcleo (P625) y la imagen principal en Commons (P18). Se piden por lotes con los
identificadores que ya tenemos en municipios.json.

    python mapa/build_wikidata_coords.py      # -> data/big/wikidata_coords.json
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIG = HERE / "data" / "big"
OUT = BIG / "wikidata_coords.json"
URL = "https://query.wikidata.org/sparql"
UA = "jevcraft-mapa/1.0 (demo local; mapa de municipios)"


def query(qids):
    values = " ".join(f"wd:{q}" for q in qids)
    q = f"""SELECT ?item ?coord ?img WHERE {{
      VALUES ?item {{ {values} }}
      OPTIONAL {{ ?item wdt:P625 ?coord. }}
      OPTIONAL {{ ?item wdt:P18 ?img. }}
    }}"""
    req = urllib.request.Request(URL + "?" + urllib.parse.urlencode({"query": q, "format": "json"}), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)["results"]["bindings"]


def main():
    munis = json.loads((BIG / "municipios.json").read_text(encoding="utf-8"))
    by_q = {m["wikidata"]: m["ine"] for m in munis if m.get("wikidata")}
    out = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    todo = [q for q, ine in by_q.items() if ine not in out]
    print(f"{len(by_q)} municipios con Wikidata, faltan {len(todo)}", flush=True)
    for k in range(0, len(todo), 300):
        batch = todo[k:k + 300]
        for attempt in range(4):
            try:
                rows = query(batch)
                break
            except Exception as e:  # noqa: BLE001
                print(f"  reintento ({e})", flush=True)
                time.sleep(5 * (attempt + 1))
        else:
            continue
        for q in batch:
            out.setdefault(by_q[q], {})
        for r in rows:
            ine = by_q[r["item"]["value"].rsplit("/", 1)[1]]
            d = out[ine]
            if "coord" in r and "lat" not in d:
                lon, lat = r["coord"]["value"].removeprefix("Point(").removesuffix(")").split()
                d["lat"], d["lon"] = round(float(lat), 5), round(float(lon), 5)
            if "img" in r and "img" not in d:
                d["img"] = urllib.parse.unquote(r["img"]["value"].rsplit("/", 1)[1])
        OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        print(f"  {min(k + 300, len(todo))}/{len(todo)}", flush=True)
        time.sleep(1)
    n_c = sum("lat" in d for d in out.values()); n_i = sum("img" in d for d in out.values())
    print(f"con coordenada: {n_c}, con foto: {n_i}")


if __name__ == "__main__":
    main()
