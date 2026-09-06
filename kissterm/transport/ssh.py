"""SSH -- secure delivery for a remote telnet session, nothing more.

The concrete case this exists for: WS1EC (Maine Packet Radio) accepts
``ssh packet@ws1ec.mainepacketradio.org -p 4122``, where the account's own
login shell runs a local ``telnet`` into the real BPQ node the moment the
session opens. SSH is purely the secure transport here -- there is no
second protocol layer for kissterm to understand, and once the channel is
open it is byte-for-byte the same thing `telnet.py` already handles: no
AX.25 framing, no SABM/UA, the byte stream *is* the session. See that
module's docstring for the `SessionTransport` reasoning this shares.

**Password authentication only, for now.** Matches WS1EC's login and is the
simplest case to wire into the Connect flow; key-based auth is a documented
follow-up in docs/ROADMAP.md, not silently unsupported.

**Host-key verification is off (`known_hosts=None`).** A real gap, not an
oversight -- pinning a host key needs either a first-connect trust-on-first-
use prompt or a config field to hold the expected key, and neither is built
yet. Until one is, a network path to the host is trusted the same way a
brand-new `ssh` client asking "are you sure you want to continue connecting"
and getting an unconditional "yes" would be. Flagged here, in
docs/ROADMAP.md, and worth a status-bar or log line the day this matters
enough to fix.

Needs the optional `asyncssh` dependency (``pip install kissterm[ssh]``),
imported lazily inside `connect()` -- never at module import time, so a
kissterm install without the extra still runs everything else, and
constructing an `SshTransport` (as `build_transport` does for every
config entry at startup) never requires it either.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from ..ax25.address import AX25Path
from .base import Session, SessionState, SessionTransport, TransportError, TransportInfo, TransportState

log = logging.getLogger(__name__)

_READ_CHUNK = 4096


class SshTransport(SessionTransport):
    """One SSH connection, presented as an interactive process (a login
    shell, not a specific remote command) -- see the module docstring for
    why that specific shape matches WS1EC's setup and is not just a stand-in
    for a raw Telnet-over-SSH tunnel."""

    def __init__(self, host: str, username: str, password: str = "", port: int = 22) -> None:
        info = TransportInfo(
            kind="ssh",
            name=f"{username}@{host}:{port}",
            detail=f"{username}@{host}:{port}",
            tier="session",
        )
        super().__init__(info)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self._connection = None
        self._process = None
        self._pump_task: asyncio.Task[None] | None = None
        self._session: Session | None = None

    async def open(self) -> None:
        # Same reasoning as TelnetTransport.open(): nothing to prepare ahead
        # of the actual connection attempt.
        self.state = TransportState.OPEN

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
        self.state = TransportState.CLOSED

    async def connect(self, path: AX25Path | None = None) -> Session:
        """Authenticate and open an interactive session.

        `path` is accepted only to satisfy `SessionTransport`'s shared
        signature and is otherwise unused -- see that class's docstring.
        """
        if self._session is not None and self._session.connected:
            return self._session
        try:
            import asyncssh
        except ImportError as exc:
            raise TransportError(
                "SSH support needs the optional 'asyncssh' package -- "
                "install with 'pip install kissterm[ssh]'"
            ) from exc

        try:
            self._connection = await asyncssh.connect(
                self.host,
                port=self.port,
                username=self.username,
                password=self.password or None,
                # UNVERIFIED / deliberate gap -- see the module docstring's
                # host-key-verification note.
                known_hosts=None,
            )
            # No command: an interactive login shell, matching a bare
            # `ssh user@host` -- the remote end's own profile is what runs
            # `telnet` into the actual node for WS1EC's setup. `encoding=
            # None` gets raw bytes rather than asyncssh's own UTF-8 decode,
            # so kissterm's single latin-1 decode point (ansi.py/monitor.py)
            # stays the only place that happens -- packet traffic is not
            # reliably UTF-8 and a second, stricter decode upstream of it
            # would raise or replace on exactly the bytes latin-1 is meant
            # to pass through whole.
            self._process = await self._connection.create_process(
                term_type="ansi", encoding=None
            )
        except TransportError:
            raise
        except Exception as exc:
            raise TransportError(
                f"could not connect to {self.username}@{self.host}:{self.port}: {exc}"
            ) from exc
        log.info("connected to %s@%s:%d", self.username, self.host, self.port)

        session = Session(transport=self, path=path, state=SessionState.CONNECTED)
        process = self._process

        async def _send(data: bytes) -> None:
            process.stdin.write(data)
            await process.stdin.drain()

        async def _close() -> None:
            if self._pump_task is not None:
                self._pump_task.cancel()
            process.close()
            self._connection.close()
            with contextlib.suppress(Exception):
                await self._connection.wait_closed()

        session._sender = _send
        session._closer = _close
        self._session = session
        self._pump_task = asyncio.create_task(
            self._pump(process, session), name=f"ssh-pump:{self.host}:{self.port}"
        )
        return session

    async def _pump(self, process, session: Session) -> None:
        try:
            while True:
                data = await process.stdout.read(_READ_CHUNK)
                if not data:
                    log.info(
                        "connection to %s@%s:%d closed by the far end",
                        self.username, self.host, self.port,
                    )
                    break
                await session.deliver(data)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.warning(
                "lost connection to %s@%s:%d: %s", self.username, self.host, self.port, exc
            )
        finally:
            session.set_state(SessionState.DISCONNECTED)
