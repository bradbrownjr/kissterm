"""Deterministic, local tests for passive watched-callsign alerts."""

from datetime import datetime, timezone

from kissterm.ax25.address import AX25Address, AX25Path
from kissterm.watched_notify import WatchNotifier, claimed_callsigns, normalize_callsigns


def _at(hour: int) -> datetime:
    return datetime(2026, 9, 18, hour, tzinfo=timezone.utc)


def test_normalizes_source_and_digipeater_claims_and_drops_malformed_values():
    path = AX25Path(AX25Address.parse("APRS"), AX25Address.parse("n1abc-2"),
                    (AX25Address.parse("w1aw-1"),))
    assert claimed_callsigns(path) == {"N1ABC-2", "W1AW-1"}
    assert normalize_callsigns(["n1abc-2", "bad-call-sign", 4]) == {"N1ABC-2"}


def test_per_callsign_cooldown_does_not_block_a_different_claim():
    gate = WatchNotifier(cooldown_seconds=60, hourly_cap=10)
    assert gate.allow("N1ABC", now_monotonic=0, now_local=_at(10))
    assert not gate.allow("N1ABC", now_monotonic=59, now_local=_at(10))
    assert gate.allow("W1AW", now_monotonic=59, now_local=_at(10))
    assert gate.allow("N1ABC", now_monotonic=60, now_local=_at(10))


def test_hourly_cap_exhausts_and_resets_on_the_next_clock_hour():
    gate = WatchNotifier(cooldown_seconds=0, hourly_cap=2)
    assert gate.allow("N1ABC", now_monotonic=0, now_local=_at(10))
    assert gate.allow("W1AW", now_monotonic=1, now_local=_at(10))
    assert not gate.allow("K1XYZ", now_monotonic=2, now_local=_at(10))
    assert gate.allow("K1XYZ", now_monotonic=3, now_local=_at(11))


def test_quiet_hours_cross_midnight_and_active_use_suppress_without_consuming_cap():
    gate = WatchNotifier(cooldown_seconds=0, hourly_cap=1, quiet_start_hour=22, quiet_end_hour=7)
    assert not gate.allow("N1ABC", now_monotonic=0, now_local=_at(22))
    assert not gate.allow("N1ABC", now_monotonic=1, now_local=_at(6))
    assert not gate.allow("N1ABC", now_monotonic=2, now_local=_at(12), app_active=True)
    assert gate.allow("N1ABC", now_monotonic=3, now_local=_at(12))
