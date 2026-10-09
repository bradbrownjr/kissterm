"""The ATU and the CAT port hand-off (ROADMAP P3a M6b), against a fake
rigctld and the supervisor's fake modem in its VARA mode."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402
import socket  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from kissterm.addressbook import Entry  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.core import Core  # noqa: E402
from kissterm.core import tuner as tuner_mod  # noqa: E402
from kissterm.core.connect import ConnectRequest  # noqa: E402
from kissterm.launch import supervisor as supervisor_mod  # noqa: E402
from kissterm.rig import rigctld  # noqa: E402
from tests.fake_rigctld import FakeRigctld  # noqa: E402
from tests.unit.test_core_connect import _Operator, _View, _core  # noqa: E402

MODEM = str(Path(__file__).resolve().parents[1] / "fake_modem.py")


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(rigctld, "BACKOFF", (0.0,))
    monkeypatch.setattr(tuner_mod, "TUNE_SECONDS", 0.3)
    monkeypatch.setattr(tuner_mod, "TUNE_SEEN", 0.1)
    monkeypatch.setattr(tuner_mod, "POLL", 0.02)


@pytest_asyncio.fixture
async def rig():
    fake = await FakeRigctld().start()
    yield fake
    await fake.stop()


def _configure(core, rig, *, keying="own", bands=()) -> None:
    core.config.rigs = [{"name": "ft991a", "model": 1035, "host": "127.0.0.1", "port": rig.port,
                         "tune_bands": list(bands)}]
    core.config.programs = [{"name": "modem", "keying": keying}]
    core.config.transports = [{"name": "hf", "kind": "tcp", "program": "modem", "rig": "ft991a"}]
    core.config.active_transport = "hf"


@pytest.mark.asyncio
async def test_the_atu_is_switched_in_after_a_tune_on_hf_only(rig):
    core, host, station, peer, ta = await _core(_Operator(answer=True))
    _configure(core, rig)
    await core.connector.connect(ConnectRequest("WS1EC-7"),
                                 entry=Entry("WS1EC-7", frequency="7.1015 MHz USB-D"))
    assert rig.tuner == 1 and "+U TUNER 1" in rig.log
    assert rig.tunes == 0, "an ATU cycle ran with no band chosen"
    rig.tuner = 0
    rig.log.clear()
    await core.rigwatch.tune(__import__("kissterm.rig.frequency", fromlist=["x"]).Tuning(145_050_000))
    assert "+U TUNER 1" not in rig.log
    station.close()
    peer.close()


@pytest.mark.asyncio
async def test_a_rig_without_an_atu_is_never_asked(rig):
    core, host, station, peer, ta = await _core(_Operator(answer=True))
    _configure(core, rig, bands=["40m"])
    rig.funcs, rig.ops = {"VOX"}, {"CPY"}
    await core.connector.connect(ConnectRequest("WS1EC-7"),
                                 entry=Entry("WS1EC-7", frequency="7.1015 MHz"))
    assert not any(line.startswith(("+U TUNER", "+G TUNE")) for line in rig.log)
    station.close()
    peer.close()


@pytest.mark.asyncio
async def test_a_chosen_band_runs_the_cycle_after_the_reminder_says_so(rig):
    operator = _Operator(answer=True)
    core, host, station, peer, ta = await _core(operator)
    _configure(core, rig, bands=["40m"])
    await core.tuner.learn(rigctld.RigctldClient.from_rig(core.config.rigs[0]), core.config.rigs[0])
    await core.connector.connect(ConnectRequest("WS1EC-7"),
                                 entry=Entry("WS1EC-7", frequency="7.1015 MHz USB-D"))
    assert "a few seconds of carrier" in operator.asked[0].tune
    assert rig.tunes == 1 and core.gate.enabled
    assert ta.sent, "the connect did not go on after the cycle"
    station.close()
    peer.close()


@pytest.mark.asyncio
async def test_a_band_not_chosen_and_a_declined_reminder_run_no_cycle(rig):
    core, host, station, peer, ta = await _core(_Operator(answer=True))
    _configure(core, rig, bands=["80m"])
    await core.tuner.learn(rigctld.RigctldClient.from_rig(core.config.rigs[0]), core.config.rigs[0])
    await core.connector.connect(ConnectRequest("WS1EC-7"),
                                 entry=Entry("WS1EC-7", frequency="7.1015 MHz"))
    assert rig.tunes == 0
    core2, host2, station2, peer2, ta2 = await _core(_Operator(answer=False))
    _configure(core2, rig, bands=["40m"])
    await core2.connector.connect(ConnectRequest("WS1EC-7"),
                                  entry=Entry("WS1EC-7", frequency="7.1015 MHz"))
    assert rig.tunes == 0 and ta2.sent == []
    for s in (station, peer, station2, peer2):
        s.close()


@pytest.mark.asyncio
async def test_an_swr_trip_stops_the_cycle_and_the_connect(rig):
    core, host, station, peer, ta = await _core(_Operator(answer=True))
    _configure(core, rig, bands=["40m"])
    await core.tuner.learn(rigctld.RigctldClient.from_rig(core.config.rigs[0]), core.config.rigs[0])
    core.gate.latch_closed("SWR tripped at 4.8:1 at 14:02")
    reasons = []
    await core.connector.connect(ConnectRequest("WS1EC-7"),
                                 entry=Entry("WS1EC-7", frequency="7.1015 MHz"), report=reasons.append)
    assert rig.tunes == 0 and ta.sent == [] and "held off" in reasons[0]
    station.close()
    peer.close()


# -- the CAT port hand-off ------------------------------------------------------

def _free_pair() -> int:
    for _ in range(50):
        with socket.socket() as a, socket.socket() as b:
            try:
                a.bind(("127.0.0.1", 0))
                port = a.getsockname()[1]
                b.bind(("127.0.0.1", port + 1))
                return port
            except OSError:
                continue
    raise RuntimeError("no free port pair")


@pytest_asyncio.fixture
async def vara_station(rig, monkeypatch):
    supervisor_mod.reset_for_tests()
    port = _free_pair()
    operator = _Operator(answer=True)
    config = Config(mycall="N1ABC-1")
    config.rigs = [{"name": "ft991a", "model": 1035, "host": "127.0.0.1", "port": rig.port}]
    config.programs = [{"name": "modem", "preset": "custom", "path": sys.executable,
                        "args": f"{MODEM} {port} --vara", "keying": "cat",
                        "start_timeout": 10, "stop_on_exit": True}]
    config.transports = [{"name": "vara-hf", "kind": "vara", "host": "127.0.0.1",
                          "mycall": "N1ABC-1", "cmd_port": port, "data_port": port + 1,
                          "program": "modem", "rig": "ft991a"}]
    config.active_transport = "vara-hf"
    from kissterm.transport import build_transport

    core = Core(config, operator=operator)
    transport = build_transport(config.transports[0])
    await core.supervisor.open_transport(config, config.transports[0], transport)
    core.session_transport = transport
    transport.gate = core.gate
    core.attach_view(_View())
    yield core, operator
    with __import__("contextlib").suppress(Exception):
        await core.session_transport.close()
    await core.supervisor.stop_all()
    supervisor_mod.reset_for_tests()


@pytest.mark.asyncio
async def test_the_hand_off_stops_tunes_and_brings_the_modem_back(rig, vara_station):
    core, operator = vara_station
    pid_before = core.supervisor.status("modem")["pid"]
    assert core.rigwatch.plan(Entry("W1AW-10", frequency="7.1015 MHz")) is not None
    await core.connector.dial_entry(Entry("W1AW-10", frequency="7.1015 MHz USB-D"))
    assert "stops modem to use the CAT port" in operator.asked[0].tune
    assert rig.frequency == 7_101_500 and rig.mode == "PKTUSB"
    status = core.supervisor.status("modem")
    assert status["running"] and status["pid"] != pid_before, "the modem was not restarted"
    assert core.sessions.link("") is not None and core.sessions.link("").connected
    texts = [n.text for n in operator.notices]
    assert any("stopping modem" in t for t in texts) and any("modem is back" in t for t in texts)


@pytest.mark.asyncio
async def test_a_rigctld_that_fails_mid_tune_still_brings_the_modem_back(rig, vara_station):
    core, operator = vara_station
    rig.fail["F"] = -5
    await core.connector.dial_entry(Entry("W1AW-10", frequency="7.1015 MHz"))
    assert core.supervisor.status("modem")["running"], "the modem stayed stopped"
    assert core.session_transport is not None and core.session_transport.state.value == "open"
    assert any("could not tune" in n.text for n in operator.notices)
    assert core.sessions.link("") is None or not core.sessions.link("").connected


@pytest.mark.asyncio
async def test_no_hand_off_while_a_session_is_up_or_for_a_modem_not_ours(rig, vara_station):
    core, operator = vara_station
    await core.connector.dial_entry(Entry("W1AW-10"))  # no frequency: no hand-off
    assert core.sessions.link("").connected
    assert "Disconnect first" in core.tuner.handoff_problem()
    assert core.rigwatch.plan(Entry("W1AW-10", frequency="7.1015 MHz")) is None
    await core.connector.disconnect("")
    await core.supervisor.stop("modem")
    assert "is not running" in core.tuner.handoff_problem()
    supervisor_mod.reset_for_tests()  # a modem someone else started
    core.supervisor = supervisor_mod.shared()
    assert "was not started by kissterm" in core.tuner.handoff_problem()
