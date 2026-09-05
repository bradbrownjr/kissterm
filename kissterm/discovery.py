"""Hardware and network auto-discovery -- the reason a new user does not quit.

linpac and EasyTerm both start from the assumption that you already know
which `/dev/tty*` your TNC is on, what baud rate it wants, and the IP and
port of any KISS-over-TCP host on your LAN. That assumption is fine for
someone who has run packet for twenty years and hostile to everyone else,
and "everyone else" is most of who amateur radio needs to attract. kissterm
treats discovery as a first-class feature specifically so the setup flow can
be "plug in a TNC, open kissterm, pick it from a list" instead of "read the
manual, find a device path, edit a config file, hope you got the baud rate
right."

Every function in this module is async, degrades to an empty result rather
than raising, and is bounded by an explicit timeout. Those three properties
are not independent: a discovery pass runs before the user has told
kissterm anything, so there is no established error-handling context to
raise into, and it commonly runs on hardware (a Raspberry Pi next to a
radio) where a hung network scan is not just slow, it is the kind of thing
that makes someone reach for the power switch mid-QSO.

**On confidence, not certainty.** Nothing here can *prove* a serial port or
TCP host is a TNC without traffic actually flowing over RF, and kissterm
will not manufacture that traffic just to find out (see `probe_kiss_serial`
and `discover_network` below for what that restraint means in practice).
Every `DiscoveredDevice` therefore carries a `confidence` score, not a
boolean verdict, and the heuristics behind that score (VID:PID tables,
description substrings, well-known port numbers) are best-effort pattern
matching against hardware this author has seen or read about -- they will
misjudge devices they have never encountered, and they are written to fail
toward "list it with a lower score" rather than "hide it."
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
import subprocess
from dataclasses import dataclass, field
from typing import Any

from .transport.kiss import FEND, KissDecoder

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DiscoveredDevice:
    """One thing discovery found, ready to become a `Config.transports` entry.

    `config` is deliberately shaped exactly like a `transports` list entry
    (`{"kind": ..., "name": ..., ...}`) so the setup UI can offer "add this"
    with no translation step between what discovery found and what gets
    written to disk.
    """

    kind: str  # "serial" | "tcp" | "bluetooth"
    label: str
    detail: str
    #: 0.0 (almost certainly not a TNC) .. 1.0 (near-certain match).
    confidence: float
    config: dict[str, Any]
    note: str = ""


# ---------------------------------------------------------------------------
# Serial
# ---------------------------------------------------------------------------

#: Description/manufacturer substrings (lower-cased) for hardware that is
#: unambiguously packet-radio gear when it shows up at all. These score high
#: because nothing else plausibly presents itself this way.
_KNOWN_TNC_SUBSTRINGS: dict[str, str] = {
    "mobilinkd": "Mobilinkd TNC (KISS-capable Bluetooth/USB packet TNC)",
    "kenwood": "Kenwood radio data port (TH-D7x/TM-D7xx families expose a built-in KISS TNC)",
    "kantronics": "Kantronics TNC (KPC3+/KAM -- long-established KISS/AX.25 hardware)",
    "tnc-pi": "TNC-Pi (Raspberry Pi HAT TNC)",
    "tncpi": "TNC-Pi (Raspberry Pi HAT TNC)",
    "digirig": "DigiRig Mobile (sound + serial interface popular for KISS TNCs and VARA)",
    "signalink": "SignaLink USB (sound interface; some units also expose a serial PTT port)",
}

#: (VID, PID) -- PID of `None` matches any PID for that vendor. These are
#: generic USB-serial bridge chipsets: seeing one only means "this could be
#: almost any USB-serial gadget," including a TNC, so it scores lower than
#: an explicit brand match above.
_GENERIC_BRIDGE_VID_PID: dict[tuple[int, int | None], str] = {
    (0x0403, None): "FTDI USB-serial bridge (common in TNCs and radio interfaces)",
    (0x10C4, 0xEA60): "Silicon Labs CP210x USB-serial bridge (common in TNCs, DigiRig, etc.)",
    (0x1A86, 0x7523): "WCH CH340 USB-serial bridge (common in budget TNCs and Arduino modems)",
    (0x1A86, 0x5523): "WCH CH341 USB-serial bridge",
    (0x067B, 0x2303): "Prolific PL2303 USB-serial bridge",
}

#: Substrings that suggest the port is something else entirely -- a dial-up
#: modem, a virtual Bluetooth COM port bound to a phone, an IR adapter.
#: These are down-scored, never hidden: a TNC that happens to share a driver
#: string with one of these is rare but not impossible.
_UNLIKELY_SUBSTRINGS = ("bluetooth", "modem", "gps receiver", "irda")

_DEFAULT_BAUD = 9600


def _score_serial_port(
    description: str, manufacturer: str, vid: int | None, pid: int | None
) -> tuple[float, str]:
    """Heuristic confidence that a serial port is attached to a TNC.

    Order of preference: an explicit brand match beats a generic bridge-chip
    match beats "looks like something else" beats "no idea." See the module
    docstring for why this is a score, not a verdict.
    """
    haystack = f"{description} {manufacturer}".lower()

    for substring, note in _KNOWN_TNC_SUBSTRINGS.items():
        if substring in haystack:
            return 0.9, note

    if vid is not None:
        for (known_vid, known_pid), note in _GENERIC_BRIDGE_VID_PID.items():
            if vid == known_vid and (known_pid is None or pid == known_pid):
                return 0.5, note

    for substring in _UNLIKELY_SUBSTRINGS:
        if substring in haystack:
            return 0.1, f"description mentions {substring!r}; not typically a TNC"

    return 0.3, "unrecognized device; could still be a TNC"


async def discover_serial() -> list[DiscoveredDevice]:
    """Enumerate serial ports via `pyserial`, scored by likely TNC-ness.

    Returns an empty list -- never raises -- if `pyserial` is not installed
    or enumeration fails for any reason (a permissions quirk, an odd
    platform). Ports are returned highest-confidence first.
    """
    try:
        from serial.tools import list_ports  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("discover_serial: pyserial not installed, skipping")
        return []

    try:
        ports = await asyncio.to_thread(list_ports.comports)
    except Exception as exc:  # noqa: BLE001 -- discovery must never raise
        logger.debug("discover_serial: comports() failed: %s", exc)
        return []

    out: list[DiscoveredDevice] = []
    for port in ports:
        device = getattr(port, "device", None)
        if not device:
            continue
        description = getattr(port, "description", "") or ""
        manufacturer = getattr(port, "manufacturer", "") or ""
        vid = getattr(port, "vid", None)
        pid = getattr(port, "pid", None)

        confidence, note = _score_serial_port(description, manufacturer, vid, pid)

        detail = description or device
        if vid is not None and pid is not None:
            detail = f"{detail} ({vid:04X}:{pid:04X})"

        out.append(
            DiscoveredDevice(
                kind="serial",
                label=device,
                detail=detail,
                confidence=confidence,
                config={"kind": "serial", "name": device, "device": device, "baud": _DEFAULT_BAUD},
                note=note,
            )
        )

    out.sort(key=lambda d: d.confidence, reverse=True)
    return out


async def probe_kiss_serial(device: str, baud: int = _DEFAULT_BAUD, timeout: float = 2.0) -> bool:
    """Open `device`, send a harmless idle probe, and listen for a KISS frame.

    The probe is two bare ``FEND`` bytes -- no type byte, no payload. That
    matters: it is *not* `kissterm.transport.kiss.exit_kiss()` (the KISS
    ``RETURN`` command), which would kick a TNC that is already sitting in
    KISS mode back into its command shell and turn a discovery probe into an
    outage on a working link. Two bare FENDs are a no-op resync pattern most
    KISS implementations already tolerate on an idle line, and they carry no
    type byte for any TNC to interpret as "transmit this" -- so this probe
    cannot itself key a transmitter.

    Returns `True` only if something reaches back with bytes that decode as
    a complete KISS frame via `KissDecoder` (reused, not reimplemented).
    **A `False` result is not proof the device is not a TNC.** A TNC that is
    correctly wired to a quiet radio, in receive-only mode, or simply
    waiting for RF that has not arrived yet will sit there silently forever
    -- that is entirely normal KISS behaviour, not a fault. Callers (and the
    UI) must present a negative result as "no traffic seen yet," never as
    "not a TNC."
    """
    try:
        import serial  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("probe_kiss_serial: pyserial not installed, skipping")
        return False

    def _probe() -> bool:
        try:
            with serial.Serial(device, baud, timeout=timeout) as ser:
                with contextlib.suppress(Exception):
                    ser.reset_input_buffer()
                ser.write(bytes([FEND, FEND]))
                ser.flush()
                decoder = KissDecoder()
                data = ser.read(4096)
                for _frame in decoder.feed(data):
                    return True
                return False
        except (OSError, ValueError) as exc:
            logger.debug("probe_kiss_serial: %s: %s", device, exc)
            return False

    try:
        return await asyncio.wait_for(asyncio.to_thread(_probe), timeout=timeout + 1.0)
    except asyncio.TimeoutError:
        return False


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

#: Well-known KISS/AGW/VARA TCP ports, in the order worth trying first.
#: port -> (service label, transport kind, is this port's config complete?)
#:
#: The `kind` matters more than the label. An earlier version reported the
#: service name correctly and then wrote ``kind = "tcp"`` for every port,
#: so accepting the AGWPE entry the scan offered configured a *raw KISS*
#: transport pointed at an AGWPE engine -- two different framings on one
#: socket, which decodes as garbage rather than failing cleanly.
#:
#: The third field is whether discovery can write a *usable* entry from a
#: probe alone. VARA cannot: `VaraTransport` needs `mycall`, which a port
#: scan does not know, and it uses two ports at once -- so its command port
#: is reported as found and left for the operator to configure, and its data
#: port is not offered as a device of its own at all, because it is the other
#: half of the same modem rather than a second thing to connect to.
_WELL_KNOWN_PORTS: dict[int, tuple[str, str | None, bool]] = {
    8001: ("Direwolf KISS", "tcp", True),
    8000: ("AGWPE", "agwpe", True),
    8100: ("KISS-over-TCP", "tcp", True),
    8300: ("VARA HF (command)", "vara", False),
    8301: ("VARA HF (data)", None, False),
    8400: ("VARA FM (command)", "varafm", False),
    8401: ("VARA FM (data)", None, False),
}

#: Cap on simultaneous connection attempts. A /24 sweep across every
#: well-known port is roughly 1500 attempts; left unbounded that is enough
#: outstanding sockets to look like a port-scan to a network's IDS, and
#: enough concurrent threads-of-work to bog down a Raspberry Pi doing the
#: scan. 64 keeps a full sweep brisk without either problem.
_MAX_CONCURRENT_PROBES = 64
#: Passive banner read -- short, because most of these services say nothing
#: until spoken to and this must never be the thing that speaks first.
_BANNER_READ_TIMEOUT = 0.2


def _guess_local_subnet() -> str | None:
    """Best-effort "what /24 am I on" without sending any actual traffic.

    Connecting a UDP socket does not put a packet on the wire -- it only
    asks the OS routing table which local address it would use, which is
    exactly the information wanted here. Returns `None` (never raises) if
    the host has no route to speak of (offline, air-gapped, IPv6-only).
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            local_ip = sock.getsockname()[0]
    except OSError:
        return None
    parts = local_ip.split(".")
    if len(parts) != 4:
        return None
    return ".".join(parts[:3])


