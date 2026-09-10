"""`AX25Station.max_links` -- the incoming-call cap the tabbed terminal needs.

Without a cap, an operator who leaves `accept_incoming` on has no ceiling on
how many simultaneous live links kissterm will hold open -- and the UI now
gives each one its own tab (`kissterm/ui/terminal_pane.py`'s `MAX_TERMINAL_TABS`
matches this station-level cap so the two never disagree about how many
sessions are usable at once). A caller past the cap gets the same DM refusal
as one arriving with `accept_incoming` off -- "answer DM to traffic you do
not have", not silence, so it does not sit there retrying its N2 budget.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams  # noqa: E402
from kissterm.ax25.frame import AX25Frame, UType  # noqa: E402
from tests.loopback import LoopbackTransport  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")


def _caller(n: int) -> AX25Address:
    return AX25Address.parse(f"W1AW-{n}")


def _sabm(peer: AX25Address) -> AX25Frame:
    return AX25Frame.u_frame(AX25Path(MYCALL, peer), UType.SABM, pf=True, command=True)


@pytest.mark.asyncio
async def test_a_caller_past_the_cap_is_dmed_not_silently_dropped():
    transport = LoopbackTransport("ours")
    station = AX25Station(
        MYCALL, transport, LinkParams(t1=0.2, t2=0.05, t3=5.0), max_links=2
    )

    for n in (1, 2):
        await station._on_frame(_sabm(_caller(n)), 0)
    assert station._connected_count() == 2, "setup: both callers should have connected"

    await station._on_frame(_sabm(_caller(3)), 0)

    assert station._connected_count() == 2, "a third caller must not push past max_links"
    assert transport.sent[-1].utype is UType.DM, "the third caller must be refused, not ignored"

    station.close()


@pytest.mark.asyncio
async def test_a_slot_freed_by_disconnecting_is_usable_again():
    """The cap counts CONNECTED links, not `len(station.links)` -- a link
    stays in that dict after it disconnects (see `link_to`'s docstring), so
    counting the dict itself would make the cap a one-way ratchet."""
    transport = LoopbackTransport("ours")
    station = AX25Station(
        MYCALL, transport, LinkParams(t1=0.2, t2=0.05, t3=5.0), max_links=1
    )

    await station._on_frame(_sabm(_caller(1)), 0)
    assert station._connected_count() == 1

    link = station.link_to(_caller(1))
    assert link is not None
    await link.disconnect()
    assert station._connected_count() == 0

    await station._on_frame(_sabm(_caller(2)), 0)

    assert station._connected_count() == 1
    assert transport.sent[-1].utype is UType.UA, "the freed slot must be usable by a new caller"

    station.close()


@pytest.mark.asyncio
async def test_no_cap_by_default():
    """`max_links=None` (the default) must refuse nothing on its own --
    every existing caller of `AX25Station()` (loopback tests, `--doctor`,
    scripts) builds one with no cap and must keep behaving exactly as before.
    """
    transport = LoopbackTransport("ours")
    station = AX25Station(MYCALL, transport, LinkParams(t1=0.2, t2=0.05, t3=5.0))

    for n in range(1, 6):
        await station._on_frame(_sabm(_caller(n)), 0)

    assert station._connected_count() == 5
    assert all(f.utype is UType.UA for f in transport.sent)

    station.close()
