"""SSH -- secure delivery for a remote telnet session, nothing more.

The concrete case this exists for: WS1EC (Maine Packet Radio) accepts
``ssh packet@ws1ec.mainepacketradio.org -p 4122``, where the account's own
login shell runs a local ``telnet`` into the real BPQ node the moment the
session opens. SSH is purely the secure transport here -- there is no
second protocol layer for kissterm to understand, and once the channel is
open it is byte-for-byte the same thing `telnet.py` already handles: no
AX.25 framing, no SABM/UA, the byte stream *is* the session. See that
module's docstring for the `SessionTransport` reasoning this shares.

**Authentication is explicit.** Set `password` for password authentication,
or set `client_key` to the private-key file to offer that key. An encrypted
key additionally needs `key_passphrase`. kissterm never searches `~/.ssh` or
silently selects an identity: the configured file is the one it offers.

**Host-key verification is explicit and fail-closed.** Set `known_hosts` to
an operator-maintained OpenSSH `known_hosts` file containing the expected
server key. The transport reads that exact file before connecting and passes
the parsed entries to AsyncSSH; it never trusts an ambient `~/.ssh/known_hosts`
file or accepts a first-seen key. A missing, unreadable, malformed, unknown,
or changed key raises `TransportError` before an interactive session exists.

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

    def __init__(
        self,
        host: str,
        username: str,
        password: str = "",
        port: int = 22,
        client_key: str = "",
        key_passphrase: str = "",
        known_hosts: str = "",
    ) -> None:
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
        self.client_key = client_key
        self.key_passphrase = key_passphrase
        self.known_hosts = known_hosts
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

        if not self.known_hosts.strip():
            raise TransportError(
                "SSH host-key verification requires a configured 'known_hosts' "
                "file containing this server's expected key"
            )
        try:
            known_hosts = asyncssh.read_known_hosts(self.known_hosts)
        except (OSError, UnicodeError, ValueError) as exc:
            raise TransportError(
                f"could not read SSH known-hosts file {self.known_hosts!r}: {exc}"
            ) from exc
        if not any(known_hosts.match(self.host, "", self.port)):
            raise TransportError(
                f"SSH known-hosts file {self.known_hosts!r} has no valid entry "
                f"for {self.host}:{self.port}"
            )

        try:
            connect_options = dict(
                host=self.host,
                port=self.port,
                username=self.username,
                password=self.password or None,
                # An explicit None prevents AsyncSSH from loading default
                # identity files. `agent_path=None` keeps an ambient
                # ssh-agent from offering unrelated keys, too.
                client_keys=[self.client_key] if self.client_key else None,
                agent_path=None,
                config=None,
                # The pre-parsed, explicitly configured entries prevent
                # AsyncSSH from consulting ambient known-hosts files.
                known_hosts=known_hosts,
            )
            if self.client_key:
                # AsyncSSH accepts paths here and loads precisely these keys.
                # Do not let an unconfigured transport search ~/.ssh: an
                # operator must name the identity kissterm is allowed to use.
                connect_options["passphrase"] = self.key_passphrase or None
            self._connection = await asyncssh.connect(**connect_options)
            # No command: an interactive login shell, matching a bare
            # `ssh user@host` -- the remote end's own profile is what runs
            # `telnet` into the actual node for WS1EC's setup. `encoding=
            # None` gets raw bytes rather than asyncssh's own UTF-8 decode,
            # so kissterm's single decode point (`ansi.decode_text`: UTF-8
            # when valid, else latin-1) stays the only place that happens --
            # packet traffic is not reliably UTF-8 and a second, stricter
            # decode upstream of it would raise or replace on exactly the
            # bytes the latin-1 fallback is meant to pass through whole.
            self._process = await self._connection.create_process(
                term_type="ansi", encoding=None
            )
        except asyncssh.HostKeyNotVerifiable as exc:
            raise TransportError(
                f"SSH host-key verification failed for {self.host}:{self.port}: {exc}. "
                "Check that 'known_hosts' contains this server's current key."
            ) from exc
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
