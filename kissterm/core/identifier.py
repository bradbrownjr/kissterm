"""Identifying the licensed callsign while operating as a tactical call.

Operating as `CCEMA` puts `CCEMA` in the source address of every frame
(`kissterm/identity.py`), so the station's own callsign is not on the air at
all. The operator said what is wanted (2026-10-08): the call goes out
automatically after an on-air transmission, as Winlink does when a VARA
session ends, and sessions are nearly always well under ten minutes. So:

- **When a link made under the tactical call ends** (disconnected, failed,
  or never came up: SABMs were sent either way) one UI frame goes to `ID`
  from the real call, `DE <real call> (CCEMA)`.
- **Every 10 minutes while such a link stays up**, the same frame, so a long
  session is identified on the schedule too.
- Nothing else. It never fires at startup, never when not operating as
  tactical, never without a transmission to follow.

This is an unattended transmission, so it follows AGENTS.md: it is switched
by the operator (operating as tactical, and `Config.tactical_id`), it goes
through `send_frame` (the gate; a closed gate drops it and the operator is
told in words that they must identify themselves), the Monitor shows it,
and it is re-checked at the moment of sending. The legal schedule is the
operator's responsibility (ROADMAP P9's note: this file is not an
authority on the rules).

Changing identity while a link is up would leave the peer answering the
old call (`Core.ask_callsign` refuses for the same reason), so
`Settings.apply_to_station` defers it to `apply_pending` here, called when
the last link ends.
"""

from __future__ import annotations

import asyncio
import logging
import time

from .. import identity
from ..ax25.address import AX25Address, AX25AddressError, AX25Path
from ..ax25.frame import AX25Frame, UType
from ..transport.base import SessionState
from .operator import Notice, Severity

log = logging.getLogger(__name__)

#: The longest a link made under the tactical call stays up unidentified.
PERIOD = 600.0
#: Two links ending together are one identification.
DEBOUNCE = 20.0
#: The UI frame's destination: the conventional "ID" address.
DESTINATION = "ID"
#: States in which the link is over.
_ENDED = (SessionState.DISCONNECTED, SessionState.FAILED)


class Identifier:
    def __init__(self, core, period: float = PERIOD) -> None:
        self.core = core
        self.period = period
        self.sent = 0
        self._last = 0.0
        self._timers: dict[int, asyncio.Task] = {}
        #: The identity setting changed while a link was up.
        self.deferred = False

    # -- watching links ---------------------------------------------------
    def watch(self, link) -> None:
        """Called for every link as it is made. Only a link made while
        operating as the tactical call is watched: the others transmit
        under the real call, which is its own identification."""
        if not (identity.tactical_active(self.core.config) and self.core.config.tactical_id):
            return
        link.on_state.append(lambda state, link=link: self._state(link, state))

    def _state(self, link, state: SessionState) -> None:
        key = id(link)
        if state is SessionState.CONNECTED and key not in self._timers:
            self._timers[key] = asyncio.get_event_loop().create_task(
                self._periodic(link), name="kissterm-identify")
        elif state in _ENDED:
            timer = self._timers.pop(key, None)
            if timer is not None:
                timer.cancel()
            asyncio.get_event_loop().create_task(self._after(link), name="kissterm-identify")

    async def _periodic(self, link) -> None:
        try:
            while True:
                await asyncio.sleep(self.period)
                if link.state is SessionState.CONNECTED:
                    await self.send(reason="while the link is up")
        except asyncio.CancelledError:
            pass

    async def _after(self, link) -> None:
        await self.send(reason="after the link ended")
        self.apply_pending()

    # -- the identification -----------------------------------------------
    def text(self) -> str:
        config = self.core.config
        return f"DE {config.mycall} ({config.tactical_call})"

    def problem(self) -> str:
        """Why an identification cannot go out now, or ""."""
        config = self.core.config
        if self.core.station is None:
            return "there is no radio transport"
        if not (identity.tactical_active(config) and config.tactical_id):
            return "not operating as the tactical call"
        gate = getattr(self.core.station.transport, "gate", None)
        if gate is not None and not gate.enabled:
            return "transmit is off"
        return ""

    def frame(self) -> AX25Frame | None:
        config = self.core.config
        try:
            path = AX25Path(AX25Address.parse(DESTINATION), AX25Address.parse(config.mycall), ())
        except (AX25AddressError, ValueError):
            return None
        return AX25Frame.u_frame(path, UType.UI, command=False, info=self.text().encode("ascii"))

    async def send(self, reason: str = "") -> bool:
        """One identification now, if one can go; says so either way."""
        if time.monotonic() - self._last < DEBOUNCE and self._last:
            return False
        why = self.problem()
        if why == "not operating as the tactical call":
            return False  # the setting was turned off since: nothing to identify
        frame = self.frame()
        if why or frame is None:
            self._notice(
                f"Not identified ({why or 'bad callsign'}): identify as "
                f"{self.core.config.mycall} yourself.", Severity.WARNING)
            return False
        try:
            await self.core.station.transport.send_frame(frame, 0)
        except Exception as exc:  # a transport can fail at any moment
            log.warning("identification not sent: %s", exc)
            self._notice(f"Not identified ({exc}): identify as "
                         f"{self.core.config.mycall} yourself.", Severity.WARNING)
            return False
        self._last = time.monotonic()
        self.sent += 1
        self._notice(f"Identified: {self.text()} {reason}".rstrip())
        return True

    # -- changing identity --------------------------------------------------
    def sessions_up(self) -> bool:
        station = self.core.station
        return station is not None and any(
            link.state not in _ENDED and link.state is not SessionState.DISCONNECTING
            for link in station.links.values())

    def defer(self) -> None:
        """The identity setting changed while links were up."""
        self.deferred = True
        self._notice("The tactical call setting applies when the sessions end.")

    def apply_pending(self) -> None:
        if self.deferred and not self.sessions_up():
            self.deferred = False
            self.core.settings.apply_to_station()

    def _notice(self, text: str, severity: Severity = Severity.INFORMATION) -> None:
        self.core.operator.notice(Notice(text, severity))
