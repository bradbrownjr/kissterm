"""Cross-check kissterm's Mic-E decoder against an independent implementation.

kissterm's own Mic-E fixtures (tests/unit/test_aprs.py) are hand-built
against kissterm's own formulas, which is exactly the failure mode that let
`_MICE_MESSAGES` ship with an inverted bit table for a whole session: the
fixtures agreed with the bug because they were built to. This file exists to
break that circularity by generating Mic-E frames from first principles
(this module's own `_encode_mice`, independent of anything in
`kissterm/aprs/`) and decoding each one through BOTH kissterm's
`parse_mic_e` and `aprslib.parsing.mice.parse_mice`, then asserting the two
agree. `aprslib` is a mature, independently-maintained APRS library (GPLv2 --
see pyproject.toml's `dev` extra comment for why it stays test-only and is
never imported by `kissterm` itself).

This is how the inverted-table bug actually got found (against real captured
traffic, not this generator) and how a second, narrower bug was found right
after it: N/S, the longitude-offset flag, and E/W are flagged by the
CUSTOM-range letters (P-Y/Z) specifically, not "any letter" the way the
message bits at positions 1-3 are -- `bits[i] == 1` happened to agree with
this on every real frame captured so far (no real transmitter puts an A-K
letter in positions 4-6, since there is no std/custom choice to make for a
single flag), but silently got N/S backwards for that case. Confirmed
against both aprslib and Direwolf's decode_aprs.c before fixing it.

Two things this suite intentionally does NOT try to reconcile, both real and
both worth understanding before touching this file again:

  - **"std" and "custom" mean different, near-opposite things to the two
    libraries.** kissterm calls a message A-K-encoded "std" and P-Y/Z-encoded
    "custom" (matching the letters actually used) and, for "custom", reuses
    the same 8 real words with a "(custom)" suffix -- see `_MICE_MESSAGES`'s
    docstring. aprslib instead picks a whole different TABLE: its "CUSTOM"
    table (generic "C0: Custom-0" labels) is selected whenever an A-K letter
    is present anywhere in positions 1-3, and its "STD" table (the real
    words) only when none is. So a kissterm "std" message (A-K letters) is
    exactly the case where aprslib falls back to a generic, non-comparable
    label -- there is no bug to chase there, just two reasonable but
    different design choices for the same wire format. The check below
    compares against a canonical word derived directly from the bit pattern
    (identical to both real tables) and only compares text against aprslib
    directly when aprslib actually returned a real word rather than a
    generic "Custom-N" placeholder.
  - **The 180-189/190-199 longitude wraparound correction** in
    `parse_mic_e` is not exercised here. The generator below never needs it
    (0-179 is reachable without landing in that branch), and fabricating an
    encoding that specifically triggers it risks testing a byte pattern no
    real transmitter produces rather than verifying one that does. That
    correction remains unverified against real traffic.
"""

from __future__ import annotations

import pytest

aprslib = pytest.importorskip("aprslib")

from kissterm.aprs.mice import parse_mic_e  # noqa: E402

_STD = "ABCDEFGHIJ"
_CUSTOM = "PQRSTUVWXY"

#: Canonical bit-pattern -> real-word mapping, identical to the corrected
#: kissterm _MICE_MESSAGES and to aprslib's MTYPE_TABLE_STD -- the "spec",
#: independent of either library's own custom/std table-selection quirks.
_CANONICAL = {
    (1, 1, 1): "Off Duty",
    (1, 1, 0): "En Route",
    (1, 0, 1): "In Service",
    (1, 0, 0): "Returning",
    (0, 1, 1): "Committed",
    (0, 1, 0): "Special",
    (0, 0, 1): "Priority",
    (0, 0, 0): "Emergency",
}


