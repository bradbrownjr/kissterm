"""Bearing/distance math -- verified against known great-circle facts rather
than round-tripped against itself, same discipline `test_locator.py` uses.
"""

from __future__ import annotations

import math

import pytest

from kissterm.geo import bearing_distance_mi, compass_point

#: One degree of longitude at the equator is the classic reference distance:
#: circumference / 360 = 24901 mi / 360 =~ 69.17 mi.
_ONE_DEGREE_AT_EQUATOR_MI = 69.17


def test_one_degree_of_longitude_at_the_equator_is_about_69_miles_east():
    bearing, distance = bearing_distance_mi(0.0, 0.0, 0.0, 1.0)
    assert distance == pytest.approx(_ONE_DEGREE_AT_EQUATOR_MI, abs=0.5)
    assert bearing == pytest.approx(90.0, abs=0.01)


def test_one_degree_of_latitude_is_about_69_miles_north():
    bearing, distance = bearing_distance_mi(0.0, 0.0, 1.0, 0.0)
    assert distance == pytest.approx(69.0, abs=0.5)
    assert bearing == pytest.approx(0.0, abs=0.01)


def test_south_and_west_come_back_as_bearings_past_180():
    bearing, distance = bearing_distance_mi(0.0, 0.0, -1.0, -1.0)
    assert 180.0 < bearing < 270.0
    assert distance > 0


def test_the_same_point_is_zero_distance_with_no_meaningful_bearing_crash():
    # Bearing is undefined at zero distance (atan2(0, 0) == 0 by convention)
    # -- the point is that this must not raise or return NaN.
    bearing, distance = bearing_distance_mi(10.0, 20.0, 10.0, 20.0)
    assert distance == pytest.approx(0.0, abs=1e-6)
    assert not math.isnan(bearing)


@pytest.mark.parametrize(
    "bearing,expected",
    [
        (0.0, "N"),
        (45.0, "NE"),
        (90.0, "E"),
        (135.0, "SE"),
        (180.0, "S"),
        (225.0, "SW"),
        (270.0, "W"),
        (315.0, "NW"),
        (359.9, "N"),
        (15.0, "NNE"),
    ],
)
def test_compass_point_labels(bearing, expected):
    assert compass_point(bearing) == expected
