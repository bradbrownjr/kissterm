"""T1, T2 and T3 -- the three link timers, and the sync/async bridge.

Split out of the state machine so that the transition logic reads as
transitions, and so the one genuinely tricky mechanic here -- calling an async
handler from `loop.call_later`, which is synchronous -- exists in exactly one
place instead of three.

**A timer handler must never take the app down.** `_fire` wraps every handler
so an exception is logged and swallowed. A crash in T1 during a marginal
contact would otherwise kill a terminal mid-emergency-net, which is the one
failure mode this project cannot have.

**T1 and T3 are mutually exclusive by definition.** T1 means "something is
outstanding"; T3 means "nothing is outstanding, is the link still alive?".
Both running at once is a contradiction, so `start_t1` stops T3. Forgetting
this produces spurious idle polls in the middle of an active transfer.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)

Handler = Callable[[], Awaitable[None]]


class LinkTimers:
    """Owns the three timer handles for one `AX25Link`.

    Not thread-safe, and deliberately so: `call_later` is bound to one event
    loop, and an `AX25Link` is single-threaded by contract.
    """

    def __init__(
        self,
        on_t1: Handler,
        on_t2: Handler,
        on_t3: Handler,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        label: str = "",
    ) -> None:
        self._on_t1 = on_t1
        self._on_t2 = on_t2
        self._on_t3 = on_t3
        self._loop = loop or asyncio.get_event_loop()
        self._label = label
        self._t1: asyncio.TimerHandle | None = None
        self._t2: asyncio.TimerHandle | None = None
        self._t3: asyncio.TimerHandle | None = None

    # -- T1: waiting on an acknowledgement -------------------------------
    def start_t1(self, seconds: float) -> None:
        self.stop_t1()
        self.stop_t3()  # see the module docstring
        self._t1 = self._loop.call_later(seconds, self._fire, self._on_t1, "T1")

    def stop_t1(self) -> None:
        if self._t1 is not None:
            self._t1.cancel()
            self._t1 = None

    @property
    def t1_running(self) -> bool:
        return self._t1 is not None

    # -- T2: delaying an acknowledgement so an I frame can carry it ------
    def start_t2(self, seconds: float) -> None:
        if self._t2 is not None:
            return  # already counting down toward the same ack
        self._t2 = self._loop.call_later(seconds, self._fire, self._on_t2, "T2")

    def stop_t2(self) -> None:
        if self._t2 is not None:
            self._t2.cancel()
            self._t2 = None

    # -- T3: idle-link check ---------------------------------------------
    def start_t3(self, seconds: float) -> None:
        self.stop_t3()
        if seconds > 0:
            self._t3 = self._loop.call_later(seconds, self._fire, self._on_t3, "T3")

    def stop_t3(self) -> None:
        if self._t3 is not None:
            self._t3.cancel()
            self._t3 = None

    def stop_all(self) -> None:
        self.stop_t1()
        self.stop_t2()
        self.stop_t3()

    # -- the bridge -------------------------------------------------------
    def _fire(self, handler: Handler, which: str) -> None:
        """Run an async handler from a synchronous `call_later` callback.

        The task is intentionally not retained: nothing awaits a timer, and a
        handler that raises is logged rather than surfacing as an unretrieved
        exception at interpreter shutdown.
        """

        async def _guarded() -> None:
            try:
                await handler()
            except Exception:
                log.exception("%s: %s handler failed", self._label or "link", which)

        self._loop.create_task(_guarded())
