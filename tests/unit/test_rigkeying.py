"""Mercury and Direwolf given the shared rigctld (ROADMAP P3a M5c).

Expected strings come from Mercury's README ("-R ... -A ... ip:port") and
Direwolf's src/config.c ("PTT RIG model port; when model is 2, port would
host:port"), cited in launch/rigkeying.py and docs/SOURCES.md.
"""

from __future__ import annotations

import asyncio

import pytest

from kissterm import _isolate

_isolate.isolate()

from kissterm.config import Config  # noqa: E402
from kissterm.launch import rigkeying as rk  # noqa: E402
from kissterm.launch.supervisor import ProgramError, Supervisor  # noqa: E402

RIG = {"name": "ft991", "host": "127.0.0.1", "port": 4532}


def test_mercury_gets_netrigctl_model_and_endpoint(tmp_path):
    program = {"name": "m", "preset": "mercury", "args": "-p 8300", "keying": "rigctld"}
    out = rk.keyed_program(program, RIG, tmp_path, platform="linux")
    assert out["args"] == "-p 8300 -R 2 -A 127.0.0.1:4532"
    assert program["args"] == "-p 8300"  # the entry itself is untouched


def test_direwolf_gets_a_copy_with_ptt_rig_and_the_original_is_kept(tmp_path):
    conf = tmp_path / "my.conf"
    conf.write_text("ADEVICE default default\nCHANNEL 0\nPTT /dev/ttyUSB0 RTS")
    program = {"name": "dw", "preset": "direwolf", "args": f"-t 0 -c {conf}"}
    out = rk.keyed_program(program, RIG, tmp_path / "state", platform="linux")
    derived = tmp_path / "state" / "direwolf-dw.conf"
    assert f"-c {derived}" in out["args"] and str(conf) not in out["args"]
    text = derived.read_text()
    assert text.startswith("ADEVICE default default\nCHANNEL 0\nPTT /dev/ttyUSB0 RTS\n")
    assert text.rstrip().endswith("CHANNEL 0\nPTT RIG 2 127.0.0.1:4532")
    assert conf.read_text().endswith("RTS")


def test_direwolf_default_file_is_in_the_working_folder(tmp_path):
    (tmp_path / "direwolf.conf").write_text("ADEVICE x y\n")
    program = {"name": "dw", "preset": "direwolf", "args": "", "cwd": str(tmp_path)}
    out = rk.keyed_program(program, RIG, tmp_path / "s", platform="linux")
    assert "-c " in out["args"]


def test_direwolf_without_its_file_says_so(tmp_path):
    program = {"name": "dw", "preset": "direwolf", "args": f"-c {tmp_path}/none.conf"}
    with pytest.raises(rk.KeyingError, match="could not be read"):
        rk.keyed_program(program, RIG, tmp_path, platform="linux")


def test_direwolf_on_windows_is_refused_not_started(tmp_path):
    with pytest.raises(rk.KeyingError, match="Windows does not support Hamlib"):
        rk.keyed_program({"name": "dw", "preset": "direwolf"}, RIG, tmp_path, platform="win32")


def test_only_rigctld_keying_of_these_two_programs_is_touched():
    assert rk.wants_rigctld({"preset": "mercury", "keying": "rigctld"})
    assert not rk.wants_rigctld({"preset": "mercury", "keying": "own"})
    assert not rk.wants_rigctld({"preset": "vara-hf", "keying": "rigctld"})
    assert not rk.wants_rigctld(None)


def test_supervisor_waits_for_rigctld_and_reports_when_it_is_missing():
    sup = Supervisor()
    program = {"name": "m", "preset": "mercury", "args": "", "keying": "rigctld"}

    async def missing(rig):
        return "Nothing answers at 10.0.0.9:4532"

    sup.ensure_rigctld = missing
    with pytest.raises(ProgramError, match="rig control, which is not available"):
        asyncio.run(sup._with_rig_keying(program, RIG))

    async def ok(rig):
        return ""

    sup.ensure_rigctld = ok
    out = asyncio.run(sup._with_rig_keying(program, RIG))
    assert "-R 2 -A 127.0.0.1:4532" in out["args"]
    assert asyncio.run(sup._with_rig_keying(program, None)) is program
