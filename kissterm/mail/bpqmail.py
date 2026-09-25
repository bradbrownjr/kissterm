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
  `<A>bort, <R Msg(s)>, <CR> = Continue..>` inside a listing. The prompt is
  the BBS's, not the message's: it is cut out wherever it appears, and a
  line left empty by the cut is dropped. Paging is a per-user BBS setting
  (`OP n`), so every function here works the same with or without it.
- `A` at a page prompt ends the read with `Output aborted`. **A read without
  its end marker is incomplete and is never filed**: a half message filed as
  if whole is worse than one that is fetched again next time.
- `Date/Time:` has no year (`21-Sep 08:37Z`); `infer_date` supplies one.

- A private message reads the same way (2026-09-24, `R 2578`): `Type/Status:
  PY`, no `R:` lines, two blank lines before the body.
- `K 2578` answers `Message #2578 Killed`; `R 99999` answers `Message 99999
  not found` (no `#`). Both are followed by the prompt.

- The greeting says `You have N messages waiting for you.` -- N counts
  unread mail only. `LM` lists read mail too (status `Y`), so a collector
  decides what it already has by BID (`MessageStore.find`), not by status.
  With the node's "Include SYSOP msgs in LM" off, `LM` lists only mail to
  the user's own call.

- `LM` with no mail at all answers with the prompt alone: no "no messages"
  line (2026-09-24). An empty listing is an empty list, not an error.

Sending, researched from the LinBPQ source (`github.com/g8bpq/linbpq`,
`BBSUtilities.c`: `DoSendCommand`, `ProcessMsgLine`; summarised with
citations in `packet-net/pdn-bbs` `docs/linbpq-mail-compat.md` sections
1.3-1.5) and confirmed by the 2026-09-25 captures `send_sr_2784.txt` and
`send_sp_w1bkw.txt`:

- `S[P|B|T] TO [@ AT] [$BID]`. TO is cut to 6 characters and loses its
  SSID; AT is at most 40. Without `@`, BPQMail adds one from the
  recipient's Home BBS or White Pages: `Address @W1BKW.#OXFO.ME.USA.NOAM
  added from HomeBBS`. A missing TO: `*** Error: The 'TO' callsign is
  missing`; a malformed line: `*** Error: Invalid Format`.
- `Enter Title (only):` (at most 60 characters stored). **An empty title
  cancels** (`*** Message Cancelled`) -- the only way out once started.
- `SR n` replies to message n with no title prompt; the title becomes
  `Re:<title>`. `SC n CALL` copies (`Fwd:`).
- `Enter Message Text (end with /ex or ctrl/z)`. The text ends at a line
  that is `/ex` in any case, or starts with Ctrl-Z, so a body line like
  that must never be sent as written.
- Accepted: `Message: 2801 Bid:  2801_WS1EC Size: 54` (two spaces after
  `Bid:`; Size counts CRLF endings), sometimes followed by a warning that
  no forwarding route is known, then the prompt.
- NTS traffic is `ST <zip> @ NTS<state>` (`ST 04005 @ NTSME`); a
  bulletin is `SB <category> @ <distribution>` (`SB WX @ ALLUS`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .message import KIND_BULLETIN, KIND_MAIL, Message

#: A page prompt, wherever it sits on a line: alone, or glued to text when
#: the BBS sends it without a line ending.
PAGE_PROMPT_RE = re.compile(r"<A>bort,.*?Continue\.\.>[ \t]*")
END_RE = re.compile(r"^\[End of Message #(\d+) from ([A-Za-z0-9/-]+)\]\s*$")
ABORTED = "Output aborted"
#: The BBS prompt. LinBPQ's default is `de CALL>` (`BBSUtilities.c`:
#: `sprintf(Prompt, "de %s>\r\n", BBSName)`); WS1EC's sysop made it
#: `de WS1EC#>`. Both match. A body line that happens to look like one ends
#: a read early, which leaves it without its end marker: never filed.
PROMPT_RE = re.compile(r"^de ([A-Z0-9]{1,6})(?:-\d{1,2})?#?>\s*$")
# Sending (`BBSUtilities.c` DoSendCommand / ProcessMsgLine; captured
# 2026-09-25 in send_sr_2784.txt and send_sp_w1bkw.txt).
TITLE_PROMPT_RE = re.compile(r"^Enter Title \(only\):\s*$")
TEXT_PROMPT_RE = re.compile(r"^Enter Message Text \(end with /ex or ctrl/z\)\s*$", re.I)
#: `Message: 2801 Bid:  2801_WS1EC Size: 54` -- two spaces after `Bid:`.
ACCEPTED_RE = re.compile(r"^Message: (\d+) Bid:\s+(\S+) Size: (\d+)\s*$")
#: `*** Error: The 'TO' callsign is missing`, `*** Error- Duplicate BID`,
#: `*** Message Cancelled`: every refusal starts with three stars.
REFUSED_RE = re.compile(r"^\*\*\*\s*(.+?)\s*$")
ADDRESS_ADDED_RE = re.compile(r"^Address @(\S+) added from (\S+)\s*$")
KILLED_RE = re.compile(r"^Message #(\d+) Killed\s*$")
NOT_FOUND_RE = re.compile(r"^Message (\d+) not found\s*$")
# UNVERIFIED: the singular ("1 message"); only 0 and 2 are captured.
WAITING_RE = re.compile(r"^You have (\d+) messages? waiting for you\.?\s*$")

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


def strip_page_prompts(line: str) -> str | None:
    """`line` with any page prompt cut out; None if nothing but the prompt."""
    if "Continue..>" not in line:
        return line
    cut = PAGE_PROMPT_RE.sub("", line)
    return cut if cut.strip() else None


def parse_list_line(line: str) -> ListEntry | None:
    line = strip_page_prompts(line) or ""
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


def killed(lines: list[str]) -> int | None:
    """The message number a `K` reply confirms killed, or None."""
    return _first_number(KILLED_RE, lines)


def not_found(lines: list[str]) -> int | None:
    """The message number an `R` or `K` reply says does not exist, or None."""
    return _first_number(NOT_FOUND_RE, lines)


def waiting(lines: list[str]) -> int | None:
    """The unread count from the login greeting, or None if it is not there."""
    return _first_number(WAITING_RE, lines)


def _first_number(pattern: re.Pattern[str], lines: list[str]) -> int | None:
    for line in lines:
        match = pattern.match((strip_page_prompts(line) or "").strip())
        if match is not None:
            return int(match.group(1))
    return None


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
    lines = [kept for kept in (strip_page_prompts(line) for line in lines) if kept is not None]
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
        elif line.strip():
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
