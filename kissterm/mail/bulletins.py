"""Bulletin categories: what a BBS offers, and which ones the operator wants.

ROADMAP P2 "Bulletin collection", decided with the operator 2026-09-24 and
2026-10-02:

- **Subscriptions, not everything.** A BBS holds hundreds of bulletins and
  a weak path moves a few lines a minute, so only chosen categories are
  read. The first collection asks for the category list and offers it as a
  checklist, with All.
- **New categories are offered, once in a while** (operator, 2026-10-02:
  "check for new categories once in a while"). The list costs airtime, so
  it is asked for on the first run and then at most every `check_days`
  days, not on every run. A category not seen before is offered; one
  declined is remembered and never offered again. "All" takes every
  category, new ones included, without asking.

What BPQMail sends, from the LinBPQ source (`BBSUtilities.c`,
`ListCategories`; `NNTPRoutines.c`, `BuildNNTPList`):

- `LC` lists one entry per bulletin "to" field (the category: `WX`,
  `ALL`, `ARES`), summed over every `@` distribution, in alphabetical
  order. Only bulletins (type B) that are neither killed nor held count.
- Each entry is `%-6s %-3d` (name, count), nine to a line, then a blank
  line: `ALL    12 ARES   3  WX     40 `. A name longer than six
  characters pushes the rest along, so entries are split on whitespace, not
  by column.
- `LB> WX` lists bulletins whose "to" is WX, ignoring case (`DoListCommand`:
  type `B`, selector `>`), newest first; `LB> WX 2801-` lists only from
  2801 up, which is how a later run asks for what is new and no more, and
  `LB> WX 2705-2804` one window of numbers, which is how a first run goes
  back a few days without a listing that cannot be stopped: **most users
  do not page** (operator, 2026-10-02), so `A` at a page prompt is only a
  second brake. `LL 1` lists the newest message, for its number.
  An empty listing is the prompt alone, as for `LM`.

Confirmed by the operator's capture from WS1EC-2, 2026-10-02
(`tests/unit/data/bpqmail/list_lc_ws1ec.txt`, `list_lb_wx_page1.txt`):
fifteen categories, `SPACWX 142UPDATE 49` (a three-digit count runs into
the next name), and `LB> WX` paging 310 bulletins 23 to a page.

The window form (`LB> WX 3112-3211`) is confirmed by the operator's first
collection over WS1EC's SSH login, 2026-10-06
(`20261006-231343_KC1JMH_WS1ECSSH.log`): windows answered, older dates
stopped the listing, 72 bulletins of the last 7 days read.

# UNVERIFIED: the open range (`LB> WX 2801-`, a later run) and `LL 1` are
# the source's, not yet seen in a capture.

The choices live in a small JSON file in the state folder, one record per
BBS callsign (categories differ from BBS to BBS). Same persistence shape
as `kissterm/harvested.py`: atomic write, I/O errors logged, never raised.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import state_path

log = logging.getLogger(__name__)

#: How often the category list is asked for again, unless set otherwise.
DEFAULT_CHECK_DAYS = 7
#: How far back the first collection from a category goes (operator,
#: 2026-10-02: "Last N days"; WS1EC-2 held 310 WX bulletins).
DEFAULT_FIRST_DAYS = 7

#: One `LC` entry: a category name and its count.
_ENTRY_RE = re.compile(r"(\S+)\s+(\d+)")
#: A category is a bulletin's "to" field: at most six characters in BPQMail
#: (`S` cuts TO to six), letters, digits and a few marks.
_CATEGORY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,11}$")


def parse_categories(lines: list[str]) -> dict[str, int]:
    """`{category: count}` from the lines of an `LC` reply.

    Lines that are not wholly `name count` pairs (the echoed command, a
    page prompt, a blank) are skipped, so a stray line is never taken for
    a category.
    """
    categories: dict[str, int] = {}
    for line in lines:
        text = line.strip()
        if not text:
            continue
        pairs = _ENTRY_RE.findall(text)
        if not pairs or _ENTRY_RE.sub("", text).strip():
            continue
        for name, count in pairs:
            if _CATEGORY_RE.match(name):
                name = name.upper()
                categories[name] = categories.get(name, 0) + int(count)
    return categories


#: Message numbers per window on a first run (`window_command`).
WINDOW = 100
#: Windows asked for at most on a first run: 1000 message numbers back.
MAX_WINDOWS = 10
#: BPQMail's default welcome, `Hello $I. Latest Message is $L, Last listed
#: is $Z` (`BBSUtilities.c`); WS1EC-2 keeps it. A sysop may change it, so
#: `LL 1` (list the last one) is asked when it is missing.
LATEST_RE = re.compile(r"Latest Message is (\d+)")
LATEST_COMMAND = "LL 1"


def list_command(category: str, after: int = 0) -> str:
    """The listing command for one category; only numbers above `after`
    when one is given."""
    return f"LB> {category} {after + 1}-" if after else f"LB> {category}"


def window_command(category: str, low: int, high: int) -> str:
    """One window of a first run: bulletins to `category` numbered `low`
    to `high`. Windows, not a bare `LB>`, because most users do not page
    (`OP`): a bare listing of 310 WX bulletins cannot be stopped once it
    starts, while a window lists a hundred numbers' worth at most."""
    return f"LB> {category} {low}-{high}"


