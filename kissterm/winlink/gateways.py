"""The Winlink RMS gateway list: where to connect, nearest first.

ROADMAP P2 "RMS Gateway list". The list comes from the Winlink API over
the Internet, **on request only**, and is kept in a file; nothing here
ever goes on the air, and nothing fetches on a timer or at launch.

**The API needs an access key**, "obtained from a Winlink administrator at
no cost and applicable to a specific application and software author"
(api.winlink.org, 2026-09-27). Pat's key is issued to Pat and is not ours
to use. Until kissterm has its own, `ACCESS_KEY` is empty, `fetch` raises
`NoAccessKey`, and the list works only from a saved file (ROADMAP,
"Blockers outside the code"). The API's terms: sanity-check every
parameter, request only on need, and a callsign sent must have a Winlink
account (none is sent here).

**The request and the reply** follow Pat (github.com/la5nta/pat, MIT):
`internal/cmsapi/api.go` posts `Mode`, `HistoryHours` (at most 48),
`ServiceCodes` (default `PUBLIC`) and `key` as a form to
`/gateway/status.json`; the reply is `{"Gateways": [...]}`, each gateway
with `Callsign`, `BaseCallsign`, `LastStatus`, `Latitude`, `Longitude`
and `GatewayChannels`, each channel with `Frequency` (Hz),
`SupportedModes` ("Packet 1200", "VARA FM", "ARDOP 2000"...),
`Gridsquare`, `Baud`, `OperatingHours` and `ServiceCode`. The field names
were checked against the sample reply Pat ships
(`internal/cmsapi/gateway_status.json.gz`, 2105 gateways, April 2026);
the tests use a small hand-made reply of the same shape.
# UNVERIFIED: our own request against the live API, which needs the key.

**Filtering by mode** follows Pat's `app/rmslist.go` `IsMode`: VARA FM is
"VARA FM..."; VARA HF is "VARA..." but not FM; anything else is a
case-insensitive substring ("packet", "ardop", "pactor").

**The distance** is from the operator's own APRS position, to the
channel's grid square centre (`locator.from_grid`), in miles like the
Heard radar (`geo.bearing_distance_mi`). A grid square is only as exact as
its size: a four-character one is some 70 by 100 miles.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .. import __version__
from ..geo import bearing_distance_mi
from ..locator import LocatorError, from_grid

log = logging.getLogger(__name__)

#: kissterm's Winlink API access key. Empty until the Winlink Development
#: Team issues one (see the module docstring); never another program's.
ACCESS_KEY = ""
STATUS_URL = "https://api.winlink.org/gateway/status.json"
#: The API's own limit on history.
MAX_HISTORY_HOURS = 48
#: A fetch that takes longer than this has failed.
FETCH_TIMEOUT = 30.0
#: Largest reply accepted: the full list is about 2 MB.
MAX_REPLY = 16 * 1024 * 1024

#: The choices offered, as (label, what `matches_mode` takes). "" is all.
MODES = (
    ("Packet", "packet"),
    ("VARA FM", "vara fm"),
    ("VARA HF", "vara hf"),
    ("ARDOP", "ardop"),
    ("Pactor", "pactor"),
    ("All modes", ""),
)


class NoAccessKey(RuntimeError):
    """kissterm has no Winlink API key yet, so the list cannot be fetched."""


class FetchError(RuntimeError):
    """The fetch failed; the message says why, in the operator's words."""


@dataclass(frozen=True)
class Channel:
    """One gateway channel: a callsign on one frequency and mode."""

    callsign: str
    base_callsign: str
    grid: str
    frequency_hz: int
    modes: str
    baud: str = ""
    hours: str = ""
    last_status: str = ""
    #: From the operator, when both positions are known; else None.
    distance_mi: float | None = None
    bearing: float | None = None

    @property
    def frequency(self) -> str:
        """"145.050 MHz"."""
        return f"{self.frequency_hz / 1e6:.3f} MHz" if self.frequency_hz else ""


def matches_mode(channel: Channel, mode: str) -> bool:
    """Pat's `IsMode` (module docstring); "" matches everything."""
    modes = channel.modes
    if not mode:
        return True
    if mode == "vara fm":
        return modes.upper().startswith("VARA FM")
    if mode == "vara hf":
        return modes.upper().startswith("VARA") and not modes.upper().startswith("VARA FM")
    return mode in modes.lower()


