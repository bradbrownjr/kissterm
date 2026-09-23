"""A TNC host that is down must fail fast and say why.

A host that drops SYNs (powered off, wrong VLAN) gives no RST, so an unbounded
`asyncio.open_connection` waits out the kernel's SYN retries -- about two
minutes on Linux -- while `kissterm` shows a blank terminal. Seen on a real
station, 2026-09-23. The error must also name the timeout: `TimeoutError` is an
`OSError` with an empty message, which would print as "failed: " and nothing.
"""

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402

from kissterm.transport import tcp_kiss  # noqa: E402
from kissterm.transport.base import TransportError  # noqa: E402


@pytest.mark.asyncio
async def test_an_unanswering_host_fails_within_the_connect_timeout(monkeypatch):
    async def never_answers(host, port):
        await asyncio.sleep(3600)

    monkeypatch.setattr(tcp_kiss, "_CONNECT_TIMEOUT", 0.05)
    monkeypatch.setattr(tcp_kiss.asyncio, "open_connection", never_answers)
    transport = tcp_kiss.TcpKissTransport(host="192.0.2.1", port=8001)
    with pytest.raises(TransportError, match="no answer within"):
        await asyncio.wait_for(transport.open(), timeout=2)
    await transport.close()
