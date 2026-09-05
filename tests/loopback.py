"""A pair of frame transports wired to each other, for testing with no radio.

The entire AX.25 stack is I/O-free above `kissterm.transport`, which is what
makes this possible: two `AX25Station`s can hold a real conversation -- SABM,
I frames, acknowledgements, retransmission, DISC -- inside one event loop, with
no TNC, no serial port, and no spectrum.

`loss` and `delay` exist because a link layer that is only ever tested on a
perfect channel is not tested at all. Every recovery path in the state machine
(REJ, timer recovery, retransmission) is unreachable without dropped frames.
"""

from __future__ import annotations

import asyncio
import random

from kissterm.ax25.frame import AX25Frame
from kissterm.transport.base import FrameTransport, TransportInfo, TransportState


class LoopbackTransport(FrameTransport):
    """One end of a pair. Frames sent here are dispatched to the peer."""

    def __init__(self, name: str) -> None:
        super().__init__(TransportInfo(kind="loopback", name=name, detail="test"))
        self.peer: LoopbackTransport | None = None
        self.loss = 0.0
        self.delay = 0.0
        self.sent: list[AX25Frame] = []
        self.dropped = 0
        self._rng = random.Random(1234)
        self._tasks: set[asyncio.Task] = set()

    async def open(self) -> None:
        self.state = TransportState.OPEN

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()
        self.state = TransportState.CLOSED

    async def _send_frame(self, frame: AX25Frame, port: int = 0) -> None:
        self.sent.append(frame)
        if self.peer is None:
            return
        if self.loss and self._rng.random() < self.loss:
            self.dropped += 1
            return
        # Re-encode and re-decode rather than passing the object across. A
        # test that hands the same AX25Frame instance to both ends silently
        # skips the wire format, which is where half the real bugs live.
        raw = frame.encode()
        peer, modulo = self.peer, frame.modulo

        async def _deliver() -> None:
            if self.delay:
                await asyncio.sleep(self.delay)
            await peer.dispatch(AX25Frame.decode(raw, modulo=modulo), port)

        task = asyncio.get_event_loop().create_task(_deliver())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


def loopback_pair(a: str = "A", b: str = "B") -> tuple[LoopbackTransport, LoopbackTransport]:
    ta, tb = LoopbackTransport(a), LoopbackTransport(b)
    ta.peer, tb.peer = tb, ta
    return ta, tb
