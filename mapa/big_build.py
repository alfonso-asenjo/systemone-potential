"""Los 8.131 municipios con todo lo que sabemos de ellos, y el árbol para Laya.

    python mapa/big_build.py   ->  data/big/lugares.json y data/big/arbol.json

Por municipio: población y altitud (Wikidata), rasgos (gpt-6-luna a partir de Wikipedia,
big_describe.py), centro del polígono del IGN, horas desde Madrid (misma fórmula que
build_places.py), distancia a la costa y si es costero.

Costa: el contorno exterior de los municipios mezcla costa y fronteras con Portugal, Francia
y Andorra, y el objeto `border` del atlas es ese mismo contorno, así que no las separa. La
línea de costa sale de Natural Earth 10m (dominio público): un municipio es costero si su
contorno exterior pasa a menos de COAST_KM de ella.

Árbol, para preguntar a Laya en cadena con 20 opciones como mucho en cada paso (idea
original: "un árbol de decisión a la inversa"): comunidad (hasta 19), provincia (hasta 9),
grupo (hasta 20) y municipio (hasta 20). No hay comarcas oficiales en toda España, así que
los grupos son geográficos: k-medias sobre el centro de cada municipio, y cada grupo de más de
20 se parte en dos hasta que ninguno pase. Cada grupo se llama como su municipio más poblado.
"""
from __future__ import annotations

import collections
import json
import math
from pathlib import Path

import numpy as np
from scipy.cluster.vq import kmeans2
from scipy.spatial import cKDTree

from build_places import AFRICA, ISLANDS, KMH, MADRID, PROVINCES, ROAD_FACTOR, centroid, decode, haversine


def ign_name(name: str) -> str:
    """El IGN escribe "Oliva, La"; aquí se escribe "La Oliva"."""
    if ", " in name:
        base, art = name.rsplit(", ", 1)
        return f"{art} {base}"
    return name

HERE = Path(__file__).resolve().parent
BIG = HERE / "data" / "big"
# Medido: con 1 km Santillana del Mar (tiene la playa de Santa Justa) salía no costera; con
# 1,5 km sí, y 466 costeros en total. Con 3 km entra Irún, que es dudoso. Las rías por dentro
# (Busturia) no están en Natural Earth, pero sus rasgos ya dicen "orilla de la ría".
COAST_KM = 1.5
MAX_CHILDREN = 20

CCAA = {  # provincia -> comunidad
    "04": "Andalucía", "11": "Andalucía", "14": "Andalucía", "18": "Andalucía", "21": "Andalucía",
    "23": "Andalucía", "29": "Andalucía", "41": "Andalucía",
    "22": "Aragón", "44": "Aragón", "50": "Aragón", "33": "Asturias", "07": "Baleares",
    "35": "Canarias", "38": "Canarias", "39": "Cantabria",
    "02": "Castilla-La Mancha", "13": "Castilla-La Mancha", "16": "Castilla-La Mancha",
    "19": "Castilla-La Mancha", "45": "Castilla-La Mancha",
    "05": "Castilla y León", "09": "Castilla y León", "24": "Castilla y León", "34": "Castilla y León",
    "37": "Castilla y León", "40": "Castilla y León", "42": "Castilla y León", "47": "Castilla y León",
    "49": "Castilla y León",
    "08": "Cataluña", "17": "Cataluña", "25": "Cataluña", "43": "Cataluña",
    "03": "Comunidad Valenciana", "12": "Comunidad Valenciana", "46": "Comunidad Valenciana",
    "06": "Extremadura", "10": "Extremadura", "15": "Galicia", "27": "Galicia", "32": "Galicia",
    "36": "Galicia", "28": "Madrid", "30": "Murcia", "31": "Navarra",
    "01": "País Vasco", "20": "País Vasco", "48": "País Vasco", "26": "La Rioja",
    "51": "Ceuta", "52": "Melilla",
}


def to_km(lonlat: np.ndarray) -> np.ndarray:
    """Proyección plana suficiente para buscar vecinos: km en x e y."""
    lon, lat = lonlat[:, 0], lonlat[:, 1]
    return np.column_stack([lon * 111.32 * np.cos(np.radians(lat)), lat * 110.57])


