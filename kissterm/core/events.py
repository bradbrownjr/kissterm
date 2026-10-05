"""Domain events the core publishes, and the bus that carries them.

**Events carry meaning, not screen text.** A front end decides how a
transport going down or the gate opening looks; the core only says that it
happened. That is what lets a phone show a red chip where the terminal UI
shows `TX OFF` in its status bar (ROADMAP P7a, goal B).

**Every event gets a sequence number** from the bus, in publication order.
A remote client that slept (a phone with its screen off) reconnects and
asks for what it missed by number instead of reloading everything; the
journal that serves those requests arrives with the WebSocket server.

**A subscriber that raises never stops the others** or the publisher: the
core's flows must not fail because one client's handler did (AGENTS.md
"Untrusted input": never let an error raise out of a background task).
Delivery is synchronous, on the publisher's loop, so a subscriber sees
state that is still current; one that needs to wait schedules its own task.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Event:
    """Base class. Subclasses are plain data a client can serialize."""


@dataclass(frozen=True, slots=True)
class TransportChanged(Event):
    """A transport was opened, switched to, or failed to open.

    `tier` is `"frame"` (KISS, AGWPE: kissterm's own AX.25 runs on it),
    `"session"` (Telnet, SSH, VARA...: already-connected byte streams), or
    `""` with no transport. `detail` is the transport's own description.
    """

    name: str
    tier: str
    detail: str


@dataclass(frozen=True, slots=True)
class GateChanged(Event):
    """The transmit gate opened or closed (`kissterm/tx.py`)."""

    enabled: bool


Subscriber = Callable[[int, Event], None]


class EventBus:
    """Synchronous fan-out with sequence numbers."""

    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []
        #: Sequence number of the last event published; 0 before any.
        self.seq = 0

    def subscribe(self, subscriber: Subscriber) -> Callable[[], None]:
        """Register `subscriber(seq, event)`; returns an unsubscribe callable."""
        self._subscribers.append(subscriber)

        def _remove() -> None:
            try:
                self._subscribers.remove(subscriber)
            except ValueError:
                pass

        return _remove

    def publish(self, event: Event) -> int:
        """Number `event` and hand it to every subscriber. Returns its number."""
        self.seq += 1
        seq = self.seq
        for subscriber in list(self._subscribers):
            try:
                subscriber(seq, event)
            except Exception:  # noqa: BLE001 - one client must not stop the rest
                log.exception("event subscriber failed on %r", event)
        return seq


# ----------------------------------------------------------------------
# Sessions (`sessions.py`). `key` names the session (`connect.session_key`);
# "" is the session tier's one session and the pre-connection view.
# ----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SessionOpened(Event):
    """A link was bound to session `key`. `activate` asks a client to show
    it; `incoming` means the far station called, and a client that already
    shows another session decides itself whether to switch (never steal
    the view) -- `activate` is then a suggestion it may ignore."""

    key: str
    peer: str
    activate: bool = True
    incoming: bool = False


@dataclass(frozen=True, slots=True)
class SessionData(Event):
    """Bytes the far end sent on `key`, raw. A client filters them before
    showing them (AGENTS.md "Untrusted input"); never display them as-is."""

    key: str
    data: bytes


@dataclass(frozen=True, slots=True)
class LineSent(Event):
    """A line went out on `key`, as it should be shown (a password already
    masked). Typed lines, auto-login lines, hop and harvest commands."""

    key: str
    text: str


@dataclass(frozen=True, slots=True)
class SessionStateChanged(Event):
    """The link under `key` changed state (`transport.base.SessionState`
    value: "connected", "disconnected", ...)."""

    key: str
    state: str


@dataclass(frozen=True, slots=True)
class SessionUpdated(Event):
    """What is known about `key` changed: the node family identified, an
    application entered or left, a hop committed, a transcript opened or
    closed. A client re-reads the session."""

    key: str


@dataclass(frozen=True, slots=True)
class SessionClosed(Event):
    """Session `key` was closed and forgotten."""

    key: str


@dataclass(frozen=True, slots=True)
class ConnectingChanged(Event):
    """A connect attempt started or ended (what a disconnect can cancel)."""


@dataclass(frozen=True, slots=True)
class ActivityChanged(Event):
    """A job the operator started says how far it has got ("Reading the
    command list"); "" when it is over."""

    text: str


# ----------------------------------------------------------------------
# APRS (`kissterm/core/aprs.py`)
# ----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class AprsMessage(Event):
    """A person-to-person message from `correspondent` was recorded in the
    conversation store. `to_me` decides whether a client opens it and marks
    it unread; one not to me is only recorded."""

    correspondent: str
    to_me: bool


@dataclass(frozen=True, slots=True)
class AprsAcked(Event):
    """`correspondent` acknowledged our message `number`."""

    correspondent: str
    number: str


@dataclass(frozen=True, slots=True)
class AprsPacketHeard(Event):
    """A decoded APRS packet that is not a message (position, weather,
    status, telemetry, object): `line` is `aprs.format_packet`'s text, `at`
    the epoch time, `packet` the decoded `aprs.AprsPacket`."""

    line: str
    at: float
    packet: object = field(compare=False)


@dataclass(frozen=True, slots=True)
class AprsBulletinHeard(Event):
    """A BLNn/ANn channel announcement from `source`."""

    source: str
    addressee: str
    text: str
    at: float


@dataclass(frozen=True, slots=True)
class AprsRetried(Event):
    """The retry check ran: an ack may have landed or a retry gone out, so
    the outgoing status of a conversation may have changed."""


@dataclass(frozen=True, slots=True)
class Alert(Event):
    """Something worth an unattended alert beyond a notice (a desktop
    notification, a phone push): an APRS emergency, a message to me."""

    title: str
    body: str
    urgent: bool
