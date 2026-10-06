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


class _KeyboardPipe:
    """A stdin that claims to be a terminal, on a real descriptor the event
    loop can watch; `press()` is the operator hitting Enter."""

    def __init__(self):
        import os

        self.r, self.w = os.pipe()

    def fileno(self):
        return self.r

    def isatty(self):
        return True

    def press(self):
        import os

        os.write(self.w, b"\n")

    def close(self):
        import os

        os.close(self.r)
        os.close(self.w)


class _HangingModem:
    connect_timeout = 10

    def __init__(self):
        self.closed = False

    async def open(self):
        await asyncio.sleep(3600)

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_enter_skips_the_wait_and_closes_the_half_open_modem():
    """Operator, 2026-10-06: the radio room's modem was off; Telnet/SSH
    contacts need none, so the wait offers a way past it."""
    from kissterm.__main__ import OpenSkipped, _open_with_progress

    out, keys, modem = _Tty(), _KeyboardPipe(), _HangingModem()
    try:
        asyncio.get_running_loop().call_later(0.2, keys.press)
        with pytest.raises(OpenSkipped):
            await asyncio.wait_for(
                _open_with_progress(modem, {"kind": "tcp", "name": "dw"}, out, keys), 5
            )
    finally:
        keys.close()
    assert "Press Enter to start without it" in out.text
    assert out.text.rstrip().endswith("Connecting to modem 'dw'... skipped")
    assert modem.closed, "a skipped modem must not keep dialling behind the app"


@pytest.mark.asyncio
async def test_a_node_over_the_internet_offers_no_skip():
    """Telnet/SSH is the Internet connection itself; skipping it leaves nothing."""
    from kissterm.__main__ import _open_with_progress

    out, keys = _Tty(), _KeyboardPipe()
    try:
        await _open_with_progress(_SlowTransport(0.01), {"kind": "telnet", "name": "gb7x"}, out, keys)
    finally:
        keys.close()
    assert "Press Enter" not in out.text


class _Stdin:
    def __init__(self, answer, tty=True):
        self.answer, self._tty = answer, tty

    def isatty(self):
        return self._tty

    def readline(self):
        return self.answer


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("\n", True), ("y\n", True), ("YES\n", True), ("n\n", False), ("", False)],
)
def test_start_anyway_defaults_to_yes_and_eof_means_no(answer, expected):
    from kissterm.__main__ import _offer_start_anyway

    out = _Tty()
    assert _offer_start_anyway(_Stdin(answer), out, environ={}) is expected
    assert "open the TNC settings" in out.text


def test_start_anyway_never_prompts_a_script():
    """A service or pipe keeps the old non-zero exit; it cannot answer."""
    from kissterm.__main__ import _offer_start_anyway

    out = _Tty(tty=False)
    assert _offer_start_anyway(_Stdin("y\n", tty=False), out, environ={}) is False
    assert out.text == ""


def test_start_anyway_in_a_browser_starts_without_asking():
    """`textual serve` runs kissterm with no terminal to answer on; exiting
    left the browser at "Application failed to start" (ROADMAP P6)."""
    from kissterm.__main__ import _offer_start_anyway

    out = _Tty(tty=False)
    environ = {"TEXTUAL_DRIVER": "textual.drivers.web_driver:WebDriver"}
    assert _offer_start_anyway(_Stdin("", tty=False), out, environ=environ) is True
    assert out.text == ""


# ROADMAP P3: every TCP transport, not just KISS, gives up and says why.


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agwpe", "telnet", "vara"])
async def test_every_tcp_transport_fails_fast_on_a_silent_host(monkeypatch, kind):
    from kissterm.transport import base, build_transport

    async def never_answers(host, port):
        await asyncio.sleep(3600)

    monkeypatch.setattr(base, "CONNECT_TIMEOUT", 0.05)
    monkeypatch.setattr(base.asyncio, "open_connection", never_answers)
    entry = {"kind": kind, "host": "192.0.2.1", "port": 8000}
    if kind == "vara":
        entry = {"kind": "vara", "host": "192.0.2.1", "mycall": "N1ABC-1"}
    transport = build_transport(entry)
    with pytest.raises(TransportError, match="no answer within"):
        await asyncio.wait_for(transport.open(), timeout=2)
        await asyncio.wait_for(transport.connect(), timeout=2)  # telnet connects here
    await transport.close()


@pytest.mark.asyncio
async def test_the_aprs_is_watch_says_a_silent_server_timed_out(monkeypatch):
    from kissterm.aprs_is import AprsIsWatch
    from kissterm.transport import base

    async def never_answers(host, port):
        await asyncio.sleep(3600)

    monkeypatch.setattr(base, "CONNECT_TIMEOUT", 0.05)
    monkeypatch.setattr(base.asyncio, "open_connection", never_answers)
    watch = AprsIsWatch()
    from kissterm.aprs_is import AprsIsAccess

    await asyncio.wait_for(watch._run("N1ABC", "192.0.2.1", 14580, AprsIsAccess(), ""), 2)
    assert "no answer within" in watch.status
