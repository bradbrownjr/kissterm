"""The deliberate APRS object composer sends one strict UI frame, or none.

This is intentionally a pilot test instead of only testing the encoder: it
exercises the operator-facing button/key, the shared symbol picker, the
closed-gate auto-arm rule, and the configured APRS digipeater path together.
"""

from __future__ import annotations

import asyncio
import logging
import re

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402
from textual.widgets import Input, Select  # noqa: E402

from kissterm import aprs  # noqa: E402
from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from tests.pilot._wait import wait_for  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402


MYCALL = AX25Address.parse("N1ABC-1")


async def _app():
    transport, peer = loopback_pair()
    await transport.open()
    await peer.open()
    config = Config(mycall=str(MYCALL))
    config.log_sessions = False
    config.aprs.path = "WIDE1-1"
    config.aprs.latitude = 41.7
    config.aprs.longitude = -72.7
    station = AX25Station(MYCALL, transport, LinkParams())
    return KissTermApp(config, station), station, transport


@pytest.mark.asyncio
async def test_object_composer_sends_its_own_position_and_arms_tx(caplog):
    app, station, transport = await _app()
    caplog.set_level(logging.DEBUG, logger="kissterm.ui.app")
    async with app.run_test(size=(120, 44)) as pilot:
        assert app.gate.enabled is False
        app.action_show_tab("aprs")
        await pilot.pause()
        app.action_aprs_object()
        for _ in range(20):
            if list(app.screen.query("#aprs-object-name")):
                break
            await asyncio.sleep(0.05)
        await pilot.pause()

        app.screen.query_one("#aprs-object-name", Input).value = "SHELTER"
        app.screen.query_one("#aprs-object-latitude", Input).value = "42.1"
        app.screen.query_one("#aprs-object-longitude", Input).value = "-71.2"
        app.screen.query_one("#aprs-object-symbol", Select).value = "/+"
        app.screen.query_one("#aprs-object-comment", Input).value = "Red Cross"
        await pilot.pause()
        await pilot.click("#aprs-object-send")
        for _ in range(20):
            if transport.sent:
                break
            await asyncio.sleep(0.05)

        assert app.gate.enabled is True
        assert len(transport.sent) == 1
        frame = transport.sent[0]
        assert str(frame.path.source) == "N1ABC-1"
        assert str(frame.path.destination) == "APRS"
        assert [str(via) for via in frame.path.repeaters] == ["WIDE1-1"]
        packet = aprs.parse_packet(frame)
        assert packet.kind == "object"
        assert packet.data.name == "SHELTER"
        assert packet.data.alive is True
        assert packet.data.position.latitude == pytest.approx(42.1)
        assert packet.data.position.longitude == pytest.approx(-71.2)
        assert packet.data.position.comment == "Red Cross"
        records = [
            record.message
            for record in caplog.records
            if record.name == "kissterm.ui.app"
            and record.message.startswith("APRS object transmission accepted:")
        ]
        assert len(records) == 1
        assert records[0].startswith("APRS object transmission accepted: N1ABC-1>APRS,WIDE1-1:;SHELTER  *")
        assert re.search(r";SHELTER  \*\d{6}z4206\.00N/07112\.00W\+Red Cross$", records[0])
    station.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "expected_via"),
    [
        ("network", ["WIDE1-1"]),
        ("rf_only", ["WIDE1-1", "RFONLY"]),
        ("direct", []),
    ],
)
async def test_object_scope_controls_its_rf_distribution(scope, expected_via):
    """An exercise object can be local without changing normal beacon paths."""
    app, station, transport = await _app()
    async with app.run_test(size=(120, 44)) as pilot:
        app.action_show_tab("aprs")
        await pilot.pause()
        app.action_aprs_object()
        # Wait for the Select's own label, not just the dialog: setting a
        # Select's value before it has composed raised NoMatches('#label')
        # under parallel load.
        await wait_for(
            lambda: app.screen.query_one("#aprs-object-scope", Select).query_one("#label"),
            "the object dialog to finish mounting",
        )
        app.screen.query_one("#aprs-object-name", Input).value = "EXERCISE"
        app.screen.query_one("#aprs-object-scope", Select).value = scope
        await pilot.pause()
        # The primary composer test above covers the real button. Calling the
        # handler here keeps this distribution matrix independent of modal
        # viewport height at the smallest supported test terminal.
        app.screen._send_object()
        await wait_for(lambda: transport.sent, "the object to be transmitted")

        assert [str(digi) for digi in transport.sent[0].path.repeaters] == expected_via
    station.close()


@pytest.mark.asyncio
async def test_object_composer_cancel_never_transmits():
    app, station, transport = await _app()
    async with app.run_test(size=(120, 44)) as pilot:
        app.action_show_tab("aprs")
        await pilot.pause()
        app.action_aprs_object()
        for _ in range(20):
            if list(app.screen.query("#aprs-object-name")):
                break
            await asyncio.sleep(0.05)
        await pilot.press("escape")
        await asyncio.sleep(0.1)
        assert transport.sent == []
        assert app.gate.enabled is False
    station.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "reference", "latitude", "longitude"),
    [
        # A grid names an area; the documented conversion uses its centre.
        ("grid", "FN31pr", 41.7292, -72.7083),
        ("mgrs", "15T WG 00000 49776", 42.0, -93.0),
        ("utm", "31 N 500000 4649776.22482", 42.0, 3.0),
    ],
)
async def test_object_composer_converts_grid_references_to_aprs_coordinates(
    mode, reference, latitude, longitude,
):
    app, station, transport = await _app()
    async with app.run_test(size=(120, 44)) as pilot:
        app.action_show_tab("aprs")
        await pilot.pause()
        app.action_aprs_object()
        await asyncio.sleep(0.05)
        await pilot.pause()
        app.screen.query_one("#aprs-object-name", Input).value = "SHELTER"
        app.screen.query_one("#aprs-object-coordinate-format", Select).value = mode
        app.screen.query_one("#aprs-object-reference", Input).value = reference
        await pilot.click("#aprs-object-send")
        for _ in range(20):
            if transport.sent:
                break
            await asyncio.sleep(0.05)
        packet = aprs.parse_packet(transport.sent[0])
        assert packet.data.position.latitude == pytest.approx(latitude, abs=0.02)
        assert packet.data.position.longitude == pytest.approx(longitude, abs=0.02)
    station.close()
