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


def _iso_date(moment: datetime) -> str:
    """ISO 8601 only -- see the module docstring on why never locale order."""
    return moment.strftime("%Y-%m-%d")


def format_clock(
    local: datetime,
    utc: datetime,
    show_local: bool = True,
    show_utc: bool = False,
    show_date: bool = False,
    use_24h: bool = True,
) -> str:
    """Render the header clock from three independent toggles.

    Local time, UTC time and the date are each shown or not shown on their
    own. They are deliberately NOT one either/or setting: an operator may want
    UTC only, both, local plus the date, or -- turning all three off -- an
    empty header. An enum for the times with a separate flag for the date
    modelled the same kind of thing two different ways.

    **Which date, when both times are shown and they disagree.** Around
    midnight the local and UTC dates differ, and a single date printed beside
    two readings silently belongs to only one of them -- which is how a log
    entry lands on the wrong day. So:

    * one time shown -> one leading date, that reading's own;
    * both shown, same date -> one leading date, unambiguous;
    * both shown, dates differ -> **each reading carries its own date**, e.g.
      ``2026-09-05 21:30 / 2026-09-06 02:30Z``. The layout only widens at the
      boundary where the ambiguity actually exists, which is exactly when the
      operator needs the extra clarity;
    * no time shown at all -> just the date, from UTC if UTC is the zone being
      shown, otherwise local.

    Both `datetime`s are passed in rather than read from the system clock so
    this stays a pure function -- see the module docstring.
    """
    local_text = format_time(local, use_24h, utc=False) if show_local else ""
    utc_text = format_time(utc, use_24h, utc=True) if show_utc else ""

    if not show_date:
        return " / ".join(p for p in (local_text, utc_text) if p)

    dates_differ = local.date() != utc.date()

    if show_local and show_utc and dates_differ:
        # The only case where one date cannot honestly cover both readings.
        return f"{_iso_date(local)} {local_text} / {_iso_date(utc)} {utc_text}"

    body = " / ".join(p for p in (local_text, utc_text) if p)
    # The date belongs to whichever zone is on screen; UTC wins when shown,
    # because that is the reading an operator logs against.
    date_source = utc if show_utc else local
    return f"{_iso_date(date_source)}  {body}".rstrip()


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
        return Text(
            format_clock(
                datetime.now(),
                datetime.now(timezone.utc),
                show_local=getattr(config, "show_local_time", True),
                show_utc=getattr(config, "show_utc_time", False),
                show_date=getattr(config, "show_date", False),
                use_24h=getattr(config, "clock_24h", True),
            )
        )


class KissTermHeader(Header):
    """`Header`, but with kissterm's configurable clock and no click-to-expand.

    Only `compose` and `_on_click` differ from the base class: the icon and
    title are Textual's own. Kept as a subclass rather than a from-scratch
    header so title/subtitle behaviour and the command palette icon keep
    working without being reimplemented.

    **The tall-header toggle is removed on purpose.** Textual's `Header`
    grows from one line to three when clicked, to show a title and subtitle.
    kissterm has neither -- the status bar carries the station identity -- so
    the extra two rows show nothing, and every widget below shifts down by
    two: the tab bar, the panes, the scrollback. Doing that to a live session
    because a mouse click landed on the top row is a jump the operator did not
    ask for and cannot undo except by finding the same row and clicking again.
    A layout change with no content behind it is not a feature.
    """

    def _on_click(self, event) -> None:
        # `prevent_default`, not merely overriding `_on_click`: Textual
        # dispatches an event to EVERY matching handler up the MRO, so a
        # subclass method does not replace `Header._on_click` -- both run, and
        # the base one still toggles. `prevent_default` is what breaks that
        # walk (`MessagePump._get_dispatch_methods` stops on
        # `_no_default_action`), and it is checked between classes, so this
        # handler running first is enough. The click is not `stop`ped: it
        # still bubbles, so nothing else that wants to know about it breaks.
        event.prevent_default()

    def compose(self) -> ComposeResult:
        yield HeaderIcon().data_bind(Header.icon)
        yield HeaderTitle()
        yield KissTermClock() if self._show_clock else HeaderClockSpace()
