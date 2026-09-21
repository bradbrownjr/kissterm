"""YAPP 1.1 client transfers over an already-connected byte-stream link.

This is deliberately a client primitive, not a file server: callers choose a
local file to upload or a local directory into which an explicitly requested
download may be saved.  It never opens, executes, or advertises a file.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

SOH, STX, ETX, EOT, ENQ, ACK, NAK, CAN = 1, 2, 3, 4, 5, 6, 21, 24
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class YappError(RuntimeError):
    """The peer declined, cancelled, malformed, or timed out a transfer."""


@dataclass(frozen=True, slots=True)
class YappResult:
    path: Path
    size: int


class _Wire:
    def __init__(self, link) -> None:
        self.link = link
        self.data = bytearray()
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
        if len(payload) > 255:
            if kind != STX or len(payload) != 256:
                raise ValueError("YAPP control payload is limited to 255 bytes")
        length = 0 if kind == STX and len(payload) == 256 else len(payload)
        await self.link.send(bytes((kind, length)) + payload)

    async def packet(self, timeout: float) -> tuple[int, bytes]:
        while len(self.data) < 2:
            await self._wait(timeout)
        kind, length = self.data[0], self.data[1]
        actual = 256 if kind == STX and length == 0 else length
        while len(self.data) < actual + 2:
            await self._wait(timeout)
        payload = bytes(self.data[2 : actual + 2])
        del self.data[: actual + 2]
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
    if got_kind == CAN:
        raise YappError("YAPP peer cancelled: " + got_payload.decode("ascii", "replace"))
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
            while chunk := stream.read(256):
                await wire.send(STX, chunk)
        await wire.send(ETX, b"\x01")
        await _expect(wire, ACK, b"\x03", timeout)
        await wire.send(EOT, b"\x01")
        await _expect(wire, ACK, b"\x04", timeout)
        return YappResult(path, size)
    finally:
        wire.close()


async def receive_file(link, directory: str | Path, *, timeout: float = 30.0) -> YappResult:
    """Receive one sender-initiated YAPP 1.1 file into an existing directory."""
    target_dir = Path(directory).expanduser().resolve()
    if not target_dir.is_dir():
        raise ValueError("receive directory does not exist")
    wire = _Wire(link)
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
        target = (target_dir / name).resolve()
        if not target.is_relative_to(target_dir):
            raise YappError("YAPP filename escapes receive directory")
        temp = target.with_name(f".{target.name}.part")
        await wire.send(ACK, b"\x02")
        written = 0
        with temp.open("wb") as stream:
            while True:
                kind, payload = await wire.packet(timeout)
                if kind == STX:
                    if written + len(payload) > expected:
                        raise YappError("YAPP file exceeds advertised size")
                    stream.write(payload)
                    written += len(payload)
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
