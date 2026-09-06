"""Plain Telnet -- an Internet-reachable node's own telnet server.

No AX.25 framing crosses this wire at all. The remote end (most commonly a
BPQ32/LinBPQ "Telnet" listener) already **is** the AX.25 station: it runs its
own link layer on its own RF ports and simply presents the identical node
prompt over a raw TCP socket that it would over a KISS TNC. From kissterm's
side there is no SABM/UA, no digipeater path, nothing for the AX.25 state
machine to do -- the byte stream *is* the session from the moment the socket
connects. That is exactly what a `SessionTransport` is for; see
`kissterm/transport/base.py`'s module docstring for the tier split this
follows, and `kernel_ax25.py` for the same reasoning applied to a different
"someone else already ran the link layer" case.

This is precisely how SyncTERM, BPQTerminal and a plain `telnet` client
already reach this kind of node today -- kissterm gains nothing by inventing
a different model for it.

``open()`` deliberately does not dial anything: unlike a KISS TNC, there is
no local resource to prepare ahead of time, and claiming OPEN before the
remote host is even known to be reachable would be a promise this transport
cannot keep. The actual TCP connection happens in `connect()`, which is also
where a real on-air terminal's "no answer" moment would be for this kind of
link -- a bad host, a closed port, a firewall -- so that is where it needs to
surface, not at app startup.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from ..ax25.address import AX25Path
from .base import Session, SessionState, SessionTransport, TransportError, TransportInfo, TransportState

log = logging.getLogger(__name__)

#: Matches the KISS transports' own read chunk size -- no protocol reason to
#: differ, just consistency.
_READ_CHUNK = 4096


class TelnetTransport(SessionTransport):
    """One Telnet connection to a node's own telnet server."""

    def __init__(self, host: str, port: int = 23) -> None:
        info = TransportInfo(
            kind="telnet",
            name=f"{host}:{port}",
            detail=f"{host}:{port}",
            tier="session",
        )
        super().__init__(info)
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._pump_task: asyncio.Task[None] | None = None
        self._session: Session | None = None

    async def open(self) -> None:
        # See the module docstring: nothing to prepare ahead of the actual
        # connect for this transport, so this just marks it ready to try.
        self.state = TransportState.OPEN

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
        self.state = TransportState.CLOSED

    async def connect(self, path: AX25Path | None = None) -> Session:
        """Open the TCP connection and hand back a live `Session`.

        `path` is accepted only to satisfy `SessionTransport`'s shared
        signature and is otherwise unused -- see that class's docstring.
        """
        if self._session is not None and self._session.connected:
            return self._session
        try:
            reader, writer = await asyncio.open_connection(self.host, self.port)
        except OSError as exc:
            raise TransportError(
                f"could not connect to {self.host}:{self.port}: {exc}"
            ) from exc
        log.info("connected to %s:%d", self.host, self.port)
        self._reader, self._writer = reader, writer

        session = Session(transport=self, path=path, state=SessionState.CONNECTED)

        async def _send(data: bytes) -> None:
            writer.write(data)
            await writer.drain()

        async def _close() -> None:
            if self._pump_task is not None:
                self._pump_task.cancel()
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

        session._sender = _send
        session._closer = _close
        self._session = session
        self._pump_task = asyncio.create_task(
            self._pump(reader, session), name=f"telnet-pump:{self.host}:{self.port}"
        )
        return session

    async def _pump(self, reader: asyncio.StreamReader, session: Session) -> None:
        """Feed bytes to `session` until EOF, a decode-unrelated error, or
        cancellation. Telnet carries no framing kissterm needs to parse --
        whatever arrives goes straight to the terminal pane, same as any
        other session-tier transport."""
        try:
            while True:
                data = await reader.read(_READ_CHUNK)
                if not data:
                    log.info("connection to %s:%d closed by the far end", self.host, self.port)
                    break
                await session.deliver(data)
        except asyncio.CancelledError:
            pass
        except OSError as exc:
            log.warning("lost connection to %s:%d: %s", self.host, self.port, exc)
        finally:
            session.set_state(SessionState.DISCONNECTED)
