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

**Except when it is not a heuristic.** `identify_tcp` asks a port what it is
and can come back with a *disproof*: an HTTP status line, an SSH banner, a
hang-up. Those results are not uncertain -- no KISS or AGWPE endpoint can
produce them -- so a disproved port is dropped from the sweep rather than
listed with a low score. This matters because a `DiscoveredDevice` is
written straight into `config.transports`: port 8000 and 8001 are as popular
with self-hosted web apps as with packet software, and the old
port-number-only match put those web apps in the transport list, where the
next symptom is an operator hunting for a TNC that was never there.

Note which direction is strong. Proving a port is NOT a TNC takes one reply.
Proving it IS a raw KISS TNC takes a frame, and KISS has no version query,
no capability exchange and no greeting -- an idle TNC on a quiet channel is
silent, and that silence is indistinguishable from a silent web server. So
`"unknown"` is a real and common answer, and the UI must never render it as
a fault. AGWPE is the exception: it has a version query that asks the
software a question, which is why its port can be confirmed outright.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
import struct
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
#: The AGWPE engine port, named because `identify_tcp` keys its probe off it:
#: AGWPE is the only one of these protocols with a question that can be asked
#: and answered without touching the radio.
_AGWPE_PORT = 8000

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
#: outstanding sockets to exhaust a file-descriptor limit and enough
#: concurrent work to bog down a Raspberry Pi doing the scan.
#:
#: This was 64, with a 0.75 s per-attempt timeout and a 3 s overall budget --
#: which is about 21 seconds of work in a 3 second window. The sweep silently
#: gave up after 43 of 254 hosts and reported its partial results as if they
#: were the whole subnet, so a TNC at .128 was invisible while a web server at
#: .3 was offered as a transport. 256 in flight at 0.5 s each finishes a full
#: /24 in a few seconds; `ScanCoverage` exists so that if it still runs short,
#: it says so instead of pretending.
_MAX_CONCURRENT_PROBES = 256

#: Per-connection timeout. A LAN host answers or refuses in single-digit
#: milliseconds; this budget is really for addresses with nothing at them at
#: all, where the wait is an ARP timeout. Long enough not to miss a busy
#: host, short enough that 254 empty addresses do not eat the sweep.
_PER_ATTEMPT_TIMEOUT = 0.5
#: Passive banner read -- short, because most of these services say nothing
#: until spoken to and this must never be the thing that speaks first.
_BANNER_READ_TIMEOUT = 0.2


@dataclass(slots=True)
class ScanCoverage:
    """How much of the subnet a sweep actually reached.

    This exists because the alternative is what the scan used to do: run out
    of time a sixth of the way through a /24 and return its partial results
    with no indication they were partial. "Nothing found" and "gave up before
    looking" are completely different answers for an operator deciding
    whether their TNC is on the network, and a scan that cannot tell them
    apart will send someone to check cabling that is fine.
    """

    subnet: str = ""
    hosts_planned: int = 0
    hosts_reached: int = 0
    probes_planned: int = 0
    probes_done: int = 0

    @property
    def truncated(self) -> bool:
        """Whether any planned probe never happened.

        Counted in PROBES, not hosts. With ports as the outer loop a
        truncated sweep still touches every address on the likeliest port, so
        `hosts_reached` stays at 254 and would call a sweep complete that
        skipped four ports on every one of them.
        """
        return self.probes_done < self.probes_planned

    @property
    def summary(self) -> str:
        if not self.hosts_planned:
            return "no subnet to scan"
        where = f"{self.subnet}.0/24" if self.subnet else "the subnet"
        if not self.truncated:
            return f"scanned all {self.hosts_planned} addresses on {where}"
        return (
            f"ran out of time: {self.probes_done} of {self.probes_planned} "
            f"probes on {where}, {self.hosts_reached} of {self.hosts_planned} "
            f"addresses touched -- a TNC may have been missed; scan again or "
            f"add it by hand"
        )


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


#: Opening bytes that identify a service as something other than a TNC. Each
#: is a protocol greeting or error response no KISS or AGWPE endpoint can
#: produce, which is what makes a match here a *disproof* rather than another
#: heuristic: KISS carries no ASCII protocol layer at all, and AGWPE answers
#: only in 36-byte binary headers.
_NOT_A_TNC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"HTTP/", "a web server (answered with an HTTP status line)"),
    (b"<!DOCTYPE", "a web server (answered with HTML)"),
    (b"<html", "a web server (answered with HTML)"),
    (b"SSH-", "an SSH server"),
    (b"220 ", "an SMTP or FTP server"),
    (b"* OK", "an IMAP server"),
    (b"+OK", "a POP3 server"),
    (b"RFB ", "a VNC server"),
    (b"\x15\x03", "a TLS service (answered with a TLS alert)"),
    (b"\x16\x03", "a TLS service (answered with a TLS handshake)"),
)


