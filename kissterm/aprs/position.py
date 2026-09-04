"""Position decoding: the uncompressed DDMM.mm form and the base-91 compressed form.

Two encodings of "where" are in wide use on APRS and both live here because
they share the same trailing-extension handling (`extensions.extract_extras`)
and because a future editor fixing a bug in one is likely to need to check
whether the other has the same bug. The uncompressed form
(``4903.50N/07201.75W``) is what a human reads on a screen; *ambiguity* --
blanking trailing minute digits with spaces to say "I only know this station
to the nearest 10 minutes" -- is a deliberate imprecision feature, not
malformed input, and is decoded by treating a blanked digit as zero while
still counting how many digits were blanked (`_parse_lat`/`_parse_lon`'s
second return value).

The compressed form packs the same information into 13 ASCII bytes using
base-91 (see `extensions.b91_decode`) for latitude and longitude, plus a
trailing cs+T byte trio that carries either a course/speed pair or -- when
the first cs byte is literally ``{`` -- a pre-calculated radio-range
estimate. That one flag byte is the single most-confused byte in the whole
APRS spec; read `_parse_compressed_position`'s docstring before touching it.

Both parsers are total: a truncated or garbled field raises `ValueError`,
which `parse.py`'s `parse_packet` catches and downgrades to
``kind="unparsed"``. A change here must never let that become an uncaught
raise -- this is one of the two most heavily exercised decoders in the
package (Mic-E, in `mice.py`, is the other), so a mistake here is loud.
"""

from __future__ import annotations

import re

from .extensions import b91_decode, extract_extras
from .types import Position

__all__ = ["parse_position_field"]

_LAT_RE = re.compile(r"^(\d{2})([0-9 ]{2})\.([0-9 ]{2})([NS])$")
_LON_RE = re.compile(r"^(\d{3})([0-9 ]{2})\.([0-9 ]{2})([EW])$")


def _parse_lat(s: str) -> tuple[float, int]:
    m = _LAT_RE.match(s)
    if not m:
        raise ValueError(f"bad latitude field {s!r}")
    deg = int(m.group(1))
    min_int, min_frac, hemi = m.group(2), m.group(3), m.group(4)
    ambiguity = min_int.count(" ") + min_frac.count(" ")
    minutes = int(min_int.replace(" ", "0")) + int(min_frac.replace(" ", "0")) / 100
    lat = deg + minutes / 60
    return (-lat if hemi == "S" else lat), ambiguity


def _parse_lon(s: str) -> tuple[float, int]:
    m = _LON_RE.match(s)
    if not m:
        raise ValueError(f"bad longitude field {s!r}")
    deg = int(m.group(1))
    min_int, min_frac, hemi = m.group(2), m.group(3), m.group(4)
    ambiguity = min_int.count(" ") + min_frac.count(" ")
    minutes = int(min_int.replace(" ", "0")) + int(min_frac.replace(" ", "0")) / 100
    lon = deg + minutes / 60
    return (-lon if hemi == "W" else lon), ambiguity


def parse_position_field(body: str) -> Position:
    """Parse the position portion common to ``!``/``=``/``/``/``@`` and to
    object/item reports, after any data-type char and timestamp are already
    stripped. Dispatches on the first byte: a digit means the readable
    ``DDMM.mm`` form, anything else (the symbol-table selector) means the
    13-byte compressed form.
    """
    if not body:
        raise ValueError("empty position field")
    if body[0].isdigit():
        return _parse_uncompressed_position(body)
    return _parse_compressed_position(body)


def _parse_uncompressed_position(body: str) -> Position:
    if len(body) < 19:
        raise ValueError("uncompressed position field truncated")
    lat, lat_amb = _parse_lat(body[0:8])
    sym_table = body[8]
    lon, lon_amb = _parse_lon(body[9:18])
    sym_code = body[18]
    comment, extras = extract_extras(body[19:])
    return Position(
        latitude=lat,
        longitude=lon,
        symbol_table=sym_table,
        symbol_code=sym_code,
        ambiguity=max(lat_amb, lon_amb),
        comment=comment,
        compressed=False,
        **extras,
    )


def _parse_compressed_position(body: str) -> Position:
    """Decode the 13-byte compressed form.

    lat = 90 - (base91(lat4) / 380926), lon = -180 + (base91(lon4) / 190463)
    per the APRS compressed-position formula. The trailing cs/T byte trio
    carries either course+speed (the common case) or, when the first cs byte
    is ``{``, a pre-calculated radio-range estimate -- several descriptions
    of this extension call it an altitude instead of a range, and this
    project was unable to fully resolve that discrepancy. `precalc_range_mi`
    (not `altitude_ft`) is populated here rather than guessing, so a caller
    can tell "this came from the ambiguous cs-byte extension" apart from
    "this came from an unambiguous ``/A=nnnnnn`` or Mic-E altitude field".
    """
    if len(body) < 13:
        raise ValueError("compressed position field truncated")
    sym_table = body[0]
    lat_raw, lon_raw = body[1:5], body[5:9]
    sym_code = body[9]
    c1, s1 = body[10], body[11]
    # body[12] is the compression-type byte T; its GPS-fix/NMEA-source/origin
    # bits are not surfaced yet -- nothing in kissterm consumes them today.
    comment, extras = extract_extras(body[13:])

    lat = 90 - (b91_decode(lat_raw) / 380926.0)
    lon = -180 + (b91_decode(lon_raw) / 190463.0)

    kwargs: dict[str, object] = dict(
        latitude=lat,
        longitude=lon,
        symbol_table=sym_table,
        symbol_code=sym_code,
        compressed=True,
        comment=comment,
    )
    if c1 != " ":
        cval, sval = ord(c1) - 33, ord(s1) - 33
        if c1 == "{":
            kwargs["precalc_range_mi"] = 2 * (1.08**sval)
        elif 0 <= cval <= 89:
            kwargs["course"] = cval * 4
            kwargs["speed_knots"] = (1.08**sval) - 1

    for key, value in extras.items():
        kwargs.setdefault(key, value)
    return Position(**kwargs)
