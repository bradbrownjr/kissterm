"""APRS payload decoding on top of AX.25 UI frames -- dispatch and display.

APRS is not a protocol stack sitting beside AX.25 -- it is a convention for
what goes in the information field of an AX.25 UI frame whose PID is
`kissterm.ax25.frame.PID_NO_LAYER3` (0xF0). kissterm's frame layer already
decodes every such frame off the wire; this module never touches a socket, a
KISS byte, or a digipeater path itself. `parse_packet` takes an
already-decoded `AX25Frame`, reads the first byte of its `info` field (the
APRS "data type identifier"), and routes to whichever format module owns that
identifier: `position.py` for ``!``/``=``/``/``/``@``, `mice.py` for the
backtick/apostrophe Mic-E identifiers, `messages.py` for ``:``/``>``/``;``/
``)``/``<``/``?``, `telemetry.py` for ``_``/``T``. This file holds only what
genuinely needs the whole picture: the dispatch table itself (`_dispatch`),
third-party (``}``) recursion (decoding a third-party payload means calling
back into this same dispatch), and `format_packet`, which has to know about
every `kind` to render one. See `kissterm/aprs/AGENTS.md` for the full file
map and which module to edit for a given data type identifier.

Every frame decoded here came off RF (or an IGate feed relaying RF), and RF
does not respect any spec: trackers ship with firmware bugs, frames get
truncated by a collision, digipeaters mangle paths. This module -- and every
decoder it dispatches to -- is therefore deliberately, aggressively total:
**no function reachable from `parse_packet` ever raises out of it.** Every
sub-parser may raise `ValueError`, `IndexError`, or whatever is convenient
internally; `parse_packet` catches all of it and downgrades to
``kind="unparsed"`` with the raw info field preserved. A monitor pane that
crashes because one cheap Baofeng tracker sent a corrupt Mic-E frame is a
worse outcome than a monitor pane that shows one ugly, unparsed line.
"""

from __future__ import annotations

import re
from dataclasses import replace

from ..ax25.address import AX25Address, AX25Path
from ..ax25.frame import AX25Frame, PID_NO_LAYER3, UType
from .messages import parse_item, parse_message, parse_object, parse_status
from .mice import parse_mic_e
from .position import parse_position_field
from .telemetry import parse_telemetry, parse_weather
from .types import (
    AprsPacket,
    Message,
    ObjectReport,
    Position,
    Status,
    Telemetry,
    ThirdParty,
    WeatherReport,
)

__all__ = [
    "Position",
    "Status",
    "Message",
    "WeatherReport",
    "Telemetry",
    "ObjectReport",
    "ThirdParty",
    "AprsPacket",
    "parse_packet",
    "format_packet",
]


# -- dispatch ---------------------------------------------------------------


def parse_packet(frame: AX25Frame) -> AprsPacket | None:
    """Decode one AX.25 frame as APRS, or return `None` if it is not APRS.

    `None` (not an `AprsPacket` with ``kind="unparsed"``) means "this frame
    was never claiming to be APRS" -- an I frame, a connect-mode UA, a UI
    frame carrying NET/ROM. ``kind="unparsed"`` means "this frame *had* PID
    0xF0 and still failed to decode," which is the case the monitor pane and
    the heard table care about differently: the latter is still worth logging
    as an APRS station even if the payload was corrupt.
    """
    if frame.kind != "U" or frame.utype != UType.UI or frame.pid != PID_NO_LAYER3:
        return None
    info = frame.info
    if not info:
        return AprsPacket(frame.path.source, frame.path.destination, frame.path, info, "unparsed", None)
    dti = chr(info[0]) if info[0] < 128 else "�"
    try:
        kind, data = _dispatch(dti, info, dest_callsign=frame.path.destination.callsign)
    except Exception:
        kind, data = "unparsed", None
    return AprsPacket(frame.path.source, frame.path.destination, frame.path, info, kind, data)


def _dispatch(dti: str, info: bytes, dest_callsign: str | None) -> tuple[str, object | None]:
    """Route on the data type identifier. Raises freely -- `parse_packet` and
    `_parse_third_party` are the only callers, and both catch everything.
    """
    text = info.decode("ascii", "replace")
    body = text[1:]

    if dti in "!=":
        return "position", parse_position_field(body)
    if dti in "/@":
        ts, rest = body[:7], body[7:]
        pos = parse_position_field(rest)
        return "position", replace(pos, timestamp=ts)
    if dti == ":":
        return "message", parse_message(body)
    if dti == ">":
        return "status", parse_status(body)
    if dti == ";":
        return "object", parse_object(body)
    if dti == ")":
        return "item", parse_item(body)
    if dti == "_":
        return "weather", parse_weather(body)
    if dti == "T":
        return "telemetry", parse_telemetry(body)
    if dti == "<":
        return "capabilities", Status(text=body.strip())
    if dti == "?":
        return "query", Status(text=body.strip())
    if dti == "}":
        return "third-party", _parse_third_party(body)
    if dti in "`'":
        return "mic-e", parse_mic_e(info, dest_callsign)
    raise ValueError(f"unrecognized data type identifier {dti!r}")


