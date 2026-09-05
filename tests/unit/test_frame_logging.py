"""What the log and the TX fan-out have to record.

This exists because of a real operating question: a connection to a distant
node over a marginal path failed, and the operator could not tell from
anything kissterm produced whether the SABM had left the building. "No
connection" is not a diagnosis. Both directions of every frame have to be
recorded, and a suppressed frame must never look like a transmitted one.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import logging  # noqa: E402

import pytest  # noqa: E402

from kissterm.ax25.address import AX25Address, AX25Path  # noqa: E402
from kissterm.ax25.frame import AX25Frame, UType  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

PATH = AX25Path(AX25Address.parse("WS1EC-15"), AX25Address.parse("N1ABC-1"))


def _sabm() -> AX25Frame:
    return AX25Frame.u_frame(PATH, UType.SABM, pf=True, command=True)


@pytest.mark.asyncio
async def test_a_transmitted_frame_is_logged(caplog):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    with caplog.at_level(logging.DEBUG, logger="kissterm.transport.base"):
        await ta.send_frame(_sabm())
    assert any("TX" in r.message and "SABM" in r.getMessage() for r in caplog.records), (
        [r.getMessage() for r in caplog.records]
    )


@pytest.mark.asyncio
async def test_a_received_frame_is_logged(caplog):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    with caplog.at_level(logging.DEBUG, logger="kissterm.transport.base"):
        await tb.dispatch(_sabm())
    assert any("RX" in r.getMessage() for r in caplog.records), (
        [r.getMessage() for r in caplog.records]
    )


@pytest.mark.asyncio
async def test_a_gated_frame_is_logged_as_blocked_not_as_sent(caplog):
    """The one lie a transmit log must not tell."""
    ta, _ = loopback_pair()
    await ta.open()
    ta.gate.set(False)
    with caplog.at_level(logging.DEBUG, logger="kissterm.transport.base"):
        await ta.send_frame(_sabm())
    messages = [r.getMessage() for r in caplog.records]
    assert any("BLOCKED" in m for m in messages), messages
    assert not any(m.startswith("TX port") for m in messages), messages
    assert ta.sent == []


@pytest.mark.asyncio
async def test_on_sent_fires_for_a_transmitted_frame():
    ta, _ = loopback_pair()
    await ta.open()
    seen: list[tuple] = []
    ta.on_sent.append(lambda frame, port: seen.append((frame, port)))
    await ta.send_frame(_sabm(), port=1)
    assert len(seen) == 1
    assert seen[0][1] == 1


@pytest.mark.asyncio
async def test_on_sent_does_not_fire_for_a_gated_frame():
    """A monitor pane that showed frames the gate dropped would be telling the
    operator they had transmitted while TX was off."""
    ta, _ = loopback_pair()
    await ta.open()
    ta.gate.set(False)
    seen: list = []
    ta.on_sent.append(lambda frame, port: seen.append(frame))
    await ta.send_frame(_sabm())
    assert seen == []


@pytest.mark.asyncio
async def test_a_raising_on_sent_callback_does_not_break_the_link():
    """The frame is already on the air; the state machine is entitled to
    believe it was sent, whatever a pane does afterwards."""
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    good: list = []

    def boom(frame, port):
        raise RuntimeError("pane exploded")

    ta.on_sent.append(boom)
    ta.on_sent.append(lambda frame, port: good.append(frame))
    await ta.send_frame(_sabm())
    assert len(ta.sent) == 1
    assert len(good) == 1, "one bad subscriber silenced the others"