@dataclass(slots=True)
class Identity:
    """What an active probe could establish about one TCP port.

    `verdict` is one of:

    * ``"agwpe"`` -- confirmed. The port answered an AGWPE version query in
      AGWPE's own binary framing.
    * ``"kiss"`` -- confirmed. A complete, well-formed KISS frame arrived.
    * ``"not-a-tnc"`` -- confirmed negative. It spoke a protocol no TNC
      speaks, or hung up on a probe a TNC ignores.
    * ``"unknown"`` -- open, silent, still connected. **This is the normal
      state of a healthy KISS TNC on a quiet channel** and must never be
      shown as a failure.
    * ``"unreachable"`` -- nothing accepted a connection.

    Note the asymmetry, because it decides how the UI has to word this: the
    negative is strong and the positive is weak. Proving a port is *not* a
    TNC takes one reply. Proving it *is* a raw KISS TNC takes a frame, and a
    KISS TNC on an idle channel has nothing to send -- KISS has no version
    query, no capability exchange, no greeting. AGWPE is the exception, and
    that is the whole reason its port can be confirmed outright.
    """

    verdict: str
    summary: str
    detail: str = ""

    @property
    def is_tnc(self) -> bool:
        return self.verdict in ("kiss", "agwpe")

    @property
    def is_disproved(self) -> bool:
        return self.verdict == "not-a-tnc"


def _classify_reply(data: bytes) -> Identity | None:
    """A verdict from the bytes a port sent back, or `None` for "no idea"."""
    if not data:
        return None
    for signature, description in _NOT_A_TNC_SIGNATURES:
        if data.startswith(signature):
            text = data[:60].decode("ascii", "replace").strip()
            return Identity(
                "not-a-tnc",
                f"Not a TNC -- this is {description}.",
                f"replied {text!r}",
            )
    decoder = KissDecoder()
    for _frame in decoder.feed(data):
        return Identity(
            "kiss",
            "Confirmed: a KISS TNC. A complete KISS frame arrived.",
            f"{len(data)} bytes, decoded as a KISS frame",
        )
    # Printable text that matched no known greeting is still not KISS: a KISS
    # stream begins with FEND (0xC0), which is not printable ASCII.
    if data[:1] != bytes([FEND]) and all(32 <= b < 127 or b in (9, 10, 13) for b in data):
        text = data[:60].decode("ascii", "replace").strip()
        return Identity(
            "not-a-tnc",
            "Not a TNC -- it answered with text. KISS is a binary framing "
            "and never greets you.",
            f"replied {text!r}",
        )
    return None


async def identify_tcp(
    host: str, port: int, kind: str | None = None, timeout: float = 2.0
) -> Identity:
    """Ask one TCP port what it is, without transmitting anything on the air.

    **What this writes, and why it cannot key a radio.** For an AGWPE port,
    one DataKind ``'R'`` version request -- a question for the *software*,
    which has no on-air meaning. For anything else, two bare ``FEND`` bytes:
    the same probe `probe_kiss_serial` already uses and for the same reason.
    A KISS frame is ``FEND type payload FEND``; two FENDs carry no type byte,
    so there is no command for a TNC to act on and nothing that can become a
    transmission. VARA's ports are never probed at all -- its command channel
    takes line-oriented commands that could start a session, so it is left
    alone and reported as untested.

    **The strong result is the negative.** A web service answers a KISS probe
    with an HTTP error line, or hangs up; either is proof it is not a TNC,
    which is exactly the false positive a port-number-based scan produces. A
    silent port stays ``"unknown"``, because that is genuinely what an idle
    KISS TNC looks like -- see `Identity`.
    """
    if kind in ("vara", "varafm"):
        return Identity(
            "unknown",
            "Not probed: VARA's command port takes line commands that can "
            "start a session, so kissterm does not speak to it uninvited.",
        )

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
    except (OSError, asyncio.TimeoutError) as exc:
        return Identity(
            "unreachable", f"Nothing is listening on {host}:{port}.", str(exc)
        )

    try:
        # Anything it says before being spoken to is free evidence.
        with contextlib.suppress(asyncio.TimeoutError, OSError):
            greeting = await asyncio.wait_for(reader.read(256), timeout=_BANNER_READ_TIMEOUT)
            verdict = _classify_reply(greeting)
            if verdict is not None:
                return verdict

        if kind == "agwpe" or port == _AGWPE_PORT:
            from .transport.agwpe import HEADER_LEN, KIND_VERSION, build_request, parse_header

            writer.write(build_request(KIND_VERSION))
            await writer.drain()
            try:
                header = await asyncio.wait_for(
                    reader.readexactly(HEADER_LEN), timeout=timeout
                )
            except (asyncio.IncompleteReadError, asyncio.TimeoutError, OSError):
                return Identity(
                    "unknown",
                    "Open, but it did not answer an AGWPE version query. "
                    "Not an AGWPE engine, or not one that answers 'R'.",
                )
            verdict = _classify_reply(header)
            if verdict is not None and verdict.is_disproved:
                return verdict
            try:
                _port, reply_kind, data_len = parse_header(header)
            except ValueError:
                return Identity("unknown", "Open, but its reply was not an AGWPE header.")
            payload = b""
            if data_len:
                with contextlib.suppress(Exception):
                    payload = await asyncio.wait_for(
                        reader.readexactly(min(data_len, 512)), timeout=timeout
                    )
            version = _agw_version(payload)
            return Identity(
                "agwpe",
                f"Confirmed: an AGWPE engine{version}.",
                f"answered DataKind {reply_kind.decode('ascii', 'replace')!r}",
            )

        writer.write(bytes([FEND, FEND]))
        await writer.drain()
        try:
            reply = await asyncio.wait_for(reader.read(1024), timeout=timeout)
        except (asyncio.TimeoutError, OSError):
            return Identity(
                "unknown",
                "Open and silent, connection still up -- which is exactly how "
                "a working KISS TNC looks on a quiet channel. Connect and "
                "watch the Monitor tab to be sure.",
            )
        if reply == b"":
            # EOF. A KISS endpoint ignores stray FENDs and holds the socket;
            # hanging up on two bytes is what a service that wanted a request
            # it could parse does.
            return Identity(
                "not-a-tnc",
                "Not a TNC -- it closed the connection when spoken to. A KISS "
                "TNC ignores stray framing bytes and stays connected.",
            )
        verdict = _classify_reply(reply)
        if verdict is not None:
            return verdict
        return Identity(
            "unknown",
            "Open, and it sent bytes that are neither a KISS frame nor any "
            "protocol kissterm recognises.",
            f"{len(reply)} bytes, first: {reply[:16]!r}",
        )
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


