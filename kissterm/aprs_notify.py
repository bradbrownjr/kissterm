"""Deciding whether a decoded APRS packet is worth an unattended notification.

Split out of `kissterm/ui/app.py` on purpose: everything here is a pure
function of an already-decoded `AprsPacket` plus the operator's own
callsigns, with no Textual, no transport, and no I/O, so it is testable the
same way `monitor.mail_waiting_for` is -- feed it a packet, check what comes
back -- without mounting the app or opening a transport. `ui/app.py`'s frame
subscriber is the only caller that turns a decision into an actual
`desktop_notify`/`notify-send` call, an auto-ack transmission, or a
`ConversationStore` write; none of those live here.

Two things are worth an unattended notification today:

- **An APRS message addressed to the operator.** "Addressed to" reuses
  `monitor.callsign_matches` -- the same SSID-stripping rule the "MAIL FOR"
  beacon check already uses, since a message to "W1AW-9" is meant for an
  operator configured as bare "W1AW" just as much as one running "W1AW-9".
- **A Mic-E position flagged Emergency.** `kissterm.aprs.mice.parse_mic_e`
  sets `Position.mic_e_message` to exactly `"Emergency"` (never
  `"Emergency (custom)"` -- see that module) for both codesets, so an exact
  string compare is correct and does not need the custom-suffix stripping a
  caller would otherwise have to do for every other message type.

`Cooldown` exists because a flapping or misconfigured station repeating the
same Emergency flag (or a message retried because its own ack never arrived)
must not become a toast every few seconds -- but an Emergency notification
always bypasses it (`urgent=True`), because the one case a cooldown must
never suppress is the one it exists to warn about. There is no "quiet
hours"/global-cap machinery here (docs/ROADMAP.md P9's rate-limiting design)
because nothing in this codebase has built that yet; this stays a plain
per-key cooldown until something else needs the more elaborate version.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .aprs import AprsPacket, Message, Position
from .monitor import callsign_matches

__all__ = ["NotifyDecision", "evaluate_packet", "Cooldown"]

#: How long a non-urgent notification key stays suppressed after firing.
DEFAULT_COOLDOWN_SECONDS = 120.0


@dataclass(frozen=True, slots=True)
class NotifyDecision:
    """What to tell the operator, and how insistently.

    `key` identifies the (source, reason) pair a `Cooldown` gates on --
    kept as a separate field rather than derived from `title`/`body` so the
    cooldown does not have to parse displayed text back into an identity.
    """

    title: str
    body: str
    key: tuple[str, str]
    urgent: bool = False


def evaluate_packet(
    packet: AprsPacket, mycall: str, aliases: list[str]
) -> NotifyDecision | None:
    """A `NotifyDecision` for `packet`, or `None` if it warrants nothing.

    Callers pass every decoded packet through this; most return `None`
    immediately (an ordinary position report, a message to someone else, a
    non-Emergency Mic-E beacon) and that is the expected, common case.
    """
    source = str(packet.source)
    mycalls = [mycall, *aliases]

    if packet.kind == "message" and isinstance(packet.data, Message):
        msg = packet.data
        if msg.is_ack or msg.is_rej:
            return None
        if not callsign_matches(msg.addressee, mycalls):
            return None
        return NotifyDecision(
            title=f"APRS message from {source}",
            body=msg.text,
            key=(source, "message"),
            urgent=False,
        )

    if packet.kind == "mic-e" and isinstance(packet.data, Position):
        if packet.data.mic_e_message == "Emergency":
            return NotifyDecision(
                title=f"APRS EMERGENCY -- {source}",
                body=packet.data.comment or "Emergency flag set, no comment text",
                key=(source, "emergency"),
                urgent=True,
            )

    return None


class Cooldown:
    """Per-key "have we already notified about this recently" gate.

    Not thread-safe and not meant to be -- everything that calls `allow`
    runs on the Textual event loop, same as every other piece of app state
    in this codebase (AGENTS.md sec. 3's single-threaded rule applies here
    too, even though this class has no timers of its own).
    """

    def __init__(self, window_seconds: float = DEFAULT_COOLDOWN_SECONDS) -> None:
        self.window_seconds = window_seconds
        self._last_fired: dict[tuple[str, str], float] = {}

    def allow(self, key: tuple[str, str], *, urgent: bool = False, now: float | None = None) -> bool:
        """Whether a notification for `key` should fire right now.

        Records the firing time itself when it returns True, so a caller
        does not have to remember to call back in -- one call per
        notification decision, same as `TransmitGate.enabled` being checked
        and acted on in one step everywhere else in this codebase.
        """
        if urgent:
            return True
        now = now if now is not None else time.monotonic()
        last = self._last_fired.get(key)
        if last is not None and now - last < self.window_seconds:
            return False
        self._last_fired[key] = now
        return True
