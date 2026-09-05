"""AGWPE (AGW Packet Engine) raw-frame transport -- Direwolf's other TCP port.

AGWPE is SV2AGW's decades-old TCP protocol for talking to a packet engine.
Direwolf speaks it on port 8000 alongside its KISS port 8001; UZ7HO
SoundModem speaks it as its primary interface. Every message, in both
directions, is a fixed 36-byte little-endian header followed by however many
payload bytes the header's length field says follow it. There is no framing
byte and no escaping -- unlike KISS, the length field *is* the framing, which
means a single dropped or duplicated byte desynchronizes the whole stream
until the connection is torn down and reopened. That fragility is one reason
kissterm treats TCP KISS (`tcp_kiss.py`) as the preferred path to Direwolf and
keeps this module around only for the TNCs (older UZ7HO builds, some AGW-only
software) that never learned KISS.

Header layout (36 bytes, little-endian, all reserved bytes sent as zero)::

    offset  size  field
    0       1     Port           radio port number (0-based)
    1       3     reserved
    4       1     DataKind       one ASCII byte selecting the message type
    5       1     reserved
    6       1     PID            AX.25 PID, or 0 where not applicable
    7       1     reserved
    8       10    CallFrom       source callsign, NUL-padded ASCII
    18      10    CallTo         destination callsign, NUL-padded ASCII
    28      4     DataLen        length of the payload that follows (uint32 LE)
    32      4     reserved (the "User" field -- unused by every server seen)

kissterm uses AGWPE strictly in *raw frame mode*: DataKind ``'K'`` carries one
complete AX.25 frame (with its own address field, so CallFrom/CallTo above are
not authoritative for it) prefixed by a single port byte, in each direction.
This is deliberate and is the one thing worth stating plainly, because AGWPE
also offers a *connected mode* -- DataKind ``'C'`` to open a connection,
``'D'``/``'d'`` to move data over it, ``'d'`` (lowercase) or a ``'X'``/``'x'``
handshake to close it, with the AGW engine itself running the AX.25 link
layer. kissterm does not implement any of that here. The whole point of
kissterm's design (see `kissterm.transport.base`) is that its own AX.25 state
machine runs identically over every raw-frame transport, so a link behaves
the same whether it is reached through a KISS TNC, an SDR, or an AGWPE
engine. Mixing in AGWPE connected mode would mean the retransmission timer,
window size, and link statistics the UI shows would come from AGW's engine
instead of kissterm's for this one transport only -- silently inconsistent
behaviour depending on which backend happened to be configured. If AGWPE
connected mode is ever wanted (there is no strong reason to want it, since
raw mode already reaches the same TNCs), it belongs in a separate
`SessionTransport`, not bolted onto this one.
"""

from __future__ import annotations

import asyncio
import contextlib
import struct

from ..ax25.address import AX25AddressError
from ..ax25.frame import AX25Frame, AX25FrameError
from .base import FrameTransport, TransportError, TransportInfo, TransportState

#: Port(1) + reserved(3) + DataKind(1) + reserved(1) + PID(1) + reserved(1)
#: + CallFrom(10) + CallTo(10) + DataLen(u32) + reserved "User"(4) = 36 bytes.
_HEADER = struct.Struct("<B3sBBBB10s10sI4s")
HEADER_LEN = _HEADER.size
assert HEADER_LEN == 36

# DataKind bytes this module sends or understands. AGWPE's own documentation
# spells these as single ASCII characters; kept as bytes here since that is
# how they sit in the header.
_KIND_MONITOR_ON = b"m"  # 'm': turn on monitoring of all traffic
_KIND_RAW_ON = b"k"  # 'k': turn on/off raw AX.25 frames in both directions
_KIND_PORT_INFO = b"G"  # 'G': ask for port capability info (port count etc.)
_KIND_RAW_FRAME = b"K"  # 'K': one raw AX.25 frame, port-byte prefixed

# Connected-mode DataKinds, listed only so the docstring's claim not to use
# them is checkable against something concrete -- never sent or parsed here.
_UNUSED_CONNECTED_KINDS = (b"C", b"D", b"d", b"X", b"x")


