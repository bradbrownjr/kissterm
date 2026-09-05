"""The Terminal pane: read-only scrollback above a deliberate send line.

The shape is the one a packet operator expects and the one that is safe: the
conversation above is **display only** -- scroll it, select it, copy from it,
follow a link in it -- and the single-line field at the bottom is the *only*
thing that ever puts bytes on the air, and only when the operator commits with
Enter or the Send button.

Four rules here are load-bearing, not stylistic.

**Everything from the far end is filtered before it reaches a widget.** Those
bytes were put on the air by somebody else's transmitter. Written raw they can
carry ANSI escapes that clear the screen, repaint it, set the window title, or
provoke a terminal response the shell later reads. This is not paranoia about
malicious operators: a corrupt frame off a noisy channel produces the same
bytes by accident, and losing the display in the middle of an emergency net is
the failure that matters.

Two filters, and which one runs is the operator's choice, not the sender's.
`monitor.sanitize()` removes every escape sequence; `ansi.to_text()` keeps
allowlisted SGR -- colour, bold, underline -- and removes everything else, so a
BBS that has painted its menus in colour since 1988 still reads the way its
sysop meant it to. **Both remove cursor movement, screen erase, OSC (window
title, clipboard, hyperlink) and DCS unconditionally**; `remote_color` chooses
between "colour too" and "text only", never between safe and unsafe. See
`kissterm/ansi.py` for why that is an allowlist and not a denylist.

**Nothing transmits except through `send_line`.** One choke point, so "can this
possibly key the transmitter?" is answerable by reading one method. Suggestions
and completions may *fill the input*, and the operator still has to commit --
a completion that transmits on its own would be a defect on a shared channel.

**Lines go out CR-terminated, not LF.** Packet nodes and BBSes are CR-oriented;
LF makes a BPQ32 node echo a spurious blank line after every command.

**Links are built here, never parsed from remote markup.** URLs are detected in
already-filtered text and the link target is set to exactly the matched
substring, so what is displayed and what would open can never differ. Remote
text is not permitted to supply markup of its own -- notably including OSC 8,
the terminal hyperlink sequence, which is exactly a way to display one address
and open another and is removed with the rest of OSC.
"""

from __future__ import annotations

import re

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, Input, RichLog

from ..ansi import to_text
from ..monitor import sanitize
from ..tx import DISABLED_MESSAGE

#: Conservative URL match. Trailing punctuation is excluded so a link at the
#: end of a sentence does not swallow the full stop into the target.
_URL_RE = re.compile(r"\b((?:https?|gopher|gemini|ftp)://[^\s<>\"']+[^\s<>\"'.,;:!?)\]])")


def linkify(text: str | Text) -> Text:
    """Make any URLs in already-filtered text clickable.

    Takes a `Text` as well as a `str` so it can be layered over the styled
    result of `ansi.to_text` without flattening the colours -- the link style
    is applied as a span over the existing ones rather than rebuilt from
    scratch. The link target is the matched substring of `Text.plain` itself,
    so the visible text and the destination are the same string by
    construction: a remote station cannot display one address and open
    another.
    """
    result = text if isinstance(text, Text) else Text(text)
    for match in _URL_RE.finditer(result.plain):
        url = match.group(1)
        result.stylize(f"underline link {url}", match.start(), match.end())
    return result


class TerminalPane(Container):
    """Read-only session log, plus the send line that is the only transmit path."""

    #: Whether a remote station's allowlisted SGR colour reaches the widget.
    #: Set from `Config.remote_color` by the app; the default stands on its
    #: own so a pane mounted in a test needs no config object.
    remote_color: bool = True

    def compose(self) -> ComposeResult:
        # A RichLog is not editable, so the transcript cannot be typed into by
        # accident. Textual's selection support keeps it copyable anyway.
        yield RichLog(
            id="session-log",
            wrap=True,
            markup=False,
            highlight=False,
            max_lines=5000,
            auto_scroll=True,
        )
        with Horizontal(id="session-send-row"):
            yield Input(
                placeholder="not connected -- Ctrl+N to connect",
                id="session-input",
            )
            yield Button("Send", id="session-send", variant="primary")

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    def log(self, text: str) -> None:
        """Write locally-generated text: status notes, echoes of what we sent.

        Deliberately separate from `write_incoming`. Text kissterm produced is
        already trusted, and putting it through `sanitize` would strip
        formatting chosen on purpose.
        """
        self.query_one("#session-log", RichLog).write(text)

    def write_incoming(self, data: bytes) -> None:
        """Write bytes received from the far end. Filtered, then linkified.

        `remote_color` picks which filter, and both are safe -- see the module
        docstring. It does not gate whether filtering happens.
        """
        text = to_text(data) if self.remote_color else Text(sanitize(data))
        self.query_one("#session-log", RichLog).write(linkify(text), expand=True)

    def clear(self) -> None:
        self.query_one("#session-log", RichLog).clear()

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def set_placeholder(self, text: str) -> None:
        self.query_one("#session-input", Input).placeholder = text

    def focus_input(self) -> None:
        self.query_one("#session-input", Input).focus()

    def suggest(self, text: str) -> None:
        """Put a suggested command in the input WITHOUT sending it.

        The autocomplete path calls this. It fills the field and leaves the
        cursor at the end; the operator still commits deliberately. Nothing in
        this method can transmit, and it must stay that way.
        """
        field = self.query_one("#session-input", Input)
        field.value = text
        field.action_end()
        field.focus()

    @on(Input.Submitted, "#session-input")
    async def _submitted(self, event: Input.Submitted) -> None:
        await self.send_line(event.value)

    @on(Button.Pressed, "#session-send")
    async def _send_pressed(self) -> None:
        await self.send_line(self.query_one("#session-input", Input).value)

    async def send_line(self, text: str) -> None:
        """The one and only path from this pane to the air.

        Every transmit route -- Enter, the Send button, and anything added
        later -- comes through here, so the answer to "what can key the
        transmitter?" is this method and nothing else.
        """
        field = self.query_one("#session-input", Input)
        link = getattr(self.app, "link", None)
        gate = getattr(self.app, "gate", None)
        if gate is not None and not gate.enabled:
            # Keep what they typed. The transport would drop this silently --
            # clearing the field as well would look exactly like a successful
            # send, which is the worst possible feedback for "nothing went
            # out". The refusal is a courtesy; kissterm/tx.py is the interlock.
            self.app.notify(DISABLED_MESSAGE, severity="warning")
            return
        field.value = ""
        if link is None or not link.connected:
            self.app.notify("Not connected.", severity="warning")
            return
        # latin-1, not UTF-8: packet is byte-oriented, and a character the
        # operator pasted must not fail to encode mid-session. CR, not LF --
        # see the module docstring.
        await link.send(text.encode("latin-1", "replace") + b"\r")
        self.log(text + "\n")
        # The durable half of the same echo. Still one `link.send` in this
        # module: recording what went out is not another way to transmit.
        recorder = getattr(self.app, "log_sent", None)
        if recorder is not None:
            recorder(text)
