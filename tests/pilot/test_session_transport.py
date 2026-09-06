"""Telnet/SSH end to end through the real app: no AX25Station, no dialog.

The point being proven: `station is None` (a session-tier transport is
active) no longer means "Ctrl+N does nothing" -- `action_connect` opens the
transport directly and binds the resulting `Session` into exactly the same
terminal-pane machinery an `AX25Link` uses, via `_SessionLinkAdapter`. See
`kissterm/ui/app.py`'s docstring on that class for why an adapter rather
than reshaping `Session` itself.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.transport.telnet import TelnetTransport  # noqa: E402
from kissterm.ui.terminal_pane import TerminalPane  # noqa: E402


def _log_text(app) -> str:
    log = app.query_one(TerminalPane).query_one("#session-log")
    return "\n".join(str(line) for line in log.lines)


async def _fake_node(reader, writer):
    # Reads raw chunks, not `readline()` -- kissterm's terminal pane sends
    # CR-terminated lines, never LF (see terminal_pane.py's module
    # docstring), and asyncio's `readline()` only ever splits on LF. A real
    # BPQ node parses CR the same way; this mirrors that instead of hanging
    # forever waiting for a byte kissterm will never send.
    writer.write(b"Welcome to FAKE-NODE\r\n")
    await writer.drain()
    while True:
        data = await reader.read(256)
        if not data:
            break
        writer.write(b"echo: " + data)
        await writer.drain()


@pytest.mark.asyncio
async def test_a_fresh_session_transport_launch_does_not_connect_on_its_own():
    """Same guarantee as the FrameTransport tier, on the other tier: opening
    the app is not a request to connect anywhere, and the gate starts
    closed regardless of which kind of transport is active."""
    server = await asyncio.start_server(_fake_node, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    transport = TelnetTransport(host, port)
    await transport.open()
    config = Config(mycall="N1ABC-1")
    app = KissTermApp(config, station=None, session_transport=transport)
    try:
        async with app.run_test(size=(110, 32)) as pilot:
            await pilot.pause()
            await asyncio.sleep(0.1)
            assert not app.gate.enabled
            assert app.link is None
    finally:
        await transport.close()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_ctrl_n_arms_the_gate_instead_of_being_refused_by_it():
    """Same rule as the FrameTransport tier (`_arm_for`'s docstring): naming
    -- here, simply asking to connect, since a session transport has only
    one destination -- is a confirmed, targeted request and ARMS transmit
    rather than being refused because it started closed."""
    server = await asyncio.start_server(_fake_node, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    transport = TelnetTransport(host, port)
    await transport.open()
    config = Config(mycall="N1ABC-1")
    app = KissTermApp(config, station=None, session_transport=transport)
    try:
        async with app.run_test(size=(110, 32)) as pilot:
            await pilot.pause()
            assert not app.gate.enabled
            await pilot.press("ctrl+n")
            await pilot.pause()
            await asyncio.sleep(0.3)
            assert app.gate.enabled
            assert app.link is not None and app.link.connected
    finally:
        await transport.close()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_ctrl_n_connects_directly_with_no_dialog():
    server = await asyncio.start_server(_fake_node, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    transport = TelnetTransport(host, port)
    await transport.open()
    config = Config(mycall="N1ABC-1")
    config.tx_armed_at_start = True
    app = KissTermApp(config, station=None, session_transport=transport)
    try:
        async with app.run_test(size=(110, 32)) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+n")
            await pilot.pause()
            await asyncio.sleep(0.3)
            await pilot.pause()

            assert app.link is not None and app.link.connected
            assert app.link.peer == f"{host}:{port}"
            text = _log_text(app)
            assert "Welcome to FAKE-NODE" in text, text

            # The single send path (TerminalPane.send_line) works unchanged.
            await app.query_one(TerminalPane).send_line("hello")
            await asyncio.sleep(0.2)
            await pilot.pause()
            text = _log_text(app)
            assert "echo: hello" in text, text

            await pilot.press("ctrl+d")
            await pilot.pause()
            await asyncio.sleep(0.2)
    finally:
        await transport.close()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_ssh_works_through_the_same_adapter_as_telnet(tmp_path):
    """`_connect_session_transport`/`_SessionLinkAdapter` do not know or
    care which `SessionTransport` they are handed -- this is the one
    app-level check that SSH gets the identical treatment Telnet already
    proved above, not a second copy of that whole test."""
    asyncssh = pytest.importorskip("asyncssh")
    from kissterm.transport.ssh import SshTransport

    class _AuthServer(asyncssh.SSHServer):
        def begin_auth(self, username):
            return True

        def password_auth_supported(self):
            return True

        def validate_password(self, username, password):
            return username == "packet" and password == "secret"

    async def _shell(process):
        process.stdout.write(b"Welcome to FAKE-NODE\r\n")
        data = await process.stdin.read(256)
        process.stdout.write(b"echo: " + data)
        process.exit(0)

    key_path = tmp_path / "host_key"
    asyncssh.generate_private_key("ssh-rsa").write_private_key(str(key_path))
    server = await asyncssh.listen(
        "127.0.0.1", 0,
        server_host_keys=[str(key_path)],
        server_factory=_AuthServer,
        process_factory=_shell,
        encoding=None,
    )
    port = server.sockets[0].getsockname()[1]
    transport = SshTransport("127.0.0.1", "packet", "secret", port=port)
    await transport.open()
    config = Config(mycall="N1ABC-1")
    config.tx_armed_at_start = True
    app = KissTermApp(config, station=None, session_transport=transport)
    try:
        async with app.run_test(size=(110, 32)) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+n")
            await pilot.pause()
            await asyncio.sleep(0.5)
            await pilot.pause()

            assert app.link is not None and app.link.connected
            text = _log_text(app)
            assert "Welcome to FAKE-NODE" in text, text

            await app.query_one(TerminalPane).send_line("hello")
            await asyncio.sleep(0.3)
            await pilot.pause()
            text = _log_text(app)
            assert "echo: hello" in text, text
    finally:
        await transport.close()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_status_bar_shows_the_session_transport_detail():
    from textual.geometry import Region

    def _plain(widget) -> str:
        region = Region(0, 0, widget.size.width or 200, widget.size.height or 5)
        return "\n".join(strip.text for strip in widget.render_lines(region))

    server = await asyncio.start_server(_fake_node, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    transport = TelnetTransport(host, port)
    await transport.open()
    config = Config(mycall="N1ABC-1")
    app = KissTermApp(config, station=None, session_transport=transport)
    try:
        async with app.run_test(size=(110, 32)) as pilot:
            await pilot.pause()
            status = _plain(app.query_one("#status-bar"))
            assert f"{host}:{port}" in status, status
    finally:
        await transport.close()
        server.close()
        await server.wait_closed()
