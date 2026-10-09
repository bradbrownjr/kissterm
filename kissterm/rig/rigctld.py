"""A client for Hamlib's `rigctld`: frequency, mode, PTT, SWR and the tuner.

**Protocol** (Hamlib `rigctld(1)`, "Extended Response Protocol"; cited in
`docs/SOURCES.md`). Every command is sent with a leading `+`, so the reply
is the command echoed as a header, one `Key: value` record per value, and a
last record `RPRT n` where n is 0 or a negative Hamlib error code. That
makes every reply self-delimiting: read lines until `RPRT`. The plain
protocol (no `+`) ends a `get` after its values with no marker, which cannot
be told from a slow rig.

    -> +f            <- get_freq:  /  Frequency: 14074000  /  RPRT 0
    -> +T 1          <- set_ptt: 1 /  RPRT 0

The long command name keeps its backslash (`+\\get_freq`); the one-letter
commands take only the `+`.

**`chk_vfo` is the one exception** (`rigctl_parse.c`, `rigctl_parse`'s
"Don't send command header on '\\chk_vfo' command" and the `cmd != 0xf0`
tests): under `+` it sends no header and no `RPRT`, only `ChkVFO: 0` (or 1,
when `rigctld` runs with `-o`). Waiting for an `RPRT` there would hang, so
`chk_vfo` reads one line. `0xf0` is rigctld's code for it.

**Reads never key.** The `set_*` methods change the rig; `set_ptt` and
`tune` transmit. Their callers hold the transmit gate (AGENTS.md); this
module does not know about it.

**No exception leaves a background task.** `poll` returns None and counts
the failure; the other methods raise `RigError`, which a caller catches.
A dropped connection is reopened on the next call, with the same backoff a
TCP transport uses, not by a timer of its own.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

#: Hamlib's error numbers by absolute value: `enum rig_errcode_e` in
#: `include/hamlib/rig.h` (Hamlib master, read 2026-10-09), the comment on
#: each, shortened.
ERROR_NAMES = {
    1: "invalid parameter", 2: "invalid configuration (serial...)", 3: "memory shortage",
    4: "function not implemented", 5: "communication timed out",
    6: "IO error, including open failed", 7: "internal Hamlib error", 8: "protocol error",
    9: "command rejected by the rig", 10: "performed, but argument truncated",
    11: "function not available", 12: "VFO not targetable", 13: "error talking on the bus",
    14: "collision on the bus", 15: "invalid pointer argument", 16: "invalid VFO",
    17: "argument out of domain", 18: "function deprecated", 19: "security error",
    20: "rig not powered on", 21: "limit exceeded", 22: "access denied (port in use?)",
}

DEFAULT_PORT = 4532
CONNECT_TIMEOUT = 3.0
COMMAND_TIMEOUT = 3.0
#: Seconds between reconnect attempts, doubling to the last.
BACKOFF = (1.0, 2.0, 5.0, 10.0)


class RigError(Exception):
    """A `rigctld` command that failed: the rig said no, or `rigctld` is
    unreachable. `code` is Hamlib's (negative), 0 for a connection failure."""

    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RigState:
    """What a poll read: nothing here required keying."""

    frequency: int
    mode: str
    passband: int
    ptt: bool | None = None  # None: the backend does not report it


def rigctld_command(rig: dict[str, Any], path: str = "") -> list[str]:
    """The argv that starts `rigctld` for a Rigs entry (the supervisor runs it).

    `-T` is always the entry's host: `rigctld` otherwise listens on every
    interface, and its port keys the radio for whoever reaches it."""
    argv = [path or str(rig.get("rigctld_path") or "rigctld"),
            "-m", str(int(rig["model"]))]
    if rig.get("device"):
        argv += ["-r", str(rig["device"])]
    if rig.get("speed"):
        argv += ["-s", str(int(rig["speed"]))]
    argv += ["-T", str(rig.get("host") or "127.0.0.1"),
             "-t", str(int(rig.get("port") or DEFAULT_PORT))]
    return argv


