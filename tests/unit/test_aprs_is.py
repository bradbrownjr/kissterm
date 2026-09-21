"""Tests for the APRS-IS diagnostic stream -- no Internet connection needed."""

from __future__ import annotations

import asyncio

import pytest

from kissterm.aprs_is import AprsIsAccess, AprsIsMode, AprsIsWatch, callsign_filter, login_line


def test_watch_filter_covers_our_packets_and_messages_addressed_to_us():
    assert callsign_filter("kc1jmh-9") == "b/KC1JMH-9 g/KC1JMH-9"


def test_receive_only_login_is_unverified_and_has_no_passcode():
    line = login_line("kc1jmh", AprsIsAccess(), filter_text=callsign_filter("kc1jmh"))

    assert line == b"user KC1JMH pass -1 vers kissterm watch filter b/KC1JMH g/KC1JMH\r\n"


def test_verified_access_is_representable_but_needs_a_real_passcode():
    with pytest.raises(ValueError, match="passcode"):
        AprsIsAccess(AprsIsMode.VERIFIED).login_pass()
    assert AprsIsAccess(AprsIsMode.VERIFIED, "12345").login_pass() == "12345"


@pytest.mark.asyncio
async def test_watch_receives_sanitized_lines_and_writes_only_login():
    received: list[bytes] = []

    async def handler(reader, writer):
        received.append(await reader.readline())
        writer.write(b"# logresp KC1JMH unverified\r\n")
        writer.write(b"KC1JMH>APRS,qAR,WS1EC-15::WXBOT    :brief{3\r\n")
        writer.write(b"BAD\x1b[2JPACKET\r\n")
        await writer.drain()
        await asyncio.sleep(0.05)
        writer.close()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        watch = AprsIsWatch()
        watch.start(callsign="kc1jmh", host="127.0.0.1", port=port)
        for _ in range(50):
            if watch.status == "Disconnected by APRS-IS":
                break
            await asyncio.sleep(0.01)
    finally:
        server.close()
        await server.wait_closed()

    assert received == [
        b"user KC1JMH pass -1 vers kissterm watch filter b/KC1JMH g/KC1JMH\r\n"
    ]
    assert list(watch.lines) == [
        "# logresp KC1JMH unverified",
        "KC1JMH>APRS,qAR,WS1EC-15::WXBOT    :brief{3",
        "BADPACKET",
    ]
    assert watch.status == "Disconnected by APRS-IS"