def _describe_banner(banner: bytes) -> str:
    if not banner:
        return "open, no traffic seen yet"
    if banner[:1] == bytes([FEND]):
        return "open; saw a KISS FEND byte"
    text = banner.decode("ascii", "replace").strip()
    if text:
        return f"open; banner: {text[:40]!r}"
    return "open, no traffic seen yet"


async def discover_network(subnet: str | None = None, timeout: float = 3.0) -> list[DiscoveredDevice]:
    """Scan a local /24 for well-known KISS/AGW/VARA TCP ports.

    `subnet` is a dotted first-three-octets string (``"192.168.1"``); when
    omitted it is derived from the host's own address via
    `_guess_local_subnet`. Every connection attempt is bounded by a
    per-attempt timeout and the whole sweep by `timeout` overall, with at
    most `_MAX_CONCURRENT_PROBES` connections in flight -- see that
    constant's docstring for why. Identification is by port number and, at
    most, a passive read of whatever the service says first: this function
    never writes a byte to a discovered socket, because unlike a serial
    port, some of these services (VARA in particular) could interpret
    unsolicited bytes as something to act on, and "probing for a TNC" must
    never be the thing that keys a transmitter.
    """
    if subnet is None:
        subnet = await asyncio.to_thread(_guess_local_subnet)
    if subnet is None:
        logger.debug("discover_network: could not determine local subnet, skipping")
        return []

    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_PROBES)
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    results: list[DiscoveredDevice] = []

    async def _probe_one(host: str, port: int) -> None:
        async with semaphore:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            per_attempt = min(0.75, remaining)
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port), timeout=per_attempt
                )
            except (OSError, asyncio.TimeoutError):
                return

            banner = b""
            try:
                banner = await asyncio.wait_for(reader.read(64), timeout=_BANNER_READ_TIMEOUT)
            except (asyncio.TimeoutError, OSError):
                banner = b""
            finally:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()

            service, kind, complete = _WELL_KNOWN_PORTS.get(
                port, (f"TCP {port}", "tcp", True)
            )
            if kind is None:
                # The data half of a two-port modem. Reporting it as its own
                # device would offer the operator a second thing to connect
                # to that is really the same radio.
                return

            label = f"{host}:{port}"
            note = _describe_banner(banner)
            if complete:
                config = {"kind": kind, "name": label, "host": host, "port": port}
            else:
                # Found, but not configurable from a probe -- see
                # _WELL_KNOWN_PORTS. Say so rather than writing an entry that
                # is the wrong kind or missing a required field.
                config = {}
                note = (
                    f"{note + '; ' if note else ''}needs your callsign and both "
                    f"ports -- add a [[transports]] entry by hand"
                ).strip()

            results.append(
                DiscoveredDevice(
                    kind=kind,
                    label=label,
                    detail=f"{service} at {host}:{port}",
                    confidence=0.7,
                    config=config,
                    note=note,
                )
            )

    tasks = [
        asyncio.create_task(_probe_one(f"{subnet}.{host}", port))
        for host in range(1, 255)
        for port in _WELL_KNOWN_PORTS
    ]
    done, pending = await asyncio.wait(tasks, timeout=timeout + 1.0)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    results.sort(key=lambda d: d.confidence, reverse=True)
    return results


