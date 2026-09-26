"""One Winlink message in B2 format: headers, body, attachments.

This is what travels, LZHUF-compressed, in a B2F exchange, and what is
kept beside a filed message as its raw `.b2f` copy (`mail/store.py`):

    Mid: LPE5NXDVLVSQ              <- always first
    Body: 104                      <- the body's size in bytes
    Date: 2016/07/20 19:21         <- UTC, YYYY/MM/DD HH:MM
    File: 31028 1469042410710.jpg  <- one per attachment: size, name
    From: LA5NTA
    Mbo: LA5NTA                    <- the mailbox that created it
    Subject: 73 fra Brekke
    To: LA4TTA                     <- repeated per recipient; Cc likewise
    Type: Private
                                   <- CRLF: end of headers
    <Body bytes>                   <- then, if there are files, CRLF,
    <file bytes> CRLF ...          <- and each file followed by CRLF

Every line ends in CRLF. Headers after Mid are written sorted by name, so
the same message always gives the same bytes. The body is ISO-8859-1 with
CRLF line ends, no line over 998 characters; a subject or file name
outside ASCII is RFC 2047 Q-encoded. On read, a header that is not an
encoded word may be UTF-8 or ISO-8859-1 (wl2k-go: "it turns out that if
CMS receives a Q-encoded subject it decodes it and forwards it as
UTF-8"), so both are accepted. Dates are read in the layouts wl2k-go has
met in the wild (RMS Relay's `2016.12.30`, old BPQ's `20161230010000`,
RFC 5322).

An address is a callsign (`LA5NTA`, upper-cased; `LA5NTA@winlink.org` is
the same) or an Internet address, which Winlink writes `SMTP:foo@bar.baz`.

**MID**: twelve characters, base32 of an MD5 over the time and callsign,
unique per message and the key the CMS uses to refuse duplicates.

**Sources.** wl2k-go `fbb/message.go`, `header.go`, `message_body.go`,
`mid.go` (MIT, LA5NTA), and its test data: `LPE5NXDVLVSQ.b2f`, a real
message, parses and writes back byte for byte
(`tests/unit/test_winlink_message.py`).
# UNVERIFIED: a message we build has not yet been accepted by a CMS; the
# first Winlink session keeps its transcript as a fixture (ON-AIR-TESTS).
"""

from __future__ import annotations

import base64
import email.errors
import email.header
import email.utils
import hashlib
import os
import quopri
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..mail.message import Message

MID_LENGTH = 12
MAX_SUBJECT = 128
MAX_FILENAME = 255
#: RFC 5322's line limit, less the CRLF.
_MAX_LINE = 998
CHARSET = "ISO-8859-1"
DATE_LAYOUT = "%Y/%m/%d %H:%M"
#: Layouts met in the wild, after the documented one (wl2k-go `dateLayouts`).
_DATE_LAYOUTS = (DATE_LAYOUT, "%Y.%m.%d %H:%M", "%Y-%m-%d %H:%M", "%Y%m%d%H%M%S")
#: What a filed Winlink message says it came from (`Message.source`).
SOURCE = "Winlink"

_CRLF = b"\r\n"
_CHARSET_RE = re.compile(r'charset\s*=\s*"?([A-Za-z0-9_.:-]+)"?', re.IGNORECASE)


class B2Error(ValueError):
    """Bytes that are not a B2 message, or a message that cannot be sent."""


@dataclass
class B2Message:
    """A B2 message as it travels. `headers` keeps order and repeats (To,
    Cc, File); values are the header text as sent, decoded ISO-8859-1 so no
    byte is lost. The helper properties decode what a person reads."""

    headers: list[tuple[str, str]] = field(default_factory=list)
    body: bytes = b""
    files: list[tuple[str, bytes]] = field(default_factory=list)

    def get(self, key: str) -> str:
        key = _canonical(key)
        return next((v for k, v in self.headers if k == key), "")

    def get_all(self, key: str) -> list[str]:
        key = _canonical(key)
        return [v for k, v in self.headers if k == key]

    @property
    def mid(self) -> str:
        return self.get("Mid")

    @property
    def sender(self) -> str:
        return address(self.get("From"))

    @property
    def to(self) -> list[str]:
        return [address(a) for a in self.get_all("To")]

    @property
    def cc(self) -> list[str]:
        return [address(a) for a in self.get_all("Cc")]

    @property
    def subject(self) -> str:
        return decode_header(self.get("Subject"))

    @property
    def date(self) -> datetime | None:
        return parse_date(self.get("Date"))

    @property
    def text(self) -> str:
        """The body as text, in its declared charset (ISO-8859-1 if none)."""
        match = _CHARSET_RE.search(self.get("Content-Type"))
        charset = match.group(1) if match else CHARSET
        try:
            text = self.body.decode(charset)
        except (LookupError, UnicodeDecodeError):
            text = self.body.decode("latin-1")
        return text.replace("\r\n", "\n")


