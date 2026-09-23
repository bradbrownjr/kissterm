"""Reading BPQMail's replies: the message list and one read message.

Written from captured sessions with WS1EC-2 (BPQMail 6.0.23.1), kept in
`tests/unit/data/bpqmail/` -- ROADMAP P2's reproduce-first rule for BBS
collection: where a message starts and ends is taken from real traffic, not
from memory. Pure functions over lines of text; the session that sends the
commands and feeds the lines in is separate.

What the captures show:

- A read is a header block (`From:`, `To:`, `Type/Status:`, `Date/Time:`,
  `Bid:`, `Title:`), then the `R:` routing lines -- sometimes after a blank
  line, sometimes not, sometimes with a blank line among them -- then the
  body, then trailing blank lines and `[End of Message #N from CALL]`.
- The BBS pages long output: `<A>bort, <CR> Continue..>` inside a read,
  `<A>bort, <R Msg(s)>, <CR> = Continue..>` inside a listing. Those lines
  are the BBS's, not the message's, and are dropped.
- `A` at a page prompt ends the read with `Output aborted`. **A read without
  its end marker is incomplete and is never filed**: a half message filed as
  if whole is worse than one that is fetched again next time.
- `Date/Time:` has no year (`21-Sep 08:37Z`); `infer_date` supplies one.

Not yet captured, so not relied on: a private message's read (assumed the
same shape; `# UNVERIFIED:`), the reply to `K`, and what `LM` or `R` say
when there is nothing to show.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .message import KIND_BULLETIN, KIND_MAIL, Message

PAGE_PROMPT_RE = re.compile(r"^<A>bort,.*Continue\.\.>\s*$")
END_RE = re.compile(r"^\[End of Message #(\d+) from ([A-Za-z0-9/-]+)\]\s*$")
ABORTED = "Output aborted"
PROMPT_RE = re.compile(r"^de ([A-Z0-9]{1,6})(?:-\d{1,2})?#>\s*$")

#: `2705   22-Sep B$     472 WP     @WS1EC  WD1O   WP Update`
LIST_RE = re.compile(
    r"^(?P<number>\d+)\s+(?P<date>\d{1,2}-[A-Za-z]{3})\s+"
    r"(?P<type>[A-Z])(?P<status>\S)\s+(?P<size>\d+)\s+"
    r"(?P<to>\S+)\s+@(?P<at>\S*)\s+(?P<sender>\S+)(?:\s+(?P<title>.*))?$"
)

_HEADER_RE = re.compile(r"^(From|To|Type/Status|Date/Time|Bid|Title):\s?(.*)$")
_ROUTE_RE = re.compile(r"^R:\d{6}/\d{4}")
_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


@dataclass(frozen=True)
class ListEntry:
    """One line of an `L`, `LM`, `LR` ... listing."""

    number: int
    date: str
    type: str  # P private, B bulletin, T NTS traffic
    status: str  # N not read, Y read, $ bulletin, F forwarded ...
    size: int
    to: str
    at: str
    sender: str
    title: str


def parse_list_line(line: str) -> ListEntry | None:
    match = LIST_RE.match(line.rstrip())
    if match is None:
        return None
    return ListEntry(
        number=int(match["number"]),
        date=match["date"],
        type=match["type"],
        status=match["status"],
        size=int(match["size"]),
        to=match["to"],
        at=match["at"],
        sender=match["sender"],
        title=(match["title"] or "").strip(),
    )


def parse_list(lines: list[str]) -> list[ListEntry]:
    return [e for e in (parse_list_line(line) for line in lines) if e is not None]


def prompt_call(line: str) -> str:
    """The BBS's callsign from its prompt (`de WS1EC#>` -> `WS1EC`), or ""."""
    match = PROMPT_RE.match(line.strip())
    return match.group(1) if match else ""


@dataclass
class BbsRead:
    """One message as the BBS sent it, split into its parts."""

    headers: dict[str, str] = field(default_factory=dict)
    routes: list[str] = field(default_factory=list)
    body: list[str] = field(default_factory=list)
    number: int = 0
    complete: bool = False
    aborted: bool = False


def parse_read(lines: list[str]) -> BbsRead | None:
    """Split the lines of one `R <num>` reply. None if no header block.

    Lines before `From:` (the echoed command, a listing's page prompt) are
    skipped. `complete` is True only when the end marker arrived.
    """
    read = BbsRead()
    i = 0
    while i < len(lines) and not lines[i].startswith("From:"):
        i += 1
    if i == len(lines):
        return None
    # Header block, ending at Title:.
    while i < len(lines):
        match = _HEADER_RE.match(lines[i])
        if match is None:
            break
        read.headers[match.group(1)] = match.group(2).strip()
        i += 1
        if match.group(1) == "Title":
            break
    # Routing lines, with blank lines allowed before and among them.
    while i < len(lines):
        line = lines[i]
        if _ROUTE_RE.match(line):
            read.routes.append(line.rstrip())
        elif line.strip() and not PAGE_PROMPT_RE.match(line):
            break
        i += 1
    for line in lines[i:]:
        end = END_RE.match(line)
        if end is not None:
            read.number = int(end.group(1))
            read.complete = True
            break
        if line.strip() == ABORTED:
            read.aborted = True
            break
        if PROMPT_RE.match(line.strip()):
            break
        if PAGE_PROMPT_RE.match(line):
            continue
        read.body.append(line.rstrip("\r"))
    while read.body and not read.body[-1].strip():
        read.body.pop()
    return read


def infer_date(text: str, now: datetime | None = None) -> datetime | None:
    """`21-Sep 08:37Z` -> a UTC datetime in the year that puts it not in the future.

    The BBS gives no year. A date more than a day ahead of `now` must be
    from last year (a December message read in January).
    """
    match = re.match(r"^\s*(\d{1,2})-([A-Za-z]{3})(?:\s+(\d{2}):(\d{2})Z?)?", text)
    if match is None:
        return None
    month = _MONTHS.get(match.group(2).lower())
    if month is None:
        return None
    now = now or datetime.now(timezone.utc)
    hour, minute = int(match.group(3) or 0), int(match.group(4) or 0)
    try:
        value = datetime(now.year, month, int(match.group(1)), hour, minute, tzinfo=timezone.utc)
        if (value - now).days >= 1:
            value = value.replace(year=now.year - 1)
    except ValueError:
        return None
    return value


def to_message(read: BbsRead, bbs_call: str, now: datetime | None = None) -> Message:
    """A store `Message` from a complete read.

    The message id is the BID/MID when the BBS shows one (unique across the
    network) and the BBS's own message number otherwise; `source` names the
    BBS by its callsign so the same message reached by another route is
    recognised (`MessageStore.find`). Routing lines are not in the body;
    the raw copy the caller files beside the message keeps them.
    """
    h = read.headers
    type_status = h.get("Type/Status", "")
    is_bulletin = type_status[:1] == "B"
    extra = {"Bbs-Number": str(read.number)} if read.number else {}
    if type_status:
        extra["Bbs-Type"] = type_status
    return Message(
        sender=h.get("From", ""),
        to=h.get("To", ""),
        subject=h.get("Title", ""),
        date=infer_date(h.get("Date/Time", ""), now),
        message_id=h.get("Bid", "") or (str(read.number) if read.number else ""),
        source=f"BBS {bbs_call}" if bbs_call else "BBS",
        kind=KIND_BULLETIN if is_bulletin else KIND_MAIL,
        category=h.get("To", "") if is_bulletin else "",
        body="\n".join(read.body) + "\n",
        extra=extra,
    )
