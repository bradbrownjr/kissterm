"""AutoBIN client transfers over an already-connected byte-stream link.

AutoBIN is deliberately available only after the operator explicitly starts a
send or receive.  A ``#BIN#`` string arriving in ordinary terminal text must
never turn an unauthenticated RF peer into a local-file writer.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import re
from dataclasses import dataclass
from pathlib import Path


_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class AutoBinError(RuntimeError):
    """The peer declined, malformed, interrupted, or timed out a transfer."""


@dataclass(frozen=True, slots=True)
class AutoBinResult:
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

    async def send(self, data: bytes) -> None:
        await self.link.send(data)

    async def wait(self, timeout: float) -> None:
        self.event.clear()
        try:
            await asyncio.wait_for(self.event.wait(), timeout)
        except TimeoutError as exc:
            raise AutoBinError("AutoBIN peer did not respond before the timeout") from exc
        if self.closed:
            raise AutoBinError("AutoBIN transfer closed")


def crc16(data: bytes, initial: int = 0) -> int:
    """The historical AutoBIN CRC: CCITT polynomial, MSB first, initial 0."""
    crc = initial
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


async def _line_containing(wire: _Wire, marker: bytes, timeout: float) -> bytes:
    """Return a CR-terminated line containing ``marker``, preserving leftovers."""
    while True:
        while (end := wire.data.find(b"\r")) >= 0:
            line = bytes(wire.data[:end])
            del wire.data[: end + 1]
            if marker in line:
                return line
        await wire.wait(timeout)


def _parse_header(line: bytes) -> tuple[int, int | None, str]:
    marker = line.find(b"#BIN#")
    if marker < 0 or (marker and line[marker - 1] != 13):
        raise AutoBinError("invalid AutoBIN header")
    body = line[marker + 5 :]
    digits = re.match(rb"[0-9]+", body)
    if digits is None:
        raise AutoBinError("AutoBIN header has no byte count")
    size = int(digits.group())
    tail = body[digits.end() :]
    crc: int | None = None
    crc_match = re.match(rb"#\|([0-9]+)", tail)
    if crc_match:
        crc = int(crc_match.group(1))
    # Names are optional.  Extended implementations commonly include metadata
    # before the final '#', so only accept the final path component as a name.
    candidate = tail.rsplit(b"#", 1)[-1].lstrip(b"$")
    try:
        name = candidate.decode("ascii").replace("\\", "/").rsplit("/", 1)[-1]
    except UnicodeDecodeError:
        name = ""
    return size, crc, name if _SAFE_NAME.fullmatch(name) else "autobin.bin"


def _destination(directory: Path, name: str) -> Path:
    target = (directory / name).resolve()
    if not target.is_relative_to(directory):
        raise AutoBinError("AutoBIN filename escapes receive directory")
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    for index in range(1, 10_000):
        candidate = (directory / f"{stem}-{index}{suffix}").resolve()
        if candidate.is_relative_to(directory) and not candidate.exists():
            return candidate
    raise AutoBinError("too many files with this AutoBIN name")


async def send_file(link, source: str | Path, *, timeout: float = 30.0) -> AutoBinResult:
    """Upload one regular local file after the peer accepts its AutoBIN header."""
    path = Path(source).expanduser().resolve()
    if not path.is_file() or not _SAFE_NAME.fullmatch(path.name):
        raise ValueError("choose a regular file with an ASCII-safe filename")
    size = path.stat().st_size
    checksum = 0
    with path.open("rb") as stream:
        while chunk := stream.read(8192):
            checksum = crc16(chunk, checksum)
    header = f"#BIN#{size}#|{checksum}#{path.name}\r".encode("ascii")
    wire = _Wire(link)
    try:
        await wire.send(header)
        reply = await _line_containing(wire, b"#", timeout)
        if b"#NO#" in reply:
            raise AutoBinError("AutoBIN peer declined: " + reply.decode("ascii", "replace"))
        if b"#OK#" not in reply:
            raise AutoBinError("AutoBIN peer did not accept the file")
        with path.open("rb") as stream:
            while chunk := stream.read(8192):
                await wire.send(chunk)
        return AutoBinResult(path, size)
    finally:
        wire.close()


async def receive_file(link, directory: str | Path, *, timeout: float = 30.0) -> AutoBinResult:
    """Receive one operator-requested AutoBIN file into an existing directory."""
    target_dir = Path(directory).expanduser().resolve()
    if not target_dir.is_dir():
        raise ValueError("receive directory does not exist")
    wire = _Wire(link)
    temp: Path | None = None
    try:
        header = await _line_containing(wire, b"#BIN#", timeout)
        expected, expected_crc, name = _parse_header(header)
        target = _destination(target_dir, name)
        temp = target.with_name(f".{target.name}.part")
        await wire.send(b"#OK#\r")
        written = 0
        checksum = 0
        with temp.open("wb") as stream:
            while written < expected:
                if not wire.data:
                    await wire.wait(timeout)
                    continue
                chunk = bytes(wire.data[: expected - written])
                del wire.data[: len(chunk)]
                stream.write(chunk)
                written += len(chunk)
                checksum = crc16(chunk, checksum)
        if expected_crc is not None and checksum != expected_crc:
            raise AutoBinError("AutoBIN checksum did not match")
        os.replace(temp, target)
        temp = None
        return AutoBinResult(target, written)
    finally:
        if temp is not None:
            with contextlib.suppress(FileNotFoundError):
                temp.unlink()
        wire.close()
