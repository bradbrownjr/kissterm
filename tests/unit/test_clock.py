"""The header clock: three independent toggles, 12/24 hour, ISO dates.

`format_clock` is pure so the whole matrix is testable without a running app,
a terminal, or a patched system clock -- which is why it takes both datetimes
as arguments instead of calling `datetime.now()` itself.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone

from kissterm.ui.clock import format_clock, format_time

LOCAL = datetime(2026, 9, 5, 14, 5)
UTC = datetime(2026, 9, 5, 19, 5, tzinfo=timezone.utc)
# Deliberately a morning time, to catch a 12-hour formatter that only ever
# gets exercised in the afternoon and quietly prints PM for everything.
LOCAL_AM = datetime(2026, 9, 5, 9, 7)
UTC_AM = datetime(2026, 9, 5, 4, 7, tzinfo=timezone.utc)
# The night the two dates disagree: 21:30 local is already tomorrow in UTC.
LOCAL_LATE = datetime(2026, 9, 5, 21, 30)
UTC_NEXT_DAY = datetime(2026, 9, 6, 2, 30, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# The three toggles are genuinely independent
# ---------------------------------------------------------------------------


def test_each_toggle_is_independent():
    """Every one of the eight combinations must be reachable and sensible.

    The first design made the two times an either/or enum with the date as a
    separate flag, which left 'show nothing' and 'show only the date'
    unreachable. This is the test that pins the model down.
    """
    seen = {}
    for show_local, show_utc, show_date in itertools.product((True, False), repeat=3):
        rendered = format_clock(LOCAL, UTC, show_local, show_utc, show_date)
        seen[(show_local, show_utc, show_date)] = rendered
        assert rendered == rendered.strip(), f"stray whitespace: {rendered!r}"
    # All eight distinct: no combination silently collapses into another.
    assert len(set(seen.values())) == 8, seen


def test_local_time_only_is_the_default_shape():
    assert format_clock(LOCAL, UTC) == "14:05"


def test_everything_off_renders_nothing():
    """'The user chooses to show them at all' -- including not at all."""
    assert format_clock(LOCAL, UTC, False, False, False) == ""


def test_date_alone_is_reachable():
    assert format_clock(LOCAL, UTC, False, False, True) == "2026-09-05"


def test_both_times_without_a_date():
    assert format_clock(LOCAL, UTC, True, True, False) == "14:05 / 19:05Z"


# ---------------------------------------------------------------------------
# UTC must always be marked; local must never be
# ---------------------------------------------------------------------------


def test_utc_is_marked_with_z_on_a_24_hour_clock():
    assert format_clock(LOCAL, UTC, False, True, use_24h=True) == "19:05Z"


def test_utc_is_marked_with_utc_on_a_12_hour_clock():
    """'7:05 PM Z' reads wrong -- Z is a 24-hour/ISO convention."""
    assert format_clock(LOCAL, UTC, False, True, use_24h=False) == "7:05 PM UTC"


def test_local_time_is_never_marked():
    """A paper log does not suffix local time either."""
    for use_24h in (True, False):
        rendered = format_clock(LOCAL, UTC, True, False, use_24h=use_24h)
        assert "Z" not in rendered and "UTC" not in rendered


def test_a_shown_utc_reading_is_always_marked():
    """The one thing this clock must never do is show unmarked UTC."""
    for show_local, show_date, use_24h in itertools.product((True, False), repeat=3):
        rendered = format_clock(
            LOCAL, UTC, show_local, True, show_date, use_24h=use_24h
        )
        assert "Z" in rendered or "UTC" in rendered, rendered


# ---------------------------------------------------------------------------
# Time formats
# ---------------------------------------------------------------------------


def test_24_hour_is_zero_padded():
    assert format_clock(LOCAL_AM, UTC_AM, use_24h=True) == "09:07"


def test_12_hour_strips_the_leading_zero_not_the_whole_hour():
    """`%-I` is glibc-only, so the zero is stripped by hand -- easy to get
    wrong in a way that turns 09:07 into ':07' or 10:07 into '1:07'."""
    assert format_clock(LOCAL_AM, UTC_AM, use_24h=False) == "9:07 AM"
    assert format_clock(datetime(2026, 9, 5, 10, 7), UTC_AM, use_24h=False) == "10:07 AM"


def test_12_hour_distinguishes_am_from_pm():
    assert "AM" in format_clock(LOCAL_AM, UTC_AM, use_24h=False)
    assert "PM" in format_clock(LOCAL, UTC, use_24h=False)


def test_midnight_and_noon_do_not_collapse():
    midnight = datetime(2026, 9, 5, 0, 0)
    noon = datetime(2026, 9, 5, 12, 0)
    assert format_clock(midnight, UTC, use_24h=False) == "12:00 AM"
    assert format_clock(noon, UTC, use_24h=False) == "12:00 PM"
    assert format_clock(midnight, UTC, use_24h=True) == "00:00"


# ---------------------------------------------------------------------------
# Dates -- and the boundary where one date cannot cover two readings
# ---------------------------------------------------------------------------


def test_date_is_iso_8601_never_locale_order():
    """03/04 is March 4th in the US and April 3rd nearly everywhere else."""
    rendered = format_clock(LOCAL, UTC, True, False, True)
    assert rendered.startswith("2026-09-05")
    assert "/" not in rendered


def test_a_single_shown_time_gets_its_own_date():
    assert format_clock(LOCAL_LATE, UTC_NEXT_DAY, True, False, True).startswith("2026-09-05")
    assert format_clock(LOCAL_LATE, UTC_NEXT_DAY, False, True, True).startswith("2026-09-06")


def test_both_times_on_the_same_date_share_one_leading_date():
    assert format_clock(LOCAL, UTC, True, True, True) == "2026-09-05  14:05 / 19:05Z"


def test_both_times_across_midnight_each_carry_their_own_date():
    """A single date beside two readings belongs to only one of them, which is
    how a log entry lands on the wrong day."""
    rendered = format_clock(LOCAL_LATE, UTC_NEXT_DAY, True, True, True)
    assert rendered == "2026-09-05 21:30 / 2026-09-06 02:30Z"


def test_date_only_follows_utc_when_utc_is_the_zone_shown():
    """With no time on screen, the date still has to belong to something."""
    assert format_clock(LOCAL_LATE, UTC_NEXT_DAY, False, False, True) == "2026-09-05"
    assert format_clock(LOCAL_LATE, UTC_NEXT_DAY, False, True, True).startswith("2026-09-06")


def test_date_is_omitted_by_default():
    assert format_clock(LOCAL, UTC) == "14:05"


# ---------------------------------------------------------------------------
# format_time on its own
# ---------------------------------------------------------------------------


def test_format_time_is_usable_on_its_own():
    assert format_time(UTC, use_24h=True, utc=True) == "19:05Z"
    assert format_time(LOCAL, use_24h=True, utc=False) == "14:05"
