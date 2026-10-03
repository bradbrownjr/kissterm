"""YAPP 1.1 client transfers over an already-connected byte-stream link.

This is deliberately a client primitive, not a file server: callers choose a
local file to upload or a local directory into which an explicitly requested
download may be saved.  It never opens, executes, or advertises a file.

**Two packet shapes, from LinBPQ's `BBSUtilities.c`** (`YAPPSendFile`,
`YAPPSendData`, `ProcessYAPPMessage`; docs/SOURCES.md):

- Control packets are exactly two bytes, a type and a code: `ENQ 1` (send
  init), `ACK 1` (ready), `ACK 2` (header accepted), `ETX 1` (end of data),
  `ACK 3`, `EOT 1` (end of transfer), `ACK 4`, `ACK 5` (cancel accepted).
- `SOH`, `STX`, `NAK` and `CAN` carry a length byte and that many bytes:
  the header `SOH len name NUL size NUL`, data `STX len data`, a refusal
  `NAK len reason`, a cancel `CAN len reason`.

Until 2026-10-03 every packet was read and written as type, length,
payload, so `ENQ 1` looked like the start of a three-byte packet and the
receiver waited for a byte that never came: WS1EC-2 sent its `ENQ 1` and
the download timed out (operator, over the air). Sender and receiver had
the same mistake, which is why the loopback test passed;
`tests/unit/test_yapp.py` now plays BPQ's exact bytes.

BPQ reads a data length of 0 as no data, not 256, and sends at most
`paclen - 2` bytes a packet; the sender here keeps to 255 and below.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

SOH, STX, ETX, EOT, ENQ, ACK, NAK, CAN = 1, 2, 3, 4, 5, 6, 21, 24
#: The packet types that carry a length byte; every other is two bytes.
_LENGTHED = frozenset((SOH, STX, NAK, CAN))
#: What a sender's first packet is: `ENQ 1`, send init.
SEND_INIT = bytes((ENQ, 1))
#: Data bytes per STX packet: under BPQ's 256-byte paclen less its header.
CHUNK = 250
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class YappError(RuntimeError):
    """The peer declined, cancelled, malformed, or timed out a transfer."""


@dataclass(frozen=True, slots=True)
class YappResult:
    path: Path
    size: int


class _Wire:
    def __init__(self, link, initial: bytes = b"") -> None:
        self.link = link
        self.data = bytearray(initial)
        self.event = asyncio.Event()
        self.closed = False
        link.on_data.append(self._on_data)

    def _on_data(self, data: bytes) -> None:
        self.data.extend(data)
        self.event.set()

    def close(self) -> None:
        with contextlib.suppress(ValueError):
            self.link.on_data.remove(self._on_data)
        self.closed = True
        self.event.set()

    async def send(self, kind: int, payload: bytes = b"") -> None:
        """A lengthed packet (`SOH`, `STX`, `NAK`, `CAN`) with `payload`, or
        a control packet whose one-byte code `payload` is."""
        if kind in _LENGTHED:
            if len(payload) > 255:
                raise ValueError("a YAPP packet carries at most 255 bytes")
            await self.link.send(bytes((kind, len(payload))) + payload)
            return
        if len(payload) != 1:
            raise ValueError("a YAPP control packet is a type and one code byte")
        await self.link.send(bytes((kind,)) + payload)

    async def packet(self, timeout: float) -> tuple[int, bytes]:
        """The next packet: (type, payload) for a lengthed one, (type,
        code) for a control one, the code as a one-byte payload."""
        while len(self.data) < 2:
            await self._wait(timeout)
        kind = self.data[0]
        if kind not in _LENGTHED:
            code = bytes(self.data[1:2])
            del self.data[:2]
            return kind, code
        length = self.data[1]
        while len(self.data) < length + 2:
            await self._wait(timeout)
        payload = bytes(self.data[2 : length + 2])
        del self.data[: length + 2]
        return kind, payload

    async def _wait(self, timeout: float) -> None:
        self.event.clear()
        try:
            await asyncio.wait_for(self.event.wait(), timeout)
        except TimeoutError as exc:
            raise YappError("YAPP peer did not respond before the crash timer") from exc
        if self.closed:
            raise YappError("YAPP transfer closed")


async def _expect(wire: _Wire, kind: int, payload: bytes, timeout: float) -> None:
    got_kind, got_payload = await wire.packet(timeout)
    if got_kind in (CAN, NAK):
        reason = got_payload.decode("ascii", "replace").strip()
        what = "cancelled" if got_kind == CAN else "refused"
        raise YappError(f"YAPP peer {what}" + (f": {reason}" if reason else ""))
    if (got_kind, got_payload) != (kind, payload):
        raise YappError(f"unexpected YAPP packet {got_kind:#x}/{got_payload!r}")


async def send_file(link, source: str | Path, *, timeout: float = 30.0) -> YappResult:
    """Upload one regular local file via YAPP 1.1 after the peer is ready."""
    path = Path(source).expanduser().resolve()
    if not path.is_file() or not _SAFE_NAME.fullmatch(path.name):
        raise ValueError("choose a regular file with an ASCII-safe filename")
    size = path.stat().st_size
    wire = _Wire(link)
    try:
        await wire.send(ENQ, b"\x01")
        await _expect(wire, ACK, b"\x01", timeout)
        header = path.name.encode("ascii") + b"\0" + str(size).encode("ascii") + b"\0"
        await wire.send(SOH, header)
        await _expect(wire, ACK, b"\x02", timeout)
        with path.open("rb") as stream:
            while chunk := stream.read(CHUNK):
                await wire.send(STX, chunk)
        await wire.send(ETX, b"\x01")
        await _expect(wire, ACK, b"\x03", timeout)
        await wire.send(EOT, b"\x01")
        await _expect(wire, ACK, b"\x04", timeout)
        return YappResult(path, size)
    finally:
        wire.close()


def starts_download(data: bytes) -> bool:
    """Whether `data`, the first bytes after the operator asked for a file,
    is a YAPP sender's send init. BPQ sends `ENQ 1` alone, flushed, in its
    own frame (`YAPPSendFile`); text never begins with ENQ."""
    return data.startswith(SEND_INIT)


def _destination(directory: Path, name: str) -> Path:
    """Where a received file goes: `name`, or `name-1.ext` and so on when
    that is taken. Every download lands in one folder (Files > Downloads),
    so writing over an earlier file of the same name would lose it; AutoBIN
    does the same (`autobin._destination`)."""
    target = (directory / name).resolve()
    if not target.is_relative_to(directory):
        raise YappError("YAPP filename escapes receive directory")
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    for index in range(1, 10_000):
        candidate = (directory / f"{stem}-{index}{suffix}").resolve()
        if candidate.is_relative_to(directory) and not candidate.exists():
            return candidate
    raise YappError("too many files with this YAPP name")


async def receive_file(
    link,
    directory: str | Path,
    *,
    timeout: float = 30.0,
    initial: bytes = b"",
    progress: Callable[[str, int, int], None] | None = None,
) -> YappResult:
    """Receive one sender-initiated YAPP 1.1 file into an existing directory.
    `initial` is what already arrived (the `ENQ 1` that showed a download
    starting, `starts_download`), read before anything new. `progress` is
    called with the file's name, bytes so far and its size, once the header
    is in and after each data packet."""
    target_dir = Path(directory).expanduser().resolve()
    if not target_dir.is_dir():
        raise ValueError("receive directory does not exist")
    wire = _Wire(link, initial)
    temp: Path | None = None
    try:
        await _expect(wire, ENQ, b"\x01", timeout)
        await wire.send(ACK, b"\x01")
        kind, header = await wire.packet(timeout)
        if kind != SOH or header.count(b"\0") < 2:
            raise YappError("invalid YAPP file header")
        raw_name, raw_size, _rest = header.split(b"\0", 2)
        try:
            name, expected = raw_name.decode("ascii"), int(raw_size.decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise YappError("invalid YAPP filename or size") from exc
        if expected < 0 or not _SAFE_NAME.fullmatch(name):
            raise YappError("unsafe YAPP filename or size")
        target = _destination(target_dir, name)
        temp = target.with_name(f".{target.name}.part")
        await wire.send(ACK, b"\x02")
        written = 0
        if progress is not None:
            progress(name, 0, expected)
        with temp.open("wb") as stream:
            while True:
                kind, payload = await wire.packet(timeout)
                if kind == STX:
                    if written + len(payload) > expected:
                        raise YappError("YAPP file exceeds advertised size")
                    stream.write(payload)
                    written += len(payload)
                    if progress is not None:
                        progress(name, written, expected)
                    continue
                if kind != ETX or payload != b"\x01" or written != expected:
                    raise YappError("YAPP file ended unexpectedly")
                break
        os.replace(temp, target)
        temp = None
        await wire.send(ACK, b"\x03")
        await _expect(wire, EOT, b"\x01", timeout)
        await wire.send(ACK, b"\x04")
        return YappResult(target, written)
    finally:
        if temp is not None:
            with contextlib.suppress(FileNotFoundError):
                temp.unlink()
        wire.close()
