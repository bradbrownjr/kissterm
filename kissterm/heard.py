"""The MHEARD table -- who kissterm has heard, independent of any protocol.

This is not an APRS feature. Every AX.25 frame that passes through a
`kissterm.transport.base.FrameTransport` -- a connect request, an APRS
beacon, a plain unproto CQ, someone else's I frame on a link kissterm is only
overhearing -- names a source station, and "who has this radio heard, and
when, and through what path" is useful long before anything above the frame
layer gets involved. Keeping it here rather than folding it into the APRS
decoder means a pure-AX.25 station that never sends a position report still
shows up, and it means the APRS pane can enrich an entry (via `set_position`)
without owning the table it is enriching.

`direct` answers a specific question a station log needs answered up front:
did we hear *this* station's own transmitter, or did we hear a digipeater
repeating it? AX.25's has-been-repeated bit says exactly that -- if every
digipeater address in the path still has that bit clear, nothing between the
source and us has retransmitted the frame yet, so whatever we received is the
original signal. One digipeater bit set anywhere in the path breaks that.

Capacity is bounded and eviction is least-recently-heard, not
least-recently-added, because a station that has been in view for hours and
just went quiet is far more likely to be worth keeping than a station heard
once ten minutes ago and never again -- LRU by *last heard* approximates "is
this station probably still around" far better than insertion order does.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass

from .ax25.frame import AX25Frame

HeardCallback = Callable[["HeardEntry"], None]

DEFAULT_CAPACITY = 500


@dataclass(slots=True)
class HeardEntry:
    """One station's MHEARD record. Mutated in place by `HeardTable.record`
    so a caller holding a reference (e.g. a Textual row bound to this object)
    sees updates without re-fetching.
    """

    callsign: str
    first_heard: float
    last_heard: float
    count: int = 1
    port: int = 0
    last_path: str = ""
    direct: bool = True
    last_frame_kind: str = ""
    last_position: tuple[float, float] | None = None

    def to_dict(self) -> dict:
        return {
            "callsign": self.callsign,
            "first_heard": self.first_heard,
            "last_heard": self.last_heard,
            "count": self.count,
            "port": self.port,
            "last_path": self.last_path,
            "direct": self.direct,
            "last_frame_kind": self.last_frame_kind,
            "last_position": list(self.last_position) if self.last_position else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HeardEntry":
        pos = d.get("last_position")
        return cls(
            callsign=d["callsign"],
            first_heard=d["first_heard"],
            last_heard=d["last_heard"],
            count=d.get("count", 1),
            port=d.get("port", 0),
            last_path=d.get("last_path", ""),
            direct=d.get("direct", True),
            last_frame_kind=d.get("last_frame_kind", ""),
            last_position=tuple(pos) if pos else None,  # type: ignore[arg-type]
        )


class HeardTable:
    """A bounded, LRU-by-last-heard table of every station this radio has
    heard, across every frame transport and every port.
    """

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        self.capacity = capacity
        self._entries: dict[str, HeardEntry] = {}
        self._subscribers: list[HeardCallback] = []

    def subscribe(self, callback: HeardCallback) -> Callable[[], None]:
        """Register a callback fired with the affected `HeardEntry` on every
        `record` or `set_position`. Returns an unsubscribe callable, matching
        `FrameTransport.subscribe`'s shape so the UI treats both the same way.
        """
        self._subscribers.append(callback)

        def _remove() -> None:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

        return _remove

    def _notify(self, entry: HeardEntry) -> None:
        for callback in list(self._subscribers):
            callback(entry)

    def record(self, frame: AX25Frame, port: int = 0) -> HeardEntry:
        """Observe one frame. Safe to call for every frame from every
        transport -- frames from non-source-identifying contexts still have
        a source address, so there is nothing to filter here.
        """
        callsign = str(frame.path.source)
        now = time.time()
        direct = not any(rpt.ch for rpt in frame.path.repeaters)
        path = ",".join(rpt.display() for rpt in frame.path.repeaters)

        entry = self._entries.get(callsign)
        if entry is None:
            entry = HeardEntry(
                callsign=callsign,
                first_heard=now,
                last_heard=now,
                count=1,
                port=port,
                last_path=path,
                direct=direct,
                last_frame_kind=frame.control_name,
            )
        else:
            entry.last_heard = now
            entry.count += 1
            entry.port = port
            entry.last_path = path
            entry.direct = direct
            entry.last_frame_kind = frame.control_name
        self._entries[callsign] = entry
        self._evict_if_needed()
        self._notify(entry)
        return entry

    def set_position(self, callsign: str, lat: float, lon: float) -> None:
        """Attach a last-known position to an existing entry. Fed by the APRS
        layer after it decodes a position report -- `HeardTable` never
        decodes APRS itself, so it cannot derive this on its own.
        """
        entry = self._entries.get(callsign)
        if entry is None:
            return
        entry.last_position = (lat, lon)
        self._notify(entry)

    def _evict_if_needed(self) -> None:
        while len(self._entries) > self.capacity:
            oldest = min(self._entries.values(), key=lambda e: e.last_heard)
            del self._entries[oldest.callsign]

    def get(self, callsign: str) -> HeardEntry | None:
        return self._entries.get(callsign)

    def __len__(self) -> int:
        return len(self._entries)

    def entries(self, sort: str = "last") -> list[HeardEntry]:
        """Snapshot of every entry, newest-first by the requested key.

        ``sort`` is one of ``"last"`` (last heard, the default -- what a
        monitor table shows by default), ``"first"``, ``"count"``, or
        ``"callsign"`` (alphabetical, not "newest first").
        """
        values = list(self._entries.values())
        if sort == "last":
            values.sort(key=lambda e: e.last_heard, reverse=True)
        elif sort == "first":
            values.sort(key=lambda e: e.first_heard, reverse=True)
        elif sort == "count":
            values.sort(key=lambda e: e.count, reverse=True)
        elif sort == "callsign":
            values.sort(key=lambda e: e.callsign)
        else:
            raise ValueError(f"unknown sort key {sort!r}")
        return values

    def to_json(self) -> str:
        return json.dumps([e.to_dict() for e in self._entries.values()])

    @classmethod
    def from_json(cls, text: str, capacity: int = DEFAULT_CAPACITY) -> "HeardTable":
        """Rebuild a table from `to_json` output. A blank or corrupt file
        (first run, or a crash mid-write) yields an empty table rather than
        raising -- the heard list is a convenience cache, not data anyone
        should lose a session over.
        """
        table = cls(capacity=capacity)
        try:
            rows = json.loads(text) if text.strip() else []
        except (json.JSONDecodeError, ValueError):
            return table
        for row in rows:
            try:
                entry = HeardEntry.from_dict(row)
            except (KeyError, TypeError, ValueError):
                continue
            table._entries[entry.callsign] = entry
        table._evict_if_needed()
        return table
