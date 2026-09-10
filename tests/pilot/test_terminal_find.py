"""`Ctrl+F`: find in the Terminal pane's scrollback.

Roadmap P2's "scrollback search" -- in-pane find, forward/backward, over the
terminal buffer Textual already retains. No connected link needed for any of
this: it operates purely on what is already in `#session-log`.
"""

from __future__ import annotations

import pytest
from textual.widgets import Input, RichLog, Static

from kissterm._isolate import isolate

isolate()

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.terminal_pane import TerminalPane  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")


async def _app():
    ta, _tb = loopback_pair()
    await ta.open()
    a = AX25Station(MYCALL, ta, LinkParams())
    config = Config(mycall=str(MYCALL))
    app = KissTermApp(config, a)
    return app, a


def _fill_log(pane: TerminalPane, marker: str, at: tuple[int, ...], count: int = 30) -> int:
    """Write `count` one-line entries, tagging the ones at `at` with `marker`.

    Returns the number of lines already in `#session-log` before this call
    (the startup banner, mainly) -- callers add this to `i` rather than
    assume line 0 is the first line THIS function wrote. Deliberately no
    trailing newline in each call: `RichLog` renders an embedded `\\n` as a
    second, blank Strip line, which would silently double the line count
    and throw off every index below -- one call, one line, is what this
    helper promises.
    """
    log = pane.query_one("#session-log", RichLog)
    baseline = len(log.lines)
    for i in range(count):
        text = f"line {i}"
        if i in at:
            text += f" {marker}"
        pane.log(pane.active_session_key, text)
    return baseline


@pytest.mark.asyncio
async def test_ctrl_f_opens_the_find_bar_on_the_terminal_tab():
    app, a = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_show_tab("monitor")
        await pilot.pause()

        await pilot.press("ctrl+f")
        await pilot.pause()

        assert app.query_one("#main-tabs").active == "terminal"
        assert app.query_one("#find-row").display is True
        assert app.query_one("#find-input", Input).has_focus
    a.close()


@pytest.mark.asyncio
async def test_typing_counts_matches_without_jumping():
    app, a = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        _fill_log(pane, "orange", at=(5, 15, 25))
        await pilot.pause()
        log = app.query_one("#session-log", RichLog)
        before = log.scroll_y

        await pilot.press("ctrl+f")
        await pilot.pause()
        app.query_one("#find-input", Input).value = "orange"
        await pilot.pause()

        assert "3 matches" in str(app.query_one("#find-status", Static).content)
        # Counting is not navigating -- nothing should have moved yet.
        assert log.scroll_y == before
    a.close()


@pytest.mark.asyncio
async def test_enter_steps_forward_through_matches_and_wraps():
    app, a = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        # Well more lines than fit in one screen, and each match well short
        # of the end -- otherwise `scroll_to` clamps the target to whatever
        # top-of-viewport position still has enough content below it to
        # fill the screen, and a match near the tail lands somewhere short
        # of the exact line asked for. Not a bug in the feature, just not
        # what a fixed-index assertion here wants to reason about.
        baseline = _fill_log(pane, "orange", at=(10, 50, 90), count=150)
        first, second, third = baseline + 10, baseline + 50, baseline + 90
        await pilot.pause()

        await pilot.press("ctrl+f")
        await pilot.pause()
        find_input = app.query_one("#find-input", Input)
        find_input.value = "orange"
        await pilot.pause()

        log = app.query_one("#session-log", RichLog)

        await pilot.press("enter")
        await pilot.pause()
        assert log.scroll_y == first
        assert "1/3" in str(app.query_one("#find-status", Static).content)

        await pilot.press("enter")
        await pilot.pause()
        assert log.scroll_y == second
        assert "2/3" in str(app.query_one("#find-status", Static).content)

        await pilot.press("enter")
        await pilot.pause()
        assert log.scroll_y == third
        assert "3/3" in str(app.query_one("#find-status", Static).content)

        # Wraps back to the first match rather than stopping.
        await pilot.press("enter")
        await pilot.pause()
        assert log.scroll_y == first
        assert "1/3" in str(app.query_one("#find-status", Static).content)
    a.close()


@pytest.mark.asyncio
async def test_shift_enter_steps_backward():
    app, a = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        baseline = _fill_log(pane, "orange", at=(10, 50, 90), count=150)
        first, third = baseline + 10, baseline + 90
        await pilot.pause()

        await pilot.press("ctrl+f")
        await pilot.pause()
        app.query_one("#find-input", Input).value = "orange"
        await pilot.pause()

        log = app.query_one("#session-log", RichLog)

        await pilot.press("enter")  # -> first match
        await pilot.pause()
        assert log.scroll_y == first

        await pilot.press("shift+enter")  # -> wraps back to the last match
        await pilot.pause()
        assert log.scroll_y == third
        assert "3/3" in str(app.query_one("#find-status", Static).content)
    a.close()


@pytest.mark.asyncio
async def test_no_matches_says_so_and_does_not_move():
    app, a = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        _fill_log(pane, "orange", at=(5,))
        await pilot.pause()
        log = app.query_one("#session-log", RichLog)
        before = log.scroll_y

        await pilot.press("ctrl+f")
        await pilot.pause()
        app.query_one("#find-input", Input).value = "purple"
        await pilot.pause()

        assert "No matches" in str(app.query_one("#find-status", Static).content)

        await pilot.press("enter")
        await pilot.pause()
        assert log.scroll_y == before
    a.close()


@pytest.mark.asyncio
async def test_escape_closes_the_bar_and_returns_focus_to_the_send_line():
    app, a = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+f")
        await pilot.pause()
        assert app.query_one("#find-row").display is True

        await pilot.press("escape")
        await pilot.pause()

        assert app.query_one("#find-row").display is False
        assert app.query_one("#session-input", Input).has_focus
    a.close()


@pytest.mark.asyncio
async def test_close_button_also_closes_it():
    from textual.widgets import Button

    app, a = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+f")
        await pilot.pause()

        app.query_one("#find-close", Button).press()
        await pilot.pause()

        assert app.query_one("#find-row").display is False
    a.close()


@pytest.mark.asyncio
async def test_escape_while_the_bar_is_already_closed_does_nothing_odd():
    """Escape is bound at the pane level (see `TerminalPane`'s class
    docstring), which means it fires even when the bar was never opened --
    it must be a harmless no-op then, not an error or a stray notification."""
    app, a = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.query_one("#find-row").display is False
    a.close()
