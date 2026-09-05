"""The header clock: local, UTC, or both; 12- or 24-hour; with or without date.

Amateur radio runs on UTC. Logs, nets, contest windows, DX spots and QSL cards
are all UTC by convention, while the operator's wall clock is local -- so the
one thing this clock must never do is show a time without saying which it is.
`Z` (the ISO 8601 / RFC 3339 designator for zero offset, and the same "Zulu"
suffix already used on the air) marks UTC everywhere it appears; local time
carries no suffix, which is the same convention a paper log uses.

`"both"` exists because that is the actual operating condition: you log in UTC
and you live in local time, and doing the arithmetic in your head during a net
is how a log ends up an hour wrong. It is not a novelty option.

**Dates are ISO 8601 (`YYYY-MM-DD`), never locale-formatted.** `03/04/2026` is
March 4th to an American operator and April 3rd to almost everyone else, and
packet is an international medium -- a station in another country reading a
screenshot of your log window should not have to guess.

`format_clock` is a pure function of the two `datetime`s it is handed, so the
whole matrix (three sources x two formats x date on/off) is testable without a
running app, a terminal, or a patched system clock.
"""

from __future__ import annotations

from datetime import datetime, timezone

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Header
from textual.widgets._header import HeaderClock, HeaderClockSpace, HeaderIcon, HeaderTitle

#: `Config.clock_source` values.
CLOCK_SOURCES = ("local", "utc", "both")


def format_time(moment: datetime, use_24h: bool, utc: bool) -> str:
    """One clock time, marked as UTC when it is.

    The UTC marker differs by format on purpose: `Z` is an ISO 8601 / 24-hour
    convention and reads wrong glued to a 12-hour clock ("7:05 PM Z"), so the
    12-hour form spells out `UTC` instead. Both are unambiguous to an
    operator; neither is silently unmarked.
    """
    if use_24h:
        return moment.strftime("%H:%M") + ("Z" if utc else "")
    # %-I is not portable (it is glibc-specific and absent on Windows), so
    # strip the leading zero by hand rather than relying on the platform.
    text = moment.strftime("%I:%M %p").lstrip("0")
    return text + (" UTC" if utc else "")


def format_clock(
    local: datetime,
    utc: datetime,
    source: str = "local",
    use_24h: bool = True,
    show_date: bool = False,
) -> str:
    """Render the header clock.

    Both `datetime`s are passed in rather than read from the system clock so
    this stays a pure function -- see the module docstring.
    """
    if source == "utc":
        body = format_time(utc, use_24h, utc=True)
        date_from = utc
    elif source == "both":
        # Local first: it is the one the operator glances at most, and the
        # Z-marked UTC reading is the one they deliberately look for.
        body = f"{format_time(local, use_24h, utc=False)} / {format_time(utc, use_24h, utc=True)}"
        date_from = utc
    else:
        body = format_time(local, use_24h, utc=False)
        date_from = local

    if show_date:
        # ISO 8601, never locale order -- see the module docstring.
        return f"{date_from.strftime('%Y-%m-%d')}  {body}"
    return body


class KissTermClock(HeaderClock):
    """A header clock that reads `App.config` instead of assuming local/24h.

    Textual's own `HeaderClock` hardcodes `datetime.now().strftime("%X")` --
    local time only, no UTC, no date, and a fixed 10-column width that a date
    or a dual reading does not fit in. Subclassing to override `render` is
    less code than reimplementing the header, and inherits the once-a-second
    refresh timer already set up in `HeaderClock._on_mount`.
    """

    DEFAULT_CSS = """
    KissTermClock {
        /* auto, not the inherited fixed 10: "2026-09-05  14:05 / 19:05Z" is
           26 columns and would be silently truncated at the inherited width. */
        width: auto;
        padding: 0 1;
        content-align: center middle;
    }
    """

    def render(self):
        config = getattr(self.app, "config", None)
        source = getattr(config, "clock_source", "local")
        use_24h = getattr(config, "clock_24h", True)
        show_date = getattr(config, "show_date", False)
        return Text(
            format_clock(
                datetime.now(),
                datetime.now(timezone.utc),
                source=source,
                use_24h=use_24h,
                show_date=show_date,
            )
        )


class KissTermHeader(Header):
    """`Header`, but with kissterm's configurable clock.

    Only `compose` differs from the base class: the icon and title are
    Textual's own. Kept as a subclass rather than a from-scratch header so
    title/subtitle behaviour, the tall-header click toggle, and the command
    palette icon all keep working without being reimplemented.
    """

    def compose(self) -> ComposeResult:
        yield HeaderIcon().data_bind(Header.icon)
        yield HeaderTitle()
        yield KissTermClock() if self._show_clock else HeaderClockSpace()