# ---------------------------------------------------------------------------
# Bluetooth
# ---------------------------------------------------------------------------


def _bluetoothctl_devices() -> list[tuple[str, str]]:
    """Parse `bluetoothctl devices` output into `(address, name)` pairs.

    Returns an empty list if `bluetoothctl` is not installed, times out, or
    produces anything unparsable -- a machine with no Bluetooth stack at all
    is a completely ordinary kissterm host (most TNCs are serial or TCP).
    """
    try:
        proc = subprocess.run(  # noqa: S603 -- fixed argv, no shell, no user input
            ["bluetoothctl", "devices"],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("discover_bluetooth: bluetoothctl unavailable: %s", exc)
        return []

    out: list[tuple[str, str]] = []
    for line in proc.stdout.splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) >= 2 and parts[0] == "Device":
            address = parts[1]
            name = parts[2] if len(parts) > 2 else ""
            out.append((address, name))
    return out


async def discover_bluetooth() -> list[DiscoveredDevice]:
    """List already-**paired** Bluetooth RFCOMM devices.

    This deliberately does not initiate a Bluetooth discovery scan or pair
    with anything. Pairing is a system-level, user-consenting action (it
    usually involves a PIN or a confirmation dialog) that belongs to the
    OS's Bluetooth settings, not to a packet-radio terminal reaching into
    the Bluetooth stack on its own. If a Mobilinkd TNC or similar has
    already been paired through the normal OS flow, it shows up here (via
    `bluetoothctl devices`, falling back to an empty list if that is
    unavailable) so it can be offered as a serial-style transport once the
    OS has bound it to an RFCOMM device node; kissterm will not pair it for
    the user.
    """
    devices = await asyncio.to_thread(_bluetoothctl_devices)
    out: list[DiscoveredDevice] = []
    for address, name in devices:
        looks_like_tnc = bool(name) and "mobilinkd" in name.lower()
        out.append(
            DiscoveredDevice(
                kind="bluetooth",
                label=name or address,
                detail=f"{name} ({address})" if name else address,
                confidence=0.6 if looks_like_tnc else 0.3,
                config={"kind": "bluetooth", "name": name or address, "address": address},
                note="already paired; kissterm does not initiate Bluetooth pairing",
            )
        )
    return out


