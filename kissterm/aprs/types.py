"""The APRS payload dataclasses -- pure data, no parsing logic.

Every decoder in this package (`position.py`, `mice.py`, `messages.py`,
`telemetry.py`, `parse.py`) needs some subset of these shapes, and `parse.py`'s
dispatcher needs all of them together for `format_packet`. Keeping them in one
leaf module that imports nothing from any sibling module is what keeps the
package's import graph a strict DAG: every format module imports `types` (and,
where it needs shared trailing-field extraction, `extensions`), and nothing
needs to import a format module just to name a return type. A function
appearing in this file is a sign the cut has gone wrong -- put parsing logic in
the module that owns the wire format instead.

Field semantics are documented on the individual dataclasses below because
they are encoding-specific (e.g. `Position.compressed` and
`Position.mic_e_message` tell a caller which of the three position encodings
produced a given value). The top-level `AprsPacket.kind` string is the type
tag a caller switches on; see `parse.py`'s module docstring for the full list
of values it takes.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..ax25.address import AX25Address, AX25Path

__all__ = [
    "Position",
    "Status",
    "Message",
    "WeatherReport",
    "Telemetry",
    "ObjectReport",
    "ThirdParty",
    "AprsPacket",
]


@dataclass(frozen=True, slots=True)
class Position:
    """A decoded position, from any of the three encodings (plain, compressed,
    Mic-E). Not every field applies to every encoding -- ``compressed`` and
    ``mic_e_message`` tell a caller which one produced this value.
    """

    latitude: float
    longitude: float
    symbol_table: str
    symbol_code: str
    course: int | None = None
    speed_knots: float | None = None
    altitude_ft: int | None = None
    ambiguity: int = 0
    timestamp: str | None = None
    comment: str = ""
    compressed: bool = False
    phg: str | None = None
    range_mi: float | None = None
    dfs: str | None = None
    #: Set only for the compressed encoding's ``{``-flagged cs byte pair. The
    #: spec text most implementations agree on calls this a pre-calculated
    #: *radio range* estimate, not an altitude -- see the note in
    #: `position.py`'s `_parse_compressed_position` for why this project
    #: treats it that way.
    precalc_range_mi: float | None = None
    #: Human status text derived from a Mic-E destination callsign's message
    #: bits (e.g. "En Route", "Emergency"). None for non-Mic-E positions.
    mic_e_message: str | None = None


@dataclass(frozen=True, slots=True)
class Status:
    """Free-text status (``>``), station-capabilities (``<``), or query
    (``?``) payload -- all three are "a data type identifier plus a line of
    text" and share this shape.
    """

    text: str
    timestamp: str | None = None


@dataclass(frozen=True, slots=True)
class Message:
    """An APRS message, bulletin, announcement, ack, or reject.

    ``is_ack``/``is_rej`` distinguish the two-way-messaging control replies
    (``:ack12345`` / ``:rej12345``) from an ordinary message; when either is
    set, ``text`` is empty and ``number`` holds the message ID being
    acknowledged or rejected.
    """

    addressee: str
    text: str
    number: str | None = None
    is_ack: bool = False
    is_rej: bool = False


@dataclass(frozen=True, slots=True)
class WeatherReport:
    """A positionless weather report (``_``).

    Field widths in the wire format are fixed but not perfectly uniform
    across vendors in the wild, so extraction here is regex-based per field
    rather than a strict fixed-column split -- a station that omits a field
    entirely (common) just leaves that attribute `None` instead of failing
    the whole report.
    """

    wind_course: int | None = None
    wind_speed_mph: int | None = None
    wind_gust_mph: int | None = None
    temperature_f: int | None = None
    rain_1h_hundredths_in: int | None = None
    rain_24h_hundredths_in: int | None = None
    rain_since_midnight_hundredths_in: int | None = None
    humidity_pct: int | None = None
    pressure_tenths_mb: int | None = None
    timestamp: str | None = None
    comment: str = ""


@dataclass(frozen=True, slots=True)
class Telemetry:
    """A ``T#`` telemetry report: a sequence number, five analog channels,
    and an 8-bit digital channel string.
    """

    sequence: str
    analog: tuple[float, ...]
    digital: str
    comment: str = ""


@dataclass(frozen=True, slots=True)
class ObjectReport:
    """An object (``;``, has a timestamp, name padded to 9 chars) or an item
    (``)``, no timestamp, name is variable-length up to 9 chars). Both are
    "a named, killable position someone else is reporting on behalf of."
    """

    name: str
    alive: bool
    position: Position | None
    timestamp: str | None = None
    is_item: bool = False


@dataclass(frozen=True, slots=True)
class ThirdParty:
    """A third-party (``}``) packet: an IGate or cross-band digipeater
    forwarding someone else's packet verbatim, wrapped in its own
    ``SRC>DST,PATH:payload`` header. ``inner`` is the recursively decoded
    payload; `source`/`destination`/`path` are kept as plain text because
    a third-party header is not guaranteed to be valid AX.25 (APRS-IS feeds
    routinely relay headers with q-constructs that never touched RF).
    """

    source: str
    destination: str
    path: str
    inner: "AprsPacket"


@dataclass(frozen=True, slots=True)
class AprsPacket:
    """The result of decoding one AX.25 UI/PID-0xF0 frame as APRS.

    ``path`` is `None` only for the synthetic inner packet of a `ThirdParty`
    payload, which never had its own AX.25 header. ``kind`` is one of
    ``"position"``, ``"mic-e"``, ``"status"``, ``"message"``, ``"weather"``,
    ``"telemetry"``, ``"object"``, ``"item"``, ``"capabilities"``,
    ``"query"``, ``"third-party"``, or ``"unparsed"``.
    """

    source: AX25Address
    destination: AX25Address
    path: AX25Path | None
    info: bytes
    kind: str
    data: object | None
