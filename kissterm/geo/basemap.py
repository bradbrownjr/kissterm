"""The offline map's outlines (`data/basemap.json.gz`, `data/detail.json.gz`,
built by `scripts/build_basemap.py` from Natural Earth, public domain).

**World** layers (coast, country, state, the large lakes) are drawn at
every zoom. **Detail** layers (the coast at 1:10m, US counties, major
and secondary highways, rivers, lakes) only once the view is narrower than
`DETAIL_SPAN` degrees: across a continent they would be a grey smear,
and they are most of the data.

Each line is kept as a flat `array('f')` of lon, lat pairs with its
bounding box, so `lines_in` skips what is off screen without looking at
a point of it; the detail file is read on first use (about a second),
never at startup.
"""

from __future__ import annotations

import gzip
import json
from array import array
from functools import lru_cache
from importlib import resources

#: Degrees of longitude across the view below which detail is drawn.
DETAIL_SPAN = 6.0

#: Drawing order, back to front, as (file, layer); the UIs style each
#: layer. Zoomed in, the detail file's coast and lakes replace the
#: world's (the same shores at 1:10m), and counties go first, under the
#: water and the state lines: a county's boundary runs out into the bay
#: and along the shore, and drawn over the coast it hid the coast.
WORLD_ORDER = (("basemap", "lake"), ("basemap", "coast"),
               ("basemap", "country"), ("basemap", "state"))
DETAIL_ORDER = (("detail", "county"), ("detail", "lake"), ("detail", "river"),
                ("detail", "coast"), ("basemap", "country"), ("basemap", "state"),
                ("detail", "road"))

Line = tuple[float, float, float, float, array]  # west, south, east, north, points


@lru_cache(maxsize=2)
def _load(name: str) -> dict[str, list[Line]]:
    raw = resources.files(__package__).joinpath(f"data/{name}.json.gz").read_bytes()
    data = json.loads(gzip.decompress(raw))
    scale = float(data["scale"])
    layers: dict[str, list[Line]] = {}
    for layer, lines in data["layers"].items():
        out = layers.setdefault(layer, [])
        for deltas in lines:
            x, y = deltas[0], deltas[1]
            points = array("f", (x / scale, y / scale))
            for i in range(2, len(deltas), 2):
                x += deltas[i]
                y += deltas[i + 1]
                points.append(x / scale)
                points.append(y / scale)
            lons, lats = points[0::2], points[1::2]
            out.append((min(lons), min(lats), max(lons), max(lats), points))
    return layers


def lines_in(west: float, south: float, east: float, north: float,
             *, detail: bool | None = None) -> list[tuple[str, array]]:
    """(layer, points) for every line that crosses the box, back to front.
    `detail` None decides by the box's width (`DETAIL_SPAN`)."""
    if detail is None:
        detail = (east - west) < DETAIL_SPAN
    found: list[tuple[str, array]] = []
    for name, layer in DETAIL_ORDER if detail else WORLD_ORDER:
        for w, s, e, n, points in _load(name).get(layer, ()):
            if e >= west and w <= east and n >= south and s <= north:
                found.append((layer, points))
    return found
