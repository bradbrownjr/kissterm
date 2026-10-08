"""Broadcast: free text to the channel with no connection, and what was heard.

Other packet programs let an operator type a line and send it as an unproto
(UI) frame to `CQ`, `QST`, `ALL`... with nobody connected: an announcement, a
test, an ad hoc chat on a frequency (operator, 2026-10-08). kissterm had only
the saved beacon text (`beacon.py`); this sends text typed now, and lists the
plain-text UI frames heard to the same addresses so a reply is seen.

**Not APRS and not the beacon.** APRS (`kissterm/aprs/`) has its own
position and message formats; BTEXT is the timed beacon. A broadcast is
sent once, by the operator, to a plain destination.

**Sending is a deliberate commit.** It is the confirmed, operator-named
request that arms the transmit gate, as a connect or an APRS message does
(`Connector.arm_for`): the front end shows the airtime first and sends only
when the operator presses Send. Nothing here repeats, retries or waits
for an answer: an unproto frame has no ack. Under a tactical call the
licensed call is identified afterwards (`core/identifier.py`).

What is *heard*: UI frames with no layer-3 protocol (PID F0) addressed to
one of `DESTINATIONS`. # UNVERIFIED: that list is the long-standing
convention (CQ, QST, ALL, TEST, BEACON, ID, MAIL), not a standard; a UI
frame to any other address is APRS or something else and stays in the
Monitor. A frame that decodes as an APRS report is left to the APRS tab, so
text that starts like one (`!`, `>`, `:`...) is not listed. Heard text is
sanitized before it is stored.
"""

from __future__ import annotations

import collections
import logging
import time
from dataclasses import dataclass

from ..ax25.address import AX25Address, AX25AddressError, AX25Path
from ..aprs.parse import parse_packet
from ..ax25.frame import PID_NO_LAYER3, AX25Frame, UType
from ..beacon import MAX_BEACON_BYTES, normalize_text
from ..monitor import sanitize
from ..nodes.reference import airtime_seconds
from .events import BroadcastHeard
from .operator import Notice, Severity
from .wording import TRANSMIT_DISABLED

log = logging.getLogger(__name__)

#: Where a broadcast may be addressed (and what is listed as heard).
DESTINATIONS = ("CQ", "QST", "ALL", "TEST", "BEACON", "ID", "MAIL")
#: Most lines kept in the heard list.
HEARD_MAX = 200


@dataclass(frozen=True, slots=True)
class Heard:
    source: str
    to: str
    text: str
    at: float
    own: bool = False


def cost(text: str) -> str:
    """What sending `text` costs the channel, in words."""
    payload = normalize_text(text).encode("latin-1", "replace")[:MAX_BEACON_BYTES]
    if not payload:
        return "nothing to send"
    seconds = airtime_seconds(len(payload))
    return ("under a second" if seconds < 1.5 else f"about {seconds:.0f} seconds") + " of channel"


class Broadcast:
    def __init__(self, core) -> None:
        self.core = core
        self.heard: collections.deque[Heard] = collections.deque(maxlen=HEARD_MAX)

    # -- hearing ------------------------------------------------------------
    def on_frame(self, frame: AX25Frame, port: int = 0) -> None:
        """A frame subscriber (`Core.frame_subscribers`)."""
        if frame.kind != "U" or frame.utype is not UType.UI or not frame.info:
            return
        if frame.pid not in (PID_NO_LAYER3, None):
            return
        to = frame.path.destination.callsign.upper()
        if to not in DESTINATIONS:
            return
        packet = parse_packet(frame)
        if packet is not None and packet.kind != "unparsed":
            return  # a decoded APRS report, not a line of text: the APRS tab has it
        text = sanitize(frame.info, keep_newlines=False).strip()
        if text:
            self._add(Heard(str(frame.path.source), to, text, time.time()))

    def _add(self, entry: Heard) -> None:
        self.heard.append(entry)
        self.core.events.publish(BroadcastHeard(entry.source, entry.to, entry.text,
                                                entry.at, entry.own))

    def recent(self) -> list[dict]:
        return [{"source": h.source, "to": h.to, "text": h.text, "at": h.at, "own": h.own}
                for h in self.heard]

    # -- sending --------------------------------------------------------------
    def problem(self, to: str, text: str) -> str:
        """Why this cannot be sent, or ""."""
        if self.core.station is None:
            return "There is no radio transport to send on."
        if to.strip().upper() not in DESTINATIONS:
            return f"Send to one of: {', '.join(DESTINATIONS)}."
        if not normalize_text(text):
            return "There is nothing to send."
        return ""

    async def send(self, to: str, text: str) -> str:
        """Send one broadcast now. Returns "" when it went out, else why not
        (also noticed). Arms the gate: pressing Send is the commitment."""
        to = to.strip().upper()
        why = self.problem(to, text)
        if why:
            self._notice(why, Severity.WARNING)
            return why
        payload = normalize_text(text).encode("latin-1", "replace")[:MAX_BEACON_BYTES]
        station = self.core.station
        try:
            path = AX25Path(AX25Address.parse(to), station.mycall, ())
        except (AX25AddressError, ValueError) as exc:
            self._notice(f"Cannot address {to}: {exc}", Severity.WARNING)
            return str(exc)
        frame = AX25Frame.u_frame(path, UType.UI, command=False, info=payload)
        self.core.connector.arm_for(f"broadcasting to {to}")
        if not self.core.gate.enabled:
            self._notice(TRANSMIT_DISABLED, Severity.WARNING)
            return TRANSMIT_DISABLED
        try:
            await station.transport.send_frame(frame, 0)
        except Exception as exc:  # a transport can fail at any moment
            log.warning("broadcast not sent: %s", exc)
            self._notice(f"Broadcast not sent: {exc}", Severity.WARNING)
            return str(exc)
        self._add(Heard(str(station.mycall), to, payload.decode("latin-1"), time.time(), True))
        self._notice(f"Broadcast sent to {to}.")
        await self.core.identifier.send(reason="after the broadcast")
        return ""

    def _notice(self, text: str, severity: Severity = Severity.INFORMATION) -> None:
        self.core.operator.notice(Notice(text, severity))