def _agw_version(payload: bytes) -> str:
    """`" version 1.2"` from an AGWPE 'R' reply, or `""` if it did not say."""
    if len(payload) >= 8:
        major, minor = struct.unpack("<II", payload[:8])
        return f" version {major}.{minor}"
    return ""


async def discover_network(
    subnet: str | None = None,
    timeout: float = 12.0,
    coverage: ScanCoverage | None = None,
) -> list[DiscoveredDevice]:
    """Scan a local /24 for well-known KISS/AGW/VARA TCP ports.

    `subnet` is a dotted first-three-octets string (``"192.168.1"``); when
    omitted it is derived from the host's own address via
    `_guess_local_subnet`. Pass a `ScanCoverage` to find out how much of the
    subnet was actually reached -- see that class for why that is not
    optional information.

    **Two phases, and the split matters.** Phase one is a plain connect sweep
    of every host and port; phase two asks only the handful that answered
    what they actually are. Identification costs up to a second per port, and
    doing it inline meant a few chatty services could eat the budget for
    entire ranges of the subnet.

    **Ports are the outer loop, hosts the inner one.** Every host is probed on
    8001 before any host is probed on 8300. A sweep that runs out of time then
    degrades into "all hosts, most likely ports" instead of "the first forty
    hosts, every port" -- which is what it used to do, and why a TNC at .128
    was invisible while a web server at .3 was offered.

    Phase two hands each open port to `identify_tcp`. VARA's ports are exempt
    and never spoken to: its command channel takes line-oriented commands that
    could start a session, and "probing for a TNC" must never be the thing
    that keys a transmitter. What goes to the others is two bare FEND bytes or
    one AGWPE version query -- neither can become a transmission, for the
    reasons set out on `identify_tcp` and `probe_kiss_serial`. Ports that
    answer with a protocol no TNC speaks are dropped rather than offered.
    """
    if subnet is None:
        subnet = await asyncio.to_thread(_guess_local_subnet)
    if subnet is None:
        logger.debug("discover_network: could not determine local subnet, skipping")
        return []

    hosts = [f"{subnet}.{octet}" for octet in range(1, 255)]
    ports = [p for p in _WELL_KNOWN_PORTS if _WELL_KNOWN_PORTS[p][1] is not None]
    if coverage is not None:
        coverage.subnet = subnet
        coverage.hosts_planned = len(hosts)
        coverage.probes_planned = len(hosts) * len(ports)

    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_PROBES)
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    #: (host, port) -> the banner it volunteered, if any.
    open_ports: dict[tuple[str, int], bytes] = {}
    reached: set[str] = set()
    #: Probes that actually reached the point of opening a socket. Counted
    #: here rather than derived from unfinished tasks, because a probe that
    #: returns early on the deadline check has "finished" without having
    #: looked at anything -- deriving it from `pending` reported a sweep that
    #: skipped four fifths of its work as complete.
    attempted = 0

    async def _probe_one(host: str, port: int) -> None:
        nonlocal attempted
        async with semaphore:
            if loop.time() >= deadline:
                return
            attempted += 1
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port), timeout=_PER_ATTEMPT_TIMEOUT
                )
            except (OSError, asyncio.TimeoutError):
                reached.add(host)
                return
            reached.add(host)

            banner = b""
            try:
                banner = await asyncio.wait_for(reader.read(64), timeout=_BANNER_READ_TIMEOUT)
            except (asyncio.TimeoutError, OSError):
                banner = b""
            finally:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
            open_ports[(host, port)] = banner

    tasks = [
        asyncio.create_task(_probe_one(host, port))
        for port in ports
        for host in hosts
    ]
    done, pending = await asyncio.wait(tasks, timeout=timeout + 1.0)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    if coverage is not None:
        coverage.hosts_reached = len(reached)
        coverage.probes_done = attempted
        if coverage.truncated:
            logger.warning("network scan incomplete: %s", coverage.summary)

    results: list[DiscoveredDevice] = []
    for (host, port), banner in sorted(open_ports.items()):
        device = await _describe_open_port(host, port, banner)
        if device is not None:
            results.append(device)

    results.sort(key=lambda d: d.confidence, reverse=True)
    return results


