"""The guarantee: a freshly launched kissterm cannot key a radio.

`tests/unit/test_tx_gate.py` proves the interlock works at the transport. This
file proves the app actually closes it -- which is the half an operator is
trusting when they read "kissterm cannot transmit until you press Ctrl+T".
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.terminal_pane import TerminalPane  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")


def _plain(widget) -> str:
    from textual.geometry import Region

    region = Region(0, 0, widget.size.width or 200, widget.size.height or 5)
    return "\n".join(strip.text for strip in widget.render_lines(region))


async def _app(**kw):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = Config(mycall=str(MYCALL))
    config.log_sessions = False
    for key, value in kw.items():
        setattr(config, key, value)
    station = AX25Station(MYCALL, ta, LinkParams(t1=0.2, t2=0.05, t3=5.0))
    return KissTermApp(config, station), station, ta


@pytest.mark.asyncio
async def test_a_fresh_launch_cannot_transmit():
    app, station, ta = await _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        assert app.gate.enabled is False
        assert station.transport.gate is app.gate, (
            "the app did not install its gate on the transport"
        )
    station.close()


@pytest.mark.asyncio
async def test_tx_off_is_always_on_screen():
    """"Why is nothing happening?" must be answerable without opening a menu."""
    app, station, _ = await _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        assert "TX OFF" in _plain(app.query_one("#status-bar"))
        await pilot.press("ctrl+t")
        await pilot.pause()
        app._refresh_status()
        await pilot.pause()
        assert "TX OFF" not in _plain(app.query_one("#status-bar"))
    station.close()


@pytest.mark.asyncio
async def test_ctrl_t_toggles_and_the_send_line_follows_it():
    app, station, ta = await _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        pane.query_one("#session-input").value = "L"
        await pane.send_line("L")
        assert ta.sent == []
        # The text stays in the field: clearing it would look exactly like a
        # successful send, which is the worst feedback for "nothing went out".
        assert pane.query_one("#session-input").value == "L"

        await pilot.press("ctrl+t")
        await pilot.pause()
        assert app.gate.enabled is True
    station.close()


@pytest.mark.asyncio
async def test_a_confirmed_connect_arms_the_gate_instead_of_refusing():
    """The gate stops transmissions the operator did NOT ask for. Naming a
    station in the connect dialog and confirming it is asking, in the most
    explicit form the UI has -- and refusing it was a dead end, since the one
    thing the operator wanted was the one thing the refusal would not do."""
    app, station, ta = await _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        assert app.gate.enabled is False
        await pilot.press("ctrl+n")
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.pause()
        from kissterm.ui.dialogs import ConnectScreen

        assert isinstance(app.screen, ConnectScreen), (
            "the connect dialog did not open"
        )
        for key in "WS1EC-7":
            await pilot.press(key if key != "-" else "minus")
        await pilot.press("enter")
        await pilot.pause()
        await asyncio.sleep(0.3)
        assert app.gate.enabled is True, "a confirmed connect did not arm the gate"
        assert ta.sent, "the SABM never went out"
    station.close()


@pytest.mark.asyncio
async def test_arming_for_a_connect_is_never_silent():
    """Auto-arming is only defensible while it stays visible: "did this thing
    start transmitting behind my back?" has to be answerable from the screen."""
    app, station, ta = await _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        app._arm_for("connect to WS1EC-7")
        await pilot.pause()
        log = app.query_one(TerminalPane).query_one("#session-log")
        text = "\n".join(str(line) for line in log.lines)
        assert "Transmit enabled automatically" in text, (
            "the gate opened with nothing said about it in the log"
        )
        assert "TX OFF" not in _plain(app.query_one("#status-bar")), (
            "the status bar still claims transmit is off"
        )
    station.close()


@pytest.mark.asyncio
async def test_cancelling_the_connect_dialog_leaves_the_gate_shut():
    """Arming follows the CONFIRMATION, not the keystroke that opens the box.
    Escaping out of the dialog is the operator changing their mind."""
    app, station, ta = await _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+n")
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.press("escape")
        await pilot.pause()
        await asyncio.sleep(0.1)
        assert app.gate.enabled is False, "cancelling the dialog armed the gate"
        assert ta.sent == []
    station.close()


@pytest.mark.asyncio
async def test_a_configured_beacon_stays_silent_until_tx_is_enabled():
    app, station, ta = await _app(tx_armed_at_start=False)
    app.config.beacon.enabled = True
    app.config.beacon.text = "N1ABC test"
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.15)
        assert not app.beaconer.running
        assert app.beaconer.problem() == "transmit is disabled"

        await pilot.press("ctrl+t")
        await pilot.pause()
        await asyncio.sleep(0.2)
        assert app.beaconer.running, "Ctrl+T did not arm the configured beacon"
    station.close()