def coastline() -> cKDTree:
    geo = json.loads((BIG / "ne_10m_coastline.geojson").read_text(encoding="utf-8"))
    pts = []
    for f in geo["features"]:
        line = f["geometry"]["coordinates"]
        for (x0, y0), (x1, y1) in zip(line, line[1:]):
            if not (-19 < x0 < 5 and 27 < y0 < 44.5):
                continue
            n = max(1, int(math.hypot(x1 - x0, y1 - y0) / 0.003))   # un punto cada ~300 m
            for k in range(n):
                pts.append((x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n))
    return cKDTree(to_km(np.array(pts)))


def exterior_points(topo: dict) -> dict[str, np.ndarray]:
    """Puntos de los arcos que no comparte ningún otro municipio: el contorno exterior."""
    def flat(a):
        for x in a:
            if isinstance(x, list):
                yield from flat(x)
            else:
                yield x
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx; y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)
    geoms = topo["objects"]["municipalities"]["geometries"]
    use = collections.Counter(a if a >= 0 else ~a for g in geoms for a in set(flat(g["arcs"])))
    out = {}
    for g in geoms:
        ext = [p for a in set(flat(g["arcs"])) if use[a if a >= 0 else ~a] == 1 for p in arcs[a if a >= 0 else ~a]]
        if ext:
            out[g["id"]] = np.array(ext)
    return out


def groups(members: list[dict]) -> list[list[dict]]:
    """Grupos geográficos de MAX_CHILDREN municipios como mucho."""
    if len(members) <= MAX_CHILDREN:
        return [members]
    pts = np.array([[m["lon"], m["lat"]] for m in members])
    k = math.ceil(len(members) / (MAX_CHILDREN - 2))
    _, labels = kmeans2(to_km(pts), k, seed=7, minit="++")
    out = []
    for c in range(k):
        part = [m for m, l in zip(members, labels) if l == c]
        if not part:
            continue
        out.extend(groups(part) if len(part) > MAX_CHILDREN else [part])
    # k-medias puede partir en trozos de más de 20 aunque la media sea menor: se repite en dos
    return [g for part in out for g in (bisect(part) if len(part) > MAX_CHILDREN else [part])]


def bisect(members: list[dict]) -> list[list[dict]]:
    pts = to_km(np.array([[m["lon"], m["lat"]] for m in members]))
    axis = int(np.ptp(pts[:, 0]) < np.ptp(pts[:, 1]))
    order = sorted(range(len(members)), key=lambda i: pts[i, axis])
    half = len(members) // 2
    parts = [[members[i] for i in order[:half]], [members[i] for i in order[half:]]]
    return [g for p in parts for g in (bisect(p) if len(p) > MAX_CHILDREN else [p])]


def halves(prov: str, gnodes: list[dict]) -> list[dict]:
    """Parte los grupos de una provincia en dos mitades por el eje más largo."""
    pts = to_km(np.array([[g["lon"], g["lat"]] for g in gnodes]))
    ns = np.ptp(pts[:, 1]) >= np.ptp(pts[:, 0])
    axis = 1 if ns else 0
    order = sorted(range(len(gnodes)), key=lambda i: pts[i, axis])
    half = len(gnodes) // 2
    names = ("sur", "norte") if ns else ("oeste", "este")
    return [{"id": f"s:{prov}:{k}", "name": f"{names[k]} de {prov}",
             "children": [gnodes[i] for i in part]}
            for k, part in enumerate((order[:half], order[half:]))]


