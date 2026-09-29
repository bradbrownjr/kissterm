"""The screenshots, the script that makes them and the docs that show them
stay in step (operator, 2026-09-29: the documentation and screenshots are
part of every change, AGENTS.md section 7).

Every image the docs show exists, every image in `assets/` is shown
somewhere (a dropped one is deleted, not left to go stale), and every
image is one `scripts/generate_screenshot.py` makes, so none can be
edited by hand and silently fall behind the app.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = (ROOT / "README.md", ROOT / "docs" / "GUIDE.md", ROOT / "SETUP.md")
_IMAGE = re.compile(r"!\[[^\]]*\]\(((?:\.\./)?assets/[^)\s]+)\)")


def _shown() -> set[str]:
    names = set()
    for doc in DOCS:
        for ref in _IMAGE.findall(doc.read_text(encoding="utf-8")):
            names.add(Path(ref).name)
    return names


def _made() -> set[str]:
    script = (ROOT / "scripts" / "generate_screenshot.py").read_text(encoding="utf-8")
    return {f"{name}.png" for name in re.findall(r'await shot\("([^"]+)"\)', script)}


def test_every_image_the_docs_show_exists():
    missing = sorted(name for name in _shown() if not (ROOT / "assets" / name).is_file())
    assert not missing, f"docs show images that are not in assets/: {missing}"


def test_every_image_in_assets_is_shown():
    unused = sorted(p.name for p in (ROOT / "assets").glob("*.png") if p.name not in _shown())
    assert not unused, f"assets/ holds images no doc shows (delete them): {unused}"


def test_every_image_comes_from_the_screenshot_script():
    made = _made()
    assert made, "found no shot() calls in scripts/generate_screenshot.py"
    by_hand = sorted(name for name in _shown() if name not in made)
    assert not by_hand, f"not made by scripts/generate_screenshot.py: {by_hand}"
