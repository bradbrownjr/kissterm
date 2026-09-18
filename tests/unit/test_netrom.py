"""NET/ROM routing broadcasts are passive, strict, and never a send path."""

from kissterm.ax25 import AX25Address, AX25Path
from kissterm.ax25.frame import AX25Frame, PID_NETROM, UType
from kissterm.netrom import KnownNodes, parse_routing_broadcast


def _address(text: str) -> bytes:
    return AX25Address.parse(text).encode()


def _frame(info: bytes) -> AX25Frame:
    return AX25Frame.u_frame(
        AX25Path(AX25Address.parse("NODES"), AX25Address.parse("N1ABC")),
        UType.UI,
        pid=PID_NETROM,
        info=info,
    )


def test_routing_broadcast_decodes_fixed_destination_record():
    frame = _frame(b"\xffSOURCE" + _address("W1AW-1") + b"ARRL  " + _address("N1ABC") + bytes([200]))
    nodes = parse_routing_broadcast(frame)
    assert nodes is not None
    assert nodes[0].callsign == "W1AW-1"
    assert nodes[0].alias == "ARRL"
    assert nodes[0].via == "N1ABC"
    assert nodes[0].quality == 200
    assert nodes[0].broadcaster == "N1ABC"


def test_routing_broadcast_rejects_bad_signature_truncation_and_non_ui():
    valid = b"\xffSOURCE" + _address("W1AW") + b"ARRL  " + _address("N1ABC") + bytes([1])
    assert parse_routing_broadcast(_frame(valid[:-1])) is None
    assert parse_routing_broadcast(_frame(b"\x00" + valid[1:])) is None
    wrong = AX25Frame.i_frame(
        AX25Path(AX25Address.parse("NODES"), AX25Address.parse("N1ABC")), 0, 0, valid, pid=PID_NETROM
    )
    assert parse_routing_broadcast(wrong) is None


def test_known_nodes_keeps_only_valid_passive_observations():
    known = KnownNodes()
    assert not known.observe(_frame(b"\xffSOURCE"))
    assert known.entries() == ()
    valid = b"\xffSOURCE" + _address("W1AW") + b"ARRL  " + _address("N1ABC") + bytes([1])
    assert known.observe(_frame(valid))
    assert [node.callsign for node in known.entries()] == ["W1AW"]
