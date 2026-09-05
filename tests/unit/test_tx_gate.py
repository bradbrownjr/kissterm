"""The gate is a safety interlock, so the tests are about what it stops.

The one property that matters: with the gate closed, no code path -- pane,
timer, state machine, background task, or a future backend nobody has written
yet -- can put a byte on the air. That is enforced by `send_frame` being
concrete in `FrameTransport`, so these tests check the choke point itself
rather than trusting each backend to remember.
"""

from __future__ import annotations

import asyncio

from kissterm import _isolate

_isolate.isolate()

import inspect  # noqa: E402
import pytest  # noqa: E402

from kissterm.ax25.address import AX25Address, AX25Path  # noqa: E402
from kissterm.ax25.frame import AX25Frame, UType  # noqa: E402
from kissterm.ax25.station import AX25Station  # noqa: E402
from kissterm.transport import base as transport_base  # noqa: E402
from kissterm.tx import TransmitGate  # noqa: E402

from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
PEER = AX25Address.parse("WS1EC-7")


def _ui_frame() -> AX25Frame:
    return AX25Frame.u_frame(AX25Path(PEER, MYCALL), UType.UI, command=False, info=b"hi")


# ---------------------------------------------------------------------------
# The switch itself
# ---------------------------------------------------------------------------


def test_a_gate_is_closed_unless_asked_otherwise():
    assert TransmitGate().enabled is False


def test_toggle_and_set_report_the_new_state():
    gate = TransmitGate()
    assert gate.toggle() is True
    assert gate.set(True) is True  # idempotent
    assert gate.toggle() is False


def test_blocked_transmissions_are_counted_and_reset_on_open():
    """The count answers "what did this closed gate stop?" -- a lifetime
    total would say nothing about the state the operator is in now."""
    gate = TransmitGate()
    for _ in range(3):
        assert gate.allow() is False
    assert gate.blocked == 3
    gate.set(True)
    assert gate.blocked == 0
    assert gate.allow() is True
    assert gate.blocked == 0


def test_listeners_fire_only_on_an_actual_change():
    gate = TransmitGate()
    seen: list[bool] = []
    gate.on_change.append(seen.append)
    gate.set(True)
    gate.set(True)
    gate.set(False)
    assert seen == [True, False]


def test_a_throwing_listener_cannot_jam_the_switch():
    """Whatever else breaks, the operator's TX switch has to keep working."""
    gate = TransmitGate()

    def boom(_enabled):
        raise RuntimeError("listener is broken")

    gate.on_change.append(boom)
    assert gate.set(True) is True
    assert gate.enabled is True


# ---------------------------------------------------------------------------
# The choke point
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_closed_gate_stops_a_frame_at_the_transport():
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    seen: list[AX25Frame] = []
    tb.subscribe(lambda f, port=0: seen.append(f))

    ta.gate = TransmitGate(enabled=False)
    await ta.send_frame(_ui_frame())
    await asyncio.sleep(0.05)
    assert ta.sent == [] and seen == []
    assert ta.gate.blocked == 1

    ta.gate.set(True)
    await ta.send_frame(_ui_frame())
    await asyncio.sleep(0.05)
    assert len(ta.sent) == 1 and len(seen) == 1


@pytest.mark.asyncio
async def test_a_closed_gate_stops_the_ax25_state_machine_too():
    """Not a special case for beacons: connecting is a transmission."""
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    ta.gate = TransmitGate(enabled=False)
    station = AX25Station(MYCALL, ta)
    link = await station.connect(AX25Path(PEER, MYCALL), timeout=0.4)
    assert link is None or not link.connected
    assert ta.sent == [], "a SABM escaped a closed gate"
    assert ta.gate.blocked >= 1
    station.close()


@pytest.mark.asyncio
async def test_blocking_never_raises_into_a_background_task():
    """AX.25 retransmission runs on timer callbacks with nowhere for an
    exception to go -- the house rule is that a background task never dies of
    one. So a blocked send returns normally."""
    ta, _ = loopback_pair()
    await ta.open()
    ta.gate = TransmitGate(enabled=False)
    assert await ta.send_frame(_ui_frame()) is None


def test_send_frame_is_concrete_and_subclasses_implement_the_private_one():
    """The gate check is only a guarantee if a new backend cannot skip it.

    `FrameTransport.send_frame` is concrete and calls the abstract
    `_send_frame`, so a backend that overrides the public name would be
    routing around the interlock. This test is the thing that notices.
    """
    assert not getattr(
        transport_base.FrameTransport.send_frame, "__isabstractmethod__", False
    )
    assert getattr(
        transport_base.FrameTransport._send_frame, "__isabstractmethod__", False
    )
    source = inspect.getsource(transport_base.FrameTransport.send_frame)
    assert "self.gate.allow()" in source

    from kissterm.transport import agwpe, bluetooth, serial_kiss, tcp_kiss

    for module in (agwpe, bluetooth, serial_kiss, tcp_kiss):
        for name, obj in vars(module).items():
            if not (isinstance(obj, type) and issubclass(obj, transport_base.FrameTransport)):
                continue
            if obj is transport_base.FrameTransport:
                continue  # the base class is imported into each module
            assert "send_frame" not in obj.__dict__, (
                f"{module.__name__}.{name} overrides send_frame, which bypasses "
                f"the transmit gate -- implement _send_frame instead"
            )


@pytest.mark.asyncio
async def test_the_session_tier_is_gated_as_well():
    """A VARA or Mercury link never produces an AX25Frame, so gating only the
    frame tier would leave every HF modem ungated."""
    ta, _ = loopback_pair()
    await ta.open()
    ta.gate = TransmitGate(enabled=False)
    sent: list[bytes] = []

    session = transport_base.Session(path=AX25Path(PEER, MYCALL), transport=ta)
    session._sender = lambda data: asyncio.sleep(0, result=sent.append(data))

    await session.send(b"hello")
    assert sent == []
    ta.gate.set(True)
    await session.send(b"hello")
    assert sent == [b"hello"]
