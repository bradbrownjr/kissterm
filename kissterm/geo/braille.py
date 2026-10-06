"""Lines drawn in braille cells: the terminal's map (operator, 2026-10-06,
"Braille-dot map").

A braille character is a 2-by-4 grid of dots, so a terminal cell (about
twice as tall as it is wide) holds dots that are close to square: a map
drawn in them keeps its shape, at eight times the resolution of one
character per cell. Each cell remembers the layer that last drew in it,
so the screen colours a road as a road even where a county line crosses
it (later layers win: `render.screen_lines` is back to front).

`ascii_safe` (the setting for terminals or fonts without braille) draws
`.` for any cell with a dot in it instead: coarser, but readable.

Text (a station's name, its marker) goes over the dots, cell by cell.
"""

from __future__ import annotations

#: Dot bit for (column, row) inside a cell: Unicode's braille numbering.
_BITS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))


class Canvas:
    """`cols` by `rows` cells, drawn on in dots: `cols * 2` by `rows * 4`."""

    def __init__(self, cols: int, rows: int, *, ascii_safe: bool = False) -> None:
        self.cols, self.rows = max(1, cols), max(1, rows)
        self.ascii_safe = ascii_safe
        self.dots = [[0] * self.cols for _ in range(self.rows)]
        self.layer: list[list[str]] = [[""] * self.cols for _ in range(self.rows)]
        #: (row, col) -> (text, style key) written over the dots.
        self.text: dict[tuple[int, int], tuple[str, str]] = {}

    @property
    def width(self) -> int:
        return self.cols * 2

    @property
    def height(self) -> int:
        return self.rows * 4

    def dot(self, x: float, y: float, layer: str) -> None:
        ix, iy = int(x), int(y)
        if 0 <= ix < self.width and 0 <= iy < self.height:
            row, col = iy >> 2, ix >> 1
            self.dots[row][col] |= _BITS[iy & 3][ix & 1]
            self.layer[row][col] = layer

    def line(self, x0: float, y0: float, x1: float, y1: float, layer: str) -> None:
        """A straight line, one dot per step along its longer axis."""
        dx, dy = x1 - x0, y1 - y0
        steps = int(max(abs(dx), abs(dy)))
        if steps == 0:
            self.dot(x0, y0, layer)
            return
        for i in range(steps + 1):
            self.dot(x0 + dx * i / steps, y0 + dy * i / steps, layer)

    def polyline(self, points: list[tuple[float, float]], layer: str) -> None:
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            self.line(x0, y0, x1, y1, layer)

    def write(self, col: int, row: int, text: str, style: str) -> bool:
        """Put `text` at a cell, over any dots; False (and nothing written)
        if it would not fit or would cover other text."""
        if not (0 <= row < self.rows) or col < 0 or col + len(text) > self.cols:
            return False
        if any((row, col + i) in self.text for i in range(len(text))):
            return False
        for i, char in enumerate(text):
            self.text[(row, col + i)] = (char, style)
        return True

    def cells(self) -> list[list[tuple[str, str]]]:
        """Every row as (character, style key) per cell: a layer name for a
        dot, the style given to `write` for text, "" for nothing."""
        out = []
        for r in range(self.rows):
            row = []
            for c in range(self.cols):
                written = self.text.get((r, c))
                if written is not None:
                    row.append(written)
                elif self.dots[r][c]:
                    char = "." if self.ascii_safe else chr(0x2800 + self.dots[r][c])
                    row.append((char, self.layer[r][c]))
                else:
                    row.append((" ", ""))
            out.append(row)
        return out
