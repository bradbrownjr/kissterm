"""What the station hears on the channel, for every front end (ROADMAP
P7a M6): the heard list, NET/ROM node claims, "mail for" beacons, watched
callsigns, and every frame each way for a client's monitor view.

**One subscriber on the one fan-out** (AGENTS.md section 2b). `Core`
registers `on_received` first, so the heard list has an entry before the
APRS decode (`aprs.py`) adds a position to it. Every frame counts,
link-owned or not: the peer we are linked to is a station we have heard,
and its UA is the most interesting frame of a connection attempt.
`on_sent` feeds only the monitor -- hearing ourselves is not hearing
another station, and our own callsign in the heard list would be a lie.

**Frames go to clients raw** (`FrameSeen`); a client filters and formats
them for its own monitor (`monitor.MonitorFilter`, `format_frame`).

**Passive notices.** A node's beacon advertising mail for this station
(ROADMAP P9, "Passive mail waiting notification") is read off the
fan-out, asks nothing and needs no connection; once per (source, call),
since a beacon repeats on its own interval. A watched callsign is a
*claim* carried in a frame, never an authenticated identity (AGENTS.md "A
callsign is a claim"); its notices are rate-limited (`WatchNotifier`) and
held back while the operator is actively using a client
(`operator_active`).

**Another station on our own call.** A frame received whose source is
exactly one of the calls this station sends as (`own_calls`: the call, the
tactical call, the aliases, the APRS source; the SSID must match, so the
operator's own node on KC1JMH-15 is another station, not this one) was
sent by something else: a second program or radio keyed up under the same
call. It answers DM to traffic on our links and the far node drops them
(LinBPQ `L2Code.c`, a DM in a connected state: `CLEAROUTLINK`), which looks
like a bad path. Found the hard way on 2026-11-18, an EasyTerm left open on
the modem's computer. A copy of our own frame (a digipeater's repeat, a TNC
that echoes) matches something we sent within `ECHO_WINDOW` seconds and is
not counted. Every one is logged; the notice repeats at most every
`OWN_CALL_REPEAT` seconds per call.
"""

from __future__ import annotations

import collections
import logging
import time
from datetime import datetime

from ..ax25.address import AX25Address, AX25AddressError
from ..ax25.frame import PID_NO_LAYER3, UType
from ..identity import air_call
from ..monitor import mail_waiting_for, sanitize
from ..netrom import KnownNodes
from ..watched_notify import WatchNotifier, claimed_callsigns, normalize_callsigns
from .events import Alert, FrameSeen, KnownNodesChanged
from .operator import Notice, Severity

log = logging.getLogger(__name__)

#: How long one of our frames can take to come back to us repeated (a
#: digipeater, a TNC that echoes what it sends). WIDE2-2 is a few seconds.
ECHO_WINDOW = 120.0
#: How often the notice about another station on our call may repeat.
OWN_CALL_REPEAT = 30 * 60.0


def _signature(frame) -> tuple:
    """What a repeat of a frame keeps: everything but the C and H bits."""
    path = frame.path
    return (str(path.destination), str(path.source), frame.kind, frame.utype,
            frame.stype, frame.ns, frame.nr, frame.pf, frame.pid, frame.info)


