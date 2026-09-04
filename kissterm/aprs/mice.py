"""Mic-E decoding: the position encoding smuggled into a UI frame's destination callsign.

Mic-E is the fiddliest decoder in this package and the most commonly botched
in hobbyist code, which is why it gets its own file: latitude digits,
hemisphere, the longitude hundred-degree offset, and the message-type bits
are not in the information field at all -- they are encoded into the six
characters of the AX.25 *destination* callsign (which is why kissterm keeps
raw, unshifted callsign text around in `AX25Address` rather than discarding
it as "just an address" -- see `kissterm/ax25/address.py`). Only longitude
minutes, course, speed, and the symbol come from the information field, and
even those are byte-offset-28 encoded rather than plain ASCII digits.

The most error-prone details, if this ever needs a fix:
  - `_MICE_TABLE` maps each of the 6 destination-callsign characters to a
    (digit-or-space, message-bit, codeset) triple; position 1-3 feeds the
    3-bit message code, position 4-6 doubles as N/S, the +100 longitude
    offset flag, and E/W.
  - The longitude-degree offset (+28, then +100 if flagged, then the
    180-189/190-199 wraparound corrections) and the speed/course wraparound
    (subtract 800 / 400 respectively above their max) are both easy to get
    subtly backwards; `tests/unit/test_aprs.py`'s two hemisphere-combination
    tests exist specifically to catch that class of bug.
  - The N/S, longitude-offset, and E/W bit convention (bit=1 -> N / +100 / W)
    is implemented per the most common description of the format but was not
    independently verified against a captured frame -- flag any change here
    for extra scrutiny.

Like every other parser in this package, `parse_mic_e` must be safe to call
from `parse.py`'s dispatcher without a caller-side try/except: it is free to
raise `ValueError`/`IndexError` internally on malformed input (a short info
field, an invalid destination-callsign character), but it must never depend
on anything past `parse_packet`'s catch-all to keep the app alive.
"""

from __future__ import annotations

import re

from .extensions import b91_decode, extract_extras
from .types import Position

__all__ = ["parse_mic_e"]

#: Destination-callsign character -> (digit-or-space, message-bit, codeset).
#: ``codeset`` is "std" for the A-K letters, "custom" for P-Z, "digit" for a
#: plain 0-9 or the all-zero space markers K/L/Z. Position 1-3 characters
#: feed the 3-bit message code; position 4-6 characters double as the N/S,
#: longitude-offset, and E/W flags (bit=1 -> N / +100 / W, bit=0 -> S / no
#: offset / E), which is the convention this implementation follows -- flagged
#: as the one part of Mic-E decode not independently verified against a
#: captured frame.
_MICE_TABLE: dict[str, tuple[str, int, str]] = {}
for _c in "0123456789":
    _MICE_TABLE[_c] = (_c, 0, "digit")
for _i, _c in enumerate("ABCDEFGHIJ"):
    _MICE_TABLE[_c] = (str(_i), 1, "std")
_MICE_TABLE["K"] = (" ", 1, "std")
_MICE_TABLE["L"] = (" ", 0, "digit")
for _i, _c in enumerate("PQRSTUVWXY"):
    _MICE_TABLE[_c] = (str(_i), 1, "custom")
_MICE_TABLE["Z"] = (" ", 1, "custom")

#: Message code (bit_A, bit_B, bit_C) -> status text, both codesets share the
#: same 8 meanings by convention except "Emergency" is unambiguous either way.
_MICE_MESSAGES: dict[tuple[int, int, int], str] = {
    (1, 1, 1): "Emergency",
    (1, 1, 0): "Priority",
    (1, 0, 1): "Special",
    (1, 0, 0): "Committed",
    (0, 1, 1): "Returning",
    (0, 1, 0): "In Service",
    (0, 0, 1): "En Route",
    (0, 0, 0): "Off Duty",
}

_MICE_ALT_RE = re.compile(r"^([\x21-\x7b]{3})\}")


def parse_mic_e(info: bytes, dest_callsign: str | None) -> Position:
    """Decode Mic-E: latitude, hemisphere, longitude offset, and message type
    come from the destination callsign; longitude minutes, course, speed, and
    symbol come from the information field.
    """
    if not dest_callsign or len(dest_callsign) != 6:
        raise ValueError("Mic-E needs a 6-character destination callsign")

    digits: list[str] = []
    bits: list[int] = []
    codesets: list[str] = []
    for ch in dest_callsign:
        entry = _MICE_TABLE.get(ch)
        if entry is None:
            raise ValueError(f"invalid Mic-E destination character {ch!r}")
        digit, bit, codeset = entry
        digits.append(digit)
        bits.append(bit)
        codesets.append(codeset)

    def _z(d: str) -> str:
        return "0" if d == " " else d

    ambiguity = sum(1 for d in digits if d == " ")
    deg = int(_z(digits[0]) + _z(digits[1]))
    min_int = int(_z(digits[2]) + _z(digits[3]))
    min_frac = int(_z(digits[4]) + _z(digits[5]))
    lat = deg + (min_int + min_frac / 100) / 60
    north = bits[3] == 1
    if not north:
        lat = -lat
    long_offset = bits[4] == 1
    west = bits[5] == 1

    msg_bits = (bits[0], bits[1], bits[2])
    msg_codeset = next((cs for cs in codesets[0:3] if cs != "digit"), "std")
    message = _MICE_MESSAGES.get(msg_bits, "Unknown")
    if msg_codeset == "custom" and message != "Emergency":
        message = f"{message} (custom)"

    body = info[1:]
    if len(body) < 8:
        raise ValueError("Mic-E info field truncated")

    lon_deg = body[0] - 28
    if long_offset:
        lon_deg += 100
    if 180 <= lon_deg <= 189:
        lon_deg -= 80
    elif 190 <= lon_deg <= 199:
        lon_deg -= 190

    lon_min = body[1] - 28
    if lon_min >= 60:
        lon_min -= 60
    lon_hmin = body[2] - 28

    lon = lon_deg + (lon_min + lon_hmin / 100) / 60
    if west:
        lon = -lon

    sp, dc, se = body[3] - 28, body[4] - 28, body[5] - 28
    speed = sp * 10 + dc // 10
    course = (dc % 10) * 100 + se
    if speed >= 800:
        speed -= 800
    if course >= 400:
        course -= 400

    sym_code = chr(body[6])
    sym_table = chr(body[7])

    remainder = info[9:].decode("ascii", "replace")
    altitude_ft: int | None = None
    m = _MICE_ALT_RE.match(remainder)
    if m:
        altitude_m = b91_decode(m.group(1)) - 10000
        altitude_ft = round(altitude_m * 3.28084)
        remainder = remainder[m.end() :]

    comment, extras = extract_extras(remainder)
    if altitude_ft is None:
        altitude_ft = extras.pop("altitude_ft", None)  # type: ignore[assignment]
    else:
        extras.pop("altitude_ft", None)

    return Position(
        latitude=lat,
        longitude=lon,
        symbol_table=sym_table,
        symbol_code=sym_code,
        course=course,
        speed_knots=float(speed),
        altitude_ft=altitude_ft,
        ambiguity=ambiguity,
        comment=comment,
        mic_e_message=message,
        **extras,
    )
