"""Broadcast: free text with no connection, and the broadcasts heard
(`core/broadcast.py`)."""

from __future__ import annotations

import asyncio

import pytest

from kissterm._isolate import isolate

isolate()

from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.ax25.frame import AX25Frame, UType  # noqa: E402
from kissterm.ax25.address import AX25Path  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.core import Core, broadcast  # noqa: E402
from kissterm.core.events import BroadcastHeard  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402
from tests.unit.test_core_sessions import _Operator, _View  # noqa: E402

MYCALL = AX25Address.parse("KC1JMH-7")


async def _core(**config):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    params = LinkParams(t1=0.2, t2=0.05, t3=5.0)
    station = AX25Station(MYCALL, ta, params)
    peer = AX25Station(AX25Address.parse("W1BKW"), tb, params)
    operator = _Operator()
    core = Core(Config(mycall=str(MYCALL), log_sessions=False, **config), station, operator=operator)
    core.attach_view(_View())
    core.attach_station()
    events: list = []
    core.events.subscribe(lambda seq, event: events.append(event))
    return core, operator, ta, tb, events


def _ui(to: str, text: bytes, *, pid: int = 0xF0, source: str = "W1BKW") -> AX25Frame:
    path = AX25Path(AX25Address.parse(to), AX25Address.parse(source), ())
    return AX25Frame.u_frame(path, UType.UI, command=False, info=text, pid=pid)


@pytest.mark.asyncio
async def test_a_broadcast_arms_the_gate_goes_out_as_one_ui_frame_and_is_listed():
    core, operator, ta, tb, events = await _core()
    assert not core.gate.enabled
    assert await core.broadcast.send("cq", "Net starts at 7 PM\n\nBring a radio") == ""
    assert core.gate.enabled, "pressing Send is the commitment that arms the gate"
    [frame] = [f for f in ta.sent if f.utype is UType.UI]
    assert str(frame.path.destination) == "CQ" and str(frame.path.source) == "KC1JMH-7"
    assert frame.info == b"Net starts at 7 PM\rBring a radio" and frame.pid == 0xF0
    [mine] = core.broadcast.recent()
    assert mine["own"] and mine["to"] == "CQ"
    assert any(isinstance(e, BroadcastHeard) and e.own for e in events)


@pytest.mark.asyncio
async def test_refusals_say_why_and_send_nothing():
    core, operator, ta, tb, events = await _core()
    assert "Send to one of" in await core.broadcast.send("APRS", "hi")
    assert "nothing to send" in await core.broadcast.send("CQ", " \n ")
    assert not ta.sent and not core.gate.enabled
    core.station = None
    assert "no radio transport" in await core.broadcast.send("CQ", "hi")


@pytest.mark.asyncio
async def test_only_plain_text_ui_frames_to_broadcast_addresses_are_heard_and_sanitized():
    core, operator, ta, tb, events = await _core()
    await tb.send_frame(_ui("CQ", b"Anyone on? \x1b[31mred\x00"))
    await tb.send_frame(_ui("QST", b"Net tonight", source="N1ABC-1"))
    await tb.send_frame(_ui("APRS", b"!4300.00N/07000.00W>position"))   # APRS: not a broadcast
    await tb.send_frame(_ui("CQ", b"netrom", pid=0xCF))                   # another protocol
    await asyncio.sleep(0.2)
    heard = core.broadcast.recent()
    assert [(h["source"], h["to"]) for h in heard] == [("W1BKW", "CQ"), ("N1ABC-1", "QST")]
    assert "\x1b" not in heard[0]["text"] and "\x00" not in heard[0]["text"]
    assert not any(h["own"] for h in heard)


def test_cost_is_in_words():
    assert broadcast.cost("") == "nothing to send"
    assert "channel" in broadcast.cost("hello")


@pytest.mark.asyncio
async def test_a_broadcast_under_the_tactical_call_is_identified_afterwards():
    core, operator, ta, tb, events = await _core(tactical_call="CCEMA", operate_as_tactical=True)
    core.station.mycall = AX25Address.parse("CCEMA")
    assert await core.broadcast.send("CQ", "EOC net check") == ""
    sent = [f for f in ta.sent if f.utype is UType.UI]
    assert [str(f.path.source) for f in sent] == ["CCEMA", "KC1JMH-7"]
    assert sent[1].info == b"DE KC1JMH-7 (CCEMA)" and str(sent[1].path.destination) == "ID"
