"""A crash report never prints a secret held in a local variable.

Textual's own report shows every frame's locals; a crash inside Get mail
printed the Winlink password among them (operator, 2026-10-03).
`KissTermApp._fatal_error` replaces it with a locals-free one.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.config import Config  # noqa: E402

SECRET = "hunter2-sample-secret"


class _Crashing(KissTermApp):
    shown: list = []

    def _print_error_renderables(self) -> None:
        self.shown = list(self._exit_renderables)
        self._exit_renderables.clear()

    def action_crash(self) -> None:
        password = SECRET  # noqa: F841 -- the local the report must not show
        raise RuntimeError("deliberate")


@pytest.mark.asyncio
async def test_the_crash_report_has_no_locals():
    app = _Crashing(Config(mycall="N1ABC-1"), station=None)
    with pytest.raises(RuntimeError):
        async with app.run_test(size=(110, 32)) as pilot:
            await pilot.pause()
            app.call_later(app.action_crash)
            await pilot.pause()
            await pilot.pause()
    assert app.shown, "the crash report was not produced"
    text = "".join(
        segment.text for renderable in app.shown for segment in renderable.segments
    )
    assert "deliberate" in text
    assert SECRET not in text
