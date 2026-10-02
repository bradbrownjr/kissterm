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
from kissterm.transport import ssh as ssh_module  # noqa: E402
from kissterm.transport.ssh import SshTransport, UnknownHostKey, trust_host_key  # noqa: E402

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


async def _shell(process, state: dict[str, int]) -> None:
    """A fake node's login shell: greet, then echo one line and exit --
    exactly the shape of WS1EC's own setup (login triggers a local telnet
    into the real node; this is that node's side of the conversation)."""
    state["shells"] += 1
    state["term"] = process.term_type
    process.stdout.write(b"Welcome to FAKE-NODE\r\n")
    line = await process.stdin.readline()
    process.stdout.write(b"echo: " + line)
    process.exit(0)


@pytest_asyncio.fixture
async def ssh_server(tmp_path: Path):
    key_path = tmp_path / "host_key"
    host_key = asyncssh.generate_private_key("ssh-rsa")
    host_key.write_private_key(str(key_path))
    client_key_path = tmp_path / "client_key"
    client_key = asyncssh.generate_private_key("ssh-rsa")
    # Encrypted PKCS#8 exercises the passphrase path without relying on the
    # optional bcrypt support AsyncSSH needs to emit encrypted OpenSSH keys.
    client_key.write_private_key(
        str(client_key_path), "pkcs8-pem", passphrase="key-secret"
    )
    state = {"shells": 0}
    server = await asyncssh.listen(
        "127.0.0.1",
        0,
        server_host_keys=[str(key_path)],
        server_factory=lambda: _AuthServer(client_key.export_public_key()),
        process_factory=lambda process: _shell(process, state),
        encoding=None,
    )
    port = server.sockets[0].getsockname()[1]
    known_hosts_path = tmp_path / "known_hosts"
    known_hosts_path.write_bytes(
        f"[127.0.0.1]:{port} ".encode() + host_key.export_public_key()
    )
    try:
        yield "127.0.0.1", port, client_key_path, known_hosts_path, state
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_connect_authenticates_and_delivers_the_banner(ssh_server):
    host, port, _client_key_path, known_hosts_path, _state = ssh_server
    transport = SshTransport(
        host, USERNAME, PASSWORD, port=port, known_hosts=str(known_hosts_path)
    )
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
@pytest.mark.parametrize("pty", [True, False])
async def test_a_terminal_only_when_asked(ssh_server, pty):
    """A binary protocol asks for no pty: WS1EC's echoed Winlink's lines
    back (2026-10-02)."""
    host, port, _client_key_path, known_hosts_path, state = ssh_server
    transport = SshTransport(host, USERNAME, PASSWORD, port=port,
                             known_hosts=str(known_hosts_path), pty=pty)
    await transport.open()
    session = await transport.connect()
    try:
        await asyncio.wait_for(session.incoming.get(), timeout=3.0)
        assert state["term"] == ("ansi" if pty else None)
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_wrong_password_raises_transport_error(ssh_server):
    host, port, _client_key_path, known_hosts_path, _state = ssh_server
    transport = SshTransport(
        host, USERNAME, "not-the-password", port=port, known_hosts=str(known_hosts_path)
    )
    await transport.open()
    with pytest.raises(TransportError):
        await transport.connect()


@pytest.mark.asyncio
async def test_encrypted_client_key_authenticates(ssh_server):
    host, port, client_key_path, known_hosts_path, _state = ssh_server
    transport = SshTransport(
        host, USERNAME, port=port,
        client_key=str(client_key_path), key_passphrase="key-secret",
        known_hosts=str(known_hosts_path),
    )
    await transport.open()
    session = await transport.connect()
    try:
        assert session.connected
        banner = await asyncio.wait_for(session.incoming.get(), timeout=3.0)
        assert banner == b"Welcome to FAKE-NODE\r\n"
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_a_new_server_is_asked_about_then_trusted(ssh_server, tmp_path: Path, monkeypatch):
    """No file named: kissterm's own known_hosts. A first contact raises
    UnknownHostKey with the server's real fingerprint and signs nothing in;
    after the operator's Trust is written, the same connect succeeds."""
    host, port, _client_key_path, _known_hosts_path, state = ssh_server
    own = tmp_path / "own" / "ssh_known_hosts"
    monkeypatch.setattr(ssh_module, "default_known_hosts", lambda: own)
    transport = SshTransport(host, USERNAME, PASSWORD, port=port)
    await transport.open()

    with pytest.raises(UnknownHostKey) as caught:
        await transport.connect()
    server_key = asyncssh.read_private_key(str(tmp_path / "host_key"))
    assert caught.value.fingerprint == server_key.get_fingerprint()
    assert caught.value.path == own
    assert caught.value.line.startswith(f"[{host}]:{port} ssh-rsa ")
    assert state["shells"] == 0 and not own.exists()

    trust_host_key(caught.value.path, caught.value.line)
    session = await transport.connect()
    try:
        assert session.connected
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_unreadable_or_malformed_known_hosts_rejects_before_a_shell_starts(ssh_server, tmp_path: Path):
    host, port, _client_key_path, _known_hosts_path, state = ssh_server
    malformed = tmp_path / "malformed_known_hosts"
    malformed.write_text("this is not an OpenSSH known-hosts entry\n")

    # A named file that is missing is an error; asyncssh skips lines it
    # cannot parse, so a malformed one holds no entry and is asked about.
    for known_hosts, raised in ((tmp_path / "missing_known_hosts", "known-hosts file"),
                                (malformed, "not a known SSH server")):
        transport = SshTransport(
            host, USERNAME, PASSWORD, port=port, known_hosts=str(known_hosts)
        )
        await transport.open()
        with pytest.raises(TransportError, match=raised):
            await transport.connect()

    assert state["shells"] == 0


@pytest.mark.asyncio
async def test_unknown_or_changed_server_key_rejects_before_a_shell_starts(ssh_server, tmp_path: Path):
    host, port, _client_key_path, _known_hosts_path, state = ssh_server
    unknown = tmp_path / "unknown_known_hosts"
    server_key = asyncssh.read_private_key(str(tmp_path / "host_key"))
    unknown.write_bytes(
        f"not-{host} ".encode() + server_key.export_public_key()
    )

    transport = SshTransport(
        host, USERNAME, PASSWORD, port=port, known_hosts=str(unknown)
    )
    await transport.open()
    with pytest.raises(UnknownHostKey):
        await transport.connect()

    changed = tmp_path / "changed_known_hosts"
    replacement_key = asyncssh.generate_private_key("ssh-rsa")
    changed.write_bytes(
        f"[127.0.0.1]:{port} ".encode() + replacement_key.export_public_key()
    )

    transport = SshTransport(
        host, USERNAME, PASSWORD, port=port, known_hosts=str(changed)
    )
    await transport.open()
    with pytest.raises(TransportError, match="refused: .* different host key") as caught:
        await transport.connect()
    # A changed key is refused, never offered for trust.
    assert not isinstance(caught.value, UnknownHostKey)

    assert state["shells"] == 0
