"""An APRS position beacon is unattended transmission, same as BTEXT --
`tests/unit/test_beacon.py`'s weighting applies here too: most of this is
about silence, and a beacon that transmits a placeholder position under the
operator's callsign is worse than one that fails to transmit at all.

Frames go through the loopback rather than a mock, so what is asserted is a
frame that actually encoded and decoded.
"""

from __future__ import annotations

import asyncio

from kissterm import _isolate

_isolate.isolate()

import pytest  # noqa: E402

from kissterm.aprs.parse import parse_packet  # noqa: E402
from kissterm.aprs_beacon import AprsBeaconer, MIN_INTERVAL_MINUTES  # noqa: E402
from kissterm.ax25.address import AX25Address  # noqa: E402
from kissterm.ax25.frame import PID_NO_LAYER3, UType  # noqa: E402
from kissterm.ax25.station import AX25Station  # noqa: E402
from kissterm.config import AprsConfig, Config, load_config, save_config  # noqa: E402

from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("W1AW-1")


async def _station():
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    return AX25Station(MYCALL, ta), ta, tb


def _config(**kw) -> AprsConfig:
    base = {
        "enabled": True,
        "latitude": 41.7,
        "longitude": -72.7,
        "symbol": "/>",
        "comment": "test",
        "beacon_interval_minutes": 30,
    }
    base.update(kw)
    return AprsConfig(**base)


# ---------------------------------------------------------------------------
# Refusing to transmit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_beacon_sends_nothing():
    station, ta, _ = await _station()
    beacon = AprsBeaconer(station, _config(enabled=False))
    assert beacon.problem() == "APRS beaconing is off"
    assert await beacon.send_once() is False
    assert ta.sent == []


@pytest.mark.asyncio
async def test_default_zero_zero_position_is_treated_as_unset():
    """0,0 is a real point (the Gulf of Guinea) and also exactly what a
    fresh `AprsConfig` defaults to -- transmitting it would put a placeholder
    position on the air under the operator's callsign."""
    station, ta, _ = await _station()
    beacon = AprsBeaconer(station, _config(latitude=0.0, longitude=0.0))
    assert "no position set" in beacon.problem()
    assert await beacon.send_once() is False
    assert ta.sent == []
    assert "no position set" in beacon.start()


@pytest.mark.asyncio
async def test_a_bad_symbol_is_reported_not_raised():
    station, _, _ = await _station()
    beacon = AprsBeaconer(station, _config(symbol="X"))
    assert "bad map symbol" in beacon.problem()
    assert await beacon.send_once() is False
    assert beacon.build_frame() is None


@pytest.mark.asyncio
async def test_a_bad_digipeater_path_is_reported_not_raised():
    station, _, _ = await _station()
    beacon = AprsBeaconer(station, _config(path="not a valid path!!"))
    assert "bad beacon path" in beacon.problem()
    assert await beacon.send_once() is False


@pytest.mark.asyncio
async def test_position_cleared_under_a_running_beaconer_stops_transmission():
    station, ta, _ = await _station()
    beacon = AprsBeaconer(station, _config())
    assert await beacon.send_once() is True
    beacon.config.latitude = 0.0
    beacon.config.longitude = 0.0
    assert await beacon.send_once() is False
    assert len(ta.sent) == 1


@pytest.mark.asyncio
async def test_live_position_is_asked_for_at_send_time_without_changing_config():
    station, _, _ = await _station()
    current = (42.1, -71.2)
    beacon = AprsBeaconer(station, _config(latitude=1.0, longitude=2.0), position_source=lambda: current)
    frame = beacon.build_frame()
    decoded = parse_packet(frame)
    assert round(decoded.data.latitude, 1) == 42.1
    assert round(decoded.data.longitude, 1) == -71.2
    assert (beacon.config.latitude, beacon.config.longitude) == (1.0, 2.0)


@pytest.mark.asyncio
async def test_configured_live_source_with_no_fix_never_falls_back_to_static_position():
    station, ta, _ = await _station()
    beacon = AprsBeaconer(station, _config(), position_source=lambda: None)
    assert beacon.problem() == "GPS has no fix"
    assert await beacon.send_once() is False
    assert ta.sent == []