class Channel:
    """The channel as heard. Owned by `Core` as `core.channel`."""

    def __init__(self, core) -> None:
        self.core = core
        #: NET/ROM nodes claimed in broadcasts heard (`netrom.py`).
        self.known_nodes = KnownNodes()
        #: (source, matched callsign) pairs already announced: the point is
        #: "you have not seen this yet", not a running tally.
        self.mail_notified: set[tuple[str, str]] = set()
        #: Monotonic time of the operator's last deliberate use of a client
        #: (`operator_active`) -- active use, not a window left open.
        self.last_operator_activity = time.monotonic()
        self.watch_notifier = self.make_watch_notifier()
        #: (monotonic time, `_signature`) of frames we sent within `ECHO_WINDOW`.
        self.recent_sent: collections.deque = collections.deque()
        #: Call -> monotonic time its "another station" notice last went out.
        self.own_call_notified: dict[str, float] = {}

    @property
    def config(self):
        return self.core.config

    def make_watch_notifier(self) -> WatchNotifier:
        watched = self.config.watched_callsigns
        return WatchNotifier(
            cooldown_seconds=watched.cooldown_minutes * 60,
            hourly_cap=watched.hourly_cap,
            quiet_start_hour=watched.quiet_start_hour if watched.quiet_start_hour >= 0 else None,
            quiet_end_hour=watched.quiet_end_hour if watched.quiet_end_hour >= 0 else None,
        )

    def operator_active(self) -> None:
        """A client saw the operator use it (a key press): a frame shown
        while they are looking needs no notice."""
        self.last_operator_activity = time.monotonic()

    # ------------------------------------------------------------------
    def on_received(self, frame, port: int = 0) -> None:
        self.core.heard.record(frame, port)
        self.core.events.publish(FrameSeen(frame, port, False))
        self.check_own_call(frame)
        self.check_mail_for(frame)
        self.check_watched_callsigns(frame)
        if self.known_nodes.observe(frame):
            self.core.events.publish(KnownNodesChanged())

    def on_sent(self, frame, port: int = 0) -> None:
        now = time.monotonic()
        self._prune_sent(now)
        self.recent_sent.append((now, _signature(frame)))
        self.core.events.publish(FrameSeen(frame, port, True))

    def _prune_sent(self, now: float) -> None:
        while self.recent_sent and now - self.recent_sent[0][0] > ECHO_WINDOW:
            self.recent_sent.popleft()

    def own_calls(self) -> set[str]:
        """Every source address this station sends under, SSID included."""
        config = self.config
        calls: set[str] = set()
        candidates = [config.mycall, air_call(config), *config.mycall_aliases]
        if config.mycall:
            try:
                candidates.append(str(config.aprs.source_for(config.mycall)))
            except (AX25AddressError, ValueError):
                pass
        for text in candidates:
            try:
                calls.add(str(AX25Address.parse(str(text).strip())))
            except (AX25AddressError, ValueError):
                continue
        return calls

    def check_own_call(self, frame) -> None:
        """Another station transmitting under exactly one of our calls
        (module docstring)."""
        source = str(frame.path.source)
        if source not in self.own_calls():
            return
        now = time.monotonic()
        self._prune_sent(now)
        signature = _signature(frame)
        if any(sent == signature for _, sent in self.recent_sent):
            return
        # Built from parsed addresses (validated letters and digits) and the
        # frame type: kissterm's own words, not remote text.
        line = frame.summary()
        log.warning("another station is transmitting as %s: heard %s", source, line)
        last = self.own_call_notified.get(source)
        if last is not None and now - last < OWN_CALL_REPEAT:
            return
        self.own_call_notified[source] = now
        self.core.operator.notice(Notice(
            f"Another station is transmitting as {source} (heard {line}). Two stations "
            f"on one call answer each other's links and the node drops them. Look for "
            f"another program or radio using {source}, such as a terminal left open on "
            f"the modem's computer.", Severity.WARNING))

    def check_watched_callsigns(self, frame) -> None:
        """Surface configured source/repeater *claims* from the fan-out."""
        watched = self.config.watched_callsigns
        if not watched.enabled or not watched.callsigns:
            return
        claimed = claimed_callsigns(frame.path)
        wanted = normalize_callsigns(watched.callsigns)
        active = time.monotonic() - self.last_operator_activity < watched.active_suppression_seconds
        now_local = datetime.now().astimezone()
        for callsign in sorted(claimed & wanted):
            if not self.watch_notifier.allow(
                callsign, now_monotonic=time.monotonic(), now_local=now_local, app_active=active
            ):
                continue
            title = f"Watched callsign claim: {callsign}"
            body = "Claim carried in a received AX.25 frame; not authenticated identity."
            self.core.operator.notice(Notice(f"{title}. {body}"))
            self.core.events.publish(Alert(title, body, False, topic="watched"))

    def check_mail_for(self, frame) -> None:
        """Someone else's node beaconing mail for us. UI frames only: that
        is what a beacon is; a connected-mode chat line that happens to say
        "mail for" is not a node advertising a mailbox."""
        if frame.kind != "U" or frame.utype is not UType.UI:
            return
        if not frame.info or frame.pid not in (PID_NO_LAYER3, None):
            return
        calls = [self.config.mycall, *self.config.mycall_aliases]
        matched = mail_waiting_for(sanitize(frame.info, keep_newlines=False), calls)
        if matched is None:
            return
        source = str(frame.path.source)
        key = (source, matched)
        if key in self.mail_notified:
            return
        self.mail_notified.add(key)
        self.core.operator.notice(Notice(f"{source} has mail waiting for {matched}."))
        self.core.events.publish(Alert(
            f"Mail waiting at {source}", f'Heard "MAIL FOR {matched}" on the channel.',
            True, topic="mail"))
