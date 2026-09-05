"""A beacon is unattended transmission, so the tests are mostly about silence.

Almost everything here asserts that nothing went on the air. That is the right
weighting: a beacon that fails to transmit is an inconvenience the operator
notices immediately, and a beacon that transmits when it should not is their
callsign on a shared channel saying something they did not authorise.

Frames go through the loopback rather than a mock, so what is asserted is a
frame that actually encoded and decoded -- the wire format is where half the
real bugs live.
"""

from __future__ import annotations

import asyncio

from kissterm import _isolate

_isolate.isolate()

import pytest  # noqa: E402

from kissterm.ax25.address import AX25Address  # noqa: E402
from kissterm.ax25.frame import PID_NO_LAYER3, UType  # noqa: E402
from kissterm.ax25.station import AX25Station  # noqa: E402
from kissterm.beacon import (  # noqa: E402
    MAX_BEACON_BYTES,
    MIN_INTERVAL_MINUTES,
    Beaconer,
    describe_cost,
    encode_text,
    normalize_text,
)
from kissterm.config import BeaconConfig, Config, load_config, save_config  # noqa: E402

from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("W1AW-1")


async def _station():
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    return AX25Station(MYCALL, ta), ta, tb


def _config(**kw) -> BeaconConfig:
    base = {"enabled": True, "text": "W1AW test beacon", "interval_minutes": 30}
    base.update(kw)
    return BeaconConfig(**base)


# ---------------------------------------------------------------------------
# Text handling
# ---------------------------------------------------------------------------


def test_multiline_text_joins_with_cr_not_lf():
    """LF makes a BPQ32 node echo a spurious blank line. Packet is CR."""
    assert normalize_text("one\ntwo") == "one\rtwo"
    assert normalize_text("one\r\ntwo") == "one\rtwo"


def test_blank_lines_are_dropped():
    assert normalize_text("one\n\n\ntwo\n") == "one\rtwo"


@pytest.mark.parametrize("text", ["", "   ", "\n\n", "\r\n"])
def test_whitespace_only_text_encodes_to_nothing(text):
    payload, _ = encode_text(text)
    assert payload == b""


def test_long_text_is_truncated_not_refused():
    payload, truncated = encode_text("x" * 1000)
    assert truncated and len(payload) == MAX_BEACON_BYTES


def test_encoding_never_raises_on_what_an_operator_pasted():
    payload, _ = encode_text("café — 你好")
    assert isinstance(payload, bytes)


def test_describe_cost_reports_channel_share():
    text = describe_cost(_config(text="x" * 200, interval_minutes=10))
    assert "seconds of channel every 10 minutes" in text
    assert "%" in text


def test_describe_cost_says_so_when_nothing_would_be_sent():
    assert describe_cost(_config(text="")) == "nothing is set to be transmitted"


# ---------------------------------------------------------------------------
# Refusing to transmit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_beacon_sends_nothing():
    station, ta, _ = await _station()
    beacon = Beaconer(station, _config(enabled=False))
    assert beacon.problem() == "beaconing is off"
    assert await beacon.send_once() is False
    assert ta.sent == []


@pytest.mark.asyncio
async def test_empty_text_sends_nothing_even_when_enabled():
    """An empty beacon is pure channel occupancy. `enabled` does not override
    having nothing to say."""
    station, ta, _ = await _station()
    beacon = Beaconer(station, _config(text="   "))
    assert beacon.problem() == "no beacon text is set"
    assert await beacon.send_once() is False
    assert ta.sent == []
    assert beacon.start() == "no beacon text is set"


@pytest.mark.asyncio
async def test_a_bad_destination_is_reported_not_raised():
    station, _, _ = await _station()
    beacon = Beaconer(station, _config(destination="not a callsign at all"))
    assert "bad beacon destination" in beacon.problem()
    assert await beacon.send_once() is False


@pytest.mark.asyncio
async def test_text_deleted_under_a_running_beaconer_stops_transmission():
    """The failure mode of not re-checking at send time is transmitting text
    the operator has already deleted."""
    station, ta, _ = await _station()
    beacon = Beaconer(station, _config())
    assert await beacon.send_once() is True
    beacon.config.text = ""
    assert await beacon.send_once() is False
    assert len(ta.sent) == 1


@pytest.mark.asyncio
async def test_a_transport_failure_does_not_raise_into_the_caller():
    station, ta, _ = await _station()

    async def boom(frame, port=0):
        raise OSError("TNC went away")

    ta.send_frame = boom
    beacon = Beaconer(station, _config())
    assert await beacon.send_once() is False
    assert beacon.sent_count == 0


# ---------------------------------------------------------------------------
# The frame that goes out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_beacon_is_a_ui_frame_from_us_to_the_destination():
    station, ta, tb = await _station()
    seen = []
    tb.subscribe(lambda f, port=0: seen.append(f))
    beacon = Beaconer(station, _config(text="W1AW test beacon"))
    assert await beacon.send_once() is True
    await asyncio.sleep(0.05)

    assert len(seen) == 1
    frame = seen[0]
    assert frame.kind == "U" and frame.utype is UType.UI
    assert frame.pid == PID_NO_LAYER3
    assert str(frame.path.source) == "W1AW-1"
    assert str(frame.path.destination) == "BEACON"
    assert frame.info == b"W1AW test beacon"


