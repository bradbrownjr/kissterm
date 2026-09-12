"""Receive-only APRS-IS capture for validating rare compressed-position fields.

The ``{`` c-byte is uncommon enough that generated fixtures only prove this
project agrees with itself.  This module connects to an APRS-IS filtered-feed
port, sends exactly one *unverified* login line, and reads until it sees a
real compressed position using that field.  ``pass -1`` deliberately makes
the login receive-only: no APRS packet can be accepted from this connection.

The network protocol lives here rather than in :mod:`kissterm.aprs`: the APRS
package is a pure payload decoder and must remain usable against RF frames,
loopback tests, and captured APRS-IS text without acquiring an I/O dependency.
The line recognizer is likewise intentionally narrow.  It accepts ordinary
station position reports (with or without a timestamp), not every APRS data
type, because the goal is a trustworthy fixture for one specific decoder path,
not a second APRS-IS client.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .aprs.position import parse_position_field

__all__ = ["RangeCapture", "capture_precalculated_range", "find_precalculated_range"]


@dataclass(frozen=True, slots=True)
class RangeCapture:
    """One raw APRS-IS line whose compressed ``cs`` field advertises range."""

    raw_line: str
    source: str
    info: str
    range_mi: float


def find_precalculated_range(line: str) -> RangeCapture | None:
    """Return a capture when one TNC2 line contains a ``{`` range position.

    APRS-IS comments begin with ``#`` and never carry a TNC2 packet.  For the
    station report forms relevant here, ``!``/``=`` put the position directly
    after the data-type identifier; ``/``/``@`` put it after a seven-byte
    timestamp.  Requiring ``{`` at compressed-position byte ``c`` avoids
    mistaking a brace in an ordinary comment for the range extension.
    """
    raw_line = line.rstrip("\r\n")
    if not raw_line or raw_line.startswith("#"):
        return None
    header, separator, info = raw_line.partition(":")
    if not separator or ">" not in header or not info:
        return None

    if info[0] in "!=":
        position = info[1:]
    elif info[0] in "/@" and len(info) >= 9:
        position = info[8:]
    else:
        return None
    if len(position) < 13 or position[0] not in "/\\" or position[10] != "{":
        return None

    try:
        decoded = parse_position_field(position)
    except ValueError:
        return None
    if decoded.precalc_range_mi is None:
        return None
    return RangeCapture(
        raw_line=raw_line,
        source=header.split(">", 1)[0],
        info=info,
        range_mi=decoded.precalc_range_mi,
    )


async def capture_precalculated_range(
    *,
    host: str,
    port: int,
    callsign: str,
    latitude: float,
    longitude: float,
    radius_km: float,
    timeout_seconds: float,
) -> RangeCapture | None:
    """Read a filtered APRS-IS stream until a real ``{`` range packet appears.

    The sole outbound text is the APRS-IS login line.  Its ``pass -1`` value
    is the protocol's receive-only mode, so this helper cannot inject a packet
    into APRS-IS even if a future caller accidentally grows a write path.
    """
    connect_timeout = min(timeout_seconds, 15.0)
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port), timeout=connect_timeout
    )
    login = (
        f"user {callsign.upper()} pass -1 vers kissterm capture "
        f"filter r/{latitude:.5f}/{longitude:.5f}/{radius_km:g}\r\n"
    )
    try:
        writer.write(login.encode("ascii"))
        await writer.drain()
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return None
            line = await asyncio.wait_for(reader.readline(), timeout=remaining)
            if not line:
                return None
            capture = find_precalculated_range(line.decode("latin-1"))
            if capture is not None:
                return capture
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
