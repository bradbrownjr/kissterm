"""APRS payload encoding -- the minimum needed to transmit.

`kissterm.aprs.parse` is deliberately permissive: a decoder has no way to
reject a malformed frame that already exists on RF, so it does its best and
falls back to ``kind="unparsed"`` rather than raising. Encoding is the mirror
image and is deliberately strict. A transmitted packet is not "our problem" in
the same way a received one is -- it goes out over the air (or into an IGate
feed) and pollutes the shared APRS namespace for every other station and
every other program's decoder if it is wrong. There is no "unparsed" outcome
available to a transmitter; there is only "sent a bad packet" or "did not
send." This module therefore validates and clamps every input and raises
`ValueError` rather than silently emitting something a stricter decoder than
kissterm's own would choke on.

Only the uncompressed position format is implemented here, not the
compressed one: uncompressed is the readable, universally-supported encoding,
and kissterm's own use case (beaconing a station's own position) has no need
for the 2-byte-per-coordinate savings compression exists for.
"""

from __future__ import annotations

import math
import re

from ..ax25.address import AX25Address, AX25Path
from ..ax25.frame import AX25Frame, PID_NO_LAYER3, UType

__all__ = ["position_report", "object_report", "status", "message", "ack", "beacon_frame"]

#: Conservative cap on the free-text portion of a transmitted packet. AX.25
#: itself allows much more, but a very long unproto frame is far more likely
#: to be a bug than a deliberate beacon comment, and many digipeaters and
#: IGates silently truncate long info fields anyway.
_MAX_COMMENT = 100
_TIMESTAMP_RE = re.compile(r"^\d{6}[zh/]$")
_MSG_NUMBER_RE = re.compile(r"^[A-Za-z0-9]{1,5}$")
_OBJECT_NAME_RE = re.compile(r"^[ -~]{1,9}$")
_OBJECT_COMMENT_MAX = 43


def _clean_text(text: str) -> str:
    """Strip control characters a KISS/AX.25 info field must not carry --
    a literal FEND (0xC0) can't appear here since this is ASCII text, but a
    stray CR/LF would otherwise smear one packet across the terminal as two.
    """
    return "".join(ch for ch in text if ch >= " " and ch != "\x7f")


def _format_lat(lat: float) -> str:
    if not math.isfinite(lat):
        raise ValueError("latitude must be finite")
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"latitude {lat} out of range -90..90")
    hemi = "N" if lat >= 0 else "S"
    lat = abs(lat)
    deg = int(lat)
    minutes = (lat - deg) * 60
    return f"{deg:02d}{minutes:05.2f}{hemi}"


def _format_lon(lon: float) -> str:
    if not math.isfinite(lon):
        raise ValueError("longitude must be finite")
    if not -180.0 <= lon <= 180.0:
        raise ValueError(f"longitude {lon} out of range -180..180")
    hemi = "E" if lon >= 0 else "W"
    lon = abs(lon)
    deg = int(lon)
    minutes = (lon - deg) * 60
    return f"{deg:03d}{minutes:05.2f}{hemi}"


def position_report(
    lat: float,
    lon: float,
    symbol_table: str,
    symbol_code: str,
    comment: str = "",
    *,
    messaging: bool = True,
    timestamp: str | None = None,
) -> bytes:
    """Build an uncompressed position report's information field.

    ``symbol_table`` must be ``/`` or ``\\``; ``symbol_code`` any printable
    ASCII character. ``timestamp``, if given, is a 6-digit day/hour/minute (or
    hour/minute/second) group plus a ``z``/``h``/``/`` suffix exactly as the
    spec requires -- this function does not attempt to derive one from wall
    clock time because it does not know whether the caller wants zulu, local,
    or a fixed-station "no timestamp" beacon.
    """
    if symbol_table not in ("/", "\\"):
        raise ValueError(f"symbol table selector must be '/' or '\\\\', got {symbol_table!r}")
    if len(symbol_code) != 1 or not 0x21 <= ord(symbol_code) <= 0x7E:
        raise ValueError(f"symbol code must be one printable ASCII character, got {symbol_code!r}")
    comment = _clean_text(comment)[:_MAX_COMMENT]

    lat_field = _format_lat(lat)
    lon_field = _format_lon(lon)

    if timestamp is not None:
        if not _TIMESTAMP_RE.match(timestamp):
            raise ValueError(f"timestamp must be 6 digits + one of 'zh/', got {timestamp!r}")
        dti = "@" if messaging else "/"
        body = f"{dti}{timestamp}{lat_field}{symbol_table}{lon_field}{symbol_code}{comment}"
    else:
        dti = "=" if messaging else "!"
        body = f"{dti}{lat_field}{symbol_table}{lon_field}{symbol_code}{comment}"
    return body.encode("ascii", "strict")