def latest_number(lines: list[str]) -> int:
    """The BBS's latest message number from its greeting, 0 if absent."""
    for line in lines:
        if (match := LATEST_RE.search(line)):
            return int(match.group(1))
    return 0


@dataclass
class Subscriptions:
    """One BBS's bulletin choices."""

    #: Categories to collect.
    chosen: list[str] = field(default_factory=list)
    #: Every category, now and later.
    all: bool = False
    #: Offered and not wanted: never offered again.
    declined: list[str] = field(default_factory=list)
    #: Every category seen in the last list, with its count.
    seen: dict[str, int] = field(default_factory=dict)
    #: When the list was last asked for; None if never.
    checked: datetime | None = None

    @property
    def asked(self) -> bool:
        """Whether the operator has answered an offer for this BBS. An
        offer cancelled before any answer is made again on the next run."""
        return bool(self.chosen or self.declined or self.all)

    def due(self, now: datetime, days: int) -> bool:
        """Whether the category list should be asked for on this run."""
        if self.checked is None or not self.asked:
            return True
        return now - self.checked >= timedelta(days=max(1, days))

    def to_offer(self, categories: dict[str, int]) -> list[str]:
        """Categories in `categories` the operator has not answered yet."""
        if self.all:
            return []
        answered = {c.upper() for c in (*self.chosen, *self.declined)}
        return sorted(c for c in categories if c.upper() not in answered)

    def answer(self, offered: list[str], picked: list[str], *, all_: bool = False) -> None:
        """Record the operator's answer to an offer: `picked` are wanted,
        the rest of `offered` declined; `all_` takes everything."""
        if all_:
            self.all = True
        wanted = {p.upper() for p in picked}
        for category in offered:
            name = category.upper()
            target = self.chosen if name in wanted or all_ else self.declined
            if name not in target:
                target.append(name)
        self.chosen.sort()
        self.declined.sort()

    def choose(self, categories: list[str], picked: list[str], *, all_: bool) -> None:
        """Replace the choice (S on the Bulletins tab): `picked` wanted, the
        rest of `categories` declined, `all_` everything."""
        self.all = all_
        wanted = {p.upper() for p in picked}
        names = {c.upper() for c in categories}
        self.chosen = sorted(wanted | ({c.upper() for c in self.chosen} - names))
        self.declined = sorted((names - wanted)
                               | ({c.upper() for c in self.declined} - names - wanted))

    def collect(self) -> list[str]:
        """The categories to list on this run, in order."""
        if self.all:
            return sorted(set(self.seen) | {c.upper() for c in self.chosen})
        return sorted({c.upper() for c in self.chosen})


def path() -> Path:
    return state_path() / "bulletin_subscriptions.json"


class SubscriptionBook:
    """Every BBS's `Subscriptions`, by callsign, in one JSON file."""

    def __init__(self, file: Path | None = None) -> None:
        self.file = file or path()
        self._by_call: dict[str, Subscriptions] = {}

    def load(self) -> None:
        """Read the file. Missing or unreadable means nothing chosen yet:
        the next run offers the categories again, which costs one list."""
        try:
            raw = json.loads(self.file.read_text("utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            log.warning("bulletin subscriptions at %s are unreadable: %s", self.file, exc)
            return
        if not isinstance(raw, dict):
            log.warning("bulletin subscriptions at %s are not an object; ignoring", self.file)
            return
        for call, record in raw.items():
            if isinstance(record, dict):
                self._by_call[str(call).strip().upper()] = _from_json(record)

    def save(self) -> None:
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.file.with_suffix(".json.tmp")
            raw = {call: _to_json(subs) for call, subs in sorted(self._by_call.items())}
            temporary.write_text(json.dumps(raw, indent=2), "utf-8")
            os.replace(temporary, self.file)
        except OSError as exc:
            log.warning("could not save bulletin subscriptions to %s: %s", self.file, exc)

    def for_bbs(self, call: str) -> Subscriptions:
        """The choices for `call`, created empty if there are none yet."""
        return self._by_call.setdefault(call.strip().upper(), Subscriptions())


def _to_json(subs: Subscriptions) -> dict:
    return {
        "chosen": subs.chosen,
        "all": subs.all,
        "declined": subs.declined,
        "seen": subs.seen,
        "checked": subs.checked.isoformat() if subs.checked else None,
    }


def _from_json(record: dict) -> Subscriptions:
    def names(key: str) -> list[str]:
        value = record.get(key, [])
        if not isinstance(value, list):
            return []
        return sorted({str(v).strip().upper() for v in value if str(v).strip()})

    seen_raw = record.get("seen", {})
    seen = {
        str(k).strip().upper(): int(v)
        for k, v in (seen_raw.items() if isinstance(seen_raw, dict) else ())
        if str(k).strip() and isinstance(v, int)
    }
    checked = None
    if isinstance(record.get("checked"), str):
        try:
            checked = datetime.fromisoformat(record["checked"])
        except ValueError:
            checked = None
        if checked is not None and checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
    return Subscriptions(
        chosen=names("chosen"),
        all=record.get("all") is True,
        declined=names("declined"),
        seen=seen,
        checked=checked,
    )
