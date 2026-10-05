"""APRS in the core: decoding off the shared fan-out, conversations,
auto-ack, sending with ack and retry, both beacons and GPS, for every front
end (ROADMAP P7a M4).

**One decode.** `on_frame` is a subscriber on the same frame fan-out as
the monitor and the heard list (AGENTS.md section 2b); `aprs.parse_packet`
never raises. What it finds goes to clients as events -- `AprsMessage`,
`AprsAcked`, `AprsPacketHeard`, `AprsBulletinHeard` -- and to the
persisted conversation store (`aprs_conversations.py`).

**Unattended traffic and the gate.** An auto-ack and a retry are
unattended: they never arm the gate, and a closed gate drops them without
claiming they went (`send_message` returns False; a blocked auto-ack is
announced, once per message, because the sender is waiting on it). A
message the operator typed, named and sent arms the gate (`compose`), as a
committed connect does; so do "send position now" and a composed object.
The retry queue lives here, not in a client, so it keeps working with no
client attached -- and is still never restored at launch (AGENTS.md
section 8).

**Acks go out under `Config.aprs.source_for`, never another identity.**
LinBPQ requires an exact SSID match; fix addressing, never spoof. Whether
a message counts as "to me" is `monitor.aprs_message_matches`'s decision
alone (`filter_by_ssid`).

**BTEXT is not APRS beaconing** (`beacon.py` vs `aprs_beacon.py`):
separate timers, separate config, separate wording.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import UTC, datetime

from .. import aprs
from ..aprs_beacon import AprsBeaconer
from ..aprs_conversations import ConversationStore, MessageDeduplicator, PendingAcks
from ..aprs_is import AprsIsWatch
from ..aprs_notify import Cooldown, evaluate_packet
from ..ax25 import parse_path
from ..ax25.address import AX25Address, AX25AddressError
from ..aprs_contacts import Contact, build_message_body
from ..beacon import Beaconer
from ..config import AprsConfig, BeaconConfig
from ..gps import GpsReader
from ..locator import find_grid_in_text
from ..monitor import aprs_message_matches, sanitize
from .events import (
    Alert,
    AprsAcked,
    AprsBulletinHeard,
    AprsMessage,
    AprsPacketHeard,
    AprsRetried,
)
from .operator import Notice, Severity
from .wording import TRANSMIT_DISABLED

log = logging.getLogger(__name__)

#: How often the retry loop checks for a due, un-acked message. Independent
#: of `PendingAcks.retry_seconds` (how long a single message waits before
#: its own first/next retry) -- this is just the polling granularity.
RETRY_CHECK_INTERVAL = 10.0


class Aprs:
    """APRS for the station. Owned by `Core` as `core.aprs`."""

    def __init__(self, core) -> None:
        self.core = core
        config = core.config
        #: Message history, keyed by correspondent. Loaded here so a message
        #: that arrives before any client looks is still recorded.
        self.conversations = ConversationStore()
        self.conversations.load()
        self.purge_stale_synthetic_messages()
        #: Keeps an RF retry or a second relay path's copy out of the
        #: conversation twice. In memory only: message numbers are reused,
        #: so a restart starts a new reception window.
        self.deduplicator = MessageDeduplicator()
        #: A repeat alert for the same (source, reason) within its window is
        #: suppressed (`aprs_notify.py`); an Emergency always gets through.
        self.notify_cooldown = Cooldown()
        #: "could not ack -- transmit is off", once per (addressee, number):
        #: a sender retries every 30-90 s. Separate from the alert cooldown,
        #: so the two never consume each other's window.
        self.ack_blocked_cooldown = Cooldown()
        #: Outgoing messages awaiting an ack, in memory only (never restored
        #: at launch; `aprs_conversations.PendingAcks`).
        self.pending = PendingAcks()
        #: Wraps well inside the spec's 1-5 alphanumeric characters.
        self.next_msg_number = 1
        #: Receive-only APRS-IS diagnostics, separate from the RF fan-out;
        #: only ever opened with a `pass -1` login.
        self.is_watch = AprsIsWatch()
        self.is_background_started = False
        #: Plain-text beacon (BTEXT). Does nothing until `start()` succeeds,
        #: which refuses unless the operator opted in AND set some text.
        self.beaconer = Beaconer(
            core.station, getattr(config, "beacon", None) or BeaconConfig(),
            on_sent=self._on_beacon_sent,
        )
        #: APRS position beacon: separate timer, config and destination.
        gps = config.aprs.gps_device.strip()
        self.aprs_beaconer = AprsBeaconer(
            core.station, getattr(config, "aprs", None) or AprsConfig(),
            on_sent=self._on_aprs_beacon_sent,
            position_source=self.gps_position if gps else None,
            motion_source=self.gps_fix if gps else None,
        )
        #: Optional, wholly local; never part of the frame fan-out.
        self.gps_reader: GpsReader | None = None
        self._gps_had_fix = False
        self._tasks: set[asyncio.Task] = set()
        self._retry_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    @property
    def config(self):
        return self.core.config

    def _publish(self, event) -> None:
        self.core.events.publish(event)

    def _notice(self, text: str, severity: Severity = Severity.INFORMATION,
                timeout: float | None = None) -> None:
        self.core.operator.notice(Notice(text, severity, timeout=timeout))

    def spawn(self, coro) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.error("APRS task failed", exc_info=task.exception())

    def start(self) -> None:
        """Start the retry loop. Call from the loop the station runs on."""
        if self._retry_task is None or self._retry_task.done():
            self._retry_task = self.spawn(self._retry_loop())

    def shutdown(self) -> None:
        """Disarm everything that could transmit or listen on its own.

        Not merely tidy: a beacon still armed while its client goes away
        would transmit under the operator's callsign with nothing on screen
        to show it.
        """
        self.beaconer.cancel()
        self.aprs_beaconer.cancel()
        self.is_watch.stop()
        if self.gps_reader is not None:
            self.gps_reader.cancel()
        for task in list(self._tasks):
            task.cancel()

    def active_identity(self) -> str:
        """This station's transmitted APRS identity (`Config.aprs.source_for`),
        what `aprs_message_matches` requires an exact match against when
        `filter_by_ssid` is on. Falls back to the bare callsign on a parse
        failure: this runs from the frame fan-out, and a malformed `mycall`
        must not take the handler down."""
        station = self.core.station
        mycall = str(station.mycall) if station is not None else self.config.mycall
        try:
            return str(self.config.aprs.source_for(mycall))
        except AX25AddressError:
            return mycall

    # ------------------------------------------------------------------
    # Receiving
    # ------------------------------------------------------------------
    async def on_frame(self, frame, port: int = 0) -> None:
        """Decode one frame as APRS, if it is APRS at all, and route it:
        the heard list's position, a conversation, an auto-ack, an alert."""
        packet = aprs.parse_packet(frame)
        if packet is None:
            return
        heard = self.core.heard
        if packet.kind in ("position", "mic-e") and isinstance(packet.data, aprs.Position):
            # The one place the heard list gets a position (`HeardTable`
            # never decodes APRS itself).
            heard.set_position(str(packet.source), packet.data.latitude, packet.data.longitude)
        elif packet.kind == "unparsed":
            # A plain node or BBS beacon often signs off with its grid square
            # ("de W1AW FN31pr"); `find_grid_in_text` is conservative, and a
            # real APRS position is never second-guessed by it.
            found = find_grid_in_text(sanitize(packet.info, keep_newlines=False))
            if found is not None:
                _grid, lat, lon = found
                heard.set_position(str(packet.source), lat, lon)

        # A message relay (WHO-IS, WXBOT, RF <-> APRS-IS traffic) often
        # reaches us only as a third-party packet wrapping the real message,
        # an igate as the outer source. Unwrapped here, or an answered query
        # retries forever. `tp.source` (plain text) is the correspondent, as
        # `format_packet` shows it: the inner AX.25 source of a header with
        # no valid callsign is the `NOCALL` placeholder.
        message_packet, message_source = packet, str(packet.source)
        if (
            packet.kind == "third-party"
            and isinstance(packet.data, aprs.ThirdParty)
            and packet.data.inner.kind == "message"
            and isinstance(packet.data.inner.data, aprs.Message)
        ):
            message_packet, message_source = packet.data.inner, packet.data.source

        if message_packet.kind == "message" and isinstance(message_packet.data, aprs.Message):
            msg = message_packet.data
            source = message_source
            if aprs.is_bulletin_addressee(msg.addressee):
                self._publish(AprsBulletinHeard(source, msg.addressee, msg.text, time.time()))
                return
            if not (msg.is_ack or msg.is_rej or msg.is_telemetry_definition):
                to_me = aprs_message_matches(
                    msg.addressee,
                    self.config.mycall,
                    self.config.mycall_aliases,
                    filter_by_ssid=self.config.aprs.filter_by_ssid,
                    active_identity=self.active_identity(),
                )
                duplicate = self.deduplicator.is_duplicate(
                    source, msg.addressee, msg.text, msg.number)
                if to_me and getattr(self.config, "aprs_auto_ack", True) and msg.number:
                    # A sender may be retrying because our first ack was
                    # lost: a duplicate is shown once but acked every time.
                    await self.send_ack(source, msg.number, port)
                if duplicate:
                    return
                self.conversations.record_incoming(source, msg.text, number=msg.number)
                # Every message is recorded; `to_me` decides whether a
                # client opens it and marks it unread.
                self._publish(AprsMessage(source, to_me))
            elif msg.is_ack and msg.number:
                self.conversations.mark_acked(source, msg.number)
                # At once, not on the next retry check: an ack answers "did
                # that get through?".
                self._publish(AprsAcked(source, msg.number))
        elif packet.kind != "unparsed":
            # Not person-to-person: position, weather, status, telemetry,
            # objects, third-party relays. No correspondent, so shown in
            # "All" only and never written to the conversation store.
            self._publish(AprsPacketHeard(aprs.format_packet(packet), time.time(), packet))

        decision = evaluate_packet(
            packet,
            self.config.mycall,
            self.config.mycall_aliases,
            filter_by_ssid=self.config.aprs.filter_by_ssid,
            active_identity=self.active_identity(),
        )
        if decision is None:
            return
        if not self.notify_cooldown.allow(decision.key, urgent=decision.urgent):
            return
        self._notice(
            f"{decision.title}: {decision.body}" if decision.body else decision.title,
            Severity.WARNING if decision.urgent else Severity.INFORMATION,
            timeout=15 if decision.urgent else 10,
        )
        self._publish(Alert(decision.title, decision.body, decision.urgent))

    def purge_stale_synthetic_messages(self) -> None:
        """Drop persisted lines no person typed, from builds before the
        checks that now exclude them: an incoming telemetry definition
        (`PARM.`/`UNIT.`/`EQNS.`/`BITS.`, excluded since 2026-09-10), and an
        outgoing auto-ack filed as a chat line ("ack407", excluded since
        2026-09-11). Cheap once purged."""
        ack_number_re = re.compile(r"^ack[A-Za-z0-9]{1,5}$")
        changed = False
        for convo in self.conversations.conversations.values():
            kept = [
                m
                for m in convo.messages
                if not (m.direction == "in" and aprs.is_telemetry_definition_text(m.text))
                and not (m.direction == "out" and m.number is None and ack_number_re.match(m.text))
            ]
            if len(kept) != len(convo.messages):
                convo.messages = kept
                changed = True
        if changed:
            self.conversations.save()

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------
    def _gate_closed(self) -> bool:
        station = self.core.station
        gate = getattr(station.transport, "gate", None) if station is not None else None
        return gate is not None and not gate.enabled

    async def send_ack(self, addressee: str, number: str, port: int) -> None:
        """Auto-ack a message addressed to us (`Config.aprs_auto_ack`).

        Under `Config.aprs.source_for`, the identity every other APRS packet
        from this station uses -- never the text the sender put in the
        addressee field: transmitting under an identity that is not this
        station's is the "callsign is a claim" hazard, and an earlier
        version did exactly that. Do not reintroduce it.

        A closed gate is announced, not just obeyed: found live, a station
        with TX off received four retries of a message with no visible sign
        why, until its sender gave up. Never logged as sent when it was not;
        never filed as a chat line (a protocol ack is not conversation).
        """
        station = self.core.station
        if station is None:
            return
        if self._gate_closed():
            if self.ack_blocked_cooldown.allow((addressee, number)):
                self._notice(
                    f"{addressee} sent a message that needs an acknowledgment, but "
                    "Transmit is OFF, so nothing was sent back. Press {key:toggle_transmit} to turn "
                    "Transmit on.",
                    Severity.WARNING,
                    timeout=10,
                )
            return
        source = self.config.aprs.source_for(str(station.mycall))
        try:
            payload = aprs.ack(addressee, number)
            outframe = aprs.beacon_frame(source, AX25Address.parse("APRS"), (), payload)
            await station.transport.send_frame(outframe, port)
        except Exception as exc:  # noqa: BLE001 - an ack failure must not disturb a link
            log.debug("APRS auto-ack to %s not sent: %s", addressee, exc)
            return
        log.info("APRS auto-ack sent to %s (msg %s)", addressee, number)

    async def send_message(
        self, addressee: str, text: str, number: str | None, *, port: int = 0, retry: bool = False
    ) -> bool:
        """Encode and transmit one message frame -- the one primitive for a
        fresh send and a retry. True if it actually went out. Touches no
        history and no pending-ack tracking: whether this is the first send
        or a retry is the caller's to know."""
        station = self.core.station
        if station is None or self._gate_closed():
            return False
        try:
            payload = aprs.message(addressee, text, number=number)
            # The same APRS-only SSID override the position beacon uses, so a
            # message and a beacon go out under one identity.
            outframe = aprs.beacon_frame(
                self.config.aprs.source_for(str(station.mycall)),
                AX25Address.parse("APRS"), (), payload)
            await station.transport.send_frame(outframe, port)
        except Exception as exc:  # noqa: BLE001 - reported as not sent
            log.debug("APRS message to %s not sent: %s", addressee, exc)
            return False
        verb = "Resent" if retry else "Sent"
        kind = "bulletin" if number is None else f"message {number}"
        log.info("%s APRS %s to %s", verb, kind, addressee)
        return True

    def next_number(self) -> str:
        number = str(self.next_msg_number)
        self.next_msg_number = self.next_msg_number % 99999 + 1
        return number

    def contact_for(self, callsign: str) -> Contact | None:
        """The saved APRS contact for `callsign`, or None for a bare "To:"
        that matches none (sent as a plain station message)."""
        callsign = callsign.strip().upper()
        for raw in getattr(self.config, "aprs_contacts", ()) or ():
            if str(raw.get("callsign", "")).strip().upper() == callsign:
                return Contact.from_dict(raw)
        return None

    async def compose(self, addressee: str, text: str) -> str:
        """Send a message the operator typed to `addressee`.

        Returns "sent" (tracked for an ack), "bulletin" (sent, never
        retried: an announcement has no peer to ack it), or "" when nothing
        went out (the operator has been told why).

        Typing a message, naming a "To:" and pressing Send is the confirmed,
        targeted request that arms the gate, as a connect is. A retry is not
        (`check_retries`): it is unattended and stays dropped while the gate
        is closed. Arming needs a station to send on, or it would open the
        gate for nothing. The history keeps what the operator typed; the
        retry resends the exact wire text the first send used.
        """
        contact = self.contact_for(addressee)
        service = contact.service if contact else "station"
        detail = contact.detail if contact else ""
        wire_text = build_message_body(
            service, detail, text,
            sms_template=getattr(self.config, "aprs_sms_template", ""),
            email_template=getattr(self.config, "aprs_email_template", ""),
        )
        bulletin = aprs.is_bulletin_addressee(addressee)
        number = None if bulletin else self.next_number()
        if service == "sms" or addressee.strip().upper() in {"SMS", "SMSGTE"}:
            # Receive-only, started before the RF request so debug logging
            # can see both the packet reach APRS-IS and the gateway's reply.
            self.start_is_watch_for_debug()
        if self.core.station is not None:
            self.core.connector.arm_for(f"sending to {addressee}")
        if not await self.send_message(addressee, wire_text, number):
            self._notice("Message not sent -- transmit is disabled ({key:toggle_transmit}).", Severity.WARNING)
            return ""
        if bulletin:
            return "bulletin"
        self.conversations.record_outgoing(addressee, text, number=number, service=service)
        self.pending.add(addressee, number, wire_text)
        return "sent"

    async def check_retries(self) -> None:
        """Resend whatever is due and un-acked. Never arms the gate."""
        self.pending.discard_acked(self.conversations)
        for callsign, number, text in self.pending.due():
            await self.send_message(callsign, text, number, retry=True)
        # An ack may have landed and a retry gone out since the last paint.
        self._publish(AprsRetried())

    async def _retry_loop(self) -> None:
        while True:
            await asyncio.sleep(RETRY_CHECK_INTERVAL)
            try:
                await self.check_retries()
            except Exception:  # noqa: BLE001 - the queue must outlive one bad send
                log.exception("APRS retry check failed")

    async def send_position_now(self) -> None:
        """APRS > Send position: one position report now. Operator-committed
        to a well-defined destination, so it arms the gate; it does not
        enable or alter the periodic beacon (`force=True` waives only that
        timer setting)."""
        self.core.connector.arm_for("APRS position beacon")
        why = self.aprs_beaconer.problem()
        if why and why != "APRS beaconing is off":
            self._notice(f"APRS position beacon not sent: {why}", Severity.WARNING)
            return
        if await self.aprs_beaconer.send_once(force=True):
            self._notice("APRS position beacon sent.")
        else:
            self._notice("APRS position beacon not sent.", Severity.WARNING)

    async def send_object(self, request) -> bool:
        """Encode and transmit one deliberately composed object report
        (`request`: name, alive, latitude, longitude, symbol, comment, scope).
        Logged only after the transport accepted it."""
        station = self.core.station
        if station is None or self._gate_closed():
            return False
        try:
            target = parse_path(f"APRS {self.config.aprs.path}".strip())
            via = target.repeaters
            if request.scope == "rf_only":
                # RFONLY in the digi field: the originator asks that this not
                # be gated to APRS-IS. The RF path stays, so an EOC beyond
                # direct range still hears the exercise object.
                if not any(str(digi) == "RFONLY" for digi in via):
                    via = (*via, AX25Address.parse("RFONLY"))
            elif request.scope == "direct":
                via = ()
            timestamp = datetime.now(UTC).strftime("%d%H%Mz")
            payload = aprs.object_report(
                request.name, request.alive, timestamp, request.latitude,
                request.longitude, request.symbol[0], request.symbol[1], request.comment,
            )
            outframe = aprs.beacon_frame(
                self.config.aprs.source_for(str(station.mycall)),
                target.destination, via, payload,
            )
            await station.transport.send_frame(outframe, 0)
        except Exception as exc:  # noqa: BLE001 - reported as not sent
            log.debug("APRS object %s not sent: %s", request.name, exc)
            return False
        # Strict printable ASCII, so the payload is safe to keep verbatim.
        log.debug("APRS object transmission accepted: %s:%s", outframe.path, payload.decode("ascii"))
        log.info("sent %s APRS object %s", "live" if request.alive else "killed",
                 request.name.strip())
        return True

    async def send_object_now(self, request) -> bool:
        """A composed object, sent: the explicit Send is operator-committed
        and arms the gate."""
        if self.core.station is not None:
            self.core.connector.arm_for(f"APRS object {request.name.strip()}")
        if await self.send_object(request):
            self._notice(f"APRS object {request.name.strip()} sent.")
            return True
        self._notice("APRS object not sent. Check its fields and APRS path.", Severity.WARNING)
        return False

    # ------------------------------------------------------------------
    # Beacons and GPS
    # ------------------------------------------------------------------
    async def beacon_now(self) -> None:
        """Send one BTEXT beacon now. It does not enable the timer, and it
        does NOT arm the gate: one keystroke, no target, is the shape of an
        accidental transmission. A closed gate is reported."""
        if not self.core.gate.enabled:
            self._notice(TRANSMIT_DISABLED, Severity.WARNING)
            return
        why = self.beaconer.problem()
        # "beaconing is off" is about the TIMER, not a reason to refuse.
        if why and why != "beaconing is off":
            self._notice(f"No beacon sent: {why}", Severity.WARNING)
            return
        if await self.beaconer.send_once(force=True):
            self._notice("Beacon sent.")
        else:
            self._notice("Beacon not sent.", Severity.WARNING)

    def follow_station(self) -> None:
        """Point both beacons at the station a newly opened transport
        built (`Core.open_initial_transport`)."""
        self.beaconer.station = self.core.station
        self.aprs_beaconer.station = self.core.station

    async def restart_beacon(self) -> None:
        """Stop then start, never mutate a running beaconer: a half-changed
        config transmitting under the operator's callsign is not acceptable."""
        await self.beaconer.stop()
        self.beaconer.station = self.core.station
        self.beaconer.config = getattr(self.config, "beacon", None) or BeaconConfig()
        why = self.beaconer.start()
        # Only when the operator asked for a beacon and did not get one; TX
        # off is already the loudest thing on screen.
        if why and self.beaconer.config.enabled and why != "transmit is disabled":
            self._notice(f"Beacon not started: {why}", Severity.WARNING)

    async def restart_aprs_beacon(self) -> None:
        await self.aprs_beaconer.stop()
        self.aprs_beaconer.station = self.core.station
        self.aprs_beaconer.config = getattr(self.config, "aprs", None) or AprsConfig()
        gps = self.aprs_beaconer.config.gps_device.strip()
        self.aprs_beaconer.position_source = self.gps_position if gps else None
        self.aprs_beaconer.motion_source = self.gps_fix if gps else None
        why = self.aprs_beaconer.start()
        if why and self.aprs_beaconer.config.enabled and why != "transmit is disabled":
            self._notice(f"APRS beacon not started: {why}", Severity.WARNING)

    async def restart_gps(self) -> None:
        """Replace the local NMEA reader after a settings change."""
        if self.gps_reader is not None:
            await self.gps_reader.stop()
        device = self.config.aprs.gps_device.strip()
        self.gps_reader = GpsReader(device) if device else None
        self._gps_had_fix = False
        if self.gps_reader is not None:
            self.gps_reader.subscribe(self.on_gps_fix)
            self.gps_reader.start()

    def gps_position(self) -> tuple[float, float] | None:
        """The receiver's live position, never copied into configuration."""
        fix = self.gps_reader.fix if self.gps_reader is not None else None
        return (fix.latitude, fix.longitude) if fix is not None else None

    def gps_fix(self):
        """The live GPS motion record, never persisted or transmitted alone."""
        return self.gps_reader.fix if self.gps_reader is not None else None

    def on_gps_fix(self, fix) -> None:
        """Start a waiting periodic beacon when a receiver first fixes, on
        the false->true edge only (keeping its sleep-first behaviour). Never
        arms TX; the beaconer's send path rechecks the gate."""
        had_fix, self._gps_had_fix = self._gps_had_fix, fix is not None
        if fix is not None and not had_fix:
            self.spawn(self.restart_aprs_beacon())
        self.aprs_beaconer.note_fix(fix)

    @staticmethod
    def _on_beacon_sent(frame) -> None:
        """Every beacon is visible: the Monitor shows the frame, the status
        shows BEACON while armed, and kissterm.log keeps the record."""
        log.info("beacon sent to %s", frame.path.destination)

    @staticmethod
    def _on_aprs_beacon_sent(frame) -> None:
        log.info("APRS position beacon sent")

    # ------------------------------------------------------------------
    # APRS-IS diagnostics (receive-only; `aprs_is.py`)
    # ------------------------------------------------------------------
    def is_background_requested(self) -> bool:
        """Whether the configured debug monitor owns the APRS-IS client."""
        return bool(
            getattr(self.config, "aprs_is_watch_debug", False)
            and log.isEnabledFor(logging.DEBUG)
        )

    def reconcile_is_debug_watch(self) -> None:
        """Apply the opt-in background APRS-IS diagnostic setting, tied to
        debug logging actually being on: the stream is useful only while
        its evidence is kept. A manually opened or SMS-started watcher is
        never stopped here."""
        enabled = self.is_background_requested()
        debug_logging = log.isEnabledFor(logging.DEBUG)
        if enabled and debug_logging and not self.is_watch.running:
            try:
                self.is_watch.start(callsign=self.active_identity())
            except ValueError as exc:
                log.debug("APRS-IS background watch not started: %s", exc)
            else:
                self.is_background_started = True
                log.debug("APRS-IS background watch enabled")
        elif self.is_background_started and (not enabled or not debug_logging):
            self.is_watch.stop()
            self.is_background_started = False

    def start_is_watch_for_debug(self) -> None:
        """Begin a receive-only observation before a deliberate SMS request,
        without delaying the RF send for it."""
        if not log.isEnabledFor(logging.DEBUG) or self.is_watch.running:
            return
        try:
            callsign = self.active_identity()
            self.is_watch.start(callsign=callsign)
            log.debug("APRS-IS watch auto-started for SMS diagnostic: %s", callsign)
        except ValueError as exc:
            log.debug("APRS-IS watch not started for SMS diagnostic: %s", exc)
