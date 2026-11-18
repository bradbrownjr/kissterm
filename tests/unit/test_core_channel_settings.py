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


def _dm_from(source, to=NODE):
    from kissterm.ax25.frame import AX25Frame, UType
    from kissterm.ax25.address import AX25Path

    return AX25Frame.u_frame(AX25Path(destination=to, source=source), UType.DM,
                             command=False, pf=True)


@pytest.mark.asyncio
async def test_another_station_on_exactly_our_call_is_announced_once_per_interval():
    """EasyTerm left open on the modem's computer answered DM as our call
    and the node dropped every link (2026-11-18)."""
    from kissterm.core.operator import Severity

    core, operator, station, ta, tb, events = await _core()
    core.channel.on_received(_dm_from(MYCALL))
    core.channel.on_received(_dm_from(MYCALL))
    [notice] = operator.notices
    assert notice.severity is Severity.WARNING
    assert notice.text.startswith("Another station is transmitting as N1ABC-1 (heard N1ABC-1>WS1EC-15 DM")
    core.channel.own_call_notified["N1ABC-1"] -= 31 * 60
    core.channel.on_received(_dm_from(MYCALL))
    assert len(operator.notices) == 2, "the notice repeats after the interval"
    station.close()


@pytest.mark.asyncio
async def test_another_ssid_of_our_call_is_another_station():
    """The operator's own node on N1ABC-15 is not this station."""
    core, operator, station, ta, tb, events = await _core()
    core.channel.on_received(_dm_from(AX25Address.parse("N1ABC-15")))
    core.channel.on_received(_dm_from(AX25Address.parse("N1ABC")))
    await ta.dispatch(_ui(AX25Address.parse("N1ABC-15"), b"node beacon"))
    assert operator.notices == []
    station.close()


@pytest.mark.asyncio
async def test_an_alias_and_the_tactical_call_count_as_ours():
    core, operator, station, ta, tb, events = await _core()
    core.config.mycall_aliases = ["N1ABC-7"]
    core.config.tactical_call = "CCEMA"
    core.config.operate_as_tactical = True
    core.channel.on_received(_dm_from(AX25Address.parse("N1ABC-7")))
    core.channel.on_received(_dm_from(AX25Address.parse("CCEMA")))
    assert [n.text.split(" (")[0] for n in operator.notices] == [
        "Another station is transmitting as N1ABC-7",
        "Another station is transmitting as CCEMA",
    ]
    station.close()


@pytest.mark.asyncio
async def test_our_own_frame_repeated_by_a_digipeater_is_not_another_station():
    core, operator, station, ta, tb, events = await _core()
    core.gate.set(True)
    sent = aprs.beacon_frame(MYCALL, AX25Address.parse("APRS"),
                             (AX25Address.parse("WIDE1-1"),), b"=4338.75N/07042.50W-")
    await ta.send_frame(sent)
    repeated = aprs.beacon_frame(MYCALL, AX25Address.parse("APRS"),
                                 (AX25Address("WS1EC", 15, ch=True),), b"=4338.75N/07042.50W-")
    core.channel.on_received(repeated)
    assert operator.notices == []
    # The same frame long after we sent it is not an echo.
    core.channel.recent_sent.clear()
    core.channel.on_received(repeated)
    assert len(operator.notices) == 1
    station.close()
