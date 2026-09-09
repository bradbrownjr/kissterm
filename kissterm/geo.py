"""Great-circle distance and bearing between two decimal-degree points.

Split out of `locator.py` rather than folded into it: `locator.py` converts
between a *single* point and its Maidenhead grid square, while this module
takes *two* points (the operator's own position and a heard station's last
reported one) and answers "how far, which way" -- a different kind of
question with its own well-known formulas (haversine distance, initial
bearing) that have nothing to do with grid squares. No dependency in
`pyproject.toml` already provides this, and the formulas are short enough
that adding one would be the wrong trade -- the same call `locator.py` and
`config.py`'s hand-rolled TOML writer already made.

Distances come back in miles, matching the unit this codebase already uses
everywhere else position-related (`Position.range_mi`,
`Position.precalc_range_mi`, `WeatherReport.wind_speed_mph`) -- there is no
config-wide unit system to plug into, and inventing one for this feature
alone would be new scope nobody asked for.
"""

from __future__ import annotations

import math

__all__ = ["bearing_distance_mi", "compass_point"]

#: Mean earth radius in miles (the conventional constant for a haversine
#: calculation -- the earth is not a perfect sphere, but the error this
#: introduces is well under what matters for "which way, roughly how far").
_EARTH_RADIUS_MI = 3958.8

#: 16-point compass, matching the granularity a station log or bearing
#: display is actually read at -- more points than that is false precision
#: for a number derived from an APRS position report, not a surveyed fix.
_COMPASS_POINTS = (
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)


def bearing_distance_mi(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> tuple[float, float]:
    """Initial bearing (degrees true, 0-360) and great-circle distance (miles)
    from point 1 to point 2.

    Point 1 is the observer (the operator's own position); point 2 is the
    station being looked up. Bearing is the *initial* heading along the
    great-circle path, which is exactly what "look this direction" means for
    a station a few miles to a few hundred miles away -- the two diverge only
    over distances far longer than APRS on VHF/UHF ever covers.
    """
    lat1_r, lon1_r, lat2_r, lon2_r = map(math.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    distance_mi = _EARTH_RADIUS_MI * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    y = math.sin(dlon) * math.cos(lat2_r)
    x = math.cos(lat1_r) * math.sin(lat2_r) - math.sin(lat1_r) * math.cos(lat2_r) * math.cos(dlon)
    bearing_deg = math.degrees(math.atan2(y, x)) % 360.0

    return bearing_deg, distance_mi


def compass_point(bearing_deg: float) -> str:
    """A 16-point compass label (N, NNE, NE, ...) for a bearing in degrees."""
    index = round(bearing_deg / 22.5) % 16
    return _COMPASS_POINTS[index]