def main() -> None:
    topo = json.loads((HERE / "data" / "municipalities.json").read_text(encoding="utf-8"))
    shapes = decode(topo)
    wd = {m["ine"]: m for m in json.loads((BIG / "municipios.json").read_text(encoding="utf-8"))}
    rasgos = {r["ine"]: r["rasgos"] for r in map(json.loads, (BIG / "rasgos.jsonl").read_text(encoding="utf-8").splitlines())}
    coast = coastline()
    ext = exterior_points(topo)

    lugares = []
    for ine, m in wd.items():
        try:
            lat, lon = centroid(shapes[ine][1])
        except TypeError:   # polígono de área cero tras la cuantización: media de sus puntos
            pts = np.array([p for ring in shapes[ine][1] for p in ring])
            lon, lat = (round(float(v), 4) for v in pts.mean(axis=0))
            print(f"  {m['name']} ({ine}): centro por media de puntos")
        prov = ine[:2]
        d_centro, _ = coast.query(to_km(np.array([[lon, lat]])))
        costero = False
        if ine in ext:
            d_borde, _ = coast.query(to_km(ext[ine]))
            costero = bool(d_borde.min() < COAST_KM)
        if prov in ISLANDS:
            hours, reach = None, "island"
        elif prov in AFRICA:
            hours, reach = None, "africa"
        else:
            hours = round(haversine(MADRID, (lat, lon)) * ROAD_FACTOR / KMH * 2) / 2
            reach = "road"
        r = rasgos.get(ine, "")
        lugares.append({
            # Algunos municipios no tienen etiqueta en castellano en Wikidata: se usa la del IGN.
            "ine": ine, "name": m["name"] or ign_name(shapes[ine][0]), "prov": PROVINCES[prov], "ccaa": CCAA[prov],
            "lat": lat, "lon": lon, "pop": m["pop"], "elev": m["elev"],
            "coast_km": round(float(d_centro[0]), 1), "costero": costero,
            "hours": hours, "reach": reach,
            "rasgos": "" if "sin rasgos" in r.lower() else r,
        })

    # Árbol: comunidad -> provincia -> grupo -> municipio
    tree = {"id": "es", "name": "España", "children": []}
    by_ccaa = collections.defaultdict(lambda: collections.defaultdict(list))
    for l in lugares:
        by_ccaa[l["ccaa"]][l["prov"]].append(l)
    for ccaa in sorted(by_ccaa):
        cnode = {"id": f"c:{ccaa}", "name": ccaa, "children": []}
        for prov in sorted(by_ccaa[ccaa]):
            pnode = {"id": f"p:{prov}", "name": prov, "children": []}
            gnodes = []
            for i, g in enumerate(groups(by_ccaa[ccaa][prov])):
                g.sort(key=lambda m: -(m["pop"] or 0))
                gname = f"zona de {g[0]['name']}" if len(g) > 1 else g[0]["name"]
                gnode = {"id": f"g:{prov}:{i}", "name": gname, "children": [m["ine"] for m in g],
                         "lat": float(np.mean([m["lat"] for m in g])), "lon": float(np.mean([m["lon"] for m in g]))}
                for m in g:
                    m["grupo"] = gnode["id"]
                gnodes.append(gnode)
            # Medido: Burgos salía con 28 grupos, Salamanca 26, Zaragoza 23, Valencia 22,
            # Barcelona y Navarra 21. En esas provincias hay un nivel más: dos mitades.
            if len(gnodes) > MAX_CHILDREN:
                pnode["children"] = halves(prov, gnodes)
            else:
                pnode["children"] = gnodes
            cnode["children"].append(pnode)
        tree["children"].append(cnode)

    (BIG / "lugares.json").write_text(json.dumps(lugares, ensure_ascii=False, indent=0), encoding="utf-8")
    (BIG / "arbol.json").write_text(json.dumps(tree, ensure_ascii=False, indent=1), encoding="utf-8")

    # Comprobaciones
    by = {l["name"]: l for l in lugares}
    for name in ("Mundaka", "Madrid", "Ronda", "Albarracín", "Tabernas", "Cudillero", "Haro"):
        l = by.get(name)
        if l:
            print(f"  {name}: costero={l['costero']}, costa a {l['coast_km']} km, {l['hours']} h, grupo {l['grupo']}")
    print(f"{len(lugares)} municipios, {sum(l['costero'] for l in lugares)} costeros, "
          f"{sum(not l['rasgos'] for l in lugares)} sin rasgos")
    widest, depth, ngroups = 0, collections.Counter(), 0
    def walk(node, d):
        nonlocal widest, ngroups
        kids = node.get("children", [])
        widest = max(widest, len(kids))
        if node["id"].startswith("g:"):
            ngroups += 1
            depth[d + 1] += len(kids)
            return
        for k in kids:
            walk(k, d + 1)
    walk(tree, 0)
    print(f"árbol: {len(tree['children'])} comunidades, {ngroups} grupos; máximo de opciones por pregunta: {widest}; "
          f"municipios por profundidad: {dict(depth)}")


if __name__ == "__main__":
    main()
