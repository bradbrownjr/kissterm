"""Session text for the Flet client: the station's styled chunks into
lines, and Rich style strings into Flet text styles.

**The station has already filtered the text** (`serve/wire.py`: the SGR
allowlist, C1 and bidi controls gone); here it is only laid out. A style
this does not recognise is dropped, never guessed: the text still shows,
plainly.

Pure functions, so the layout is tested without Flutter
(`tests/unit/test_client_ui.py`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The terminal's font families, one per weight, so bold is 0xProto's own
#: Bold and not Flutter thickening the Regular. `web.py` and `desktop.py`
#: register `FONTS` with the page.
MONO = "kissterm-mono"
MONO_BOLD = "kissterm-mono-bold"
FONTS = {MONO: "fonts/0xProto-Regular-NL.ttf", MONO_BOLD: "fonts/0xProto-Bold-NL.ttf"}

#: The 16 ANSI colours, as xterm draws them.
ANSI = {
    "black": "#000000", "red": "#cd0000", "green": "#00cd00", "yellow": "#cdcd00",
    "blue": "#0000ee", "magenta": "#cd00cd", "cyan": "#00cdcd", "white": "#e5e5e5",
    "bright_black": "#7f7f7f", "bright_red": "#ff0000", "bright_green": "#00ff00",
    "bright_yellow": "#ffff00", "bright_blue": "#5c5cff", "bright_magenta": "#ff00ff",
    "bright_cyan": "#00ffff", "bright_white": "#ffffff",
}
_ORDER = list(ANSI)

# ----------------------------------------------------------------------
# The terminal's look, chosen on each device (More > Terminal)
# ----------------------------------------------------------------------

#: Background name -> panel colour. Dark by default: a terminal, whatever
#: the rest of the app follows.
BACKGROUNDS = {"dark": "#1b1d23", "light": "#fafaf7"}
#: Text colour name -> (on dark, on light). Each pair keeps its contrast
#: on its own background, which is why the strongest is "contrast" and not
#: "white": on a light panel it is black.
TEXT_COLOURS = {
    "grey": ("#d4d4d4", "#24292f"),
    "contrast": ("#ffffff", "#000000"),
    "green": ("#4ade80", "#116329"),
    "amber": ("#ffb000", "#8a5300"),
    "cyan": ("#5eead4", "#0e6b72"),
}
#: The operator's own lines, in an accent that is neither text colour.
OUTGOING = {"dark": "#8ab4f8", "light": "#1a56db"}
DEFAULT_BACKGROUND, DEFAULT_TEXT = "dark", "grey"  # what THEME is without a palette
#: ANSI colours a node sends for a dark screen that vanish on a light one,
#: drawn darker there.
_ON_LIGHT = {"#e5e5e5": "#57606a", "#ffffff": "#24292f", "#cdcd00": "#7d6b00",
             "#ffff00": "#7d6b00", "#00cd00": "#1a7f37", "#00ff00": "#1a7f37", "#00cdcd": "#0e6b72",
             "#00ffff": "#0e6b72"}


#: A device that has chosen nothing follows the station's theme
#: (`Look.palette`); "dark" and "light" and the named text colours are
#: this device's own override of it.
THEME = "theme"


@dataclass(frozen=True, slots=True)
class Look:
    """How session text is drawn: `background` and `text` are `THEME` or
    names from `BACKGROUNDS` and `TEXT_COLOURS`; an unknown name is the
    default. `palette` is the station's theme as sorted `(name, value)`
    pairs (`themes.palette`), which `THEME` follows; without one (not yet
    asked, an old station) `THEME` is the dark panel with grey text."""

    background: str = THEME
    text: str = THEME
    palette: tuple = ()

    def __post_init__(self) -> None:
        if self.background != THEME and self.background not in BACKGROUNDS:
            object.__setattr__(self, "background", DEFAULT_BACKGROUND)
        if self.text != THEME and self.text not in TEXT_COLOURS:
            object.__setattr__(self, "text", DEFAULT_TEXT)

    @staticmethod
    def pack(palette: dict | None) -> tuple:
        return tuple(sorted((k, v) for k, v in (palette or {}).items()
                            if isinstance(v, (str, bool)))) if palette else ()

    def _theme(self, name: str, default=None):
        return dict(self.palette).get(name, default)

    @property
    def following(self) -> bool:
        """Background taken from the station's theme."""
        return self.background == THEME and bool(self.palette)

    @property
    def light(self) -> bool:
        if self.background == THEME:
            return bool(self.palette) and not self._theme("dark", True)
        return self.background == "light"

    @property
    def _key(self) -> str:
        return "light" if self.light else "dark"

    @property
    def bgcolor(self) -> str:
        if self.following:
            return self._theme("background") or BACKGROUNDS[self._key]
        return BACKGROUNDS[self._key]

    @property
    def color(self) -> str:
        if self.text == THEME and self.following:
            return self._theme("foreground") or TEXT_COLOURS[DEFAULT_TEXT][self.light]
        name = DEFAULT_TEXT if self.text == THEME else self.text
        return TEXT_COLOURS[name][1 if self.light else 0]

    @property
    def outgoing(self) -> str:
        if self.following:
            return self._theme("primary") or OUTGOING[self._key]
        return OUTGOING[self._key]

    def ansi(self, color: str | None) -> str | None:
        """A colour the station sent, readable on this background."""
        if color is None or not self.light:
            return color
        return _ON_LIGHT.get(color.lower(), color)

