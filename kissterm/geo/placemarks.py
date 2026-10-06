"""What the map shows: stations and objects heard with a position.

**Stations** come from two places. The heard list keeps every station's
last position (`HeardEntry.last_position`, an APRS report or a grid
square in a node's beacon); this store adds what the heard list does not
keep, the APRS symbol and comment. **Objects and items** (`;` and `)`)
exist only here: they are someone else's report about a thing, not a
station heard, so they never enter the heard list. A killed object is
removed at once -- its originator is saying it is no longer there.

In memory only, like the dedup window: a map restored from disk would
show stale positions as if heard. `MAX_OBJECTS` bounds a busy channel's
object traffic (a weather net, a tracked event), oldest dropped first.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

#: Objects and items kept, newest win.
MAX_OBJECTS = 500

STATION, OBJECT, ITEM, ME = "station", "object", "item", "me"


@dataclass(slots=True)
class Placemark:
    """One thing on the map. `by` is who reported an object; `symbol` the
    two-character APRS table and code ("" when unknown, e.g. a grid
    square)."""

    name: str
    lat: float
    lon: float
    kind: str = STATION
    symbol: str = ""
    comment: str = ""
    when: float = 0.0
    by: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "lat": self.lat, "lon": self.lon, "kind": self.kind,
                "symbol": self.symbol, "comment": self.comment, "when": self.when,
                "by": self.by}


class Placemarks:
    """The symbol and comment of each station, and every live object."""

    def __init__(self) -> None:
        self.stations: dict[str, Placemark] = {}
        self.objects: dict[str, Placemark] = {}

    def station(self, callsign: str, lat: float, lon: float, *, symbol: str = "",
                comment: str = "", when: float | None = None) -> None:
        self.stations[callsign] = Placemark(
            callsign, lat, lon, STATION, symbol, comment,
            time.time() if when is None else when)

    def object(self, name: str, by: str, alive: bool, lat: float | None = None,
               lon: float | None = None, *, item: bool = False, symbol: str = "",
               comment: str = "", when: float | None = None) -> None:
        """Record or kill an object. Keyed by name alone: APRS objects are
        global, and a second station updating one is taking it over."""
        key = name.strip().upper()
        if not key:
            return
        if not alive:
            self.objects.pop(key, None)
            return
        if lat is None or lon is None:
            return  # "if they included coordinates" (operator, 2026-10-06)
        self.objects.pop(key, None)  # re-inserted last: the newest
        self.objects[key] = Placemark(
            name.strip(), lat, lon, ITEM if item else OBJECT, symbol, comment,
            time.time() if when is None else when, by)
        while len(self.objects) > MAX_OBJECTS:
            self.objects.pop(next(iter(self.objects)))
