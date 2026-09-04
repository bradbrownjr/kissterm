"""Headless Textual tests: the app mounts, its tabs work, and frames reach panes.

`isolate()` runs FIRST, before any other kissterm import. `kissterm/config.py`
computes its config/state/data paths from `platformdirs` at **import time**,
using the same "kissterm" app name the real installed app uses -- on a dev
machine that is the developer's actual `~/.config/kissterm`. Patching after the
import is too late. See `kissterm/_isolate.py`; this is a hard rule in this
repo, and a sibling project destroyed a real user's settings twice by getting
it wrong.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams  # noqa: E402
from kissterm.ax25.frame import AX25Frame, UType  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.dialogs import CallsignScreen, ConnectScreen  # noqa: E402
from kissterm.ui.heard_pane import HeardPane  # noqa: E402
from kissterm.ui.monitor_pane import MonitorPane  # noqa: E402
from kissterm.ui.settings_pane import SettingsPane  # noqa: E402
from kissterm.ui.terminal_pane import TerminalPane  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
PEER = AX25Address.parse("WS1EC-7")


async def _app():
    """An app on a loopback transport: no radio, no serial port, no real config.

    `KissTermApp(config, station)` takes both as constructor arguments
    specifically so this is possible. Do not let it construct them internally.
    """
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = Config(mycall=str(MYCALL), active_transport="loopback")
    station = AX25Station(MYCALL, ta, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    return KissTermApp(config, station), ta, tb, station


@pytest.mark.asyncio
async def test_app_mounts_with_every_pane():
    app, ta, tb, station = await _app()
    async with app.run_test(size=(120, 40)):
        for pane in (TerminalPane, MonitorPane, HeardPane, SettingsPane):
            assert app.query_one(pane) is not None, f"{pane.__name__} did not mount"
    station.close()


@pytest.mark.asyncio
async def test_every_tab_can_be_selected():
    app, ta, tb, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        for tab in ("monitor", "heard", "aprs", "settings", "terminal"):
            app.action_show_tab(tab)
            await pilot.pause()
            assert app.query_one("#main-tabs").active == tab
    station.close()


@pytest.mark.asyncio
async def test_a_frame_off_the_air_reaches_the_monitor_pane():
    """The end-to-end fan-out: transport -> station -> app -> MonitorPane."""
    app, ta, tb, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_show_tab("monitor")
        await pilot.pause()

        # A UI frame between two other stations -- not addressed to us, which
        # is exactly the traffic the monitor pane exists to show.
        path = AX25Path(AX25Address.parse("APRS"), AX25Address.parse("W1AW-9"))
        await tb.send_frame(AX25Frame.u_frame(path, UType.UI, info=b"!4223.45N/07105.67W>"))
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.pause()

        rendered = app.query_one("#monitor-log").lines
        text = "\n".join(str(line) for line in rendered)
        assert "W1AW-9" in text, f"frame never reached the monitor pane: {text!r}"
        assert len(app.heard) >= 1, "heard table did not record the frame"
    station.close()


@pytest.mark.asyncio
async def test_connect_dialog_opens():
    app, ta, tb, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("ctrl+n")
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.pause()
        assert isinstance(app.screen, ConnectScreen), f"got {type(app.screen).__name__}"
    station.close()


@pytest.mark.asyncio
async def test_remote_escape_sequences_never_reach_the_widget():
    """The sanitize rule, proven at the pane boundary rather than in a unit test."""
    app, ta, tb, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        pane = app.query_one(TerminalPane)
        pane.write_incoming(b"\x1b[2J\x1b]0;pwned\x07NODE ready\r\n")
        await pilot.pause()
        text = "\n".join(str(line) for line in app.query_one("#session-log").lines)
        assert "NODE ready" in text
        assert "\x1b" not in text and "pwned" not in text, "escape sequence survived"
    station.close()


# ---------------------------------------------------------------------------
# Changing callsign. An operator changes SSID far more often than the "set it
# once at install" model assumes -- portable, a -1 mailbox, a club call for an
# event -- so this path needs to work without a restart or a wizard.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_callsign_dialog_opens_prefilled():
    app, ta, tb, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("ctrl+k")
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.pause()
        assert isinstance(app.screen, CallsignScreen)
        field = app.screen.query_one("#callsign-value")
        assert field.value == str(MYCALL), "dialog must prefill the current call"
    station.close()


@pytest.mark.asyncio
async def test_changing_callsign_updates_the_live_station():
    """The change must reach the station, not just the config file.

    Otherwise it silently would not take effect until the next launch, which
    is exactly the confusion this feature exists to remove.
    """
    app, ta, tb, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("ctrl+k")
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.pause()

        field = app.screen.query_one("#callsign-value")
        field.value = "W1AW-9"
        await pilot.press("enter")
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()

        assert app.config.mycall == "W1AW-9"
        assert str(station.mycall) == "W1AW-9", "live station kept the old callsign"
    station.close()


@pytest.mark.asyncio
async def test_new_callsign_is_the_one_actually_transmitted():
    """The proof that matters: the new call appears in the address field."""
    app, ta, tb, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("ctrl+k")
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.pause()
        app.screen.query_one("#callsign-value").value = "W1AW-9"
        await pilot.press("enter")
        await pilot.pause()
        await asyncio.sleep(0.2)

        ta.sent.clear()
        await station.connect(AX25Path(PEER, station.mycall), timeout=0.5)
        assert ta.sent, "no frame was transmitted"
        assert str(ta.sent[0].path.source) == "W1AW-9", (
            f"transmitted as {ta.sent[0].path.source}, not the new callsign"
        )
    station.close()


@pytest.mark.asyncio
async def test_callsign_change_refused_while_connected():
    """Swapping the call mid-session would kill the link by N2 timeout."""
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = Config(mycall=str(MYCALL))
    a = AX25Station(MYCALL, ta, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    b = AX25Station(PEER, tb, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    app = KissTermApp(config, a)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()  # let compose() finish before querying panes
        link = await a.connect(AX25Path(PEER, MYCALL))
        assert link is not None and link.connected
        app._bind_link(link)
        await pilot.press("ctrl+k")
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.pause()
        assert not isinstance(app.screen, CallsignScreen), (
            "dialog opened while a link was up"
        )
        assert app.config.mycall == str(MYCALL)
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_status_bar_and_footer_do_not_overlap():
    """Regression: both used to dock bottom and land in the same region.

    The Footer painted over the status bar, so link state, frame counts and
    retransmit count -- the diagnostics an operator actually watches -- were
    invisible. Nothing in the suite caught it; generating a screenshot did.
    Assert on geometry, because "is it visible" is exactly what was wrong.
    """
    app, ta, tb, station = await _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        bar = app.query_one("#status-bar").region
        footer = app.query_one("Footer").region
        assert bar.y != footer.y, (
            f"status bar and footer share row {bar.y}; the footer will hide it"
        )
        assert bar.height >= 1 and bar.width > 0
    station.close()


@pytest.mark.asyncio
async def test_status_bar_is_populated_on_mount():
    """It used to stay blank for the first second, until the interval fired."""
    app, ta, tb, station = await _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        text = str(app.query_one("#status-bar").render())
        assert str(MYCALL) in text, f"status bar was blank on mount: {text!r}"
    station.close()


@pytest.mark.asyncio
async def test_heard_table_populates_the_moment_the_tab_opens():
    """Regression: it stayed empty until the 2-second interval ticked.

    The status bar said "heard 6" while the table showed nothing, which reads
    as "nothing heard" at the exact moment the operator went looking.
    """
    app, ta, tb, station = await _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        for call in ("KC1XYZ-9", "W1AW-7", "KB1QRP"):
            path = AX25Path(AX25Address.parse("APRS"), AX25Address.parse(call))
            await tb.send_frame(AX25Frame.u_frame(path, UType.UI, info=b"x"))
        await pilot.pause()
        await asyncio.sleep(0.1)

        app.action_show_tab("heard")
        await pilot.pause()          # no sleep: it must be populated already
        table = app.query_one("#heard-table")
        assert table.row_count == 3, (
            f"heard table had {table.row_count} rows immediately after switching"
        )
    station.close()


@pytest.mark.asyncio
async def test_unplugging_the_active_transport_is_reported():
    """A TNC vanishing mid-session must say so, not fail silently later."""
    from kissterm.hotplug import PortEvent

    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = Config(
        mycall=str(MYCALL),
        transports=[{"name": "USB TNC", "kind": "serial", "device": "/dev/ttyUSB0"}],
        active_transport="USB TNC",
    )
    station = AX25Station(MYCALL, ta, LinkParams())
    app = KissTermApp(config, station)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        assert app._active_device() == "/dev/ttyUSB0"
        app._on_port_event(PortEvent(action="removed", device="/dev/ttyUSB0"))
        await pilot.pause()
        text = "\n".join(str(line) for line in app.query_one("#session-log").lines)
        assert "unplugged" in text.lower(), f"no warning logged: {text!r}"

        # A different port disappearing is not the operator's problem.
        before = text
        app._on_port_event(PortEvent(action="removed", device="/dev/ttyS9"))
        await pilot.pause()
        after = "\n".join(str(line) for line in app.query_one("#session-log").lines)
        assert after == before, "an unrelated port produced a warning"
    station.close()
