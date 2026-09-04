"""The Linux kernel's own AX.25 stack (``AF_AX25`` sockets), linpac's path.

Linux has shipped a real AX.25 network-layer implementation since the
mid-1990s: `ax25-tools`/`ax25-apps` bring up a port against a KISS device
(often via `kissattach`, itself just a KISS-over-serial or -PTY client) and
from then on the kernel does address negotiation, retransmission, window
management, and connection state entirely on its own. Userspace opens a
`socket.AF_AX25` / `SOCK_SEQPACKET` socket, `bind()`s it to a local
``(callsign, port)``, `connect()`s to a remote callsign, and reads and writes
already-reassembled application data -- exactly what `linpac`, `ax25ipd`, and
the BBS software of that era do.

This is a `SessionTransport`, and deliberately not a `FrameTransport`, for a
reason worth being explicit about: the kernel already *is* a complete AX.25
implementation. If kissterm's own state machine (`kissterm.ax25.session`)
were layered on top of frames pulled off a kernel AX.25 socket, there would
be two independent AX.25 implementations -- one in the kernel, one in this
process -- both trying to own retransmission and sequencing for the same
link. They would not agree on window state, and the failure mode is not a
clean crash but silent, intermittent frame loss that looks like a bad radio
link. Kernel AX.25 is therefore treated as producing an *already-connected
byte stream*, exactly like VARA or Mercury, even though under the hood it is
"real" AX.25 -- because from kissterm's point of view what matters is who is
running the link layer, not what protocol that link layer happens to speak.

The practical cost of this design is that a machine using this transport
cannot also use kissterm's own state machine on the same radio port at the
same time (the kernel already owns it via `kissattach`), and multi-connection
fan-out, if wanted, is the kernel's `SOCK_SEQPACKET` semantics, not
kissterm's -- open a new socket per remote station.

``AF_AX25`` is Linux-only and requires the ``ax25`` kernel module (and often
`ax25-tools` to have configured `/etc/ax25/axports`) to be present; neither is
guaranteed even on Linux. The availability check happens in `open()`, not at
import time, so importing this module on macOS/Windows -- or a stripped-down
Linux kernel -- never raises; only trying to use it does.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket

from ..ax25.address import AX25Path
from .base import Session, SessionState, SessionTransport, TransportError, TransportInfo, TransportState

#: SOCK_SEQPACKET is what carries whole AX.25 I-frame payloads as discrete
#: reads, matching how `Session.deliver` expects to receive data -- one
#: `deliver()` call per received unit, not an arbitrary byte-stream split.
_READ_CHUNK = 4096


class KernelAx25Transport(SessionTransport):
    """Connects through the Linux kernel's AX.25 stack via ``AF_AX25`` sockets.

    ``ax25_port`` is the *kernel* AX.25 port name from ``/etc/ax25/axports``
    (e.g. ``"radio1"``), configured outside kissterm by `kissattach`; it is
    unrelated to the KISS/AGW ``port`` numbers used elsewhere in this package.
    ``mycall`` is the callsign (with optional SSID) this socket binds as.
    """

    def __init__(self, ax25_port: str, mycall: str) -> None:
        info = TransportInfo(
            kind="kernel",
            name=ax25_port,
            detail=f"AF_AX25 {ax25_port} as {mycall}",
            tier="session",
        )
        super().__init__(info)
        self.ax25_port = ax25_port
        self.mycall = mycall
        self._sock: socket.socket | None = None
        self._sessions: list[tuple[Session, asyncio.Task[None]]] = []

    async def open(self) -> None:
        if not hasattr(socket, "AF_AX25"):
            self.state = TransportState.ERROR
            self._error = "AF_AX25 is not available on this platform"
            raise TransportError(
                "AF_AX25 sockets are not available: this is a Linux-only "
                "feature that also requires the kernel 'ax25' module and "
                "ax25-tools (kissattach) to have brought up a port. On "
                "any other OS, or a Linux kernel without AX.25 support, "
                "use a FrameTransport (serial/tcp KISS) instead."
            )
        # The socket itself is opened lazily per-connect below: AF_AX25
        # sockets in Linux are created and bound individually per session
        # (there is no single "listening" socket shared across connections
        # the way a TCP server would have one), so open() here only proves
        # the address family exists and records that the transport is ready
        # to hand out connections.
        self.state = TransportState.OPEN
        self._error = ""

    async def connect(self, path: AX25Path) -> Session:
        if self.state is not TransportState.OPEN:
            raise TransportError("kernel AX.25 transport is not open")

        loop = asyncio.get_running_loop()
        session = Session(path=path, transport=self, state=SessionState.CONNECTING)
        sock: socket.socket | None = None

        try:
            # AF_AX25 being a valid constant does not mean the kernel actually
            # supports it -- that also needs the 'ax25' module loaded, which
            # socket.socket() itself is what fails on (ENOPROTOOPT/EAFNOSUPPORT)
            # if it is missing. Wrapping the constructor here, not just
            # connect() below, is what keeps that failure a TransportError
            # instead of a raw OSError escaping to the caller.
            sock = socket.socket(socket.AF_AX25, socket.SOCK_SEQPACKET)
            sock.setblocking(False)

            # AF_AX25 addresses are (port_name, callsign) pairs at the socket
            # API level -- distinct from the axports port *number* used by
            # some older tools. bind() selects which configured radio port
            # and local callsign this socket answers as; connect() then
            # names the remote station.
            #
            # RESEARCH: the exact bind/connect tuple shape
            # (('port_name', 'MYCALL-1') vs a bytes-packed sockaddr_ax25)
            # differs across Python versions and has shifted in the stdlib
            # socket module historically. This is written to the documented
            # `socket.AF_AX25` contract but has not been exercised against a
            # live kernel AX.25 stack; verify against a real kissattach
            # setup before relying on it.
            await loop.sock_connect(sock, (self.ax25_port, str(path.destination)))
        except OSError as exc:
            if sock is not None:
                sock.close()
            session.set_state(SessionState.FAILED)
            raise TransportError(f"AF_AX25 connect to {path.destination} failed: {exc}") from exc

        assert sock is not None  # the try block above always raises or assigns it

        async def _send(data: bytes) -> None:
            await loop.sock_sendall(sock, data)

        async def _close() -> None:
            with contextlib.suppress(Exception):
                sock.close()
            session.set_state(SessionState.DISCONNECTED)

        session._sender = _send
        session._closer = _close
        session.set_state(SessionState.CONNECTED)

        reader_task = asyncio.create_task(
            self._reader_loop(sock, session), name=f"ax25-kernel:{path.destination}"
        )
        self._sessions.append((session, reader_task))
        return session

    async def _reader_loop(self, sock: socket.socket, session: Session) -> None:
        loop = asyncio.get_running_loop()
        try:
            while True:
                data = await loop.sock_recv(sock, _READ_CHUNK)
                if not data:
                    break
                await session.deliver(data)
        except asyncio.CancelledError:
            raise
        except OSError:
            pass  # socket torn down under us; fall through to disconnect
        finally:
            session.set_state(SessionState.DISCONNECTED)

    async def close(self) -> None:
        for session, task in self._sessions:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await session.close()
        self._sessions.clear()
        self.state = TransportState.CLOSED
