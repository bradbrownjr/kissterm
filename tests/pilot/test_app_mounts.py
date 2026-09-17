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
from kissterm.addressbook import AddressBook  # noqa: E402
from kissterm.ui.commands import ACTION_META, KeyBindingsProvider, _action_base  # noqa: E402
from kissterm.ui.dialogs import CallsignScreen, ConnectScreen  # noqa: E402
from textual.widgets import TabbedContent  # noqa: E402
from textual.widgets import Input, Select, TextArea  # noqa: E402

from kissterm.ui.heard_pane import HeardPane  # noqa: E402
from kissterm.ui.monitor_pane import MonitorPane  # noqa: E402
from kissterm.ui.settings_pane import SettingsPane  # noqa: E402
from kissterm.ui.terminal_pane import TerminalPane  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402


def _plain(widget) -> str:
    """The text currently visible in `widget`, read from its rendered strips.

    `#status-bar` holds a `rich.table.Table` (see `kissterm.ui.app._status_row`),
    not a plain string, so `str(widget.render())` stopped containing the
    visible text the moment that changed -- `render()` returns a Textual
    `Visual` wrapper, and reaching into its private `_renderable` attribute is
    exactly the kind of internals-coupling that breaks on the next Textual
    upgrade. Rendering the actual strips is what the terminal itself would
    show, so it cannot drift from the display.
    """
    from textual.geometry import Region

    region = Region(0, 0, widget.size.width or 200, widget.size.height or 5)
    return "\n".join(strip.text for strip in widget.render_lines(region))


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
    # Transmit is disabled on a fresh app (kissterm/tx.py); these tests are
    # about other behaviour and would otherwise all fail at the gate. The
    # closed-by-default guarantee itself is asserted in
    # tests/pilot/test_transmit_gate.py.
    config = Config(mycall=str(MYCALL), active_transport="loopback")
    config.tx_armed_at_start = True
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
async def test_multiport_connect_uses_the_selected_radio_port():
    """A port choice must reach the station, not merely decorate the dialog."""
    app, ta, tb, station = await _app()
    ta.ports = tb.ports = 2
    far = AX25Station(PEER, tb, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("ctrl+n")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConnectScreen)
        screen.query_one("#connect-port", Select).value = 1
        target = screen.query_one("#connect-target", Input)
        target.value = str(PEER)
        await pilot.press("enter")
        await asyncio.sleep(0.2)
        assert station.link_to(PEER, 1) is not None
        assert station.link_to(PEER, 1).connected
        assert station.link_to(PEER, 0) is None
    station.close()
    far.close()


@pytest.mark.asyncio
async def test_monitor_port_picker_filters_a_multiport_transport():
    app, ta, tb, station = await _app()
    ta.ports = tb.ports = 2
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_show_tab("monitor")
        await pilot.pause()
        picker = app.query_one("#monitor-port", Select)
        picker.value = "1"
        await pilot.pause()
        assert app.monitor_filter.ports == (1,)
        picker.value = "all"
        await pilot.pause()
        assert app.monitor_filter.ports == ()
    station.close()


