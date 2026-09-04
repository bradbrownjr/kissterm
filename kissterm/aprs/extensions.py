"""Small decoders shared by more than one APRS format: trailing-field
extraction, and the base-91 numeric codec.

Position reports, Mic-E, and (through position reports) objects and items all
end with an open-ended comment field that *may* carry one or more of a fixed
handful of conventional extensions: a leading course/speed pair, an in-comment
``/A=nnnnnn`` altitude, ``PHGnnnn`` power-height-gain, ``RNGnnnn`` range, or
``DFSnnnn`` direction-finding data. Centralizing `extract_extras` here means a
station that packs three of these into one comment (seen in the wild) gets
all three lifted out correctly no matter which top-level format carried the
comment, and a fix to one extension's regex does not require hunting down
every format that might also carry it. Field widths in the wire format are
fixed but not perfectly uniform across vendors, so extraction is regex-based
per field rather than a strict fixed-column split -- a station that omits or
reorders an extension just leaves the corresponding `Position` field `None`
instead of failing the whole decode.

`b91_decode` lives here rather than in `position.py` even though the
compressed position format is its main user: `mice.py` also needs it (for
Mic-E's own, differently-scaled altitude extension), and this package's rule
is that format modules only import `types` and `extensions` -- never each
other -- so nothing here should force `mice.py` to import `position.py` just
to decode a number.

Every function here may raise (`ValueError` on anything that does not look
like a valid extension or a valid base-91 digit); nothing in this module
catches its own exceptions. The parsers that call these
(`position.py`, `mice.py`) are themselves called only from `parse.py`'s
`_dispatch`, which is wrapped by `parse_packet`'s catch-all -- that is where
this package's "never raise on malformed input" invariant is actually
enforced, not here.
"""

from __future__ import annotations

import re

#: Matches a leading course/speed pair in a comment, e.g. "088/036" -- the
#: conventional way to attach course (degrees) and speed (knots) to an
#: uncompressed position that has no PHG data.
_CSE_SPD_RE = re.compile(r"^(\d{3})/(\d{3})")
_ALTITUDE_RE = re.compile(r"/A=(-?\d{6})")
_PHG_RE = re.compile(r"PHG(\d{4})")
_RNG_RE = re.compile(r"RNG(\d{4})")
_DFS_RE = re.compile(r"DFS(\d{4})")


def extract_extras(comment: str) -> tuple[str, dict[str, object]]:
    """Pull the common trailing extensions (course/speed, altitude, PHG,
    range, DFS) out of a comment and return the cleaned remainder plus a
    dict of `Position` kwargs. Shared by every format that ends in free text.
    """
    extras: dict[str, object] = {}

    m = _CSE_SPD_RE.match(comment)
    if m:
        extras["course"] = int(m.group(1))
        extras["speed_knots"] = float(int(m.group(2)))
        comment = comment[m.end() :]

    for pattern, key, cast in (
        (_ALTITUDE_RE, "altitude_ft", int),
        (_PHG_RE, "phg", str),
        (_RNG_RE, "range_mi", lambda v: float(int(v))),
        (_DFS_RE, "dfs", str),
    ):
        m = pattern.search(comment)
        if m:
            extras[key] = cast(m.group(1))
            comment = comment[: m.start()] + comment[m.end() :]

    return comment.strip(), extras


def b91_decode(s: str) -> int:
    """Decode a base-91 string (each byte `chr(33)`..`chr(123)`, i.e. ``!``
    through ``{``) to an integer, most-significant digit first.

    Used by the compressed position format for latitude/longitude and by
    Mic-E for its own altitude extension -- two different scalings of the
    same digit alphabet, which is why the codec is shared but the formula
    that turns the integer into a coordinate or an altitude is not.
    """
    val = 0
    for ch in s:
        code = ord(ch) - 33
        if not 0 <= code <= 90:
            raise ValueError(f"byte {ch!r} is not a valid base-91 digit")
        val = val * 91 + code
    return val
