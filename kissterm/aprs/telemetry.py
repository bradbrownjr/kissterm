"""Weather reports and telemetry: two positionless, fixed-key report formats.

Both are "a data-type identifier plus a run of known fields," which is why
they share a file even though the fields mean different things. A weather
report's fields are all independent sensor readings pulled out by regex
rather than a strict fixed-column split, because field widths in the wire
format are nominally fixed but vendors do not agree in the wild -- a station
that omits one field (common) just leaves that attribute `None` instead of
failing the whole report. Telemetry's fields are strictly comma-positional
instead (sequence, 5 analog channels, one digital-channel string, then a
free-text comment), because that format has no vendor-variance problem to
work around.

Neither format carries a position of its own. A station beaconing weather
data *with* a position uses an ordinary position report (`position.py`) whose
comment happens to also match these weather field patterns -- that case is
handled entirely by `_extract_extras`-style comment parsing in the position
path, not here, and this module has no dependency on `position.py` because
of it.
"""

from __future__ import annotations

import re

from .types import Telemetry, WeatherReport

__all__ = ["parse_weather", "parse_telemetry"]

_WX_TS_RE = re.compile(r"^(\d{8})")
_WX_FIELD_RE = re.compile(r"([csgtrpPhb])(-?\d{2,5})")


def parse_weather(body: str) -> WeatherReport:
    timestamp = None
    m = _WX_TS_RE.match(body)
    if m:
        timestamp = m.group(1)
        body = body[m.end() :]
    fields: dict[str, int] = {}
    for m in _WX_FIELD_RE.finditer(body):
        fields.setdefault(m.group(1), int(m.group(2)))
    return WeatherReport(
        wind_course=fields.get("c"),
        wind_speed_mph=fields.get("s"),
        wind_gust_mph=fields.get("g"),
        temperature_f=fields.get("t"),
        rain_1h_hundredths_in=fields.get("r"),
        rain_24h_hundredths_in=fields.get("p"),
        rain_since_midnight_hundredths_in=fields.get("P"),
        humidity_pct=fields.get("h"),
        pressure_tenths_mb=fields.get("b"),
        timestamp=timestamp,
    )


def parse_telemetry(body: str) -> Telemetry:
    if not body.startswith("#"):
        raise ValueError("telemetry field missing '#'")
    parts = body[1:].split(",")
    if len(parts) < 6:
        raise ValueError("telemetry needs a sequence number and 5 analog channels")
    analog = tuple(float(p) for p in parts[1:6])
    digital = parts[6] if len(parts) > 6 else ""
    comment = ",".join(parts[7:])
    return Telemetry(sequence=parts[0], analog=analog, digital=digital, comment=comment)
