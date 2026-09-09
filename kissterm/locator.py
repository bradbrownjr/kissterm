"""Maidenhead grid-square <-> decimal-degree conversion.

The Maidenhead Locator System is the standard way hams give their position
as a short alphanumeric string instead of decimal degrees -- what a
callsign's QTH is usually quoted as. No dependency in `pyproject.toml`
already provides this (checked before writing it), and the algorithm is
short enough that adding one would be the wrong trade, the same call
`config.py` already made for its own hand-rolled TOML writer.

The public algorithm, briefly: longitude spans -180..180 and latitude
-90..90. Each is divided into 18 **fields** of 20 degrees (longitude) and
10 degrees (latitude), lettered A-R -- that's the first two characters.
Each field is then divided into 10x10 **squares** (2 degrees by 1 degree),
given as two digits. Each square is further divided into 24x24
**subsquares** (5 minutes by 2.5 minutes), lettered a-x (or A-X --
subsquare letters are conventionally lowercase but accepted either way on
input). An optional further 10x10 **extended square** division gives 8
total characters. kissterm supports 4, 6, or 8-character precision;
2-character (field-only, ~lower left of a state or two) is too coarse to
be useful for a station's own position and is not offered.

Verified against the commonly-cited reference point FN31pr (the ARRL's own
Newington, CT headquarters grid square, roughly 41.71 N 72.73 W) in
`tests/unit/test_locator.py`.
"""

from __future__ import annotations

import re

__all__ = ["LocatorError", "to_grid", "from_grid"]

#: Field letters run A-R (18 of them: 18*20=360 for longitude, 18*10=180
#: for latitude). Subsquare letters run A-X (24 of them: 24 subsquares per
#: square in both axes).
_FIELD_LETTERS = "ABCDEFGHIJKLMNOPQR"
_SUBSQUARE_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWX"

_GRID_RE = re.compile(r"^[A-Ra-r]{2}(?:\d{2}(?:[A-Xa-x]{2}(?:\d{2})?)?)?$")


class LocatorError(ValueError):
    """A grid square string or coordinate pair could not be converted."""


def to_grid(lat: float, lon: float, precision: int = 6) -> str:
    """Decimal degrees -> a Maidenhead grid square of the given length.

    `precision` must be 4, 6, or 8. Field-only (2-character) precision is
    not offered -- it identifies an area roughly the size of a US state,
    too coarse to mean anything as a station's own QTH.
    """
    if precision not in (4, 6, 8):
        raise LocatorError(f"precision must be 4, 6, or 8, got {precision!r}")
    if not -90.0 <= lat <= 90.0:
        raise LocatorError(f"latitude {lat} out of range -90..90")
    if not -180.0 <= lon <= 180.0:
        raise LocatorError(f"longitude {lon} out of range -180..180")

    # Shift to all-positive ranges (0..360 / 0..180) so every division
    # below is a plain non-negative modulo/floor-divide. Clamp the exact
    # north/east pole values into the last cell rather than overflowing
    # one past the end of the alphabet.
    lon_shifted = min(lon + 180.0, 359.999_999_999)
    lat_shifted = min(lat + 90.0, 179.999_999_999)

    field_lon, lon_rem = divmod(lon_shifted, 20.0)
    field_lat, lat_rem = divmod(lat_shifted, 10.0)
    grid = _FIELD_LETTERS[int(field_lon)] + _FIELD_LETTERS[int(field_lat)]

    square_lon, lon_rem = divmod(lon_rem, 2.0)
    square_lat, lat_rem = divmod(lat_rem, 1.0)
    grid += f"{int(square_lon)}{int(square_lat)}"
    if precision == 4:
        return grid

    sub_lon, lon_rem = divmod(lon_rem, 2.0 / 24)
    sub_lat, lat_rem = divmod(lat_rem, 1.0 / 24)
    grid += _SUBSQUARE_LETTERS[int(sub_lon)].lower() + _SUBSQUARE_LETTERS[int(sub_lat)].lower()
    if precision == 6:
        return grid

    ext_lon = int(lon_rem / (2.0 / 240))
    ext_lat = int(lat_rem / (1.0 / 240))
    return grid + f"{min(ext_lon, 9)}{min(ext_lat, 9)}"


def from_grid(grid: str) -> tuple[float, float]:
    """A Maidenhead grid square (4, 6, or 8 characters) -> (lat, lon).

    Returns the CENTER of the named cell, the standard convention for
    turning a grid square back into a point -- a grid square names an
    area, not a single coordinate, and the center is the least-wrong single
    point to pick. Accepts subsquare letters in either case.
    """
    grid = grid.strip()
    if not _GRID_RE.match(grid) or len(grid) not in (4, 6, 8):
        raise LocatorError(
            f"{grid!r} is not a 4, 6, or 8-character Maidenhead grid square"
        )
    upper = grid.upper()

    lon = _FIELD_LETTERS.index(upper[0]) * 20.0
    lat = _FIELD_LETTERS.index(upper[1]) * 10.0
    lon_width = 20.0
    lat_width = 10.0

    lon += int(upper[2]) * 2.0
    lat += int(upper[3]) * 1.0
    lon_width = 2.0
    lat_width = 1.0

    if len(upper) >= 6:
        lon += _SUBSQUARE_LETTERS.index(upper[4]) * (2.0 / 24)
        lat += _SUBSQUARE_LETTERS.index(upper[5]) * (1.0 / 24)
        lon_width = 2.0 / 24
        lat_width = 1.0 / 24

    if len(upper) == 8:
        lon += int(upper[6]) * (2.0 / 240)
        lat += int(upper[7]) * (1.0 / 240)
        lon_width = 2.0 / 240
        lat_width = 1.0 / 240

    lon_center = lon + lon_width / 2 - 180.0
    lat_center = lat + lat_width / 2 - 90.0
    return lat_center, lon_center
