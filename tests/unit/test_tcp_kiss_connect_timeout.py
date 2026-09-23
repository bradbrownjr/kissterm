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


class _Tty:
    """A stream that claims to be a terminal and records what it was sent."""

    def __init__(self, tty=True):
        self.text = ""
        self._tty = tty

    def isatty(self):
        return self._tty

    def write(self, s):
        self.text += s

    def flush(self):
        pass


class _SlowTransport:
    def __init__(self, delay, timeout=None, fail=False):
        self.delay, self.fail = delay, fail
        if timeout is not None:
            self.connect_timeout = timeout

    async def open(self):
        await asyncio.sleep(self.delay)
        if self.fail:
            raise TransportError("connect to 10.0.0.1:8001 failed: no answer")


@pytest.mark.asyncio
async def test_startup_names_the_modem_reminds_to_start_it_and_counts_down():
    from kissterm.__main__ import _open_with_progress

    out = _Tty()
    entry = {"kind": "tcp", "name": "direwolf"}
    await _open_with_progress(_SlowTransport(1.2, timeout=10), entry, out)
    assert "modem software" in out.text and "Start it first" in out.text
    assert "Connecting to modem 'direwolf'..." in out.text
    assert "10s until timeout" in out.text and "9s until timeout" in out.text
    assert out.text.endswith("\n")


@pytest.mark.asyncio
async def test_a_failed_open_still_raises_and_leaves_the_line_finished():
    from kissterm.__main__ import _open_with_progress

    out = _Tty()
    with pytest.raises(TransportError):
        await _open_with_progress(_SlowTransport(0.01, fail=True), {"kind": "tcp", "name": "x"}, out)
    assert out.text.endswith("\n")


@pytest.mark.asyncio
async def test_piped_output_gets_one_line_and_no_carriage_returns():
    from kissterm.__main__ import _open_with_progress

    out = _Tty(tty=False)
    await _open_with_progress(_SlowTransport(0.01), {"kind": "telnet", "name": "gb7x"}, out)
    assert out.text == "Connecting to node 'gb7x'...\n"
