"""The APRS beacon works; this is about whether the app turns it on --
`tests/unit/test_aprs_beacon.py` proves `AprsBeaconer` transmits, refuses,
and clamps. Mirrors `test_beacon_wiring.py` exactly, one config table over.
"""

from __future__ import annotations

import asyncio

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.terminal_pane import TerminalPane  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")


def _plain(widget) -> str:
    from textual.geometry import Region

    # `outer_size`, not `size`: the latter is the CONTENT box while
    # `render_lines` paints the padded/bordered one, so a widget with
    # horizontal padding silently loses its right-hand edge here. See
    # `tests/pilot/test_terminal_ux.py::_plain`.
    size = widget.outer_size
    region = Region(0, 0, size.width or 200, size.height or 5)
    return "\n".join(strip.text for strip in widget.render_lines(region))


async def _app(**aprs):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = Config(mycall=str(MYCALL))
    config.log_sessions = False
    for key, value in aprs.items():
        setattr(config.aprs, key, value)
    config.tx_armed_at_start = True
    station = AX25Station(MYCALL, ta, LinkParams())
    return KissTermApp(config, station), station, ta


@pytest.mark.asyncio
async def test_a_fresh_install_arms_nothing():
    app, station, ta = await _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.1)
        assert not app.aprs_beaconer.running
        assert ta.sent == []
    station.close()


@pytest.mark.asyncio
async def test_an_enabled_beacon_is_armed_on_mount_and_shown_in_the_status_bar():
    app, station, _ = await _app(enabled=True, latitude=41.7, longitude=-72.7)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.15)
        assert app.aprs_beaconer.running
        app._refresh_status()
        await pilot.pause()
        rendered = _plain(app.query_one("#status-bar"))
        assert "APRS BEACON" in rendered, rendered
    station.close()


@pytest.mark.asyncio
async def test_enabled_but_no_position_arms_nothing_and_says_why():
    app, station, ta = await _app(enabled=True)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.15)
        assert not app.aprs_beaconer.running
        assert ta.sent == []
        assert "no position set" in app.aprs_beaconer.problem()
    station.close()


@pytest.mark.asyncio
async def test_reapplying_settings_does_not_leave_two_beacons_running():
    app, station, _ = await _app(enabled=True, latitude=41.7, longitude=-72.7)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.15)
        first = app.aprs_beaconer._task
        app.apply_runtime_settings()
        await asyncio.sleep(0.15)
        assert app.aprs_beaconer.running
        assert app.aprs_beaconer._task is not first, "old task was not replaced"
        assert first.cancelled() or first.done(), "old beacon task still alive"
    station.close()


@pytest.mark.asyncio
async def test_turning_it_off_in_settings_disarms_it():
    app, station, _ = await _app(enabled=True, latitude=41.7, longitude=-72.7)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.15)
        assert app.aprs_beaconer.running
        app.config.aprs.enabled = False
        app.apply_runtime_settings()
        await asyncio.sleep(0.15)
        assert not app.aprs_beaconer.running
    station.close()


@pytest.mark.asyncio
async def test_a_beacon_that_fires_is_visible_in_the_terminal_pane():
    app, station, ta = await _app(enabled=True, latitude=41.7, longitude=-72.7)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        assert await app.aprs_beaconer.send_once() is True
        await pilot.pause()
        log = app.query_one(TerminalPane).query_one("#session-log")
        rendered = "\n".join(str(line) for line in log.lines)
        assert "APRS position beacon sent" in rendered, rendered
        assert len(ta.sent) == 1
    station.close()


@pytest.mark.asyncio
async def test_the_two_beacons_are_independent():
    """Enabling one must not arm the other -- separate config tables,
    separate timers, per AGENTS.md's beaconing rules."""
    app, station, ta = await _app(enabled=True, latitude=41.7, longitude=-72.7)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.15)
        assert app.aprs_beaconer.running
        assert not app.beaconer.running
    station.close()
