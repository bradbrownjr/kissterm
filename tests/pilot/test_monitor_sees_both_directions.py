"""The monitor pane has to be a CHANNEL monitor, not a leftovers pane.

An operator connected to a distant node over a marginal path and could not
tell, from anything on screen, whether their SABM had been transmitted at all.
Two separate reasons for that, both fixed and both guarded here:

* nothing kissterm transmitted was ever shown, and
* a frame belonging to an open link is routed straight to that link by
  `AX25Station`, so it never reached `on_unhandled` -- which was the monitor's
  only input. The pane therefore went quiet at precisely the moment a
  connection was being established, which is the event worth watching.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.ax25.address import AX25Path  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.monitor_pane import MonitorPane  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
PEER = AX25Address.parse("WS1EC-15")


def _monitor_text(app) -> str:
    from textual.widgets import RichLog

    log = app.query_one(MonitorPane).query_one("#monitor-log", RichLog)
    return "\n".join(str(line) for line in log.lines)


async def _show_monitor(app, pilot) -> None:
    """A `RichLog` on an unrendered tab has no `lines` to assert against --
    it holds the text but has never been given a width to wrap it to. Switch
    to the tab the way the operator would."""
    app.action_show_tab("monitor")
    await pilot.pause()


async def _app():
    """The app on one end of the loopback, a plain station on the other."""
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


@pytest.mark.asyncio
async def test_our_own_transmissions_appear_in_the_monitor():
    app, mine, theirs = await _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await mine.connect(AX25Path(PEER, MYCALL))
        assert link is not None, "the loopback peer did not answer"
        await _show_monitor(app, pilot)
        text = _monitor_text(app)
        assert "SABM" in text, text
        assert "> " in text, "no outgoing direction marker: " + text
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_the_answer_to_our_connect_appears_in_the_monitor():
    """The UA is the single most interesting frame of a connection attempt,
    and it belongs to a link -- which is exactly why it used to be invisible."""
    app, mine, theirs = await _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await mine.connect(AX25Path(PEER, MYCALL))
        assert link is not None
        await _show_monitor(app, pilot)
        text = _monitor_text(app)
        assert "UA" in text, text
        assert "< " in text, "no incoming direction marker: " + text
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_traffic_on_an_established_link_is_still_monitored():
    app, mine, theirs = await _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await mine.connect(AX25Path(PEER, MYCALL))
        assert link is not None
        far = theirs.link_to(MYCALL)
        assert far is not None
        await far.send(b"hello from the node\r")
        await _show_monitor(app, pilot)
        for _ in range(20):
            if "hello from the node" in _monitor_text(app):
                break
            await pilot.pause()
        assert "hello from the node" in _monitor_text(app), _monitor_text(app)
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_nothing_reaches_the_monitor_while_transmit_is_disabled():
    """The gate drops the frame before it is sent; showing it would tell the
    operator they had transmitted with TX off."""
    app, mine, theirs = await _app()
    app.config.tx_armed_at_start = False
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        app.gate.set(False)
        await mine.connect(AX25Path(PEER, MYCALL), timeout=0.4)
        await _show_monitor(app, pilot)
        assert "SABM" not in _monitor_text(app), _monitor_text(app)
    mine.close()
    theirs.close()
