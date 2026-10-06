"""Draw the remote control's icons: the splash while the web app loads,
the browser tab's favicon and the home-screen icons (operator, 2026-10-06:
the splash showed Flet's logo, which says nothing about kissterm).

The mark is a terminal prompt, `>_`, in 0xProto Bold on the dark
terminal panel the app itself uses (`client/ui/text.py`), with an
antenna radiating to both sides for the radio. Written into `kissterm/client/ui/assets/`, which the
Flet server searches before its own web files, so these replace Flet's
by name (`icons/loading-animation.png`, `icons/icon-*.png`,
`favicon.png`).

    .venv/bin/python scripts/generate_web_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "kissterm" / "client" / "ui" / "assets"
FONT = ASSETS / "fonts" / "0xProto-Bold-NL.ttf"

PANEL = (27, 29, 35, 255)      # text.BACKGROUNDS["dark"]
PROMPT = (74, 222, 128, 255)   # text.TEXT_COLOURS["green"] on dark
WAVES = (138, 180, 248, 255)   # text.OUTGOING["dark"]


def mark(size: int, *, bleed: bool = False) -> Image.Image:
    """The icon at `size` pixels. `bleed`: fill the square (a maskable
    icon, which the phone crops to its own shape) and keep the mark in
    the middle 70%."""
    scale = 4  # drawn large, then reduced, for smooth edges
    big = size * scale
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if bleed:
        draw.rectangle((0, 0, big, big), fill=PANEL)
        inner = big * 0.70
    else:
        draw.rounded_rectangle((0, 0, big - 1, big - 1), radius=big * 0.22, fill=PANEL)
        inner = big * 0.86
    origin = (big - inner) / 2

    font = ImageFont.truetype(str(FONT), int(inner * 0.50))
    text = ">_"
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    x = origin + inner * 0.12 - left
    y = origin + inner * 0.88 - bottom
    draw.text((x, y), text, font=font, fill=PROMPT)

    # An antenna radiating to both sides, ((|)): the radio.
    cx, cy = origin + inner * 0.74, origin + inner * 0.26
    width = max(scale, int(inner * 0.045))
    draw.line((cx, cy, cx, cy + inner * 0.30), fill=WAVES, width=width)
    draw.ellipse((cx - width * 1.1, cy - width * 1.1, cx + width * 1.1, cy + width * 1.1),
                 fill=WAVES)
    for r in (0.13, 0.22):
        radius = inner * r
        box = (cx - radius, cy - radius, cx + radius, cy + radius)
        draw.arc(box, start=140, end=220, fill=WAVES, width=width)
        draw.arc(box, start=-40, end=40, fill=WAVES, width=width)
    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    icons = ASSETS / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    mark(512).save(icons / "loading-animation.png")
    mark(192).save(icons / "icon-192.png")
    mark(512).save(icons / "icon-512.png")
    for size in (192, 512):
        mark(size, bleed=True).convert("RGB").save(icons / f"icon-maskable-{size}.png")
    mark(192, bleed=True).convert("RGB").save(icons / "apple-touch-icon-192.png")
    mark(32).save(ASSETS / "favicon.png")
    for path in sorted([*icons.glob("*.png"), ASSETS / "favicon.png"]):
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
