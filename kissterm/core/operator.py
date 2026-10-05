"""The `Operator` port: the core's only view of a user interface.

**Why a port and not calls into the UI.** kissterm is to have more than one
front end -- the Textual terminal UI, and later a WebSocket API that a
phone, desktop or browser client drives (ROADMAP P7a). The core's flows
(open a transport, connect, Send/Receive) must therefore never touch a
widget. Where a flow needs to tell the operator something it calls
`notice()`; where it needs a decision -- the frequency reminder, a hop to
confirm, a login -- it awaits `ask()` with a typed `Question`. Each front
end implements this protocol its own way: Textual's adapter turns a notice
into a toast and a question into `push_screen_wait`; a WebSocket adapter
sends a `prompt` event and waits for the matching `answer`, so a phone
draws it as a native sheet.

**Questions are data, not screens**, so every client can render them
natively. A client never arms the transmit gate by command: the core arms it
itself after a confirming answer to a question it asked (see `kissterm/tx.py`
and AGENTS.md "The transmit gate"). An `ask()` that returns None means
"cancelled" and must leave the flow having transmitted nothing.

`NullOperator` is the stand-in with nobody present (tests, a core with no
client attached): every question is declined, so nothing that needs a
confirmation can happen, and notices go to the log.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

log = logging.getLogger(__name__)


class Severity(StrEnum):
    """How loudly a notice is shown. Values match Textual's severities."""

    INFORMATION = "information"
    WARNING = "warning"
    ERROR = "error"


#: The shortest time a notice may ask to stay up (DESIGN.md section 6;
#: operator, 2026-10-02: pairs of 4-second toasts "went by too fast to
#: read"). Enforced here, so it holds for every client.
MIN_NOTICE_SECONDS = 10


@dataclass(frozen=True, slots=True)
class Notice:
    """Something the operator should be told, with no answer expected.

    `timeout` is a request in seconds, at least `MIN_NOTICE_SECONDS` (None:
    the client's default, which is no shorter); `title` is optional. Text
    is plain and already sanitized -- a notice is kissterm's own words,
    never remote bytes.
    """

    text: str
    severity: Severity = Severity.INFORMATION
    title: str = ""
    timeout: float | None = None

    def __post_init__(self) -> None:
        if self.timeout is not None and self.timeout < MIN_NOTICE_SECONDS:
            raise ValueError(
                f"a notice stays up at least {MIN_NOTICE_SECONDS}s, not {self.timeout}")


@dataclass(frozen=True, slots=True)
class Question:
    """Base for every decision the core asks the operator for.

    Concrete questions subclass this with the fields a client needs to draw
    them; the answer type is documented on each subclass.
    """


class Operator(Protocol):
    """What a front end provides to the core."""

    def notice(self, notice: Notice) -> None: ...

    async def ask(self, question: Question) -> Any | None: ...


class NullOperator:
    """No one is there: decline every question, log every notice."""

    def notice(self, notice: Notice) -> None:
        level = {
            Severity.ERROR: logging.ERROR,
            Severity.WARNING: logging.WARNING,
        }.get(notice.severity, logging.INFO)
        from .wording import neutral

        log.log(level, "notice: %s", neutral(notice.text))

    async def ask(self, question: Question) -> Any | None:
        log.info("question declined, no operator: %r", question)
        return None