def parse(data: bytes | str, *, lat: float | None = None, lon: float | None = None) -> list[Channel]:
    """Every channel in a gateway status reply, with its distance from
    (`lat`, `lon`) when given. A gateway or channel that is not the
    documented shape is skipped, never guessed at. Raises `ValueError`
    if the reply is not JSON or has no gateway list."""
    reply = json.loads(data)
    gateways = reply.get("Gateways") if isinstance(reply, dict) else None
    if not isinstance(gateways, list):
        raise ValueError("no gateway list in the reply")
    channels: list[Channel] = []
    for gateway in gateways:
        if not isinstance(gateway, dict):
            continue
        callsign = _text(gateway.get("Callsign"))
        found = gateway.get("GatewayChannels")
        if not callsign or not isinstance(found, list):
            continue
        for item in found:
            if not isinstance(item, dict):
                continue
            try:
                frequency = int(item.get("Frequency") or 0)
            except (TypeError, ValueError):
                continue
            grid = _text(item.get("Gridsquare")).upper()
            distance = bearing = None
            if lat is not None and lon is not None and grid:
                try:
                    bearing, distance = bearing_distance_mi(lat, lon, *from_grid(grid))
                except LocatorError:
                    pass
            channels.append(Channel(
                callsign=callsign.upper(),
                base_callsign=_text(gateway.get("BaseCallsign")).upper(),
                grid=grid,
                frequency_hz=frequency,
                modes=_text(item.get("SupportedModes")),
                baud=_text(item.get("Baud")),
                hours=_text(item.get("OperatingHours")),
                last_status=_text(gateway.get("LastStatus")),
                distance_mi=distance,
                bearing=bearing,
            ))
    return channels


def _text(value) -> str:
    """A field as one line of printable text, whatever the reply held."""
    text = value if isinstance(value, str) else "" if value is None else str(value)
    return "".join(ch for ch in text if ch.isprintable()).strip()


def nearest(channels: list[Channel], mode: str = "packet", limit: int | None = None) -> list[Channel]:
    """The channels in `mode`, nearest first; those with no known
    distance last, by callsign."""
    chosen = [c for c in channels if matches_mode(c, mode)]
    chosen.sort(key=lambda c: (c.distance_mi is None, c.distance_mi or 0.0, c.callsign, c.frequency_hz))
    return chosen[:limit] if limit else chosen


def cache_path(data_dir: Path) -> Path:
    return data_dir / "winlink-gateways.json"


def load_cached(path: Path) -> tuple[bytes, float] | None:
    """The saved reply and when it was fetched (the file's time), or None."""
    try:
        return path.read_bytes(), path.stat().st_mtime
    except OSError:
        return None


def save_cached(path: Path, data: bytes) -> None:
    """Write the reply beside the old one, then replace it, so a failed
    write never leaves half a list. Raises `OSError`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".partial")
    partial.write_bytes(data)
    os.replace(partial, path)


def fetch(
    key: str = ACCESS_KEY,
    *,
    mode: str = "AnyAll",
    history_hours: int = MAX_HISTORY_HOURS,
    service_codes: tuple[str, ...] = ("PUBLIC",),
    timeout: float = FETCH_TIMEOUT,
    url: str = STATUS_URL,
) -> bytes:
    """The gateway status reply from the Winlink API. Blocking: run it in
    a thread. Raises `NoAccessKey` without a key and `FetchError` for
    anything else, and checks the reply parses before returning it."""
    if not key:
        raise NoAccessKey("kissterm has no Winlink API key yet")
    # The terms ask for every parameter to be checked before a request.
    if mode not in ("AnyAll", "Packet", "Pactor", "RobustPacket", "AllHf"):
        raise ValueError(f"not an API mode: {mode!r}")
    if not all(code.isalnum() for code in service_codes):
        raise ValueError(f"not a service code: {service_codes!r}")
    form = [("Mode", mode), ("HistoryHours", str(max(1, min(history_hours, MAX_HISTORY_HOURS)))),
            ("key", key)] + [("ServiceCodes", code) for code in service_codes]
    request = urllib.request.Request(
        url, data=urllib.parse.urlencode(form).encode("ascii"), method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json",
                 "User-Agent": f"kissterm/{__version__}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(MAX_REPLY + 1)
    except urllib.error.HTTPError as exc:
        raise FetchError(f"winlink.org answered {exc.code} {exc.reason}") from None
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise FetchError(f"could not reach winlink.org ({reason})") from None
    if len(data) > MAX_REPLY:
        raise FetchError("the reply was larger than any gateway list")
    try:
        parse(data)
    except ValueError as exc:
        raise FetchError(f"the reply was not a gateway list ({exc})") from None
    return data


def age_text(fetched_at: float, now: float | None = None) -> str:
    """"fetched 3 days ago"."""
    seconds = max(0.0, (now if now is not None else time.time()) - fetched_at)
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            count = int(seconds // size)
            return f"fetched {count} {unit}{'s' if count != 1 else ''} ago"
    return "fetched just now"
