"""Where a latitude and longitude land on a screen, and the line saying
how far and which way a station is from here.

**Equirectangular, with longitude shrunk by cos(latitude) at the centre**
(`View`): within the few hundred kilometres a VHF map covers it is close
to what a road map shows, and it needs no projection library. A view is
its centre and the degrees of longitude across its width; height follows
from the screen's shape, so a degree of latitude is a degree of latitude.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .distance import bearing_distance_mi, compass_point

#: The narrowest and widest views, degrees of longitude across.
MIN_SPAN, MAX_SPAN = 0.02, 360.0
_ROUND = (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000)


def describe(from_lat: float, from_lon: float, lat: float, lon: float) -> str:
    """`24.3 mi 248\N{DEGREE SIGN} WSW`: where a station is from here, in the
    Heard pane's words (`distance.bearing_distance_mi`)."""
    bearing, miles = bearing_distance_mi(from_lat, from_lon, lat, lon)
    figure = f"{miles:.1f}" if miles < 100 else f"{miles:.0f}"
    return f"{figure} mi {bearing:.0f}\N{DEGREE SIGN} {compass_point(bearing)}"


@dataclass
class View:
    """A window on the map: centre, degrees of longitude across, size in
    pixels (or braille dots)."""

    lat: float
    lon: float
    span: float
    width: float
    height: float

    @property
    def _xscale(self) -> float:
        return self.width / self.span  # pixels per degree of longitude

    @property
    def _yscale(self) -> float:
        # A degree of latitude is 1/cos(lat) degrees of longitude long.
        return self._xscale / max(0.05, math.cos(math.radians(self.lat)))

    def to_screen(self, lat: float, lon: float) -> tuple[float, float]:
        return (self.width / 2 + (lon - self.lon) * self._xscale,
                self.height / 2 - (lat - self.lat) * self._yscale)

    def to_map(self, x: float, y: float) -> tuple[float, float]:
        return (self.lat - (y - self.height / 2) / self._yscale,
                self.lon + (x - self.width / 2) / self._xscale)

    def bounds(self) -> tuple[float, float, float, float]:
        """(west, south, east, north) of what is on screen."""
        north, west = self.to_map(0, 0)
        south, east = self.to_map(self.width, self.height)
        return west, south, east, north

    def zoom(self, factor: float) -> None:
        """`factor` > 1 zooms in."""
        self.span = min(MAX_SPAN, max(MIN_SPAN, self.span / factor))

    def zoom_at(self, factor: float, x: float, y: float) -> None:
        """Zoom keeping the place under (x, y) where it is: a pinch's
        focal point, the mouse under a wheel."""
        lat, lon = self.to_map(x, y)
        self.zoom(factor)
        nx, ny = self.to_screen(lat, lon)
        self.pan(x - nx, y - ny)

    def pan(self, dx: float, dy: float) -> None:
        """Move what is on screen by (dx, dy) pixels."""
        self.lon -= dx / self._xscale
        self.lat = max(-85.0, min(85.0, self.lat + dy / self._yscale))

    def scale_bar(self, longest: float) -> tuple[float, str]:
        """(length on screen, label) of a round distance no longer than
        `longest` pixels, for the corner of the map: `(84.0, "10 mi")`."""
        y = self.height / 2
        lat1, lon1 = self.to_map(0, y)
        lat2, lon2 = self.to_map(longest, y)
        _bearing, miles = bearing_distance_mi(lat1, lon1, lat2, lon2)
        best = _ROUND[0]
        for amount in _ROUND:
            if amount <= miles:
                best = amount
        label = f"{best:g} mi"
        return (longest * best / miles if miles else longest), label

    @classmethod
    def fit(cls, points: list[tuple[float, float]], width: float, height: float,
            *, margin: float = 0.15, at_least: float = 0.5) -> View:
        """A view showing every (lat, lon) in `points`, with a margin;
        a single point (or none) gets `at_least` degrees around it."""
        if not points:
            return cls(39.0, -98.0, 60.0, width, height)  # the continental US
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        lat = (min(lats) + max(lats)) / 2
        lon = (min(lons) + max(lons)) / 2
        cos = max(0.05, math.cos(math.radians(lat)))
        span_lon = max(lons) - min(lons)
        # The latitude range, as degrees of longitude at this screen's shape.
        span_lat = (max(lats) - min(lats)) / cos * (width / max(1.0, height))
        span = max(span_lon, span_lat, at_least) * (1 + 2 * margin)
        return cls(lat, lon, min(MAX_SPAN, span), width, height)