@pytest.mark.asyncio
async def test_remote_escape_sequences_never_reach_the_widget():
    """The sanitize rule, proven at the pane boundary rather than in a unit test."""
    app, ta, tb, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        pane = app.query_one(TerminalPane)
        pane.write_incoming(pane.active_session_key, b"\x1b[2J\x1b]0;pwned\x07NODE ready\r\n")
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
    config.tx_armed_at_start = True  # this test needs a real link; see test_transmit_gate.py
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
        text = _plain(app.query_one("#status-bar"))
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
async def test_a_position_frame_enriches_the_heard_table():
    """`HeardTable.set_position` used to be dead code -- nothing ever called
    it, so `HeardEntry.last_position` stayed `None` forever and the Heard
    pane's Distance/Bearing columns had nothing to render. This is the
    frame -> `_on_aprs_frame` -> `heard.set_position` wiring."""
    app, ta, tb, station = await _app()
    async with app.run_test(size=(110, 32)) as pilot:
        path = AX25Path(AX25Address.parse("APRS"), AX25Address.parse("W1AW-9"))
        # 42 23.45 N, 071 05.67 W in the plain uncompressed position format.
        await tb.send_frame(AX25Frame.u_frame(path, UType.UI, info=b"!4223.45N/07105.67W>"))
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.pause()

        entry = app.heard.get("W1AW-9")
        assert entry is not None, "position frame did not reach the heard table at all"
        assert entry.last_position is not None, "heard entry never got a position"
        lat, lon = entry.last_position
        assert lat == pytest.approx(42.0 + 23.45 / 60, abs=0.001)
        assert lon == pytest.approx(-(71.0 + 5.67 / 60), abs=0.001)
    station.close()


@pytest.mark.asyncio
async def test_a_plain_beacon_with_a_grid_square_enriches_the_heard_table_too():
    """Not every station beacons APRS -- a great many ordinary packet-node
    and BBS beacons just say their grid square in plain text. This is the
    `_on_aprs_frame`'s ``kind == "unparsed"`` -> `find_grid_in_text` path,
    the plain-packet counterpart to the APRS position test above."""
    app, ta, tb, station = await _app()
    async with app.run_test(size=(110, 32)) as pilot:
        path = AX25Path(AX25Address.parse("BEACON"), AX25Address.parse("N1ABC-9"))
        await tb.send_frame(
            AX25Frame.u_frame(path, UType.UI, info=b"N1ABC-9 BBS de FN31pr QRV 145.030")
        )
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.pause()

        entry = app.heard.get("N1ABC-9")
        assert entry is not None, "beacon frame did not reach the heard table at all"
        assert entry.last_position is not None, "plain-text grid square was not picked up"
        lat, lon = entry.last_position
        assert lat == pytest.approx(41.7, abs=0.5)
        assert lon == pytest.approx(-72.7, abs=1.0)
    station.close()


@pytest.mark.asyncio
async def test_heard_table_shows_bearing_and_distance_once_own_position_is_set():
    app, ta, tb, station = await _app()
    async with app.run_test(size=(120, 32)) as pilot:
        # Same fix as the test above, a few miles from the operator's own
        # position set below.
        path = AX25Path(AX25Address.parse("APRS"), AX25Address.parse("W1AW-9"))
        await tb.send_frame(AX25Frame.u_frame(path, UType.UI, info=b"!4223.45N/07105.67W>"))
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.pause()

        # Nothing set yet -- Distance/Bearing must read "-", not crash or
        # show a stale/zero value.
        app.action_show_tab("heard")
        await pilot.pause()
        table = app.query_one("#heard-table")
        row = next(r for r in range(table.row_count) if str(table.get_cell_at((r, 0))) == "W1AW-9")
        assert str(table.get_cell_at((row, 5))) == "-"
        assert str(table.get_cell_at((row, 6))) == "-"

        app.config.aprs.latitude = 42.0
        app.config.aprs.longitude = -71.0
        app._refresh_heard(force=True)
        await pilot.pause()

        row = next(r for r in range(table.row_count) if str(table.get_cell_at((r, 0))) == "W1AW-9")
        distance_text = str(table.get_cell_at((row, 5)))
        bearing_text = str(table.get_cell_at((row, 6)))
        assert distance_text.endswith("mi"), distance_text
        assert "\N{DEGREE SIGN}" in bearing_text, bearing_text
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