@pytest.mark.asyncio
async def test_beacon_is_not_a_command():
    """A UI frame to an unconnected destination is not asking anyone for
    anything; marking it a command invites a strict AX.25 2.2 station to
    answer it."""
    station, _, _ = await _station()
    frame = Beaconer(station, _config()).build_frame()
    assert frame is not None and not frame.command


@pytest.mark.asyncio
async def test_digipeater_path_reaches_the_frame():
    station, _, _ = await _station()
    frame = Beaconer(station, _config(path="W1XYZ-1,WIDE2-1")).build_frame()
    assert [str(r) for r in frame.path.repeaters] == ["W1XYZ-1", "WIDE2-1"]


@pytest.mark.asyncio
async def test_empty_path_means_direct():
    station, _, _ = await _station()
    frame = Beaconer(station, _config(path="")).build_frame()
    assert frame.path.repeaters == ()


@pytest.mark.asyncio
async def test_alternate_destinations_work():
    station, _, _ = await _station()
    for dest in ("BEACON", "ID", "CQ"):
        frame = Beaconer(station, _config(destination=dest)).build_frame()
        assert str(frame.path.destination) == dest


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------


def test_interval_floor_is_enforced_in_code_not_only_in_the_config_loader():
    """A Config built in code bypasses the loader, and the floor is a courtesy
    to everyone else on the frequency, not a preference to be talked out of."""
    beacon = Beaconer(None, BeaconConfig(interval_minutes=1))
    assert beacon.interval_seconds == MIN_INTERVAL_MINUTES * 60


def test_config_loader_clamps_the_interval_and_says_so(tmp_path):
    path = tmp_path / "config.toml"
    cfg = Config(mycall="W1AW-1")
    cfg.beacon = _config(interval_minutes=2)
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.beacon.interval_minutes == MIN_INTERVAL_MINUTES
    assert any("minimum" in w for w in loaded.warnings)


def test_config_loader_warns_about_an_enabled_beacon_with_no_text(tmp_path):
    path = tmp_path / "config.toml"
    cfg = Config(mycall="W1AW-1")
    cfg.beacon = _config(text="")
    save_config(cfg, path)
    loaded = load_config(path)
    assert any("empty" in w for w in loaded.warnings)


@pytest.mark.asyncio
async def test_nothing_is_transmitted_at_start():
    """Launching the app is not a request to transmit. An operator who starts
    kissterm to check something and quits must not have keyed the radio."""
    station, ta, _ = await _station()
    beacon = Beaconer(station, _config())
    assert beacon.start() == ""
    try:
        await asyncio.sleep(0.2)
        assert ta.sent == []
        assert beacon.sent_count == 0
    finally:
        await beacon.stop()


@pytest.mark.asyncio
async def test_the_timer_fires_after_one_interval():
    station, ta, _ = await _station()
    beacon = Beaconer(station, _config())
    # Monkeypatched rather than waiting ten real minutes. The floor itself is
    # asserted separately, above.
    type(beacon).interval_seconds = property(lambda self: 0.05)
    try:
        assert beacon.start() == ""
        await asyncio.sleep(0.18)
        assert beacon.sent_count >= 2
        assert len(ta.sent) >= 2
    finally:
        del type(beacon).interval_seconds
        await beacon.stop()


@pytest.mark.asyncio
async def test_start_is_idempotent_so_a_second_save_does_not_double_the_rate():
    station, _, _ = await _station()
    beacon = Beaconer(station, _config())
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
    beacon = Beaconer(station, _config())
    beacon.cancel()
    await beacon.stop()
    assert not beacon.running


@pytest.mark.asyncio
async def test_stop_disarms_it():
    station, ta, _ = await _station()
    beacon = Beaconer(station, _config())
    type(beacon).interval_seconds = property(lambda self: 0.05)
    try:
        beacon.start()
        await beacon.stop()
        assert not beacon.running
        await asyncio.sleep(0.2)
        assert ta.sent == []
    finally:
        del type(beacon).interval_seconds


# ---------------------------------------------------------------------------
# The distinction from APRS -- the mistake this feature is most likely to make
# ---------------------------------------------------------------------------


def test_beacon_config_is_separate_from_aprs_config():
    """One feature turning on the other would put a transmission on the air
    that the operator did not intend, under their own callsign."""
    cfg = Config()
    assert cfg.beacon is not cfg.aprs
    cfg.beacon.enabled = True
    assert cfg.aprs.enabled is False
    assert not hasattr(cfg.beacon, "symbol")
    assert not hasattr(cfg.aprs, "text")


@pytest.mark.asyncio
async def test_beacon_does_not_use_the_aprs_destination():
    station, _, _ = await _station()
    frame = Beaconer(station, _config()).build_frame()
    assert str(frame.path.destination) != "APRS"
