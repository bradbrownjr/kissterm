"""The map: what the station heard with a position, and an offline map to
show it on (operator, 2026-10-06: "a map of heard stations that have
coordinates and objects received ... Basic offline map if possible").

- `placemarks`: stations and objects with a position, as heard.
- `basemap`: coastlines, borders, states, and at zoom counties, roads,
  rivers and lakes, from Natural Earth, shipped in `data/` (built by
  `scripts/build_basemap.py`); no Internet needed.
- `distance`: great-circle distance and bearing (the Heard pane's
  columns and radar; re-exported here, where they were first).
- `project`: the map's view (centre, span) and a station's
  distance-and-bearing line.
- `braille`: drawing lines in braille cells, for the terminal.

No UI and no I/O beyond reading the shipped data: the terminal's map
screen and the phone's map page both draw from here.
"""

from .distance import bearing_distance_mi, compass_point

__all__ = ["bearing_distance_mi", "compass_point"]
