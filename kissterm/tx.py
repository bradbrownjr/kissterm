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
"""

from __future__ import annotations

import logging
from collections.abc import Callable

log = logging.getLogger(__name__)

#: What the UI says when it refuses. One string so the terminal pane, the
#: connect dialog and the beacon cannot drift into three different wordings
#: for the same state.
DISABLED_MESSAGE = "Transmit is disabled -- press Ctrl+T to enable it."


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

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set(self, enabled: bool) -> bool:
        """Open or close the gate. Returns the new state."""
        if enabled == self._enabled:
            return self._enabled
        self._enabled = enabled
        if enabled:
            self.blocked = 0
        log.info("transmit %s", "enabled" if enabled else "disabled")
        for callback in list(self.on_change):
            try:
                callback(enabled)
            except Exception:
                # A listener that throws must not be able to jam the switch
                # in whichever position it happened to be in.
                log.exception("transmit gate listener failed")
        return self._enabled

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
        return f"<TransmitGate {state}>"
