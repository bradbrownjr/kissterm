"""The SWR watch and trip (ROADMAP P3a M5b), against a fake rigctld whose
SWR readings a test scripts, and a fake VARA."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from kissterm.config import Config  # noqa: E402
from kissterm.core import Core  # noqa: E402
from kissterm.core import swr as swr_mod  # noqa: E402
from kissterm.core.events import Alert, GateChanged  # noqa: E402
from kissterm.core.questions import SwrRearm  # noqa: E402
from kissterm.rig import rigctld  # noqa: E402
from kissterm.transport.vara import VaraHfTransport  # noqa: E402
from tests.fake_rigctld import FakeRigctld  # noqa: E402
from tests.fake_vara import FakeVara  # noqa: E402
from tests.unit.test_core_connect import _Operator, _View  # noqa: E402


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(rigctld, "BACKOFF", (0.0,))
    monkeypatch.setattr(swr_mod, "SETTLE", 0.1)
    monkeypatch.setattr(swr_mod, "SWR_POLL", 0.01)
    monkeypatch.setattr(swr_mod, "PTT_POLL", 0.01)
    with __import__("contextlib").suppress(FileNotFoundError):
        swr_mod._state_file().unlink()
    yield
    with __import__("contextlib").suppress(FileNotFoundError):
        swr_mod._state_file().unlink()


@pytest_asyncio.fixture
async def rig():
    fake = await FakeRigctld().start()
    yield fake
    await fake.stop()


@pytest_asyncio.fixture
async def vara():
    modem = await FakeVara().start()
    yield modem
    await modem.stop()


async def _station(rig, vara, *, keying="rigctld", answer=True, **limits):
    operator = _Operator(answer=answer)
    transport = VaraHfTransport("127.0.0.1", "N1ABC-1", cmd_port=vara.cmd_port,
                                data_port=vara.data_port)
    await transport.open()
    config = Config(mycall="N1ABC-1")
    config.rigs = [{"name": "ic7300", "model": 3073, "host": "127.0.0.1", "port": rig.port,
                    "swr_warn": limits.get("warn", 2.0), "swr_trip": limits.get("trip", 3.0)}]
    config.programs = [{"name": "VARA HF", "keying": keying}]
    config.transports = [{"name": "vara-hf", "kind": "vara", "program": "VARA HF",
                          "rig": "ic7300"}]
    config.active_transport = "vara-hf"
    core = Core(config, session_transport=transport, operator=operator)
    core.attach_view(_View())
    core.gate.set(True)
    core.ptt.start()
    core.swr.start()
    return core, transport, operator


async def _stop(core, transport) -> None:
    await core.swr.shutdown()
    await core.ptt.shutdown()
    await transport.close()


async def _until(condition, what: str, tries: int = 300) -> None:
    for _ in range(tries):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}")


@pytest.mark.asyncio
async def test_one_high_reading_does_not_trip(rig, vara):
    core, transport, _ = await _station(rig, vara)
    rig.swr = [4.5, 1.3]  # one spike, then the antenna's own
    await vara.notify("PTT ON")
    await _until(lambda: core.swr.last == 1.3, "readings after the spike")
    await asyncio.sleep(0.1)
    assert core.gate.enabled and not core.gate.latch
    await _stop(core, transport)


@pytest.mark.asyncio
async def test_a_sustained_high_swr_trips_unkeys_and_latches(rig, vara):
    core, transport, operator = await _station(rig, vara)
    events = []
    core.events.subscribe(lambda s, e: events.append(e))
    rig.frequency, rig.mode = 7_101_500, "PKTUSB"
    await core.rigwatch.tune(__import__("kissterm.rig.frequency", fromlist=["Tuning"]).Tuning(
        7_101_500, "PKTUSB"))
    rig.swr = [4.8]
    await vara.notify("PTT ON")
    await _until(lambda: core.gate.latch, "the trip")
    await _until(lambda: rig.ptt == 0, "the unkey")
    assert not core.gate.enabled
    assert "4.8:1" in core.gate.latch and "7.101.500 USB-D" in core.gate.latch
    assert "ABORT" in vara.commands, "VARA was not told to stop"
    assert any(isinstance(e, Alert) and e.topic == "swr" and e.urgent for e in events)
    assert any(isinstance(e, GateChanged) and e.latch for e in events)
    assert any("SWR tripped" in n.text for n in operator.notices)
    assert swr_mod._state_file().exists()
    # Nothing of kissterm's opens it again: not a connect, not VARA's next PTT.
    assert core.gate.set(True) is False
    assert core.connector.arm_for("a beacon") is False
    await vara.notify("PTT OFF")
    await vara.notify("PTT ON")
    await asyncio.sleep(0.05)
    assert rig.ptt == 0
    await _stop(core, transport)


@pytest.mark.asyncio
async def test_only_the_operator_re_arms_and_is_asked_first(rig, vara):
    core, transport, operator = await _station(rig, vara, answer=False)
    rig.swr = [4.8]
    await vara.notify("PTT ON")
    await _until(lambda: core.gate.latch, "the trip")
    assert await core.swr.ask_rearm() is False
    assert isinstance(operator.asked[-1], SwrRearm) and "4.8:1" in operator.asked[-1].trip
    assert core.gate.latch and swr_mod._state_file().exists()
    operator.answer = True
    assert await core.swr.ask_rearm() is True
    assert not core.gate.latch and not swr_mod._state_file().exists()
    assert core.gate.set(True) is True
    await _stop(core, transport)


@pytest.mark.asyncio
async def test_the_trip_survives_a_restart():
    swr_mod._state_file().parent.mkdir(parents=True, exist_ok=True)
    swr_mod._state_file().write_text(
        '{"swr": 4.8, "frequency": 7101500, "mode": "PKTUSB", "rig": "ic7300", '
        '"at": "2026-10-09T14:02:00"}', encoding="utf-8")
    operator = _Operator()
    core = Core(Config(mycall="N1ABC-1", tx_armed_at_start=True), operator=operator)
    assert not core.gate.enabled and "SWR tripped at 4.8:1 on 7.101.500 USB-D at 14:02" in core.gate.latch
    core.swr.start()
    assert any("before kissterm was last closed" in n.text for n in operator.notices)
    await core.swr.shutdown()


@pytest.mark.asyncio
async def test_a_modem_on_its_own_port_is_unkeyed_by_cat_and_named(rig, vara):
    core, transport, operator = await _station(rig, vara, keying="own")
    rig.swr = [4.8]
    rig.ptt = 1  # the modem keyed it by RTS; the rig reports it
    await _until(lambda: core.gate.latch, "the trip")
    assert "+T 0" in rig.log
    assert any("may still be able to key" in n.text for n in operator.notices)
    await _stop(core, transport)


@pytest.mark.asyncio
async def test_a_rig_without_swr_is_said_once_and_never_trips(rig, vara):
    core, transport, _ = await _station(rig, vara)
    rig.fail["l"] = -11
    await vara.notify("PTT ON")
    await _until(lambda: core.swr.problem, "the problem")
    assert "does not report SWR" in core.swr.problem and not core.gate.latch
    await _stop(core, transport)


@pytest.mark.asyncio
async def test_a_warning_is_said_once_per_transmission(rig, vara):
    core, transport, operator = await _station(rig, vara)
    rig.swr = [2.4]
    await vara.notify("PTT ON")
    await _until(lambda: core.swr.last == 2.4, "a reading")
    await asyncio.sleep(0.1)
    warnings = [n for n in operator.notices if "warning above" in n.text]
    assert len(warnings) == 1 and not core.gate.latch
    await _stop(core, transport)


def test_the_phone_follows_the_latch():
    from kissterm.client.state import StationState

    state = StationState()
    state.apply({"type": "welcome", "station": {}, "snapshot": {
        "gate": False, "gate_latch": "SWR tripped at 4.8:1 at 14:02"}})
    assert state.gate_latch.startswith("SWR tripped")
    state.apply({"type": "event", "seq": 2, "name": "GateChanged",
                 "data": {"enabled": False, "latch": ""}})
    assert state.gate_latch == ""
