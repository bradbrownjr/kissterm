"""Tests for the receive-only APRS-IS compressed-range capture helper."""

from __future__ import annotations

import asyncio

import pytest

from kissterm.aprs_is_capture import capture_precalculated_range, find_precalculated_range


def test_finds_a_compressed_precalculated_range_packet():
    line = "N1ABC-9>APRS,TCPIP*,qAC,IGATE:=/5L!!<*e8>{+!Range flagged\r\n"

    capture = find_precalculated_range(line)

    assert capture is not None
    assert capture.source == "N1ABC-9"
    assert capture.info == "=/5L!!<*e8>{+!Range flagged"
    assert capture.range_mi == pytest.approx(2 * (1.08**10))


@pytest.mark.parametrize(
    "line",
    [
        "# logresp N1ABC unverified, server test\r\n",
        "N1ABC>APRS:>status mentions { but is not a position\r\n",
        "N1ABC>APRS:=/5L!!<*e8>7P!comment has { but cs is course/speed\r\n",
    ],
)
def test_ignores_non_range_lines(line):
    assert find_precalculated_range(line) is None


@pytest.mark.asyncio
async def test_capture_bounds_connection_setup(monkeypatch):
    async def never_connect(*_args, **_kwargs):
        await asyncio.Future()

    monkeypatch.setattr(asyncio, "open_connection", never_connect)

    with pytest.raises(TimeoutError):
        await capture_precalculated_range(
            host="example.invalid",
            port=14580,
            callsign="N1ABC",
            latitude=42.0,
            longitude=-71.0,
            radius_km=75,
            timeout_seconds=0.01,
        )


@pytest.mark.asyncio
async def test_capture_returns_none_when_no_matching_packet_arrives():
    async def handler(reader, writer):
        await reader.readline()
        writer.write(b"# logresp N1ABC unverified, server test\r\n")
        await writer.drain()
        await asyncio.sleep(1)
        writer.close()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        capture = await capture_precalculated_range(
            host="127.0.0.1",
            port=port,
            callsign="N1ABC",
            latitude=42.0,
            longitude=-71.0,
            radius_km=75,
            timeout_seconds=0.01,
        )
    finally:
        server.close()
        await server.wait_closed()

    assert capture is None


@pytest.mark.asyncio
async def test_capture_uses_an_unverified_login_and_never_sends_a_packet():
    login_lines: list[bytes] = []

    async def handler(reader, writer):
        login_lines.append(await reader.readline())
        writer.write(b"# logresp N1ABC unverified, server test\r\n")
        writer.write(b"N1ABC>APRS,TCPIP*,qAC,IGATE:=/5L!!<*e8>{+!Range flagged\r\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        capture = await capture_precalculated_range(
            host="127.0.0.1",
            port=port,
            callsign="N1ABC",
            latitude=42.0,
            longitude=-71.0,
            radius_km=75,
            timeout_seconds=1,
        )
    finally:
        server.close()
        await server.wait_closed()

    assert capture is not None
    assert login_lines == [
        b"user N1ABC pass -1 vers kissterm capture filter r/42.00000/-71.00000/75\r\n"
    ]