def _canonical(key: str) -> str:
    """`content-type` -> `Content-Type`, as Go's textproto does."""
    return "-".join(part[:1].upper() + part[1:].lower() for part in key.strip().split("-"))


def address(text: str) -> str:
    """A recipient as Winlink writes it: `LA5NTA` for a Winlink account
    (upper-cased, `@winlink.org` dropped), `SMTP:user@host` for anything
    else with an `@`, and `PROTO:addr` kept as it is."""
    text = text.strip()
    if text.count(":") == 1:
        return text
    if "@" not in text:
        return text.upper()
    user, _, host = text.partition("@")
    if host.lower() == "winlink.org":
        return user.upper()
    return f"SMTP:{text}"


def parse_date(text: str) -> datetime | None:
    """A B2 `Date:` value as UTC, or None if it is empty or unreadable."""
    text = text.strip()
    if not text:
        return None
    for layout in _DATE_LAYOUTS:
        try:
            return datetime.strptime(text, layout).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        value = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def decode_header(value: str) -> str:
    """A subject or file name as a person reads it: RFC 2047 words decoded,
    and otherwise UTF-8 when the bytes are UTF-8, else ISO-8859-1."""
    if "=?" in value:
        try:
            parts = email.header.decode_header(value)
        except (ValueError, email.errors.HeaderParseError):
            return value
        out = []
        for part, charset in parts:
            if isinstance(part, str):
                out.append(part)
                continue
            try:
                out.append(part.decode(charset or "latin-1"))
            except (LookupError, UnicodeDecodeError):
                out.append(part.decode("latin-1"))
        return "".join(out)
    raw = value.encode("latin-1", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return value


def encode_header(text: str) -> str:
    """`text` as a header value: as it is when printable ASCII, else a
    Q-encoded word (ISO-8859-1 when it fits, UTF-8 when it does not)."""
    text = " ".join(text.split())
    if all(32 <= ord(c) < 127 for c in text) and "=?" not in text:
        return text
    try:
        raw, charset = text.encode("latin-1"), CHARSET
    except UnicodeEncodeError:
        raw, charset = text.encode("utf-8"), "UTF-8"
    encoded = quopri.encodestring(raw, header=True).decode("ascii")
    encoded = encoded.replace("?", "=3F").replace("\t", "=09").replace("=\n", "")
    return f"=?{charset}?q?{encoded}?="


def body_bytes(text: str) -> bytes:
    """A body as B2 carries it: CRLF after every line, no line over 998
    characters, ISO-8859-1 (a character outside it becomes `?`)."""
    lines: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        while len(line) > _MAX_LINE:
            lines.append(line[:_MAX_LINE])
            line = line[_MAX_LINE:]
        lines.append(line)
    if lines and lines[-1] == "":
        lines.pop()  # the text's own final newline
    return "".join(f"{line}\r\n" for line in lines).encode("latin-1", errors="replace")


def generate_mid(callsign: str, now: datetime | None = None) -> str:
    """A new twelve-character MID. The random part makes two messages
    written in the same instant differ."""
    now = now or datetime.now(timezone.utc)
    payload = f"{now.isoformat()}-{callsign.upper()}-{os.urandom(8).hex()}".encode()
    return base64.b32encode(hashlib.md5(payload).digest()).decode("ascii")[:MID_LENGTH]


def build(
    *,
    sender: str,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    files: list[tuple[str, bytes]] | None = None,
    mid: str = "",
    date: datetime | None = None,
    mbo: str = "",
    kind: str = "Private",
) -> B2Message:
    """A new message, ready to `serialize`. Raises `B2Error` with every
    problem, in the operator's words, if it could not be sent."""
    files = files or []
    data = body_bytes(body)
    problems = check(sender=sender, to=[*to, *(cc or [])], subject=subject, body=data,
                     mid=mid or "X", files=files)
    if problems:
        raise B2Error(" ".join(problems))
    headers = [
        ("Mid", mid or generate_mid(sender)),
        ("Body", str(len(data))),
        ("Content-Transfer-Encoding", "8bit"),
        ("Content-Type", f"text/plain; charset={CHARSET}"),
        ("Date", (date or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime(DATE_LAYOUT)),
        ("From", address(sender)),
        ("Mbo", (mbo or sender).upper()),
        ("Subject", encode_header(subject)),
        ("Type", kind),
    ]
    headers += [("To", address(a)) for a in to]
    headers += [("Cc", address(a)) for a in cc or []]
    headers += [("File", f"{len(content)} {encode_header(name)}") for name, content in files]
    return B2Message(headers, data, list(files))


def check(*, sender: str, to: list[str], subject: str, body: bytes, mid: str,
          files: list[tuple[str, bytes]]) -> list[str]:
    """What stops a message from being sent (wl2k-go `Validate`)."""
    problems: list[str] = []
    if not mid or len(mid) > MID_LENGTH:
        problems.append(f"The message ID must be 1 to {MID_LENGTH} characters.")
    if not [a for a in to if a.strip()]:
        problems.append("There is no recipient.")
    if not sender.strip():
        problems.append("From is empty.")
    if not body:
        problems.append("The message has no text.")
    if not subject.strip():
        problems.append("Subject is empty.")
    elif len(encode_header(subject)) > MAX_SUBJECT:
        problems.append(f"Subject is at most {MAX_SUBJECT} characters on Winlink.")
    for name, _ in files:
        if not name or len(name) > MAX_FILENAME:
            problems.append(f"Attachment name must be 1 to {MAX_FILENAME} characters: {name!r}.")
    return problems


def serialize(message: B2Message) -> bytes:
    """The message's bytes: Mid first, the other headers sorted by name
    (a stable sort, so repeated To lines keep their order)."""
    if not message.mid:
        raise B2Error("a B2 message needs a Mid")
    rest = sorted(((k, v) for k, v in message.headers if k != "Mid"), key=lambda kv: kv[0])
    out = bytearray(f"Mid: {message.mid}\r\n".encode("latin-1"))
    for key, value in rest:
        out += f"{key}: {' '.join(value.split())}\r\n".encode("latin-1", errors="replace")
    out += _CRLF
    out += message.body
    if message.files:
        out += _CRLF
    for _, content in message.files:
        out += content + _CRLF
    return bytes(out)


def parse(data: bytes) -> B2Message:
    """Read a B2 message. Raises `B2Error` if the headers are missing or a
    section is shorter than its header says."""
    data = data.lstrip(b" \t\r\n\v\f")
    end = data.find(b"\r\n\r\n")
    if end < 0 or not data:
        raise B2Error("no end of headers")
    headers: list[tuple[str, str]] = []
    for raw in data[:end].split(b"\r\n"):
        line = raw.decode("latin-1")
        if line[:1] in (" ", "\t") and headers:
            key, value = headers[-1]
            headers[-1] = (key, f"{value} {line.strip()}")
            continue
        key, sep, value = line.partition(":")
        if not sep or not key.strip():
            raise B2Error(f"not a header line: {line[:40]!r}")
        headers.append((_canonical(key), value.strip()))
    message = B2Message(headers)
    if not message.mid:
        raise B2Error("no Mid header")
    position = end + 4

    def section(size: int) -> bytes:
        nonlocal position
        chunk = data[position:position + size]
        if len(chunk) != size:
            raise B2Error("message is shorter than its headers say")
        position += size
        tail = data[position:position + 2]
        if tail and tail != _CRLF:
            raise B2Error("unexpected end of section")
        position += len(tail)
        return chunk

    try:
        message.body = section(int(message.get("Body") or 0))
        for value in message.get_all("File"):
            size, _, name = value.partition(" ")
            message.files.append((decode_header(name), section(int(size))))
    except ValueError as exc:
        raise B2Error(f"bad size header: {exc}") from None
    return message


def to_mail(message: B2Message) -> Message:
    """The message as the Mail store files it (the raw bytes are kept
    beside it as `<stem>.b2f`)."""
    extra: dict[str, str] = {}
    if message.cc:
        extra["Cc"] = ", ".join(message.cc)
    if message.get("Mbo"):
        extra["Mbo"] = message.get("Mbo")
    if message.get("Type") and message.get("Type") != "Private":
        extra["Winlink-Type"] = message.get("Type")
    if message.files:
        extra["Attachments"] = ", ".join(f"{name} ({len(content)} bytes)" for name, content in message.files)
    return Message(
        sender=message.sender,
        to=", ".join(message.to),
        subject=message.subject,
        date=message.date,
        message_id=message.mid,
        source=SOURCE,
        body=message.text,
        extra=extra,
    )
