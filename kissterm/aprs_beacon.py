"""APRS position beaconing -- a periodic position report, on its own timer.

**This is NOT the plain-text beacon in `kissterm/beacon.py`.** That module
sends free text to `BEACON`/`ID`/`CQ`; this one sends an APRS position report
to `APRS`. Separate config table (`Config.aprs`, not `Config.beacon`),
separate Settings section, separate interval -- see `beacon.py`'s module
docstring for why conflating the two is a transmitting bug, not a cosmetic
one: an operator who enables one expecting the other is putting something on
the air under their own callsign that they did not intend.

`AprsBeaconer` mirrors `Beaconer`'s shape (`start`/`stop`/`cancel`/
`send_once`/`problem`/`build_frame`) deliberately -- both are the same
pattern, unattended timer-driven transmission that is off by default, never
sends nothing, and re-checks itself at the moment of transmission rather than
trusting the state it was started in. Only the payload and the config table
differ.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from .aprs import encode as aprs_encode
from .ax25.address import AX25AddressError, AX25Path, parse_path
from .ax25.frame import AX25Frame
from .config import MIN_BEACON_INTERVAL_MINUTES, AprsConfig

log = logging.getLogger(__name__)

#: Same floor as the plain-text beacon, for the same reason: a courtesy to
#: everyone else on the channel, not a preference of the operator's to be
#: talked out of. Enforced here AND in `config._load_aprs`, because a
#: `Config` built in code bypasses the loader.
MIN_INTERVAL_MINUTES = MIN_BEACON_INTERVAL_MINUTES

#: The conventional APRS destination callsign. Not configurable -- unlike the
#: plain-text beacon's `destination` (BEACON/ID/CQ are all legitimate
#: choices), every APRS decoder in the world expects position/status/message
#: traffic addressed to APRS specifically, matching `_send_aprs_ack`/
#: `_send_aprs_message` in `kissterm/ui/app.py`.
APRS_DESTINATION = "APRS"


class AprsBeaconer:
    """Sends a position report built from `config` every
    `config.beacon_interval_minutes`.

    Owns no timer state the app has to reason about: `start()` is idempotent,
    `stop()` is safe to call when it never started, and changing the config
    means stop-then-start rather than a live mutation -- see `Beaconer` for
    the full rationale, which applies unchanged here.
    """

    def __init__(
        self,
        station,
        config: AprsConfig,
        *,
        on_sent: Callable[[AX25Frame], None] | None = None,
    ) -> None:
        self.station = station
        self.config = config
        self.on_sent = on_sent
        self._task: asyncio.Task | None = None
        self.sent_count = 0

    # ------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def interval_seconds(self) -> float:
        """The interval actually used -- clamped, not merely recommended.

        See `Beaconer.interval_seconds`: the config loader clamps this too,
        both deliberately, because a `Config` built in code bypasses the
        loader.
        """
        return max(MIN_INTERVAL_MINUTES, self.config.beacon_interval_minutes) * 60.0

    def problem(self) -> str:
        """Why this beacon cannot transmit, or `""` if it can.

        Returned rather than raised, same as `Beaconer.problem`: every caller
        wants to show the reason, and none of them want a beacon
        misconfiguration to take down the app.
        """
        if not self.config.enabled:
            return "APRS beaconing is off"
        if self.station is None:
            return "no transport"
        gate = getattr(self.station.transport, "gate", None)
        if gate is not None and not gate.enabled:
            # Same rule as Beaconer.problem: the transport would drop the
            # frame silently, and this class must never report a beacon it
            # did not send.
            return "transmit is disabled"
        if self.config.latitude == 0.0 and self.config.longitude == 0.0:
            # 0,0 is a real point (the Gulf of Guinea) and also exactly what
            # an unconfigured `AprsConfig` defaults to. Treating it as "no
            # position set" is the safe read: transmitting a placeholder
            # position under the operator's callsign is worse than not
            # beaconing at all.
            return "no position set (latitude and longitude are both 0.0)"
        if len(self.config.symbol) != 2 or self.config.symbol[0] not in "/\\":
            return f"bad map symbol {self.config.symbol!r}"
        try:
            self._path()
        except AX25AddressError as exc:
            return f"bad beacon path: {exc}"
        return ""

    # ------------------------------------------------------------------
    def _path(self) -> AX25Path:
        return parse_path(f"{APRS_DESTINATION} {self.config.path}".strip())

    def build_frame(self) -> AX25Frame | None:
        """The frame that would go out now, or None if nothing should.

        Separate from sending so a test -- and the Settings pane -- can see
        exactly what would be transmitted without transmitting it. Does not
        trust `problem()` to have been checked first -- `send_once(force=
        True)` waives exactly the "beaconing is off" reason, and `problem()`
        returns only the first thing it finds wrong; if that first thing was
        "off", a second, independent problem (an unset position) would never
        surface. So the checks that must hold even under `force` are
        repeated here too, mirroring `Beaconer.build_frame`'s own
        independent empty-text guard.
        """
        if self.config.latitude == 0.0 and self.config.longitude == 0.0:
            log.warning("APRS beacon not sent: no position set (both 0.0)")
            return None
        if len(self.config.symbol) != 2 or self.config.symbol[0] not in "/\\":
            log.warning("APRS beacon not sent: bad map symbol %r", self.config.symbol)
            return None
        try:
            payload = aprs_encode.position_report(
                self.config.latitude,
                self.config.longitude,
                self.config.symbol[0],
                self.config.symbol[1],
                self.config.comment,
                messaging=True,
            )
        except ValueError as exc:
            log.warning("APRS beacon not sent: %s", exc)
            return None
        target = self._path()
        return aprs_encode.beacon_frame(
            self.station.mycall, target.destination, target.repeaters, payload
        )

    async def send_once(self, force: bool = False) -> bool:
        """Transmit one beacon now. Returns whether anything went out.

        Re-checks `problem()` rather than trusting the state it was started
        in, same as `Beaconer.send_once`: config can change under a running
        beaconer, and the failure mode of not re-checking is transmitting a
        position the operator has already cleared.

        `force` waives exactly one check -- whether the *timer* is enabled --
        matching `Beaconer.send_once`'s "manual beacon is not the timer"
        rule. Every other refusal still stands.
        """
        why = self.problem()
        if why and not (force and why == "APRS beaconing is off"):
            return False
        frame = self.build_frame()
        if frame is None:
            return False
        try:
            await self.station.transport.send_frame(frame, 0)
        except Exception as exc:  # a transport can fail at any moment
            log.warning("APRS beacon not sent: %s", exc)
            return False
        self.sent_count += 1
        if self.on_sent is not None:
            self.on_sent(frame)
        return True

    def start(self) -> str:
        """Begin beaconing. Returns `""` on success or the reason it will not."""
        if self.running:
            return ""
        why = self.problem()
        if why:
            return why
        self._task = asyncio.create_task(self._run(), name="kissterm-aprs-beacon")
        return ""

    def cancel(self) -> None:
        """Stop without awaiting -- for a synchronous teardown path.

        See `Beaconer.cancel`: Textual's `on_unmount` is synchronous, and a
        beacon task still armed while the app is going away is a
        transmission nobody is watching for.
        """
        task, self._task = self._task, None
        if task is not None:
            task.cancel()

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        while True:
            # Sleep FIRST. Starting the app is not a request to transmit.
            await asyncio.sleep(self.interval_seconds)
            await self.send_once()
