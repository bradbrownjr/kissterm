"""`AX25Station.connect`'s per-link `paclen`/`window` overrides.

Roadmap P2's "configurable paclen/window per link": `LinkParams` was already
a per-link dataclass (see its docstring in `ax25/session.py`), but every
link a station opened got an identical copy of `self.params`, built once
from the global `Config.paclen`/`window`. This is the piece that lets a
single call override just one link -- the address-book-entry integration in
`kissterm/ui/app.py::action_connect` is what actually reaches this from the
UI, tested separately in `tests/pilot/test_addressbook_pane.py`.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
PEER = AX25Address.parse("W1AW-7")


def _station_pair() -> tuple[AX25Station, AX25Station]:
    ta, tb = loopback_pair()
    a = AX25Station(MYCALL, ta, LinkParams(t1=0.2, t2=0.05, t3=5.0, paclen=200, window=5))
    b = AX25Station(PEER, tb, LinkParams(t1=0.2, t2=0.05, t3=5.0))
    return a, b


@pytest.mark.asyncio
async def test_no_override_keeps_the_stations_own_params():
    a, b = _station_pair()
    link = await a.connect(AX25Path(PEER, MYCALL))
    assert link is not None and link.connected
    assert link.params.paclen == 200
    assert link.params.window == 5
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_an_override_changes_only_this_link_not_the_station_default():
    a, b = _station_pair()
    link = await a.connect(AX25Path(PEER, MYCALL), paclen=64, window=2)
    assert link is not None and link.connected
    assert link.params.paclen == 64
    assert link.params.window == 2
    # `self.params` itself must be untouched -- the next connect this
    # station makes, to anyone else, has to get the station's own defaults
    # back, not the last override left lying around.
    assert a.params.paclen == 200
    assert a.params.window == 5
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_an_override_is_still_clamped_like_any_other_link_params():
    """`LinkParams.__post_init__` caps paclen at 256 -- an override is not a
    backdoor around that clamp, it's still built via `dataclasses.replace`,
    which re-runs `__post_init__`."""
    a, b = _station_pair()
    link = await a.connect(AX25Path(PEER, MYCALL), paclen=9999, window=99)
    assert link is not None and link.connected
    assert link.params.paclen == 256
    assert link.params.window == 7
    a.close()
    b.close()
