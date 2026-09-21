"""Loopback coverage for passive watched-callsign notification handoff."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams  # noqa: E402
from kissterm.ax25.frame import AX25Frame, UType  # noqa: E402
from kissterm.config import Config  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402


MYCALL = AX25Address.parse("N1ABC-1")


async def _mounted_app(config: Config):
    tx, rx = loopback_pair()
    await tx.open()
    await rx.open()
    station = AX25Station(MYCALL, tx, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    return KissTermApp(config, station), tx, rx, station


@pytest.mark.asyncio
async def test_watched_callsigns_are_default_disabled_then_use_the_existing_receive_seam():
    """Frames reach the one app fan-out; alerts never create a send path."""
    config = Config(mycall=str(MYCALL))
    app, tx, rx, station = await _mounted_app(config)
    in_app: list[tuple[str, dict]] = []
    desktop: list[tuple[str, str]] = []
    app.notify = lambda message, **kwargs: in_app.append((message, kwargs))
    app._notify_watched_desktop = lambda title, body: desktop.append((title, body))
    path = AX25Path(
        AX25Address.parse("APRS"),
        AX25Address.parse("OTHER-1"),
        (AX25Address.parse("w1aw-2"),),
    )

    async with app.run_test(size=(100, 32)) as pilot:
        await rx.send_frame(AX25Frame.u_frame(path, UType.UI, info=b"received"))
        await asyncio.sleep(0.05)
        await pilot.pause()
        assert in_app == []
        assert desktop == []
        assert tx.sent == []

        config.watched_callsigns.enabled = True
        config.watched_callsigns.callsigns = ["W1AW-2"]
        config.watched_callsigns.cooldown_minutes = 1
        config.watched_callsigns.hourly_cap = 2
        config.watched_callsigns.active_suppression_seconds = 0
        app.apply_runtime_settings()

        await rx.send_frame(AX25Frame.u_frame(path, UType.UI, info=b"received again"))
        await asyncio.sleep(0.05)
        await pilot.pause()

        assert len(in_app) == 1
        assert "Watched callsign claim: W1AW-2" in in_app[0][0]
        assert "not authenticated identity" in in_app[0][0]
        assert desktop == [("Watched callsign claim: W1AW-2", "Claim carried in a received AX.25 frame; not authenticated identity.")]
        assert tx.sent == []
    station.close()
