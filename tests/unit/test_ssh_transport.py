"""`SshTransport` against a real (local) SSH server -- no radio, no mock.

`asyncssh` ships a full client AND server implementation, so this runs a
genuine SSH handshake and password authentication over a loopback socket --
not a stand-in for one. What it proves: once authenticated, an SSH channel
is byte-for-byte the same kind of session `TelnetTransport` already handles
(see that module's docstring) -- no second protocol layer, no AX.25 framing.

Skipped entirely if `asyncssh` is not installed (`pip install kissterm[ssh]`
/ the `dev` extra) -- this is the one transport test file in the suite with
an optional dependency, by design (see `ssh.py`'s module docstring on why
that import is never at module scope in the transport itself).
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

asyncssh = pytest.importorskip("asyncssh")

from kissterm.transport.base import SessionState, TransportError, TransportState  # noqa: E402
from kissterm.transport.ssh import SshTransport  # noqa: E402

USERNAME = "packet"
PASSWORD = "letmein"


class _AuthServer(asyncssh.SSHServer):
    def __init__(self, authorized_key: bytes) -> None:
        self._authorized_key = authorized_key

    def connection_made(self, conn) -> None:
        self._conn = conn

    def begin_auth(self, username: str) -> bool:
        return True  # False here would mean "no auth needed", not what we want

    def password_auth_supported(self) -> bool:
        return True

    def public_key_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return username == USERNAME and password == PASSWORD

    def validate_public_key(self, username: str, key) -> bool:
        return username == USERNAME and key.export_public_key() == self._authorized_key


async def _shell(process) -> None:
    """A fake node's login shell: greet, then echo one line and exit --
    exactly the shape of WS1EC's own setup (login triggers a local telnet
    into the real node; this is that node's side of the conversation)."""
    process.stdout.write(b"Welcome to FAKE-NODE\r\n")
    line = await process.stdin.readline()
    process.stdout.write(b"echo: " + line)
    process.exit(0)


@pytest_asyncio.fixture
async def ssh_server(tmp_path: Path):
    key_path = tmp_path / "host_key"
    asyncssh.generate_private_key("ssh-rsa").write_private_key(str(key_path))
    client_key_path = tmp_path / "client_key"
    client_key = asyncssh.generate_private_key("ssh-rsa")
    # Encrypted PKCS#8 exercises the passphrase path without relying on the
    # optional bcrypt support AsyncSSH needs to emit encrypted OpenSSH keys.
    client_key.write_private_key(
        str(client_key_path), "pkcs8-pem", passphrase="key-secret"
    )
    server = await asyncssh.listen(
        "127.0.0.1",
        0,
        server_host_keys=[str(key_path)],
        server_factory=lambda: _AuthServer(client_key.export_public_key()),
        process_factory=_shell,
        encoding=None,
    )
    port = server.sockets[0].getsockname()[1]
    try:
        yield "127.0.0.1", port, client_key_path
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_connect_authenticates_and_delivers_the_banner(ssh_server):
    host, port, _client_key_path = ssh_server
    transport = SshTransport(host, USERNAME, PASSWORD, port=port)
    await transport.open()
    assert transport.state is TransportState.OPEN

    session = await transport.connect()
    try:
        assert session.connected
        assert session.peer == f"{USERNAME}@{host}:{port}"

        banner = await asyncio.wait_for(session.incoming.get(), timeout=3.0)
        assert banner == b"Welcome to FAKE-NODE\r\n"

        await session.send(b"hello\n")
        echoed = await asyncio.wait_for(session.incoming.get(), timeout=3.0)
        assert echoed == b"echo: hello\n"

        await asyncio.sleep(0.2)  # the shell exits right after echoing
        assert session.state is SessionState.DISCONNECTED
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_wrong_password_raises_transport_error(ssh_server):
    host, port, _client_key_path = ssh_server
    transport = SshTransport(host, USERNAME, "not-the-password", port=port)
    await transport.open()
    with pytest.raises(TransportError):
        await transport.connect()


@pytest.mark.asyncio
async def test_encrypted_client_key_authenticates(ssh_server):
    host, port, client_key_path = ssh_server
    transport = SshTransport(
        host, USERNAME, port=port,
        client_key=str(client_key_path), key_passphrase="key-secret",
    )
    await transport.open()
    session = await transport.connect()
    try:
        assert session.connected
        banner = await asyncio.wait_for(session.incoming.get(), timeout=3.0)
        assert banner == b"Welcome to FAKE-NODE\r\n"
    finally:
        await transport.close()
