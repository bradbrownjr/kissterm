"""Internet contacts: a Telnet or SSH Address Book entry dialed into its
own Terminal tab, beside the radio (operator, 2026-09-26: "create all of
their contacts in the address book regardless of transport").

The radio here is a loopback AX25Station with the transmit gate CLOSED,
as at every launch. The point being proven is that an Internet session
neither needs nor opens it: dialing, the login script, typing and Ctrl+D
all work with the gate shut, and the gate is still shut afterwards.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402

from kissterm.addressbook import AddressBook  # noqa: E402
from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config, set_credential  # noqa: E402
from kissterm.ui.terminal_pane import TerminalPane  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402
from tests.pilot._wait import wait_for  # noqa: E402

MYCALL = AX25Address.parse("KC1JMH-7")


class _Node:
    """A Telnet node that records every chunk it hears."""

    def __init__(self) -> None:
        self.heard = b""
        self.closed = asyncio.Event()

    async def serve(self, reader, writer) -> None:
        writer.write(b"Welcome to FAKE-NODE\r\n")
        await writer.drain()
        while data := await reader.read(256):
            self.heard += data
            writer.write(b"echo: " + data)
            await writer.drain()
        self.closed.set()


async def _app(tmp_path):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = Config(mycall=str(MYCALL))  # the gate starts closed
    station = AX25Station(MYCALL, ta, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    app = KissTermApp(config, station)
    app.addressbook = AddressBook(tmp_path / "addressbook.json")
    return app, station


def _log(app) -> str:
    log = app.query_one(TerminalPane).query_one("#session-log")
    return "\n".join(str(line) for line in log.lines)


@pytest.mark.asyncio
async def test_a_telnet_contact_dials_beside_the_radio_without_the_gate(tmp_path):
    node = _Node()
    server = await asyncio.start_server(node.serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    app, station = await _app(tmp_path)
    entry = app.addressbook.upsert("Home by Telnet", connect_by="telnet", host="127.0.0.1",
                                   port=str(port), script="BBS")
    try:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert not app.gate.enabled
            app.action_connect(prefill=entry)
            await wait_for(lambda: b"BBS\r" in node.heard, "the login script")
            assert app.station is station  # the radio stays bound
            assert app._active_key() == "Home by Telnet"
            await wait_for(lambda: "Welcome to FAKE-NODE" in _log(app), "the node's greeting")
            # Typing goes out with the gate shut, and does not open it.
            app.query_one("#session-input").value = "LM"
            await pilot.press("enter")
            await wait_for(lambda: b"LM\r" in node.heard, "the typed line")
            assert not app.gate.enabled
            assert app.addressbook.find("Home by Telnet").connects == 1
            # Ctrl+D hangs up without arming anything.
            app.action_show_tab("terminal")
            await pilot.pause()
            await pilot.press("ctrl+d")
            await asyncio.wait_for(node.closed.wait(), 5)
            await wait_for(lambda: app.link is None or not app.link.connected, "the hang-up")
            assert not app.gate.enabled
            # Ctrl+R dials it again.
            node.heard = b""
            await pilot.press("ctrl+r")
            await wait_for(lambda: b"BBS\r" in node.heard, "the redial")
            assert not app.gate.enabled
    finally:
        station.close()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_a_contact_that_cannot_connect_says_why_and_leaves_nothing_open(tmp_path):
    app, station = await _app(tmp_path)
    entry = app.addressbook.upsert("Nowhere", connect_by="telnet", host="127.0.0.1", port="1")
    try:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_connect(prefill=entry)
            await wait_for(lambda: "Could not connect" in _log(app), "the failure")
            assert not app._internet_connecting
            assert not app.gate.enabled
    finally:
        station.close()


asyncssh = pytest.importorskip("asyncssh")
from tests.unit.test_ssh_transport import PASSWORD, USERNAME, ssh_server  # noqa: E402,F401


@pytest.mark.asyncio
async def test_an_ssh_contact_logs_in_with_its_saved_password(tmp_path, ssh_server):
    host, port, _key, known_hosts, state = ssh_server
    app, station = await _app(tmp_path)
    set_credential(app.config, "WS1EC SSH password", PASSWORD)
    entry = app.addressbook.upsert("WS1EC", connect_by="ssh", host=host, port=str(port),
                                   username=USERNAME, password_login="WS1EC SSH password",
                                   known_hosts=str(known_hosts), script="C 2")
    try:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_connect(prefill=entry)
            # The fake shell reads to LF and kissterm ends lines with CR, as
            # BPQ expects, so it cannot echo the line: see that it went out.
            await wait_for(lambda: "Welcome to FAKE-NODE" in _log(app), "the shell's greeting")
            await wait_for(lambda: "Auto-login: sending 1 line" in _log(app), "the login script")
            assert state["shells"] == 1
            assert not app.gate.enabled
            assert PASSWORD not in _log(app)
    finally:
        station.close()
