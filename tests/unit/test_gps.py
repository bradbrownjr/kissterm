"""NMEA parsing is deliberately pure; no receiver is needed to prove it."""

from __future__ import annotations

import pytest

from kissterm import _isolate

_isolate.isolate()

from kissterm.discovery import DiscoveredDevice  # noqa: E402
from kissterm import gps  # noqa: E402
from kissterm.gps import GpsReader, parse_sentence  # noqa: E402


def test_gga_position_and_altitude_are_parsed():
    fix = parse_sentence("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47")
    assert fix is not None
    assert round(fix.latitude, 5) == 48.1173
    assert round(fix.longitude, 5) == 11.51667
    assert fix.altitude_m == 545.4


def test_rmc_position_speed_and_course_are_parsed():
    fix = parse_sentence("$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A")
    assert fix is not None
    assert fix.speed_knots == 22.4
    assert fix.course_degrees == 84.4


def test_bad_checksum_and_no_fix_never_become_a_position():
    assert parse_sentence("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*00") is None
    assert parse_sentence("$GPRMC,123519,V,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*7D") is None


def test_no_fix_sentence_clears_reader_and_gga_rmc_fields_combine():
    reader = GpsReader("/dev/not-used-in-this-test")
    reader.feed_sentence("$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A")
    reader.feed_sentence("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47")
    assert reader.fix is not None
    assert reader.fix.altitude_m == 545.4
    assert reader.fix.speed_knots == 22.4
    reader.feed_sentence("$GPRMC,123519,V,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*7D")
    assert reader.fix is None


@pytest.mark.asyncio
async def test_gps_port_scan_reuses_serial_discovery_and_ranks_gps_first(monkeypatch):
    async def found():
        return [
            DiscoveredDevice("serial", "/dev/ttyUSB0", "FTDI bridge", 0.5, {}),
            DiscoveredDevice("serial", "/dev/ttyUSB1", "GPS receiver", 0.1, {}),
        ]

    monkeypatch.setattr(gps, "discover_serial", found)
    devices = await gps.discover_serial_gps()
    assert [device.label for device in devices] == ["/dev/ttyUSB1", "/dev/ttyUSB0"]
