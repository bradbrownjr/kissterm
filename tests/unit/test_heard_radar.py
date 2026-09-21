"""Pure geometry and safety coverage for the read-only Heard radar."""

from __future__ import annotations

from kissterm.heard import HeardEntry
from kissterm.ui.heard_pane import _STALE_SECONDS, render_radar


def _entry(
    callsign: str, position: tuple[float, float] | None, *, last_heard: float = 1_000.0
) -> HeardEntry:
    return HeardEntry(callsign, 1_000.0, last_heard, last_position=position)


def test_radar_places_cardinal_received_claims_around_the_operator():
    rendered = render_radar(
        [_entry("NORTH", (1.0, 0.0)), _entry("EAST", (0.0, 1.0))],
        (0.0, 0.0),
        now=1_001.0,
    )
    lines = rendered.splitlines()
    grid = lines[1:16]
    center = len(grid) // 2
    assert "@" in grid[center]
    assert "1" in "\n".join(grid[:center])
    assert "2" in grid[center]
    assert "1 NORTH" in rendered
    assert "2 EAST" in rendered


def test_radar_omits_invalid_or_unknown_claims_and_marks_stale_ones():
    rendered = render_radar(
        [
            _entry("UNKNOWN", None),
            _entry("BAD", (91.0, 0.0)),
            _entry("OLD", (1.0, 0.0), last_heard=1_000.0),
        ],
        (0.0, 0.0),
        now=1_000.0 + _STALE_SECONDS + 1,
    )
    assert "no known position: 2." in rendered
    assert "1 OLD" in rendered
    assert "1 OLD" in rendered and " ~" in rendered
    assert "UNKNOWN" not in rendered
    assert "BAD" not in rendered


def test_radar_requires_a_configured_operator_position_without_guessing_one():
    rendered = render_radar([_entry("NORTH", (1.0, 0.0))], None, now=1_001.0)
    assert "needs this station's position" in rendered
    assert "Received position claims: 1; no known position: 0." in rendered
