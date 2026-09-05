"""`AX25Station.rebind_transport` -- swapping the TNC underneath a station.

Exists for the Settings pane: picking a different configured transport and
hitting Save used to change `Config.active_transport` and nothing else. The
station kept talking to the OLD transport object, so the status bar kept
reporting the old TNC no matter how many times the operator saved. This is
the half that actually reopens the connection.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams  # noqa: E402
from tests.loopback import LoopbackTransport, loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
PEER = AX25Address.parse("W1AW-7")


def _station() -> tuple[AX25Station, LoopbackTransport]:
    ta, _tb = loopback_pair()
    return AX25Station(MYCALL, ta, LinkParams(t1=0.2, t2=0.05, t3=5.0)), ta


def test_rebind_replaces_the_transport_and_returns_the_old_one():
    station, old = _station()
    new = LoopbackTransport("new")

    returned = station.rebind_transport(new)

    assert returned is old
    assert station.transport is new


def test_rebind_moves_the_frame_subscription_too():
    """Not just the attribute -- frames must actually route through the new
    transport afterwards, or the station looks rebound but is still deaf."""
    station, old = _station()
    new = LoopbackTransport("new")

    station.rebind_transport(new)

    assert len(old._handlers) == 0, "the old transport still calls into the station"
    assert len(new._handlers) == 1, "the station never subscribed to the new transport"


@pytest.mark.asyncio
async def test_rebind_refuses_while_a_link_is_connected():
    """Swapping the wire underneath a live conversation would silently
    misroute its frames onto unrelated hardware -- Settings already tells the
    operator to disconnect first; this is the guarantee behind that
    instruction, not just the wording of it."""
    ta, tb = loopback_pair()
    tb_station = AX25Station(PEER, tb, LinkParams(t1=0.1, t2=0.05, t3=5.0))
    station = AX25Station(MYCALL, ta, LinkParams(t1=0.1, t2=0.05, t3=5.0))

    link = await station.connect(AX25Path(PEER, MYCALL))
    assert link is not None and link.connected, "setup: the loopback link did not come up"

    with pytest.raises(RuntimeError):
        station.rebind_transport(LoopbackTransport("new"))

    assert station.transport is ta, "the transport changed despite the refusal"

    station.close()
    tb_station.close()


def test_rebind_succeeds_once_nothing_is_connected():
    station, old = _station()
    # A link object can exist without being connected -- a failed attempt
    # left behind, say -- and must not itself block a rebind.
    station.links[("W1AW", 7, 0)] = type("Stub", (), {"connected": False})()
    new = LoopbackTransport("new")

    station.rebind_transport(new)

    assert station.transport is new
