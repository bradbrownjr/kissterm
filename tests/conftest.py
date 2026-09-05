"""Test configuration.

**Every `async def test_` needs an explicit `@pytest.mark.asyncio`.** There is
no `asyncio_mode = "auto"` configured -- an earlier version of this docstring
claimed there was, and the symptom of believing it is a whole file reporting
"async def functions are not natively supported", which reads like a missing
dependency rather than a missing decorator.

The event loop is function-scoped: an `AX25Link` schedules `call_later` timers
on the running loop, so sharing a loop between tests lets a previous test's T1
fire inside the next one and produce failures that look like state-machine bugs
but are not.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
