"""AGWPE's socket lifecycle, exercised against a real loopback engine."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402

from kissterm.transport.agwpe import (  # noqa: E402
    HEADER_LEN,
    AgwpeTransport,
    _build_header,
    parse_header,
    parse_port_info,
)
from kissterm.transport.base import TransportState  # noqa: E402


def test_parse_port_info_keeps_the_engine_count_and_labels():
    count, labels = parse_port_info(
        b"2;Port1 145.030 MHz 1200 baud;Port2 loopback;\x00\x00"
    )

    assert count == 2
    assert labels == ("Port1 145.030 MHz 1200 baud", "Port2 loopback")


def test_parse_port_info_fills_in_an_omitted_description():
    count, labels = parse_port_info(b"2;Port1 VHF;")

    assert count == 2
    assert labels == ("Port1 VHF", "Port 2")


@pytest.mark.asyncio
async def test_reconnects_and_refreshes_engine_port_info(monkeypatch):
    """A restart is visible as reconnecting, then resumes without app restart."""
    import kissterm.transport.agwpe as agwpe

    monkeypatch.setattr(agwpe, "_INITIAL_BACKOFF", 0.01)
    connected_twice = asyncio.Event()
    keep_second_connection = asyncio.Event()
    requests: list[list[bytes]] = []

    async def handler(reader, writer):
        kinds: list[bytes] = []
        for _ in range(3):
            header = await reader.readexactly(HEADER_LEN)
            _port, kind, data_len = parse_header(header)
            if data_len:
                await reader.readexactly(data_len)
            kinds.append(kind)
        requests.append(kinds)
        port_info = b"2;Port1 VHF;Port2 UHF;"
        writer.write(_build_header(0, b"G", data_len=len(port_info)) + port_info)
        await writer.drain()
        if len(requests) == 1:
            writer.close()
            await writer.wait_closed()
            return
        connected_twice.set()
        await keep_second_connection.wait()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    transport = AgwpeTransport(host, port)
    try:
        await transport.open()
        await asyncio.wait_for(connected_twice.wait(), timeout=1.0)
        await asyncio.sleep(0)

        assert transport.state is TransportState.OPEN
        assert transport.reconnects == 1
        assert transport.ports == 2
        assert transport.port_descriptions == ("Port1 VHF", "Port2 UHF")
        assert requests == [[b"m", b"k", b"G"], [b"m", b"k", b"G"]]
    finally:
        keep_second_connection.set()
        await transport.close()
        server.close()
        await server.wait_closed()
