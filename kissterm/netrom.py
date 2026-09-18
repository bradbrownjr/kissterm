"""Read-only NET/ROM routing-broadcast decoding.

The wire layout is from *The NET/ROM Protocol*, ``Automatic Routing Table
Updates`` (pp. 8--9), available at
https://wiki.oarc.uk/_media/packet:thenetromprotocol.pdf: a broadcast is a
``0xff`` signature, a six-byte sender mnemonic, followed by fixed 21-byte
destination records (destination callsign, mnemonic, best neighbour, quality).

This deliberately does not decode NET/ROM transport traffic, calculate routes,
or establish links.  Broadcast values are untrusted on-air claims, not proof
that a destination is reachable or authenticated.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ax25.address import AX25Address, AX25AddressError
from .ax25.frame import AX25Frame, PID_NETROM, UType

_SIGNATURE = 0xFF
_MNEMONIC_SIZE = 6
_ADDRESS_SIZE = 7
_RECORD_SIZE = _ADDRESS_SIZE + _MNEMONIC_SIZE + _ADDRESS_SIZE + 1


@dataclass(frozen=True, slots=True)
class KnownNode:
    """One destination claimed by a received routing broadcast."""

    callsign: str
    alias: str
    via: str
    quality: int
    broadcaster: str


def _alias(raw: bytes) -> str | None:
    """Accept printable ASCII aliases only; they are remote display text."""
    if len(raw) != _MNEMONIC_SIZE or any(byte < 0x20 or byte > 0x7E for byte in raw):
        return None
    return raw.decode("ascii").rstrip()


def _address(raw: bytes) -> AX25Address | None:
    try:
        address, _last = AX25Address.decode(raw)
        return address
    except (AX25AddressError, ValueError):
        return None


def parse_routing_broadcast(frame: AX25Frame) -> tuple[KnownNode, ...] | None:
    """Return claimed nodes for one valid NET/ROM routing UI broadcast.

    ``None`` means the frame is not a complete broadcast.  Rejecting a whole
    malformed payload avoids presenting a partially-corrupt route as useful.
    """
    if frame.kind != "U" or frame.utype is not UType.UI or frame.pid != PID_NETROM:
        return None
    data = frame.info
    if len(data) < 1 + _MNEMONIC_SIZE or data[0] != _SIGNATURE:
        return None
    if _alias(data[1 : 1 + _MNEMONIC_SIZE]) is None:
        return None
    records = data[1 + _MNEMONIC_SIZE :]
    if not records or len(records) % _RECORD_SIZE:
        return None
    broadcaster = str(frame.path.source)
    nodes: list[KnownNode] = []
    for offset in range(0, len(records), _RECORD_SIZE):
        record = records[offset : offset + _RECORD_SIZE]
        destination = _address(record[:_ADDRESS_SIZE])
        alias = _alias(record[_ADDRESS_SIZE : _ADDRESS_SIZE + _MNEMONIC_SIZE])
        neighbour = _address(record[_ADDRESS_SIZE + _MNEMONIC_SIZE : -1])
        if destination is None or alias is None or neighbour is None:
            return None
        nodes.append(KnownNode(str(destination), alias, str(neighbour), record[-1], broadcaster))
    return tuple(nodes)


class KnownNodes:
    """Small in-memory view of received claims, keyed by destination callsign."""

    def __init__(self) -> None:
        self._nodes: dict[str, KnownNode] = {}

    def observe(self, frame: AX25Frame) -> bool:
        nodes = parse_routing_broadcast(frame)
        if nodes is None:
            return False
        self._nodes.update({node.callsign: node for node in nodes})
        return True

    def entries(self) -> tuple[KnownNode, ...]:
        return tuple(sorted(self._nodes.values(), key=lambda node: node.callsign))
