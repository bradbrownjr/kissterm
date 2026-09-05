"""Plain-text beacons (BTEXT) -- periodic unproto UI frames.

The oldest convention in packet: a short, repeating transmission to an
unconnected destination announcing that a station exists and what it offers.
It is how somebody who has never heard of you finds out there is a reason to
connect.

**This is not APRS beaconing.** APRS (`kissterm/aprs/`) sends a position in
APRS payload format to the `APRS` destination. This sends free text to
`BEACON`/`ID`/`CQ`. Same `AX25Frame.u_frame(..., UType.UI)` machinery, two
different features, and they must not be conflated in the config or in the UI
-- an operator who turns on "beaconing" expecting one and gets the other is
transmitting something they did not intend, under their own callsign.

**A beacon is unattended transmission.** Everything here follows from that:

- Off by default. A fresh install must never key a transmitter on its own.
- `MIN_INTERVAL_MINUTES` is enforced *in code*, in two places -- the config
  loader clamps it, and `Beaconer.interval_seconds` clamps it again. A
  minimum interval that lives only in a help string is not a minimum.
- The first transmission happens one full interval after start, never at
  startup. Launching the app is not a request to transmit, and an operator
  who starts kissterm to check something and quits has then keyed the radio
  for no reason.
- An empty beacon is never sent. Text that says nothing is pure channel
  occupancy; `MAIL FOR:` with nothing after it is the classic instance.
- Every transmission is written to the terminal pane. A station that
  transmits without the operator being able to see that it did is the thing
  the whole opt-in exists to prevent.

`describe_cost` exists because "every 10 minutes" does not tell an operator
anything, and "about 3 seconds of channel every 10 minutes -- 0.5% of the
frequency" does. At 1200 baud a beacon is a real cost borne by everyone else
on the channel, so the number goes in front of the operator at the moment
they choose the interval.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from .ax25.address import AX25Address, AX25AddressError, AX25Path, parse_path
from .ax25.frame import AX25Frame, UType
from .config import MIN_BEACON_INTERVAL_MINUTES, BeaconConfig
from .nodes.reference import airtime_seconds

log = logging.getLogger(__name__)

#: Re-exported so callers do not have to reach into `config` for it.
MIN_INTERVAL_MINUTES = MIN_BEACON_INTERVAL_MINUTES

#: A beacon longer than this is a bulletin, and bulletins do not belong on a
#: timer. Truncated rather than refused, so a long text still beacons -- but
#: `build_frame` reports the truncation so the operator is not misled about
#: what went out.
MAX_BEACON_BYTES = 256


def normalize_text(text: str) -> str:
    """Collapse operator-entered beacon text into what actually goes on the air.

    Multi-line text is joined with CR, not LF, because packet is CR-oriented
    (an LF makes a BPQ32 node echo a spurious blank line). Blank lines are
    dropped rather than transmitted as empty frames' worth of nothing.
    """
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\r".join(line for line in lines if line)


def encode_text(text: str) -> tuple[bytes, bool]:
    """Encode beacon text for the air. Returns ``(payload, was_truncated)``.

    latin-1 with replacement, matching every other transmit path here: packet
    is byte-oriented and a character the operator pasted must not raise on the
    way to the radio.
    """
    raw = normalize_text(text).encode("latin-1", "replace")
    if len(raw) <= MAX_BEACON_BYTES:
        return raw, False
    return raw[:MAX_BEACON_BYTES], True


def describe_cost(config: BeaconConfig) -> str:
    """One line an operator can act on: what this beacon costs the channel."""
    payload, _ = encode_text(config.text)
    if not payload:
        return "nothing is set to be transmitted"
    seconds = airtime_seconds(len(payload))
    minutes = max(MIN_INTERVAL_MINUTES, config.interval_minutes)
    share = seconds / (minutes * 60) * 100
    length = "under a second" if seconds < 1.5 else f"about {seconds:.0f} seconds"
    # "0.0% of the frequency" reads as "free", which no transmission is.
    portion = "under 0.1%" if share < 0.05 else f"{share:.1f}%"
    return f"{length} of channel every {minutes} minutes -- {portion} of the frequency"


class Beaconer:
    """Sends `config.text` as a UI frame every `config.interval_minutes`.

    Owns no timer state the app has to reason about: `start()` is idempotent,
    `stop()` is safe to call when it never started, and changing the config
    means stop-then-start rather than a live mutation, so there is never a
    moment where the interval and the text disagree about what is going out.
    """

    def __init__(
        self,
        station,
        config: BeaconConfig,
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

        The config loader clamps this too. Both, deliberately: a `Config`
        built in code rather than loaded from a file bypasses the loader, and
        the floor is a courtesy to everyone else on the frequency, not a
        preference of the operator's to be talked out of.
        """
        return max(MIN_INTERVAL_MINUTES, self.config.interval_minutes) * 60.0

    def problem(self) -> str:
        """Why this beacon cannot transmit, or `""` if it can.

        Returned rather than raised: every caller wants to show the reason,
        and none of them want a beacon misconfiguration to take down the app.
        """
        if not self.config.enabled:
            return "beaconing is off"
        if not normalize_text(self.config.text):
            return "no beacon text is set"
        if self.station is None:
            return "no transport"
        try:
            self._path()
        except AX25AddressError as exc:
            return f"bad beacon destination or path: {exc}"
        return ""

    # ------------------------------------------------------------------
    def _path(self) -> AX25Path:
        target = parse_path(f"{self.config.destination} {self.config.path}".strip())
        source: AX25Address = self.station.mycall
        return AX25Path(target.destination, source, target.repeaters)

    def build_frame(self) -> AX25Frame | None:
        """The frame that would go out now, or None if nothing should.

        Separate from sending so a test -- and the Settings pane -- can see
        exactly what would be transmitted without transmitting it.
        """
        payload, truncated = encode_text(self.config.text)
        if not payload:
            return None
        if truncated:
            log.warning(
                "beacon text truncated to %d bytes; a beacon is not a bulletin",
                MAX_BEACON_BYTES,
            )
        # command=False: a UI frame to an unconnected destination is not
        # asking anyone for anything, and marking it a command invites a
        # station running strict AX.25 2.2 to answer it.
        return AX25Frame.u_frame(self._path(), UType.UI, command=False, info=payload)

    async def send_once(self) -> bool:
        """Transmit one beacon now. Returns whether anything went out.

        Re-checks `problem()` rather than trusting the state it was started
        in: config can change under a running beaconer, and the failure mode
        of not re-checking is transmitting text the operator has already
        deleted.
        """
        if self.problem():
            return False
        frame = self.build_frame()
        if frame is None:
            return False
        try:
            await self.station.transport.send_frame(frame, self.config.port)
        except Exception as exc:  # a transport can fail at any moment
            log.warning("beacon not sent: %s", exc)
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
        self._task = asyncio.create_task(self._run(), name="kissterm-beacon")
        return ""

    def cancel(self) -> None:
        """Stop without awaiting -- for a synchronous teardown path.

        `stop()` is the one to prefer; this exists because Textual's
        `on_unmount` is synchronous and a beacon task still armed while the
        app is going away is a transmission nobody is watching for.
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
            # Sleep FIRST. See the module docstring: starting the app is not
            # a request to transmit.
            await asyncio.sleep(self.interval_seconds)
            await self.send_once()
