"""Mercury's documented VARA-compatible TNC interface over real loopback TCP."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402

from kissterm.ax25.address import parse_path  # noqa: E402
from kissterm.transport.mercury import DEFAULT_MERCURY_PORT, MercuryTransport  # noqa: E402


@pytest.mark.asyncio
async def test_mercury_uses_control_and_data_sockets_with_documented_commands():
    commands: list[str] = []
    received = asyncio.Event()

    async def control(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                line = await reader.readuntil(b"\r")
                command = line[:-1].decode("ascii")
                commands.append(command)
                writer.write(b"OK\r\n")
                if command.startswith("CONNECT "):
                    writer.write(b"CONNECTED\r\n")
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    async def data(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            payload = await reader.read(4096)
            if payload:
                writer.write(payload)
                await writer.drain()
                received.set()
        finally:
            writer.close()

    control_server = await asyncio.start_server(control, "127.0.0.1", 0)
    cmd_port = control_server.sockets[0].getsockname()[1]
    data_server = await asyncio.start_server(data, "127.0.0.1", 0)
    data_port = data_server.sockets[0].getsockname()[1]
    transport = MercuryTransport("127.0.0.1", "N1ABC", port=cmd_port, data_port=data_port)
    try:
        await transport.open()
        session = await transport.connect(parse_path("K1ABC"))
        await session.send(b"hello")
        await asyncio.wait_for(received.wait(), timeout=1)
        assert await asyncio.wait_for(session.incoming.get(), timeout=1) == b"hello"
        assert commands == [
            "MYCALL N1ABC",
            "LISTEN ON",
            "PUBLIC ON",
            "CONNECT N1ABC K1ABC",
        ]
        await transport.close()
    finally:
        control_server.close()
        data_server.close()
        await control_server.wait_closed()
        await data_server.wait_closed()


def test_mercury_defaults_to_its_documented_port_pair():
    transport = MercuryTransport("127.0.0.1", "N1ABC")

    assert transport.info.kind == "mercury"
    assert transport.cmd_port == DEFAULT_MERCURY_PORT
    assert transport.data_port == DEFAULT_MERCURY_PORT + 1
