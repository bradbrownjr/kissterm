"""The outlines in a view, as screen coordinates: what the phone's canvas
and the terminal's braille map both draw.

**Decimated to the screen**: a point closer than `step` to the last one
kept is dropped, so a coastline across a continent costs a few hundred
points, not tens of thousands -- the phone's canvas goes over a
websocket, and the braille map has two dots to a cell across. **Culled
to the view** twice: whole lines by bounding box (`basemap.lines_in`),
then runs of points off screen, so panning along a coast does not draw
the rest of it.
"""

from __future__ import annotations

import math

from . import basemap
from .project import View

Polyline = list[tuple[float, float]]


def screen_lines(view: View, *, step: float = 1.5,
                 detail: bool | None = None) -> list[tuple[str, list[Polyline]]]:
    """Every outline crossing the view as (layer, polylines in screen
    coordinates), back to front, one entry per layer in drawing order."""
    west, south, east, north = view.bounds()
    xscale = view.width / view.span
    yscale = xscale / max(0.05, math.cos(math.radians(view.lat)))
    cx, cy = view.width / 2 - view.lon * xscale, view.height / 2 + view.lat * yscale
    # A segment may cross the screen with both ends just outside it.
    pad = max(view.width, view.height) * 0.5
    left, top, right, bottom = -pad, -pad, view.width + pad, view.height + pad
    step2 = step * step
    out: list[tuple[str, list[Polyline]]] = []
    by_layer: dict[str, list[Polyline]] = {}
    for layer, points in basemap.lines_in(west, south, east, north, detail=detail):
        lines = by_layer.get(layer)
        if lines is None:
            lines = by_layer[layer] = []
            out.append((layer, lines))
        current: Polyline = []
        lx = ly = 0.0
        for i in range(0, len(points), 2):
            x = cx + points[i] * xscale
            y = cy - points[i + 1] * yscale
            if not (left <= x <= right and top <= y <= bottom):
                if len(current) > 1:
                    current.append((x, y))  # finish the edge leaving the view
                    lines.append(current)
                    current = []
                elif current:
                    current = []
                lx, ly = x, y
                continue
            if not current:
                if i:
                    current.append((lx, ly))  # the edge entering the view
                current.append((x, y))
                lx, ly = x, y
            elif (x - lx) ** 2 + (y - ly) ** 2 >= step2 or i == len(points) - 2:
                current.append((x, y))
                lx, ly = x, y
        if len(current) > 1:
            lines.append(current)
    return [(layer, lines) for layer, lines in out if lines]
