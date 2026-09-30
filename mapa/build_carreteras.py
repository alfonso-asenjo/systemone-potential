"""Datos para el mapa de carreteras de los 90 (static_big/carreteras.html).

Natural Earth (dominio público) pone lo que un mapa de carreteras tiene y el mapa de luces no:
autopistas y carreteras, ferrocarril, ríos, embalses y los países vecinos. Se recorta a la zona de
España, se simplifica y se escribe junto a la página. También se copian los polígonos de los
municipios (para ampliar el que se elige) y los datos de cada pueblo para su ficha.

    python mapa/build_carreteras.py
"""
from __future__ import annotations

import json
import shutil
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
NE = HERE / "data" / "ne"
STATIC = HERE / "static_big"
BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
BBOX = (-19.5, 26.5, 6.0, 45.5)          # de Canarias al sur de Francia
NEAR = {"PRT", "FRA", "AND", "MAR", "DZA", "GIB", "ESP"}


def fetch(name: str) -> dict:
    NE.mkdir(parents=True, exist_ok=True)
    f = NE / f"{name}.geojson"
    if not f.exists():
        print(f"descargando {name}…", flush=True)
        urllib.request.urlretrieve(BASE + f"{name}.geojson", f)
    return json.loads(f.read_text(encoding="utf-8"))


def rdp(pts, eps):
    """Douglas-Peucker: quita los puntos que no cambian la forma a esta escala."""
    if len(pts) < 3:
        return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = (dx * dx + dy * dy) ** 0.5 or 1e-12
    dmax, idx = 0.0, 0
    for i in range(1, len(pts) - 1):
        x, y = pts[i]
        d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / norm
        if d > dmax:
            dmax, idx = d, i
    if dmax <= eps:
        return [pts[0], pts[-1]]
    return rdp(pts[:idx + 1], eps)[:-1] + rdp(pts[idx:], eps)


def simplify(pts, eps):
    """Como rdp, pero sirve también para anillos cerrados (empiezan y acaban en el mismo punto)."""
    if len(pts) > 3 and pts[0] == pts[-1]:
        x0, y0 = pts[0]
        k = max(range(len(pts)), key=lambda i: (pts[i][0] - x0) ** 2 + (pts[i][1] - y0) ** 2)
        return rdp(pts[:k + 1], eps)[:-1] + rdp(pts[k:], eps)
    return rdp(pts, eps)


def near(coords) -> bool:
    xs = [c[0] for c in coords]; ys = [c[1] for c in coords]
    return not (max(xs) < BBOX[0] or min(xs) > BBOX[2] or max(ys) < BBOX[1] or min(ys) > BBOX[3])


def clean_line(line, eps):
    return [[round(x, 4), round(y, 4)] for x, y in simplify(line, eps)]


def lines_of(geom):
    if geom is None:
        return []
    if geom["type"] == "LineString":
        return [geom["coordinates"]]
    if geom["type"] == "MultiLineString":
        return geom["coordinates"]
    return []


def polys_of(geom):
    if geom is None:
        return []
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def line_layer(name, keep, props, eps):
    out = []
    for f in fetch(name)["features"]:
        p = f["properties"]
        if not keep(p):
            continue
        parts = [clean_line(l, eps) for l in lines_of(f["geometry"]) if near(l)]
        parts = [l for l in parts if len(l) >= 2]
        if parts:
            out.append({"type": "Feature", "properties": {k: p.get(k) for k in props},
                        "geometry": {"type": "MultiLineString", "coordinates": parts}})
    return {"type": "FeatureCollection", "features": out}


def poly_layer(name, keep, props, eps, min_pts=4):
    out = []
    for f in fetch(name)["features"]:
        p = f["properties"]
        if not keep(p):
            continue
        polys = []
        for poly in polys_of(f["geometry"]):
            if not near(poly[0]):
                continue
            rings = [clean_line(r, eps) for r in poly]
            rings = [r for r in rings if len(r) >= min_pts]
            if rings:
                polys.append(rings)
        if polys:
            out.append({"type": "Feature", "properties": {k: p.get(k) for k in props},
                        "geometry": {"type": "MultiPolygon", "coordinates": polys}})
    return {"type": "FeatureCollection", "features": out}


def main():
    sys.setrecursionlimit(20000)   # Douglas-Peucker recursivo sobre contornos de miles de puntos
    geo = {
        "countries": poly_layer("ne_10m_admin_0_countries", lambda p: p.get("ADM0_A3") in NEAR,
                                ["ADM0_A3", "NAME_ES"], 0.004),
        "roads": line_layer("ne_10m_roads", lambda p: p.get("continent") in ("Europe", "Africa") and not p.get("ferry"),
                            ["type", "expressway", "toll", "label", "scalerank"], 0.002),
        "rail": line_layer("ne_10m_railroads", lambda p: p.get("continent") in ("Europe", "Africa"), ["scalerank"], 0.002),
        "rivers": {"type": "FeatureCollection", "features":
                   line_layer("ne_10m_rivers_lake_centerlines", lambda p: True, ["name", "scalerank"], 0.002)["features"]
                   + line_layer("ne_10m_rivers_europe", lambda p: True, ["name", "scalerank"], 0.002)["features"]},
        "lakes": poly_layer("ne_10m_lakes", lambda p: True, ["name"], 0.002),
    }
    for k, v in geo.items():
        print(f"{k}: {len(v['features'])} elementos")
    (STATIC / "carreteras-geo.json").write_text(json.dumps(geo, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # los pueblos, en el mismo orden que usa el servidor para las probabilidades
    lugares = json.loads((HERE / "data" / "big" / "lugares.json").read_text(encoding="utf-8"))
    # el punto va en el pueblo (Wikidata), no en el centro del término, salvo que el dato sea absurdo
    wd_path = HERE / "data" / "big" / "wikidata_coords.json"
    wd = json.loads(wd_path.read_text(encoding="utf-8")) if wd_path.exists() else {}
    moved = 0
    rows = []
    for l in lugares:
        lat, lon, w = l["lat"], l["lon"], wd.get(l["ine"], {})
        if "lat" in w:
            dk = ((w["lat"] - lat) * 111) ** 2 + ((w["lon"] - lon) * 111 * 0.77) ** 2
            if dk < 30 ** 2:
                lat, lon, moved = w["lat"], w["lon"], moved + 1
        rows.append([l["name"], l["prov"], l["pop"], lat, lon, l["ine"], l["elev"], l["hours"],
                     1 if l["costero"] else 0, l["reach"], l["rasgos"] or "", w.get("img", "")])
    print(f"pueblos colocados en su núcleo: {moved} de {len(rows)}")
    (STATIC / "carreteras-lugares.json").write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    shutil.copyfile(HERE / "data" / "municipalities.json", STATIC / "municipios-topo.json")
    for f in ("carreteras-geo.json", "carreteras-lugares.json", "municipios-topo.json"):
        print(f"{f}: {(STATIC / f).stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
