"""The APRS symbol table -- integrity of the sourced data and the filter
helper the Settings symbol picker is built on.
"""

from __future__ import annotations

from kissterm.aprs.symbols import SYMBOLS, filter_symbols, lookup


def test_every_symbol_key_is_unique():
    keys = [s.key for s in SYMBOLS]
    assert len(keys) == len(set(keys))


def test_both_tables_are_present_and_the_same_size():
    primary = [s for s in SYMBOLS if s.table == "/"]
    secondary = [s for s in SYMBOLS if s.table == "\\"]
    assert len(primary) == 92
    assert len(secondary) == 92


def test_every_code_is_one_printable_ascii_character():
    for s in SYMBOLS:
        assert len(s.code) == 1
        assert 0x21 <= ord(s.code) <= 0x7E


def test_well_known_symbols_match_the_documented_table():
    """Spot-check a few entries against the sourced CSV directly, so a
    future edit that garbles the table is caught even without re-fetching
    the source."""
    assert lookup("/", ">").description == "Car"
    assert lookup("/", "-").description == "House"
    assert lookup("/", "#").description == "Digipeater"
    assert lookup("\\", "!").description == "Emergency"
    assert lookup("\\", "#").description == "Digipeater, green star"


def test_unassigned_code_points_have_an_empty_description_not_a_guess():
    entry = lookup("/", '"')
    assert entry is not None
    assert entry.description == ""
    assert "Unassigned" in entry.label


def test_lookup_of_an_unknown_key_returns_none():
    assert lookup("/", "|") is None
    assert lookup("x", "y") is None


def test_filter_with_empty_needle_returns_everything():
    assert filter_symbols("") == SYMBOLS
    assert filter_symbols("   ") == SYMBOLS


def test_filter_matches_description_case_insensitively():
    matches = filter_symbols("car")
    assert lookup("/", ">") in matches  # "Car"
    assert lookup("\\", ">") in matches  # "Red car"
    assert lookup("/", "-") not in matches  # "House"


def test_filter_matches_a_literal_key_too():
    matches = filter_symbols("/>")
    assert lookup("/", ">") in matches


def test_every_symbol_has_a_stable_two_character_key():
    for s in SYMBOLS:
        assert s.key[0] == s.table
        assert s.key[1] == s.code
        assert len(s.key) == 2


def test_ascii_safe_labels_omit_cosmetic_emoji_only():
    car = lookup("/", ">")
    assert car is not None
    assert car.display_label(ascii_safe=True) == "Car (/>)"
    assert car.display_label(ascii_safe=False) == car.label
