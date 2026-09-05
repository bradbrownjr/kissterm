"""The beacon works; this is about whether the app turns it on.

`tests/unit/test_beacon.py` proves `Beaconer` transmits, refuses, and clamps.
None of that is worth anything if the app never starts it, starts it twice, or
leaves it armed after the operator switched it off -- and each of those passes
every unit test in the suite.
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
    """The strips the terminal itself would draw.

    `#status-bar` holds a `rich.table.Table`, not a string, so `str(render())`
    does not contain the visible text -- see `tests/pilot/test_app_mounts.py`.
    """
    from textual.geometry import Region

    region = Region(0, 0, widget.size.width or 200, widget.size.height or 5)
    return "\n".join(strip.text for strip in widget.render_lines(region))


async def _app(**beacon):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = Config(mycall=str(MYCALL))
    config.log_sessions = False
    for key, value in beacon.items():
        setattr(config.beacon, key, value)
    station = AX25Station(MYCALL, ta, LinkParams())
    return KissTermApp(config, station), station, ta


@pytest.mark.asyncio
async def test_a_fresh_install_arms_nothing():
    app, station, ta = await _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.1)
        assert not app.beaconer.running
        assert ta.sent == []
    station.close()


@pytest.mark.asyncio
async def test_an_enabled_beacon_is_armed_on_mount_and_shown_in_the_status_bar():
    app, station, _ = await _app(enabled=True, text="N1ABC test")
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.15)
        assert app.beaconer.running
        # The bar repaints on a timer; the beacon is armed by a worker that
        # finishes after mount, so ask for the repaint rather than waiting a
        # second for one.
        app._refresh_status()
        await pilot.pause()
        rendered = _plain(app.query_one("#status-bar"))
        assert "BEACON" in rendered, rendered
    station.close()


@pytest.mark.asyncio
async def test_enabled_but_empty_text_arms_nothing_and_says_why():
    """`enabled` does not override having nothing to say."""
    app, station, ta = await _app(enabled=True, text="")
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.15)
        assert not app.beaconer.running
        assert ta.sent == []
        assert app.beaconer.problem() == "no beacon text is set"
    station.close()


@pytest.mark.asyncio
async def test_reapplying_settings_does_not_leave_two_beacons_running():
    """Save gets pressed repeatedly. The second press must not double the
    rate at which this station transmits."""
    app, station, _ = await _app(enabled=True, text="N1ABC test")
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.15)
        first = app.beaconer._task
        app.apply_runtime_settings()
        await asyncio.sleep(0.15)
        assert app.beaconer.running
        assert app.beaconer._task is not first, "old task was not replaced"
        assert first.cancelled() or first.done(), "old beacon task still alive"
    station.close()


@pytest.mark.asyncio
async def test_turning_it_off_in_settings_disarms_it():
    app, station, _ = await _app(enabled=True, text="N1ABC test")
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.15)
        assert app.beaconer.running
        app.config.beacon.enabled = False
        app.apply_runtime_settings()
        await asyncio.sleep(0.15)
        assert not app.beaconer.running
    station.close()


@pytest.mark.asyncio
async def test_a_beacon_that_fires_is_visible_in_the_terminal_pane():
    """A station that transmits without the operator being able to see that
    it did is what the whole opt-in exists to prevent."""
    app, station, ta = await _app(enabled=True, text="N1ABC test")
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        assert await app.beaconer.send_once() is True
        await pilot.pause()
        log = app.query_one(TerminalPane).query_one("#session-log")
        rendered = "\n".join(str(line) for line in log.lines)
        assert "Beacon sent to BEACON" in rendered, rendered
        assert len(ta.sent) == 1
    station.close()
