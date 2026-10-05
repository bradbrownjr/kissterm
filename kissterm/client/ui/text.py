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

#: The terminal's font family; `web.py` and `desktop.py` register it with the page.
MONO = "kissterm-mono"

#: The 16 ANSI colours, as xterm draws them.
ANSI = {
    "black": "#000000", "red": "#cd0000", "green": "#00cd00", "yellow": "#cdcd00",
    "blue": "#0000ee", "magenta": "#cd00cd", "cyan": "#00cdcd", "white": "#e5e5e5",
    "bright_black": "#7f7f7f", "bright_red": "#ff0000", "bright_green": "#00ff00",
    "bright_yellow": "#ffff00", "bright_blue": "#5c5cff", "bright_magenta": "#ff00ff",
    "bright_cyan": "#00ffff", "bright_white": "#ffffff",
}
_ORDER = list(ANSI)
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
