"""Writing a BBS message: checks, reply quoting, and the send command.

ROADMAP P2 "Compose and Outbox". A composed message is an ordinary
`Message` in Mail/BBS/Outbox; nothing here transmits. The send headers in
`Message.extra` say how it goes out when Send/Receive sends the Outbox:

- `Send-Type`: `P` private, `B` bulletin, `T` NTS traffic (a radiogram,
  `radiogram_message`; its `To` is the ZIP and `Send-At` is `NTS<state>`).
- `Send-At`: the `@` part, or "" to let BPQMail add it from the
  recipient's Home BBS ("Address @... added from HomeBBS").
- `Reply-Number`, `Reply-Source`: set on a reply to a message read from a
  BBS. `send_command` uses `SR <number>` only when the BBS it is talking
  to is that source: the number means nothing anywhere else.

**The checks are BPQMail's own limits** (researched from the LinBPQ source
and confirmed on air; see `bpqmail.py`'s docstring), made before saving so
a message is never refused halfway through a send on a slow link:

- TO is at most 6 characters and has no SSID (BPQMail cuts both off
  silently, which would deliver to the wrong call); `@` at most 40.
- A title of 1 to 60 characters: an empty title cancels the send on the
  BBS, and anything past 60 is cut.
- **No body line that ends the text early**: `/ex` in any case, or a line
  starting with Ctrl-Z. BPQMail would take the rest as commands.

Quoting is the operator's choice, never forced: Q always quotes, R quotes
only when Settings > Mail says so (off by default -- every quoted line is
airtime). The quote is ordinary body text, editable like the rest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .message import Message
from .store import MAIL
from .store import OUTBOX as _OUTBOX

#: Where a composed BBS message waits to be sent.
BBS_OUTBOX = f"{MAIL}/BBS/{_OUTBOX}"

SEND_PRIVATE = "P"
SEND_BULLETIN = "B"
SEND_TRAFFIC = "T"

#: BPQMail's limits (`BBSUtilities.c`, `DoSendCommand` / `CreateMessage`).
MAX_TO = 6
MAX_AT = 40
MAX_TITLE = 60

_TO_RE = re.compile(r"^[A-Z0-9]+$")
_AT_RE = re.compile(r"^[A-Z0-9.#-]+$")
#: C0 controls other than tab and newline; a pasted body can carry them.
_CONTROLS_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


@dataclass
class Draft:
    """A message written elsewhere (a form) for the compose screen to
    address and save. `form_id` is kept as the `Form:` header so the
    message can be found as that form later (and, with Winlink, carry
    its XML)."""

    to: str = ""
    at: str = ""
    title: str = ""
    body: str = ""
    send_type: str = SEND_PRIVATE
    form_id: str = ""
    form_values: dict[str, Any] = field(default_factory=dict)


def clean_text(text: str) -> str:
    """Tabs to spaces, CRLF and CR to LF, other control characters out."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    return _CONTROLS_RE.sub("", text)


def ends_text_early(line: str) -> bool:
    """True for a line BPQMail would take as the end of the message."""
    return line.strip().lower() == "/ex" or line.startswith("\x1a")


def check(to: str, at: str, title: str, body: str, *, reply_by_number: bool = False) -> list[str]:
    """What stops this message from being saved, in the operator's words.

    `reply_by_number` skips the TO and title checks: an `SR` reply is
    addressed and titled by the BBS.
    """
    problems: list[str] = []
    to = to.strip().upper()
    at = at.strip().upper()
    if not reply_by_number:
        if not to:
            problems.append("To is empty.")
        elif "-" in to:
            problems.append("To must not have an SSID: BPQMail drops it (KC1JMH, not KC1JMH-7).")
        elif not _TO_RE.match(to):
            problems.append("To takes letters and digits only.")
        elif len(to) > MAX_TO:
            problems.append(f"To is at most {MAX_TO} characters on BPQMail.")
        if not title.strip():
            problems.append("Title is empty: the BBS would cancel the message.")
        elif len(title.strip()) > MAX_TITLE:
            problems.append(f"Title is at most {MAX_TITLE} characters on BPQMail.")
    if at:
        if not _AT_RE.match(at):
            problems.append("@ takes letters, digits, dots and # only (W1BKW.#OXFO.ME.USA.NOAM).")
        elif len(at) > MAX_AT:
            problems.append(f"@ is at most {MAX_AT} characters on BPQMail.")
    if not body.strip():
        problems.append("The message has no text.")
    for number, line in enumerate(body.split("\n"), 1):
        if ends_text_early(line):
            problems.append(
                f"Line {number} would end the message on the BBS ({line.strip()!r}). "
                "Change it, for example put a space or a word before it."
            )
            break
    return problems


