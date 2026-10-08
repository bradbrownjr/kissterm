"""Session > Broadcast in the terminal: opening, typing and choosing a
destination transmit nothing; only the Send button does."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402
from textual.widgets import Button, Input, Static  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.dialogs import BroadcastScreen  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402
from tests.pilot._wait import wait_for  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")


@pytest.mark.asyncio
async def test_the_screen_transmits_only_when_send_is_pressed():
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    station = AX25Station(MYCALL, ta, LinkParams())
    app = KissTermApp(Config(mycall=str(MYCALL), log_sessions=False), station)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_broadcast()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, BroadcastScreen)
        screen.query_one("#broadcast-text", Input).value = "Net check, 7 PM"
        await pilot.pause()
        assert "channel" in str(screen.query_one("#broadcast-cost", Static).render())
        await pilot.press("enter")  # Enter in the text only moves to the button
        await pilot.pause()
        assert ta.sent == [] and not app.gate.enabled
        screen.query_one("#broadcast-send", Button).press()
        await wait_for(lambda: len(ta.sent) == 1, "the broadcast frame", timeout=3)
        assert ta.sent[0].info == b"Net check, 7 PM" and app.gate.enabled
        await wait_for(lambda: "Net check" in str(screen.query_one("#broadcast-heard", Static).render()), "it listed as sent")
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, BroadcastScreen)