def _build_header(
    port: int, data_kind: bytes, call_from: str = "", call_to: str = "", data_len: int = 0
) -> bytes:
    return _HEADER.pack(
        port,
        b"\x00\x00\x00",
        ord(data_kind),
        0,
        0,
        0,
        call_from.encode("ascii", "replace")[:10].ljust(10, b"\x00"),
        call_to.encode("ascii", "replace")[:10].ljust(10, b"\x00"),
        data_len,
        b"\x00\x00\x00\x00",
    )


class AgwpeTransport(FrameTransport):
    """Raw-AX.25-frame mode over an AGWPE TCP engine (Direwolf, UZ7HO)."""

    def __init__(self, host: str, port: int = 8000, ports: int = 1) -> None:
        info = TransportInfo(
            kind="agwpe",
            name=f"{host}:{port}",
            detail=f"{host}:{port} (AGWPE)",
            tier="frame",
        )
        super().__init__(info, ports=ports)
        self.host = host
        self.port = port

        self.decode_errors = 0

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task[None] | None = None

    async def open(self) -> None:
        self.state = TransportState.OPENING
        self._error = ""
        try:
            self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        except OSError as exc:
            self.state = TransportState.ERROR
            self._error = str(exc)
            raise TransportError(f"could not connect to AGWPE at {self.host}:{self.port}: {exc}") from exc

        # Ask the engine to start delivering raw frames and monitored traffic,
        # and ask for its port table (the reply is informational only here --
        # kissterm already knows how many ports it configured).
        await self._send(_build_header(0, _KIND_MONITOR_ON))
        await self._send(_build_header(0, _KIND_RAW_ON))
        await self._send(_build_header(0, _KIND_PORT_INFO))

        self._read_task = asyncio.create_task(
            self._read_loop(), name=f"agwpe-read:{self.host}:{self.port}"
        )
        self.state = TransportState.OPEN

    async def _send(self, data: bytes) -> None:
        if self._writer is None:
            raise TransportError("AGWPE transport is not open")
        self._writer.write(data)
        await self._writer.drain()

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while True:
                header = await self._reader.readexactly(HEADER_LEN)
                port, _r1, kind_byte, _r2, _pid, _r3, _from, _to, data_len, _user = (
                    _HEADER.unpack(header)
                )
                payload = (
                    await self._reader.readexactly(data_len) if data_len else b""
                )
                await self._handle_message(port, bytes([kind_byte]), payload)
        except asyncio.IncompleteReadError:
            self.state = TransportState.ERROR
            self._error = "AGWPE connection closed by peer"
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- a dead read loop must not crash the app
            self.state = TransportState.ERROR
            self._error = f"AGWPE read loop failed: {exc}"

    async def _handle_message(self, port: int, kind: bytes, payload: bytes) -> None:
        if kind != _KIND_RAW_FRAME:
            # Port info ('G'), version ('R'), monitor strings ('U'/'I'/...),
            # and anything else the engine sends unprompted are not needed:
            # kissterm gets everything it needs from the raw frame stream.
            return
        if not payload:
            return
        # The raw-frame payload is one port byte followed by the AX.25 frame
        # (destination/source/digipeaters onward -- no FCS, same convention
        # as a KISS DATA payload). This layout is documented behaviour of
        # AGWPE DataKind 'K' in both Direwolf's and the original AGW's notes.
        frame_port, frame_bytes = payload[0], payload[1:]
        try:
            frame = AX25Frame.decode(frame_bytes)
        except (AX25FrameError, AX25AddressError):
            # A garbled or partially-desynchronized AGWPE stream must not
            # kill the read loop -- see the module docstring on why this
            # protocol is more fragile than KISS to begin with. Address
            # parsing failures (AX25AddressError) are just as possible as
            # control-field failures (AX25FrameError) and are not the same
            # exception type, so both are caught.
            self.decode_errors += 1
            return
        await self.dispatch(frame, frame_port)

    async def _send_frame(self, frame: AX25Frame, port: int = 0) -> None:
        if self.state is not TransportState.OPEN:
            raise TransportError("AGWPE transport is not open")
        raw = frame.encode()
        payload = bytes([port]) + raw
        header = _build_header(port, _KIND_RAW_FRAME, data_len=len(payload))
        await self._send(header + payload)

    async def close(self) -> None:
        if self._read_task is not None:
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._read_task
            self._read_task = None
        if self._writer is not None:
            with contextlib.suppress(Exception):
                self._writer.close()
                await self._writer.wait_closed()
            self._writer = None
        self._reader = None
        self.state = TransportState.CLOSED
