"""Draw a running Textual app's screen as a PNG, cell by cell, with Pillow.

Why not the SVG Textual exports (operator, 2026-10-02: "why are we using
browserless for a terminal UI?"): an SVG is not a picture until something
renders it, and every renderer tried failed on the same thing, the font.
cairosvg cannot load the web font the SVG names, falls back to one whose
box-drawing glyphs are shorter than a row, and draws dashed borders; with
the font supplied it still seams between cell backgrounds. Headless Chrome
loaded the font but needed a browserless server, which refused any page
scale but 1 and then every page. A terminal screen is a grid of cells,
so this draws the grid: whole-pixel cells, nothing to seam, nothing to fetch.

**Box-drawing and block characters are drawn, not typeset.** Their shape
comes from the character's Unicode name ("BOX DRAWINGS LIGHT DOWN AND
RIGHT", "LOWER ONE EIGHTH BLOCK", "QUADRANT UPPER LEFT"), so a border
joins whatever the font's glyphs look like. Dashed and diagonal lines,
which do not need to join, fall back to the font.

**The font** is 0xProto Nerd Font Mono, the operator's terminal font (the
Mono build keeps every glyph to one cell). It is downloaded once from the
pinned Nerd Fonts release, checked against `FONT_SHA256`, and cached in
`~/.cache/kissterm/fonts/`; `KISSTERM_SHOT_FONT_DIR` names another folder
holding the same three files. A character 0xProto lacks (Textual's tree
markers, `▶` and `▼`) is drawn from whichever installed monospace font
fontconfig says has it, as a terminal falls back; without fontconfig it
shows as the font's missing-glyph box.
"""

from __future__ import annotations

import functools
import hashlib
import io
import os
import subprocess
import unicodedata
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from rich.cells import cell_len
from rich.color import Color
from rich.console import Console
from rich.style import Style
from rich.terminal_theme import SVG_EXPORT_THEME

FONT_URL = "https://github.com/ryanoasis/nerd-fonts/releases/download/v3.5.1/0xProto.zip"
FONT_SHA256 = "8951412356611266734e2e9904173d437b804af1ffce4fe1804feef4fe9c8c3b"
FACES = {
    "regular": "0xProtoNerdFontMono-Regular.ttf",
    "bold": "0xProtoNerdFontMono-Bold.ttf",
    "italic": "0xProtoNerdFontMono-Italic.ttf",
}
#: Points: about the pixel size the old Chrome renders came out at.
FONT_SIZE = 24
#: Pixels of the screen's own background around the grid.
MARGIN = 16

Rgb = tuple[int, int, int]


def font_dir() -> Path:
    """The folder holding `FACES`, downloading them the first time."""
    named = os.environ.get("KISSTERM_SHOT_FONT_DIR")
    if named:
        return Path(named)
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    folder = cache / "kissterm" / "fonts" / "0xProto-3.5.1"
    if all((folder / name).is_file() for name in FACES.values()):
        return folder
    with urllib.request.urlopen(FONT_URL, timeout=120) as response:
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != FONT_SHA256:
        raise RuntimeError(f"{FONT_URL} has SHA-256 {digest}, expected {FONT_SHA256}")
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in (*FACES.values(), "LICENSE"):
            (folder / name).write_bytes(archive.read(name))
    return folder


def screen_lines(app) -> list[list]:
    """The screen as rows of Rich segments: what `App.export_screenshot`
    prints, without turning it into SVG (Textual 8.2.8)."""
    width, height = app.size
    console = Console(width=width, height=height, file=io.StringIO(), force_terminal=True,
                      color_system="truecolor", legacy_windows=False, safe_box=False)
    update = app.screen._compositor.render_update(
        full=True, screen_stack=app._background_screens, simplify=False)
    return console.render_lines(update, console.options.update(height=height), pad=True)


def save(app, path: Path, *, fonts: Path | None = None) -> None:
    """The app's current screen, as a PNG at `path`."""
    render(screen_lines(app), fonts or font_dir()).save(path, optimize=True)


def render(lines: list[list], fonts: Path, size: int = FONT_SIZE) -> Image.Image:
    faces = {key: ImageFont.truetype(str(fonts / name), size) for key, name in FACES.items()}
    regular = faces["regular"]
    ascent, descent = regular.getmetrics()
    cw = round(regular.getlength("M"))
    ch = ascent + descent
    cols = max((sum(cell_len(seg.text) for seg in line if not seg.control) for line in lines),
               default=0)
    theme_bg = SVG_EXPORT_THEME.background_color
    image = Image.new("RGB", (cols * cw + 2 * MARGIN, len(lines) * ch + 2 * MARGIN),
                      tuple(theme_bg))
    draw = ImageDraw.Draw(image)
    glyphs = []
    # Backgrounds first, for the whole screen: a glyph that overhangs its
    # cell is then never painted over by the next cell's background.
    for row, line in enumerate(lines):
        col = 0
        y = MARGIN + row * ch
        for seg in line:
            if seg.control:
                # The compositor's cursor moves: not cells.
                continue
            fg, bg = _colours(seg.style)
            for char in seg.text:
                width = cell_len(char)
                if not width:
                    continue
                x = MARGIN + col * cw
                draw.rectangle((x, y, x + width * cw - 1, y + ch - 1), fill=bg)
                if not char.isspace():
                    glyphs.append((char, x, y, width, fg, bg, seg.style))
                col += width
    for char, x, y, width, fg, bg, style in glyphs:
        box = (x, y, x + width * cw, y + ch)
        if not _draw_shape(draw, char, box, fg, bg):
            face = faces["bold" if style and style.bold else
                         "italic" if style and style.italic else "regular"]
            if _missing(face, char):
                face = _fallback(char, size) or face
            draw.text((x, y + ascent), char, font=face, fill=fg, anchor="ls")
        if style and style.underline:
            draw.line((x, y + ascent + 2, x + width * cw - 1, y + ascent + 2), fill=fg)
    return image


