"""The README screenshots' renderer draws borders that join
(`scripts/cellshot.py`; operator, 2026-09-29: "broken lines in the
rendering"). Shapes only: no font file or network needed."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import cellshot  # noqa: E402

CW, CH = 15, 30
FG, BG = (255, 255, 255), (0, 0, 0)


def _draw(text: str) -> Image.Image:
    image = Image.new("RGB", (CW * len(text), CH), BG)
    draw = ImageDraw.Draw(image)
    for i, char in enumerate(text):
        assert cellshot._draw_shape(draw, char, (i * CW, 0, (i + 1) * CW, CH), FG, BG), char
    return image


def _lit(image: Image.Image, x: int, y: int) -> bool:
    return image.getpixel((x, y)) == FG


def test_a_line_runs_unbroken_across_cells():
    image = _draw("───")
    row = next(y for y in range(CH) if _lit(image, 0, y))
    assert all(_lit(image, x, row) for x in range(image.width))


def test_a_corner_meets_its_line_without_a_gap_or_a_nub():
    for text in ("┌─", "╭─"):
        image = _draw(text)
        row = next(y for y in range(CH) if _lit(image, image.width - 1, y))
        # From where the corner turns (its centre; a rounded one's curve
        # ends nearer the edge) to the far edge, unbroken.
        start = CW // 2 if text[0] == "┌" else CW - 4
        assert all(_lit(image, x, row) for x in range(start, image.width)), text
        # Nothing left of the vertical arm or above the horizontal one.
        assert not any(_lit(image, x, y) for x in range(CW // 2 - 2) for y in range(CH)), text
        assert not any(_lit(image, x, y) for x in range(image.width) for y in range(row - 2)), text


def test_every_rounded_corner_is_drawn():
    for char in "╭╮╯╰":
        _draw(char)


@pytest.mark.parametrize(("words", "fraction"), [
    (["HALF"], 0.5), (["ONE", "EIGHTH"], 0.125), (["THREE", "QUARTERS"], 0.75),
    (["SEVEN", "EIGHTHS"], 0.875), (["TWO", "HALVES"], None),
])
def test_block_fractions(words, fraction):
    assert cellshot._fraction(words) == fraction


def test_every_block_element_is_drawn():
    for code in range(0x2580, 0x25A0):
        _draw(chr(code))


def test_a_dashed_line_is_left_to_the_font():
    image = Image.new("RGB", (CW, CH))
    assert not cellshot._draw_shape(ImageDraw.Draw(image), "┄", (0, 0, CW, CH), FG, BG)