# ---------------------------------------------------------------------------
# The footer must not repeat what the tab bar already says. F1-F5 switch tabs
# and are named IN the tab label; showing them again in the footer put the
# same words on screen twice, in two different corners.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tab_switching_keys_are_not_duplicated_in_the_footer():
    app, ta, tb, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # Check the Footer's own binding source directly, so this does not
        # depend on rendering or terminal width.
        shown = {
            key: active.binding.description
            for key, active in app.active_bindings.items()
            if active.binding.show
        }
        for key in ("f1", "f2", "f3", "f4", "f5"):
            assert key not in shown, (
                f"{key} is shown in the footer, duplicating its tab label"
            )
        # Function keys are tabs; Ctrl sequences are actions and modals. So
        # NO function key should appear in the footer at all -- the command
        # reference is ctrl+r, and the F-row stays reserved for the tabs
        # still to come (Mail, Bulletins, Files).
        assert not any(k.startswith("f") and k[1:].isdigit() for k in shown), (
            f"a function key is in the footer: {sorted(shown)}"
        )
        assert "ctrl+r" in shown
    station.close()


#: The tab bar, left to right: the printed label, the pane id it opens, and
#: the key that opens it. Ordered by how often an operator visits them --
#: requested directly, "putting useful stuff to the left of Monitor and
#: Settings". The three have to agree, which is what the two tests below
#: check: a label that says F2 while F2 opens something else is worse than
#: no hint at all.
TAB_BAR = (
    ("F1 Terminal", "terminal", "f1"),
    ("F2 APRS", "aprs", "f2"),
    ("F3 Heard", "heard", "f3"),
    ("F4 Monitor", "monitor", "f4"),
    ("F5 Settings", "settings", "f5"),
)


@pytest.mark.asyncio
async def test_tab_labels_carry_the_function_key_hint_in_order():
    app, ta, tb, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # The OUTER strip only -- `#main-tabs` also contains the Settings
        # pane's own `TabbedContent`, whose tabs would otherwise be counted.
        strip = app.query_one("#main-tabs").query_one("Tabs")
        labels = [str(tab.label) for tab in strip.query("Tab")]
        assert labels == [label for label, _, _ in TAB_BAR]
    station.close()


@pytest.mark.asyncio
async def test_each_function_key_opens_the_pane_its_label_names():
    """The label and the key are two copies of one fact, in two places. This
    is the test that stops them drifting apart -- pressed from a focused
    input, because that is the case the tab keys were silently broken in
    until the focus fix (see `action_show_tab`)."""
    app, ta, tb, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        for _, pane_id, key in TAB_BAR:
            # Back to Terminal and into its send line each time, so every key
            # is pressed from the same starting point -- and from a focused
            # `Input`, never from a fresh app with focus nowhere.
            app.action_show_tab("terminal")
            await pilot.pause()
            await asyncio.sleep(0.05)
            app.query_one("#session-input").focus()
            await pilot.pause()

            await pilot.press(key)
            await pilot.pause()
            await asyncio.sleep(0.1)
            assert app.query_one("#main-tabs").active == pane_id, key
    station.close()


# ---------------------------------------------------------------------------
# The Ctrl+G contacts slide-out -- see DESIGN.md's "slide-out panels" section.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_addressbook_slideout_follows_the_width_rule():
    """It used to start hidden unconditionally. Now it opens itself at 80
    columns and stays shut below that -- see `kissterm/ui/slideouts.py`, and
    `tests/pilot/test_slideout_auto_open.py` for the rest of the behaviour."""
    for size, expected in (((79, 30), False), ((120, 40), True)):
        app, ta, tb, station = await _app()
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await asyncio.sleep(0.1)
            await pilot.pause()
            assert app.query_one("#terminal-addressbook-column").display is expected, size
        station.close()


@pytest.mark.asyncio
async def test_ctrl_g_is_a_no_op_on_a_tab_with_no_slideout():
    """Ctrl+G means the same thing everywhere; on a tab with nothing to open
    it does nothing at all -- and in particular does not reach into another
    pane's slide-out. Run narrow so the Terminal pane's column is shut to
    begin with, which makes "nothing happened" unambiguous."""
    app, ta, tb, station = await _app()
    async with app.run_test(size=(79, 30)) as pilot:
        await pilot.press("f4")  # Monitor -- no slide-out of its own
        await pilot.pause()
        assert not app.query_one("#terminal-addressbook-column").display
        await pilot.press("ctrl+g")
        await pilot.pause()
        assert not app.query_one("#terminal-addressbook-column").display
    station.close()