def object_report(
    name: str,
    alive: bool,
    timestamp: str,
    lat: float,
    lon: float,
    symbol_table: str,
    symbol_code: str,
    comment: str = "",
) -> bytes:
    """Build a strict uncompressed APRS object-report information field.

    APRS 1.0.1, chapter 11, defines an object as ``;`` followed by a fixed
    nine-character printable-ASCII name, ``*`` (live) or ``_`` (killed), a
    mandatory seven-character timestamp, and a position.  Names are padded
    here, never truncated: truncating would silently create a different
    object.  This encoder intentionally emits only the broadly interoperable
    uncompressed position form and no optional data extension.
    """
    if not isinstance(alive, bool):
        raise ValueError("object liveness must be a boolean")
    if not _OBJECT_NAME_RE.fullmatch(name) or not name.strip():
        raise ValueError("object name must be 1-9 printable ASCII characters and not all spaces")
    if not _TIMESTAMP_RE.match(timestamp):
        raise ValueError("object timestamp must be 6 digits + one of 'zh/'")
    if symbol_table not in ("/", "\\"):
        raise ValueError(f"symbol table selector must be '/' or '\\\\', got {symbol_table!r}")
    if len(symbol_code) != 1 or not 0x21 <= ord(symbol_code) <= 0x7E:
        raise ValueError(f"symbol code must be one printable ASCII character, got {symbol_code!r}")
    if not comment.isascii() or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in comment):
        raise ValueError("object comment must contain printable ASCII only")
    if len(comment) > _OBJECT_COMMENT_MAX:
        raise ValueError(f"object comment must be at most {_OBJECT_COMMENT_MAX} characters")
    marker = "*" if alive else "_"
    body = f";{name:<9}{marker}{timestamp}{_format_lat(lat)}{symbol_table}{_format_lon(lon)}{symbol_code}{comment}"
    return body.encode("ascii", "strict")


def status(text: str) -> bytes:
    """Build a status-report information field (``>``)."""
    text = _clean_text(text)[:_MAX_COMMENT]
    return f">{text}".encode("ascii", "replace")


def message(addressee: str, text: str, number: str | None = None) -> bytes:
    """Build a message information field (``:ADDRESSEE :text{number``).

    ``addressee`` is padded to the fixed 9-character field the spec requires;
    a longer callsign cannot be represented and is rejected rather than
    silently truncated, since a truncated addressee delivers the message to
    the wrong station or to nobody.
    """
    addressee = addressee.strip().upper()
    if not addressee or len(addressee) > 9:
        raise ValueError(f"addressee must be 1-9 characters, got {addressee!r}")
    text = _clean_text(text)[:67]  # 67 = 70-byte APRS message max minus ":AAAAAAAAA:" overhead margin
    body = f":{addressee:<9}:{text}"
    if number is not None:
        if not _MSG_NUMBER_RE.match(number):
            raise ValueError(f"message number must be 1-5 alphanumeric characters, got {number!r}")
        body += f"{{{number}"
    return body.encode("ascii", "replace")


def ack(addressee: str, number: str) -> bytes:
    """Build a message-ack information field (``:ADDRESSEE :ackNNNNN``)."""
    addressee = addressee.strip().upper()
    if not addressee or len(addressee) > 9:
        raise ValueError(f"addressee must be 1-9 characters, got {addressee!r}")
    if not _MSG_NUMBER_RE.match(number):
        raise ValueError(f"message number must be 1-5 alphanumeric characters, got {number!r}")
    return f":{addressee:<9}:ack{number}".encode("ascii", "replace")


def beacon_frame(
    source: AX25Address,
    destination: AX25Address,
    via: tuple[AX25Address, ...],
    payload: bytes,
) -> AX25Frame:
    """Wrap an already-encoded APRS payload in a ready-to-transmit UI frame.

    Command semantics (`command=True`) match every APRS beacon actually seen
    on the air: APRS unproto traffic is always a command frame, never a
    response, because there is no connection for it to be a response within.
    """
    path = AX25Path(destination=destination, source=source, repeaters=via)
    return AX25Frame.u_frame(path, UType.UI, pid=PID_NO_LAYER3, command=True, info=payload)
