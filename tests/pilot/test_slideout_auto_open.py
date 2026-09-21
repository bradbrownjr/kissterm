"""Both slide-outs opening themselves, on a real mounted app.

`tests/unit/test_slideouts.py` proves the arithmetic; this file proves it is
actually wired to the two panes, that an auto-opened panel does not steal the
cursor, and that a resize can never overrule the operator.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")

#: Wide enough for both columns; one column short of it.
WIDE = (100, 30)
NARROW = (79, 30)


async def _app(config=None):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    station = AX25Station(MYCALL, ta, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    return KissTermApp(config or Config(mycall=str(MYCALL)), station), station


async def _settle(app, pilot, tab):
    app.action_show_tab(tab)
    await pilot.pause()
    await asyncio.sleep(0.1)
    await pilot.pause()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tab,column",
    [("terminal", "#terminal-addressbook-column"), ("aprs", "#aprs-contacts-column")],
)
async def test_a_wide_terminal_opens_the_slideout_and_a_narrow_one_does_not(tab, column):
    for size, expected in ((NARROW, False), (WIDE, True)):
        app, station = await _app()
        async with app.run_test(size=size) as pilot:
            await _settle(app, pilot, tab)
            assert app.query_one(column).display is expected, (size, tab)
        station.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tab,column,typing",
    [
        ("terminal", "#terminal-addressbook-column", "#session-input"),
        ("aprs", "#aprs-contacts-column", "#aprs-compose-input"),
    ],
)
async def test_an_auto_opened_slideout_does_not_steal_the_cursor(tab, column, typing):
    """DESIGN.md says opening a slide-out moves focus into it -- and that is
    right for a panel the operator summoned to pick something from. A panel
    that was already there when they arrived is furniture, and taking the
    cursor out of the box they were typing in because a window got wider is a
    different thing entirely.
    """
    app, station = await _app()
    async with app.run_test(size=WIDE) as pilot:
        await _settle(app, pilot, tab)
        assert app.query_one(column).display, "setup: it should have opened itself"
        assert app.focused is not None
        assert app.focused.id == typing.lstrip("#"), (
            f"the auto-opened panel took focus; it is on {app.focused.id}"
        )
    station.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tab,column", [("terminal", "#terminal-addressbook-column"), ("aprs", "#aprs-contacts-column")]
)
async def test_closing_by_hand_survives_a_resize(tab, column):
    """Once the operator has said what they want, the width rule stops having
    an opinion. Without this, dragging a window wider would re-open a panel
    somebody had just closed on purpose."""
    app, station = await _app()
    async with app.run_test(size=WIDE) as pilot:
        await _settle(app, pilot, tab)
        assert app.query_one(column).display

        await pilot.press("ctrl+g")
        await pilot.pause()
        assert not app.query_one(column).display

        await pilot.resize_terminal(160, 40)
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.pause()
        assert not app.query_one(column).display, "a resize overruled the operator"
    station.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tab,column", [("terminal", "#terminal-addressbook-column"), ("aprs", "#aprs-contacts-column")]
)
async def test_the_setting_turns_the_whole_thing_off(tab, column):
    config = Config(mycall=str(MYCALL))
    config.slideouts_auto_open = False
    app, station = await _app(config)
    async with app.run_test(size=(200, 40)) as pilot:
        await _settle(app, pilot, tab)
        assert not app.query_one(column).display, "the setting was ignored"

        # Still openable by hand -- the setting governs what happens unasked,
        # never what the operator can reach.
        await pilot.press("ctrl+g")
        await pilot.pause()
        assert app.query_one(column).display
    station.close()


@pytest.mark.asyncio
async def test_the_conversation_column_keeps_its_forty_columns():
    """The one number the operator named. Checked on the rendered widths, not
    on the arithmetic -- that is what makes this a wiring test.

    `outer_size`, not `size`: Textual's `Widget.size` is the *content* area,
    already inside the widget's own border and padding, so reading it here
    would measure something several cells narrower than the column the split
    actually allocated and fail a rule that is being kept.
    """
    for width in (80, 96, 110, 160):
        app, station = await _app()
        async with app.run_test(size=(width, 30)) as pilot:
            await _settle(app, pilot, "aprs")
            main = app.query_one("#aprs-conversation-column")
            panel = app.query_one("#aprs-contacts-column")
            assert panel.display, width
            assert main.outer_size.width >= 40, (
                width,
                main.outer_size.width,
                panel.outer_size.width,
            )
        station.close()


@pytest.mark.asyncio
async def test_aprs_compose_row_stays_usable_with_the_contacts_panel_open():
    """APRS controls live in the context footer, leaving only To/Message/Send."""
    for width in (80, 110, 200):
        app, station = await _app()
        async with app.run_test(size=(width, 30)) as pilot:
            await _settle(app, pilot, "aprs")
            assert app.query_one("#aprs-contacts-column").display, width
            assert app.query_one("#aprs-compose-input").outer_size.width >= 16, width
        station.close()


@pytest.mark.asyncio
async def test_aprs_compose_row_grows_when_the_contacts_panel_closes():
    app, station = await _app()
    async with app.run_test(size=(110, 30)) as pilot:
        await _settle(app, pilot, "aprs")
        before = app.query_one("#aprs-compose-input").outer_size.width

        await pilot.press("ctrl+g")  # close the contact list
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.pause()
        assert app.query_one("#aprs-compose-input").outer_size.width > before
    station.close()