def _missing(face, char: str) -> bool:
    """Does `face` lack `char`? Its drawing is then the font's own
    missing-glyph box, the same as for a code point no font has."""
    return _lacks(face.path, face.size, char)


@functools.cache
def _lacks(path: str, size: int, char: str) -> bool:
    face = ImageFont.truetype(path, size)
    return _ink(face, char) == _ink(face, "\U0010fffd")


def _ink(face, char: str) -> bytes:
    size = int(face.size) * 2
    image = Image.new("L", (size, size))
    ImageDraw.Draw(image).text((0, 0), char, font=face, fill=255)
    return image.tobytes()


@functools.cache
def _fallback(char: str, size: int):
    """An installed monospace font that has `char`, by fontconfig."""
    try:
        path = subprocess.run(
            ["fc-match", "-f", "%{file}", f"monospace:charset={ord(char):x}"],
            capture_output=True, text=True, timeout=10, check=True).stdout.strip()
        face = ImageFont.truetype(path, size)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return None if _missing(face, char) else face


def _rgb(color: Color | None, *, foreground: bool) -> Rgb | None:
    if color is None or color.is_default:
        return None
    return tuple(color.get_truecolor(SVG_EXPORT_THEME, foreground=foreground))


def _colours(style: Style | None) -> tuple[Rgb, Rgb]:
    fg = bg = None
    if style is not None:
        fg = _rgb(style.color, foreground=True)
        bg = _rgb(style.bgcolor, foreground=False)
    fg = fg or tuple(SVG_EXPORT_THEME.foreground_color)
    bg = bg or tuple(SVG_EXPORT_THEME.background_color)
    if style is not None and style.reverse:
        fg, bg = bg, fg
    if style is not None and style.dim:
        fg = _blend(fg, bg, 0.5)
    return fg, bg


def _blend(a: Rgb, b: Rgb, t: float) -> Rgb:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


# --- shapes drawn rather than typeset ----------------------------------------

_WEIGHTS = {"LIGHT", "HEAVY", "DOUBLE", "SINGLE"}
_ARMS = {"UP": ("UP",), "DOWN": ("DOWN",), "LEFT": ("LEFT",), "RIGHT": ("RIGHT",),
         "HORIZONTAL": ("LEFT", "RIGHT"), "VERTICAL": ("UP", "DOWN")}
_NUMBERS = {"ONE": 1, "THREE": 3, "FIVE": 5, "SEVEN": 7}
_SIDES = {
    "LOWER": lambda f: (0, 1 - f, 1, 1),
    "UPPER": lambda f: (0, 0, 1, f),
    "LEFT": lambda f: (0, 0, f, 1),
    "RIGHT": lambda f: (1 - f, 0, 1, 1),
}


def _fraction(words: list[str]) -> float | None:
    """"HALF" -> 0.5, "THREE EIGHTHS" -> 0.375, "ONE QUARTER" -> 0.25."""
    if words == ["HALF"]:
        return 0.5
    if len(words) == 2 and words[0] in _NUMBERS:
        unit = {"EIGHTH": 8, "EIGHTHS": 8, "QUARTER": 4, "QUARTERS": 4}.get(words[1])
        if unit:
            return _NUMBERS[words[0]] / unit
    return None


def _draw_shape(draw, char: str, box, fg: Rgb, bg: Rgb) -> bool:
    """Draw `char` if it is a box-drawing or block character this knows;
    False to typeset it from the font instead."""
    try:
        name = unicodedata.name(char)
    except ValueError:
        return False
    if name.startswith("BOX DRAWINGS "):
        return _box(draw, name[len("BOX DRAWINGS "):].split(), box, fg)
    return _block(draw, name, box, fg, bg)


