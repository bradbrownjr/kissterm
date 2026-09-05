"""Telling a KISS TNC from a web app on the same port number.

A scan that identifies services by port number alone is wrong often enough to
matter: 8000 and 8001 are as popular with self-hosted web apps as with packet
software, and a false positive gets written straight into `config.transports`
and then hunted for as a missing TNC.

Every test here runs a REAL asyncio server, so what is proven is the byte
exchange, not a mock's idea of one. Note which direction is strong: the
negatives are conclusive (a web server cannot answer in KISS framing), the
positive for raw KISS is not (a healthy idle TNC says nothing at all).
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402

from kissterm.discovery import identify_tcp  # noqa: E402
from kissterm.transport.agwpe import HEADER_LEN, parse_header  # noqa: E402
from kissterm.transport.kiss import FEND, KissCommand, encode  # noqa: E402


async def _serve(handler):
    """Start `handler` on a loopback port and return ``(host, port, server)``."""
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    return host, port, server


async def _identify(handler, **kw):
    host, port, server = await _serve(handler)
    try:
        return await identify_tcp(host, port, timeout=1.0, **kw)
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_a_web_server_is_ruled_out_not_listed():
    """The exact false positive that started this: a self-hosted app on 8001."""

    async def handler(reader, writer):
        await reader.read(64)
        writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()

    identity = await _identify(handler)
    assert identity.verdict == "not-a-tnc", identity.summary
    assert identity.is_disproved
    assert "web server" in identity.summary


@pytest.mark.asyncio
async def test_a_server_that_hangs_up_is_ruled_out():
    """A KISS endpoint ignores stray framing bytes and stays connected.
    Hanging up on two FENDs is what something wanting a parseable request does."""

    async def handler(reader, writer):
        await reader.read(64)
        writer.close()

    identity = await _identify(handler)
    assert identity.verdict == "not-a-tnc", identity.summary
    assert "closed the connection" in identity.summary


@pytest.mark.asyncio
async def test_an_ssh_server_is_ruled_out_from_its_greeting_alone():
    """Some services speak first. That costs us nothing and settles it."""

    async def handler(reader, writer):
        writer.write(b"SSH-2.0-OpenSSH_9.6\r\n")
        await writer.drain()
        await asyncio.sleep(0.5)

    identity = await _identify(handler)
    assert identity.verdict == "not-a-tnc", identity.summary
    assert "SSH" in identity.summary


@pytest.mark.asyncio
async def test_a_kiss_frame_confirms_a_tnc():
    """The positive case, when the channel is not silent."""

    async def handler(reader, writer):
        await reader.read(64)
        writer.write(encode(b"\x00hello", 0, KissCommand.DATA))
        await writer.drain()
        await asyncio.sleep(0.5)

    identity = await _identify(handler)
    assert identity.verdict == "kiss", identity.summary
    assert identity.is_tnc


@pytest.mark.asyncio
async def test_a_silent_port_is_unknown_never_a_failure():
    """A correctly wired KISS TNC on a quiet channel has nothing to send.
    Reporting that as "not a TNC" would be the worst possible answer: it is
    what a WORKING station looks like."""

    async def handler(reader, writer):
        await reader.read(64)
        await asyncio.sleep(2.0)

    identity = await _identify(handler)
    assert identity.verdict == "unknown", identity.summary
    assert not identity.is_disproved
    assert "quiet channel" in identity.summary


@pytest.mark.asyncio
async def test_nothing_listening_is_unreachable():
    host, port, server = await _serve(lambda r, w: None)
    server.close()
    await server.wait_closed()
    identity = await identify_tcp(host, port, timeout=0.5)
    assert identity.verdict == "unreachable"


@pytest.mark.asyncio
async def test_an_agwpe_engine_answers_a_version_query():
    """AGWPE is the one protocol here that can be confirmed outright, because
    it has a question that asks the SOFTWARE something ('R', version) rather
    than asking the radio to do anything."""
    seen: list[bytes] = []

    async def handler(reader, writer):
        import struct

        from kissterm.transport.agwpe import _build_header

        header = await reader.readexactly(HEADER_LEN)
        _port, kind, _len = parse_header(header)
        seen.append(kind)
        # Built with the transport's own header packer, so this cannot pass
        # against a header shape this repo would never itself produce.
        payload = struct.pack("<II", 2023, 3)
        writer.write(_build_header(0, b"R", data_len=len(payload)) + payload)
        await writer.drain()
        await asyncio.sleep(1.0)

    identity = await _identify(handler, kind="agwpe")
    assert identity.verdict == "agwpe", identity.summary
    assert seen == [b"R"], f"probe sent {seen!r}, not a version query"
    assert "2023.3" in identity.summary


@pytest.mark.asyncio
async def test_vara_is_never_spoken_to():
    """VARA's command port takes line commands that can start a session.
    The probe must not touch it -- if this test ever fails, discovery has
    started talking to a modem that can act on what it hears."""
    contacted = asyncio.Event()

    async def handler(reader, writer):
        contacted.set()

    host, port, server = await _serve(handler)
    try:
        identity = await identify_tcp(host, port, kind="vara", timeout=0.5)
    finally:
        server.close()
        await server.wait_closed()
    assert identity.verdict == "unknown"
    assert "does not speak to it" in identity.summary
    assert not contacted.is_set(), "the probe connected to a VARA port"


@pytest.mark.asyncio
async def test_the_kiss_probe_can_never_become_a_transmission():
    """The safety claim, checked on the wire rather than asserted in a
    docstring: a KISS frame is FEND, type byte, payload, FEND. What goes out
    is two FENDs -- no type byte, so there is no command to act on and
    nothing that decodes as a frame to put on the air."""
    received = bytearray()

    async def handler(reader, writer):
        received.extend(await reader.read(64))
        await asyncio.sleep(1.0)

    host, port, server = await _serve(handler)
    try:
        await identify_tcp(host, port, timeout=0.6)
    finally:
        server.close()
        await server.wait_closed()

    assert bytes(received) == bytes([FEND, FEND]), f"probe wrote {bytes(received)!r}"

    from kissterm.transport.kiss import KissDecoder

    assert list(KissDecoder().feed(bytes(received))) == [], (
        "the probe bytes decoded as a KISS frame"
    )
