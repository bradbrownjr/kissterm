"""The sliding window: V(S), V(R), V(A), and every piece of modular arithmetic.

This is carved out of the state machine deliberately. Almost every subtle bug
an AX.25 implementation has lives in these forty lines of sequence-number
arithmetic, not in the state transitions -- and here it can be unit-tested
exhaustively without an event loop, a transport, or a peer.

The one rule that matters: **sequence numbers wrap.** Comparing them as plain
integers is always wrong. ``while self.va < nr`` looks correct, passes a test
that sends five frames, and then silently stops acknowledging the first time
N(R) wraps past zero -- at which point the window jams shut and the link stalls
forever. The symptom an operator reports is "it stops after exactly 8 frames".
Every comparison here is therefore a modular walk, never a magnitude test.

`sent` retains the payload of each unacknowledged I frame because AX.25
retransmission is the sender's job: there is no request-and-resend handshake,
just "N(R) says they never got frame 3", and the sender must still have frame 3
to put back on the air.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field


@dataclass(slots=True)
class SlidingWindow:
    """Send/receive sequence state for one link.

    `modulo` is 8 or 128; `k` is the number of I frames that may be outstanding
    at once. Both come from the link's negotiated parameters, and neither may
    change while frames are in flight -- reset the window instead.
    """

    modulo: int = 8
    k: int = 4

    vs: int = 0  # V(S) -- next N(S) to send
    vr: int = 0  # V(R) -- next N(S) expected from the peer
    va: int = 0  # V(A) -- oldest N(S) not yet acknowledged
    sent: dict[int, bytes] = field(default_factory=dict)

    # -- send side -------------------------------------------------------
    @property
    def outstanding(self) -> int:
        """How many I frames are on the air unacknowledged."""
        return (self.vs - self.va) % self.modulo

    @property
    def is_open(self) -> bool:
        """True when another I frame may be sent without exceeding k."""
        return self.outstanding < self.k

    @property
    def fully_acked(self) -> bool:
        return self.va == self.vs

    def record_sent(self, info: bytes) -> int:
        """Assign the next N(S) to ``info`` and advance V(S). Returns that N(S)."""
        ns = self.vs
        self.sent[ns] = info
        self.vs = (self.vs + 1) % self.modulo
        return ns

    def ack_upto(self, nr: int) -> bool:
        """Advance V(A) to N(R), discarding acknowledged frames.

        Returns True if anything was actually acknowledged, which the state
        machine reads as proof the peer is alive and hearing us.
        """
        nr %= self.modulo
        advanced = False
        # Bounded by modulo so a peer sending a nonsensical N(R) cannot spin
        # this loop; the walk visits each sequence number at most once.
        for _ in range(self.modulo):
            if self.va == nr:
                break
            self.sent.pop(self.va, None)
            self.va = (self.va + 1) % self.modulo
            advanced = True
        return advanced

    def pending_from(self, nr: int) -> Iterator[tuple[int, bytes]]:
        """Go-back-N: every frame from N(R) up to V(S), in order."""
        seq = nr % self.modulo
        for _ in range(self.modulo):
            if seq == self.vs:
                return
            info = self.sent.get(seq)
            if info is not None:
                yield seq, info
            seq = (seq + 1) % self.modulo

    def pending_one(self, nr: int) -> bytes | None:
        """Selective reject: just the one frame the peer asked for."""
        return self.sent.get(nr % self.modulo)

    # -- receive side ----------------------------------------------------
    def accept(self, ns: int) -> bool:
        """Accept an I frame if it is the one expected, advancing V(R).

        Returns False for anything out of sequence. AX.25 has no reordering
        buffer in the base spec -- an out-of-sequence frame is discarded and a
        REJ asks for the whole window again -- so there is deliberately nowhere
        here to stash it.
        """
        if ns != self.vr:
            return False
        self.vr = (self.vr + 1) % self.modulo
        return True

    # -- lifecycle -------------------------------------------------------
    def reset(self) -> None:
        """Return to the post-SABM state. Called on connect and re-establish.

        Re-clamps k because `modulo` may have changed since construction -- a
        SABME refused with DM falls the link back to modulo 8, and a k of 8
        that was legal under modulo 128 is not legal under modulo 8.
        """
        self._clamp_k()
        self.vs = self.vr = self.va = 0
        self.sent.clear()

    def __post_init__(self) -> None:
        self._clamp_k()

    def _clamp_k(self) -> None:
        """Enforce k < modulo, the invariant the whole window rests on.

        With k == modulo, a completely full window and a completely empty one
        produce identical V(S) and V(A): `outstanding` reads 0 for both and
        `ack_upto` acknowledges nothing, so the link jams at exactly one full
        cycle. AX.25 caps k at 7 for modulo 8 and 63 for modulo 128 for this
        reason. `LinkParams` clamps too, but the invariant is enforced *here*
        as well on purpose -- this is where the arithmetic that depends on it
        lives, and a window built directly (by a test, or a future caller)
        must not be able to violate it.
        """
        self.k = max(1, min(self.k, self.modulo - 1))

    def __repr__(self) -> str:
        return (
            f"<SlidingWindow mod{self.modulo} k={self.k} "
            f"V(S)={self.vs} V(R)={self.vr} V(A)={self.va} "
            f"outstanding={self.outstanding}>"
        )