def _box(draw, words: list[str], box, fg: Rgb) -> bool:
    if any(w in ("DASH", "DIAGONAL") for w in words):
        return False
    if "ARC" in words:
        return _arc(draw, words, box, fg)
    words = [w for w in words if w not in ("ARC", "AND")]
    arms: dict[str, str] = {}
    if words and words[0] in _WEIGHTS:
        # "LIGHT DOWN RIGHT", "LIGHT LEFT HEAVY RIGHT": a weight, then its arms.
        weight = "LIGHT"
        for word in words:
            if word in _WEIGHTS:
                weight = word
            elif word in _ARMS:
                for arm in _ARMS[word]:
                    arms[arm] = weight
    else:
        # "DOWN LIGHT RIGHT HEAVY": each arm, then its weight.
        pending: list[str] = []
        for word in words:
            if word in _ARMS:
                pending.extend(_ARMS[word])
            elif word in _WEIGHTS:
                for arm in pending:
                    arms[arm] = word
                pending = []
    if not arms:
        return False
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    thin = max(1, round((x1 - x0) / 9))
    widest = 0
    for arm, weight in arms.items():
        width = thin * 2 if weight == "HEAVY" else thin
        offsets = (-thin, thin) if weight == "DOUBLE" else (0,)
        for off in offsets:
            lo = -(width // 2)
            # Each arm runs from the cell's edge to its centre line; the
            # junction square below closes the corner without a nub.
            if arm in ("LEFT", "RIGHT"):
                y = cy + off + lo
                xa, xb = (x0, cx) if arm == "LEFT" else (cx, x1 - 1)
                draw.rectangle((xa, y, xb, y + width - 1), fill=fg)
            else:
                x = cx + off + lo
                ya, yb = (y0, cy) if arm == "UP" else (cy, y1 - 1)
                draw.rectangle((x, ya, x + width - 1, yb), fill=fg)
        widest = max(widest, width + (2 * thin if weight == "DOUBLE" else 0))
    if len(arms) > 1:
        lo = -(widest // 2)
        draw.rectangle((cx + lo, cy + lo, cx + lo + widest - 1, cy + lo + widest - 1), fill=fg)
    return True


#: A rounded corner: (arms, the circle centre's offset from the cell
#: centre in radii, PIL's start and end angles, clockwise from 3 o'clock).
_ARC = {
    ("DOWN", "RIGHT"): ((1, 1), 180, 270),
    ("DOWN", "LEFT"): ((-1, 1), 270, 360),
    ("LEFT", "UP"): ((-1, -1), 0, 90),
    ("RIGHT", "UP"): ((1, -1), 90, 180),
}


def _arc(draw, words: list[str], box, fg: Rgb) -> bool:
    """╭╮╯╰: a quarter circle from the centre line of one arm to the
    other, then straight to the cell's edges."""
    arms = tuple(sorted(w for w in words if w in ("UP", "DOWN", "LEFT", "RIGHT")))
    if arms not in _ARC:
        return False
    (dx, dy), start, end = _ARC[arms]
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    thin = max(1, round((x1 - x0) / 9))
    lo = -(thin // 2)
    r = (x1 - x0) // 2
    ox, oy = cx + dx * r, cy + dy * r
    draw.arc((ox - r + lo, oy - r + lo, ox + r - lo - 1, oy + r - lo - 1),
             start, end, fill=fg, width=thin)
    # The straight runs from where the arc ends to the cell's edges.
    if dy > 0:
        draw.rectangle((cx + lo, oy, cx + lo + thin - 1, y1 - 1), fill=fg)
    else:
        draw.rectangle((cx + lo, y0, cx + lo + thin - 1, oy), fill=fg)
    if dx > 0:
        draw.rectangle((ox, cy + lo, x1 - 1, cy + lo + thin - 1), fill=fg)
    else:
        draw.rectangle((x0, cy + lo, ox, cy + lo + thin - 1), fill=fg)
    return True


def _block(draw, name: str, box, fg: Rgb, bg: Rgb) -> bool:
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0

    def fill(ax: float, ay: float, bx: float, by: float, colour: Rgb = fg) -> None:
        draw.rectangle((x0 + round(ax * w), y0 + round(ay * h),
                        x0 + round(bx * w) - 1, y0 + round(by * h) - 1), fill=colour)

    words = name.split()
    if name == "FULL BLOCK":
        fill(0, 0, 1, 1)
    elif len(words) >= 3 and words[-1] == "BLOCK" and words[0] in _SIDES:
        # "LOWER ONE EIGHTH", "LEFT THREE QUARTERS", "UPPER HALF" ...
        f = _fraction(words[1:-1])
        if f is None:
            return False
        ax, ay, bx, by = _SIDES[words[0]](f)
        fill(ax, ay, bx, by)
    elif name in ("LIGHT SHADE", "MEDIUM SHADE", "DARK SHADE"):
        t = {"LIGHT": 0.25, "MEDIUM": 0.5, "DARK": 0.75}[words[0]]
        fill(0, 0, 1, 1, _blend(bg, fg, t))
    elif words[0] == "QUADRANT":
        parts = " ".join(words[1:]).split(" AND ")
        quads = {"UPPER LEFT": (0, 0), "UPPER RIGHT": (0.5, 0),
                 "LOWER LEFT": (0, 0.5), "LOWER RIGHT": (0.5, 0.5)}
        if not all(p in quads for p in parts):
            return False
        for part in parts:
            ax, ay = quads[part]
            fill(ax, ay, ax + 0.5, ay + 0.5)
    else:
        return False
    return True
