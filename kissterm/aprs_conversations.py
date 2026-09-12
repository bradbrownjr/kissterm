"""APRS message history, kept per correspondent -- the log behind the chat pane.

Modeled directly on `kissterm/addressbook.py`: JSON in the state directory
(never `config.toml` -- this is history the program writes on its own, not
settings an operator hand-edits, exactly the reasoning `AddressBook`'s own
docstring gives for the same choice), atomic write via temp-file plus
`os.replace`, and a load that never raises -- a corrupt or missing file costs
you your message history and nothing else, same as a corrupt address book
costs you your station list and nothing else.

**Keyed on the full callsign-plus-SSID, not the base call.** Unlike the
"addressed to me" check in `kissterm.aprs_notify` (which deliberately
ignores SSID, because a message meant for the operator should reach them
however their own station is configured), a *conversation* with "W1AW-9" and
one with "W1AW" are kept separate here: they may be different physical
stations (a home station and a mobile), and merging their histories under
one entry would be presenting messages from two potentially different people
as one conversation.

**Pending-ack/retry bookkeeping (`PendingAcks`, below) is deliberately
NOT part of `ConversationStore` and is never persisted.** Which outgoing
message numbers are still awaiting an ack, how many times each has been
retried, and when the next retry is due are all in-memory-only state owned
by the pane that sent them -- the same reason `AX25Link`'s T1/T2/T3 timers
are never persisted. A message still unacknowledged when kissterm restarts
should not silently keep retrying into a conversation the operator may have
already resolved by other means (a phone call, a different net); it is left
in the log as sent, un-acked, and the retry loop simply does not resume.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import state_path

log = logging.getLogger(__name__)

#: Messages kept per conversation. A chat log is a convenience, not an
#: archive -- see `addressbook.MAX_ENTRIES` for the identical reasoning.
MAX_MESSAGES_PER_CONVERSATION = 200
#: Conversations kept in total, oldest (by `last_activity`) dropped first.
MAX_CONVERSATIONS = 200

#: An APRS sender normally retries an unacknowledged message over the next
#: minute or two; a copy may also arrive through more than one RF/IGate path.
#: Keep an identical packet out of the chat history during that window, but
#: do not persist this short-lived reception state across a restart.
MESSAGE_DEDUP_SECONDS = 120.0


class MessageDeduplicator:
    """Recognize a recently repeated APRS message without doing any I/O.

    A message number alone is not enough: some services omit it, and a
    sender is allowed to reuse one later. The fingerprint therefore includes
    source, addressee, text, and number. The timestamp is intentionally not
    refreshed by a duplicate, so a genuinely new identical message can be
    shown after one bounded retry window rather than being hidden forever by
    a faulty station repeating it continuously.
    """

    def __init__(self, window_seconds: float = MESSAGE_DEDUP_SECONDS) -> None:
        self.window_seconds = window_seconds
        self._seen: dict[tuple[str, str, str, str], float] = {}

    def is_duplicate(
        self,
        source: str,
        addressee: str,
        text: str,
        number: str | None,
        *,
        now: float | None = None,
    ) -> bool:
        """Return whether this exact message was received in the recent window."""
        now = time.monotonic() if now is None else now
        key = (source.strip().upper(), addressee.strip().upper(), text, number or "")
        previous = self._seen.get(key)
        if previous is not None and now - previous < self.window_seconds:
            return True
        self._seen[key] = now
        # Bound memory even on an APRS frequency with sustained, unrelated
        # traffic. The cache is only an operational retry window, so expired
        # entries have no value after it closes.
        for old_key, seen_at in list(self._seen.items()):
            if now - seen_at >= self.window_seconds:
                del self._seen[old_key]
        return False


@dataclass(slots=True)
class MessageEntry:
    """One line of a conversation, in either direction."""

    direction: str  # "in" or "out"
    text: str
    timestamp: float = field(default_factory=time.time)
    #: The APRS message number this was sent/received with, if any -- ack
    #: and reject lines and free-text status carry `None`.
    number: str | None = None
    #: "station" | "sms" | "email" -- which compose mode produced an
    #: outgoing message; always "station" for an incoming one, since an
    #: incoming message has no compose mode of its own.
    service: str = "station"
    #: Only meaningful for `direction == "out"`: whether an ack for this
    #: message's `number` was ever seen. An incoming message is never
    #: "acked" in this sense -- kissterm's own ack of it is a separate
    #: outgoing entry, not a flag on the incoming one.
    acked: bool = False


@dataclass(slots=True)
class Conversation:
    """Every message exchanged with one callsign, most recent last."""

    callsign: str
    messages: list[MessageEntry] = field(default_factory=list)

    @property
    def last_activity(self) -> float:
        return self.messages[-1].timestamp if self.messages else 0.0


def path() -> Path:
    return state_path() / "aprs_messages.json"


class ConversationStore:
    """All conversations, persisted as JSON. Every method that touches disk
    swallows its own errors and logs them -- same rule as `AddressBook`: a
    chat history failing to save must never interrupt an in-progress send.
    """

    def __init__(self, file: Path | None = None) -> None:
        self.file = file or path()
        self.conversations: dict[str, Conversation] = {}

    # -- persistence ------------------------------------------------------
    def load(self) -> None:
        try:
            raw = json.loads(self.file.read_text("utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            log.warning("APRS message history at %s is unreadable: %s", self.file, exc)
            return
        if not isinstance(raw, dict):
            log.warning("APRS message history at %s is not a table; ignoring", self.file)
            return

        conversations: dict[str, Conversation] = {}
        for callsign, item in raw.items():
            if not isinstance(item, dict):
                continue
            messages_raw = item.get("messages", [])
            if not isinstance(messages_raw, list):
                continue
            messages: list[MessageEntry] = []
            for m in messages_raw:
                if not isinstance(m, dict):
                    continue
                direction = str(m.get("direction", ""))
                if direction not in ("in", "out"):
                    continue
                messages.append(
                    MessageEntry(
                        direction=direction,
                        text=str(m.get("text", "")),
                        timestamp=float(m.get("timestamp", 0.0) or 0.0),
                        number=(str(m["number"]) if m.get("number") is not None else None),
                        service=str(m.get("service", "station")),
                        acked=bool(m.get("acked", False)),
                    )
                )
            conversations[callsign] = Conversation(
                callsign=callsign, messages=messages[-MAX_MESSAGES_PER_CONVERSATION:]
            )
        self.conversations = conversations

    def save(self) -> None:
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                callsign: {"messages": [asdict(m) for m in convo.messages]}
                for callsign, convo in self.conversations.items()
            }
            temporary = self.file.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(data, indent=2), "utf-8")
            os.replace(temporary, self.file)
        except OSError as exc:
            log.warning("could not save APRS message history to %s: %s", self.file, exc)

    # -- the log ------------------------------------------------------------
    def _get(self, callsign: str) -> Conversation:
        callsign = callsign.strip().upper()
        convo = self.conversations.get(callsign)
        if convo is None:
            convo = Conversation(callsign=callsign)
            self.conversations[callsign] = convo
        return convo

    def record_outgoing(
        self, callsign: str, text: str, *, number: str | None, service: str = "station"
    ) -> MessageEntry:
        entry = MessageEntry(direction="out", text=text, number=number, service=service)
        self._append(callsign, entry)
        return entry

    def record_incoming(self, callsign: str, text: str, *, number: str | None) -> MessageEntry:
        entry = MessageEntry(direction="in", text=text, number=number)
        self._append(callsign, entry)
        return entry

    def forget(self, callsign: str) -> None:
        """Delete one correspondent's entire history.

        `AprsPane.clear_active`'s Ctrl+L on a conversation tab -- the chat
        equivalent of `TerminalPane.clear`'s own Ctrl+L wiping a session's
        buffer, deliberately scoped to the one conversation on screen rather
        than "All", which merges every correspondent by timestamp (see that
        method's docstring). A no-op for a callsign with no history.
        """
        if self.conversations.pop(callsign.strip().upper(), None) is not None:
            self.save()

    def clear_all(self) -> None:
        """Delete EVERY correspondent's history -- `AprsPane.clear_active`'s
        Ctrl+L on "All", requested directly: with third-party-relayed
        replies filed here as real chat rather than raw packet lines, most
        of what "All" shows is conversation content, and a clear that left
        it untouched looked unresponsive. There is no confirmation step;
        the operator pressing Clear on the one tab that shows every
        conversation at once is the confirmation.
        """
        if self.conversations:
            self.conversations = {}
            self.save()

    def mark_acked(self, callsign: str, number: str) -> bool:
        """Flag the outgoing message `number` in `callsign`'s conversation as
        acked. Returns whether a matching message was found."""
        convo = self.conversations.get(callsign.strip().upper())
        if convo is None:
            return False
        for entry in reversed(convo.messages):
            if entry.direction == "out" and entry.number == number:
                entry.acked = True
                self.save()
                return True
        return False

    def _append(self, callsign: str, entry: MessageEntry) -> None:
        convo = self._get(callsign)
        convo.messages.append(entry)
        del convo.messages[:-MAX_MESSAGES_PER_CONVERSATION]
        if len(self.conversations) > MAX_CONVERSATIONS:
            oldest = min(self.conversations.values(), key=lambda c: c.last_activity)
            if oldest is not convo:
                del self.conversations[oldest.callsign]
        self.save()


#: How long to wait for an ack before resending, and how many times to try.
#: The APRS spec does not mandate exact figures for either -- these are a
#: reasonable implementation choice, not a cited value, the same honesty
#: `mice.py` and `mail_waiting_for` apply to their own unverified constants.
DEFAULT_RETRY_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 3


@dataclass(slots=True)
class _Pending:
    text: str
    attempts: int = 0
    next_retry: float = 0.0


class PendingAcks:
    """In-memory-only tracking of outgoing messages awaiting an ack.

    Deliberately not part of `ConversationStore` or persisted -- see this
    module's docstring. Owned by `kissterm.ui.aprs_pane.AprsPane`, which is
    the only thing that both sends messages and runs a retry timer; nothing
    here does any I/O of its own, so it is testable with no transport and no
    mounted app.
    """

    def __init__(
        self,
        retry_seconds: float = DEFAULT_RETRY_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self.retry_seconds = retry_seconds
        self.max_retries = max_retries
        self._pending: dict[tuple[str, str], _Pending] = {}

    def add(self, callsign: str, number: str, text: str, *, now: float | None = None) -> None:
        """Start tracking a just-sent message. Called once, by the sender --
        never by a retry, which must not restart this message's own clock
        or it would never be allowed to expire."""
        now = now if now is not None else time.monotonic()
        key = (callsign.strip().upper(), number)
        self._pending[key] = _Pending(text=text, attempts=0, next_retry=now + self.retry_seconds)

    def discard(self, callsign: str, number: str) -> None:
        self._pending.pop((callsign.strip().upper(), number), None)

    def discard_for(self, callsign: str) -> None:
        """Drop every pending entry for `callsign`, regardless of message
        number -- used when its whole conversation is cleared
        (`ConversationStore.forget`), so a retry does not keep transmitting
        into a chat log that no longer shows the message it is resending.
        """
        callsign = callsign.strip().upper()
        for key in [k for k in self._pending if k[0] == callsign]:
            del self._pending[key]

    def clear(self) -> None:
        """Drop every pending entry, for every callsign -- the counterpart
        to `ConversationStore.clear_all`, so wiping every conversation from
        "All" does not leave a retry timer resending into a chat log with
        nothing left in it."""
        self._pending.clear()

    def discard_acked(self, store: ConversationStore) -> None:
        """Drop any pending entry the store already shows acked.

        Reconciles against `ConversationStore.mark_acked`'s effect -- the
        two classes share no direct reference to each other, so this is the
        one place that connects "an ack arrived" (the store) to "stop
        retrying" (here); called by the retry timer before `due()`.
        """
        for callsign, number in list(self._pending.keys()):
            convo = store.conversations.get(callsign)
            if convo and any(
                m.direction == "out" and m.number == number and m.acked for m in convo.messages
            ):
                del self._pending[(callsign, number)]

    def attempts_for(self, callsign: str, number: str | None) -> int | None:
        """How many times this message has been retried, or None if it is not
        awaiting an ack (never sent by us, already acked, or given up on).

        Read-only, unlike `due()` -- this exists so the conversation view can
        show an operator whether a message is still in flight without that
        display having the side effect of consuming a retry.
        """
        if number is None:
            return None
        pending = self._pending.get((callsign.strip().upper(), number))
        return None if pending is None else pending.attempts

    def due(self, *, now: float | None = None) -> list[tuple[str, str, str]]:
        """(callsign, number, text) triples due for a retry right now.

        A side effect, not just a query: every entry returned has its
        attempt count bumped and its next-retry deadline pushed out, on the
        assumption the caller is about to actually resend it -- the same
        "checked and acted on in one step" shape `TransmitGate.allow()`
        uses. An entry that has already used up `max_retries` is dropped
        (left un-acked in the conversation log, per this module's
        docstring) rather than returned again.
        """
        now = now if now is not None else time.monotonic()
        due: list[tuple[str, str, str]] = []
        for key, pending in list(self._pending.items()):
            if now < pending.next_retry:
                continue
            if pending.attempts >= self.max_retries:
                del self._pending[key]
                continue
            pending.attempts += 1
            pending.next_retry = now + self.retry_seconds
            due.append((key[0], key[1], pending.text))
        return due