@pytest.mark.asyncio
async def test_beacon_now_reports_honestly_when_transmit_is_off():
    """A blocked frame must never be reported as a beacon that went out."""
    app, station, ta = await _app(tx_armed_at_start=False)
    app.config.beacon.enabled = True
    app.config.beacon.text = "N1ABC test"
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        assert await app.beaconer.send_once(force=True) is False
        assert ta.sent == []
        log = app.query_one(TerminalPane).query_one("#session-log")
        assert "Beacon sent" not in "\n".join(str(line) for line in log.lines)
    station.close()


@pytest.mark.asyncio
async def test_ctrl_shift_b_sends_one_beacon_even_with_the_timer_off():
    """A manual beacon is not the timer. Refusing one because the periodic
    beacon is switched off would answer a question nobody asked."""
    app, station, ta = await _app(tx_armed_at_start=True)
    app.config.beacon.enabled = False
    app.config.beacon.text = "N1ABC test"
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        assert not app.beaconer.running
        await pilot.press("ctrl+shift+b")
        await pilot.pause()
        await asyncio.sleep(0.2)
        assert len(ta.sent) == 1, "Ctrl+Shift+B did not send a beacon"
        assert not app.beaconer.running, "Ctrl+Shift+B must not start the timer"
    station.close()


@pytest.mark.asyncio
async def test_plain_ctrl_b_still_beacons_on_a_legacy_terminal():
    """The beacon moved to Ctrl+Shift+B to stop tmux (prefix Ctrl+B) from
    eating it, but a terminal without the enhanced keyboard protocol cannot
    tell the two apart -- it sends 0x02 for both. Dropping the plain binding
    would leave those terminals with no way to beacon at all, since there is
    no slash command for it. Under a multiplexer this binding is unreachable
    anyway, which is the whole point.
    """
    app, station, ta = await _app(tx_armed_at_start=True)
    app.config.beacon.enabled = False
    app.config.beacon.text = "N1ABC test"
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+b")
        await pilot.pause()
        await asyncio.sleep(0.2)
        assert len(ta.sent) == 1, "the legacy Ctrl+B fallback did not beacon"
    station.close()


@pytest.mark.asyncio
async def test_ctrl_shift_b_still_refuses_with_no_text():
    app, station, ta = await _app(tx_armed_at_start=True)
    app.config.beacon.text = ""
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+shift+b")
        await pilot.pause()
        await asyncio.sleep(0.15)
        assert ta.sent == []
    station.close()


@pytest.mark.asyncio
async def test_an_unattended_station_can_arm_at_startup():
    app, station, _ = await _app(tx_armed_at_start=True)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        assert app.gate.enabled is True
        assert "TX OFF" not in _plain(app.query_one("#status-bar"))
    station.close()


@pytest.mark.asyncio
async def test_a_dead_tnc_link_is_not_reported_as_a_dead_rf_path():
    """From a real on-air attempt: the socket to the TNC dropped mid-connect,
    every SABM after that was refused by the transport, and all the operator
    saw was "no connection to WS1EC-15" -- a message pointing at the antenna
    when the fault was a TCP socket in the next room."""
    from kissterm.transport.base import TransportState

    app, station, ta = await _app(tx_armed_at_start=True)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        ta.state = TransportState.OPENING  # what a reconnecting socket looks like
        app._refresh_status()
        await pilot.pause()

        status = _plain(app.query_one("#status-bar"))
        assert "RECONNECTING" in status, (
            f"the status bar still showed a healthy transport: {status!r}"
        )

        await pilot.press("ctrl+n")
        await pilot.pause()
        await asyncio.sleep(0.1)
        for key in "WS1EC-7":
            await pilot.press(key if key != "-" else "minus")
        await pilot.press("enter")
        await pilot.pause()
        await asyncio.sleep(0.3)

        log = app.query_one(TerminalPane).query_one("#session-log")
        text = "\n".join(str(line) for line in log.lines)
        assert "not an RF problem" in text, text
        assert ta.sent == [], "SABMs were sent into a transport that was down"
    station.close()