# -- third-party recursion ---------------------------------------------------

_THIRD_PARTY_RE = re.compile(r"^([^>]+)>([^,:]+)(?:,([^:]+))?:(.*)$", re.S)


def _safe_address(text: str) -> AX25Address:
    try:
        return AX25Address.parse(text)
    except Exception:
        return AX25Address("NOCALL")


def _parse_third_party(body: str) -> ThirdParty:
    m = _THIRD_PARTY_RE.match(body)
    if not m:
        raise ValueError("malformed third-party header")
    src, dest, path, inner_text = m.group(1), m.group(2), m.group(3) or "", m.group(4)
    inner_info = inner_text.encode("ascii", "replace")
    if not inner_info:
        raise ValueError("third-party packet carries no inner payload")
    inner_kind, inner_data = _dispatch(chr(inner_info[0]), inner_info, dest_callsign=None)
    inner = AprsPacket(
        source=_safe_address(src),
        destination=_safe_address(dest),
        path=None,
        info=inner_info,
        kind=inner_kind,
        data=inner_data,
    )
    return ThirdParty(source=src, destination=dest, path=path, inner=inner)


# -- display -----------------------------------------------------------

#: A handful of common primary-table symbols, purely cosmetic for
#: `format_packet`. Anything not listed falls back to the raw symbol
#: character rather than guessing.
_SYMBOL_NAMES: dict[tuple[str, str], str] = {
    ("/", ">"): "car",
    ("/", "-"): "house",
    ("/", "k"): "truck",
    ("/", "b"): "bike",
    ("/", "_"): "wx",
    ("/", "j"): "jeep",
    ("/", "s"): "ship",
    ("/", "u"): "van",
    ("/", "["): "runner",
    ("/", "$"): "phone",
}


def _format_position(src: str, p: Position) -> str:
    bits = [src, "pos", f"{p.latitude:.4f},{p.longitude:.4f}"]
    symbol = _SYMBOL_NAMES.get((p.symbol_table, p.symbol_code), p.symbol_code)
    if symbol:
        bits.append(symbol)
    if p.course is not None and p.speed_knots is not None:
        bits.append(f"{p.course}deg {p.speed_knots:.0f}kt")
    if p.altitude_ft is not None:
        bits.append(f"{p.altitude_ft}ft")
    if p.mic_e_message:
        bits.append(p.mic_e_message)
    if p.comment:
        bits.append(f'"{p.comment}"')
    return " ".join(bits)


def format_packet(pkt: AprsPacket) -> str:
    """One clean, ASCII-only human line for the APRS pane."""
    src = str(pkt.source)

    if pkt.kind in ("position", "mic-e") and isinstance(pkt.data, Position):
        return _format_position(src, pkt.data)
    if pkt.kind == "status" and isinstance(pkt.data, Status):
        return f'{src} status "{pkt.data.text}"'
    if pkt.kind == "capabilities" and isinstance(pkt.data, Status):
        return f'{src} caps "{pkt.data.text}"'
    if pkt.kind == "query" and isinstance(pkt.data, Status):
        return f'{src} query "{pkt.data.text}"'
    if pkt.kind == "message" and isinstance(pkt.data, Message):
        m = pkt.data
        if m.is_ack:
            return f"{src} ack to {m.addressee} #{m.number}"
        if m.is_rej:
            return f"{src} rej to {m.addressee} #{m.number}"
        tail = f" {{{m.number}}}" if m.number else ""
        return f'{src} msg to {m.addressee}: "{m.text}"{tail}'
    if pkt.kind == "weather" and isinstance(pkt.data, WeatherReport):
        w = pkt.data
        bits = [src, "wx"]
        if w.temperature_f is not None:
            bits.append(f"{w.temperature_f}F")
        if w.wind_speed_mph is not None:
            bits.append(f"wind {w.wind_speed_mph}mph")
        if w.humidity_pct is not None:
            bits.append(f"{w.humidity_pct}%RH")
        return " ".join(bits)
    if pkt.kind in ("object", "item") and isinstance(pkt.data, ObjectReport):
        o = pkt.data
        state = "alive" if o.alive else "killed"
        line = f"{src} {pkt.kind} {o.name} ({state})"
        if o.position is not None:
            line += f" {o.position.latitude:.4f},{o.position.longitude:.4f}"
        return line
    if pkt.kind == "telemetry" and isinstance(pkt.data, Telemetry):
        t = pkt.data
        return f"{src} telemetry #{t.sequence} " + ",".join(f"{a:g}" for a in t.analog)
    if pkt.kind == "third-party" and isinstance(pkt.data, ThirdParty):
        tp = pkt.data
        return f"{src} 3rd-party {tp.source}>{tp.destination}: {format_packet(tp.inner)}"
    if pkt.kind == "unparsed":
        return f"{src} unparsed ({len(pkt.info)} bytes)"
    return f"{src} {pkt.kind}"
