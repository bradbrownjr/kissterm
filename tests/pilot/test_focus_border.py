"""The accent border follows focus, and nothing else carries it.

Reported 2026-09-22: "the bright box border remains on the text entry field,
so I type and wonder at first why my keystrokes aren't going into the entry
field." The send box was styled `$accent` permanently, so the colour marked
the widget rather than the focus. The rule (kissterm/ui/styles.py, DESIGN.md
section 2): whatever has focus is drawn in `$accent`, everything else in
`$primary`.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402
from textual.color import Color  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")


async def _app(**config):
    ta, _ = loopback_pair()
    await ta.open()
    station = AX25Station(MYCALL, ta, LinkParams())
    return KissTermApp(Config(mycall=str(MYCALL), **config), station), station


def _colour(app, widget_id: str) -> Color:
    return app.query_one(widget_id).styles.border_top[1]


def _theme(app, name: str) -> Color:
    # The resolved CSS variable, not the theme's hex: they can differ by
    # rounding, and the border uses the variable.
    return Color.parse(app.get_css_variables()[name])


async def _focus(app, pilot, widget_id: str) -> None:
    app.query_one(widget_id).focus()
    await pilot.pause()


@pytest.mark.asyncio
@pytest.mark.parametrize("ascii_safe", [False, True])
async def test_the_accent_border_moves_with_focus(ascii_safe):
    app, station = await _app(ascii_safe=ascii_safe)
    async with app.run_test(size=(140, 45)) as pilot:
        accent, primary = _theme(app, "accent"), _theme(app, "primary")

        app.action_show_tab("terminal")
        await pilot.pause()
        await _focus(app, pilot, "#session-log")
        assert _colour(app, "#session-log") == accent
        assert _colour(app, "#session-input") == primary, (
            "the send box stayed accent while the scrollback had focus"
        )
        await _focus(app, pilot, "#session-input")
        assert _colour(app, "#session-input") == accent
        assert _colour(app, "#session-log") == primary

        app.action_show_tab("aprs")
        await pilot.pause()
        await _focus(app, pilot, "#aprs-conversation-log")
        assert _colour(app, "#aprs-conversation-log") == accent
        assert _colour(app, "#aprs-compose-input") == primary
        assert _colour(app, "#aprs-to-input") == primary

        app.action_show_tab("heard")
        await pilot.pause()
        await _focus(app, pilot, "#heard-table")
        assert _colour(app, "#heard-table") == accent
    station.close()


@pytest.mark.asyncio
async def test_the_palette_and_menu_keep_their_own_chrome():
    """App CSS outranks every widget's DEFAULT_CSS, so the focus rule must not
    draw boxes inside the Ctrl+P palette or the F10 menu's item list."""
    app, station = await _app()
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.press("f10")
        await pilot.pause()
        assert app.screen.query_one("#menu-items").styles.border_top[0] in ("", "none")
        await pilot.press("escape")
        await pilot.pause()

        await pilot.press("ctrl+p")
        await pilot.pause()
        from textual.command import CommandInput

        assert app.screen.query_one(CommandInput).styles.border_top[0] == "blank"
    station.close()
