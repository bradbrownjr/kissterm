"""Wait on a condition, not on the clock (docs/ROADMAP.md P0.4).

A pilot test that sleeps a fixed 0.1 s and then reads a widget passes on an
idle machine and fails when `-n auto` workers compete for the CPU, which is
how a different test failed on every parallel run. `wait_for` polls with a
bare `asyncio.sleep` (not `pilot.pause()`, which costs 100-120 ms of real
time per call -- AGENTS.md sec. 6) until the condition holds, and fails with
a message naming what never happened. The deadline only matters when the
test is going to fail anyway, so it is generous on purpose.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable


async def wait_for(
    condition: Callable[[], object],
    what: str,
    timeout: float = 10.0,
    interval: float = 0.02,
) -> None:
    """Return once `condition()` is truthy; fail naming `what` after `timeout`.

    A condition that raises (a query for a widget not mounted yet) counts as
    not yet true, which is the usual state just after a screen is pushed.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        try:
            if condition():
                return
        except Exception:  # noqa: BLE001 - not mounted yet is "not yet"
            pass
        if loop.time() >= deadline:
            raise AssertionError(f"timed out after {timeout}s waiting for {what}")
        await asyncio.sleep(interval)
