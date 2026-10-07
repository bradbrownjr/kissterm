"""Restart kissterm in place, from the keyboard or a remote client.

Asked for by the operator (2026-10-07) for two reasons: to pick up new
code while testing away from the station, and as the remote control a
station needs when it is run from somewhere else (47 CFR 97.109; "in
case I'm doing this because of a stuck transmitter or something").

**It disconnects first; it never refuses** (operator, 2026-10-07: "I'd
have it do a disconnect before restart rather than refusing"). A restart
that waited for the operator to clear every link first would be useless
in exactly the case it exists for. The order is the shutdown order, made
safe for the radio:

1. Everything that transmits on its own stops: beacons, the APRS retry
   queue, file transfers, a mail run (`Aprs.shutdown`,
   `Transfers.shutdown`, `Mail.cancel`).
2. Every live session is ended the way Disconnect ends it
   (`Connector.disconnect`: one DISC per AX.25 link, recorded in its
   transcript; a connect still dialling is cancelled with no further
   SABMs).
3. **The DISCs are given `DISCONNECT_WAIT` seconds to be answered, then
   forced** (operator, 2026-10-07: "Add a timeout in case graceful
   disconnect won't work for some reason, and force the disconnect"): a
   link still up is closed without transmitting (`AX25Link.close`) and
   dropped from the station, so the shutdown that follows sends it
   nothing more. A peer that never answered times out on its own.
4. The front end's `on_restart` stops it as Quit would, and `__main__`
   starts the same command line again (`reexec`).
5. **A watchdog thread re-executes anyway after `SHUTDOWN_WAIT`**, in case
   the shutdown itself hangs (a transport that will not close, a stuck
   task). A hung station is the worst case for a remote operator: it can
   neither be reached nor stopped.

What it cannot do: unkey a TNC whose PTT is stuck in hardware. Closing
the serial or TCP connection is all software can do; whether that clears
the TNC is the TNC's business.

The restart is logged at WARNING (kissterm.log keeps a record of who
asked: "the keyboard" or "a remote client"), and the station comes back
as at any launch: transmit off, beacons waiting a full interval. The
pairing token is a file, so a paired phone reconnects with the key it
kept.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
import threading
import time
from collections.abc import Callable

from ..ax25.session import AX25Link
from ..transport.base import SessionState
from .operator import Notice, Severity

log = logging.getLogger(__name__)

_ON_AIR = (SessionState.CONNECTED, SessionState.TIMER_RECOVERY, SessionState.DISCONNECTING)

#: `_amain`'s return value meaning "start me again" (EX_TEMPFAIL).
RESTART_EXIT = 75
#: Seconds the DISCs get to be answered before a link is forced closed.
DISCONNECT_WAIT = 5.0
#: Seconds after the request before the watchdog re-executes regardless.
SHUTDOWN_WAIT = 15.0


def command_line() -> list[str]:
    """The command line this process was started with, as `-m kissterm`
    (works whether it was launched as `kissterm` or `python -m kissterm`)."""
    return [sys.executable, "-m", "kissterm", *sys.argv[1:]]


def reexec() -> None:
    """Replace this process with a fresh kissterm, same arguments, same
    terminal. Flushes the logs first. Does not return."""
    log.warning("Restarting: %s", " ".join(command_line()[1:]))
    logging.shutdown()
    with contextlib.suppress(Exception):
        sys.stdout.flush()
        sys.stderr.flush()
    os.execv(sys.executable, command_line())


def describe(plan: dict) -> str:
    """The confirmation's words for `Restarter.plan()`."""
    parts = []
    sessions = plan.get("sessions") or []
    if sessions:
        parts.append(f"Disconnects {', '.join(sessions)} first (forced after "
                     f"{DISCONNECT_WAIT:.0f} s without an answer).")
    unacked = int(plan.get("aprs_unacked") or 0)
    if unacked:
        parts.append(f"{unacked} APRS message{'s' if unacked != 1 else ''} still waiting "
                     "for an ack will not be resent.")
    parts.append("kissterm starts again with the same settings, transmit off; a paired "
                 "phone reconnects by itself.")
    return " ".join(parts)


class Restarter:
    """`Core.restarter`: one restart, however many times it is asked for."""

    def __init__(self, core) -> None:
        self.core = core
        #: Set once a restart is under way; `__main__` re-executes on it.
        self.requested = False
        #: The front end's stop (`KissTermApp.exit`, the headless loop's
        #: stop event), set when it starts.
        self.on_restart: Callable[[], None] | None = None
        #: Seconds, overridable by tests.
        self.disconnect_wait = DISCONNECT_WAIT
        self.shutdown_wait = SHUTDOWN_WAIT
        #: The watchdog's action; tests replace it.
        self.force = reexec
        self._watchdog: threading.Timer | None = None
        self._task: asyncio.Task | None = None

    def plan(self) -> dict:
        """What a restart would end, for the confirmation: the stations
        connected (or being dialled) and the APRS messages still waiting
        for an ack (never kept across a restart)."""
        core = self.core
        live = []
        if core.sessions is not None and core.connector is not None:
            for key, session in core.sessions.by_key.items():
                if core.connector.session_is_live(key):
                    live.append(str(getattr(session.link, "peer", "") or key or "the session"))
        return {"sessions": live, "aprs_unacked": len(core.aprs.pending)}

    def start(self, by: str) -> asyncio.Task:
        """`restart` as a task of its own: a remote command answers at once
        and is not cancelled with the server's tasks as the station stops."""
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self.restart(by))
        return self._task

    async def restart(self, by: str) -> None:
        """Stop, disconnect, and hand over to the front end to exit."""
        if self.requested:
            return
        self.requested = True
        core = self.core
        log.warning("Restart requested from %s", by)
        core.operator.notice(Notice(f"Restarting kissterm (asked from {by}).",
                                    Severity.WARNING))
        self._start_watchdog()
        core.aprs.shutdown()
        core.transfers.shutdown()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(core.mail.cancel(), self.disconnect_wait)
        await self._disconnect_all()
        if self.on_restart is not None:
            self.on_restart()

    async def _disconnect_all(self) -> None:
        core = self.core
        if core.sessions is None or core.connector is None:
            return
        live = [key for key in list(core.sessions.by_key)
                if core.connector.session_is_live(key)]
        for key in live:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(core.connector.disconnect(key), self.disconnect_wait)
        deadline = time.monotonic() + self.disconnect_wait
        while time.monotonic() < deadline and self._still_up():
            await asyncio.sleep(0.1)
        for link in self._still_up():
            peer = getattr(link, "peer", "?")
            log.warning("Restart: no answer to DISC from %s in %.0f s; closing the link "
                        "without it", peer, self.disconnect_wait)
            link.close(reason="restart: disconnect not answered")
            if core.station is not None:
                core.station.drop(link)

    def _still_up(self) -> list:
        """AX.25 links still connected or waiting for the UA to their DISC
        (a link in DISCONNECTING is not `connected`, but it is still on the
        air: T1 resends the DISC until N2)."""
        return [s.link for s in self.core.sessions.by_key.values()
                if isinstance(s.link, AX25Link) and s.link.state in _ON_AIR]

    def _start_watchdog(self) -> None:
        def fire() -> None:
            log.warning("Restart: shutdown did not finish in %.0f s; restarting anyway",
                        self.shutdown_wait)
            self.force()

        self._watchdog = threading.Timer(self.shutdown_wait, fire)
        self._watchdog.daemon = True
        self._watchdog.start()

    def cancel_watchdog(self) -> None:
        """For tests: a restart that is not followed by an exec."""
        if self._watchdog is not None:
            self._watchdog.cancel()
