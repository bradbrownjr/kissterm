"""Starting, watching and stopping the modem program beside the radio.

ROADMAP P3a. A transport entry may name a Programs entry (`program`). When
that transport is opened -- at launch, in Settings, a switch -- and not
before, kissterm makes sure the program is running:

1. **Try the transport first.** If it connects, something is already
   listening (the operator started the modem, or an earlier run did) and
   kissterm uses it and leaves it alone. Only a process kissterm started is
   ever stopped.
2. **If it is refused, start the program** and retry the same connect with a
   short backoff until the entry's `start_timeout`. A program that exits
   before the transport answers ends the wait at once, with its exit code
   and last output, not a timeout.

That is the transport's ordinary connect, not a probe, so discovery's rule
(AGENTS.md: it never touches VARA's ports and never starts anything) is
untouched. The supervisor never runs on a timer.

**Never a shell.** The command line is `[wine] <path> <args...>` with the
arguments split by `shlex`, handed to `asyncio.create_subprocess_exec`.
Nothing is interpreted by `/bin/sh` or `cmd.exe`.

**Stopping is polite, then not.** POSIX: the program leads its own session,
so SIGTERM goes to its whole group (Wine's helper processes included), then
SIGKILL after `STOP_WAIT`. Windows: the program starts in a new process
group, receives CTRL_BREAK, then `terminate()`. Output of stdout and stderr
goes to the `kissterm.launch` logger (sanitized: AGENTS.md "Untrusted
input"), the last lines kept for an error message.

**A program that dies while its transport is open** is shown as the
transport DOWN with the program's exit code (`status_note`), never as an RF
problem. kissterm does not restart it by itself: the operator decides.

**Restart and Shut down never wait on a child** (`core/restart.py`): they
call `stop_all`, bounded, and the watchdog still fires. A crash cannot be
helped by `finally`, so an `atexit` handler kills what kissterm started
(`kill_all_now`).

A program that transmits by itself (Direwolf's own beacons, VARA answering
while `LISTEN ON`) is outside the transmit gate; the form says so.
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import logging
import os
import shlex
import shutil
import signal
import sys
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..monitor import sanitize

log = logging.getLogger("kissterm.launch")

#: Seconds a program gets to leave after the polite signal before it is killed.
STOP_WAIT = 4.0
#: Seconds between connect retries, ending on the last value.
RETRY_BACKOFF = (0.5, 1.0, 1.0, 2.0)
#: Output lines kept per program for an error message.
TAIL_LINES = 20
DEFAULT_START_TIMEOUT = 30


class ProgramError(Exception):
    """A program that could not be started or did not make its transport
    answer. The message is the operator's, in plain words."""


@dataclass
class Managed:
    """One program kissterm started."""

    name: str
    process: asyncio.subprocess.Process
    argv: list[str]
    stop_on_exit: bool
    started: float = field(default_factory=time.monotonic)
    exit_code: int | None = None
    tail: deque = field(default_factory=lambda: deque(maxlen=TAIL_LINES))
    tasks: list[asyncio.Task] = field(default_factory=list)
    stopping: bool = False

    @property
    def running(self) -> bool:
        return self.exit_code is None


def program_for(config, entry: dict[str, Any]) -> dict[str, Any] | None:
    """The Programs entry a transport entry names, or None."""
    name = str(entry.get("program") or "")
    return next((p for p in config.programs if p.get("name") == name), None) if name else None


def build_argv(program: dict[str, Any], *, platform: str | None = None) -> list[str]:
    """The command line for a Programs entry: `[wine] path args...`.

    `platform` is `sys.platform` unless a test says otherwise. Raises
    `ProgramError` for a program that cannot be launched here, saying why."""
    platform = platform or sys.platform
    path = str(program.get("path") or "").strip()
    if not path:
        raise ProgramError(f"{program.get('name', 'The program')} has no program file set.")
    argv = [path]
    if program.get("wine") and not platform.startswith("win"):
        wine = shutil.which("wine")
        if wine is None:
            raise ProgramError(
                f"{program.get('name')} runs under Wine, and wine is not installed "
                "(or not on PATH).")
        argv = [wine, path]
    text = str(program.get("args") or "")
    try:
        argv += shlex.split(text, posix=not platform.startswith("win"))
    except ValueError as exc:
        raise ProgramError(f"{program.get('name')}'s arguments are not valid: {exc}") from exc
    return argv


