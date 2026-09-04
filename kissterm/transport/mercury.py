"""Mercury (Rafael Diniz, github.com/rafael2k/mercury) -- not implemented.

Mercury is an open-source HF digital-voice/data modem. Unlike VARA, its
source is public, which means its wire protocol *can* eventually be nailed
down precisely instead of inferred from third-party summaries -- but that
work has not been done yet, and this module does not guess at it. A modem
transport is exactly the kind of code where an invented framing detail
(a wrong length field, a wrong sync byte) does not fail loudly; it produces
a plausible-looking implementation that silently corrupts every session run
through it. That is a worse outcome than admitting the gap, so `open()`
below raises immediately and unconditionally rather than pretending to
half-work.

This module exists anyway, ahead of the real implementation, so that:

* `kissterm.transport.build_transport` has a stable `"mercury"` kind to
  dispatch to today, and callers get a clear `TransportError` instead of a
  `KeyError` or an import failure when they select it;
* the shape of a Mercury transport (SessionTransport, not FrameTransport --
  see the `# RESEARCH` note below) is decided and documented now, so the
  eventual implementation is a matter of filling in `open`/`connect`/`close`
  against the shape here, not re-deriving the architecture; and
* the specific unknowns are written down in one place instead of scattered
  across issues, so whoever picks this up next knows exactly where to start
  reading upstream.

# RESEARCH: everything below needs verifying against github.com/rafael2k/mercury
# before this can be implemented for real.
#
# 1. Wire shape -- is Mercury controlled over a local TCP/serial control
#    channel the way VARA is (a command port plus a data port), or is it a
#    library/CLI invoked as a subprocess with pipes, or a shared-memory /
#    JACK-style audio interface with no separate "modem protocol" at all?
#    This determines whether MercuryTransport even belongs in this package
#    as network I/O, or whether it should shell out to a `mercury` binary.
# 2. If there is a control protocol: is it line-oriented ASCII like VARA, a
#    binary framed protocol, or something else? What are its connect/
#    disconnect/status commands and their exact spellings?
# 3. Does Mercury do its own ARQ/link-layer addressing (making this rightly
#    a SessionTransport, mirrored below), or does it hand back raw
#    demodulated bytes with no addressing of its own (which would make it
#    closer to a sound-card modem needing an AX.25 layer on top, i.e.
#    arguably a FrameTransport candidate instead)? This is the single
#    biggest open question and decides which ABC this class should actually
#    extend.
# 4. What does Mercury report for link quality / buffer occupancy, if
#    anything -- is there an analogue of VARA's `BUFFER n` to base flow
#    control on, or does it rely on the control channel's own backpressure?
# 5. Is there an existing Python binding, or would this need FFI/subprocess
#    integration against a C/C++ library?
#
# The SessionTransport shape is assumed for now on the basis that an HF ARQ
# modem "in the spirit of VARA" most plausibly runs its own link layer, but
# this is exactly the kind of assumption item 3 above exists to check --
# treat it as a placeholder, not a conclusion.
"""

from __future__ import annotations

from ..ax25.address import AX25Path
from .base import Session, SessionTransport, TransportError, TransportInfo, TransportState


class MercuryTransport(SessionTransport):
    """Placeholder for a future Mercury HF modem transport. Not implemented.

    Every method here exists only to satisfy the `SessionTransport` ABC and
    to fail predictably and clearly; none of it should be taken as a
    statement about Mercury's real protocol. See the module docstring's
    ``# RESEARCH`` list for what has to be confirmed against the upstream
    Mercury source before this can be filled in for real.
    """

    def __init__(self, host: str = "", port: int = 0, mycall: str = "") -> None:
        info = TransportInfo(
            kind="mercury",
            name=host or "mercury",
            detail=f"{host}:{port}" if host else "not configured",
            tier="session",
        )
        super().__init__(info)
        self.host = host
        self.port = port
        self.mycall = mycall

    async def open(self) -> None:
        self.state = TransportState.ERROR
        self._error = "Mercury support is not implemented yet"
        raise TransportError("Mercury support is not implemented yet -- see docs/ROADMAP.md")

    async def connect(self, path: AX25Path) -> Session:
        raise TransportError("Mercury support is not implemented yet -- see docs/ROADMAP.md")

    async def close(self) -> None:
        self.state = TransportState.CLOSED
