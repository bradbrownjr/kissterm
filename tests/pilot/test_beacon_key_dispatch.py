"""The two beacons are two commands, not one key with two meanings.

Session > Send beacon sends one BTEXT beacon now, on any tab (see
`test_beacon_wiring.py` for that half in full). APRS > Position beacon
toggles `config.aprs.enabled`, the quick-access equivalent of the Settings
checkbox plus Save. APRS > Send position sends one position report now
without changing that setting.

They shared Ctrl+Shift+B, dispatched by active tab, until the key standard
(docs/ROADMAP.md P0.2) removed every Ctrl+Shift binding: an ordinary
terminal delivers it as Ctrl+B, which is tmux's prefix. Menu commands have
no such collision and say which beacon they are.
"""

from __future__ import annotations

import asyncio

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config, load_config  # noqa: E402
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


@pytest.mark.asyncio
async def test_on_the_terminal_pane_it_still_sends_one_btext_beacon():
    """Provably unchanged: identical outcome to calling the BTEXT beaconer
    directly, whether or not the key has become context-aware elsewhere."""
    config = Config(mycall=str(MYCALL))
    config.tx_armed_at_start = True
    config.beacon.enabled = True
    config.beacon.text = "N1ABC test"
    app, station, ta = await _app()
    app.config = config
    app.beaconer.config = config.beacon
    app.gate.set(True)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        assert app.query_one("#main-tabs").active == "terminal"
        app.action_beacon_now()
        await pilot.pause()
        await asyncio.sleep(0.1)
        assert len(ta.sent) == 1
        assert app.aprs_beaconer.running is False
    station.close()


@pytest.mark.asyncio
async def test_the_position_beacon_command_toggles_aprs_enabled_without_sending():
    app, station, ta = await _app(tx_armed_at_start=True)
    app.config.aprs.latitude = 41.7
    app.config.aprs.longitude = -72.7
    async with app.run_test(size=(110, 32)) as pilot:
        app.action_show_tab("aprs")
        await pilot.pause()
        assert app.config.aprs.enabled is False

        app.action_toggle_aprs_beacon()
        await pilot.pause()
        await asyncio.sleep(0.15)
        assert app.config.aprs.enabled is True
        assert app.aprs_beaconer.running is True
        assert ta.sent == [], "the toggle itself must never transmit"

        app.action_toggle_aprs_beacon()
        await pilot.pause()
        await asyncio.sleep(0.15)
        assert app.config.aprs.enabled is False
        assert app.aprs_beaconer.running is False
    station.close()


@pytest.mark.asyncio
async def test_enabling_aprs_this_way_disables_a_running_btext_timer():
    config = Config(mycall=str(MYCALL))
    config.tx_armed_at_start = True
    config.beacon.enabled = True
    config.beacon.text = "N1ABC test"
    config.aprs.latitude = 41.7
    config.aprs.longitude = -72.7
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    station = AX25Station(MYCALL, ta, LinkParams())
    app = KissTermApp(config, station)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.15)
        assert app.beaconer.running is True

        app.action_show_tab("aprs")
        await pilot.pause()
        app.action_toggle_aprs_beacon()
        await pilot.pause()
        await asyncio.sleep(0.15)

        assert app.config.aprs.enabled is True
        assert app.config.beacon.enabled is False
        assert app.aprs_beaconer.running is True
        assert app.beaconer.running is False
    station.close()


@pytest.mark.asyncio
async def test_the_toggle_never_arms_a_closed_transmit_gate():
    """AGENTS.md: a command with no confirmation and no named target must
    never arm the gate -- this is architecturally the same case as the
    manual BTEXT beacon, just for the timer instead of a one-shot send."""
    app, station, ta = await _app()  # tx_armed_at_start defaults False
    app.config.aprs.latitude = 41.7
    app.config.aprs.longitude = -72.7
    async with app.run_test(size=(110, 32)) as pilot:
        app.action_show_tab("aprs")
        await pilot.pause()
        assert app.gate.enabled is False

        app.action_toggle_aprs_beacon()
        await pilot.pause()
        await asyncio.sleep(0.15)

        assert app.config.aprs.enabled is True
        assert app.gate.enabled is False, "the toggle must not arm the gate"
        assert ta.sent == []
    station.close()


@pytest.mark.asyncio
async def test_send_position_sends_one_position_and_arms_tx_without_starting_the_timer():
    """A deliberate position report is not unattended beaconing.

    It must work with periodic APRS beaconing off, use the configured APRS
    path, and leave the timer off afterwards.  Starting with TX closed proves
    the action, rather than test setup, is what armed it.
    """
    app, station, ta = await _app()
    app.config.aprs.latitude = 41.7
    app.config.aprs.longitude = -72.7
    app.config.aprs.path = "WIDE1-1"
    async with app.run_test(size=(110, 32)) as pilot:
        app.action_show_tab("aprs")
        await pilot.pause()
        await pilot.pause()
        assert app.gate.enabled is False
        assert app.config.aprs.enabled is False

        app.action_aprs_beacon_now()
        await asyncio.sleep(0.15)

        assert app.gate.enabled is True
        assert app.config.aprs.enabled is False
        assert app.aprs_beaconer.running is False
        assert len(ta.sent) == 1
        frame = ta.sent[0]
        assert str(frame.path.destination) == "APRS"
        assert [str(repeater) for repeater in frame.path.repeaters] == ["WIDE1-1"]
        assert str(frame.path.source) == "N1ABC-1"
    station.close()


@pytest.mark.asyncio
async def test_the_toggle_persists_across_a_simulated_restart():
    app, station, ta = await _app(tx_armed_at_start=True)
    app.config.aprs.latitude = 41.7
    app.config.aprs.longitude = -72.7
    async with app.run_test(size=(110, 32)) as pilot:
        app.action_show_tab("aprs")
        await pilot.pause()
        app.action_toggle_aprs_beacon()
        await pilot.pause()
        await asyncio.sleep(0.15)
        assert app.config.aprs.enabled is True
    station.close()

    reloaded = load_config()
    assert reloaded.aprs.enabled is True


@pytest.mark.asyncio
async def test_the_beacon_command_works_from_any_tab():
    """It is a menu command an operator chose by name, not a key that might
    have been pressed by accident on a tab where it means nothing -- which
    is what the old per-tab dispatch had to guard against."""
    config = Config(mycall=str(MYCALL))
    config.tx_armed_at_start = True
    config.beacon.enabled = True
    config.beacon.text = "N1ABC test"
    app, station, ta = await _app()
    app.config = config
    app.beaconer.config = config.beacon
    app.gate.set(True)
    async with app.run_test(size=(110, 32)) as pilot:
        app.action_show_tab("monitor")
        await pilot.pause()
        app.action_beacon_now()
        await pilot.pause()
        await asyncio.sleep(0.1)
        assert len(ta.sent) == 1
        assert app.aprs_beaconer.running is False
    station.close()
