"""KISS framing -- the codec, with no I/O of its own.

KISS (Kantronics/Chepponis-Karn, 1987) is deliberately almost nothing: it wraps
each frame in ``FEND`` bytes, escapes any ``FEND``/``FESC`` inside, and puts one
type byte at the front. It carries no addressing, no acknowledgement, and no
connection concept -- which is precisely why kissterm has to bring its own
AX.25 state machine. Anything that talks about "a KISS connection" is confusing
the pipe with the protocol.

The type byte is ``port << 4 | command``. Ports are how one TNC exposes several
radio channels (Direwolf's ``CHANNEL 0/1``) over a single link.

Keeping the codec I/O-free means serial, TCP, and Bluetooth transports all
share exactly one implementation of the escaping rules, and the decoder can be
unit-tested by feeding it bytes a byte at a time -- which is how it actually
arrives from a serial port.
"""

from __future__ import annotations

import enum
from collections.abc import Iterator

FEND = 0xC0
FESC = 0xDB
TFEND = 0xDC
TFESC = 0xDD


class KissCommand(enum.IntEnum):
    DATA = 0x00
    TXDELAY = 0x01
    PERSIST = 0x02
    SLOTTIME = 0x03
    TXTAIL = 0x04
    FULLDUPLEX = 0x05
    SETHARDWARE = 0x06
    RETURN = 0x0F  # leave KISS mode


def encode(payload: bytes, port: int = 0, command: KissCommand = KissCommand.DATA) -> bytes:
    """Wrap ``payload`` in one KISS frame."""
    if not 0 <= port <= 15:
        raise ValueError(f"KISS port {port} out of range 0-15")
    out = bytearray([FEND, (port << 4) | int(command)])
    for byte in payload:
        if byte == FEND:
            out += bytes([FESC, TFEND])
        elif byte == FESC:
            out += bytes([FESC, TFESC])
        else:
            out.append(byte)
    out.append(FEND)
    return bytes(out)


def set_hardware(payload: bytes, port: int = 0) -> bytes:
    return encode(payload, port, KissCommand.SETHARDWARE)


def exit_kiss(port: int = 0) -> bytes:
    """The frame that returns a TNC to command mode."""
    return encode(b"", port, KissCommand.RETURN)


class KissDecoder:
    """Incremental KISS decoder. Feed it whatever arrives; take what completes.

    Tolerant by design, because a real serial line is not: back-to-back
    ``FEND``s (many TNCs send a leading one), empty frames, and a truncated
    frame at the moment a cable is unplugged all produce nothing rather than an
    exception. A decoder that raises on line noise takes the whole app down
    with it at the worst possible moment.
    """

    #: Guard against a stuck line silently eating memory. A KISS frame holding
    #: a legal AX.25 frame cannot approach this; anything that does is noise.
    MAX_FRAME = 8192

    def __init__(self) -> None:
        self._buf = bytearray()
        self._in_frame = False
        self._escaped = False
        self.overruns = 0

    def feed(self, data: bytes) -> Iterator[tuple[int, KissCommand, bytes]]:
        """Yield ``(port, command, payload)`` for each frame that completes."""
        for byte in data:
            if byte == FEND:
                if self._in_frame and self._buf:
                    frame = self._take()
                    if frame is not None:
                        yield frame
                self._buf.clear()
                self._escaped = False
                self._in_frame = True
                continue

            if not self._in_frame:
                continue  # bytes before the first FEND are not ours

            if self._escaped:
                self._buf.append(FEND if byte == TFEND else FESC if byte == TFESC else byte)
                self._escaped = False
            elif byte == FESC:
                self._escaped = True
            else:
                self._buf.append(byte)

            if len(self._buf) > self.MAX_FRAME:
                self.overruns += 1
                self._buf.clear()
                self._in_frame = False
                self._escaped = False

    def _take(self) -> tuple[int, KissCommand, bytes] | None:
        raw = bytes(self._buf)
        self._buf.clear()
        type_byte = raw[0]
        try:
            command = KissCommand(type_byte & 0x0F)
        except ValueError:
            return None
        return (type_byte >> 4) & 0x0F, command, raw[1:]

    def reset(self) -> None:
        self._buf.clear()
        self._in_frame = False
        self._escaped = False