# ---------------------------------------------------------------------------
# The width-aware Footer and the Ctrl+P key reference --
# docs/CHANGELOG.md's "Footer overflow and a real, searchable Keys
# reference" entry, kissterm/ui/commands.py.
# ---------------------------------------------------------------------------


def test_every_visible_binding_action_has_footer_and_palette_metadata():
    """A `Binding` with no `ACTION_META` entry silently falls back to
    `commands._FALLBACK_META` instead of crashing the Footer -- this test is
    what actually enforces that every action gets a deliberate category and
    priority, the same discipline `AGENTS.md` asks of `Config`/
    `SETTINGS_SCHEMA`."""
    missing = {
        _action_base(binding.action)
        for binding in KissTermApp.BINDINGS
        if binding.show and _action_base(binding.action) not in ACTION_META
    }
    assert not missing, f"no ACTION_META entry for: {sorted(missing)}"


@pytest.mark.asyncio
async def test_the_footer_shows_fewer_keys_at_an_ordinary_terminal_width():
    app, ta, tb, station = await _app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        footer = app.query_one("Footer")
        shown = {c.description for c in footer.children}
        # The core mid-contact cluster survives an 80-column terminal...
        for essential in ("TX", "Connect", "Disconnect", "Contacts"):
            assert essential in shown, f"{essential} missing at 80 columns: {shown}"
        # ...but not everything does; if it did, this feature fixed nothing.
        assert "Transcripts" not in shown
        assert len(shown) < len(KissTermApp.BINDINGS)
    station.close()


@pytest.mark.asyncio
async def test_the_footer_shows_every_binding_once_the_terminal_is_wide_enough():
    app, ta, tb, station = await _app()
    async with app.run_test(size=(200, 30)) as pilot:
        await pilot.pause()
        footer = app.query_one("Footer")
        shown = {c.description for c in footer.children}
        for expected in (
            "TX",
            "Connect",
            "Disconnect",
            "Contacts",
            "Commands",
            "Beacon",
            "Callsign",
            "Find",
            "Clear",
            "Transcripts",
            "Quit",
        ):
            assert expected in shown, f"{expected} missing at 200 columns: {shown}"
    station.close()


@pytest.mark.asyncio
async def test_the_footer_widens_back_out_on_a_live_resize():
    app, ta, tb, station = await _app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        footer = app.query_one("Footer")
        narrow_count = len(list(footer.children))
        await pilot.resize_terminal(200, 30)
        await pilot.pause()
        assert len(list(footer.children)) > narrow_count
    station.close()


@pytest.mark.asyncio
async def test_ctrl_p_key_reference_finds_and_runs_a_binding():
    """Before this, Ctrl+P only listed Textual's own tiny built-in System
    Commands -- searching for one of kissterm's own keys found nothing at
    all, regardless of terminal width."""
    app, ta, tb, station = await _app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        assert KeyBindingsProvider in app.COMMANDS
        provider = KeyBindingsProvider(app.screen)
        hits = [hit async for hit in provider.search("contacts")]
        assert hits, "Ctrl+G's Contacts binding is not searchable from the palette"
        # 80 columns is exactly the auto-open threshold, so the slide-out is
        # already showing -- what the palette hit has to prove is that it
        # runs the action at all, which here means closing it.
        column = app.query_one("#terminal-addressbook-column")
        assert column.display
        await hits[0].command()
        await pilot.pause()
        assert not column.display, "the palette hit's command did not run the action"
    station.close()