@pytest.mark.asyncio
async def test_ctrl_d_cancels_a_stuck_connect_instead_of_saying_not_connected():
    """From a real report: typing the wrong station, then wanting out before
    N2 retries expire. Before this, Ctrl+D checked only `self.link`, which is
    not bound until a connect SUCCEEDS -- so a stuck attempt made Ctrl+D
    report "Not connected" (true, useless) and the operator had to wait out
    the whole retry budget while the radio kept keying up on its own."""
    app, station, ta = await _app(tx_armed_at_start=True)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+n")
        await pilot.pause()
        await asyncio.sleep(0.1)
        for key in "WS1EC-7":
            await pilot.press(key if key != "-" else "minus")
        await pilot.press("enter")
        await pilot.pause()
        await asyncio.sleep(0.1)  # let the first SABM go out

        sent_before_cancel = len(ta.sent)
        assert sent_before_cancel >= 1, "the connect attempt never sent anything"

        await pilot.press("ctrl+d")
        await pilot.pause()
        await asyncio.sleep(0.05)

        assert app.link is None, "there was never a UA -- nothing came up to bind"
        assert app._connecting == {}, "the cancelled attempt is still tracked as in-flight"

        # If cancellation only stopped the *UI* and not the retry timer, more
        # SABMs would still be queued to go out; wait past where the next
        # retry (T1=0.2s) would have fired and confirm none did.
        await asyncio.sleep(0.3)
        assert len(ta.sent) == sent_before_cancel, "a retry fired after cancellation"

        log = app.query_one(TerminalPane).query_one("#session-log")
        text = "\n".join(str(line) for line in log.lines)
        assert "cancel" in text.lower(), text
        assert "No connection to" not in text, (
            "a cancelled attempt was reported as a timed-out one: " + text
        )
    station.close()


@pytest.mark.asyncio
async def test_ctrl_shift_d_disconnects_even_with_the_outgoing_box_focused():
    """From a real report: the Footer's Disconnect hint vanished and the
    keystroke stopped reaching `action_disconnect` once the outgoing-message
    box took focus -- which is true for nearly all of a live session.
    Textual's `Input` binds plain `Ctrl+D` to delete-character-right, and
    whichever binding is closer to the focused widget wins; `Ctrl+Shift+D` is
    not claimed by `Input` at all, so it must keep working regardless of
    focus. See the BINDINGS list in `kissterm/ui/app.py`."""
    from kissterm.ax25 import AX25Path

    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = Config(mycall=str(MYCALL), tx_armed_at_start=True)
    config.log_sessions = False
    peer = AX25Address.parse("WS1EC-7")
    station = AX25Station(MYCALL, ta, LinkParams(t1=0.2, t2=0.05, t3=5.0))
    peer_station = AX25Station(peer, tb, LinkParams(t1=0.2, t2=0.05, t3=5.0))
    app = KissTermApp(config, station)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await station.connect(AX25Path(peer, MYCALL), timeout=2.0)
        assert link is not None and link.connected
        app._bind_link(link)
        await pilot.pause()

        send_box = app.query_one(TerminalPane).query_one("#session-input")
        send_box.focus()
        await pilot.pause()
        assert send_box.has_focus, "the outgoing box must hold focus for this to prove anything"

        await pilot.press("ctrl+shift+d")
        await pilot.pause()
        await asyncio.sleep(0.3)

        assert not link.connected, "Ctrl+Shift+D did not reach action_disconnect"
    station.close()
    peer_station.close()


@pytest.mark.asyncio
async def test_sending_a_line_with_a_closed_gate_arms_it_instead_of_refusing():
    """The same "confirmed, targeted" reasoning `_arm_for` already applies to
    a confirmed Connect applies here: a line the operator typed, to a station
    they are already connected to, committed with Enter or Send. Refusing it
    with DISABLED_MESSAGE would be the identical dead end -- the one thing
    the operator just asked for is the one thing the refusal would not do."""
    from kissterm.ax25 import AX25Path

    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = Config(mycall=str(MYCALL), tx_armed_at_start=True)
    config.log_sessions = False
    peer = AX25Address.parse("WS1EC-7")
    station = AX25Station(MYCALL, ta, LinkParams(t1=0.2, t2=0.05, t3=5.0))
    peer_station = AX25Station(peer, tb, LinkParams(t1=0.2, t2=0.05, t3=5.0))
    app = KissTermApp(config, station)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await station.connect(AX25Path(peer, MYCALL), timeout=2.0)
        assert link is not None and link.connected
        app._bind_link(link)
        await pilot.pause()

        # A confirmed connect already armed the gate above; close it again --
        # the same as pressing Ctrl+T mid-session -- before proving Send
        # re-arms it rather than being refused by it.
        app.gate.set(False)
        pane = app.query_one(TerminalPane)
        await pane.send_line("hello there")
        await pilot.pause()

        assert app.gate.enabled is True, "sending a line did not re-arm a closed gate"
        assert ta.sent, "the line never reached the wire after arming"
        assert "Transmit enabled automatically" in "\n".join(
            str(line) for line in pane.query_one("#session-log").lines
        )
    station.close()
    peer_station.close()


@pytest.mark.asyncio
async def test_sending_a_line_while_disconnected_never_touches_the_gate():
    """Arming for a send that has nothing to go out on would open the gate
    for nothing -- `send_line` checks `link.connected` before it ever looks
    at the gate, the same guard `AprsPane._send_compose` applies against
    `self.app.station`."""
    app, station, ta = await _app(tx_armed_at_start=False)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        await pane.send_line("hello")
        await pilot.pause()
        assert app.gate.enabled is False, "a send with nothing connected armed the gate anyway"
        assert ta.sent == []
    station.close()