@pytest.mark.asyncio
async def test_a_transport_failure_does_not_raise_into_the_caller():
    station, ta, _ = await _station()

    async def boom(frame, port=0):
        raise OSError("TNC went away")

    ta.send_frame = boom
    beacon = AprsBeaconer(station, _config())
    assert await beacon.send_once() is False
    assert beacon.sent_count == 0


# ---------------------------------------------------------------------------
# The frame that goes out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_beacon_is_a_ui_frame_from_us_to_aprs():
    station, ta, tb = await _station()
    seen = []
    tb.subscribe(lambda f, port=0: seen.append(f))
    beacon = AprsBeaconer(station, _config())
    assert await beacon.send_once() is True
    await asyncio.sleep(0.05)

    assert len(seen) == 1
    frame = seen[0]
    assert frame.kind == "U" and frame.utype is UType.UI
    assert frame.pid == PID_NO_LAYER3
    assert str(frame.path.source) == "W1AW-1"
    assert str(frame.path.destination) == "APRS"


@pytest.mark.asyncio
async def test_beacon_is_a_command_frame():
    """Every APRS beacon actually seen on the air is a command frame; there
    is no connection for it to be a response within."""
    station, _, _ = await _station()
    frame = AprsBeaconer(station, _config()).build_frame()
    assert frame is not None and frame.command


@pytest.mark.asyncio
async def test_digipeater_path_reaches_the_frame():
    station, _, _ = await _station()
    frame = AprsBeaconer(station, _config(path="W1XYZ-1,WIDE2-1")).build_frame()
    assert [str(r) for r in frame.path.repeaters] == ["W1XYZ-1", "WIDE2-1"]


@pytest.mark.asyncio
async def test_empty_path_means_direct():
    station, _, _ = await _station()
    frame = AprsBeaconer(station, _config(path="")).build_frame()
    assert frame.path.repeaters == ()


@pytest.mark.asyncio
async def test_the_transmitted_frame_decodes_back_to_the_same_position():
    """Round-trip through the real decoder, not just the encoder -- the
    wire format is where half the real bugs live."""
    station, _, _ = await _station()
    beacon = AprsBeaconer(station, _config(latitude=41.7, longitude=-72.7, comment="hi"))
    frame = beacon.build_frame()
    decoded = parse_packet(frame)
    assert decoded.kind == "position"
    assert decoded.data is not None
    assert round(decoded.data.latitude, 1) == 41.7
    assert round(decoded.data.longitude, 1) == -72.7
    assert decoded.data.comment == "hi"


# ---------------------------------------------------------------------------
# Winlink notify flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_winlink_check_appends_the_token_to_the_comment():
    station, _, _ = await _station()
    beacon = AprsBeaconer(station, _config(comment="hi", winlink_check=True))
    frame = beacon.build_frame()
    decoded = parse_packet(frame)
    assert decoded.data.comment == "hi WINLINK"


@pytest.mark.asyncio
async def test_winlink_check_off_leaves_the_comment_untouched():
    station, _, _ = await _station()
    beacon = AprsBeaconer(station, _config(comment="hi", winlink_check=False))
    frame = beacon.build_frame()
    decoded = parse_packet(frame)
    assert decoded.data.comment == "hi"


@pytest.mark.asyncio
async def test_winlink_token_alone_when_comment_is_empty():
    station, _, _ = await _station()
    beacon = AprsBeaconer(station, _config(comment="", winlink_check=True))
    frame = beacon.build_frame()
    decoded = parse_packet(frame)
    assert decoded.data.comment == "WINLINK"


@pytest.mark.asyncio
async def test_winlink_token_survives_truncation_of_a_long_comment():
    """The token must never be the thing that gets cut off -- reserve its
    room before truncating the operator's own comment, not after."""
    station, _, _ = await _station()
    beacon = AprsBeaconer(station, _config(comment="x" * 200, winlink_check=True))
    frame = beacon.build_frame()
    decoded = parse_packet(frame)
    assert decoded.data.comment.endswith("WINLINK")
    assert len(decoded.data.comment.encode("ascii")) <= 100


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------


def test_interval_floor_is_enforced_in_code_not_only_in_the_config_loader():
    beacon = AprsBeaconer(None, AprsConfig(beacon_interval_minutes=1))
    assert beacon.interval_seconds == MIN_INTERVAL_MINUTES * 60


