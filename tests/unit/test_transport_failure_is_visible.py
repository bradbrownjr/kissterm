"""A dead TNC socket must never read as a dead RF path.

Every test here comes from one real on-air attempt. The log said:

    18:05:33 TX port 0: KC1JMH>WS1EC-15 SABM P cmd
    18:05:36 TX port 0: KC1JMH>WS1EC-15 SABM P cmd
    18:05:39 TX port 0: KC1JMH>WS1EC-15 SABM P cmd
    18:05:42 TX port 0: KC1JMH>WS1EC-15 SABM P cmd
    18:05:42 ERROR ... TransportError: tcp transport to 10.6.26.5:8001 is not connected

Four transmissions logged, the fourth of which never left the process, and
not one line saying the connection to the TNC had gone away. The operator saw
"no answer from WS1EC-15" and had every reason to blame the antenna.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import logging  # noqa: E402

import pytest  # noqa: E402

from kissterm.ax25 import AX25Address, AX25Path  # noqa: E402
from kissterm.ax25.frame import AX25Frame, UType  # noqa: E402
from kissterm.transport.base import FrameTransport, TransportError, TransportInfo  # noqa: E402


def _sabm() -> AX25Frame:
    path = AX25Path(AX25Address.parse("WS1EC-15"), AX25Address.parse("KC1JMH"))
    return AX25Frame.u_frame(path, UType.SABM, pf=True, command=True)


class _DeadTransport(FrameTransport):
    """A transport whose socket has gone away, like the real one had."""

    def __init__(self) -> None:
        super().__init__(TransportInfo(kind="tcp", name="dead", detail="10.6.26.5:8001"))
        self.attempts = 0

    async def open(self) -> None:  # pragma: no cover - not exercised
        pass

    async def close(self) -> None:  # pragma: no cover - not exercised
        pass

    async def _send_frame(self, frame, port: int = 0) -> None:
        self.attempts += 1
        raise TransportError("tcp transport to 10.6.26.5:8001 is not connected")


@pytest.mark.asyncio
async def test_a_frame_the_transport_refused_is_not_logged_as_transmitted(caplog):
    """The original bug, exactly: "TX port 0" was written before the send was
    attempted, so a frame that never left the process appeared in the log as
    one that went on the air."""
    transport = _DeadTransport()
    with caplog.at_level(logging.DEBUG, logger="kissterm.transport.base"):
        with pytest.raises(TransportError):
            await transport.send_frame(_sabm())

    messages = [r.getMessage() for r in caplog.records]
    sent = [m for m in messages if m.startswith("TX port")]
    assert sent == [], f"a refused frame was logged as transmitted: {sent}"


@pytest.mark.asyncio
async def test_the_refusal_itself_is_logged_with_the_reason(caplog):
    """Silence would be no better than the lie. The line has to name the
    frame and why it did not go, because that reason ("not connected") is the
    whole diagnosis."""
    transport = _DeadTransport()
    with caplog.at_level(logging.DEBUG, logger="kissterm.transport.base"):
        with pytest.raises(TransportError):
            await transport.send_frame(_sabm())

    failures = [r.getMessage() for r in caplog.records if "TX FAILED" in r.getMessage()]
    assert len(failures) == 1, caplog.text
    assert "SABM" in failures[0]
    assert "not connected" in failures[0]


@pytest.mark.asyncio
async def test_a_refused_frame_never_reaches_the_monitor(caplog):
    """`on_sent` feeds the monitor pane. A frame the transport refused must
    not appear there either -- the monitor is the operator's evidence of what
    was actually on the air."""
    transport = _DeadTransport()
    seen: list[AX25Frame] = []
    transport.on_sent.append(lambda frame, port: seen.append(frame))

    with pytest.raises(TransportError):
        await transport.send_frame(_sabm())

    assert seen == [], "a frame that was never sent was announced as sent"


@pytest.mark.asyncio
async def test_the_exception_still_propagates(caplog):
    """Logging it does not mean swallowing it. `AX25Link` needs the failure
    to reach its own error path; a send that quietly does nothing would put
    the state machine back where it started -- believing the frame went."""
    transport = _DeadTransport()
    with pytest.raises(TransportError, match="not connected"):
        await transport.send_frame(_sabm())
    assert transport.attempts == 1
