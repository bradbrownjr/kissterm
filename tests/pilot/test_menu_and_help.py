"""F10 (the menu) and F1 (help), and the rule that a key only works where it
means something.

`isolate()` runs FIRST, before any other kissterm import -- see
`tests/pilot/test_app_mounts.py`'s docstring for why.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.menu import HelpScreen, MenuScreen  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")


async def _app(**kw):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = Config(mycall=str(MYCALL))
    config.log_sessions = False
    for key, value in kw.items():
        setattr(config, key, value)
    station = AX25Station(MYCALL, ta, LinkParams())
    return KissTermApp(config, station), station, ta


async def _settle(pilot, seconds: float = 0.1):
    await pilot.pause()
    await asyncio.sleep(seconds)
    await pilot.pause()


@pytest.mark.asyncio
async def test_f10_opens_the_menu_at_the_heading_for_the_current_tab():
    """F10 then one letter should reach the work in front of the operator,
    so the menu opens on Session from Terminal and on APRS from APRS."""
    app, station, _ta = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("f10")
        await _settle(pilot)
        assert isinstance(app.screen, MenuScreen)
        assert app.screen.groups[app.screen.current][0] == "Session"
        await pilot.press("escape")
        await _settle(pilot)

        app.action_show_tab("aprs")
        await _settle(pilot)
        await pilot.press("f10")
        await _settle(pilot)
        assert app.screen.groups[app.screen.current][0] == "APRS"
        await pilot.press("escape")
    station.close()


@pytest.mark.asyncio
async def test_a_menu_command_switches_to_its_own_tab_before_running():
    """Contacts belongs to APRS. Chosen from the Terminal tab it has to take
    the operator there, not act invisibly on a pane they cannot see."""
    app, station, _ta = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)
        assert app.active_tab() == "terminal"
        await pilot.press("f10")
        await _settle(pilot)
        await pilot.press("right")  # Session -> APRS
        await _settle(pilot)
        await pilot.press("c")  # Contacts
        await _settle(pilot, 0.2)
        assert app.active_tab() == "aprs"
    station.close()


@pytest.mark.asyncio
async def test_a_command_that_cannot_run_is_listed_with_the_reason():
    """The menu is where an operator learns what exists, so Disconnect stays
    visible with nothing connected -- dimmed, saying why, and inert."""
    app, station, _ta = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("f10")
        await _settle(pilot)
        entries = dict(
            (command.label, reason)
            for command, reason in app.screen.groups[app.screen.current][1]
        )
        assert entries["Disconnect"] == "not connected"
        assert entries["Connect"] == ""

        await pilot.press("d")
        await _settle(pilot)
        assert isinstance(app.screen, MenuScreen), (
            "a disabled entry must not run or close the menu"
        )
        await pilot.press("escape")
    station.close()


@pytest.mark.asyncio
async def test_opening_and_closing_the_menu_transmits_nothing():
    """It lists Send beacon and Send position; browsing it is not sending."""
    app, station, ta = await _app(tx_armed_at_start=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)
        for group_key in ("", "right", "right", "right"):
            await pilot.press("f10")
            await _settle(pilot)
            if group_key:
                await pilot.press(group_key)
                await _settle(pilot)
            await pilot.press("escape")
            await _settle(pilot)
        assert ta.sent == []
    station.close()


@pytest.mark.asyncio
async def test_f1_shows_help_for_the_tab_you_are_on():
    app, station, _ta = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_show_tab("monitor")
        await _settle(pilot)
        await pilot.press("f1")
        await _settle(pilot)
        assert isinstance(app.screen, HelpScreen)
        from rich.console import Console

        console = Console(width=100, record=True)
        console.print(app.screen.body)
        body = console.export_text()
        assert "Monitor" in body
        assert "Ctrl+T" in body
        # Find searches the terminal scrollback: not a Monitor key. (Connect
        # is listed, because Ctrl+N works from any tab.)
        assert "Find: " not in body
        await pilot.press("escape")
        await _settle(pilot)
        assert not isinstance(app.screen, HelpScreen)
    station.close()


@pytest.mark.asyncio
async def test_a_key_for_another_tab_does_nothing_instead_of_explaining():
    """Rule 5: an action that does not apply here is absent from the Footer
    and inert, not shown and then answered with a toast."""
    app, station, _ta = await _app()
    toasts: list[str] = []
    app.notify = lambda message, *a, **kw: toasts.append(str(message))
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_show_tab("heard")
        await _settle(pilot)
        await pilot.press("ctrl+f")  # Find: Terminal only
        await _settle(pilot)
        assert app.active_tab() == "heard"
        assert toasts == []
    station.close()
