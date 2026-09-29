"""Every "Settings > X" the UI or docs name is a real Settings section.

The paths were typed by hand and went stale: "Settings (F9) >
Connections" (operator, 2026-09-27: "I don't see an F9 Settings >
Connections"), and "Settings, then Transports" in the first-run greeting,
the setup guide and SETUP.md, long after that section became Radio.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import re  # noqa: E402
from pathlib import Path  # noqa: E402

from kissterm.ui.settings_pane import section_titles  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
# "Settings > Mail", "Settings (F9) > Radio", "Settings (`F9`) > Radio",
# "Settings, then Radio", "Settings -> Radio".
_PATH = re.compile(r"Settings(?: \(`?F9`?\))?,? (?:>|->|then) ([A-Z][A-Za-z]*)")


def _files():
    yield from (ROOT / "kissterm").rglob("*.py")
    yield from (ROOT / name for name in ("README.md", "SETUP.md", "DESIGN.md", "docs/GUIDE.md"))
    yield ROOT / "docs" / "ON-AIR-TESTS.md"


def test_every_settings_path_names_a_real_section():
    titles = set(section_titles())
    wrong = []
    for path in _files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in _PATH.finditer(line):
                if match.group(1) not in titles:
                    wrong.append(f"{path.relative_to(ROOT)}:{number}: {match.group(0)!r}")
    assert not wrong, "Settings has no such section:\n" + "\n".join(wrong)