_HEX = re.compile(r"#[0-9a-fA-F]{6}")
_INDEX = re.compile(r"color\((\d{1,3})\)")
_RGB = re.compile(r"rgb\((\d{1,3}),(\d{1,3}),(\d{1,3})\)")


def _xterm(n: int) -> str | None:
    if n < 16:
        return ANSI[_ORDER[n]]
    if n < 232:
        n -= 16
        levels = (0, 95, 135, 175, 215, 255)
        return "#{:02x}{:02x}{:02x}".format(levels[n // 36], levels[(n // 6) % 6], levels[n % 6])
    if n < 256:
        grey = 8 + (n - 232) * 10
        return f"#{grey:02x}{grey:02x}{grey:02x}"
    return None


def colour(word: str) -> str | None:
    """One Rich colour word as `#rrggbb`, or None."""
    word = word.strip().lower()
    if word in ANSI:
        return ANSI[word]
    if _HEX.fullmatch(word):
        return word
    match = _INDEX.fullmatch(word)
    if match:
        return _xterm(int(match.group(1)))
    match = _RGB.fullmatch(word.replace(" ", ""))
    if match and all(int(v) < 256 for v in match.groups()):
        return "#{:02x}{:02x}{:02x}".format(*(int(v) for v in match.groups()))
    return None


def style_props(style: str) -> dict:
    """A Rich style string ("bold red on blue") as text properties:
    `color`, `bgcolor`, `bold`, `italic`, `underline`, `dim`, `reverse`."""
    props: dict = {}
    words = (" " + style).replace(" on ", " on:").split()
    for word in words:
        if word.startswith("on:"):
            bg = colour(word[3:])
            if bg:
                props["bgcolor"] = bg
        elif word in ("bold", "italic", "underline", "dim", "reverse"):
            props[word] = True
        elif word.startswith("not"):
            continue
        else:
            fg = colour(word)
            if fg:
                props["color"] = fg
    if props.pop("reverse", False):
        props["color"], props["bgcolor"] = props.get("bgcolor", "#000000"), props.get("color", "#e5e5e5")
    return props


def split_lines(text: str, spans: list) -> list[tuple[str, list]]:
    """`text` with `spans` (`[start, end, style]`) as lines, each with its
    own spans (offsets within the line). The last element is always the
    unterminated tail, "" when `text` ends with a newline. CR is dropped
    (a node's line endings)."""
    lines: list[tuple[str, list]] = []
    start = 0
    while True:
        newline = text.find("\n", start)
        end = len(text) if newline < 0 else newline
        line_spans = [[max(a, start) - start, min(b, end) - start, style]
                      for a, b, style in spans if max(a, start) < min(b, end)]
        line = text[start:end]
        lines.append((line.replace("\r", ""), _shift_cr(line, line_spans)))
        if newline < 0:
            return lines
        start = newline + 1


def _shift_cr(line: str, spans: list) -> list:
    """Spans re-measured once CRs are taken out of `line`."""
    if "\r" not in line:
        return spans
    removed = [i for i, ch in enumerate(line) if ch == "\r"]

    def moved(pos: int) -> int:
        return pos - sum(1 for r in removed if r < pos)

    return [[moved(a), moved(b), style] for a, b, style in spans if moved(a) < moved(b)]


def runs(line: str, spans: list) -> list[tuple[str, dict]]:
    """`line` cut where its style changes: `(text, props)` pieces, later
    spans winning over earlier ones where they overlap."""
    if not line:
        return []
    props_at: list[dict] = [{} for _ in line]
    for start, end, style in spans:
        props = style_props(style)
        for i in range(max(0, start), min(end, len(line))):
            props_at[i] = {**props_at[i], **props}
    pieces: list[tuple[str, dict]] = []
    for char, props in zip(line, props_at):
        if pieces and pieces[-1][1] == props:
            pieces[-1] = (pieces[-1][0] + char, props)
        else:
            pieces.append((char, props))
    return pieces
