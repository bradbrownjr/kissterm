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
from kissterm.ui.dialogs import ConnectScreen  # noqa: E402
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
