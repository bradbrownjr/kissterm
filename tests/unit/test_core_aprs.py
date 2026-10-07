"""APRS in the core, with no UI: what a remote client will rely on.

A message to this station is recorded, announced as an event and acked
under the station's own identity; a closed gate drops the ack and says so
once; a typed message arms the gate and is tracked until acked; a retry is
unattended and never arms anything.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm import aprs  # noqa: E402
from kissterm.aprs_conversations import PendingAcks  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.core import Core, Notice  # noqa: E402
from kissterm.core.events import AprsAcked, AprsMessage, AprsRetried  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
PEER = AX25Address.parse("W1AW-9")


class _Operator:
    def __init__(self) -> None:
        self.notices: list[Notice] = []

    def notice(self, notice: Notice) -> None:
        self.notices.append(notice)

    async def ask(self, question):
        return None


class _View:
    def active_key(self) -> str:
        return ""

    def has_room_for(self, key) -> bool:
        return True

    def open_session(self, key, *, kind, focus) -> None:
        pass

    def is_active(self, key) -> bool:
        return True

    def focus_input(self) -> None:
        pass


async def _core():
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    operator = _Operator()
    station = AX25Station(MYCALL, ta, LinkParams())
    core = Core(Config(mycall=str(MYCALL), log_sessions=False), station, operator=operator)
    core.attach_view(_View())
    core.attach_station()
    core.aprs.conversations.clear_all()
    events: list = []
    core.events.subscribe(lambda seq, event: events.append(event))
    return core, operator, station, ta, events


def _from_peer(payload: bytes):
    return aprs.beacon_frame(PEER, AX25Address.parse("APRS"), (), payload)


@pytest.mark.asyncio
async def test_a_message_to_me_is_recorded_announced_and_acked():
    core, operator, station, ta, events = await _core()
    core.gate.set(True)
    await core.aprs.on_frame(_from_peer(aprs.message(str(MYCALL), "hello", number="12")))
    assert AprsMessage(str(PEER), True) in events
    convo = core.aprs.conversations.conversations[str(PEER)]
    assert [m.text for m in convo.messages] == ["hello"]
    [ack] = ta.sent
    assert str(ack.path.source) == str(MYCALL)
    packet = aprs.parse_packet(ack)
    assert packet.data.is_ack and packet.data.number == "12"
    station.close()


@pytest.mark.asyncio
async def test_a_closed_gate_drops_the_ack_and_says_so_once():
    core, operator, station, ta, events = await _core()
    frame = _from_peer(aprs.message(str(MYCALL), "hello", number="12"))
    await core.aprs.on_frame(frame)
    await core.aprs.on_frame(frame)  # the sender's retry
    assert ta.sent == []
    assert core.gate.enabled is False
    warned = [n for n in operator.notices if "needs an acknowledgment" in n.text]
    assert len(warned) == 1
    # A duplicate is shown once.
    assert len(core.aprs.conversations.conversations[str(PEER)].messages) == 1
    station.close()


@pytest.mark.asyncio
async def test_a_typed_message_arms_and_is_tracked_until_acked():
    core, operator, station, ta, events = await _core()
    assert await core.aprs.compose(str(PEER), "on my way") == "sent"
    assert core.gate.enabled is True, "a typed, addressed message arms the gate"
    [sent] = ta.sent
    number = aprs.parse_packet(sent).data.number
    assert core.aprs.pending.attempts_for(str(PEER), number) is not None

    await core.aprs.on_frame(_from_peer(aprs.ack(str(MYCALL), number)))
    assert AprsAcked(str(PEER), number) in events
    await core.aprs.check_retries()
    assert core.aprs.pending.due(now=1e12) == []
    assert AprsRetried() in events
    station.close()


@pytest.mark.asyncio
async def test_a_retry_with_the_gate_closed_sends_nothing_and_arms_nothing():
    core, operator, station, ta, events = await _core()
    core.aprs.pending = PendingAcks(retry_seconds=0, max_retries=3)
    core.aprs.pending.add(str(PEER), "7", "are you there")
    await core.aprs.check_retries()
    assert ta.sent == []
    assert core.gate.enabled is False
    station.close()


@pytest.mark.asyncio
async def test_templates_are_the_gateway_service_and_the_saved_messages_and_send_nothing():
    core, operator, station, ta, events = await _core()
    core.gate.set(True)
    found = core.aprs.templates("wlnk-1")
    assert found["service"]["id"] == "winlink" and found["service"]["commands"]
    assert {"name", "summary", "text", "confidence"} <= set(found["service"]["commands"][0])
    assert core.aprs.templates("W1AW-9")["service"] is None
    assert ta.sent == []
    station.close()


@pytest.mark.asyncio
async def test_saved_messages_are_scoped_validated_replaced_and_forgotten():
    core, operator, station, ta, events = await _core()
    assert core.aprs.template_save("", "x") and core.aprs.template_save("n", " ")
    assert core.aprs.template_save("Check in", "QRV 146.52") == []
    assert core.aprs.template_save("List", "L", "winlink") == []
    assert [m["name"] for m in core.aprs.templates("W1AW-9")["saved"]] == ["Check in"]
    assert [m["name"] for m in core.aprs.templates("WLNK-1")["saved"]] == ["List", "Check in"]
    old = {"name": "Check in", "text": "QRV 146.52", "gateway": ""}
    assert core.aprs.template_save("Check in", "QRV 147.09", "", old) == []
    assert core.aprs.templates("W1AW-9")["saved"][0]["text"] == "QRV 147.09"
    assert core.aprs.template_forget("List", "L", "winlink")
    assert not core.aprs.template_forget("List", "L", "winlink")
    assert len(core.config.aprs_templates) == 1
    station.close()


def test_an_objects_place_can_be_a_grid_square_mgrs_or_utm():
    from kissterm.core.aprs import place_from
    from kissterm.locator import from_utm

    lat, lon = place_from("grid", "FN31pr")
    assert 41 < lat < 42 and -73 < lon < -72
    assert place_from("mgrs", "18T WL 85664 11348") == pytest.approx((40.7486, -73.9853), abs=0.001)
    assert place_from("utm", "18 N 691875 4576931") == from_utm("18 N 691875 4576931")
    for mode in ("grid", "mgrs", "utm"):
        with pytest.raises(ValueError, match="Enter"):
            place_from(mode, "nonsense")
    with pytest.raises(ValueError):
        place_from("decimal", "43 -70")