class RigctldClient:
    """One connection to one `rigctld`, commands serialised."""

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT, name: str = "") -> None:
        self.host = host
        self.port = port
        self.name = name or f"{host}:{port}"
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._failures = 0
        self._next_try = 0.0
        #: Failed commands and connects since creation, for `--doctor`/status.
        self.errors = 0
        self.last_error = ""

    @classmethod
    def from_rig(cls, rig: dict[str, Any]) -> "RigctldClient":
        return cls(str(rig.get("host") or "127.0.0.1"),
                   int(rig.get("port") or DEFAULT_PORT), str(rig.get("name", "")))

    # -- connection ---------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def _connect(self) -> None:
        if self.connected:
            return
        now = time.monotonic()
        if now < self._next_try:
            raise RigError(f"{self.name}: rigctld is not reachable (retrying shortly): "
                           f"{self.last_error}")
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), CONNECT_TIMEOUT)
        except (OSError, asyncio.TimeoutError) as exc:
            self._fail(f"cannot reach rigctld at {self.host}:{self.port}: {exc or 'timed out'}")
            raise RigError(self.last_error) from exc
        self._failures = 0
        log.debug("rigctld %s connected", self.name)

    def _fail(self, why: str) -> None:
        self.errors += 1
        self.last_error = why
        self._next_try = time.monotonic() + BACKOFF[min(self._failures, len(BACKOFF) - 1)]
        self._failures += 1
        log.warning("rigctld %s: %s", self.name, why)

    async def close(self) -> None:
        writer, self._reader, self._writer = self._writer, None, None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    # -- the protocol -------------------------------------------------------
    async def command(self, text: str, *, one_line: bool = False) -> dict[str, str]:
        """Send one command in extended mode; its `Key: value` records.

        `one_line`: `\\chk_vfo`, whose reply is a single line with no `RPRT`.

        Raises `RigError` on a negative RPRT, a timeout or a dropped
        connection (which is closed, so the next call reconnects)."""
        async with self._lock:
            await self._connect()
            assert self._reader is not None and self._writer is not None
            log.debug("rigctld %s -> %s", self.name, text)
            try:
                self._writer.write(f"+{text}\n".encode("ascii"))
                await self._writer.drain()
                records = await asyncio.wait_for(self._read_block(one_line), COMMAND_TIMEOUT)
            except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
                await self.close()
                why = ("rigctld closed the connection"
                       if isinstance(exc, asyncio.IncompleteReadError) else exc or "no reply")
                self._fail(f"{text.split()[0]}: {why}")
                raise RigError(self.last_error) from exc
        if one_line:
            key, sep, value = records[0].partition(": ")
            return {key if sep else "#0": value if sep else records[0]}
        return self._parse(text, records)

    async def _read_block(self, one_line: bool = False) -> list[str]:
        assert self._reader is not None
        lines: list[str] = []
        while True:
            raw = await self._reader.readline()
            if not raw:
                raise asyncio.IncompleteReadError(b"", None)
            line = raw.decode("ascii", "replace").rstrip("\r\n")
            log.debug("rigctld %s <- %s", self.name, line)
            lines.append(line)
            if one_line or line.startswith("RPRT "):
                return lines

    def _parse(self, text: str, lines: list[str]) -> dict[str, str]:
        try:
            code = int(lines[-1].split()[1])
        except (IndexError, ValueError):
            self._fail(f"{text.split()[0]}: unreadable reply {lines[-1]!r}")
            raise RigError(self.last_error)
        if code < 0:
            name = ERROR_NAMES.get(-code, "error")
            self.errors += 1
            self.last_error = f"{text.split()[0]}: {name} (RPRT {code})"
            log.warning("rigctld %s: %s", self.name, self.last_error)
            raise RigError(self.last_error, code)
        values: dict[str, str] = {}
        for index, line in enumerate(lines[1:-1]):
            key, sep, value = line.partition(": ")
            values[key if sep else f"#{index}"] = value if sep else line
        return values

    # -- reads (never key) --------------------------------------------------
    async def get_frequency(self) -> int:
        return int(float((await self.command("f"))["Frequency"]))

    async def get_mode(self) -> tuple[str, int]:
        values = await self.command("m")
        return values["Mode"], int(float(values.get("Passband", "0")))

    async def get_ptt(self) -> bool:
        values = await self.command("t")
        return next(iter(values.values())).strip() not in ("0", "")

    async def get_level(self, level: str) -> float:
        """A level such as `SWR` (a float, `RIG_LEVEL_SWR` in rig.h: "arg
        float [0.0 ... infinite]", read-only, where the backend has it) or `STRENGTH`. Raises `RigError` when unsupported."""
        values = await self.command(f"l {level}")
        return float(next(iter(values.values())))

    async def get_swr(self) -> float:
        return await self.get_level("SWR")

    async def chk_vfo(self) -> bool:
        """Whether `rigctld` runs in VFO mode (`-o`), where every command
        takes a VFO argument. kissterm starts it without `-o`; a `rigctld` the
        operator started with it cannot be driven by these commands."""
        values = await self.command("\\chk_vfo", one_line=True)
        return any(v.strip() == "1" for v in values.values())

    async def dump_state(self) -> list[str]:
        """The raw `\\dump_state` records; M6b reads tuner capability from it."""
        return list((await self.command("\\dump_state")).values())

    async def state(self) -> RigState:
        """Frequency, mode and, where reported, PTT. Reads only."""
        frequency = await self.get_frequency()
        mode, passband = await self.get_mode()
        try:
            ptt: bool | None = await self.get_ptt()
        except RigError:
            ptt = None
        return RigState(frequency, mode, passband, ptt)

    async def poll(self) -> RigState | None:
        """`state`, or None with the failure counted and logged. For
        background tasks: nothing is raised."""
        try:
            return await self.state()
        except RigError:
            return None
        except Exception as exc:  # noqa: BLE001 - a background task must not die
            self._fail(f"poll: {exc!r}")
            return None

    # -- changes the rig (the caller decides whether it may) ----------------
    async def set_frequency(self, hertz: int) -> None:
        """Tune. Changes the rig; no carrier."""
        await self.command(f"F {int(hertz)}")

    async def set_mode(self, mode: str, passband: int = 0) -> None:
        """Set the mode token (USB, PKTUSB...) and passband (0: rig default)."""
        await self.command(f"M {mode} {int(passband)}")

    async def set_tuner(self, on: bool) -> None:
        """Switch the built-in ATU in (`U TUNER 1`). Changes the rig; no carrier."""
        await self.command(f"U TUNER {1 if on else 0}")

    # -- transmits (the caller holds the gate) ------------------------------
    async def set_ptt(self, keyed: bool) -> None:
        """KEYS THE RADIO when `keyed`. The caller has checked the transmit
        gate at this moment; `False` always goes through."""
        await self.command(f"T {1 if keyed else 0}")

    async def tune(self) -> None:
        """Start the ATU's tuning cycle (`G TUNE`): a few seconds of CARRIER.
        The caller has checked the transmit gate at this moment."""
        await self.command("G TUNE")


