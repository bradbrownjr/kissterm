"""The header clock: local/UTC/both, 12/24 hour, optional ISO date.

`format_clock` is pure so the whole matrix is testable without a running app,
a terminal, or a patched system clock -- which is the reason it takes both
datetimes as arguments instead of calling `datetime.now()` itself.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kissterm.ui.clock import CLOCK_SOURCES, format_clock, format_time

LOCAL = datetime(2026, 9, 5, 14, 5)
UTC = datetime(2026, 9, 5, 19, 5, tzinfo=timezone.utc)
# Deliberately a morning time, to catch a 12-hour formatter that only ever
# gets exercised in the afternoon and quietly prints PM for everything.
LOCAL_AM = datetime(2026, 9, 5, 9, 7)
UTC_AM = datetime(2026, 9, 5, 4, 7, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# UTC must always be marked; local must never be
# ---------------------------------------------------------------------------


def test_utc_is_marked_with_z_on_a_24_hour_clock():
    assert format_clock(LOCAL, UTC, "utc", use_24h=True) == "19:05Z"


def test_utc_is_marked_with_utc_on_a_12_hour_clock():
    """'7:05 PM Z' reads wrong -- Z is a 24-hour/ISO convention."""
    assert format_clock(LOCAL, UTC, "utc", use_24h=False) == "7:05 PM UTC"


def test_local_time_is_never_marked():
    """A paper log does not suffix local time either."""
    for use_24h in (True, False):
        rendered = format_clock(LOCAL, UTC, "local", use_24h=use_24h)
        assert "Z" not in rendered and "UTC" not in rendered


@pytest.mark.parametrize("source", CLOCK_SOURCES)
def test_any_utc_reading_is_always_marked(source):
    """The one thing this clock must never do is show an unmarked UTC time."""
    for use_24h in (True, False):
        rendered = format_clock(LOCAL, UTC, source, use_24h=use_24h)
        if source in ("utc", "both"):
            assert "Z" in rendered or "UTC" in rendered, rendered


# ---------------------------------------------------------------------------
# Formats
# ---------------------------------------------------------------------------


def test_24_hour_is_zero_padded():
    assert format_clock(LOCAL_AM, UTC_AM, "local", use_24h=True) == "09:07"


def test_12_hour_strips_the_leading_zero_not_the_whole_hour():
    """`%-I` is glibc-only, so the zero is stripped by hand -- easy to get
    wrong in a way that turns 09:07 into ':07' or 10:07 into '1:07'."""
    assert format_clock(LOCAL_AM, UTC_AM, "local", use_24h=False) == "9:07 AM"
    ten = datetime(2026, 9, 5, 10, 7)
    assert format_clock(ten, UTC_AM, "local", use_24h=False) == "10:07 AM"


def test_12_hour_distinguishes_am_from_pm():
    assert "AM" in format_clock(LOCAL_AM, UTC_AM, "local", use_24h=False)
    assert "PM" in format_clock(LOCAL, UTC, "local", use_24h=False)


def test_midnight_and_noon_do_not_collapse():
    midnight = datetime(2026, 9, 5, 0, 0)
    noon = datetime(2026, 9, 5, 12, 0)
    assert format_clock(midnight, UTC, "local", use_24h=False) == "12:00 AM"
    assert format_clock(noon, UTC, "local", use_24h=False) == "12:00 PM"
    assert format_clock(midnight, UTC, "local", use_24h=True) == "00:00"


# ---------------------------------------------------------------------------
# Both
# ---------------------------------------------------------------------------


def test_both_shows_local_first_then_marked_utc():
    assert format_clock(LOCAL, UTC, "both", use_24h=True) == "14:05 / 19:05Z"


def test_both_shows_two_different_readings():
    """A 'both' display that printed the same time twice would be useless."""
    rendered = format_clock(LOCAL, UTC, "both", use_24h=True)
    left, right = rendered.split(" / ")
    assert left != right


# ---------------------------------------------------------------------------
# Date
# ---------------------------------------------------------------------------


def test_date_is_iso_8601_never_locale_order():
    """03/04 is March 4th in the US and April 3rd nearly everywhere else."""
    rendered = format_clock(LOCAL, UTC, "local", use_24h=True, show_date=True)
    assert rendered.startswith("2026-09-05")
    assert "/" not in rendered.split()[0]


def test_date_follows_the_displayed_zone():
    """Around midnight the local and UTC dates differ; the date shown must
    belong to the reading it sits beside, or a log entry lands on the wrong
    day."""
    local_late = datetime(2026, 9, 5, 21, 30)
    utc_next_day = datetime(2026, 9, 6, 2, 30, tzinfo=timezone.utc)
    local_view = format_clock(local_late, utc_next_day, "local", show_date=True)
    utc_view = format_clock(local_late, utc_next_day, "utc", show_date=True)
    assert local_view.startswith("2026-09-05")
    assert utc_view.startswith("2026-09-06")


def test_date_is_omitted_by_default():
    assert format_clock(LOCAL, UTC, "local") == "14:05"


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


def test_unknown_source_falls_back_to_local_rather_than_raising():
    """A bad config value is validated at load time, but the formatter must
    not be the thing that crashes if one ever slips through."""
    assert format_clock(LOCAL, UTC, "gmt") == "14:05"


def test_format_time_is_usable_on_its_own():
    assert format_time(UTC, use_24h=True, utc=True) == "19:05Z"
    assert format_time(LOCAL, use_24h=True, utc=False) == "14:05"
