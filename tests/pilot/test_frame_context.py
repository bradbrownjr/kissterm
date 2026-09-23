"""Frames that arrive from a task started BEFORE the app still reach a live app.

The real launch (`kissterm/__main__.py`) opens the transport before
`app.run_async()`, so the transport's reader task -- the task every received
frame is dispatched from -- is created in a context where Textual's
`active_app` is unset. Everything a frame triggers (the station, the link's
`on_data`, the Terminal pane) inherits that context. Textual's `Timer._tick`
does a bare `active_app.get()`, so a `set_timer` armed anywhere on that chain
raised `LookupError` inside its own task and its callback never ran, with
nothing on screen to show it. That is the "TerminalPane's message queue does
not drain" report of 2026-09-22: a flush timer armed repeatedly on a real
station, zero callbacks, while direct method calls kept working.

It never reproduced under `run_test` because `run_test` yields the pilot
inside `app._context()`, so every frame a test injects already carries the
app. These tests deliver frames from a reader task started before
`run_test`, the way the real launch does.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams  # noqa: E402
from kissterm.ax25.frame import AX25Frame  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.terminal_pane import TerminalPane  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
PEER = AX25Address.parse("WS1EC-15")


async def _app_fed_by_an_outside_reader():
    """An app whose inbound frames come from a task made before the app ran.

    Outbound frames from the app's station still go straight to the peer.
    Frames from the peer are re-routed through a queue drained by `reader`,
    which is created here -- outside any app context -- exactly as a TCP or
    serial transport's read task is created by `transport.open()` in
    `__main__`.
    """
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    tb.peer = None
    inbound: asyncio.Queue = asyncio.Queue()
    tb.on_sent.append(
        lambda frame, port=0: inbound.put_nowait(AX25Frame.decode(frame.encode()))
    )

    async def reader() -> None:
        while True:
            await ta.dispatch(await inbound.get())

    reader_task = asyncio.create_task(reader())
    a = AX25Station(MYCALL, ta, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    b = AX25Station(PEER, tb, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    incoming: list = []
    b.on_incoming.append(incoming.append)
    config = Config(mycall=str(MYCALL))
    config.tx_armed_at_start = True
    return KissTermApp(config, a), a, b, incoming, reader_task


@pytest.mark.asyncio
async def test_a_pane_timer_armed_by_a_received_frame_fires():
    app, a, b, incoming, reader_task = await _app_fed_by_an_outside_reader()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        assert link is not None
        app._bind_link(link)
        await asyncio.sleep(0.1)
        far = incoming[0]

        pane = app.query_one(TerminalPane)
        fired: list[bytes] = []
        # Appended AFTER `_bind_link`, so it runs on the same chain as the
        # app's own handler: frame -> reader task -> station -> link.on_data.
        link.on_data.append(
            lambda data: pane.set_timer(0.05, lambda: fired.append(data))
        )
        await far.send(b"de WS1EC>\r")

        deadline = asyncio.get_running_loop().time() + 2.0
        while not fired and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.05)
        assert fired, (
            "a Textual timer armed from a received frame never fired -- the "
            "frame was dispatched outside the app's context"
        )
    reader_task.cancel()
    a.close()
    b.close()
