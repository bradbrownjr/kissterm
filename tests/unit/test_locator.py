"""Maidenhead grid-square conversion -- verified against a real, commonly
cited reference point rather than only round-tripped against itself.
"""

from __future__ import annotations

import pytest

from kissterm.locator import LocatorError, find_grid_in_text, from_grid, from_mgrs, from_utm, to_grid

# ARRL HQ, Newington CT -- widely cited as grid square FN31pr.
ARRL_LAT, ARRL_LON = 41.7148, -72.7273


def test_a_well_known_reference_point_encodes_to_its_known_grid_square():
    assert to_grid(ARRL_LAT, ARRL_LON, 6) == "FN31pr"


def test_four_and_eight_char_precision_share_the_same_prefix():
    assert to_grid(ARRL_LAT, ARRL_LON, 4) == "FN31"
    assert to_grid(ARRL_LAT, ARRL_LON, 8).startswith("FN31pr")


@pytest.mark.parametrize("precision", [4, 6, 8])
def test_decoding_a_grid_square_lands_within_its_own_cell(precision):
    """`from_grid` returns the CENTER of the cell -- it must never be
    further from the original point than half that cell's own size."""
    grid = to_grid(ARRL_LAT, ARRL_LON, precision)
    lat, lon = from_grid(grid)
    # Cell sizes: field 10x20 deg, square 1x2 deg, subsquare 1/24 x 2/24 deg,
    # extended square 1/240 x 2/240 deg. Half of the coarsest (4-char) cell
    # comfortably bounds every precision tested here.
    assert abs(lat - ARRL_LAT) < 0.5
    assert abs(lon - ARRL_LON) < 1.0


def test_subsquare_letters_are_accepted_in_either_case():
    lat_lower, lon_lower = from_grid("fn31pr")
    lat_upper, lon_upper = from_grid("FN31PR")
    assert lat_lower == lat_upper
    assert lon_lower == lon_upper


def test_known_mgrs_reference_converts_to_wgs84():
    """MGRS's published 15TWG example is at 42 N, 93 W to grid precision."""
    lat, lon = from_mgrs("15T WG 00000 49776")
    assert lat == pytest.approx(42.0, abs=0.0001)
    assert lon == pytest.approx(-93.0, abs=0.0001)


def test_utm_requires_an_explicit_hemisphere_and_converts_to_wgs84():
    # Zone 31's central meridian is 3 E; this is the standard UTM example at 42 N.
    lat, lon = from_utm("31 N 500000 4649776.22482")
    assert lat == pytest.approx(42.0, abs=0.0001)
    assert lon == pytest.approx(3.0, abs=0.0001)


@pytest.mark.parametrize("converter,reference", [(from_mgrs, "18I BAD"), (from_utm, "18N 691875 4576931")])
def test_malformed_projected_coordinates_are_refused(converter, reference):
    with pytest.raises(LocatorError):
        converter(reference)


@pytest.mark.parametrize(
    "lat,lon",
    [
        (0.0, 0.0),
        (90.0, 180.0),
        (-90.0, -180.0),
        (41.7148, -72.7273),
        (-33.8688, 151.2093),  # Sydney -- southern and eastern hemispheres
    ],
)
def test_round_trip_stays_within_one_subsquare_cell(lat, lon):
    grid = to_grid(lat, lon, 6)
    back_lat, back_lon = from_grid(grid)
    # Subsquare cell: 1/24 deg lat (~0.042), 2/24 deg lon (~0.083).
    assert abs(back_lat - lat) <= 1.0 / 24
    assert abs(back_lon - lon) <= 2.0 / 24


def test_bad_precision_is_reported_not_raised_as_something_else():
    with pytest.raises(LocatorError, match="precision"):
        to_grid(41.7, -72.7, 5)


@pytest.mark.parametrize("lat,lon", [(91.0, 0.0), (-91.0, 0.0), (0.0, 181.0), (0.0, -181.0)])
def test_out_of_range_coordinates_are_refused(lat, lon):
    with pytest.raises(LocatorError):
        to_grid(lat, lon, 6)


@pytest.mark.parametrize(
    "text",
    ["", "F", "FN3", "FN31p", "1N31pr", "FZ31pr", "FN31zz", "not a grid at all"],
)
def test_malformed_grid_strings_are_refused(text):
    with pytest.raises(LocatorError):
        from_grid(text)


@pytest.mark.parametrize(
    "text",
    [
        "de W1AW FN31pr",
        "N1ABC BBS -- QTH: FN31pr -- QRV 145.030",
        "de W1AW FN31pr 73",
        "FN31pr",  # the whole string, not just embedded in a longer line
    ],
)
def test_a_grid_square_is_found_in_a_plain_beacon_line(text):
    found = find_grid_in_text(text)
    assert found is not None, f"no grid found in {text!r}"
    grid, lat, lon = found
    assert grid.upper() == "FN31PR"
    assert lat == pytest.approx(41.7, abs=0.5)
    assert lon == pytest.approx(-72.7, abs=1.0)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "73 de KC1XYZ",
        "CQ CQ de KB1QRP",
        "N1ABC-9 BBS v2.1, type H for help",
        "WIDE1-1,WIDE2-1",
        "no grid square anywhere in this sentence",
    ],
)
def test_no_grid_square_is_found_in_ordinary_beacon_text(text):
    assert find_grid_in_text(text) is None


def test_a_token_that_only_starts_like_a_grid_square_does_not_match():
    # "FN31pr" is a valid 6-char grid, but immediately followed by more
    # word characters it is a longer token that only looks like one --
    # e.g. a version string -- and must not match a truncated prefix of
    # itself.
    assert find_grid_in_text("build FN31prXYZ99 failed") is None