@pytest.mark.asyncio
async def test_status_bar_sits_below_the_footer():
    """The keys you might press come first; the passive readout comes last."""
    app, ta, tb, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        footer_y = app.query_one("Footer").region.y
        status_y = app.query_one("#status-bar").region.y
        assert status_y > footer_y, "status bar is not below the footer"
    station.close()


@pytest.mark.asyncio
async def test_active_tab_has_no_solid_block_background():
    """Regression: Textual's default block-cursor fill on the focused tab
    strip read as a heavy rectangle next to the flat panels elsewhere.

    "transparent" composites down to the ambient screen color rather than
    reporting zero alpha, so the right check is that the ACTIVE tab's
    resolved background matches an INACTIVE one -- i.e. our override adds no
    extra fill of its own -- rather than asserting anything about alpha.
    """
    app, ta, tb, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        tabs_widget = app.query_one("#main-tabs").query_one("Tabs")
        all_tabs = list(tabs_widget.query("Tab"))
        active = next(t for t in all_tabs if "-active" in t.classes)
        inactive = next(t for t in all_tabs if "-active" not in t.classes)
        active_bg = active.get_visual_style().background
        inactive_bg = inactive.get_visual_style().background
        assert active_bg == inactive_bg, (
            f"active tab has its own fill ({active_bg}) distinct from an "
            f"inactive tab's ({inactive_bg})"
        )
    station.close()


@pytest.mark.asyncio
async def test_status_bar_matches_the_tab_bars_black_not_the_header_panel():
    """Requested directly: status bar should read as the same black as the
    tab row, not the slate-blue $panel shade Header/Footer use.
    """
    app, ta, tb, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        status_bg = app.query_one("#status-bar").get_visual_style().background
        tabs_bg = app.query_one("#main-tabs").query_one("Tabs").get_visual_style().background
        header_bg = app.query_one("Header").get_visual_style().background
        assert status_bg == tabs_bg, f"status bar ({status_bg}) != tab bar ({tabs_bg})"
        assert status_bg != header_bg, "status bar should not match the Header's panel shade"
    station.close()


@pytest.mark.asyncio
async def test_status_fields_spread_across_the_full_width_not_bunched_left():
    """The old '  |  '.join() rendering left most of a wide terminal blank."""
    app, ta, tb, station = await _app()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        region = app.query_one("#status-bar").size
        from textual.geometry import Region as _Region

        line = app.query_one("#status-bar").render_lines(
            _Region(0, 0, region.width, 1)
        )[0]
        text = line.text
        first_content_col = len(text) - len(text.lstrip())
        last_content_col = len(text.rstrip())
        # A left-bunched single string would leave a large blank run at the
        # right; spread fields should reach well past the middle of the row.
        assert last_content_col > region.width * 0.6, (
            f"status content ends at column {last_content_col} of {region.width}"
        )
    station.close()


@pytest.mark.asyncio
async def test_clicking_the_header_does_not_reshuffle_the_layout():
    """Textual's Header grows to three lines when clicked, to reveal a title
    and subtitle. kissterm has neither -- the status bar carries the station
    identity -- so the two extra rows show nothing while pushing the tab bar,
    the panes and the scrollback down by two, mid-session, because a mouse
    click landed on the top row."""
    app, ta, tb, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        header = app.query_one("Header")
        before = header.size.height
        # The TITLE, not the Header origin: the origin is HeaderIcon,
        # which handles its own click (command palette) and stops it
        # before the toggle ever sees it. Clicking there proves nothing.
        await pilot.click("HeaderTitle")
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.pause()
        assert header.size.height == before, (
            f"the header changed height on click: {before} -> {header.size.height}"
        )
        assert not header.has_class("-tall")

        # ...and the one click the header IS supposed to answer still works.
        # The toggle is suppressed with `prevent_default`, which stops
        # Textual's MRO walk -- if that had been done by stopping the event
        # instead, the command palette icon would have gone with it.
        await pilot.click("HeaderIcon")
        await pilot.pause()
        await asyncio.sleep(0.1)
        assert type(app.screen).__name__ == "CommandPalette", (
            f"the header icon no longer opens the palette (got {type(app.screen).__name__})"
        )
    station.close()