def reply_title(subject: str) -> str:
    """BPQMail's own `SR` title: `Re:` and the original, cut to 60."""
    subject = subject.strip()
    if not subject.lower().startswith("re:"):
        subject = f"Re:{subject}"
    return subject[:MAX_TITLE]


def quote(original: Message) -> str:
    """The original as `> ` lines under an attribution line."""
    when = original.date.strftime("%Y-%m-%d %H:%MZ") if original.date else "an earlier message"
    lines = original.body.rstrip("\n").split("\n")
    quoted = "\n".join(f"> {line}".rstrip() for line in lines)
    who = original.sender or "the sender"
    return f"On {when}, {who} wrote:\n{quoted}\n"


def outbox_message(
    *,
    sender: str,
    to: str,
    at: str,
    title: str,
    body: str,
    send_type: str = SEND_PRIVATE,
    reply_to: Message | None = None,
    now: datetime | None = None,
    form_id: str = "",
) -> Message:
    """The message as filed in the Outbox, send headers included."""
    extra = {"Send-Type": send_type}
    if form_id:
        extra["Form"] = form_id
    if at.strip():
        extra["Send-At"] = at.strip().upper()
    if reply_to is not None and reply_to.extra.get("Bbs-Number"):
        extra["Reply-Number"] = reply_to.extra["Bbs-Number"]
        extra["Reply-Source"] = reply_to.source
    return Message(
        sender=sender.upper(),
        to=to.strip().upper(),
        subject=clean_text(title).strip()[:MAX_TITLE],
        date=now or datetime.now(timezone.utc),
        body=clean_text(body).rstrip("\n") + "\n",
        extra=extra,
    )


def can_reply_by_number(original: Message) -> bool:
    """A message read from a BBS, so `SR <number>` can answer it there."""
    return bool(original.extra.get("Bbs-Number")) and original.source.startswith("BBS ")


def send_command(message: Message, bbs_source: str) -> tuple[str, bool]:
    """The line that starts this message on the BBS, and whether the BBS
    will ask for a title.

    `bbs_source` is the connected BBS as a `Source:` value (`BBS WS1EC`).
    A reply uses `SR <n>` only on the BBS its number came from; anywhere
    else it goes out as an ordinary `SP` to the sender.
    """
    number = message.extra.get("Reply-Number", "")
    if number and message.extra.get("Reply-Source", "") == bbs_source:
        return f"SR {number}", False
    send_type = message.extra.get("Send-Type", SEND_PRIVATE)
    line = f"S{send_type} {message.to}"
    at = message.extra.get("Send-At", "")
    if at:
        line += f" @ {at}"
    return line, True


def radiogram_message(gram, sender: str) -> Message:
    """A filled `nts.Radiogram` as an Outbox message: `ST <zip> @ NTS<st>`
    titled with its `subject()`. `Nts-Number` and
    `Nts-Place` let the next radiogram suggest its number and place."""
    to, at = gram.routing()
    return Message(
        sender=sender.upper(),
        to=to,
        subject=gram.subject(),
        date=datetime.now(timezone.utc),
        body=gram.body(),
        extra={
            "Send-Type": SEND_TRAFFIC,
            "Send-At": at,
            "Nts-Number": gram.number.strip(),
            "Nts-Place": gram.place.strip().upper(),
            **({"Form": "radiogram_ics213"} if gram.ics213 else {}),
        },
    )


def radiogram_defaults(store) -> tuple[str, str]:
    """The next radiogram's number and place of origin, from the ones in
    the BBS Outbox and Sent: one past the highest number used, and the
    newest place (so a station numbering its traffic keeps counting)."""
    from .nts import next_number
    from .store import SENT

    numbers: list[str] = []
    place, newest = "", None
    for folder in (BBS_OUTBOX, f"{MAIL}/BBS/{SENT}"):
        for summary in store.list(folder):
            if not (summary.to.isdigit() and len(summary.to) == 5):
                continue  # an ST message is addressed to a ZIP
            try:
                message = store.read(summary.ref)
            except (OSError, ValueError):
                continue
            if message.extra.get("Send-Type") != SEND_TRAFFIC:
                continue
            numbers.append(message.extra.get("Nts-Number", ""))
            if message.extra.get("Nts-Place") and (newest is None or (summary.date and summary.date > newest)):
                place, newest = message.extra["Nts-Place"], summary.date
    return next_number(numbers), place