# ---------------------------------------------------------------------------
# Everything at once
# ---------------------------------------------------------------------------


async def discover_all(subnet: str | None = None, deadline: float = 6.0) -> list[DiscoveredDevice]:
    """Run every discovery method concurrently, bounded by one overall deadline.

    Uses `asyncio.wait` with a timeout rather than `asyncio.gather` so that
    a slow method (network scanning is the usual culprit) does not delay
    the results of fast ones (serial enumeration, Bluetooth) past
    `deadline` -- whatever has finished when the deadline passes is
    returned, and whatever has not is cancelled outright. Combined with
    every method's own internal degrade-to-empty behaviour, this function
    itself never raises.
    """
    network_timeout = max(1.0, deadline - 1.0)
    tasks = {
        asyncio.create_task(discover_serial()): "serial",
        asyncio.create_task(discover_network(subnet=subnet, timeout=network_timeout)): "network",
        asyncio.create_task(discover_bluetooth()): "bluetooth",
    }

    done, pending = await asyncio.wait(tasks.keys(), timeout=deadline)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    combined: list[DiscoveredDevice] = []
    for task in done:
        try:
            combined.extend(task.result())
        except Exception as exc:  # noqa: BLE001 -- discovery must never raise
            logger.debug("discover_all: %s failed: %s", tasks[task], exc)

    combined.sort(key=lambda d: d.confidence, reverse=True)
    return combined
