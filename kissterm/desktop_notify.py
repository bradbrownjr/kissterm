"""Bridge kissterm's own alerts to herdr's desktop notification, when present.

kissterm often runs as one pane among several under herdr
(https://herdr.dev), a terminal workspace manager -- and a pane that is not
the one currently focused is easy to miss. Textual's `App.notify` only
paints inside kissterm's own screen, so something like "W0RLI-15 has mail
waiting" is invisible if the operator is looking at a different pane, or a
different window entirely. This is exactly the gap the passive "mail
waiting" notice (docs/ROADMAP.md P9) needs closed: the whole point is that
the operator should find out *without* having kissterm focused, since the
modem only needs to be on frequency, not connected to anything.

herdr ships a CLI for exactly this, confirmed interactively against a real
herdr install during development: `herdr notification show <title>
[--body TEXT] [--position ...] [--sound none|done|request]`, which prints a
JSON result (`{"result": {"shown": true, ...}}`) on success. Detection uses
`HERDR_ENV=1`, herdr's own marker for "a herdr session is managing this
terminal" (set alongside `HERDR_PANE_ID`/`HERDR_TAB_ID`) -- checked in
addition to the binary being on PATH, so a herdr install that merely exists
on the machine, with kissterm launched outside of it, does not pop
notifications into a session herdr is not actually showing.

Every call here swallows its own failures. herdr not being installed, its
CLI shape changing in a future release, or the subprocess hanging is a
"the notification did not happen" problem, never a "kissterm crashed" one
-- same rule this codebase applies to every other background-task failure
(AGENTS.md sec. 7). `notify()` is a coroutine, not a blocking call, because
`AX25Link` schedules its own timers on the running loop (AGENTS.md sec. 3)
and a synchronous `subprocess.run` here would stall T1/T2/T3 for whatever
this waits on the external `herdr` process for.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil

log = logging.getLogger(__name__)

_HERDR_BIN = shutil.which("herdr")

#: How long to wait on the `herdr` subprocess before giving up. A hung or
#: slow-starting external binary must never be allowed to stall kissterm.
_TIMEOUT = 2.0


def herdr_present() -> bool:
    """True when this process is running under herdr and its CLI is on PATH."""
    return bool(_HERDR_BIN) and os.environ.get("HERDR_ENV") == "1"


async def notify(title: str, body: str = "", *, sound: str = "none") -> bool:
    """Best-effort desktop notification via `herdr notification show`.

    Returns whether the command actually ran -- callers use this only to
    decide whether it is worth also raising kissterm's own in-app
    notification (never instead of it: herdr may not be present at all,
    and the in-app one is the one guaranteed to be seen by an operator
    looking at kissterm itself).
    """
    if not herdr_present():
        return False
    assert _HERDR_BIN is not None
    cmd = [_HERDR_BIN, "notification", "show", title]
    if body:
        cmd += ["--body", body]
    if sound:
        cmd += ["--sound", sound]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.wait_for(proc.wait(), timeout=_TIMEOUT)
    except (OSError, asyncio.TimeoutError) as exc:
        log.debug("herdr notification failed: %s", exc)
        return False
    return proc.returncode == 0
