"""Switching the active transport mid-session carries the app's wiring with it.

`AX25Station.rebind_transport` moves only the station's own subscription.
Everything else the app attached to the first transport -- the transmit
gate, the monitor/heard/APRS subscribers, the `on_sent` fan-out -- is the
app's to move. A freshly built transport has an OPEN gate (a bare transport
has no operator to throw it; see kissterm/tx.py), so a switch that left it in
place would transmit with the operator's switch showing OFF.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

import kissterm.transport as transport_mod  # noqa: E402
from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams  # noqa: E402
from kissterm.ax25.frame import AX25Frame, UType  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.transport.base import (  # noqa: E402
    SessionTransport,
    TransportInfo,
    TransportState,
)
from tests.loopback import LoopbackTransport, loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
HEARD = AX25Address.parse("W1AW")


def _beacon(source: AX25Address) -> AX25Frame:
    path = AX25Path(AX25Address.parse("BEACON"), source)
    return AX25Frame.u_frame(path, UType.UI, info=b"hello")


@pytest.mark.asyncio
async def test_a_switched_transport_inherits_the_gate_and_the_app_subscribers(monkeypatch):
    first, _ = loopback_pair()
    await first.open()
    second = LoopbackTransport("second")
    await second.open()
    monkeypatch.setattr(transport_mod, "build_transport", lambda entry: second)

    station = AX25Station(MYCALL, first, LinkParams())
    config = Config(
        mycall=str(MYCALL),
        transports=[{"name": "second", "kind": "tcp", "host": "10.0.0.9", "port": 8001}],
    )
    app = KissTermApp(config, station)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.gate.enabled is False, "precondition: transmit starts OFF"

        assert await app._switch_frame_transport("second")
        assert station.transport is second

        # The operator's switch still reads OFF, so nothing may leave.
        await second.send_frame(_beacon(MYCALL))
        assert second.sent == [], "a switched transport transmitted with TX off"

        # The monitor and heard list follow the new transport, not the old one.
        await second.dispatch(_beacon(HEARD))
        assert app.heard.get("W1AW") is not None, "the new transport's frames never reached the app"
        assert not first._handlers, "the app is still subscribed to the old transport"
        assert not first.on_sent, "the app's on_sent is still on the old transport"
    station.close()


class _IdleSessionTransport(SessionTransport):
    """A session transport that opens and never connects."""

    def __init__(self, name: str) -> None:
        super().__init__(TransportInfo("test", name, name, "session"))

    async def open(self) -> None:
        self.state = TransportState.OPEN

    async def close(self) -> None:
        self.state = TransportState.CLOSED

    async def connect(self, path=None):  # pragma: no cover - never dialled here
        raise AssertionError("the switch must not connect")


@pytest.mark.asyncio
async def test_a_switched_session_transport_inherits_the_gate(monkeypatch):
    """Same hole on the session tier: `Session.send` checks its transport's
    own gate, so a switched-in Telnet/SSH/VARA transport must carry the
    operator's."""
    first = _IdleSessionTransport("first")
    second = _IdleSessionTransport("second")
    await first.open()
    monkeypatch.setattr(transport_mod, "build_transport", lambda entry: second)
    config = Config(
        mycall=str(MYCALL),
        transports=[{"name": "second", "kind": "telnet", "host": "10.0.0.9", "port": 23}],
    )
    app = KissTermApp(config, None, session_transport=first)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert await app._switch_session_transport("second")
        assert app.session_transport is second
        assert second.gate is app.gate, "the switched-in transport kept its own open gate"
        assert not second.gate.allow()
