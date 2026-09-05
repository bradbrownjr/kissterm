"""KISS over TCP -- the transport kissterm is built around.

Direwolf, UZ7HO SoundModem's KISS mode, BPQ32's KISS port, and most software
TNCs expose exactly this: a plain TCP socket carrying the same byte stream a
serial KISS port would, with none of pyserial's dependency headaches. Because
this is the path with the fewest moving parts and the widest reach (it works
identically on Linux, macOS, and Windows, local or over a LAN to a Raspberry
Pi running Direwolf next to the radio), it is the transport most kissterm
setups should default to when a real TNC is not already wired up over serial.

That convenience comes with one obligation the serial transport does not
have: a TCP peer can vanish and come back. Direwolf gets restarted, a
Raspberry Pi loses power during a storm, a router reboots -- and unlike a
serial cable falling out from under a running process, the socket does not
usually notice until the next failed read or write. When it does notice, the
right behaviour is not to hand the user a dead transport and require a
restart of the whole terminal; it is to retry the connection with backoff
until the TNC comes back, exactly as a real terminal program would reconnect
to a modem. That reconnect logic lives here, not in the UI, because the UI
should not need to know that TCP is the one transport tier that can drop out
from under it mid-session.
"""

from __future__ import annotations

import asyncio
import contextlib

from ..ax25.address import AX25AddressError
from ..ax25.frame import AX25Frame, AX25FrameError
from .base import FrameTransport, TransportError, TransportInfo, TransportState
from .kiss import KissCommand, KissDecoder, encode

#: Reconnect backoff: start fast (a restarting Direwolf is often back in under
#: a second) and double up to a ceiling that keeps retries from becoming a
#: nuisance in a log file if the far end is gone for good.
_INITIAL_BACKOFF = 0.5
_MAX_BACKOFF = 30.0


class TcpKissTransport(FrameTransport):
    """KISS framing over a TCP connection to a software or networked TNC.

    ``ports`` follows `FrameTransport`: Direwolf with ``CHANNEL 0``/``CHANNEL
    1`` bound to two radios is one TCP connection carrying both, distinguished
    by the KISS port nibble -- not two transports.
    """

    def __init__(self, host: str, port: int = 8001, ports: int = 1) -> None:
        info = TransportInfo(
            kind="tcp",
            name=f"{host}:{port}",
            detail=f"{host}:{port}",
            tier="frame",
        )
        super().__init__(info, ports=ports)
        self.host = host
        self.port = port

        self.decode_errors = 0
        self.reconnects = 0

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._decoder = KissDecoder()
        self._connection_task: asyncio.Task[None] | None = None
        self._closing = False
        #: Set once the first connection attempt has resolved (success or
        #: failure), so open() can report a real error instead of returning
        #: immediately and letting the reconnect loop fail silently forever.
        self._first_attempt: asyncio.Event = asyncio.Event()

    async def open(self) -> None:
        self.state = TransportState.OPENING
        self._error = ""
        self._closing = False
        self._first_attempt = asyncio.Event()
        self._connection_task = asyncio.create_task(
            self._connection_loop(), name=f"tcp-kiss:{self.host}:{self.port}"
        )
        await self._first_attempt.wait()
        if self.state is TransportState.ERROR:
            raise TransportError(self._error or f"could not connect to {self.host}:{self.port}")

    async def _connection_loop(self) -> None:
        """Connect, pump frames until the socket dies, then retry with backoff.

        Runs for the whole lifetime of the transport, not just the initial
        connect -- `state` goes back to OPENING (not ERROR) on a drop so the
        status bar can show "reconnecting" rather than a hard failure while
        this loop is still trying.
        """
        backoff = _INITIAL_BACKOFF
        first = True
        while not self._closing:
            try:
                self._reader, self._writer = await asyncio.open_connection(
                    self.host, self.port
                )
            except OSError as exc:
                self._error = f"connect to {self.host}:{self.port} failed: {exc}"
                if first:
                    self.state = TransportState.ERROR
                    self._first_attempt.set()
                    return
                self.state = TransportState.OPENING
                await self._sleep_backoff(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF)
                continue

            self.state = TransportState.OPEN
            self._error = ""
            if first:
                first = False
                self._first_attempt.set()
            else:
                self.reconnects += 1
            connected_at = asyncio.get_running_loop().time()

            try:
                await self._read_until_closed()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 -- keep the loop alive
                self._error = str(exc)

            self._decoder.reset()
            await self._close_socket()
            if self._closing:
                return

            # Only treat this as a healthy connection -- and reset backoff --
            # once it stayed up longer than the backoff ceiling would have
            # made us wait anyway. Without this, a peer that accepts the TCP
            # connection and then immediately drops it (a flapping listener,
            # a service that rejects at the application level) would reset
            # backoff to _INITIAL_BACKOFF on every single successful accept()
            # and reconnect in a tight ~0.5s loop forever, rather than backing
            # off the way a peer that refuses the connection outright already
            # does in the OSError branch above.
            if asyncio.get_running_loop().time() - connected_at >= _MAX_BACKOFF:
                backoff = _INITIAL_BACKOFF
            self.state = TransportState.OPENING
            await self._sleep_backoff(backoff)
            backoff = min(backoff * 2, _MAX_BACKOFF)

    async def _sleep_backoff(self, backoff: float) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(backoff)

    async def _read_until_closed(self) -> None:
        assert self._reader is not None
        while True:
            chunk = await self._reader.read(4096)
            if not chunk:
                self._error = "connection closed by peer"
                return
            for port, command, payload in self._decoder.feed(chunk):
                if command != KissCommand.DATA:
                    continue
                try:
                    frame = AX25Frame.decode(payload)
                except (AX25FrameError, AX25AddressError):
                    # A malformed frame from a flaky link/TNC must not tear
                    # down the socket -- only line noise on the RF side, not
                    # the TCP link, produced it. AX25Frame.decode can raise
                    # either its own error or AX25AddressError from address
                    # parsing, so both are caught here.
                    self.decode_errors += 1
                    continue
                await self.dispatch(frame, port)

    async def _send_frame(self, frame: AX25Frame, port: int = 0) -> None:
        if self._writer is None or self.state is not TransportState.OPEN:
            raise TransportError(f"tcp transport to {self.host}:{self.port} is not connected")
        self._writer.write(encode(frame.encode(), port))
        await self._writer.drain()

    async def _close_socket(self) -> None:
        if self._writer is not None:
            with contextlib.suppress(Exception):
                self._writer.close()
                await self._writer.wait_closed()
            self._writer = None
        self._reader = None

    async def close(self) -> None:
        self._closing = True
        if self._connection_task is not None:
            self._connection_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._connection_task
            self._connection_task = None
        await self._close_socket()
        self.state = TransportState.CLOSED
