"""Keying the radio for VARA through the gate (ROADMAP P3a M5), against a
fake VARA (`tests/fake_vara.py`, from EA5HVK's command document) and a fake
rigctld."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from kissterm.config import Config  # noqa: E402
from kissterm.core import Core  # noqa: E402
from kissterm.core import ptt as ptt_mod  # noqa: E402
from kissterm.rig import rigctld  # noqa: E402
from kissterm.transport.vara import VaraHfTransport  # noqa: E402
from tests.fake_rigctld import FakeRigctld  # noqa: E402
from tests.fake_vara import FakeVara  # noqa: E402
from tests.unit.test_core_connect import _Operator  # noqa: E402


@pytest_asyncio.fixture
async def rig(monkeypatch):
    monkeypatch.setattr(rigctld, "BACKOFF", (0.0,))
    fake = await FakeRigctld().start()
    yield fake
    await fake.stop()


@pytest_asyncio.fixture
async def vara():
    modem = await FakeVara().start()
    yield modem
    await modem.stop()


async def _station(rig, vara, *, keying="rigctld", gate=True, ptt_timeout=120):
    operator = _Operator(answer=True)
    transport = VaraHfTransport("127.0.0.1", "N1ABC-1", cmd_port=vara.cmd_port,
                                data_port=vara.data_port)
    await transport.open()
    config = Config(mycall="N1ABC-1")
    config.rigs = [{"name": "ic7300", "model": 3073, "host": "127.0.0.1", "port": rig.port,
                    "ptt_timeout": ptt_timeout}]
    config.programs = [{"name": "VARA HF", "keying": keying}]
    config.transports = [{"name": "vara-hf", "kind": "vara", "program": "VARA HF",
                          "rig": "ic7300"}]
    config.active_transport = "vara-hf"
    core = Core(config, session_transport=transport, operator=operator)
    core.gate.set(gate)
    core.ptt.start()
    return core, transport, operator


async def _until(condition, what: str) -> None:
    for _ in range(200):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}")


def _keys(rig) -> list[str]:
    return [line for line in rig.log if line.startswith("+T")]


@pytest.mark.asyncio
async def test_vara_ptt_keys_and_unkeys_the_radio(rig, vara):
    core, transport, _ = await _station(rig, vara)
    await vara.notify("PTT ON")
    await _until(lambda: rig.ptt == 1, "the key")
    assert core.ptt.keyed
    await vara.notify("PTT OFF")
    await _until(lambda: rig.ptt == 0 and not core.ptt.keyed, "the unkey")
    assert _keys(rig) == ["+T 1", "+T 0"]
    await core.ptt.shutdown()
    await transport.close()


@pytest.mark.asyncio
async def test_a_closed_gate_refuses_the_key_and_says_so_once(rig, vara):
    core, transport, operator = await _station(rig, vara, gate=False)
    for _ in range(3):
        await vara.notify("PTT ON")
        await vara.notify("PTT OFF")
    await vara.notify("PTT ON")
    await asyncio.sleep(0.1)
    assert "+T 1" not in _keys(rig)
    assert rig.ptt == 0 and not core.ptt.keyed
    refusals = [n for n in operator.notices if "transmit is off" in n.text]
    assert len(refusals) == 1, "every ARQ retry raised its own notice"
    assert core.gate.blocked >= 4
    await core.ptt.shutdown()
    await transport.close()


@pytest.mark.asyncio
async def test_closing_the_gate_while_keyed_unkeys(rig, vara):
    core, transport, operator = await _station(rig, vara)
    await vara.notify("PTT ON")
    await _until(lambda: rig.ptt == 1, "the key")
    core.gate.set(False)
    await _until(lambda: rig.ptt == 0, "the unkey")
    assert any("Transmit turned off" in n.text for n in operator.notices)
    await vara.notify("PTT ON")  # VARA still wants to: refused now
    await asyncio.sleep(0.05)
    assert rig.ptt == 0
    await core.ptt.shutdown()
    await transport.close()


@pytest.mark.asyncio
async def test_the_watchdog_unkeys_and_holds_off_until_ptt_off(rig, vara):
    core, transport, operator = await _station(rig, vara, ptt_timeout=0.1)
    await vara.notify("PTT ON")
    await _until(lambda: rig.ptt == 1, "the key")
    await _until(lambda: rig.ptt == 0, "the watchdog")
    assert any("was keyed for" in n.text for n in operator.notices)
    await vara.notify("PTT ON")
    await asyncio.sleep(0.05)
    assert rig.ptt == 0, "a modem stuck keyed re-keyed the radio"
    await vara.notify("PTT OFF")
    await vara.notify("PTT ON")
    await _until(lambda: rig.ptt == 1, "keying again after PTT OFF")
    await core.ptt.shutdown()
    assert rig.ptt == 0
    await transport.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("how", ["vara exits", "transport closes", "shutdown"])
async def test_every_way_vara_goes_away_unkeys(rig, vara, how):
    core, transport, _ = await _station(rig, vara)
    await vara.notify("PTT ON")
    await _until(lambda: rig.ptt == 1, "the key")
    if how == "vara exits":
        vara.drop()
    elif how == "transport closes":
        await transport.close()
    else:
        await core.ptt.shutdown()
    await _until(lambda: rig.ptt == 0, "the unkey")
    await core.ptt.shutdown()
    await transport.close()


@pytest.mark.asyncio
async def test_a_modem_that_keys_by_itself_is_never_keyed_for(rig, vara):
    core, transport, _ = await _station(rig, vara, keying="own")
    await vara.notify("PTT ON")
    await asyncio.sleep(0.1)
    assert _keys(rig) == [] and rig.connections == 0
    await core.ptt.shutdown()
    await transport.close()


@pytest.mark.asyncio
async def test_a_rig_that_refuses_the_key_is_reported(rig, vara):
    core, transport, operator = await _station(rig, vara)
    rig.fail["T"] = -9
    await vara.notify("PTT ON")
    await _until(lambda: any("Could not key" in n.text for n in operator.notices), "the report")
    assert not core.ptt.keyed
    await core.ptt.shutdown()
    await transport.close()


@pytest.mark.asyncio
async def test_the_status_shows_ptt_while_kissterm_holds_it(rig, vara):
    from kissterm.core.events import RigStateChanged

    core, transport, _ = await _station(rig, vara)
    core.rigwatch.poll_seconds = 0.05
    seen = []
    core.events.subscribe(lambda s, e: seen.append(e.ptt) if isinstance(e, RigStateChanged) else None)
    core.rigwatch.start()
    await _until(lambda: core.rigwatch.state is not None, "a reading")
    await vara.notify("PTT ON")
    await _until(lambda: True in seen, "PTT shown")
    await vara.notify("PTT OFF")
    await _until(lambda: seen[-1] is False, "PTT cleared")
    await core.rigwatch.shutdown()
    await core.ptt.shutdown()
    await transport.close()


@pytest.mark.asyncio
async def test_the_last_resort_unkeys_with_no_event_loop_task(rig, vara):
    core, transport, _ = await _station(rig, vara)
    await vara.notify("PTT ON")
    await _until(lambda: rig.ptt == 1, "the key")
    assert ("127.0.0.1", rig.port) in ptt_mod._KEYED
    await asyncio.to_thread(ptt_mod.unkey_all_now)
    assert rig.ptt == 0 and ("127.0.0.1", rig.port) not in ptt_mod._KEYED
    core.ptt.keyed = False
    await core.ptt.shutdown()
    await transport.close()
