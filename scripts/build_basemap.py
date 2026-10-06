"""Build `kissterm/geo/data/`, the offline map's outlines.

Usage:
    python scripts/build_basemap.py DIR

DIR holds Natural Earth's GeoJSON (public domain,
https://github.com/nvkelso/natural-earth-vector, `geojson/`), the files
named in `WORLD` and `DETAIL`.

Two files come out. **basemap.json.gz**, the world at 1:50m (coastlines,
country and state/province lines, the large lakes), drawn at every zoom.
**detail.json.gz**, from 1:10m, drawn only once zoomed in (operator,
2026-10-06: "If we can include county lines, that may help. Main roads
and highways and major bodies of water would help identify a
location"): the coastline at 1:10m, US counties, major and secondary
highways, rivers and lakes.

Every line is simplified (Douglas-Peucker, its layer's tolerance in
degrees) and its points stored as integers (`scale` per degree),
flattened `[lon, lat, dlon, dlat, ...]`: the first point, then each
point's difference from the one before, gzipped, so the whole map ships
at about 1.8 MB and needs no Internet (operator, 2026-10-06: "Basic
offline map if possible"). `kissterm/geo/basemap.py` reads them.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "kissterm" / "geo" / "data"

ROADS = {"Major Highway", "Secondary Highway", "Beltway", "Bypass"}

#: (file, layer, tolerance in degrees, keep(properties) or None)
WORLD = [
    ("ne_50m_coastline", "coast", 0.03, None),
    ("ne_50m_admin_0_boundary_lines_land", "country", 0.03, None),
    ("ne_50m_admin_1_states_provinces_lines", "state", 0.03, None),
    ("ne_50m_lakes", "lake", 0.03, lambda p: (p.get("scalerank") or 9) <= 2),
]
DETAIL = [
    ("ne_10m_coastline", "coast", 0.003, None),
    ("ne_10m_admin_2_counties", "county", 0.005, None),
    ("ne_10m_roads", "road", 0.005, lambda p: p.get("type") in ROADS),
    ("ne_10m_rivers_lake_centerlines", "river", 0.005, None),
    ("ne_10m_lakes", "lake", 0.005, None),
]


def simplify(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """Douglas-Peucker, iterative (coastlines are long)."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        (x1, y1), (x2, y2) = points[first], points[last]
        dx, dy = x2 - x1, y2 - y1
        norm = (dx * dx + dy * dy) ** 0.5
        worst, index = 0.0, -1
        for i in range(first + 1, last):
            x, y = points[i]
            if norm == 0:
                d = ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
            else:
                d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / norm
            if d > worst:
                worst, index = d, i
        if worst > tolerance and index > 0:
            keep[index] = True
            stack += [(first, index), (index, last)]
    return [p for p, k in zip(points, keep) if k]


def lines_of(geometry: dict) -> list[list[tuple[float, float]]]:
    kind, coords = geometry["type"], geometry["coordinates"]
    if kind == "LineString":
        return [coords]
    if kind in ("MultiLineString", "Polygon"):
        return list(coords)
    if kind == "MultiPolygon":
        return [ring for polygon in coords for ring in polygon]
    return []


def build(directory: Path, layers: list, scale: int) -> dict:
    out: dict[str, list] = {}
    for name, layer, tolerance, keep in layers:
        data = json.loads((directory / f"{name}.geojson").read_text("utf-8"))
        lines = out.setdefault(layer, [])
        for feature in data["features"]:
            if keep is not None and not keep(feature["properties"]):
                continue
            for line in lines_of(feature["geometry"]):
                points = simplify([(float(x), float(y)) for x, y, *_ in line], tolerance)
                flat = [round(v * scale) for point in points for v in point]
                if len(flat) >= 4:
                    lines.append(flat[:2] + [flat[i] - flat[i - 2] for i in range(2, len(flat))])
    return {"source": "Natural Earth (public domain), naturalearthdata.com",
            "scale": scale, "layers": out}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    DATA.mkdir(parents=True, exist_ok=True)
    for filename, layers, scale in (("basemap.json.gz", WORLD, 100),
                                    ("detail.json.gz", DETAIL, 1000)):
        built = build(Path(argv[1]), layers, scale)
        path = DATA / filename
        raw = json.dumps(built, separators=(",", ":")).encode("utf-8")
        # mtime=0: the same input builds the same bytes.
        path.write_bytes(gzip.compress(raw, 9, mtime=0))
        counts = {k: len(v) for k, v in built["layers"].items()}
        print(f"wrote {path.name} ({path.stat().st_size // 1024} KB): {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
