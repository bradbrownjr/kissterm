"""`TelnetTransport` against a real (local) TCP server -- no radio, no mock.

The point being verified: no AX.25 framing crosses this wire at all, the
byte stream from the moment the socket connects IS the session, exactly the
way a real BPQ32 telnet listener already behaves for SyncTERM or a plain
`telnet` client today.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402

from kissterm.transport.base import SessionState, TransportError, TransportState  # noqa: E402
from kissterm.transport.telnet import TelnetTransport  # noqa: E402


@pytest.mark.asyncio
async def test_connect_delivers_the_banner_and_echoes_what_is_sent():
    received_by_server: list[bytes] = []

    async def handler(reader, writer):
        writer.write(b"Welcome to FAKE-NODE\r\n")
        await writer.drain()
        data = await reader.read(64)
        received_by_server.append(data)
        writer.write(b"echo: " + data)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    try:
        transport = TelnetTransport(host, port)
        await transport.open()
        assert transport.state is TransportState.OPEN

        session = await transport.connect()
        assert session.connected
        assert session.peer == f"{host}:{port}"

        banner = await asyncio.wait_for(session.incoming.get(), timeout=2.0)
        assert banner == b"Welcome to FAKE-NODE\r\n"

        await session.send(b"hello\r")
        echoed = await asyncio.wait_for(session.incoming.get(), timeout=2.0)
        assert echoed == b"echo: hello\r"
        assert received_by_server == [b"hello\r"]

        await asyncio.sleep(0.1)  # the server closes right after echoing
        assert session.state is SessionState.DISCONNECTED
    finally:
        await transport.close()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_connect_to_nothing_raises_transport_error():
    transport = TelnetTransport("127.0.0.1", 1)  # port 1: nothing listens there
    await transport.open()
    with pytest.raises(TransportError):
        await transport.connect()


@pytest.mark.asyncio
async def test_open_never_transmits_or_blocks_on_the_network():
    """`open()` cannot know the host is reachable and must not pretend to --
    it only prepares local state. Constructing and opening a transport for a
    host that does not resolve at all must not raise or hang."""
    transport = TelnetTransport("this-host-does-not-resolve.invalid", 23)
    await transport.open()
    assert transport.state is TransportState.OPEN
