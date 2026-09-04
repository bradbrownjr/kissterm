"""The Terminal pane: the session scrollback and the line the operator types.

This is the pane the whole program exists for, and it carries two rules that
are load-bearing rather than stylistic.

**Everything arriving from the far end goes through `monitor.sanitize()`.**
Those bytes were put on the air by somebody else's transmitter. Written to a
widget raw they can carry ANSI escape sequences that clear the screen, repaint
it, set the window title, or provoke a terminal response the shell later reads.
This is not paranoia about malicious operators -- a corrupt frame off a noisy
channel produces the same bytes by accident, and losing the display in the
middle of an emergency net is the failure that actually matters. `sanitize` is
the only thing standing between the radio and the operator's terminal; do not
add a path around it.

**Lines go out CR-terminated, not LF.** Packet nodes and BBSes are CR-oriented.
Sending LF makes a BPQ32 node echo a spurious blank line after every command,
which looks like a kissterm bug and is not.

The pane owns its own submit handler rather than leaving it on the app, so that
changing how typed input is handled means opening this file and nothing else.
It reaches the active link as `self.app.link`, a documented attribute of
`KissTermApp`.
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Input, RichLog

from ..monitor import sanitize


class TerminalPane(Container):
    """Session scrollback (`#session-log`) above the input line (`#session-input`)."""

    def compose(self) -> ComposeResult:
        yield RichLog(
            id="session-log", wrap=True, markup=False, highlight=False, max_lines=5000
        )
        yield Input(placeholder="not connected -- Ctrl+N to connect", id="session-input")

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    def log(self, text: str) -> None:
        """Write locally-generated text -- status notes, echoes of what we sent.

        Deliberately separate from `write_incoming`: text that kissterm itself
        produced is already trusted, and routing it through `sanitize` would
        quietly strip formatting we chose on purpose.
        """
        self.query_one("#session-log", RichLog).write(text)

    def write_incoming(self, data: bytes) -> None:
        """Write bytes received from the far end. Sanitized -- see the docstring."""
        self.query_one("#session-log", RichLog).write(sanitize(data), expand=True)

    def clear(self) -> None:
        self.query_one("#session-log", RichLog).clear()

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def set_placeholder(self, text: str) -> None:
        self.query_one("#session-input", Input).placeholder = text

    def focus_input(self) -> None:
        self.query_one("#session-input", Input).focus()

    @on(Input.Submitted, "#session-input")
    async def _send_line(self, event: Input.Submitted) -> None:
        text = event.value
        event.input.value = ""
        link = getattr(self.app, "link", None)
        if link is None or not link.connected:
            self.app.notify("Not connected.", severity="warning")
            return
        # latin-1, not UTF-8: packet is a byte-oriented medium and a callsign
        # or payload the operator pasted must not fail to encode mid-session.
        # CR, not LF -- see the module docstring.
        await link.send(text.encode("latin-1", "replace") + b"\r")
        self.log(text + "\n")
