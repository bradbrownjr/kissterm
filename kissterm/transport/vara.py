"""VARA HF / VARA FM (EA5HVK) -- a TNC-as-a-service reached over two sockets.

VARA is not KISS and never carries an AX.25 frame anywhere: it is a
closed-source Windows modem (run standalone or under Wine) that does its own
modulation, its own ARQ, and its own addressing, and exposes the result as
two plain TCP connections to whatever sits above it:

* a **command** port (HF default 8300, FM default 8300 as well by convention
  but configured separately per instance -- VARA FM's defaults differ from
  VARA HF's, so both are named constants below rather than shared), a
  line-oriented ASCII protocol terminated by ``\\r``, used to configure the
  modem and to receive asynchronous status notifications; and
* a **data** port (command port + 1 by VARA's convention, i.e. HF default
  8301), a raw byte pipe that carries the connected session's actual
  application data once a link is up.

Because VARA already ran the entire link layer by the time bytes arrive on
the data port, this is a `SessionTransport`: there is no frame to decode and
no state machine to run above it, exactly the same shape as
`kernel_ax25.KernelAx25Transport` for the same underlying reason (see
`kissterm.transport.base`).

**Everything protocol-level in this module is UNVERIFIED against a running
VARA instance.** It is written against EA5HVK's published VARA HF and VARA FM
command-set documentation as commonly summarized by third-party VARA/Winlink
integration write-ups (the "VARA TNC command set" that FLDIGI, YAAC, and
similar programs implement against), targeting the VARA 4.x command set.
VARA has changed its wire behaviour across versions before, EA5HVK does not
publish a versioned protocol spec, and this has not been run against real
VARA software. Every place a specific command, reply, or notification is used
below is commented ``# UNVERIFIED:`` where its exact spelling or behaviour is
inferred rather than confirmed. Treat this module as a starting point for
testing against real VARA, not as a finished, trustworthy implementation --
get it in front of actual VARA HF and VARA FM instances before relying on it
for real traffic.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum

from ..ax25.address import AX25Path
from .base import Session, SessionState, SessionTransport, TransportError, TransportInfo, TransportState

# -- ports -----------------------------------------------------------------

#: UNVERIFIED: commonly documented VARA HF defaults. VARA FM ships with the
#: same default pair in most installers, but the two programs are configured
#: independently and either can be pointed at other ports.
DEFAULT_HF_CMD_PORT = 8300
DEFAULT_HF_DATA_PORT = 8301
DEFAULT_FM_CMD_PORT = 8300
DEFAULT_FM_DATA_PORT = 8301

# -- command-port protocol constants ----------------------------------------
#
# The command port is line-oriented ASCII, one command or notification per
# line, terminated by CR (commonly CRLF in practice). Every literal below is
# named so nothing protocol-specific is a bare string anywhere else in this
# module -- it makes the UNVERIFIED surface area auditable at a glance.

_LINE_TERMINATOR = "\r"

# Commands this module sends. UNVERIFIED: exact keyword spelling/spacing.
_CMD_MYCALL = "MYCALL"  # "MYCALL <callsign>[-ssid]"
_CMD_LISTEN = "LISTEN"  # "LISTEN ON" / "LISTEN OFF"
_CMD_PUBLIC = "PUBLIC"  # "PUBLIC ON" / "PUBLIC OFF" -- unproto/CQ visibility
_CMD_CONNECT = "CONNECT"  # "CONNECT <mycall> <target> [via <path>]"
_CMD_DISCONNECT = "DISCONNECT"
_CMD_ABORT = "ABORT"
_CMD_BW = "BW"  # UNVERIFIED: "BW2300"/"BW500" etc., no space before value

#: UNVERIFIED: VARA HF bandwidth choices, in Hz, as commonly documented.
#: VARA FM instead documents a 500/2300/2750/... option set of its own that
#: differs from HF's; callers pass whichever value their VaraTransport
#: subclass is configured for and this module does not validate it, on the
#: theory that VARA's own "WRONG" reply is the authoritative validator.
HF_BANDWIDTHS = (500, 1000, 1400, 1700, 2000, 2300)

# Async notifications VARA sends unprompted on the command port. UNVERIFIED:
# exact spelling and whether some carry parameters inline vs. on their own
# line (documented here as it is commonly summarized).
_NOTE_CONNECTED = "CONNECTED"
_NOTE_DISCONNECTED = "DISCONNECTED"
_NOTE_BUFFER = "BUFFER"  # "BUFFER <n>" -- bytes still queued in the modem
_NOTE_PTT = "PTT"  # "PTT ON" / "PTT OFF"
_NOTE_IAMALIVE = "IAMALIVE"  # periodic keepalive
_NOTE_REGISTERED = "REGISTERED"  # licensed copy acknowledged
_NOTE_MISSING_SOUNDCARD = "MISSING SOUNDCARD"
_NOTE_BUSY = "BUSY"  # "BUSY ON" / "BUSY OFF" -- channel-busy detector
_NOTE_LINK_REGISTERED = "LINK REGISTERED"

# Replies to a sent command.
_REPLY_OK = "OK"
_REPLY_WRONG = "WRONG"

#: How long to wait for CONNECTED after sending CONNECT before giving up.
#: UNVERIFIED: VARA HF link setup over a marginal path can legitimately take
#: well over a minute; this default favours not hanging forever over not
#: giving a slow-but-working link enough time, and should be raised for HF.
DEFAULT_CONNECT_TIMEOUT = 90.0

#: Flow-control high-water mark, in bytes, of unsent data allowed to sit in
#: this module's own send queue in front of the data socket. This governs
#: kissterm's own buffering, not VARA's internal buffer (VARA reports that
#: separately via BUFFER n) -- the two are kept apart so that a slow HF link
#: throttles the *sender* (via Session.send backpressure) instead of
#: kissterm silently accumulating unbounded memory in front of it.
DEFAULT_HIGH_WATER = 4096


class VaraBand(enum.Enum):
    HF = "hf"
    FM = "fm"


class VaraTransport(SessionTransport):
    """Base VARA transport: two TCP sockets, one connected `Session` at a time.

    VARA (both HF and FM) is a single-channel modem -- one link at a time,
    unlike a KISS TNC's frame transport which can carry many sessions'
    frames interleaved. `connect()` therefore raises if a session is already
    active rather than silently queuing a second one.
    """

    #: Subclasses (VaraHfTransport, VaraFmTransport) set these.
    band: VaraBand = VaraBand.HF
    kind_name = "vara"

    def __init__(
        self,
        host: str,
        mycall: str,
        cmd_port: int = DEFAULT_HF_CMD_PORT,
        data_port: int = DEFAULT_HF_DATA_PORT,
        bandwidth: int | None = None,
        listen: bool = True,
        public: bool = True,
        high_water: int = DEFAULT_HIGH_WATER,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    ) -> None:
        info = TransportInfo(
            kind=self.kind_name,
            name=host,
            detail=f"{host}:{cmd_port}/{data_port} ({self.band.value.upper()})",
            tier="session",
        )
        super().__init__(info)
        self.host = host
        self.mycall = mycall
        self.cmd_port = cmd_port
        self.data_port = data_port
        self.bandwidth = bandwidth
        self.listen = listen
        self.public = public
        self.high_water = high_water
        self.connect_timeout = connect_timeout

        self.buffer_bytes = 0  # last BUFFER n notification value
        self.ptt = False
        self.busy = False
        self.registered: bool | None = None

        self._cmd_reader: asyncio.StreamReader | None = None
        self._cmd_writer: asyncio.StreamWriter | None = None
        self._data_reader: asyncio.StreamReader | None = None
        self._data_writer: asyncio.StreamWriter | None = None
        self._cmd_read_task: asyncio.Task[None] | None = None
        self._data_read_task: asyncio.Task[None] | None = None

        self._reply_waiters: list[asyncio.Future[str]] = []
        self._connected_event = asyncio.Event()
        self._disconnected_event = asyncio.Event()
        self._session: Session | None = None
        self._send_lock = asyncio.Lock()

    # -- lifecycle ---------------------------------------------------------

    async def open(self) -> None:
        self.state = TransportState.OPENING
        self._error = ""
        try:
            self._cmd_reader, self._cmd_writer = await asyncio.open_connection(
                self.host, self.cmd_port
            )
            self._data_reader, self._data_writer = await asyncio.open_connection(
                self.host, self.data_port
            )
        except OSError as exc:
            self.state = TransportState.ERROR
            self._error = str(exc)
            raise TransportError(
                f"could not connect to VARA {self.band.value.upper()} at "
                f"{self.host}:{self.cmd_port}/{self.data_port}: {exc}"
            ) from exc

        self._cmd_read_task = asyncio.create_task(
            self._command_read_loop(), name=f"vara-cmd:{self.host}"
        )

        await self._send_command(f"{_CMD_MYCALL} {self.mycall}")
        if self.bandwidth is not None:
            # UNVERIFIED: "BW<value>" with no separator, e.g. "BW2300".
            await self._send_command(f"{_CMD_BW}{self.bandwidth}")
        await self._send_command(f"{_CMD_LISTEN} {'ON' if self.listen else 'OFF'}")
        await self._send_command(f"{_CMD_PUBLIC} {'ON' if self.public else 'OFF'}")

        self.state = TransportState.OPEN

    async def close(self) -> None:
        if self._session is not None:
            with contextlib.suppress(Exception):
                await self._session.close()
            self._session = None

        for task in (self._cmd_read_task, self._data_read_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._cmd_read_task = None
        self._data_read_task = None

        for writer in (self._cmd_writer, self._data_writer):
            if writer is not None:
                with contextlib.suppress(Exception):
                    writer.close()
                    await writer.wait_closed()
        self._cmd_writer = None
        self._data_writer = None
        self._cmd_reader = None
        self._data_reader = None

        self.state = TransportState.CLOSED

    # -- command port --------------------------------------------------------

    async def _send_command(self, line: str) -> str:
        """Send one command line and wait for its OK/WRONG reply."""
        if self._cmd_writer is None:
            raise TransportError("VARA command socket is not open")
        waiter: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._reply_waiters.append(waiter)
        self._cmd_writer.write((line + _LINE_TERMINATOR).encode("ascii", "replace"))
        await self._cmd_writer.drain()
        try:
            reply = await asyncio.wait_for(waiter, timeout=10.0)
        except asyncio.TimeoutError:
            with contextlib.suppress(ValueError):
                self._reply_waiters.remove(waiter)
            raise TransportError(f"VARA command {line!r} timed out waiting for a reply") from None
        if reply != _REPLY_OK:
            raise TransportError(f"VARA rejected command {line!r}: {reply}")
        return reply

    async def _command_read_loop(self) -> None:
        assert self._cmd_reader is not None
        try:
            while True:
                raw = await self._cmd_reader.readline()
                if not raw:
                    self._error = "VARA command socket closed by peer"
                    self.state = TransportState.ERROR
                    return
                line = raw.decode("ascii", "replace").strip("\r\n")
                if line:
                    self._handle_command_line(line)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- must not crash the app
            self._error = f"VARA command read loop failed: {exc}"
            self.state = TransportState.ERROR

    def _handle_command_line(self, line: str) -> None:
        # UNVERIFIED: this dispatch assumes every notification/reply is a
        # single line with space-separated tokens, which matches every
        # third-party summary of the VARA command set seen, but VARA's own
        # docs are not authoritative-checked here.
        if line in (_REPLY_OK, _REPLY_WRONG):
            self._resolve_next_waiter(line)
            return

        word, _, rest = line.partition(" ")
        if word == _NOTE_CONNECTED:
            self._connected_event.set()
        elif word == _NOTE_DISCONNECTED:
            self._disconnected_event.set()
            if self._session is not None:
                self._session.set_state(SessionState.DISCONNECTED)
        elif word == _NOTE_BUFFER:
            with contextlib.suppress(ValueError):
                self.buffer_bytes = int(rest.strip())
        elif word == _NOTE_PTT:
            self.ptt = rest.strip().upper() == "ON"
        elif word == _NOTE_BUSY:
            self.busy = rest.strip().upper() == "ON"
        elif word == _NOTE_REGISTERED:
            self.registered = True
        elif line == _NOTE_MISSING_SOUNDCARD:
            self._error = "VARA reports no sound card available"
        elif word == _NOTE_IAMALIVE:
            pass  # keepalive only
        elif line == _NOTE_LINK_REGISTERED:
            pass
        # Anything unrecognized is silently ignored rather than raised: a
        # future VARA version adding a notification this module does not
        # know about must not be fatal.

    def _resolve_next_waiter(self, reply: str) -> None:
        if self._reply_waiters:
            waiter = self._reply_waiters.pop(0)
            if not waiter.done():
                waiter.set_result(reply)

    # -- connecting ----------------------------------------------------------

    async def connect(self, path: AX25Path) -> Session:
        if self.state is not TransportState.OPEN:
            raise TransportError("VARA transport is not open")
        if self._session is not None:
            raise TransportError("VARA is single-channel: a session is already active")

        self._connected_event.clear()
        self._disconnected_event.clear()

        # UNVERIFIED: digipeater path syntax on the CONNECT line. Omitted
        # entirely when there is no path, since guessing VARA's separator
        # (space vs comma vs "VIA") without a reference is worse than
        # leaving direct-only connects working correctly.
        target = str(path.destination)
        if path.repeaters:
            via = ",".join(str(r) for r in path.repeaters)
            cmd = f"{_CMD_CONNECT} {self.mycall} {target} VIA {via}"
        else:
            cmd = f"{_CMD_CONNECT} {self.mycall} {target}"

        session = Session(path=path, transport=self, state=SessionState.CONNECTING)
        await self._send_command(cmd)

        try:
            await asyncio.wait_for(self._connected_event.wait(), timeout=self.connect_timeout)
        except asyncio.TimeoutError:
            with contextlib.suppress(TransportError):
                await self._send_command(_CMD_ABORT)
            session.set_state(SessionState.FAILED)
            raise TransportError(f"VARA connect to {target} timed out") from None

        session._sender = self._send_data
        session._closer = self._disconnect
        session.set_state(SessionState.CONNECTED)
        self._session = session

        self._data_read_task = asyncio.create_task(
            self._data_read_loop(session), name=f"vara-data:{target}"
        )
        return session

    async def _data_read_loop(self, session: Session) -> None:
        assert self._data_reader is not None
        try:
            while True:
                chunk = await self._data_reader.read(4096)
                if not chunk:
                    break
                await session.deliver(chunk)
        except asyncio.CancelledError:
            raise
        except OSError:
            pass
        finally:
            session.set_state(SessionState.DISCONNECTED)

    async def _send_data(self, data: bytes) -> None:
        """Write to the data socket, throttled against VARA's own buffer.

        `buffer_bytes` is VARA's last-reported queue depth (from the async
        ``BUFFER n`` notification), which is the only visibility this
        protocol gives into how much is still waiting to go out over the
        air. Waiting for it to drop below `high_water` before writing more
        keeps kissterm from stacking additional application data on top of
        an HF link that is still working through what it already has --
        the whole point of implementing flow control here rather than
        trusting the data socket's own TCP backpressure, which would only
        reflect the TCP link to VARA (effectively instantaneous on
        localhost), not VARA's actual over-the-air throughput.
        """
        if self._data_writer is None:
            raise TransportError("VARA data socket is not open")
        async with self._send_lock:
            while self.buffer_bytes > self.high_water:
                await asyncio.sleep(0.2)
            self._data_writer.write(data)
            await self._data_writer.drain()

    async def _disconnect(self) -> None:
        with contextlib.suppress(TransportError):
            await self._send_command(_CMD_DISCONNECT)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._disconnected_event.wait(), timeout=10.0)
        if self._data_read_task is not None:
            self._data_read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._data_read_task
            self._data_read_task = None
        self._session = None


class VaraHfTransport(VaraTransport):
    """VARA HF: narrowband, ARQ over a marginal ionospheric path."""

    band = VaraBand.HF
    kind_name = "vara"

    def __init__(
        self,
        host: str,
        mycall: str,
        cmd_port: int = DEFAULT_HF_CMD_PORT,
        data_port: int = DEFAULT_HF_DATA_PORT,
        bandwidth: int = 2300,
        **kwargs: object,
    ) -> None:
        super().__init__(
            host, mycall, cmd_port=cmd_port, data_port=data_port, bandwidth=bandwidth, **kwargs
        )


class VaraFmTransport(VaraTransport):
    """VARA FM: wider-band, VHF/UHF, much higher throughput than VARA HF.

    UNVERIFIED: VARA FM's bandwidth keyword set differs from HF's (it is
    commonly documented with options up to 25 kHz channels rather than HF's
    narrowband set); no default is assumed here beyond leaving `bandwidth`
    unset unless the caller supplies one, since sending a wrong HF-style
    value on an FM instance is worse than sending none.
    """

    band = VaraBand.FM
    kind_name = "varafm"

    def __init__(
        self,
        host: str,
        mycall: str,
        cmd_port: int = DEFAULT_FM_CMD_PORT,
        data_port: int = DEFAULT_FM_DATA_PORT,
        bandwidth: int | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(
            host, mycall, cmd_port=cmd_port, data_port=data_port, bandwidth=bandwidth, **kwargs
        )