def test_grid_square_and_winlink_check_round_trip_through_save_and_load(tmp_path):
    path = tmp_path / "config.toml"
    cfg = Config(mycall="W1AW-1")
    cfg.aprs = _config(grid_square="FN31pr", winlink_check=True)
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.aprs.grid_square == "FN31pr"
    assert loaded.aprs.winlink_check is True
    assert loaded.warnings == []


def test_config_loader_clamps_the_interval_and_says_so(tmp_path):
    path = tmp_path / "config.toml"
    cfg = Config(mycall="W1AW-1")
    cfg.aprs = _config(beacon_interval_minutes=2)
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.aprs.beacon_interval_minutes == MIN_INTERVAL_MINUTES
    assert any("minimum" in w for w in loaded.warnings)


@pytest.mark.asyncio
async def test_nothing_is_transmitted_at_start():
    station, ta, _ = await _station()
    beacon = AprsBeaconer(station, _config())
    assert beacon.start() == ""
    try:
        await asyncio.sleep(0.2)
        assert ta.sent == []
        assert beacon.sent_count == 0
    finally:
        await beacon.stop()


@pytest.mark.asyncio
async def test_the_timer_fires_after_one_interval(monkeypatch):
    """`monkeypatch.setattr` on the class, not a manual set-then-`del`: a
    `del` on a class attribute destroys the original `@property` object
    permanently for the rest of the process rather than reverting to it --
    order-dependent breakage that only failed to show up here because
    pytest happens to collect `tests/pilot/` before `tests/unit/`."""
    station, ta, _ = await _station()
    beacon = AprsBeaconer(station, _config())
    monkeypatch.setattr(type(beacon), "interval_seconds", property(lambda self: 0.05))
    try:
        assert beacon.start() == ""
        await asyncio.sleep(0.18)
        assert beacon.sent_count >= 2
        assert len(ta.sent) >= 2
    finally:
        await beacon.stop()


@pytest.mark.asyncio
async def test_start_is_idempotent_so_a_second_save_does_not_double_the_rate():
    station, _, _ = await _station()
    beacon = AprsBeaconer(station, _config())
    try:
        assert beacon.start() == ""
        first = beacon._task
        assert beacon.start() == ""
        assert beacon._task is first
    finally:
        await beacon.stop()


@pytest.mark.asyncio
async def test_stop_and_cancel_are_safe_when_never_started():
    station, _, _ = await _station()
    beacon = AprsBeaconer(station, _config())
    beacon.cancel()
    await beacon.stop()
    assert not beacon.running


@pytest.mark.asyncio
async def test_stop_disarms_it(monkeypatch):
    station, ta, _ = await _station()
    beacon = AprsBeaconer(station, _config())
    monkeypatch.setattr(type(beacon), "interval_seconds", property(lambda self: 0.05))
    assert beacon.start() == ""
    await asyncio.sleep(0.12)
    await beacon.stop()
    sent_at_stop = beacon.sent_count
    await asyncio.sleep(0.15)
    assert beacon.sent_count == sent_at_stop
    assert not beacon.running


@pytest.mark.asyncio
async def test_force_waives_only_the_timer_being_off():
    """A manual beacon is not the timer -- it must still refuse a genuinely
    bad configuration."""
    station, ta, _ = await _station()
    disabled = AprsBeaconer(station, _config(enabled=False))
    assert await disabled.send_once(force=True) is True
    assert len(ta.sent) == 1

    no_position = AprsBeaconer(station, _config(enabled=False, latitude=0.0, longitude=0.0))
    assert await no_position.send_once(force=True) is False
    assert len(ta.sent) == 1


@pytest.mark.asyncio
async def test_the_aprs_ssid_override_reaches_the_transmitted_frame():
    """A beacon from a car should say -9 even though connected-mode packet
    keeps running under the base call."""
    station, _ta, _tb = await _station()
    beacon = AprsBeaconer(station, _config(ssid="9"))
    frame = beacon.build_frame()
    assert str(frame.path.source) == f"{MYCALL.callsign}-9"


@pytest.mark.asyncio
async def test_no_aprs_ssid_leaves_the_station_callsign_alone():
    station, _ta, _tb = await _station()
    frame = AprsBeaconer(station, _config()).build_frame()
    assert str(frame.path.source) == str(station.mycall)
