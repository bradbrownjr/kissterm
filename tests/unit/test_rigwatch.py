"""Reading and tuning the transport's radio (ROADMAP P3a M6), against a fake rigctld."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from kissterm.addressbook import Entry  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.core import Core  # noqa: E402
from kissterm.core.connect import ConnectRequest  # noqa: E402
from kissterm.core.events import RigStateChanged  # noqa: E402
from kissterm.rig import rigctld  # noqa: E402
from kissterm.rig.frequency import Tuning, band_of, dial_from_centre, parse_frequency  # noqa: E402
from kissterm.serve import wire  # noqa: E402
from tests.fake_rigctld import FakeRigctld  # noqa: E402
from tests.unit.test_core_connect import _Operator, _core  # noqa: E402


@pytest_asyncio.fixture
async def fake(monkeypatch):
    monkeypatch.setattr(rigctld, "BACKOFF", (0.0,))
    rig = await FakeRigctld().start()
    yield rig
    await rig.stop()


def _configure(core, fake, **program) -> None:
    core.config.rigs = [{"name": "ic7300", "model": 3073, "host": "127.0.0.1", "port": fake.port}]
    core.config.programs = [{"name": "modem", "keying": program.get("keying", "own")}]
    core.config.transports = [{"name": "hf", "kind": "tcp", "program": "modem", "rig": "ic7300"}]
    core.config.active_transport = "hf"


@pytest.mark.parametrize("text,hz,mode", [
    ("7.101500 MHz USB-D", 7_101_500, "PKTUSB"), ("145.090", 145_090_000, ""),
    ("7101.5", 7_101_500, ""), ("7101500", 7_101_500, ""), ("14.0705 MHz LSB", 14_070_500, "LSB"),
])
def test_frequencies_are_read_by_unit_and_magnitude(text, hz, mode):
    assert parse_frequency(text) == Tuning(hz, mode)


@pytest.mark.parametrize("text", ["", "simplex", "0", "call first"])
def test_no_number_means_nothing_to_tune(text):
    assert parse_frequency(text) is None


def test_a_winlink_hf_digital_centre_is_dialled_1500_hz_lower():
    assert dial_from_centre(7_103_000, "VARA") == Tuning(7_101_500, "PKTUSB")
    assert dial_from_centre(145_090_000, "Packet") == Tuning(145_090_000, "")
    assert dial_from_centre(145_090_000, "VARA FM") == Tuning(145_090_000, "")
    assert band_of(7_101_500) == "40m" and band_of(1) == ""


def test_a_tuning_is_described_for_the_reminder():
    assert Tuning(7_101_500, "PKTUSB").describe() == "7.101.500 USB-D"
    assert Tuning(7_101_500, "PKTUSB").as_contact_text() == "7.101500 MHz USB-D"


@pytest.mark.asyncio
async def test_the_radio_is_read_and_published(fake):
    core, host, station, peer, ta = await _core(_Operator(answer=True))
    _configure(core, fake)
    core.rigwatch.poll_seconds = 0.05
    seen = []
    core.events.subscribe(lambda seq, event: seen.append(event)
                          if isinstance(event, RigStateChanged) else None)
    core.rigwatch.start()
    for _ in range(100):
        if core.rigwatch.state is not None:
            break
        await asyncio.sleep(0.02)
    assert core.rigwatch.state.frequency == 7_101_500
    assert seen and seen[-1].name == "ic7300" and seen[-1].frequency == 7_101_500
    assert wire.rig_summary(core)["mode"] == "USB"
    # Reading never keys.
    assert not any(line.startswith("+T") or line.startswith("T ") for line in fake.log)
    await core.rigwatch.shutdown()
    station.close()
    peer.close()


@pytest.mark.asyncio
async def test_a_modem_that_owns_cat_is_left_alone(fake):
    core, host, station, peer, ta = await _core(_Operator(answer=True))
    _configure(core, fake, keying="cat")
    core.rigwatch.start()
    await asyncio.sleep(0.1)
    assert core.rigwatch.state is None and "CAT" in core.rigwatch.problem
    assert fake.connections == 0
    await core.rigwatch.shutdown()
    station.close()
    peer.close()


@pytest.mark.asyncio
async def test_a_confirmed_connect_tunes_after_the_reminder_says_so(fake):
    operator = _Operator(answer=True)
    core, host, station, peer, ta = await _core(operator)
    _configure(core, fake)
    entry = Entry("WS1EC-7", frequency="7.1015 MHz USB-D")
    await core.connector.connect(ConnectRequest("WS1EC-7"), entry=entry)
    assert "7.101.500 USB-D" in operator.asked[0].tune
    assert fake.frequency == 7_101_500 and fake.mode == "PKTUSB"
    await core.rigwatch.shutdown()
    station.close()
    peer.close()


@pytest.mark.asyncio
async def test_a_declined_reminder_does_not_tune(fake):
    core, host, station, peer, ta = await _core(_Operator(answer=False))
    _configure(core, fake)
    fake.frequency = 3_800_000
    await core.connector.connect(ConnectRequest("WS1EC-7"),
                                 entry=Entry("WS1EC-7", frequency="7.1015 MHz"))
    assert fake.frequency == 3_800_000
    assert ta.sent == []
    await core.rigwatch.shutdown()
    station.close()
    peer.close()


@pytest.mark.asyncio
async def test_a_failed_tune_stops_the_connect(fake):
    core, host, station, peer, ta = await _core(_Operator(answer=True))
    _configure(core, fake)
    fake.fail["F"] = -5
    reasons = []
    await core.connector.connect(ConnectRequest("WS1EC-7"),
                                 entry=Entry("WS1EC-7", frequency="7.1015 MHz"),
                                 report=reasons.append)
    assert reasons and "could not tune" in reasons[0]
    assert ta.sent == [], "connected over a radio that was not tuned"
    await core.rigwatch.shutdown()
    station.close()
    peer.close()


@pytest.mark.asyncio
async def test_a_gateway_is_stored_as_its_dial_with_the_centre_noted():
    core, host, station, peer, ta = await _core(_Operator(answer=True))
    core.mail.use_gateway("W1AW", "7.103 MHz", "VARA 500", "FN43")
    entry = core.addressbook.find("W1AW")
    assert entry.frequency == "7.101500 MHz USB-D"
    assert "listed centre 7.103 MHz" in entry.note
    station.close()
    peer.close()


def test_the_phone_follows_the_radio_reading():
    from kissterm.client.state import StationState

    state = StationState()
    heard = []
    state.subscribe(lambda kind, data: heard.append(kind))
    state.apply({"type": "welcome", "station": {}, "snapshot": {
        "rig": {"name": "ic7300", "frequency": 7_101_500, "mode": "PKTUSB", "ptt": False}}})
    assert state.rig["frequency"] == 7_101_500
    state.apply({"type": "event", "seq": 2, "name": "RigStateChanged",
                 "data": {"name": "ic7300", "frequency": 0, "mode": "", "ptt": None}})
    assert state.rig == {} and "rig" in heard
