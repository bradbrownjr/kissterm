"""One message as a plain-text file: `Key: value` headers, a blank line, body.

The file is the message. There is no database behind it, because a mailbox
only this app can read is a bad bargain for an emergency tool (ROADMAP P2,
P9): an operator with nothing but a text editor can read, write or recover
any message. The format is deliberately the shape of an email header block
without claiming to be RFC 5322 -- no folding, no encoded words -- so that a
parser bug can never hide a message.

Header values are single lines. `format_message` strips CR/LF out of every
value, so a subject that arrived with an embedded newline can never forge a
second header or end the header block early. Keys this module does not know
are kept in `Message.extra` and written back unchanged, so a later version
(or the operator) can add fields without an older one dropping them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..ansi import decode_text

#: Header order on write. Anything in `Message.extra` follows, sorted.
_KNOWN = (
    "From",
    "To",
    "Subject",
    "Date",
    "Message-Id",
    "Kind",
    "Category",
    "Expires",
    "Status",
    "Deleted-From",
)

_HEADER_RE = re.compile(r"^([A-Za-z][A-Za-z0-9-]*):[ \t]?(.*)$")
_LINE_BREAKS_RE = re.compile(r"[\r\n]+")

KIND_MAIL = "mail"
KIND_BULLETIN = "bulletin"

STATUS_NEW = "new"
STATUS_READ = "read"


@dataclass
class Message:
    """A message's headers and body. Every field is optional on read.

    `kind` is "mail" or "bulletin". A bulletin is addressed to a `category`
    (WX, ARES, ALL) rather than a person and may carry `expires`; ROADMAP P2
    asks for both to be modelled from the start rather than bolted on.
    `deleted_from` is set only while the message sits in a Deleted folder
    and says where Restore puts it back.
    """

    sender: str = ""
    to: str = ""
    subject: str = ""
    date: datetime | None = None
    message_id: str = ""
    kind: str = KIND_MAIL
    category: str = ""
    expires: datetime | None = None
    status: str = STATUS_NEW
    deleted_from: str = ""
    body: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def is_read(self) -> bool:
        return self.status == STATUS_READ

    def expired(self, now: datetime | None = None) -> bool:
        """True once a bulletin's `expires` has passed. Mail never expires."""
        if self.expires is None:
            return False
        return (now or datetime.now(timezone.utc)) >= self.expires


def _one_line(value: str) -> str:
    return _LINE_BREAKS_RE.sub(" ", value).strip()


def _format_date(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(text: str) -> datetime | None:
    """An ISO 8601 date, or None. A naive time is taken as UTC."""
    text = text.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def format_message(message: Message) -> str:
    """The file text for `message`. Empty headers are left out."""
    values = {
        "From": message.sender,
        "To": message.to,
        "Subject": message.subject,
        "Date": _format_date(message.date),
        "Message-Id": message.message_id,
        "Kind": message.kind if message.kind != KIND_MAIL else "",
        "Category": message.category,
        "Expires": _format_date(message.expires),
        "Status": message.status if message.status != STATUS_NEW else "",
        "Deleted-From": message.deleted_from,
    }
    lines = [f"{key}: {_one_line(values[key])}" for key in _KNOWN if _one_line(values[key])]
    known = {k.lower() for k in _KNOWN}
    for key in sorted(message.extra):
        if key.lower() in known or not _HEADER_RE.match(f"{key}:"):
            continue
        value = _one_line(message.extra[key])
        if value:
            lines.append(f"{key}: {value}")
    body = message.body.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(lines) + "\n\n" + body


def parse_message(data: bytes | str) -> Message:
    """Read a message file. Never raises on content.

    A file whose first line is not a header (an operator's own note dropped
    into a folder) is all body. Decoding follows the rest of the app:
    UTF-8 when valid, latin-1 when not (`ansi.decode_text`).
    """
    text = decode_text(data) if isinstance(data, bytes) else data
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    headers: dict[str, str] = {}
    lines = text.split("\n")
    body_start = 0
    for index, line in enumerate(lines):
        if line == "":
            body_start = index + 1
            break
        match = _HEADER_RE.match(line)
        if match is None:
            # Not a header block after all: keep everything as body.
            headers = {}
            body_start = 0
            break
        headers[match.group(1)] = match.group(2).strip()
    else:
        # Headers with no blank line and no body.
        body_start = len(lines)

    lower = {k.lower(): v for k, v in headers.items()}
    known = {k.lower() for k in _KNOWN}
    return Message(
        sender=lower.get("from", ""),
        to=lower.get("to", ""),
        subject=lower.get("subject", ""),
        date=parse_date(lower.get("date", "")),
        message_id=lower.get("message-id", ""),
        kind=lower.get("kind", "") or KIND_MAIL,
        category=lower.get("category", ""),
        expires=parse_date(lower.get("expires", "")),
        status=lower.get("status", "") or STATUS_NEW,
        deleted_from=lower.get("deleted-from", ""),
        body="\n".join(lines[body_start:]),
        extra={k: v for k, v in headers.items() if k.lower() not in known},
    )