def _check_executable(program: dict[str, Any]) -> None:
    """The file to run must exist (a bare name is looked up on PATH) and,
    off Windows and outside Wine, be executable."""
    target = str(program.get("path") or "").strip()
    found = target if os.path.isfile(target) else shutil.which(target)
    if not found:
        raise ProgramError(f"{program.get('name')}: {target!r} is not a file. Check its path.")
    wine_run = bool(program.get("wine")) and not sys.platform.startswith("win")
    if not wine_run and not sys.platform.startswith("win") and not os.access(found, os.X_OK):
        raise ProgramError(f"{program.get('name')}: {found!r} is not executable.")


class Supervisor:
    """The programs kissterm started, in this process."""

    def __init__(self) -> None:
        self._running: dict[str, Managed] = {}
        #: `(text, severity_name)` for the front end; the core sets it.
        self.notify: Callable[[str, str], None] | None = None
        #: Seconds, overridable by tests.
        self.stop_wait = STOP_WAIT
        self.retry_backoff = RETRY_BACKOFF

    # -- asking ------------------------------------------------------------
    def status(self, name: str) -> dict[str, Any]:
        managed = self._running.get(name)
        if managed is None:
            return {"running": False, "started_by_kissterm": False, "exit_code": None, "pid": None}
        return {"running": managed.running, "started_by_kissterm": True,
                "exit_code": managed.exit_code, "pid": managed.process.pid}

    def status_note(self, config, entry: dict[str, Any] | None) -> str:
        """For a transport's status field: "" while the program is fine or
        not kissterm's, else the plain words for a program that died."""
        if not entry:
            return ""
        name = str(entry.get("program") or "")
        managed = self._running.get(name)
        if managed is None or managed.running or managed.stopping:
            return ""
        return f"{name} exited with code {managed.exit_code}"

    # -- opening a transport -----------------------------------------------
    async def open_transport(self, config, entry: dict[str, Any], transport) -> None:
        """`transport.open()`, starting the entry's program first if the
        transport is refused (module docstring). Raises what `open()` raises
        when there is no program to start, else `ProgramError`."""
        program = program_for(config, entry)
        try:
            await transport.open()
            if program is not None and program["name"] not in self._running:
                log.info("%s is already answering; leaving it alone", program["name"])
            return
        except Exception as first:  # noqa: BLE001 - decide below
            if program is None:
                if entry.get("program"):
                    raise ProgramError(
                        f"{entry.get('name')} names program {entry.get('program')!r}, "
                        "which is not in the list. Edit the transport.") from first
                raise
            failure: BaseException = first
        managed = self._running.get(program["name"])
        if managed is None or not managed.running:
            managed = await self.start(program)
        timeout = float(program.get("start_timeout") or DEFAULT_START_TIMEOUT)
        deadline = time.monotonic() + timeout
        attempt = 0
        while True:
            if not managed.running:
                raise ProgramError(self._exited_message(managed))
            if time.monotonic() >= deadline:
                raise ProgramError(
                    f"Started {program['name']}, but {entry.get('name')} did not answer "
                    f"within {timeout:g} s: {failure}")
            await asyncio.sleep(self.retry_backoff[min(attempt, len(self.retry_backoff) - 1)])
            attempt += 1
            try:
                await transport.open()
                log.info("%s answered after %d tries", entry.get("name"), attempt)
                return
            except Exception as exc:  # noqa: BLE001 - keep waiting
                failure = exc

    # -- starting and stopping ---------------------------------------------
    async def start(self, program: dict[str, Any]) -> Managed:
        """Start a Programs entry; `ProgramError` says why not."""
        name = str(program.get("name"))
        existing = self._running.get(name)
        if existing is not None and existing.running:
            return existing
        argv = build_argv(program)
        _check_executable(program)
        kwargs: dict[str, Any] = {}
        if sys.platform.startswith("win"):
            import subprocess

            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        cwd = str(program.get("cwd") or "") or None
        log.info("starting %s: %s", name, " ".join(argv))
        try:
            process = await asyncio.create_subprocess_exec(
                *argv, cwd=cwd, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **kwargs)
        except OSError as exc:
            raise ProgramError(f"Could not start {name}: {exc}") from exc
        managed = Managed(name, process, argv, bool(program.get("stop_on_exit", True)))
        self._running[name] = managed
        for stream, label in ((process.stdout, "out"), (process.stderr, "err")):
            managed.tasks.append(asyncio.ensure_future(self._pump(managed, stream, label)))
        managed.tasks.append(asyncio.ensure_future(self._watch(managed)))
        return managed

    async def _pump(self, managed: Managed, stream, label: str) -> None:
        try:
            while stream is not None:
                raw = await stream.readline()
                if not raw:
                    return
                line = sanitize(raw[:400], keep_newlines=False).strip()
                if line:
                    managed.tail.append(line)
                    log.info("%s %s: %s", managed.name, label, line)
        except Exception as exc:  # noqa: BLE001 - never raise out of a background task
            log.warning("%s: output reader stopped: %s", managed.name, exc)

    async def _watch(self, managed: Managed) -> None:
        try:
            code = await managed.process.wait()
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: wait failed: %s", managed.name, exc)
            return
        managed.exit_code = code
        if managed.stopping:
            log.info("%s stopped (code %s)", managed.name, code)
            return
        text = self._exited_message(managed)
        log.warning("%s", text)
        if self.notify is not None:
            with contextlib.suppress(Exception):
                self.notify(text, "error")

    @staticmethod
    def _exited_message(managed: Managed) -> str:
        last = f" Last output: {managed.tail[-1]}" if managed.tail else ""
        return f"{managed.name} exited with code {managed.exit_code}.{last}"

    async def stop(self, name: str) -> bool:
        """Stop a program kissterm started: polite, then not. False if it
        was not running or not kissterm's."""
        managed = self._running.get(name)
        if managed is None or not managed.running:
            return False
        managed.stopping = True
        self._signal(managed, force=False)
        try:
            await asyncio.wait_for(managed.process.wait(), self.stop_wait)
        except asyncio.TimeoutError:
            log.warning("%s did not leave after %g s; killing it", name, self.stop_wait)
            self._signal(managed, force=True)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(managed.process.wait(), self.stop_wait)
        for task in managed.tasks:
            if task is not asyncio.current_task():
                task.cancel()
        return True

    async def stop_all(self, timeout: float | None = None) -> None:
        """Stop every program kissterm started with `stop_on_exit`, in
        parallel, bounded (Restart never waits on a child)."""
        names = [n for n, m in self._running.items() if m.running and m.stop_on_exit]
        if not names:
            return
        bound = timeout if timeout is not None else self.stop_wait * 2 + 1
        with contextlib.suppress(Exception):
            await asyncio.wait_for(
                asyncio.gather(*(self.stop(n) for n in names), return_exceptions=True), bound)

    def kill_all_now(self) -> None:
        """Synchronous last resort (`atexit`, a crash): kill what kissterm
        started with `stop_on_exit`. Idempotent."""
        for managed in self._running.values():
            if managed.running and managed.stop_on_exit:
                managed.stopping = True
                with contextlib.suppress(Exception):
                    self._signal(managed, force=True)

    @staticmethod
    def _signal(managed: Managed, *, force: bool) -> None:
        process = managed.process
        if process.returncode is not None:
            return
        try:
            if sys.platform.startswith("win"):
                if force:
                    process.kill()
                else:
                    process.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            else:
                os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        except OSError as exc:
            log.warning("%s: could not signal it: %s", managed.name, exc)


_shared: Supervisor | None = None


def shared() -> Supervisor:
    """The one supervisor of this process, so the launch and the core see
    the same programs. Registers the crash cleanup once."""
    global _shared
    if _shared is None:
        _shared = Supervisor()
        atexit.register(_shared.kill_all_now)
    return _shared


def reset_for_tests() -> None:
    global _shared
    if _shared is not None:
        _shared.kill_all_now()
    _shared = None
