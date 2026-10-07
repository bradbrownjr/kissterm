"""Message-ID numbering: a short traceable prefix on an outgoing BBS title.

Outpost Packet Message Manager tags every outbound subject with a prefix
(three characters, by default the last three of the callsign), a sequence
number and a one-letter type, `6PE-2032P: Stevens Creek Dam Status`
(ROADMAP P11, researched from outpostpm.org). It is a subject-line
convention for a human following a message across BBS forwarding, not a
protocol field, so nothing here changes how a message is sent.

# UNVERIFIED: the exact separator, zero-padding and type letters are the
# roadmap's reading of Outpost's documentation, not a captured message. The
# sequence is plain digits, one counter for the station, never reused; the
# type is P (private) or B (bulletin).

What is numbered: a **BBS message the operator wrote** (private or
bulletin). Not a Winlink message (it has its own MID), not a form or a
radiogram (their standards carry their own numbering), not a reply by
number (the BBS titles it: `SR n`), and not a title already numbered.
BPQMail cuts a title at 60 characters, so the title gives way, never the
number.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .compose import MAX_TITLE

#: A title that already carries a number, so editing and re-filing a
#: message never numbers it twice.
_NUMBERED = re.compile(r"^[A-Z0-9]{1,6}-\d+[A-Z]?: ")
_TYPE_LETTERS = {"P": "P", "B": "B"}


def default_prefix(mycall: str) -> str:
    """The last three letters or digits of the callsign, SSID dropped."""
    base = re.sub(r"[^A-Z0-9]", "", mycall.split("-", 1)[0].upper())
    return base[-3:]


def clean_prefix(prefix: str, mycall: str) -> str:
    """The configured prefix as it is used: letters and digits, upper case,
    at most six; the callsign's default when empty."""
    cleaned = re.sub(r"[^A-Z0-9]", "", prefix.upper())[:6]
    return cleaned or default_prefix(mycall)


def applies(extra: dict[str, str], subject: str) -> bool:
    """Whether a filed message gets a number (see the module docstring)."""
    return (extra.get("Send-Type") in _TYPE_LETTERS and not extra.get("Form")
            and not extra.get("Reply-Number") and not _NUMBERED.match(subject))


def numbered_title(prefix: str, number: int, send_type: str, title: str) -> str:
    """`PRE-123P: title`, the title cut so the whole fits a BPQMail title."""
    head = f"{prefix}-{number}{_TYPE_LETTERS[send_type]}: "
    return head + title[: max(MAX_TITLE - len(head), 0)].rstrip()


class Counter:
    """The station's next number, kept in a small JSON file so it survives
    a restart and is never reused. A file that cannot be read or written
    starts again at 1 and never stops a message being filed."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def take(self) -> int:
        try:
            number = int(json.loads(self.path.read_text("utf-8"))["next"])
        except (OSError, ValueError, KeyError, TypeError):
            number = 1
        number = max(number, 1)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"next": number + 1}), "utf-8")
        except OSError:
            pass
        return number
