"""Delivery and read receipts, the way Outpost does them (ROADMAP P11).

Outpost Packet Message Manager lets a sender ask the receiving Outpost
station to answer when a private message was *downloaded* (a Delivery
Receipt) and when it was *opened* (a Read Receipt). It is a convention in
the message text and title, not a BBS feature, so a plain BBS and a client
that does not know it just show the text. Sources: the Outpost 3.7 Users
Guide, section 6.8 and 8.5 (outpostpm.org/docs/OutpostUserBasics.pdf), and
`message/payload/outpost.go`, `message/receipt/delivrcpt.go` and
`readrcpt.go` in github.com/rothskeller/packet (v4), a client written to
interoperate with Outpost, with its test message `wppsvr/analyze/testdata/
invalid/delivrcpt.yaml`. Read both, per AGENTS.md; no capture from a real
Outpost station has been seen:

- A request is a flag at the very start of the body, `!RDR!` (delivery)
  and `!RRR!` (read), joined to the first line with no newline, after an
  optional `!URG!`. (`!B64!` marks a Base64 body; kissterm does not decode
  it, so a body that starts with it is left alone.)
- The answer is a new private message to the original sender. Delivery:
  title `DELIVERED: <original title>`, body::

      !LMI!<local id>!DR!<MM/DD/YYYY HH:MM>
      Your Message
      To: <the original's To>
      Subject: <the original's title>
      was delivered on <MM/DD/YYYY HH:MM>
      Recipient's Local Message ID: <local id>

  Read: title `READ: <original title>`, body::

      !RR!<MM/DD/YYYY HH:MM>
      Your Message

      To: <the original's To>
      Subject: <the original's title>

      was read on <MM/DD/YYYY HH:MM>

# UNVERIFIED: the local id is ours (the station's prefix, the BBS message
# number and P); Outpost fills it with its own numbering and only passes it
# back. Times are the station's local time; nothing in the sources says
# otherwise.

**Nothing here transmits.** kissterm queues a receipt in the BBS Outbox
and it goes with the operator's next Send/Receive (see
`core/mail.py: Mail.answer_receipts`), so it is never an unattended
transmission and the operator can read or delete it first.
"""

from __future__ import annotations

import re
from datetime import datetime

REQUEST_DR = "!RDR!"
REQUEST_RR = "!RRR!"
_URGENT = "!URG!"
_FLAGS = (REQUEST_DR, REQUEST_RR, _URGENT)

DELIVERED = "DELIVERED: "
READ = "READ: "

#: Extra headers a filed message carries.
HEADER_DR = "Request-DR"
HEADER_RR = "Request-RR"
HEADER_RECEIPT = "Receipt"  # "delivered" or "read": this message is one
HEADER_ANSWERED = "Receipt-Sent"  # "DR", "RR" or "DR RR": already answered

#: BPQMail cuts a title at 60 characters (`mail.compose.MAX_TITLE`).
_TITLE_LIMIT = 60

_LMI_BAD = re.compile(r"[!\r\n]")
_DELIVERY_RE = re.compile(r"^\n*!LMI![^!]+!DR!")
_READ_RE = re.compile(r"^\n*!RR!")


def request_flags(delivery: bool, read: bool) -> str:
    """The flags to put at the start of an outgoing body."""
    return (REQUEST_DR if delivery else "") + (REQUEST_RR if read else "")


def split_requests(body: str) -> tuple[bool, bool, str]:
    """(delivery asked, read asked, the body without the flags). A body with
    no flag, or one that starts `!B64!`, comes back unchanged."""
    rest = body.lstrip("\n")
    delivery = read = found = False
    while rest[:5] in _FLAGS:
        found = True
        delivery |= rest[:5] == REQUEST_DR
        read |= rest[:5] == REQUEST_RR
        rest = rest[5:]
    return (delivery, read, rest) if found else (False, False, body)


def receipt_kind(subject: str, body: str) -> str:
    """"delivered" or "read" when this is a receipt from an Outpost-style
    station, else ""."""
    if subject.startswith(DELIVERED) and _DELIVERY_RE.match(body):
        return "delivered"
    if subject.startswith(READ) and _READ_RE.match(body):
        return "read"
    return ""


def _stamp(when: datetime) -> str:
    return when.strftime("%m/%d/%Y %H:%M")


def _title(prefix: str, subject: str) -> str:
    return (prefix + subject)[:_TITLE_LIMIT].rstrip()


def delivery_receipt(*, local_id: str, to: str, subject: str, when: datetime) -> tuple[str, str]:
    """(title, body) of the Delivery Receipt for a message sent `to` with
    `subject`. ValueError when the local id is empty or has a `!` or a
    newline in it."""
    if not local_id or _LMI_BAD.search(local_id):
        raise ValueError("The local message ID must not be empty or contain ! or newlines.")
    stamp = _stamp(when)
    body = (f"!LMI!{local_id}!DR!{stamp}\nYour Message\nTo: {_one_line(to)}\n"
            f"Subject: {_one_line(subject)}\nwas delivered on {stamp}\n"
            f"Recipient's Local Message ID: {local_id}\n")
    return _title(DELIVERED, subject), body


def read_receipt(*, to: str, subject: str, when: datetime) -> tuple[str, str]:
    """(title, body) of the Read Receipt."""
    stamp = _stamp(when)
    body = (f"!RR!{stamp}\nYour Message\n\nTo: {_one_line(to)}\n"
            f"Subject: {_one_line(subject)}\n\nwas read on {stamp}\n")
    return _title(READ, subject), body


def _one_line(text: str) -> str:
    return " ".join(text.split())