# ---------------------------------------------------------------------------
# The connect dialog's address book
# ---------------------------------------------------------------------------


def _fresh_book(app, tmp_path):
    """Point the app's address book at a per-test file.

    `isolate()` redirects platformdirs once for the whole session, so every
    test otherwise shares one `addressbook.json` and reads rows another test
    wrote -- which is how these first went green in isolation and red in a
    full run.
    """
    app.addressbook = AddressBook(tmp_path / "addressbook.json")
    return app.addressbook


async def _open_connect(app, pilot):
    await pilot.press("ctrl+n")
    await pilot.pause()
    await asyncio.sleep(0.15)
    await pilot.pause()
    assert isinstance(app.screen, ConnectScreen), f"got {type(app.screen).__name__}"
    return app.screen


def _address_book_targets(select: Select) -> list:
    """The station targets currently offered by the address-book dropdown,
    in on-screen order. `Select` exposes no public accessor for its option
    list, so this reads `_options` directly -- the same tuples `set_options`
    was given, minus the leading blank/`Select.NULL` entry every `Select`
    with `allow_blank` carries."""
    return [value for _, value in select._options if value is not Select.NULL]


@pytest.mark.asyncio
async def test_the_connect_dialog_offers_stations_already_tried(tmp_path):
    """`WS1EC-15` and `WS1EC-7` are different services on one machine, and a
    mistyped SSID fails in a way that looks exactly like a bad RF path."""
    app, ta, tb, station = await _app()
    _fresh_book(app, tmp_path)
    app.addressbook.record_attempt("WS1EC-15")
    app.addressbook.record_connect("W1AW-1")
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open_connect(app, pilot)
        select = screen.query_one("#connect-address-book", Select)
        assert select.display, "the address book dropdown was not shown"
        assert _address_book_targets(select) == ["W1AW-1", "WS1EC-15"]
    station.close()


@pytest.mark.asyncio
async def test_typing_narrows_the_list(tmp_path):
    app, ta, tb, station = await _app()
    _fresh_book(app, tmp_path)
    for target in ("WS1EC-15", "WS1EC-7", "W1AW-1"):
        app.addressbook.record_attempt(target)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open_connect(app, pilot)
        for key in "ws":
            await pilot.press(key)
        await pilot.pause()
        select = screen.query_one("#connect-address-book", Select)
        assert _address_book_targets(select) == ["WS1EC-7", "WS1EC-15"]
    station.close()


@pytest.mark.asyncio
async def test_delete_forgets_a_row_and_it_stays_forgotten(tmp_path):
    """The explicit ask: rows you can delete -- pick one from the address
    book dropdown, then Delete forgets it."""
    app, ta, tb, station = await _app()
    _fresh_book(app, tmp_path)
    app.addressbook.record_attempt("WS1EC-15")
    app.addressbook.record_attempt("W1AW-1")
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open_connect(app, pilot)
        select = screen.query_one("#connect-address-book", Select)
        select.value = "W1AW-1"
        select.focus()
        await pilot.pause()
        assert select.has_focus, "picking a row did not leave the dropdown focused"
        await pilot.press("delete")
        await pilot.pause()
        assert _address_book_targets(select) == ["WS1EC-15"]
        assert [e.target for e in app.addressbook.entries] == ["WS1EC-15"]

        reloaded = AddressBook(app.addressbook.file)
        reloaded.load()
        assert [e.target for e in reloaded.entries] == ["WS1EC-15"], (
            "the deletion was not persisted"
        )
    station.close()


