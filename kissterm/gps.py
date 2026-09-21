"""A defensive NMEA-0183 reader for an attached GPS receiver.

GPS is not a KISS transport: it only reads a local serial stream and never
transmits. Consumers ask for its current fix when needed; it never writes a
moving position into persistent configuration.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass

from .discovery import DiscoveredDevice, discover_serial

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GpsFix:
    latitude: float
    longitude: float
    altitude_m: float | None = None
    speed_knots: float | None = None
    course_degrees: float | None = None


def _checksum_ok(sentence: str) -> bool:
    if not sentence.startswith("$") or "*" not in sentence:
        return False
    body, supplied = sentence[1:].rsplit("*", 1)
    try:
        expected = int(supplied, 16)
    except ValueError:
        return False
    value = 0
    for char in body:
        value ^= ord(char)
    return len(supplied) == 2 and value == expected


def _coordinate(raw: str, hemisphere: str, degrees: int) -> float | None:
    try:
        value = float(raw)
        whole = int(value // 100)
        minutes = value - whole * 100
    except ValueError:
        return None
    if whole > (90 if degrees == 2 else 180) or not 0 <= minutes < 60:
        return None
    if hemisphere not in (("N", "S") if degrees == 2 else ("E", "W")):
        return None
    return (-1 if hemisphere in ("S", "W") else 1) * (whole + minutes / 60)


def parse_sentence(sentence: str) -> GpsFix | None:
    """Return a valid GGA/RMC fix, otherwise ``None`` without raising."""
    sentence = sentence.strip()
    if not _checksum_ok(sentence):
        return None
    fields = sentence[1:sentence.index("*")].split(",")
    kind = fields[0][-3:] if fields else ""
    try:
        if kind == "GGA" and len(fields) >= 10 and fields[6] not in ("", "0"):
            lat = _coordinate(fields[2], fields[3], 2)
            lon = _coordinate(fields[4], fields[5], 3)
            altitude = float(fields[9]) if fields[9] else None
            return GpsFix(lat, lon, altitude) if lat is not None and lon is not None else None
        if kind == "RMC" and len(fields) >= 9 and fields[2] == "A":
            lat = _coordinate(fields[3], fields[4], 2)
            lon = _coordinate(fields[5], fields[6], 3)
            speed = float(fields[7]) if fields[7] else None
            course = float(fields[8]) if fields[8] else None
            return GpsFix(lat, lon, speed_knots=speed, course_degrees=course) if lat is not None and lon is not None else None
    except ValueError:
        pass
    return None


async def discover_serial_gps() -> list[DiscoveredDevice]:
    """Reuse serial discovery, ranking GPS-labelled ports ahead of TNCs."""
    devices = await discover_serial()
    return sorted(
        devices,
        key=lambda item: ("gps" not in f"{item.detail} {item.note}".lower(), -item.confidence),
    )


class GpsReader:
    """Continuously read one serial NMEA source without leaking failures."""

    def __init__(self, device: str, baud: int = 4800) -> None:
        self.device, self.baud, self.fix, self.error = device, baud, None, ""
        self._callbacks: list[Callable[[GpsFix | None], None]] = []
        self._task: asyncio.Task[None] | None = None
        self._serial = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def subscribe(self, callback: Callable[[GpsFix | None], None]) -> Callable[[], None]:
        self._callbacks.append(callback)
        def unsubscribe() -> None:
            with contextlib.suppress(ValueError): self._callbacks.remove(callback)
        return unsubscribe

    def start(self) -> None:
        if not self.running and self.device.strip():
            self._task = asyncio.create_task(self._run(), name=f"kissterm-gps:{self.device}")

    def cancel(self) -> None:
        task, self._task = self._task, None
        if task is not None: task.cancel()

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError): await task

    def feed_sentence(self, sentence: str) -> None:
        fix = parse_sentence(sentence)
        kind = sentence[3:6] if sentence.startswith("$") else ""
        if fix is None and kind not in ("GGA", "RMC"):
            return
        if fix is not None and self.fix is not None:
            # GGA contributes altitude while RMC contributes motion. Preserve
            # the other sentence's recent fields for Smart Beaconing's future
            # use without pretending either source is persistent state.
            fix = GpsFix(
                fix.latitude, fix.longitude,
                altitude_m=fix.altitude_m if fix.altitude_m is not None else self.fix.altitude_m,
                speed_knots=fix.speed_knots if fix.speed_knots is not None else self.fix.speed_knots,
                course_degrees=fix.course_degrees if fix.course_degrees is not None else self.fix.course_degrees,
            )
        if fix == self.fix: return
        self.fix = fix
        for callback in tuple(self._callbacks):
            try: callback(fix)
            except Exception: log.exception("GPS subscriber failed")

    async def _run(self) -> None:
        try:
            import serial  # type: ignore[import-untyped]
            loop = asyncio.get_running_loop()
            self._serial = await loop.run_in_executor(None, lambda: serial.Serial(self.device, self.baud, timeout=0.25))
            while True:
                line = await loop.run_in_executor(None, self._serial.readline)
                if line: self.feed_sentence(line.decode("ascii", errors="ignore"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error, self.fix = str(exc), None
            log.warning("GPS reader %s stopped: %s", self.device, exc)
        finally:
            serial, self._serial = self._serial, None
            if serial is not None:
                with contextlib.suppress(Exception): serial.close()
