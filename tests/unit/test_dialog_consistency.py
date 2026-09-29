"""A dialog's buttons match its fields (DESIGN.md section 3).

Compact fields with bordered buttons, or the reverse, looked like two
applications when one dialog opened another (2026-09-29). Read from source:
no widget tree needed, and it catches a new dialog at the line that adds it.
"""

from __future__ import annotations

import re
from pathlib import Path

import kissterm.ui.dialogs as dialogs

SOURCE = Path(dialogs.__file__).read_text()


def _classes() -> dict[str, str]:
    out = {}
    for part in re.split(r"\n(?=class )", SOURCE):
        m = re.match(r"class (\w+)", part)
        if m:
            out[m.group(1)] = part
    return out


def test_every_dialog_uses_one_button_style():
    mixed = []
    for name, body in _classes().items():
        buttons = re.findall(r"yield Button\([^\n]*\)\n", body)
        if not buttons:
            continue
        compact = [("compact=True" in b) for b in buttons]
        if any(compact) and not all(compact):
            mixed.append(f"{name}: some buttons compact, some bordered")
        fields = body.count("compact=True") - sum(compact)
        if fields and not all(compact):
            mixed.append(f"{name}: compact fields with bordered buttons")
        if not fields and any(compact):
            mixed.append(f"{name}: bordered fields with compact buttons")
    assert not mixed, "\n".join(mixed)
