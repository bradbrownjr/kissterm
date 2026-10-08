"""Operating as a tactical call, and identifying the licensed call after
the transmissions made under it (`identity.py`, `core/identifier.py`)."""

from __future__ import annotations

import asyncio

import pytest

from kissterm._isolate import isolate

isolate()

from kissterm import identity  # noqa: E402
from kissterm.ax25 import AX25Station, LinkParams  # noqa: E402
from kissterm.ax25.address import AX25Address, parse_path  # noqa: E402
from kissterm.ax25.frame import UType  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.core import Core  # noqa: E402
from kissterm.core import settings_schema as schema  # noqa: E402
from kissterm.core.identifier import Identifier  # noqa: E402
from kissterm.core.operator import NullOperator  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402


def test_the_air_call_is_the_tactical_call_only_when_on_and_set():
    cfg = Config(mycall="KC1JMH-7", tactical_call="CCEMA", operate_as_tactical=False)
    assert identity.air_call(cfg) == "KC1JMH-7" and not identity.tactical_active(cfg)
    cfg.operate_as_tactical = True
    assert identity.air_call(cfg) == "CCEMA" and str(identity.parse_air_call(cfg)) == "CCEMA"
    assert identity.air_call(Config(mycall="KC1JMH-7", operate_as_tactical=True)) == "KC1JMH-7"


def test_settings_accept_an_empty_tactical_call_and_refuse_one_that_cannot_be_an_address():
    spec = next(f for s in schema.SETTINGS_SCHEMA for f in s.fields if f.path == "tactical_call")
    assert schema.coerce(spec, "") == "" and schema.coerce(spec, "ccema") == "CCEMA"
    with pytest.raises(schema.ValidationError):
        schema.coerce(spec, "WSSM-ECT")
    on = Config(mycall="KC1JMH-7", operate_as_tactical=True)
    assert any("no tactical call" in p for p in schema.cross_check(on))


class Notices(NullOperator):
    def __init__(self) -> None:
        self.seen: list[str] = []

    def notice(self, notice) -> None:
        self.seen.append(notice.text)


async def _station(config, period=None):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    params = LinkParams(t1=0.2, t2=0.05, t3=5.0)
    station = AX25Station(identity.parse_air_call(config), ta, params)
    peer = AX25Station(AX25Address.parse("W1BKW"), tb, params, accept_incoming=True)
    operator = Notices()
    core = Core(config, station, operator=operator)
    if period is not None:
        core.identifier = Identifier(core, period=period)
    core.attach_station()
    core.gate.set(True)
    return core, station, peer, ta, operator


def _ids(transport):
    return [f for f in transport.sent if f.utype is UType.UI and str(f.path.destination) == "ID"]


@pytest.mark.asyncio
async def test_a_link_under_the_tactical_call_is_identified_when_it_ends():
    config = Config(mycall="KC1JMH-7", tactical_call="CCEMA", operate_as_tactical=True)
    core, station, peer, ta, operator = await _station(config)
    link = await station.connect(parse_path("W1BKW"))
    assert link is not None and link.connected
    assert str(ta.sent[0].path.source) == "CCEMA", "the connect went out as the tactical call"
    await link.disconnect()
    await asyncio.sleep(0.3)
    [frame] = _ids(ta)
    assert str(frame.path.source) == "KC1JMH-7" and frame.info == b"DE KC1JMH-7 (CCEMA)"
    assert any(t.startswith("Identified: DE KC1JMH-7") for t in operator.seen)


@pytest.mark.asyncio
async def test_no_identification_as_the_real_call_or_with_identify_off():
    for config in (Config(mycall="KC1JMH-7", tactical_call="CCEMA", operate_as_tactical=False),
                   Config(mycall="KC1JMH-7", tactical_call="CCEMA", operate_as_tactical=True,
                          tactical_id=False)):
        core, station, peer, ta, operator = await _station(config)
        link = await station.connect(parse_path("W1BKW"))
        await link.disconnect()
        await asyncio.sleep(0.3)
        assert _ids(ta) == []


@pytest.mark.asyncio
async def test_a_closed_gate_is_said_in_words_and_nothing_is_sent():
    config = Config(mycall="KC1JMH-7", tactical_call="CCEMA", operate_as_tactical=True)
    core, station, peer, ta, operator = await _station(config)
    link = await station.connect(parse_path("W1BKW"))
    core.gate.set(False)
    [theirs] = peer.links.values()
    await theirs.disconnect()  # the far end hangs up; our reply is held by the gate
    await asyncio.sleep(0.3)
    assert _ids(ta) == []
    assert any("Not identified (transmit is off)" in t and "KC1JMH-7 yourself" in t
               for t in operator.seen)


@pytest.mark.asyncio
async def test_a_long_link_is_identified_on_the_period_and_a_call_change_waits_for_the_sessions():
    config = Config(mycall="KC1JMH-7", tactical_call="CCEMA", operate_as_tactical=True)
    core, station, peer, ta, operator = await _station(config, period=0.05)
    import kissterm.core.identifier as ident
    ident.DEBOUNCE = 0.0
    link = await station.connect(parse_path("W1BKW"))
    await asyncio.sleep(0.3)
    assert len(_ids(ta)) >= 2, "identified while the link is still up"
    # Operating as the real call is wanted now, but a link is up: it waits.
    config.operate_as_tactical = False
    core.settings.apply_to_station()
    assert str(station.mycall) == "CCEMA" and core.identifier.deferred
    await link.disconnect()
    await asyncio.sleep(0.3)
    assert str(station.mycall) == "KC1JMH-7" and not core.identifier.deferred
