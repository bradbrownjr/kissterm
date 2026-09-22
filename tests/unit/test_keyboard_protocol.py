"""Textual's enhanced (Kitty) keyboard protocol stays OFF by default.

Why this is worth a test of its own. Under that protocol Enter stops being a
plain CR and becomes a bare `CSI 13 u` sequence carrying no associated text,
while ordinary letters still arrive with their text attached. When the
protocol state goes wrong -- a multiplexer detaching and reattaching the
window, a previous program leaving the stack pushed -- typing keeps working
and Enter silently disappears, which is exactly what was measured on a real
station: a key probe logged `b`, `y`, `e` and no event at all for Enter, so
the send line could only be sent with the mouse.

The switch is an environment variable that `textual.constants` reads at
IMPORT time, so `kissterm/__init__.py` has to set it before anything pulls in
Textual. That ordering is invisible at runtime and fails silently if someone
later moves it, adds an earlier Textual import, or "tidies" the assignment
into `__main__` -- the app would simply go back to losing Enter on the
affected terminal with nothing to show for it. These run in subprocesses
because import order is the whole point and cannot be re-tested once this
process has already imported Textual.
"""

from __future__ import annotations

import subprocess
import sys

_CHECK = (
    "import kissterm;"
    "from textual import constants;"
    "print(constants.DISABLE_KITTY_KEY)"
)


def _run(env_extra: dict[str, str] | None = None) -> str:
    import os

    env = dict(os.environ)
    env.pop("TEXTUAL_DISABLE_KITTY_KEY", None)
    env.update(env_extra or {})
    result = subprocess.run(
        [sys.executable, "-c", _CHECK],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result.stdout.strip()


def test_importing_kissterm_disables_the_enhanced_keyboard_protocol():
    """The default, and the thing that keeps Enter working."""
    assert _run() == "True", (
        "importing kissterm must leave Textual's DISABLE_KITTY_KEY set -- "
        "if this fails, check nothing imports Textual before "
        "kissterm/__init__.py sets the variable"
    )


def test_an_operator_can_turn_the_protocol_back_on():
    """`setdefault`, not assignment: a terminal that handles the protocol
    correctly is entitled to it, and the operator says so from the
    environment rather than by editing the package."""
    assert _run({"TEXTUAL_DISABLE_KITTY_KEY": "0"}) == "False"
