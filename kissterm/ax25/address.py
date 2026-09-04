"""AX.25 address-field encoding and decoding.

An AX.25 address is 7 bytes: six callsign characters followed by an SSID byte.
Every callsign character is **shifted left one bit** so the LSB of each byte is
free to carry the "last address in the field" extension flag -- that shift is
why a raw AX.25 frame never looks like ASCII in a hex dump.

SSID byte layout (MSB first)::

    C/H  R  R  S3 S2 S1 S0  Ext
    0x80          0x1E       0x01

* ``C/H`` -- on the destination/source pair this is the **command/response**
  bit (see `AX25Path.command`); on a digipeater it is the **has-been-repeated**
  bit.
* ``R R`` -- reserved, transmitted as 1s.
* ``Ext`` -- 1 on the final address of the field, 0 otherwise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ADDR_LEN = 7
_CALLSIGN_RE = re.compile(r"^[A-Z0-9]{1,6}$")

#: SSID-byte bit masks.
CH_BIT = 0x80
RESERVED_BITS = 0x60
SSID_MASK = 0x1E
EXT_BIT = 0x01


class AX25AddressError(ValueError):
    """A callsign or address field could not be parsed or encoded."""


@dataclass(frozen=True, slots=True)
class AX25Address:
    """One 7-byte AX.25 address: a callsign, an SSID, and one flag bit.

    ``ch`` is overloaded by position in the address field, exactly as the
    protocol overloads it: command/response for destination and source,
    has-been-repeated for a digipeater. Nothing here interprets it -- that is
    `AX25Path`'s job, because only position gives it meaning.
    """

    callsign: str
    ssid: int = 0
    ch: bool = False

    def __post_init__(self) -> None:
        if not _CALLSIGN_RE.match(self.callsign):
            raise AX25AddressError(
                f"invalid callsign {self.callsign!r}: 1-6 chars of A-Z and 0-9"
            )
        if not 0 <= self.ssid <= 15:
            raise AX25AddressError(f"SSID {self.ssid} out of range 0-15")

    # -- text ------------------------------------------------------------
    @classmethod
    def parse(cls, text: str, ch: bool = False) -> "AX25Address":
        """Parse ``"WS1EC-7"`` (or ``"WS1EC"``) into an address.

        A trailing ``*`` -- the conventional way a monitor listing marks a
        digipeater that has already repeated the frame -- sets ``ch``.
        """
        text = text.strip().upper()
        if text.endswith("*"):
            ch = True
            text = text[:-1]
        call, _, ssid_text = text.partition("-")
        if not ssid_text:
            ssid = 0
        else:
            try:
                ssid = int(ssid_text)
            except ValueError:
                raise AX25AddressError(f"invalid SSID in {text!r}") from None
        return cls(call, ssid, ch)

    def __str__(self) -> str:
        return self.callsign if self.ssid == 0 else f"{self.callsign}-{self.ssid}"

    def display(self) -> str:
        """`str` plus a trailing ``*`` when the has-been-repeated bit is set."""
        return f"{self}*" if self.ch else str(self)

    # -- wire ------------------------------------------------------------
    def encode(self, last: bool = False) -> bytes:
        """Encode to 7 bytes. ``last`` sets the extension bit."""
        padded = self.callsign.ljust(6)
        out = bytearray(c << 1 for c in padded.encode("ascii"))
        ssid_byte = RESERVED_BITS | (self.ssid << 1)
        if self.ch:
            ssid_byte |= CH_BIT
        if last:
            ssid_byte |= EXT_BIT
        out.append(ssid_byte)
        return bytes(out)

    @classmethod
    def decode(cls, raw: bytes) -> tuple["AX25Address", bool]:
        """Decode 7 bytes into ``(address, is_last)``."""
        if len(raw) != ADDR_LEN:
            raise AX25AddressError(f"address needs {ADDR_LEN} bytes, got {len(raw)}")
        call = bytes(b >> 1 for b in raw[:6]).decode("ascii", "replace").rstrip()
        # Real-world frames arrive with junk in the callsign field often enough
        # (a corrupt frame that still passed the modem's CRC) that raising here
        # would drop otherwise-decodable monitor traffic. Sanitize instead.
        call = "".join(c for c in call.upper() if c.isalnum()) or "?"
        ssid_byte = raw[6]
        addr = cls(
            callsign=call[:6],
            ssid=(ssid_byte & SSID_MASK) >> 1,
            ch=bool(ssid_byte & CH_BIT),
        )
        return addr, bool(ssid_byte & EXT_BIT)


@dataclass(frozen=True, slots=True)
class AX25Path:
    """A whole address field: destination, source, and up to 8 digipeaters.

    `command` and `response` read the two C bits together, which is the only
    way they mean anything: AX.25 2.x encodes a command as *dest C set, source
    C clear* and a response as the reverse. A frame with both bits equal is
    legacy AX.25 1.x, where the distinction simply does not exist -- both
    properties return False for it rather than guessing.
    """

    destination: AX25Address
    source: AX25Address
    repeaters: tuple[AX25Address, ...] = ()

    MAX_REPEATERS = 8

    def __post_init__(self) -> None:
        if len(self.repeaters) > self.MAX_REPEATERS:
            raise AX25AddressError(
                f"at most {self.MAX_REPEATERS} digipeaters, got {len(self.repeaters)}"
            )

    @property
    def command(self) -> bool:
        return self.destination.ch and not self.source.ch

    @property
    def response(self) -> bool:
        return self.source.ch and not self.destination.ch

    @property
    def legacy(self) -> bool:
        """True for AX.25 1.x framing, where neither C bit distinguishes."""
        return self.destination.ch == self.source.ch

    def with_command(self, command: bool) -> "AX25Path":
        """Return a copy whose C bits mark it as a command or a response."""
        return AX25Path(
            destination=AX25Address(
                self.destination.callsign, self.destination.ssid, ch=command
            ),
            source=AX25Address(self.source.callsign, self.source.ssid, ch=not command),
            repeaters=self.repeaters,
        )

    def reply(self, command: bool = False) -> "AX25Path":
        """Swap source and destination for a frame heading the other way.

        The digipeater list is reversed and every has-been-repeated bit is
        cleared, since the return trip has not traversed any of them yet.
        """
        return AX25Path(
            destination=AX25Address(self.source.callsign, self.source.ssid, ch=command),
            source=AX25Address(
                self.destination.callsign, self.destination.ssid, ch=not command
            ),
            repeaters=tuple(
                AX25Address(r.callsign, r.ssid, ch=False)
                for r in reversed(self.repeaters)
            ),
        )

    @property
    def next_repeater(self) -> AX25Address | None:
        """The first digipeater that has not yet repeated this frame."""
        for rpt in self.repeaters:
            if not rpt.ch:
                return rpt
        return None

    def encode(self) -> bytes:
        addrs = [self.destination, self.source, *self.repeaters]
        return b"".join(
            a.encode(last=(i == len(addrs) - 1)) for i, a in enumerate(addrs)
        )

    @classmethod
    def decode(cls, raw: bytes) -> tuple["AX25Path", int]:
        """Decode an address field. Returns ``(path, bytes_consumed)``."""
        addrs: list[AX25Address] = []
        offset = 0
        while True:
            if offset + ADDR_LEN > len(raw):
                raise AX25AddressError("address field truncated (no extension bit)")
            addr, last = AX25Address.decode(raw[offset : offset + ADDR_LEN])
            addrs.append(addr)
            offset += ADDR_LEN
            if last:
                break
            if len(addrs) > 2 + cls.MAX_REPEATERS:
                raise AX25AddressError("address field runs past 10 addresses")
        if len(addrs) < 2:
            raise AX25AddressError("address field needs destination and source")
        return cls(addrs[0], addrs[1], tuple(addrs[2:])), offset

    def __str__(self) -> str:
        base = f"{self.source}>{self.destination}"
        if self.repeaters:
            base += "," + ",".join(r.display() for r in self.repeaters)
        return base


def parse_path(text: str) -> AX25Path:
    """Parse ``"WS1EC-7 VIA W1AW-1,W1XYZ"`` / ``"WS1EC-7"`` into a path.

    The source is left as a placeholder (``NOCALL``); callers overwrite it with
    the station's own callsign. This exists so a user can type a connect target
    and a digipeater path as one string.
    """
    text = text.strip()
    parts = re.split(r"\s+(?:via|VIA|v|V)\s+|\s+", text, maxsplit=1)
    dest = AX25Address.parse(parts[0])
    repeaters: tuple[AX25Address, ...] = ()
    if len(parts) > 1 and parts[1].strip():
        repeaters = tuple(
            AX25Address.parse(p) for p in re.split(r"[,\s]+", parts[1].strip()) if p
        )
    return AX25Path(dest, AX25Address("NOCALL"), repeaters)
