"""The connect flow in the core, with no UI: `Connector` on a loopback.

What a phone or browser client relies on once it drives the core: a
declined reminder transmits nothing, a confirmed connect arms the gate
visibly (a record, a notice, an event), a down TNC is not reported as an RF
failure, and a disconnect during the SABMs stops them.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402

from kissterm.addressbook import Entry  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.core import Core, GateChanged, Notice  # noqa: E402
from kissterm.core.connect import CANCELLED_REASON, ConnectRequest  # noqa: E402
from kissterm.core.questions import RadioReminder  # noqa: E402
from kissterm.transport.base import TransportState  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
PEER = AX25Address.parse("WS1EC-7")


class _Operator:
    def __init__(self, answer=None) -> None:
        self.answer = answer
        self.asked: list = []
        self.notices: list[Notice] = []

    def notice(self, notice: Notice) -> None:
        self.notices.append(notice)

    async def ask(self, question):
        self.asked.append(question)
        return self.answer


class _Host:
    """Records what the flow asked of the session bookkeeping."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []
        self.bound: list[str] = []
        self.opened: list[str] = []
        self.links: dict = {}

    def active_key(self) -> str:
        return ""

    def link(self, key):
        return self.links.get(key)

    def has_room_for(self, key) -> bool:
        return True

    def open_session(self, key, *, kind, focus) -> None:
        self.opened.append(key)

    def bind(self, link, key, *, activate=True) -> None:
        self.links[key] = link
        self.bound.append(key)

    def record(self, key, text) -> None:
        self.records.append((key, text))

    note = record

    def is_active(self, key) -> bool:
        return True

    def focus_input(self) -> None:
        pass

    def echo_sent(self, key, shown, sent, *, watch_hop=True) -> None:
        pass

    def commit_hop(self, key, node) -> None:
        pass

    def connecting_changed(self) -> None:
        pass


def _params() -> LinkParams:
    return LinkParams(t1=0.2, t2=0.05, t3=5.0, connect_retries=3)


async def _core(operator, *, peer_answers: bool = True):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    station = AX25Station(MYCALL, ta, _params())
    peer = AX25Station(PEER, tb, _params(), accept_incoming=peer_answers)
    core = Core(Config(mycall=str(MYCALL)), station, operator=operator)
    host = _Host()
    core.use_session_host(host)
    core.attach_station()
    return core, host, station, peer, ta


@pytest.mark.asyncio
async def test_a_declined_reminder_transmits_nothing_and_arms_nothing():
    operator = _Operator(answer=False)
    core, host, station, peer, ta = await _core(operator)
    entry = Entry("WS1EC-7", frequency="145.090")
    await core.connector.connect(ConnectRequest("WS1EC-7"), entry=entry)
    assert operator.asked == [RadioReminder("145.090", "", "")]
    assert ta.sent == [], "a cancelled reminder still transmitted"
    assert core.gate.enabled is False
    assert host.opened == [], "a cancelled reminder changed what is on screen"
    station.close()
    peer.close()


@pytest.mark.asyncio
async def test_a_confirmed_connect_arms_visibly_and_comes_up():
    operator = _Operator(answer=True)
    core, host, station, peer, ta = await _core(operator)
    events = []
    core.events.subscribe(lambda seq, event: events.append(event))
    reached = []
    await core.connector.connect(
        ConnectRequest("WS1EC-7"), entry=Entry("WS1EC-7", frequency="145.090"),
        on_reached=reached.append)
    assert core.gate.enabled is True
    assert GateChanged(True) in events
    assert ("WS1EC-7", "Transmit enabled automatically for: connect to WS1EC-7") in host.records
    assert any("Transmit ENABLED" in n.text for n in operator.notices)
    assert host.bound == ["WS1EC-7"] and reached == [True]
    assert host.links["WS1EC-7"].connected
    station.close()
    peer.close()


@pytest.mark.asyncio
async def test_a_down_tnc_is_not_called_an_rf_problem_and_arms_nothing():
    operator = _Operator()
    core, host, station, peer, ta = await _core(operator)
    ta.state = TransportState.ERROR
    await core.connector.connect(ConnectRequest("WS1EC-7"))
    assert ta.sent == []
    assert core.gate.enabled is False
    assert any("not an RF problem" in n.text for n in operator.notices)
    station.close()
    peer.close()


@pytest.mark.asyncio
async def test_a_disconnect_during_the_sabms_cancels_them():
    operator = _Operator()
    core, host, station, peer, ta = await _core(operator, peer_answers=False)
    peer.close()  # nobody answers
    task = asyncio.ensure_future(core.connector.connect(ConnectRequest("WS1EC-7")))
    for _ in range(100):
        if core.connector.connecting:
            break
        await asyncio.sleep(0.01)
    assert core.connector.connecting
    await core.connector.disconnect("WS1EC-7")
    await asyncio.wait_for(task, 5)
    assert core.connector.connecting == {}
    assert ("WS1EC-7", "Connect to WS1EC-7 cancelled") in host.records
    failed = station.link_to(PEER, 0)
    assert failed is None or failed.last_error == CANCELLED_REASON
    station.close()


@pytest.mark.asyncio
async def test_nobody_present_means_a_reminder_is_declined():
    core, host, station, peer, ta = await _core(None)
    await core.connector.connect(
        ConnectRequest("WS1EC-7"), entry=Entry("WS1EC-7", note="ask first"))
    assert ta.sent == [] and core.gate.enabled is False
    station.close()
    peer.close()
