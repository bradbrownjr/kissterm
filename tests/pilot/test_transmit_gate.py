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
