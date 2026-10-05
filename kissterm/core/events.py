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
from dataclasses import dataclass

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
