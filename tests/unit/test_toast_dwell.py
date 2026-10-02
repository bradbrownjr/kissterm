"""A toast stays up long enough to read (DESIGN.md section 6; operator,
2026-10-02: pairs of 4-second toasts "went by too fast to read")."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import ast  # noqa: E402
from pathlib import Path  # noqa: E402

from kissterm.ui.app import KissTermApp  # noqa: E402

MIN_SECONDS = 10
UI = Path(__file__).resolve().parents[2] / "kissterm" / "ui"


def test_the_default_dwell_is_long_enough():
    assert KissTermApp.NOTIFICATION_TIMEOUT >= MIN_SECONDS


def test_no_toast_passes_a_shorter_timeout():
    short = []
    for path in sorted(UI.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "notify"):
                continue
            for kw in node.keywords:
                if kw.arg != "timeout":
                    continue
                # A conditional (urgent ? 15 : 10) is checked branch by branch.
                values = ([kw.value.body, kw.value.orelse] if isinstance(kw.value, ast.IfExp)
                          else [kw.value])
                if not all(isinstance(v, ast.Constant) and v.value >= MIN_SECONDS for v in values):
                    short.append(f"{path.name}:{node.lineno}")
    assert not short, f"toasts shorter than {MIN_SECONDS}s: {short}"
