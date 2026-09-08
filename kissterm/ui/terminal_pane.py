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

**A paste is filtered before it reaches the send line, not after.** This is
the opposite direction from the filtering above: `ansi.py` protects the local
screen from what a remote station sends, and `_SendInput._on_paste` protects
the channel from what the operator's own clipboard hands to `send_line`.
Textual enables bracketed paste for the whole app, so a paste always arrives
as one `events.Paste` rather than simulated keystrokes -- but `Input`'s own
handler silently keeps only the first line and nothing caps its length or
strips control bytes a binary or multi-line clipboard can carry, and a paclen
of 256 turns one long pasted line into many I frames with no way to take the
Enter back once it is pressed.
"""

from __future__ import annotations

import re

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.timer import Timer
from textual.widgets import Button, Input, RichLog, Static

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


#: A pasted line longer than this is not a command or a chat line, it is a
#: flood: fragmented into I frames at the default 256-byte `paclen`, a paste
#: this size still ties up a slow VHF/HF link for a long time after one Enter
#: press the operator cannot take back. Two default frames' worth is still
#: generous for anything a person actually typed with intent.
_MAX_PASTE_CHARS = 512

#: C0/C1 control bytes, minus nothing -- unlike `_CONTROL_RE` in `ansi.py`
#: this is a single-line send box, so there is no tab/LF/CR to preserve. A
#: byte in this set from a binary clipboard or a copied terminal session
#: would otherwise ride out to the far end looking exactly like something
#: the operator typed, which is the "remote command injection" half of what
#: paste protection guards against.
_PASTE_CONTROL_RE = re.compile("[\x00-\x1f\x7f-\x9f]")


class _SendInput(Input):
    """The outgoing-message box -- Input's own "enter" binding, plus a
    defensive net around it.

    From a real report: typed text sent fine through the Send button, but
    plain Enter did nothing at all -- the text just sat there. Nothing in
    this app intercepts Enter (`grep` confirms no `on_key`/`_on_key`
    anywhere in `kissterm/ui/`), so the keystroke was reaching Textual and
    simply not resolving to the string `"enter"` Input's own binding
    matches. This app's enhanced-keyboard-protocol reliance is not
    hypothetical -- `Ctrl+Shift+B`/`Ctrl+Shift+D` need it and are confirmed
    working over Konsole's CSI-u mode -- and that same class of protocol is
    exactly where a terminal can occasionally attach a modifier to a bare
    Enter that a plain one would never carry, changing the reported key
    name out from under a binding that only listens for "enter". These
    extra bindings catch the variants that would otherwise swallow the
    keystroke silently, all routed to the same `action_submit` a normal
    Enter already runs.
    """

    BINDINGS = [
        Binding("shift+enter", "submit", show=False),
        Binding("ctrl+enter", "submit", show=False),
        Binding("alt+enter", "submit", show=False),
    ]

    def _on_paste(self, event: events.Paste) -> None:
        """Sanitize a paste before `Input`'s own handler ever sees it.

        `Input._on_paste` already keeps only the first line -- but silently,
        which is the wrong kind of silent for a channel that costs airtime:
        an operator who pastes a multi-line block deserves to be told only
        one line is going anywhere, not to discover it after the fact.

        Mutates `event.text` and returns WITHOUT calling `Input`'s own
        `_on_paste` -- Textual's dispatcher (`MessagePump._on_message`)
        walks the whole MRO and calls every class's own handler for a
        message, `Input`'s included, so `super()._on_paste(event)` here
        would run the insert-at-cursor/replace-selection logic a second
        time and double whatever this method left in `event.text`. This
        method only narrows the event; it never puts anything on the air
        itself.
        """
        if not event.text:
            return
        lines = event.text.splitlines()
        first_line = lines[0] if lines else ""
        notices = []
        if len(lines) > 1:
            notices.append("only the first line was kept")
        cleaned = _PASTE_CONTROL_RE.sub("", first_line)
        if cleaned != first_line:
            notices.append("control characters were removed")
        if len(cleaned) > _MAX_PASTE_CHARS:
            cleaned = cleaned[:_MAX_PASTE_CHARS]
            notices.append(f"cut to {_MAX_PASTE_CHARS} characters")
        event.text = cleaned
        if notices:
            self.app.notify(
                "Paste protection: " + "; ".join(notices) + ". Enter still sends it.",
                severity="warning",
            )


class TerminalPane(Container):
    """Read-only session log, plus the send line that is the only transmit path."""

    #: Whether a remote station's allowlisted SGR colour reaches the widget.
    #: Set from `Config.remote_color` by the app; the default stands on its
    #: own so a pane mounted in a test needs no config object.
    remote_color: bool = True

    #: Shift+Enter (previous match) and Escape (close the bar) only need to
    #: fire while focus is somewhere inside this pane -- including
    #: `#find-input` itself, since plain `Input` binds neither key and lets
    #: them bubble up. `_SendInput`'s OWN `shift+enter` binding (submit) is
    #: resolved first whenever `#session-input` is the actually-focused
    #: widget, so the two never collide despite sharing a key.
    BINDINGS = [
        Binding("shift+enter", "previous_match", show=False),
        Binding("escape", "close_find", show=False),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # `None` here, never "" -- an empty needle is a real, typeable state
        # (the operator cleared the box) and must still force a recompute
        # the first time, which comparing against "" would skip.
        self._find_needle: str | None = None
        self._find_matches: list[int] = []
        self._find_pos: int = -1
        # Incoming bytes not yet written to the log -- see `_flush_incoming`
        # for why a chunk boundary must never become a visible line break.
        self._pending_incoming: bytes = b""
        self._flush_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        # A fixed header, not a line in the scrollback -- a session can run
        # for hours, and the one thing worth finding without scrolling back
        # to the top is where its own record is being kept. Empty and
        # hidden until a transcript actually opens; see `set_transcript_note`.
        yield Static("", id="transcript-note")
        # Hidden until Ctrl+F -- see `open_find`/`action_close_find`. Sits
        # above the scrollback, not the send row, so it never shifts where
        # the operator types.
        with Horizontal(id="find-row"):
            yield Input(
                placeholder="find in this session -- Enter: next, Shift+Enter: previous",
                id="find-input",
            )
            yield Static("", id="find-status")
            yield Button("Close", id="find-close")
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
            yield _SendInput(
                placeholder="not connected -- Ctrl+N to connect",
                id="session-input",
            )
            yield Button("Send", id="session-send", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#transcript-note", Static).display = False

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    def log(self, text: str) -> None:
        """Write locally-generated text: status notes, echoes of what we sent.

        Deliberately separate from `write_incoming`. Text kissterm produced is
        already trusted, and putting it through `sanitize` would strip
        formatting chosen on purpose. Flushes any buffered incoming bytes
        first, so a "*** Disconnecting..." note (or any other status line)
        cannot jump ahead of output the far end already sent -- and a link
        that drops mid-word never loses the word.
        """
        self._flush_incoming(final=True)
        self.query_one("#session-log", RichLog).write(text)

    def write_incoming(self, data: bytes) -> None:
        """Write bytes received from the far end. Filtered, then linkified.

        `remote_color` picks which filter, and both are safe -- see the module
        docstring. It does not gate whether filtering happens.

        Buffered rather than written straight through: AX.25 delivers this a
        frame (up to `paclen` bytes) at a time, with no regard for where a
        word ends, and each call to `RichLog.write` renders as its own line
        -- it does not continue the previous one. Writing every chunk as it
        arrives turned an ordinary word straddling a frame boundary into a
        hard line break mid-word ("You have 2 me" / "ssages waiting for
        you."), reported directly from a real session. `_flush_incoming`
        holds back everything after the last newline until either a newline
        completes it or a short idle timer fires, so a chunk boundary is
        invisible unless it happens to land on a real line break.
        """
        self._pending_incoming += data
        self._flush_incoming(final=False)

    def _flush_incoming(self, *, final: bool) -> None:
        """Write complete buffered lines; `final` also flushes a trailing
        partial one (a prompt with no newline, a dying link, Ctrl+L).
        """
        buf = self._pending_incoming
        if not buf:
            return
        if final:
            ready, self._pending_incoming = buf, b""
        else:
            # `\r` counts as a line end too, not just `\n` -- packet nodes
            # are CR-oriented (see the module docstring) and a bare-CR
            # stream would otherwise never find a "\n" to split on and
            # would sit fully at the mercy of the idle timer.
            split = max(buf.rfind(b"\n"), buf.rfind(b"\r"))
            if split == -1:
                # No complete line yet -- wait for the rest of the word
                # instead of rendering the chunk boundary as a wrap point.
                self._schedule_flush()
                return
            ready, self._pending_incoming = buf[: split + 1], buf[split + 1 :]
        if self._flush_timer is not None:
            self._flush_timer.stop()
            self._flush_timer = None
        text = to_text(ready) if self.remote_color else Text(sanitize(ready))
        self.query_one("#session-log", RichLog).write(linkify(text), expand=True)
        if not final and self._pending_incoming:
            self._schedule_flush()

    def _schedule_flush(self) -> None:
        # Only ever one in flight, and it is not rescheduled on every byte --
        # a prompt with no trailing newline still has to appear within a
        # bounded time even if data keeps trickling in, not "eventually".
        if self._flush_timer is None:
            self._flush_timer = self.set_timer(0.2, self._on_flush_timer)

    def _on_flush_timer(self) -> None:
        self._flush_timer = None
        self._flush_incoming(final=True)

    def clear(self) -> None:
        self._pending_incoming = b""
        if self._flush_timer is not None:
            self._flush_timer.stop()
            self._flush_timer = None
        self.query_one("#session-log", RichLog).clear()

    def set_transcript_note(self, text: str) -> None:
        """Show or clear the transcript-path header. Empty hides it."""
        note = self.query_one("#transcript-note", Static)
        note.update(text)
        note.display = bool(text)

    # ------------------------------------------------------------------
    # Find in scrollback
    # ------------------------------------------------------------------
    def open_find(self) -> None:
        """Show the find bar and focus it. `Ctrl+F`'s target in `app.py`."""
        self.query_one("#find-row").display = True
        self.query_one("#find-input", Input).focus()

    def action_close_find(self) -> None:
        """Escape, or the Close button. A no-op if the bar is already
        hidden, so binding it at the pane level (see the class docstring)
        never disturbs a plain Escape typed for some other reason."""
        row = self.query_one("#find-row")
        if not row.display:
            return
        row.display = False
        self._find_needle = None
        self._find_matches = []
        self._find_pos = -1
        self.query_one("#find-status", Static).update("")
        self.focus_input()

    def _recompute_matches(self, needle: str) -> None:
        """Rebuild the match list only when the needle actually changed, so
        repeated Enter/Shift+Enter on an unchanged search just walks
        `_find_pos` instead of re-scanning the whole scrollback every time.
        """
        if needle == self._find_needle:
            return
        self._find_needle = needle
        self._find_pos = -1
        if not needle:
            self._find_matches = []
            return
        # `RichLog.lines` holds every WRAPPED display line currently kept
        # (up to its own `max_lines`), each a `Strip` -- `.text` is its
        # plain content. A match that straddles a wrap point is missed;
        # accepted for a find-as-you-type box over an operator's own
        # session, not a document search tool.
        lowered = needle.lower()
        log = self.query_one("#session-log", RichLog)
        self._find_matches = [
            i for i, strip in enumerate(log.lines) if lowered in strip.text.lower()
        ]

    def _step_match(self, direction: int) -> None:
        status = self.query_one("#find-status", Static)
        if not self._find_matches:
            status.update("No matches" if self._find_needle else "")
            return
        self._find_pos = (self._find_pos + direction) % len(self._find_matches)
        line = self._find_matches[self._find_pos]
        # `immediate=True`: this is a deliberate jump, not a smooth follow --
        # and it makes the new position readable back in a test right after
        # the call, with no animation frame to wait out.
        self.query_one("#session-log", RichLog).scroll_to(y=line, animate=False, immediate=True)
        status.update(f"{self._find_pos + 1}/{len(self._find_matches)}")

    @on(Input.Changed, "#find-input")
    def _find_typed(self, event: Input.Changed) -> None:
        """Count matches as the operator types, without jumping anywhere
        yet -- Enter (see `_find_submitted`) is the deliberate "go" here,
        the same "typing alone never acts" shape `send_line` enforces for
        the send line itself, just for navigation instead of transmission.
        """
        self._recompute_matches(event.value.strip())
        status = self.query_one("#find-status", Static)
        if not self._find_needle:
            status.update("")
        elif self._find_matches:
            n = len(self._find_matches)
            status.update(f"{n} match" if n == 1 else f"{n} matches")
        else:
            status.update("No matches")

    @on(Input.Submitted, "#find-input")
    def _find_submitted(self, event: Input.Submitted) -> None:
        self._recompute_matches(event.value.strip())
        self._step_match(1)

    def action_previous_match(self) -> None:
        self._recompute_matches(self.query_one("#find-input", Input).value.strip())
        self._step_match(-1)

    @on(Button.Pressed, "#find-close")
    def _find_close_pressed(self) -> None:
        self.action_close_find()

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
        # Enter leaves focus on the input by itself, but a mouse click on
        # the Send button moves focus to the BUTTON -- Textual's normal
        # behaviour for anything clicked. Every subsequent line then needs
        # a click back into the field before it can be typed, which is
        # exactly the loop a real report described: type, click Send,
        # click the field, type, click Send... Refocusing here, on every
        # path through this method, means clicking Send once behaves like
        # pressing Enter once: the field is ready for the next line
        # immediately, mouse or keyboard.
        field.focus()
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
