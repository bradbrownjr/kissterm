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

# Isolate before ANY test file is imported. Each test file also calls
# `isolate()` first, but a run that loads a file which does not (many unit
# files import kissterm directly) ahead of a pilot test in the same worker
# fixed `kissterm.config`'s paths on the operator's real directories -- and a
# pilot test that saves a callsign then overwrote their real config.toml.
# That happened on 2026-09-23 (`pytest tests/unit/test_commands.py
# tests/pilot/...`). This conftest is loaded before every test module in
# every xdist worker, so isolating here covers every ordering.
from kissterm._isolate import isolate, isolated_base  # noqa: E402

isolate()


def pytest_configure(config):
    """Refuse to run at all if kissterm's paths are not the scratch tree."""
    import pytest

    from kissterm import config as kconfig

    base = isolated_base()
    for name in ("_CONFIG_DIR", "_STATE_DIR", "_DATA_DIR"):
        path = getattr(kconfig, name)
        if base is None or base not in path.parents:
            pytest.exit(f"kissterm.config.{name} is {path}, not under the test scratch "
                        f"tree {base}; refusing to run and touch real files.", returncode=3)