@pytest.mark.asyncio
async def test_delete_while_typing_edits_text_instead_of_forgetting(tmp_path):
    """Delete is a text-editing key first. Losing a saved station because the
    cursor was in the input would be a nasty surprise."""
    app, ta, tb, station = await _app()
    _fresh_book(app, tmp_path)
    app.addressbook.record_attempt("WS1EC-15")
    async with app.run_test(size=(120, 40)) as pilot:
        await _open_connect(app, pilot)
        await pilot.press("delete")
        await pilot.pause()
        assert [e.target for e in app.addressbook.entries] == ["WS1EC-15"]
    station.close()


@pytest.mark.asyncio
async def test_a_first_run_shows_no_empty_list(tmp_path):
    """With nothing remembered the dialog must look exactly as it did before
    this feature -- not a blank dropdown where a list will one day be."""
    app, ta, tb, station = await _app()
    _fresh_book(app, tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open_connect(app, pilot)
        assert not screen.query_one("#connect-address-book", Select).display
        assert not screen.query_one("#connect-hint").display
    station.close()


@pytest.mark.asyncio
async def test_a_confirmed_target_is_remembered_even_when_it_fails(tmp_path):
    app, ta, tb, station = await _app()
    _fresh_book(app, tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _open_connect(app, pilot)
        for key in "WS1EC-7":
            await pilot.press(key if key != "-" else "minus")
        await pilot.press("enter")
        await pilot.pause()
        await asyncio.sleep(0.2)
        assert [e.target for e in app.addressbook.entries] == ["WS1EC-7"]
        assert app.addressbook.entries[0].attempts == 1
    station.close()


@pytest.mark.asyncio
async def test_browsing_history_previews_that_stations_script(tmp_path):
    """Picking a row from the address-book dropdown loads its saved script
    into the box -- that is how an operator finds out one is even there,
    short of remembering it."""
    app, ta, tb, station = await _app()
    book = _fresh_book(app, tmp_path)
    book.record_attempt("WS1EC-7", script="CLYDE\nMYPASS")
    book.record_attempt("W1AW-1")  # no script -- the preview must clear too
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open_connect(app, pilot)
        select = screen.query_one("#connect-address-book", Select)

        select.value = "W1AW-1"  # the most recent entry, no script
        await pilot.pause()
        assert screen.query_one("#connect-script", TextArea).text == ""

        # Picking narrowed the dropdown to whatever now matches the target
        # field it just filled in (see `ConnectScreen._render_history`'s
        # docstring) -- clear it before the second pick, exactly as an
        # operator would by backspacing, or "WS1EC-7" is not a legal option
        # any more.
        screen.query_one("#connect-target", Input).value = ""
        await pilot.pause()
        select.value = "WS1EC-7"
        await pilot.pause()
        assert screen.query_one("#connect-script", TextArea).text == "CLYDE\nMYPASS"
    station.close()


@pytest.mark.asyncio
async def test_a_saved_script_is_sent_after_the_connect_comes_up(tmp_path):
    """The point of the feature: log in without retyping it, but not
    invisibly -- every line has to land in the terminal log exactly as if
    the operator had typed and sent it, and actually reach the peer."""
    app, ta, tb, station = await _app()
    book = _fresh_book(app, tmp_path)
    book.record_attempt("WS1EC-7", script="CLYDE\nMYPASS")
    peer_station = AX25Station(PEER, tb, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open_connect(app, pilot)
        screen.query_one("#connect-address-book", Select).value = "WS1EC-7"
        await pilot.pause()
        await pilot.click("#connect-go")
        await pilot.pause()
        await asyncio.sleep(2.0)  # connect, then two lines ~0.75s apart
        await pilot.pause()

        log = app.query_one(TerminalPane).query_one("#session-log")
        text = "\n".join(str(line) for line in log.lines)
        assert "Auto-login: sending 2 line(s)" in text, text
        assert "CLYDE" in text and "MYPASS" in text, text

        peer_link = peer_station.link_to(MYCALL)
        assert peer_link is not None, "the connect never reached the peer"
        assert peer_link.read_nowait() == b"CLYDE\rMYPASS\r"
    peer_station.close()
    station.close()


@pytest.mark.asyncio
async def test_a_digipeater_path_and_node_hops_together_is_refused(tmp_path):
    """The two do not compose -- a digipeater path repeats ONE frame at the
    link layer, node hops are a sequence of independent connects made
    minutes apart. Silently picking one would be a worse outcome than
    refusing outright."""
    app, ta, tb, station = await _app()
    _fresh_book(app, tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open_connect(app, pilot)
        screen.query_one("#connect-target", Input).value = "W1LH-6 via W1XYZ"
        screen.query_one("#connect-hops", Input).value = "WS1EC-7"
        await pilot.pause()
        await pilot.click("#connect-go")
        await pilot.pause()
        assert isinstance(app.screen, ConnectScreen), "dismissed despite the conflict"
        error = str(screen.query_one("#connect-error").content)
        assert "pick one" in error, error
    station.close()


@pytest.mark.asyncio
async def test_selecting_a_saved_credential_disables_the_script_box(tmp_path):
    """The script box is disabled, not cleared or overwritten, while a
    credential is selected -- so toggling the dropdown back and forth can
    never leak one credential's text into another station's saved script."""
    app, ta, tb, station = await _app()
    app.config.credentials = [{"name": "Personal BBS login", "text": "MYPASS"}]
    _fresh_book(app, tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("ctrl+n")
        await pilot.pause()
        await asyncio.sleep(0.15)
        screen = app.screen
        area = screen.query_one("#connect-script", TextArea)
        area.text = "something typed by hand"

        screen.query_one("#connect-credential", Select).value = "Personal BBS login"
        await pilot.pause()
        assert area.disabled is True
        assert area.text == "something typed by hand", "typed text was overwritten"

        screen.query_one("#connect-credential", Select).value = Select.NULL
        await pilot.pause()
        assert area.disabled is False
        assert area.text == "something typed by hand", "typed text was lost"
    station.close()



@pytest.mark.asyncio
async def test_tab_keys_work_while_an_input_has_focus():
    """The regression that made F1-F5 unusable whenever you were typing.

    Textual re-activates a `TabPane` when a widget inside it takes focus.
    Switching tabs while an `Input` in the outgoing pane was still focused
    made Textual move focus to the next widget *in that hidden pane*, which
    pulled the activation straight back -- the tab appeared for a frame and
    vanished. It affected every pane with a focusable widget, and went
    unnoticed because tests drove `action_show_tab` without focusing
    anything first.
    """
    app, _ta, _tb, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        tabs = app.query_one("#main-tabs", TabbedContent)
        for start, widget, key, dest in (
            ("terminal", "#session-input", "f2", "aprs"),
            ("terminal", "#session-input", "f5", "settings"),
            ("aprs", "#aprs-compose-input", "f4", "monitor"),
            ("aprs", "#aprs-compose-input", "f3", "heard"),
        ):
            app.action_show_tab(start)
            await pilot.pause()
            await asyncio.sleep(0.1)
            app.query_one(widget).focus()
            await pilot.pause()
            assert tabs.active == start

            await pilot.press(key)
            await pilot.pause()
            await asyncio.sleep(0.2)
            assert tabs.active == dest, (
                f"{key} from {start} with {widget} focused landed on "
                f"{tabs.active}, not {dest}"
            )
    station.close()


@pytest.mark.asyncio
async def test_opening_a_tab_focuses_something_worth_typing_into():
    """The other half of the fix: land somewhere useful, not nowhere."""
    app, _ta, _tb, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        for tab, expected in (
            ("terminal", "session-input"),
            ("aprs", "aprs-compose-input"),
            ("monitor", "monitor-query"),
        ):
            app.action_show_tab(tab)
            await pilot.pause()
            await asyncio.sleep(0.2)
            assert app.focused is not None and app.focused.id == expected, (
                f"{tab} focused {app.focused.id if app.focused else None}"
            )
    station.close()