async def _describe_open_port(
    host: str, port: int, banner: bytes
) -> DiscoveredDevice | None:
    """One open port, identified, as a device to offer -- or `None` to drop it."""
    service, kind, complete = _WELL_KNOWN_PORTS.get(port, (f"TCP {port}", "tcp", True))
    if kind is None:
        # The data half of a two-port modem. Reporting it as its own device
        # would offer the operator a second thing to connect to that is
        # really the same radio.
        return None

    label = f"{host}:{port}"
    note = _describe_banner(banner)

    # Port number alone is a guess, and on a LAN full of self-hosted services
    # it is a bad one: 8000 and 8001 are as popular with web apps as with
    # packet software. So every candidate that is not VARA gets asked what it
    # actually is. A DISPROVED port is dropped outright rather than listed
    # with a low score -- the module's usual "fail toward listing it" rule is
    # about heuristics being uncertain, and this is not a heuristic: an HTTP
    # status line is proof. Listing it anyway would put a web app into
    # `config.transports`, which is what the scan did before and what sent an
    # operator hunting for a TNC that was never there.
    identity = await identify_tcp(host, port, kind=kind, timeout=1.5)
    if identity.is_disproved:
        logger.debug("discover_network: %s ruled out -- %s", label, identity.summary)
        return None
    confidence = 0.95 if identity.is_tnc else 0.5
    if identity.verdict != "unknown":
        note = identity.summary
    elif not banner:
        note = "open, identity unconfirmed -- nothing said either way"

    if complete:
        config = {"kind": kind, "name": label, "host": host, "port": port}
    else:
        # Found, but not configurable from a probe -- see _WELL_KNOWN_PORTS.
        # Say so rather than writing an entry that is the wrong kind or
        # missing a required field.
        config = {}
        note = (
            f"{note + '; ' if note else ''}needs your callsign and both "
            f"ports -- add a [[transports]] entry by hand"
        ).strip()

    return DiscoveredDevice(
        kind=kind,
        label=label,
        detail=f"{service} at {host}:{port}",
        confidence=confidence,
        config=config,
        note=note,
    )


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


async def discover_all(
    subnet: str | None = None,
    deadline: float = 16.0,
    coverage: ScanCoverage | None = None,
) -> list[DiscoveredDevice]:
    """Run every discovery method concurrently, bounded by one overall deadline.

    Uses `asyncio.wait` with a timeout rather than `asyncio.gather` so that
    a slow method (network scanning is the usual culprit) does not delay
    the results of fast ones (serial enumeration, Bluetooth) past
    `deadline` -- whatever has finished when the deadline passes is
    returned, and whatever has not is cancelled outright. Combined with
    every method's own internal degrade-to-empty behaviour, this function
    itself never raises.
    """
    # The network sweep is the long pole and the only one that can be
    # truncated into a wrong answer, so it gets nearly the whole budget. The
    # default deadline is sized for a full /24 rather than for how long
    # someone is willing to stare at a spinner -- a scan that finishes fast by
    # missing most of the subnet is worse than one that takes ten seconds.
    network_timeout = max(1.0, deadline - 2.0)
    tasks = {
        asyncio.create_task(discover_serial()): "serial",
        asyncio.create_task(
            discover_network(subnet=subnet, timeout=network_timeout, coverage=coverage)
        ): "network",
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
