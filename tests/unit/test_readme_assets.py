"""The screenshots, the script that makes them and the docs that show them
stay in step (operator, 2026-09-29: the documentation and screenshots are
part of every change, AGENTS.md section 7).

Every image the docs show exists, every image in `assets/` is shown
somewhere (a dropped one is deleted, not left to go stale), and every
image is one a screenshot script makes (`scripts/generate_screenshot.py`
for the terminal, `scripts/generate_phone_screenshots.py` for the phone),
so none can be edited by hand and silently fall behind the app.
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


SCRIPTS = ("generate_screenshot.py", "generate_phone_screenshots.py")


def _made() -> set[str]:
    names = set()
    for script in SCRIPTS:
        text = (ROOT / "scripts" / script).read_text(encoding="utf-8")
        names.update(f"{name}.png" for name in re.findall(r'await shot\("([^"]+)"', text))
    return names


def test_every_image_the_docs_show_exists():
    missing = sorted(name for name in _shown() if not (ROOT / "assets" / name).is_file())
    assert not missing, f"docs show images that are not in assets/: {missing}"


def test_every_image_in_assets_is_shown():
    unused = sorted(p.name for p in (ROOT / "assets").glob("*.png") if p.name not in _shown())
    assert not unused, f"assets/ holds images no doc shows (delete them): {unused}"


def test_every_image_comes_from_the_screenshot_script():
    made = _made()
    assert made, f"found no shot() calls in {SCRIPTS}"
    assert "screenshot-phone.png" in made, "the phone script's shot() was not found"
    by_hand = sorted(name for name in _shown() if name not in made)
    assert not by_hand, f"not made by a screenshot script: {by_hand}"
