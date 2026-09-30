"""Construye static/places.json a partir de data/places.txt y los municipios del IGN.

    python mapa/build_places.py

De cada lugar escribo a mano el nombre, su municipio, la costa y lo que lo distingue. Las
coordenadas salen del centroide de su municipio en es-atlas (Instituto Geográfico Nacional),
y las horas desde Madrid de la distancia en línea recta, así que son aproximadas y lo dicen.
"""
from __future__ import annotations

import json
import math
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROVINCES = {
    "01": "Álava", "02": "Albacete", "03": "Alicante", "04": "Almería", "05": "Ávila",
    "06": "Badajoz", "07": "Baleares", "08": "Barcelona", "09": "Burgos", "10": "Cáceres",
    "11": "Cádiz", "12": "Castellón", "13": "Ciudad Real", "14": "Córdoba", "15": "A Coruña",
    "16": "Cuenca", "17": "Girona", "18": "Granada", "19": "Guadalajara", "20": "Gipuzkoa",
    "21": "Huelva", "22": "Huesca", "23": "Jaén", "24": "León", "25": "Lleida",
    "26": "La Rioja", "27": "Lugo", "28": "Madrid", "29": "Málaga", "30": "Murcia",
    "31": "Navarra", "32": "Ourense", "33": "Asturias", "34": "Palencia", "35": "Las Palmas",
    "36": "Pontevedra", "37": "Salamanca", "38": "Santa Cruz de Tenerife", "39": "Cantabria",
    "40": "Segovia", "41": "Sevilla", "42": "Soria", "43": "Tarragona", "44": "Teruel",
    "45": "Toledo", "46": "Valencia", "47": "Valladolid", "48": "Bizkaia", "49": "Zamora",
    "50": "Zaragoza", "51": "Ceuta", "52": "Melilla",
}
ISLANDS = {"07", "35", "38"}
AFRICA = {"51", "52"}
MADRID = (40.4168, -3.7038)
# Carretera frente a línea recta, y velocidad media: comprobado contra Madrid-San Sebastián
# (4 h 30), Madrid-Sevilla (5 h 15) y Madrid-Toledo (1 h), con error de media hora.
ROAD_FACTOR = 1.25
KMH = 100


def norm(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    # El IGN escribe "Oliva, La"; aquí se escribe "La Oliva". Se comparan las dos formas.
    if ", " in name:
        base, art = name.rsplit(", ", 1)
        name = f"{art} {base}"
    return name.strip()


def decode(topo: dict) -> dict[str, list]:
    """Anillos en lon/lat de cada municipio, deshaciendo la cuantización de TopoJSON."""
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)

    def ring(ids):
        out = []
        for i in ids:
            pts = arcs[i] if i >= 0 else list(reversed(arcs[~i]))
            out.extend(pts if not out else pts[1:])
        return out

    shapes = {}
    for g in topo["objects"]["municipalities"]["geometries"]:
        polys = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]
        shapes[g["id"]] = (g["properties"]["name"], [ring(p[0]) for p in polys])
    return shapes


def centroid(rings: list) -> tuple[float, float]:
    """Centroide del polígono más grande, que es donde vive casi todo el municipio."""
    best = None
    for pts in rings:
        a = cx = cy = 0.0
        for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
            cross = x0 * y1 - x1 * y0
            a += cross
            cx += (x0 + x1) * cross
            cy += (y0 + y1) * cross
        if a == 0:
            continue
        cand = (abs(a), cy / (3 * a), cx / (3 * a))
        if best is None or cand[0] > best[0]:
            best = cand
    return round(best[1], 4), round(best[2], 4)


def haversine(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def main() -> int:
    topo = json.loads((HERE / "data" / "municipalities.json").read_text(encoding="utf-8"))
    shapes = decode(topo)
    by_prov: dict[str, dict[str, str]] = {}
    for code, (name, _) in shapes.items():
        forms = {norm(name)} | {norm(part) for part in name.split("/")}
        for f in forms:
            by_prov.setdefault(code[:2], {})[f] = code

    places, missing = [], []
    for line in (HERE / "data" / "places.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, muni, prov, coast, pop, traits = [x.strip() for x in line.split("|")]
        code = by_prov.get(prov, {}).get(norm(muni))
        if code is None:
            missing.append(f"{name} ({muni}, {prov})")
            continue
        lat, lon = centroid(shapes[code][1])
        if prov in ISLANDS:
            hours = None
            reach = "island"
        elif prov in AFRICA:
            hours = None
            reach = "africa"
        else:
            hours = round(haversine(MADRID, (lat, lon)) * ROAD_FACTOR / KMH * 2) / 2
            reach = "road"
        places.append({
            "id": len(places), "name": name, "muni": shapes[code][0], "ine": code,
            "prov": PROVINCES[prov], "coast": coast, "pop": int(pop), "hours": hours,
            "reach": reach, "lat": lat, "lon": lon, "traits": traits,
        })

    if missing:
        print("Sin municipio en el IGN:", *missing, sep="\n  ")
        return 1
    if len(places) > 255:
        print(f"{len(places)} lugares: jev admite 255 opciones como mucho")
        return 1
    out = HERE / "static" / "places.json"
    out.write_text(json.dumps(places, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{len(places)} lugares en {out}")
    for check in ("San Sebastián", "Sevilla", "Toledo", "Mundaka"):
        p = next(p for p in places if p["name"] == check)
        print(f"  {check}: {p['lat']}, {p['lon']}, {p['hours']} h")
    return 0


if __name__ == "__main__":
    sys.exit(main())