_MODEL_ROW = re.compile(
    r"^\s*(\d+)\s+(.+?)\s{2,}(.+?)\s+(\d{8}\S*)\s*(?:(\S+?)\s*)?"
    r"(Alpha|Untested|Beta|Stable|Buggy)\s*$")


def parse_model_list(text: str) -> list[dict[str, Any]]:
    """`rigctl -l` as `{"model", "make", "name", "version", "macro", "status"}`.

    `print_model_list` in Hamlib's `tests/rigctl_parse.c` prints
    `"%6d  %-23s%-24s%-16s%-12s%s"` for id, manufacturer, model, version,
    **macro** then **status** (`rig_strstatus` in `src/misc.c`: Alpha,
    Untested, Beta, Stable, Buggy), though its header line says Status before
    Macro. Padding never truncates, so a macro longer than 12 characters
    (`RIG_MODEL_FT991`) runs straight into the status with no space. Older
    Hamlib prints no macro column at all. Rows are therefore split on the
    shape of the line, not on columns: a version starts with eight digits (a
    date), the status is one of the five words at the end, and whatever lies
    between is the macro. The header and any other line are skipped."""
    rows = []
    for line in text.splitlines():
        match = _MODEL_ROW.match(line)
        if match:
            rows.append({"model": int(match[1]), "make": match[2].strip(),
                         "name": match[3].strip(), "version": match[4],
                         "macro": match[5] or "", "status": match[6]})
    return rows


async def list_models(rigctl_path: str = "rigctl", timeout: float = 15.0) -> list[dict[str, Any]]:
    """The radios this Hamlib supports: runs `rigctl -l` once. A local read
    that touches no radio and no network; [] when `rigctl` is missing."""
    try:
        process = await asyncio.create_subprocess_exec(
            rigctl_path, "-l", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(process.communicate(), timeout)
    except (OSError, asyncio.TimeoutError) as exc:
        log.warning("rigctl -l: %s", exc or "timed out")
        return []
    return parse_model_list(out.decode("utf-8", "replace"))
