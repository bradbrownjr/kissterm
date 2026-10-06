# AGENTS.md — kissterm/geo

The APRS map's pieces, shared by the terminal (`ui/map_screen.py`) and
the phone (`client/ui/aprs_map.py`). Read `__init__.py` first.

1. **No UI and no station.** Nothing here imports Textual, Flet,
   `kissterm.core` or any transport: the phone client imports this
   package and must run with no station in it (`tests/unit/test_map.py`).
2. **The outlines are shipped data** (`data/*.json.gz`, Natural Earth,
   public domain; `docs/SOURCES.md`). Rebuild them only with
   `scripts/build_basemap.py` from the GeoJSON it names, never by hand;
   `pyproject.toml` package-data ships them.
3. **The detail file loads on first zoom, never at startup** (about half
   a second); the world file is small.
4. **A position is a claim** (AGENTS.md section 7): words built here say
   "reported", never "is at".
5. **Objects live in memory only** (`placemarks.py`): a map restored from
   disk would show stale positions as if heard. Stations' positions are
   the Heard list's.
6. `distance.py` is the Heard pane's bearing and distance, re-exported
   from the package as it was when it was `kissterm/geo.py`.
