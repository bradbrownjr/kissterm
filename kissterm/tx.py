"""The master transmit switch -- one gate every outbound byte passes through.

Borrowed, deliberately, from WSJT-X's "Enable Tx": an operator switch that is
off when the program starts and has to be thrown before anything can key a
radio. It is the convention an amateur operator already knows, and it answers
a question kissterm previously answered only by argument -- "can this program
transmit right now?" -- with a switch they can see and a key they can press.

**Why it lives on the transport and not in the UI.** A check in a button
handler is a courtesy, not an interlock: it protects the one path somebody
remembered to guard. This gate sits in `FrameTransport.send_frame` and
`Session.send`, which every frame and every byte goes through regardless of
which pane, timer, state machine or background task produced it. The panes
check it too, but only so the operator gets told *why* nothing happened; the
transport check is the one that makes the guarantee.

**Blocking is silent and counted, never raised.** A packet link is driven by
timers and background tasks, and AX.25 retransmission in particular runs on
`call_later` callbacks with nowhere sensible for an exception to go -- the
house rule is that a background task never dies of one. So a blocked
transmission returns normally and increments `blocked`. Nothing on the air,
nothing crashed, and a number the status bar and `--doctor` can show if the
operator is wondering why a connect is timing out.

**A bare transport transmits.** `Transport` installs an *open* gate by
default, because a transport built by a test, a script, or a probe has no
operator to throw the switch and a safety interlock nobody can reach is just
a broken program. The gate that is closed by default is the one
`KissTermApp` installs from `Config.tx_armed_at_start`, because the app is
the thing that has an operator. `tests/pilot/test_transmit_gate.py` asserts a
freshly mounted app cannot transmit.

**A latch holds it closed with a reason** (ROADMAP P3a M5b, the SWR trip):
`latch_closed(reason)` closes the gate and refuses every `set(True)` until
`clear_latch()`, so every existing gate check -- the transports, the beacon,
answering, `Connector.arm_for` -- honours a trip unchanged. Only the
operator's own re-arm clears it (`core/swr.py`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

log = logging.getLogger(__name__)

class TransmitGate:
    """Open or closed. Closed means nothing reaches the air."""

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = enabled
        #: Transmissions suppressed since the last time the gate was opened.
        #: Reset on open rather than accumulating forever: the number is only
        #: useful as "things this closed gate stopped", and a lifetime total
        #: tells the operator nothing about the state they are in now.
        self.blocked = 0
        self.on_change: list[Callable[[bool], None]] = []
        #: Why the gate is held closed ("" when it is not): see the module
        #: docstring.
        self.latch = ""

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set(self, enabled: bool) -> bool:
        """Open or close the gate. Returns the new state."""
        if enabled and self.latch:
            log.warning("transmit stays off: %s", self.latch)
            return self._enabled
        if enabled == self._enabled:
            return self._enabled
        self._enabled = enabled
        if enabled:
            self.blocked = 0
        log.info("transmit %s", "enabled" if enabled else "disabled")
        # A listener that throws must not be able to jam the switch in
        # whichever position it happened to be in (`_tell` logs it).
        self._tell(enabled)
        return self._enabled

    def latch_closed(self, reason: str) -> None:
        """Close the gate and hold it closed until `clear_latch`."""
        self.latch = reason
        log.warning("transmit latched off: %s", reason)
        if self._enabled:
            self.set(False)
        else:
            self._tell(False)

    def clear_latch(self) -> None:
        """The operator's re-arm: `set(True)` works again. The gate stays
        closed until it is set."""
        if self.latch:
            self.latch = ""
            log.warning("transmit latch cleared")
            self._tell(self._enabled)

    def _tell(self, enabled: bool) -> None:
        for callback in list(self.on_change):
            try:
                callback(enabled)
            except Exception:
                log.exception("transmit gate listener failed")

    def toggle(self) -> bool:
        return self.set(not self._enabled)

    def allow(self) -> bool:
        """Whether a transmission may proceed. Counts it if not.

        Called on every outbound frame, so it stays cheap and total -- no
        raising, no logging per call. See the module docstring on why a block
        is silent here and reported by the UI instead.
        """
        if self._enabled:
            return True
        self.blocked += 1
        return False

    def __repr__(self) -> str:
        state = "open" if self._enabled else f"closed, {self.blocked} blocked"
        if self.latch:
            state += f", latched: {self.latch}"
        return f"<TransmitGate {state}>"
