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
from kissterm.ui.dialogs import CallsignScreen, ConnectScreen  # noqa: E402
from textual.widgets import Input, OptionList, Select, TextArea  # noqa: E402

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
        for key in ("f1", "f2", "f3", "f4", "f5", "f6"):
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


@pytest.mark.asyncio
async def test_tab_labels_carry_the_function_key_hint():
    app, ta, tb, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        tabs = app.query_one("#main-tabs")
        labels = {str(tab.label) for tab in tabs.query("Tab")}
        for hint in (
            "F1 Terminal",
            "F2 Monitor",
            "F3 Heard",
            "F4 APRS",
            "F5 Address Book",
            "F6 Settings",
        ):
            assert hint in labels, f"missing {hint!r} in tab labels: {labels}"
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
        history = screen.query_one("#connect-history", OptionList)
        assert history.display, "the history list was not shown"
        shown = [history.get_option_at_index(i).id for i in range(history.option_count)]
        assert shown == ["W1AW-1", "WS1EC-15"], shown
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
        history = screen.query_one("#connect-history", OptionList)
        shown = [history.get_option_at_index(i).id for i in range(history.option_count)]
        assert shown == ["WS1EC-7", "WS1EC-15"], shown
    station.close()


@pytest.mark.asyncio
async def test_delete_forgets_a_row_and_it_stays_forgotten(tmp_path):
    """The explicit ask: rows you can delete."""
    app, ta, tb, station = await _app()
    _fresh_book(app, tmp_path)
    app.addressbook.record_attempt("WS1EC-15")
    app.addressbook.record_attempt("W1AW-1")
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open_connect(app, pilot)
        await pilot.press("down")
        await pilot.pause()
        history = screen.query_one("#connect-history", OptionList)
        assert history.has_focus, "Down did not move into the history list"
        await pilot.press("delete")
        await pilot.pause()
        shown = [history.get_option_at_index(i).id for i in range(history.option_count)]
        assert shown == ["WS1EC-15"], shown
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
    this feature -- not a blank hole where a list will one day be."""
    app, ta, tb, station = await _app()
    _fresh_book(app, tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open_connect(app, pilot)
        assert not screen.query_one("#connect-history", OptionList).display
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
    """Arrowing onto a row loads its saved script into the box -- that is how
    an operator finds out one is even there, short of remembering it."""
    app, ta, tb, station = await _app()
    book = _fresh_book(app, tmp_path)
    book.record_attempt("WS1EC-7", script="CLYDE\nMYPASS")
    book.record_attempt("W1AW-1")  # no script -- the preview must clear too
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open_connect(app, pilot)
        screen.action_into_list()  # highlights the first (most recent) row: W1AW-1
        await pilot.pause()
        assert screen.query_one("#connect-script", TextArea).text == ""

        await pilot.press("down")  # onto WS1EC-7
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
        screen.action_into_list()
        await pilot.pause()
        await pilot.press("enter")
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

