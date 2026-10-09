"""The program supervisor, against a small Python script as the modem."""

from __future__ import annotations

import asyncio
import logging
import socket
import sys
from pathlib import Path

import pytest

from kissterm import _isolate

_isolate.isolate()

from kissterm.config import Config  # noqa: E402
from kissterm.launch import supervisor as sup  # noqa: E402
from kissterm.launch.supervisor import ProgramError, Supervisor, build_argv  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform.startswith("win"),
                                reason="POSIX process groups; Windows goes to ON-AIR-TESTS")

MODEM = str(Path(__file__).resolve().parents[1] / "fake_modem.py")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Port:
    """A transport stand-in whose open() is a real TCP connect."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.opened = 0

    async def open(self) -> None:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.close()
        self.opened += 1


def _program(port: int, *extra: str, **over) -> dict:
    # `path` is the script's interpreter, as a test would never put a script
    # itself on a path the way an operator puts a modem; arguments carry it.
    entry = {"name": "modem", "preset": "custom", "path": sys.executable,
             "args": f"{MODEM} {port} {' '.join(extra)}", "start_timeout": 10,
             "stop_on_exit": True}
    entry.update(over)
    return entry


def _config(program: dict) -> tuple[Config, dict]:
    config = Config()
    config.programs = [program]
    entry = {"name": "kiss", "kind": "tcp", "host": "127.0.0.1", "port": 1, "program": "modem"}
    return config, entry


@pytest.fixture
def supervisor():
    s = Supervisor()
    s.retry_backoff = (0.05,)
    s.stop_wait = 1.0
    yield s
    s.kill_all_now()


@pytest.mark.asyncio
async def test_a_refused_transport_starts_the_program_and_retries(supervisor):
    port = _free_port()
    config, entry = _config(_program(port, "--delay", "0.3"))
    transport = Port(port)
    await supervisor.open_transport(config, entry, transport)
    assert transport.opened == 1
    assert supervisor.status("modem")["started_by_kissterm"]
    await supervisor.stop_all()
    assert not supervisor.status("modem")["running"]


@pytest.mark.asyncio
async def test_a_transport_that_already_answers_is_used_and_left_alone(supervisor):
    port = _free_port()
    config, entry = _config(_program(port))
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", port)
    try:
        transport = Port(port)
        await supervisor.open_transport(config, entry, transport)
        assert transport.opened == 1
        assert supervisor.status("modem")["pid"] is None  # nothing was started
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_a_program_that_exits_early_ends_the_wait_with_its_code_and_output(supervisor):
    port = _free_port()
    config, entry = _config(_program(port, "--exit-code", "3"))
    with pytest.raises(ProgramError) as err:
        await supervisor.open_transport(config, entry, Port(port))
    assert "exited with code 3" in str(err.value)
    assert "fake modem failing" in str(err.value)


@pytest.mark.asyncio
async def test_a_program_that_never_answers_times_out_with_the_reason(supervisor):
    port = _free_port()
    config, entry = _config(_program(port, "--delay", "30", start_timeout=1))
    with pytest.raises(ProgramError) as err:
        await supervisor.open_transport(config, entry, Port(port))
    assert "did not answer within 1 s" in str(err.value)
    await supervisor.stop_all()


@pytest.mark.asyncio
async def test_a_transport_with_no_program_raises_what_open_raises(supervisor):
    config = Config()
    entry = {"name": "kiss", "kind": "tcp"}
    with pytest.raises(OSError):
        await supervisor.open_transport(config, entry, Port(_free_port()))


@pytest.mark.asyncio
async def test_a_transport_naming_a_missing_program_says_so(supervisor):
    entry = {"name": "kiss", "kind": "tcp", "program": "ghost"}
    with pytest.raises(ProgramError, match="not in the list"):
        await supervisor.open_transport(Config(), entry, Port(_free_port()))


@pytest.mark.asyncio
async def test_stop_is_polite_then_kills_a_program_that_ignores_it(supervisor):
    port = _free_port()
    config, entry = _config(_program(port, "--ignore-term"))
    await supervisor.open_transport(config, entry, Port(port))
    pid = supervisor.status("modem")["pid"]
    assert await supervisor.stop("modem")
    status = supervisor.status("modem")
    assert not status["running"] and status["exit_code"] is not None
    with pytest.raises(ProcessLookupError):
        import os
        os.kill(pid, 0)


@pytest.mark.asyncio
async def test_only_programs_with_stop_on_exit_are_stopped_with_kissterm(supervisor):
    port = _free_port()
    config, entry = _config(_program(port, stop_on_exit=False))
    await supervisor.open_transport(config, entry, Port(port))
    await supervisor.stop_all()
    assert supervisor.status("modem")["running"]
    await supervisor.stop("modem")


@pytest.mark.asyncio
async def test_a_program_that_dies_later_is_named_for_the_status_bar(supervisor):
    port = _free_port()
    config, entry = _config(_program(port))
    told = []
    supervisor.notify = lambda text, severity: told.append((text, severity))
    await supervisor.open_transport(config, entry, Port(port))
    assert supervisor.status_note(config, entry) == ""
    import os
    import signal
    os.killpg(supervisor.status("modem")["pid"], signal.SIGKILL)
    for _ in range(100):
        if supervisor.status_note(config, entry):
            break
        await asyncio.sleep(0.05)
    assert "modem exited with code" in supervisor.status_note(config, entry)
    assert told and told[0][1] == "error"


@pytest.mark.asyncio
async def test_output_goes_to_the_launch_logger(supervisor, caplog):
    port = _free_port()
    config, entry = _config(_program(port))
    with caplog.at_level(logging.INFO, logger="kissterm.launch"):
        await supervisor.open_transport(config, entry, Port(port))
        await asyncio.sleep(0.1)
    assert any("fake modem listening" in r.getMessage() for r in caplog.records)
    await supervisor.stop_all()


@pytest.mark.asyncio
async def test_arguments_are_never_given_to_a_shell(supervisor, tmp_path):
    """A `;` in the arguments is one argument, not a second command."""
    marker = tmp_path / "pwned"
    program = {"name": "echo", "path": sys.executable,
               "args": f"-c pass ; touch {marker}", "start_timeout": 2}
    await supervisor.start(program)
    await asyncio.sleep(0.3)
    assert not marker.exists()


def test_build_argv_splits_with_shlex_and_wraps_wine(monkeypatch):
    monkeypatch.setattr(sup.shutil, "which", lambda name: "/usr/bin/wine")
    argv = build_argv({"name": "vara", "path": "/x/VARA.exe", "args": '-a "b c"', "wine": True},
                      platform="linux")
    assert argv == ["/usr/bin/wine", "/x/VARA.exe", "-a", "b c"]
    assert build_argv({"name": "m", "path": "/usr/bin/mercury", "args": "-p 8300"},
                      platform="linux") == ["/usr/bin/mercury", "-p", "8300"]


def test_wine_missing_and_bad_programs_are_refused_in_words(monkeypatch):
    monkeypatch.setattr(sup.shutil, "which", lambda name: None)
    with pytest.raises(ProgramError, match="wine is not installed"):
        build_argv({"name": "vara", "path": "/x/VARA.exe", "wine": True}, platform="linux")
    with pytest.raises(ProgramError, match="no program file"):
        build_argv({"name": "x", "path": ""})
    with pytest.raises(ProgramError, match="not valid"):
        build_argv({"name": "x", "path": "/a", "args": '"unclosed'}, platform="linux")


@pytest.mark.asyncio
async def test_a_missing_or_non_executable_file_is_refused_before_starting(supervisor, tmp_path):
    with pytest.raises(ProgramError, match="is not a file"):
        await supervisor.start({"name": "x", "path": str(tmp_path / "nope")})
    plain = tmp_path / "plain"
    plain.write_text("x")
    with pytest.raises(ProgramError, match="not executable"):
        await supervisor.start({"name": "x", "path": str(plain)})
