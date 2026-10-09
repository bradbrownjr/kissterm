"""The rigctld client against a fake that speaks the Extended Response Protocol."""

from __future__ import annotations

import asyncio
import shutil

import pytest
import pytest_asyncio

from kissterm import _isolate

_isolate.isolate()

from kissterm.rig import rigctld  # noqa: E402
from kissterm.rig.rigctld import RigError, RigctldClient, parse_model_list, rigctld_command  # noqa: E402
from tests.fake_rigctld import FakeRigctld  # noqa: E402


@pytest_asyncio.fixture
async def rig(monkeypatch):
    monkeypatch.setattr(rigctld, "BACKOFF", (0.0,))
    fake = await FakeRigctld().start()
    client = RigctldClient("127.0.0.1", fake.port, "test")
    yield fake, client
    await client.close()
    await fake.stop()


@pytest.mark.asyncio
async def test_reads_frequency_mode_and_ptt(rig):
    fake, client = rig
    state = await client.state()
    assert (state.frequency, state.mode, state.passband, state.ptt) == (7101500, "USB", 2400, False)
    assert all(line.startswith("+") for line in fake.log)
    assert not any(line.startswith(("+T", "+G")) for line in fake.log)  # a read never keys


@pytest.mark.asyncio
async def test_sets_frequency_mode_and_tuner(rig):
    fake, client = rig
    await client.set_frequency(14074000)
    await client.set_mode("PKTUSB", 2400)
    await client.set_tuner(True)
    assert (fake.frequency, fake.mode, fake.tuner) == (14074000, "PKTUSB", 1)


@pytest.mark.asyncio
async def test_ptt_and_tune_are_separate_calls(rig):
    fake, client = rig
    await client.set_ptt(True)
    assert fake.ptt == 1
    await client.set_ptt(False)
    assert fake.ptt == 0
    await client.tune()
    assert "+G TUNE" in fake.log


@pytest.mark.asyncio
async def test_swr_is_a_ratio_and_unsupported_is_an_error(rig):
    fake, client = rig
    fake.swr = [1.5, 4.8]
    assert await client.get_swr() == 1.5
    assert await client.get_swr() == 4.8
    fake.fail["l"] = -11
    with pytest.raises(RigError) as err:
        await client.get_swr()
    assert err.value.code == -11 and "not available" in str(err.value)


@pytest.mark.asyncio
async def test_a_negative_rprt_is_a_rig_error_with_its_code(rig):
    fake, client = rig
    fake.fail["F"] = -1
    with pytest.raises(RigError) as err:
        await client.set_frequency(1)
    assert err.value.code == -1
    assert client.errors == 1


@pytest.mark.asyncio
async def test_chk_vfo_answers_one_line_without_rprt(rig):
    """rigctl_parse.c sends no header and no RPRT for \\chk_vfo; waiting for
    one would hang until the timeout."""
    _, client = rig
    assert await client.chk_vfo() is False
    assert await client.get_frequency() == 7101500  # the stream is still in step


@pytest.mark.asyncio
async def test_a_dropped_connection_is_reopened_on_the_next_call(rig):
    fake, client = rig
    await client.get_frequency()
    fake.drop_clients()
    await asyncio.sleep(0.05)
    with pytest.raises(RigError):
        await client.get_frequency()  # notices the drop, closes
    assert await client.get_frequency() == 7101500
    assert fake.connections == 2


@pytest.mark.asyncio
async def test_no_answer_times_out_without_hanging(rig, monkeypatch):
    fake, client = rig
    monkeypatch.setattr(rigctld, "COMMAND_TIMEOUT", 0.1)
    fake.silent.add("f")
    with pytest.raises(RigError):
        await client.get_frequency()
    assert not client.connected


@pytest.mark.asyncio
async def test_poll_never_raises(rig):
    fake, client = rig
    assert (await client.poll()).frequency == 7101500
    await fake.stop()
    assert await client.poll() is None
    assert client.errors >= 1 and "rigctld" in client.last_error


@pytest.mark.asyncio
async def test_an_unreachable_rigctld_backs_off(monkeypatch):
    monkeypatch.setattr(rigctld, "BACKOFF", (30.0,))
    client = RigctldClient("127.0.0.1", 1, "nothing")  # nothing listens on port 1
    with pytest.raises(RigError):
        await client.get_frequency()
    first = client.errors
    with pytest.raises(RigError, match="retrying shortly"):
        await client.get_frequency()
    assert client.errors == first  # the second call did not try the network


