"""AX.25 frame encoding and decoding (modulo-8 and modulo-128).

A frame is an address field (`kissterm.ax25.address.AX25Path`), a control
field, an optional PID, and an optional information field. The FCS is *not*
here: KISS TNCs add and strip it themselves, so a frame handed to or received
from a KISS transport never carries one.

Control-field layout, modulo 8 (one byte)::

    I:  N(R) N(R) N(R)  P/F  N(S) N(S) N(S)  0      bit0 = 0
    S:  N(R) N(R) N(R)  P/F   SS   SS   0    1      bits 0-1 = 01
    U:   MM   MM   MM   P/F   MM   MM   1    1      bits 0-1 = 11

Modulo 128 widens I and S control fields to two bytes so the sequence numbers
can reach 127; U frames stay one byte in both modes. That asymmetry is the
single most common source of off-by-one bugs in an AX.25 implementation, so
every encoder and decoder below takes ``modulo`` explicitly rather than
reading it from ambient state.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from .address import AX25Path

#: Protocol IDs. Terminal traffic is always NO_LAYER3.
PID_NO_LAYER3 = 0xF0
PID_NETROM = 0xCF
PID_IP = 0xCC
PID_ARP = 0xCD

MODULO8 = 8
MODULO128 = 128

#: Maximum information-field bytes in one I frame (AX.25 2.2 default N1).
DEFAULT_PACLEN = 256
#: Maximum unacknowledged I frames in flight (window, AX.25 2.2 default k).
DEFAULT_WINDOW = 4


class AX25FrameError(ValueError):
    """A frame could not be parsed or built."""


class UType(enum.IntEnum):
    """Unnumbered-frame modifiers, with the P/F bit already masked out."""

    SABME = 0x6F  # set async balanced mode extended -- ask for modulo 128
    SABM = 0x2F  # set async balanced mode -- ask for modulo 8
    DISC = 0x43  # disconnect
    DM = 0x0F  # disconnected mode -- "I will not / cannot connect"
    UA = 0x63  # unnumbered acknowledge
    FRMR = 0x87  # frame reject (AX.25 2.0; 2.2 prefers to just reset)
    UI = 0x03  # unnumbered information -- beacons, APRS, unproto
    XID = 0xAF  # exchange identification -- parameter negotiation
    TEST = 0xE3


class SType(enum.IntEnum):
    """Supervisory-frame types, as the 2-bit field value."""

    RR = 0  # receive ready
    RNR = 1  # receive not ready -- busy
    REJ = 2  # reject -- go-back-N retransmit request
    SREJ = 3  # selective reject (AX.25 2.2)


PF_BIT = 0x10  # poll/final, modulo-8 control byte


@dataclass(slots=True)
class AX25Frame:
    """One decoded AX.25 frame.

    Exactly one of ``utype`` / ``stype`` / ``ns`` is meaningful depending on
    `kind`; the unused fields stay ``None``. `pid` is present only on I and UI
    frames -- the only two frame types that carry a layer-3 payload.
    """

    path: AX25Path
    kind: str  # "I" | "S" | "U"
    pid: int | None = None
    info: bytes = b""
    ns: int | None = None  # I frames only
    nr: int | None = None  # I and S frames
    pf: bool = False
    utype: UType | None = None
    stype: SType | None = None
    modulo: int = MODULO8

    # -- constructors ----------------------------------------------------
    @classmethod
    def i_frame(
        cls,
        path: AX25Path,
        ns: int,
        nr: int,
        info: bytes,
        *,
        pf: bool = False,
        pid: int = PID_NO_LAYER3,
        modulo: int = MODULO8,
    ) -> "AX25Frame":
        return cls(
            path=path.with_command(True),
            kind="I",
            pid=pid,
            info=info,
            ns=ns % modulo,
            nr=nr % modulo,
            pf=pf,
            modulo=modulo,
        )

    @classmethod
    def s_frame(
        cls,
        path: AX25Path,
        stype: SType,
        nr: int,
        *,
        pf: bool = False,
        command: bool = False,
        modulo: int = MODULO8,
    ) -> "AX25Frame":
        return cls(
            path=path.with_command(command),
            kind="S",
            stype=stype,
            nr=nr % modulo,
            pf=pf,
            modulo=modulo,
        )

    @classmethod
    def u_frame(
        cls,
        path: AX25Path,
        utype: UType,
        *,
        pf: bool = False,
        command: bool = True,
        info: bytes = b"",
        pid: int | None = None,
    ) -> "AX25Frame":
        if utype is UType.UI and pid is None:
            pid = PID_NO_LAYER3
        return cls(
            path=path.with_command(command),
            kind="U",
            utype=utype,
            pf=pf,
            info=info,
            pid=pid,
        )

    # -- properties ------------------------------------------------------
    @property
    def command(self) -> bool:
        return self.path.command

    @property
    def response(self) -> bool:
        return self.path.response

    @property
    def control_name(self) -> str:
        """Short human name used by the monitor pane, e.g. ``"I"``, ``"RR"``."""
        if self.kind == "I":
            return "I"
        if self.kind == "S":
            return self.stype.name if self.stype is not None else "S?"
        return self.utype.name if self.utype is not None else "U?"

    # -- wire ------------------------------------------------------------
    def _encode_control(self) -> bytes:
        if self.kind == "U":
            assert self.utype is not None
            return bytes([int(self.utype) | (PF_BIT if self.pf else 0)])

        if self.modulo == MODULO128:
            # Two bytes: sequence numbers occupy bits 1-7 of each byte, and the
            # P/F bit moves down to bit 0 of the *second* byte.
            if self.kind == "I":
                assert self.ns is not None and self.nr is not None
                return bytes(
                    [(self.ns << 1) & 0xFE, (self.nr << 1) | (0x01 if self.pf else 0)]
                )
            assert self.stype is not None and self.nr is not None
            return bytes(
                [
                    0x01 | (int(self.stype) << 2),
                    (self.nr << 1) | (0x01 if self.pf else 0),
                ]
            )

        if self.kind == "I":
            assert self.ns is not None and self.nr is not None
            return bytes(
                [(self.nr << 5) | (PF_BIT if self.pf else 0) | (self.ns << 1)]
            )
        assert self.stype is not None and self.nr is not None
        return bytes(
            [(self.nr << 5) | (PF_BIT if self.pf else 0) | (int(self.stype) << 2) | 0x01]
        )

    def encode(self) -> bytes:
        out = bytearray(self.path.encode())
        out += self._encode_control()
        if self.pid is not None:
            out.append(self.pid)
        out += self.info
        return bytes(out)

    @classmethod
    def decode(cls, raw: bytes, modulo: int = MODULO8) -> "AX25Frame":
        """Decode one frame.

        ``modulo`` is what the *caller's link* negotiated. It cannot be read off
        the wire: a modulo-128 I frame is indistinguishable from a modulo-8 one
        by inspection, which is exactly why SABME/UA negotiation has to happen
        before any I frame is exchanged. Unproto listeners (the monitor pane)
        pass modulo 8, the near-universal case.
        """
        path, used = AX25Path.decode(raw)
        rest = raw[used:]
        if not rest:
            raise AX25FrameError("frame has no control field")

        ctrl = rest[0]
        # U frames are one byte in both modes; test for them before widening.
        if ctrl & 0x03 == 0x03:
            utype_val = ctrl & ~PF_BIT & 0xFF
            try:
                utype = UType(utype_val)
            except ValueError:
                raise AX25FrameError(f"unknown U-frame modifier 0x{utype_val:02X}")
            body = rest[1:]
            pid = None
            if utype in (UType.UI, UType.TEST) and body:
                pid, body = body[0], body[1:]
            return cls(
                path=path,
                kind="U",
                utype=utype,
                pf=bool(ctrl & PF_BIT),
                info=body,
                pid=pid,
            )

        if modulo == MODULO128:
            if len(rest) < 2:
                raise AX25FrameError("modulo-128 control field truncated")
            b0, b1 = rest[0], rest[1]
            pf = bool(b1 & 0x01)
            nr = (b1 >> 1) & 0x7F
            body = rest[2:]
            if b0 & 0x01 == 0:
                ns = (b0 >> 1) & 0x7F
                if not body:
                    raise AX25FrameError("I frame has no PID")
                return cls(
                    path=path,
                    kind="I",
                    pid=body[0],
                    info=body[1:],
                    ns=ns,
                    nr=nr,
                    pf=pf,
                    modulo=MODULO128,
                )
            return cls(
                path=path,
                kind="S",
                stype=SType((b0 >> 2) & 0x03),
                nr=nr,
                pf=pf,
                modulo=MODULO128,
            )

        pf = bool(ctrl & PF_BIT)
        nr = (ctrl >> 5) & 0x07
        body = rest[1:]
        if ctrl & 0x01 == 0:
            if not body:
                raise AX25FrameError("I frame has no PID")
            return cls(
                path=path,
                kind="I",
                pid=body[0],
                info=body[1:],
                ns=(ctrl >> 1) & 0x07,
                nr=nr,
                pf=pf,
            )
        return cls(
            path=path, kind="S", stype=SType((ctrl >> 2) & 0x03), nr=nr, pf=pf
        )

    # -- display ---------------------------------------------------------
    def summary(self) -> str:
        """One monitor-pane line, ``listen -a`` style, without the payload."""
        bits = [str(self.path), self.control_name]
        if self.kind == "I":
            bits.append(f"S{self.ns} R{self.nr}")
        elif self.kind == "S":
            bits.append(f"R{self.nr}")
        if self.pf:
            bits.append("P" if self.command else "F")
        if self.command:
            bits.append("cmd")
        elif self.response:
            bits.append("res")
        if self.info:
            bits.append(f"len={len(self.info)}")
        return " ".join(bits)
