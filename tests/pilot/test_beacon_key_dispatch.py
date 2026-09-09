"""Ctrl+Shift+B is context-aware by active tab -- same dispatch shape as
Ctrl+G (`action_toggle_contacts`). Terminal pane: unchanged, sends one
BTEXT beacon immediately (see `test_beacon_wiring.py` for that half in
full). APRS pane: toggles `config.aprs.enabled`, the quick-access
equivalent of the Settings checkbox plus Save.
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
async def test_on_the_aprs_pane_it_toggles_aprs_enabled_instead_of_sending():
    app, station, ta = await _app(tx_armed_at_start=True)
    app.config.aprs.latitude = 41.7
    app.config.aprs.longitude = -72.7
    async with app.run_test(size=(110, 32)) as pilot:
        app.action_show_tab("aprs")
        await pilot.pause()
        assert app.config.aprs.enabled is False

        app.action_beacon_now()
        await pilot.pause()
        await asyncio.sleep(0.15)
        assert app.config.aprs.enabled is True
        assert app.aprs_beaconer.running is True
        assert ta.sent == [], "the toggle itself must never transmit"

        app.action_beacon_now()
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
        app.action_beacon_now()
        await pilot.pause()
        await asyncio.sleep(0.15)

        assert app.config.aprs.enabled is True
        assert app.config.beacon.enabled is False
        assert app.aprs_beaconer.running is True
        assert app.beaconer.running is False
    station.close()


@pytest.mark.asyncio
async def test_the_toggle_never_arms_a_closed_transmit_gate():
    """AGENTS.md: a bare keystroke with no confirmation and no named
    target must never arm the gate -- this is architecturally the same
    case as the manual BTEXT beacon, just for the timer instead of a
    one-shot send."""
    app, station, ta = await _app()  # tx_armed_at_start defaults False
    app.config.aprs.latitude = 41.7
    app.config.aprs.longitude = -72.7
    async with app.run_test(size=(110, 32)) as pilot:
        app.action_show_tab("aprs")
        await pilot.pause()
        assert app.gate.enabled is False

        app.action_beacon_now()
        await pilot.pause()
        await asyncio.sleep(0.15)

        assert app.config.aprs.enabled is True
        assert app.gate.enabled is False, "the toggle must not arm the gate"
        assert ta.sent == []
    station.close()


@pytest.mark.asyncio
async def test_the_toggle_persists_across_a_simulated_restart():
    app, station, ta = await _app(tx_armed_at_start=True)
    app.config.aprs.latitude = 41.7
    app.config.aprs.longitude = -72.7
    async with app.run_test(size=(110, 32)) as pilot:
        app.action_show_tab("aprs")
        await pilot.pause()
        app.action_beacon_now()
        await pilot.pause()
        await asyncio.sleep(0.15)
        assert app.config.aprs.enabled is True
    station.close()

    reloaded = load_config()
    assert reloaded.aprs.enabled is True


@pytest.mark.asyncio
async def test_btext_send_still_works_from_a_tab_that_is_neither_terminal_nor_aprs():
    """Only the APRS pane gets special dispatch. BTEXT's manual send was
    never tab-scoped before this key became context-aware, and stays that
    way everywhere except APRS -- matching the approved plan's "on any
    other tab: unchanged" wording, not a new per-tab restriction."""
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