def test_rigctld_is_started_bound_to_the_rig_host_only():
    argv = rigctld_command({"model": 1035, "device": "/dev/ttyUSB0", "speed": 38400,
                            "host": "127.0.0.1", "port": 4532})
    assert argv == ["rigctld", "-m", "1035", "-r", "/dev/ttyUSB0", "-s", "38400",
                    "-T", "127.0.0.1", "-t", "4532"]
    assert "-T" in rigctld_command({"model": 1}, path="/opt/hamlib/rigctld")


def test_the_model_list_is_parsed_from_hamlibs_own_format():
    """Rows built with print_model_list's format string (rigctl_parse.c):
    macro before status, and a macro longer than its column pushes the rest."""
    def row(i, mfg, model, version, macro, status):
        return "%6d  %-23s%-24s%-16s%-12s%s" % (i, mfg, model, version, macro, status)

    text = "\n".join([
        " Rig #  Mfg                    Model                   Version         Status      Macro",
        row(1, "Hamlib", "Dummy", "20230801.0", "RIG_MODEL_DUMMY", "Stable"),
        row(1035, "Yaesu", "FT-991A", "20211030.0", "RIG_MODEL_FT991", "Stable"),
        row(3073, "Icom", "IC-7300", "20240101.0", "RIG_MODEL_IC7300", "Stable"),
        row(2, "Hamlib", "NET rigctl", "20230101.0", "RIG_MODEL_NETRIGCTL", "Beta"),
    ])
    rows = parse_model_list(text)
    assert [r["model"] for r in rows] == [1, 1035, 3073, 2]
    ft = rows[1]
    assert (ft["make"], ft["name"], ft["macro"], ft["status"]) == (
        "Yaesu", "FT-991A", "RIG_MODEL_FT991", "Stable")
    assert rows[3]["name"] == "NET rigctl" and rows[3]["status"] == "Beta"
    # Older Hamlib has no macro column.
    old = parse_model_list("  1035  Yaesu                  FT-991A                 20211030.0      Stable\n")
    assert old[0]["name"] == "FT-991A" and old[0]["macro"] == "" and old[0]["status"] == "Stable"


@pytest.mark.asyncio
async def test_the_rig_test_button_reads_and_never_keys(rig):
    from types import SimpleNamespace

    from kissterm.config import Config
    from kissterm.core.radio import Radio

    fake, _ = rig
    config = Config()
    config.rigs = [{"name": "ft991a", "model": 1035, "host": "127.0.0.1", "port": fake.port}]
    radio = Radio(SimpleNamespace(config=config, save_config=lambda: True,
                                  events=SimpleNamespace(publish=lambda e: None)))
    assert await radio.test_rig("ft991a") == {"ok": True, "text": "OK  --  7.1015 MHz USB"}
    assert not any(line.startswith(("+T", "+G", "+F", "+M", "+U")) for line in fake.log)
    assert (await radio.test_rig("nope"))["ok"] is False
    await fake.stop()
    bad = await radio.test_rig("ft991a")
    assert bad["ok"] is False and bad["text"].startswith("FAILED")


@pytest.mark.skipif(shutil.which("rigctld") is None, reason="Hamlib's rigctld is not installed")
@pytest.mark.asyncio
async def test_against_hamlibs_dummy_rig(tmp_path):
    """The real daemon, model 1 (the dummy rig): the protocol as Hamlib
    speaks it, not as the fake does."""
    port = 45329
    process = await asyncio.create_subprocess_exec(
        *rigctld_command({"model": 1, "host": "127.0.0.1", "port": port}),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    client = RigctldClient("127.0.0.1", port, "dummy")
    try:
        for _ in range(50):
            try:
                await client.get_frequency()
                break
            except RigError:
                await asyncio.sleep(0.1)
        await client.set_frequency(7101500)
        await client.set_mode("USB", 0)
        assert (await client.state()).frequency == 7101500
        assert await client.chk_vfo() in (True, False)
    finally:
        await client.close()
        process.terminate()
        await process.wait()
