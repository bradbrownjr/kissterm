"""`Core` with no UI attached: the transport lifecycle on a loopback.

What the terminal UI used to do itself (`ui/app.py`) and a remote client
must get the same way: the operator's gate on every transport, every
subscriber moved on a switch, an event for each change, and a failure told
to the operator rather than raised.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

import kissterm.transport as transport_mod  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams  # noqa: E402
from kissterm.ax25.frame import AX25Frame, UType  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.core import (  # noqa: E402
    Core,
    EventBus,
    GateChanged,
    Notice,
    NullOperator,
    Question,
    Severity,
    TransportChanged,
)
from tests.loopback import LoopbackTransport, loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
HEARD = AX25Address.parse("W1AW")


class _Recorder:
    def __init__(self) -> None:
        self.notices: list[Notice] = []

    def notice(self, notice: Notice) -> None:
        self.notices.append(notice)

    async def ask(self, question):
        return None


def _beacon(source: AX25Address) -> AX25Frame:
    return AX25Frame.u_frame(AX25Path(AX25Address.parse("BEACON"), source), UType.UI, info=b"hi")


def _config(**kw) -> Config:
    return Config(mycall=str(MYCALL), **kw)


def test_the_gate_starts_closed_and_is_installed_on_the_transport():
    first, _ = loopback_pair()
    station = AX25Station(MYCALL, first, LinkParams())
    core = Core(_config(), station)
    assert core.gate.enabled is False
    assert first.gate is core.gate
    station.close()


def test_a_gate_change_is_an_event():
    core = Core(_config())
    seen = []
    core.events.subscribe(lambda seq, event: seen.append((seq, event)))
    core.gate.set(True)
    assert seen == [(1, GateChanged(True))]


@pytest.mark.asyncio
async def test_a_switch_moves_every_subscriber_and_keeps_the_gate(monkeypatch):
    first, _ = loopback_pair()
    await first.open()
    second = LoopbackTransport("second")
    await second.open()
    monkeypatch.setattr(transport_mod, "build_transport", lambda entry: second)
    station = AX25Station(MYCALL, first, LinkParams())
    core = Core(
        _config(transports=[{"name": "second", "kind": "tcp", "host": "h", "port": 1}]),
        station,
    )
    received, sent, events = [], [], []
    core.frame_subscribers.append(lambda frame, port=0: received.append(frame))
    core.sent_subscribers.append(lambda frame, port=0: sent.append(frame))
    core.events.subscribe(lambda seq, event: events.append(event))
    core.attach_station()

    assert await core.switch_frame_transport("second")
    assert station.transport is second and second.gate is core.gate
    await second.send_frame(_beacon(MYCALL))
    assert second.sent == [], "a switched transport transmitted with the gate closed"
    await second.dispatch(_beacon(HEARD))
    assert len(received) == 1
    assert not first._handlers and not first.on_sent
    assert events == [TransportChanged("second", "frame", second.info.detail)]
    station.close()


@pytest.mark.asyncio
async def test_a_failed_open_is_a_notice_not_an_exception(monkeypatch):
    def _refuse(entry):
        raise OSError("connection refused")

    monkeypatch.setattr(transport_mod, "build_transport", _refuse)
    operator = _Recorder()
    core = Core(
        _config(transports=[{"name": "tnc", "kind": "tcp", "host": "h", "port": 1}]),
        operator=operator,
    )
    assert await core.switch_frame_transport("tnc") is False
    assert core.station is None
    assert [n.severity for n in operator.notices] == [Severity.ERROR]
    assert "connection refused" in operator.notices[0].text


@pytest.mark.asyncio
async def test_opening_the_first_transport_builds_a_station_and_clears_the_problem(monkeypatch):
    transport = LoopbackTransport("tnc")
    monkeypatch.setattr(transport_mod, "build_transport", lambda entry: transport)
    core = Core(
        _config(transports=[{"name": "tnc", "kind": "tcp", "host": "h", "port": 1}]),
        transport_problem="refused at launch",
    )
    assert await core.switch_frame_transport("tnc")
    assert core.station is not None and core.station.transport is transport
    assert transport.gate is core.gate
    assert core.transport_problem is None
    core.station.close()


def test_a_subscriber_that_raises_does_not_stop_the_others():
    bus = EventBus()
    seen = []

    def _broken(seq, event):
        raise RuntimeError("client bug")

    bus.subscribe(_broken)
    bus.subscribe(lambda seq, event: seen.append(seq))
    assert bus.publish(GateChanged(True)) == 1
    assert seen == [1]


@pytest.mark.asyncio
async def test_nobody_present_declines_every_question():
    assert await NullOperator().ask(Question()) is None
