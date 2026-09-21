"""Pure, passive watched-callsign notification decisions.

This module only examines address claims already decoded from a received AX.25
frame.  It neither decodes frames nor performs I/O; ``ui.app`` remains the
single receive fan-out subscriber and delivery owner.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .ax25.address import AX25Address, AX25Path


def normalize_callsigns(values: list[str]) -> set[str]:
    """Return valid, normalized callsign claims; malformed input is ignored."""
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        try:
            normalized.add(str(AX25Address.parse(value)))
        except ValueError:
            continue
    return normalized


def claimed_callsigns(path: AX25Path) -> set[str]:
    """The source and digipeater address claims carried by a received frame."""
    return {str(path.source), *(str(repeater) for repeater in path.repeaters)}


def in_quiet_hours(now: datetime, start_hour: int | None, end_hour: int | None) -> bool:
    """Whether ``now`` is inside an optional local-time quiet-hours interval."""
    if start_hour is None or end_hour is None or start_hour == end_hour:
        return False
    hour = now.hour
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


@dataclass
class WatchNotifier:
    """Bounded notification gate, with injected clocks for deterministic tests."""

    cooldown_seconds: float
    hourly_cap: int
    quiet_start_hour: int | None = None
    quiet_end_hour: int | None = None

    def __post_init__(self) -> None:
        self._last_notified: dict[str, float] = {}
        self._hour: tuple[int, int, int, int] | None = None
        self._count = 0

    def allow(
        self,
        callsign: str,
        *,
        now_monotonic: float,
        now_local: datetime,
        app_active: bool = False,
    ) -> bool:
        """Record and allow one claim, unless a bounded suppression applies."""
        if app_active or in_quiet_hours(now_local, self.quiet_start_hour, self.quiet_end_hour):
            return False
        bucket = (now_local.year, now_local.month, now_local.day, now_local.hour)
        if bucket != self._hour:
            self._hour, self._count = bucket, 0
        if self._count >= self.hourly_cap:
            return False
        last = self._last_notified.get(callsign)
        if last is not None and now_monotonic - last < self.cooldown_seconds:
            return False
        self._last_notified[callsign] = now_monotonic
        self._count += 1
        return True
