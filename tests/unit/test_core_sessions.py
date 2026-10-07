"""Sessions in the core, with no UI: what a remote client will rely on.

A typed line arms the gate visibly and is echoed as an event; the far end's
bytes arrive as an event, raw; the node is identified passively from its
banner; a caller gets a session marked incoming; the reply watch speaks
only once the far end has acknowledged.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402

from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.core import Core, Notice  # noqa: E402
from kissterm.core import sessions as sessions_module  # noqa: E402
from kissterm.core.events import (  # noqa: E402
    LineSent,
    SessionData,
    SessionOpened,
    SessionUpdated,
)
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
PEER = AX25Address.parse("WS1EC-7")


class _Operator:
    def __init__(self) -> None:
        self.notices: list[Notice] = []

    def notice(self, notice: Notice) -> None:
        self.notices.append(notice)

    async def ask(self, question):
        return None


class _View:
    def active_key(self) -> str:
        return "WS1EC-7"

    def has_room_for(self, key) -> bool:
        return True

    def open_session(self, key, *, kind, focus) -> None:
        pass

    def is_active(self, key) -> bool:
        return True

    def focus_input(self) -> None:
        pass


def _params() -> LinkParams:
    return LinkParams(t1=0.2, t2=0.05, t3=5.0)


async def _setup(**config):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    operator = _Operator()
    station = AX25Station(MYCALL, ta, _params())
    peer = AX25Station(PEER, tb, _params(), accept_incoming=True)
    core = Core(Config(mycall=str(MYCALL), log_sessions=False, **config), station,
                operator=operator)
    core.attach_view(_View())
    core.attach_station()
    events: list = []
    core.events.subscribe(lambda seq, event: events.append(event))
    return core, operator, station, peer, events


@pytest.mark.asyncio
async def test_a_typed_line_arms_the_gate_and_is_echoed():
    core, operator, station, peer, events = await _setup()
    core.gate.set(True)
    link = await station.connect(AX25Path(PEER, MYCALL))
    key = core.sessions.bind(link)
    core.gate.set(False)
    heard: list[bytes] = []
    far = peer.link_to(MYCALL, 0)
    far.on_data.append(heard.append)

    assert await core.sessions.send_line(key, "BYE")
    assert core.gate.enabled, "a typed line to a connected station arms the gate"
    assert LineSent(key, "BYE") in events
    assert any("Transmit ENABLED" in n.text for n in operator.notices)
    for _ in range(50):
        if heard:
            break
        await asyncio.sleep(0.02)
    assert b"".join(heard) == b"BYE\r"
    station.close()
    peer.close()


@pytest.mark.asyncio
async def test_not_connected_sends_nothing_and_arms_nothing():
    core, operator, station, peer, events = await _setup()
    assert await core.sessions.send_line("WS1EC-7", "HELLO") is False
    assert core.gate.enabled is False
    assert [n.text for n in operator.notices] == ["Not connected."]
    station.close()
    peer.close()


@pytest.mark.asyncio
async def test_the_far_end_arrives_raw_and_identifies_the_node():
    core, operator, station, peer, events = await _setup()
    core.gate.set(True)
    link = await station.connect(AX25Path(PEER, MYCALL))
    key = core.sessions.bind(link)
    banner = b"CCEMA:WS1EC-15} BBS CHAT CONNECT BYE INFO NODES PORTS ROUTES USERS MHEARD\r"
    core.sessions.on_link_data(key, banner)
    assert SessionData(key, banner) in events
    assert core.sessions.get(key).reference.family is not None, "a BPQ banner went unrecognised"
    assert SessionUpdated(key) in events
    station.close()
    peer.close()


@pytest.mark.asyncio
async def test_a_caller_gets_a_session_marked_incoming():
    core, operator, station, peer, events = await _setup(accept_incoming=True)
    core.gate.set(True)
    station.accept_incoming = True
    far = await peer.connect(AX25Path(MYCALL, PEER))
    assert far is not None
    for _ in range(50):
        if any(isinstance(e, SessionOpened) for e in events):
            break
        await asyncio.sleep(0.02)
    [opened] = [e for e in events if isinstance(e, SessionOpened)]
    assert opened.incoming and opened.peer == str(PEER)
    assert any(f"Connection from {PEER}" == n.text for n in operator.notices)
    station.close()
    peer.close()


@pytest.mark.asyncio
async def test_the_reply_watch_speaks_only_after_an_acknowledgement(monkeypatch):
    monkeypatch.setattr(sessions_module, "REPLY_WAIT_SECONDS", 0.4)
    core, operator, station, peer, events = await _setup()
    core.gate.set(True)
    link = await station.connect(AX25Path(PEER, MYCALL))
    key = core.sessions.bind(link)
    await core.sessions.send_line(key, "INFO")
    for _ in range(100):
        if any("acknowledged that" in n.text for n in operator.notices):
            break
        await asyncio.sleep(0.02)
    assert any("acknowledged that -- no reply yet" in n.text for n in operator.notices)
    station.close()
    peer.close()


@pytest.mark.asyncio
async def test_the_reference_and_suggestions_come_from_the_node_in_effect_and_send_nothing():
    core, operator, station, peer, events = await _setup()
    core.gate.set(True)
    link = await station.connect(AX25Path(PEER, MYCALL))
    key = core.sessions.bind(link)
    core.sessions.on_link_data(
        key, b"CCEMA:WS1EC-15} BBS CHAT CONNECT BYE INFO NODES PORTS ROUTES USERS MHEARD\r")
    view = core.sessions.reference_view(key)
    first = view["sections"][0]
    assert first["title"] and first["commands"]
    assert {"name", "usage", "summary", "source", "context", "sysop"} <= set(first["commands"][0])
    assert view["can_harvest"] is True and view["peer"]
    assert len(view["airtime"]) == 2
    assert core.sessions.suggest(key, "") == []
    found = core.sessions.suggest(key, "nod")
    assert found and found[0]["name"] == "N"  # NODES is its alias
    assert not any(c["sysop"] for c in first["commands"] if c["name"] in {f["name"] for f in found})
    assert core.sessions.reference_view("nobody") == {} and core.sessions.suggest("nobody", "n") == []
    station.close()
    peer.close()
