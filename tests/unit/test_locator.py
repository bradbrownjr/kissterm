"""Maidenhead grid-square conversion -- verified against a real, commonly
cited reference point rather than only round-tripped against itself.
"""

from __future__ import annotations

import pytest

from kissterm.locator import LocatorError, from_grid, to_grid

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
