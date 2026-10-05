"""The channel and settings in the core, with no UI.

A heard frame lands in the heard list and goes to clients raw; our own
frames reach the monitor but never the heard list; a mail-for beacon is
announced once; a settings save is all or nothing and reaches the live
station.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm import aprs  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.core import Core, Notice  # noqa: E402
from kissterm.core.events import Alert, FrameSeen  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
NODE = AX25Address.parse("WS1EC-15")


class _Operator:
    def __init__(self) -> None:
        self.notices: list[Notice] = []

    def notice(self, notice: Notice) -> None:
        self.notices.append(notice)

    async def ask(self, question):
        return None


async def _core():
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    operator = _Operator()
    station = AX25Station(MYCALL, ta, LinkParams())
    core = Core(Config(mycall=str(MYCALL), log_sessions=False), station, operator=operator)
    core.attach_station()
    events: list = []
    core.events.subscribe(lambda seq, event: events.append(event))
    return core, operator, station, ta, tb, events


def _ui(source, text: bytes):
    return aprs.beacon_frame(source, AX25Address.parse("ID"), (), text)


@pytest.mark.asyncio
async def test_heard_frames_reach_the_heard_list_and_ours_do_not():
    core, operator, station, ta, tb, events = await _core()
    await ta.dispatch(_ui(NODE, b"WS1EC node"))
    core.gate.set(True)
    await ta.send_frame(_ui(MYCALL, b"our beacon"))
    seen = [(str(e.frame.path.source), e.outgoing) for e in events if isinstance(e, FrameSeen)]
    assert seen == [(str(NODE), False), (str(MYCALL), True)]
    heard = {str(e.callsign) for e in core.heard.entries()}
    assert str(NODE) in heard and str(MYCALL) not in heard
    station.close()


@pytest.mark.asyncio
async def test_a_mail_for_beacon_is_announced_once():
    core, operator, station, ta, tb, events = await _core()
    beacon = _ui(NODE, b"Mail for: N1ABC")
    core.channel.on_received(beacon)
    core.channel.on_received(beacon)
    assert [n.text for n in operator.notices] == ["WS1EC-15 has mail waiting for N1ABC."]
    assert [e.topic for e in events if isinstance(e, Alert)] == ["mail"]
    station.close()


@pytest.mark.asyncio
async def test_a_settings_save_is_all_or_nothing_and_reaches_the_station():
    core, operator, station, ta, tb, events = await _core()
    result = core.settings.save({"paclen": "128", "window": "not a number"})
    assert result.errors and "window" in result.errors
    assert core.config.paclen != 128, "a refused save changed a value"

    result = core.settings.save({"paclen": "128"})
    assert not result.errors
    assert core.config.paclen == 128
    assert station.params.paclen == 128, "the live station did not get the new value"
    station.close()