def _encode_mice(
    lat: float,
    lon: float,
    course: int,
    speed_knots: float,
    msg_bits: tuple[int, int, int],
    msg_codeset: str,
) -> tuple[str, bytes]:
    """Build a (destination_callsign, info) pair from first principles.

    Independent of kissterm/aprs/mice.py's own formulas -- this exists so
    the cross-check isn't just kissterm agreeing with itself. See the module
    docstring for what this deliberately does not cover.
    """
    north = lat >= 0
    alat = abs(lat)
    deg = int(alat)
    minutes = (alat - deg) * 60
    min_int = int(minutes)
    min_frac = round((minutes - min_int) * 100)
    if min_frac >= 100:
        min_frac = 0
        min_int += 1
    digits = [deg // 10, deg % 10, min_int // 10, min_int % 10, min_frac // 10, min_frac % 10]

    letters = _STD if msg_codeset == "std" else _CUSTOM
    chars = [letters[digits[i]] if msg_bits[i] else str(digits[i]) for i in range(3)]

    west = lon < 0
    alon = abs(lon)
    lon_deg = int(alon)
    lon_minutes = (alon - lon_deg) * 60
    lon_min_int = int(lon_minutes)
    lon_min_frac = round((lon_minutes - lon_min_int) * 100)
    if lon_min_frac >= 100:
        lon_min_frac = 0
        lon_min_int += 1

    for i, flag in zip((3, 4, 5), (north, False, west)):
        chars.append(_CUSTOM[digits[i]] if flag else str(digits[i]))
    dest = "".join(chars)

    if lon_deg < 100:
        lon_deg_byte = lon_deg + 28
    else:
        lon_deg_byte = (lon_deg - 100) + 28  # long-offset flag stays False here on purpose

    speed = round(speed_knots)
    sp = speed // 10
    dc = (speed % 10) * 10 + course // 100
    se = course % 100

    body = bytes(
        [
            lon_deg_byte,
            lon_min_int + 28,
            lon_min_frac + 28,
            sp + 28,
            dc + 28,
            se + 28,
            ord(">"),
            ord("/"),
        ]
    )
    return dest, b"`" + body


# Longitude degrees >= 10 (and, past the +100 offset boundary, >= 110) and
# minutes >= 10: aprslib's own input-validation regex requires the encoded
# bytes to be above a minimum (see aprslib/parsing/mice.py's `re.match`),
# which a near-zero degree or minutes value falls below. Real GPS fixes
# rarely land exactly on tiny values like these anyway.
_LAT_LON_CASES = [
    (42.355, -71.250, 45, 30),
    (-33.850, 151.200, 270, 12),
    (18.500, 66.500, 0, 0),
    (89.983, 179.983, 359, 125),
    (-55.750, -110.500, 180, 60),
]

_MESSAGE_CASES = [
    ((0, 0, 0), "std"),
    ((0, 0, 1), "std"),
    ((0, 1, 0), "std"),
    ((0, 1, 1), "std"),
    ((1, 0, 0), "std"),
    ((1, 0, 1), "std"),
    ((1, 1, 0), "std"),
    ((1, 1, 1), "std"),
    ((0, 0, 1), "custom"),
    ((1, 1, 1), "custom"),
    ((1, 0, 1), "custom"),
]


@pytest.mark.parametrize("lat,lon,course,speed", _LAT_LON_CASES)
@pytest.mark.parametrize("msg_bits,msg_codeset", _MESSAGE_CASES)
def test_mic_e_agrees_with_aprslib(
    lat: float,
    lon: float,
    course: int,
    speed: float,
    msg_bits: tuple[int, int, int],
    msg_codeset: str,
) -> None:
    dest, info = _encode_mice(lat, lon, course, speed, msg_bits, msg_codeset)

    ours = parse_mic_e(info, dest)
    _, theirs = aprslib.parsing.mice.parse_mice(dest, info[1:].decode("latin-1"))

    assert round(ours.latitude, 3) == round(theirs["latitude"], 3)
    assert round(ours.longitude, 3) == round(theirs["longitude"], 3)
    assert ours.course == theirs["course"]
    assert round(ours.speed_knots, 1) == round(theirs["speed"] / 1.852, 1)

    expected_word = _CANONICAL[msg_bits]
    ours_word = ours.mic_e_message.removesuffix(" (custom)") if ours.mic_e_message else None
    assert ours_word == expected_word

    theirs_text = theirs["mtype"].split(": ", 1)[-1]
    if not theirs_text.startswith("Custom-"):
        # aprslib gave a real word (its STD table was selected -- no A-K
        # letter present in positions 1-3), so it must match too.
        assert theirs_text == expected_word