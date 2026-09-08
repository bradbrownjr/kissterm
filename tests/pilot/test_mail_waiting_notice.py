"""A passive "MAIL FOR" beacon has to reach the operator with no connection.

Reported request (docs/ROADMAP.md P9): if the monitor hears a node beacon
"MAIL FOR {my callsign}", raise a notification even while not connected to
that node at all -- the modem being on frequency is enough. This exercises
the real path: a UI frame off the shared frame fan-out
(`AX25Station`/`FrameTransport.subscribe`), never a connection.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.ax25.address import AX25Path  # noqa: E402
from kissterm.ax25.frame import AX25Frame, UType  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.terminal_pane import TerminalPane  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
PEER = AX25Address.parse("WS1EC-15")


async def _app():
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = Config(mycall=str(MYCALL))
    config.log_sessions = False
    config.tx_armed_at_start = True
    params = LinkParams(t1=0.3, t2=0.05, t3=5.0, retries=2)
    mine = AX25Station(MYCALL, ta, params)
    theirs = AX25Station(PEER, tb, params)
    return KissTermApp(config, mine), mine, theirs


async def _beacon(theirs: AX25Station, text: str) -> None:
    path = AX25Path(AX25Address.parse("ID"), PEER)
    frame = AX25Frame.u_frame(path, UType.UI, command=False, info=text.encode("latin-1"))
    await theirs.transport.send_frame(frame, 0)


@pytest.mark.asyncio
async def test_a_mail_for_beacon_notifies_with_no_connection():
    app, mine, theirs = await _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await _beacon(theirs, "MAIL FOR: N1ABC K1XYZ")
        for _ in range(20):
            if app._mail_notified:
                break
            await pilot.pause()
        assert ("WS1EC-15", "N1ABC") in app._mail_notified
        text = "\n".join(
            str(line)
            for line in app.query_one(TerminalPane).query_one("#session-log").lines
        )
        assert "WS1EC-15 is holding mail for N1ABC" in text, text
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_matches_our_ssid_alias_even_when_the_beacon_carries_none():
    """The mailbox addresses the base call; our own callsign here carries an
    SSID the beacon never mentions -- see `mail_waiting_for`'s docstring."""
    app, mine, theirs = await _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await _beacon(theirs, "MAIL FOR: N1ABC")
        for _ in range(20):
            if app._mail_notified:
                break
            await pilot.pause()
        assert ("WS1EC-15", "N1ABC") in app._mail_notified
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_a_repeated_beacon_does_not_notify_twice():
    app, mine, theirs = await _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await _beacon(theirs, "MAIL FOR: N1ABC")
        for _ in range(20):
            if app._mail_notified:
                break
            await pilot.pause()
        assert len(app._mail_notified) == 1

        await _beacon(theirs, "MAIL FOR: N1ABC")
        await pilot.pause()
        text = "\n".join(
            str(line)
            for line in app.query_one(TerminalPane).query_one("#session-log").lines
        )
        assert text.count("is holding mail for N1ABC") == 1, text
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_no_notice_when_the_beacon_is_for_somebody_else():
    app, mine, theirs = await _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await _beacon(theirs, "MAIL FOR: K1XYZ W2DEF")
        await pilot.pause()
        assert app._mail_notified == set()
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_no_notice_from_a_connected_mode_line_that_merely_mentions_it():
    """A beacon is a UI frame. Ordinary session chat that happens to contain
    the same words is not a node advertising a mailbox."""
    app, mine, theirs = await _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await mine.connect(AX25Path(PEER, MYCALL))
        assert link is not None
        far = theirs.link_to(MYCALL)
        assert far is not None
        await far.send(b"no MAIL FOR N1ABC here, just chatting\r")
        await pilot.pause()
        for _ in range(10):
            await pilot.pause()
        assert app._mail_notified == set()
    mine.close()
    theirs.close()
