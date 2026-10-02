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

**Host-key verification is explicit and fail-closed.** The transport reads
one OpenSSH `known_hosts` file before connecting and passes the parsed
entries to AsyncSSH; it never consults an ambient `~/.ssh/known_hosts`. The
file is `known_hosts` when set (one the operator maintains), else kissterm's
own (`default_known_hosts`). A server with no entry there raises
`UnknownHostKey`, carrying the key it offered, and nothing is signed in: the
app shows the fingerprint and only an operator's Trust writes it
(`trust_host_key`), as OpenSSH asks on first contact. A *changed* key is
refused outright with no prompt -- that is the case host keys exist to
catch. An unreadable or malformed configured file raises `TransportError`.

Why ask rather than require a file (operator, 2026-10-02): requiring one
meant the Address Book could not save an SSH contact until the operator had
run ``ssh-keyscan`` by hand, which nothing told them to do.

**A terminal (pty) unless the caller is moving bytes, not typing.** The
operator's terminal gets one, as a bare ``ssh`` does. A binary protocol
(Winlink through the node, `pty=False`) must not: on WS1EC the pty sits
in front of ``telnet localhost 8010`` in cooked mode, which echoed every
line kissterm sent straight back (``;FW: KC1JMH`` heard as the gateway's
own, 2026-10-02 transcript `20261002-155701_KC1JMH_WS1ECSSH.log`) and
would treat Ctrl+C, Ctrl+D, erase and kill-line inside a compressed
message as commands, and add a CR to each LF on the way out. Without a
pty the login program still runs (WS1EC's is a plain script, operator
2026-10-02).
# UNVERIFIED: that a remote `telnet` with no tty passes binary intact; its
# escape character (0x1D) and CR handling still apply unless it runs as
# `telnet -8 -E` -- the node's side to set.

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
import os
from pathlib import Path

from ..ax25.address import AX25Path
from .base import Session, SessionState, SessionTransport, TransportError, TransportInfo, TransportState

log = logging.getLogger(__name__)

_READ_CHUNK = 4096


def default_known_hosts() -> Path:
    """kissterm's own known_hosts, used when an entry names none."""
    from ..config import state_path

    return state_path() / "ssh_known_hosts"


def host_pattern(host: str, port: int) -> str:
    """The known_hosts host field: bare on port 22, ``[host]:port`` otherwise."""
    return host if port == 22 else f"[{host}]:{port}"


class UnknownHostKey(TransportError):
    """The server is not in the known_hosts file yet. Carries what it
    offered so the operator can decide; nothing was signed in."""

    def __init__(self, host: str, port: int, path: Path, key_type: str,
                 fingerprint: str, line: str) -> None:
        super().__init__(
            f"{host}:{port} is not a known SSH server yet (key {fingerprint})"
        )
        self.host = host
        self.port = port
        self.path = path
        self.key_type = key_type
        self.fingerprint = fingerprint
        #: The known_hosts line `trust_host_key` appends.
        self.line = line


def trust_host_key(path: Path, line: str) -> None:
    """Append one operator-trusted line to a known_hosts file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(line.rstrip("\n") + "\n")


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
        pty: bool = True,
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
        #: Ask for a terminal; False for a binary protocol (module docstring).
        self.pty = pty
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

    async def _unknown_host(self, asyncssh, path: Path) -> TransportError:
        """Fetch the key the server offers (key exchange only, no sign-in)
        and wrap it in `UnknownHostKey` for the operator to judge."""
        try:
            key = await asyncssh.get_server_host_key(self.host, self.port, config=None)
        except Exception as exc:  # noqa: BLE001 -- any failure means "could not reach it"
            return TransportError(f"could not reach {self.host}:{self.port}: {exc}")
        if key is None:
            return TransportError(f"{self.host}:{self.port} offered no host key")
        key_type, blob = key.export_public_key("openssh").decode("ascii").split()[:2]
        return UnknownHostKey(
            self.host, self.port, path, key_type, key.get_fingerprint(),
            f"{host_pattern(self.host, self.port)} {key_type} {blob}",
        )

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

        configured = self.known_hosts.strip()
        hosts_file = Path(configured).expanduser() if configured else default_known_hosts()
        if not configured and not hosts_file.exists():
            # kissterm's own file before its first Trust: nothing known yet.
            known_hosts = asyncssh.import_known_hosts("")
        else:
            try:
                known_hosts = asyncssh.read_known_hosts(str(hosts_file))
            except (OSError, UnicodeError, ValueError) as exc:
                raise TransportError(
                    f"could not read SSH known-hosts file {str(hosts_file)!r}: {exc}"
                ) from exc
        if not any(known_hosts.match(self.host, "", self.port)):
            raise await self._unknown_host(asyncssh, hosts_file)

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
                **({"term_type": "ansi"} if self.pty else {}), encoding=None
            )
        except asyncssh.HostKeyNotVerifiable as exc:
            raise TransportError(
                f"refused: {self.host}:{self.port} sent a different host key from "
                f"the one trusted in {str(hosts_file)!r} ({exc}). If the server's operator "
                "confirms its key changed, delete its line there and connect again."
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
