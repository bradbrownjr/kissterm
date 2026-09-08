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

**Pending-ack/retry bookkeeping is deliberately NOT here.** Which outgoing
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
