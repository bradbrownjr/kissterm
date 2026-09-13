"""Messages, acks/rejects, status, bulletins, objects, and items.

These share one file because they are all "a short, mostly fixed-format
line addressed at either a station or nobody in particular" -- a message is
addressed to one 9-character callsign field, a status/query/capabilities line
has no addressee, and an object/item is a named position someone else is
reporting on behalf of a thing that cannot transmit for itself (a repeater, a
weather station, an event). Objects and items delegate their actual position
decoding to `position.py`; everything else here is field-splitting on fixed
delimiters.

ack/rej are not really "empty messages" even though they reuse the message
data-type identifier (``:``) and the `Message` dataclass -- `is_ack`/`is_rej`
exist specifically so a caller doing two-way messaging cannot mistake one for
an ordinary blank-text message. Bulletins and announcements are not given a
distinct shape either: on the wire they are just a message whose addressee
happens to be ``BLNn`` or ``ANn`` padded to 9 characters, so `parse_message`
handles them without special-casing -- a caller that cares can check
`Message.addressee` itself.

A telemetry-equipped station labelling its own channels (``PARM.``/``UNIT.``/
``EQNS.``/``BITS.``, one message each, addressed to itself) is the same
situation as ack/rej for exactly the same reason: real APRS traffic riding
the message data type without being a message a human wrote to another
human. `is_telemetry_definition` flags it so a caller doing two-way
messaging -- `KissTermApp._on_aprs_frame`, which files ordinary messages
into a conversation log -- does not have to also know the APRS telemetry
spec to keep four lines of channel-scaling coefficients out of a chat view.

Total/never-raise applies here exactly as everywhere else in this package:
these functions are called only from `parse.py`'s `_dispatch`, which is
wrapped by `parse_packet`'s catch-all, so raising `ValueError` on malformed
input is the correct and expected way to fail.
"""

from __future__ import annotations

import re

from .position import parse_position_field
from .types import Message, ObjectReport, Status

__all__ = [
    "parse_message",
    "parse_status",
    "parse_object",
    "parse_item",
    "is_telemetry_definition_text",
    "is_bulletin_addressee",
]

#: The four telemetry channel-labelling message types, per the APRS spec's
#: telemetry chapter -- always sent as a message a station addresses to
#: itself, never text a human typed. Matched on the leading dotted keyword
#: only, so a genuine chat message that happens to start the same way (very
#: unlikely -- "PARM." is not an English word) is the one false positive
#: this accepts in exchange for not needing to also check the addressee.
_TELEMETRY_DEFINITION_PREFIXES = ("PARM.", "UNIT.", "EQNS.", "BITS.")


def is_telemetry_definition_text(text: str) -> bool:
    """Same prefix check `parse_message` uses, exposed for callers that
    already have a `Message.text` in hand and need the same answer outside
    a fresh parse -- `KissTermApp` uses it once at startup to purge
    telemetry-definition lines a pre-2026-09-10 build recorded into chat
    history before this check existed at all. One definition, so the two
    call sites can never drift apart on what counts as one of these.
    """
    return text.startswith(_TELEMETRY_DEFINITION_PREFIXES)


def is_bulletin_addressee(addressee: str) -> bool:
    """Return whether an addressee is a BLNn bulletin or ANn announcement."""
    return bool(re.fullmatch(r"(?:BLN|AN)[0-9]", addressee.strip().upper()))


def parse_message(body: str) -> Message:
    if len(body) < 10 or body[9] != ":":
        raise ValueError("malformed message addressee field")
    addressee = body[0:9].strip()
    rest = body[10:]
    if rest.startswith("ack"):
        return Message(addressee=addressee, text="", number=rest[3:].strip() or None, is_ack=True)
    if rest.startswith("rej"):
        return Message(addressee=addressee, text="", number=rest[3:].strip() or None, is_rej=True)
    if is_telemetry_definition_text(rest):
        return Message(addressee=addressee, text=rest, is_telemetry_definition=True)
    m = re.search(r"\{([A-Za-z0-9]{1,5})\}?$", rest)
    if m:
        return Message(addressee=addressee, text=rest[: m.start()], number=m.group(1))
    return Message(addressee=addressee, text=rest)


_STATUS_TS_RE = re.compile(r"^(\d{6}z)")


def parse_status(body: str) -> Status:
    m = _STATUS_TS_RE.match(body)
    if m:
        return Status(text=body[m.end() :].strip(), timestamp=m.group(1))
    return Status(text=body.strip())


def parse_object(body: str) -> ObjectReport:
    if len(body) < 18:
        raise ValueError("object field truncated")
    name = body[0:9].rstrip()
    alive = body[9] == "*"
    timestamp = body[10:17]
    position = parse_position_field(body[17:])
    return ObjectReport(name=name, alive=alive, position=position, timestamp=timestamp, is_item=False)


def parse_item(body: str) -> ObjectReport:
    idx = next((i for i, ch in enumerate(body[:10]) if ch in "!_"), None)
    if idx is None:
        raise ValueError("item missing live/kill terminator")
    name = body[:idx]
    alive = body[idx] == "!"
    position = parse_position_field(body[idx + 1 :])
    return ObjectReport(name=name, alive=alive, position=position, timestamp=None, is_item=True)
