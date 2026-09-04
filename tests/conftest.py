"""Test configuration.

`asyncio_mode = "auto"` is set in pyproject so every ``async def test_`` runs
without a decorator. The event loop is function-scoped: an `AX25Link` schedules
`call_later` timers on the running loop, so sharing a loop between tests lets a
previous test's T1 fire inside the next one and produce failures that look like
state-machine bugs but are not.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
