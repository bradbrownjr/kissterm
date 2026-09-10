"""`kissterm.aprs_notify` -- pure decision logic, no app, no I/O."""

from __future__ import annotations

from kissterm.ax25.address import AX25Address, AX25Path
from kissterm.aprs.types import AprsPacket, Message, Position
from kissterm.aprs_notify import Cooldown, evaluate_packet


def _packet(kind: str, data, addressee_source: str = "K1ABC-9") -> AprsPacket:
    source = AX25Address.parse(addressee_source)
    dest = AX25Address.parse("APRS")
    return AprsPacket(
        source=source,
        destination=dest,
        path=AX25Path(destination=dest, source=source, repeaters=()),
        info=b"",
        kind=kind,
        data=data,
    )


def test_a_message_addressed_to_me_is_worth_notifying():
    msg = Message(addressee="W1AW", text="hello there")
    packet = _packet("message", msg)
    decision = evaluate_packet(packet, "W1AW", [])
    assert decision is not None
    assert decision.body == "hello there"
    assert decision.urgent is False


def test_addressing_ignores_ssid_like_mail_waiting_for():
    msg = Message(addressee="W1AW-9", text="hi")
    packet = _packet("message", msg)
    assert evaluate_packet(packet, "W1AW", []) is not None


def test_a_message_to_someone_else_is_not_worth_notifying():
    msg = Message(addressee="K1XYZ", text="hi")
    packet = _packet("message", msg)
    assert evaluate_packet(packet, "W1AW", []) is None


def test_an_ack_is_never_worth_notifying():
    msg = Message(addressee="W1AW", text="", number="5", is_ack=True)
    packet = _packet("message", msg)
    assert evaluate_packet(packet, "W1AW", []) is None


def test_a_reject_is_never_worth_notifying():
    msg = Message(addressee="W1AW", text="", number="5", is_rej=True)
    packet = _packet("message", msg)
    assert evaluate_packet(packet, "W1AW", []) is None


def test_a_telemetry_definition_is_never_worth_notifying():
    # Addressed to itself, matching how a telemetry station really sends
    # one -- included even though that address would otherwise match.
    msg = Message(addressee="W1AW", text="PARM.Vin,Rx1h", is_telemetry_definition=True)
    packet = _packet("message", msg)
    assert evaluate_packet(packet, "W1AW", []) is None


def test_an_emergency_mic_e_flag_is_urgent():
    pos = Position(
        latitude=44.0, longitude=-70.0, symbol_table="/", symbol_code=">",
        mic_e_message="Emergency", comment="test",
    )
    packet = _packet("mic-e", pos)
    decision = evaluate_packet(packet, "W1AW", [])
    assert decision is not None
    assert decision.urgent is True
    assert "EMERGENCY" in decision.title


def test_a_non_emergency_mic_e_message_is_not_worth_notifying():
    pos = Position(
        latitude=44.0, longitude=-70.0, symbol_table="/", symbol_code=">",
        mic_e_message="Off Duty",
    )
    packet = _packet("mic-e", pos)
    assert evaluate_packet(packet, "W1AW", []) is None


def test_an_ordinary_position_is_not_worth_notifying():
    pos = Position(latitude=44.0, longitude=-70.0, symbol_table="/", symbol_code=">")
    packet = _packet("position", pos)
    assert evaluate_packet(packet, "W1AW", []) is None


def test_cooldown_suppresses_a_repeat_within_the_window():
    cd = Cooldown(window_seconds=60.0)
    key = ("K1ABC", "message")
    assert cd.allow(key, now=0.0) is True
    assert cd.allow(key, now=10.0) is False
    assert cd.allow(key, now=61.0) is True


def test_cooldown_never_suppresses_an_urgent_notification():
    cd = Cooldown(window_seconds=60.0)
    key = ("K1ABC", "emergency")
    assert cd.allow(key, urgent=True, now=0.0) is True
    assert cd.allow(key, urgent=True, now=1.0) is True
