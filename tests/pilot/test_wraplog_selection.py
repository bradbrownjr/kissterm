"""Copying from a WrapLog (the Terminal's scrollback) never raises.

Operator, 2026-10-02: a selection that started below the last line
(`Selection(start=Offset(x=163, y=30), end=None)` over 30 lines) crashed
the app: Textual's `Selection.extract` indexes the start line unchecked.
"""

from kissterm import _isolate

_isolate.isolate()

import pytest  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.geometry import Offset  # noqa: E402
from textual.selection import Selection  # noqa: E402

from kissterm.ui.wraplog import WrapLog  # noqa: E402


class _Host(App):
    def compose(self) -> ComposeResult:
        yield WrapLog()


@pytest.mark.asyncio
async def test_a_selection_below_the_last_line_copies_nothing():
    app = _Host()
    async with app.run_test(size=(80, 20)) as pilot:
        log = app.query_one(WrapLog)
        for line in ("KC1JMH", "", "Welcome to the node"):
            log.write(line)
        await pilot.pause()
        rows = len(log.lines)
        assert log.get_selection(Selection(Offset(163, rows), None)) is None
        assert log.get_selection(Selection(Offset(0, rows + 5), Offset(3, rows + 6))) is None


@pytest.mark.asyncio
async def test_a_selection_inside_the_text_still_copies_it():
    app = _Host()
    async with app.run_test(size=(80, 20)) as pilot:
        log = app.query_one(WrapLog)
        log.write("Welcome to the node")
        await pilot.pause()
        assert log.get_selection(Selection(Offset(0, 0), Offset(7, 0))) == ("Welcome", "\n")
