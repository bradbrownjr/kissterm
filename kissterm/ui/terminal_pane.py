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

**The suggestion strip is Tab-to-fill, never Tab-to-send.** As the operator
types, `#suggestion-strip` shows up to `CommandReference.complete`'s limit of
matching commands and their short explanations for the node currently
identified on this session's tab; `_SendInput`'s own `tab` binding calls
`TerminalPane.accept_suggestion`, which routes through `suggest()` like the
Ctrl+R command reference already did -- so Tab is exactly one more way to
reach the one fill path, not a second way to reach the air. Tab with nothing
suggested falls through to `Screen.focus_next()`, reproducing the ordinary
un-overridden behaviour, so an operator who never triggers a suggestion never
notices Tab acts any differently than before this existed.

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

**The Address Book lives here, as a collapsible slide-out, not as its own
tab.** Dialing a station is something an operator does *from* the terminal,
not a separate destination -- and `AddressBookPane` (`addressbook_pane.py`)
is otherwise unchanged: it still reads and writes the one shared
`KissTermApp.addressbook`, and dialing still goes through the full
`action_connect` flow. `Ctrl+G` (`KissTermApp.action_toggle_contacts`,
dispatched here to `toggle_addressbook`) shows or hides
`#terminal-addressbook-column`, focusing its table on open; `Escape` closes
it, the same shape as `action_close_find` below, checked first so the two
never fight over the same key. See `DESIGN.md`'s "slide-out panels" section
for the pattern -- `AprsPane`'s contacts column and, later, Mail's own
contacts panel follow the identical recipe.

**NET/ROM claims are supporting context, not a second directory.** `Ctrl+PageDown`
collapses or restores their lower section without changing the Address Book
slide-out. If the slide-out is closed, it opens it with claims shown, so both
sections remain independently reachable.

**Multiple simultaneous connections get one tab each, on a second strip
inside this pane** -- the same recipe `AprsPane`'s `_ConvoTabs` already
shipped for per-correspondent conversations (see DESIGN.md's "A second tab
strip inside a pane"), reused rather than re-derived: **one shared
`#session-log`, repainted on `Tabs.TabActivated` from a per-session replay
buffer**, not a live widget subtree per connection -- twelve simultaneous
sessions would otherwise mean twelve render states kept alive for nothing.
A session is identified by its peer callsign (`_tab_id`'s digit-leading-
callsign guard is the same trick APRS's `_tab_id` uses, and for the same
reason -- `2E0ABC` is a real UK callsign and an unprefixed widget id raises
`BadIdentifier`).

**Session identity is the empty string until something is connected.**
`""` is a real, permanent key in every per-session dict here (never a real
tab, never counted against `MAX_TERMINAL_TABS`) -- it is the pre-connection
view every fresh launch starts on, so `log`/`write_incoming`/`clear` never
need a "no session yet" special case: they always have *some* buffer to
write into. `KissTermApp` mirrors this with its own permanent `""` entry in
`self._sessions`, which is what lets `app.link`/`app.reference`/
`app.transcript` keep meaning exactly what they meant before tabs existed
when nothing is connected.

**Tabs open on demand and never steal the view.** An operator-initiated
connect (Ctrl+N, a dial) opens and activates its tab -- that is the thing
they just asked to look at. An incoming call accepted while another session
is already on screen opens a tab and marks it unread, but does not move the
screen out from under whatever the operator was doing -- identical reasoning
to `AprsPane.note_incoming`.

**Closing a session tab is two `Delete`s, not one.** The first disconnects
(dispatched to `KissTermApp.disconnect_or_close_tab`, which sends the DISC);
the second, once the tab reads DISCONNECTED, actually removes it. A single
keystroke that both disconnected and closed would erase the "*** Disconnecting"
note before the operator could read it.
"""

from __future__ import annotations

import asyncio
import logging
import re

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import Button, DataTable, Input, RichLog, Static, Tab, Tabs

from ..ansi import to_text
from ..bbs import complete as complete_bbs
from . import slideouts
from ..monitor import sanitize
from ..tx import DISABLED_MESSAGE
from .addressbook_pane import AddressBookPane
from .wraplog import WrapLog

logger = logging.getLogger(__name__)

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

#: Concurrent session tabs, not counting the pre-connection default view.
#: Kept in lockstep with `AX25Station.max_links` (wired in `__main__.py`) so
#: the two caps never disagree about how many connections are usable at
#: once. Unlike `AprsPane`'s `_MAX_CONVO_TABS`, a session tab is never
#: evicted to make room for a new one -- it holds a LIVE link with real
#: resources (timers, a transcript file), and silently disconnecting one to
#: free a slot would be worse than refusing the new connection.
MAX_TERMINAL_TABS = 8

#: Replay-buffer lines kept per session, matching `WrapLog`'s own
#: `max_lines` -- a session left running in the background for hours must
#: not grow an unbounded buffer nothing ever trims.
_BUFFER_LINES = 5000


def _tab_id(session_key: str) -> str:
    """The `Tabs` id for one session's tab.

    The `sess-` prefix is load-bearing, not decoration: a Textual widget id
    may not begin with a digit, and `2E0ABC` is an ordinary UK callsign --
    unprefixed it raises `BadIdentifier` and takes the pane down on the
    first connection from half of Europe. Mirrors `aprs_pane._tab_id`
    exactly, for the same reason.
    """
    return "sess-" + re.sub(r"[^A-Za-z0-9_-]", "_", session_key.strip().upper())


class _SessionTabs(Tabs):
    """The per-connection strip, with `Delete` to disconnect/close the
    focused tab.

    `show=True`, so the key appears in the Footer while the strip has focus
    -- same reasoning as `aprs_pane._ConvoTabs`, which this mirrors. The
    actual disconnect-vs-close decision needs to know whether the session is
    still connected, which this widget does not track -- that lives in
    `KissTermApp.disconnect_or_close_tab`, this only forwards the key.
    """

    BINDINGS = [Binding("delete", "close_tab", "Close tab")]

    def action_close_tab(self) -> None:
        self.app.query_one(TerminalPane).close_active_tab()


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
        Binding("tab", "accept_suggestion", show=False),
        Binding("up", "previous_suggestion", show=False),
        Binding("down", "next_suggestion", show=False),
    ]

    def action_accept_suggestion(self) -> None:
        """Tab: fill in the top suggestion if the strip is showing one,
        otherwise do exactly what a bare Tab always did.

        `Input` itself binds no `tab` key -- `tab`/`shift+tab` are
        non-priority `Screen` bindings (`focus_next`/`focus_previous`), so
        this widget-level binding is resolved first and must reproduce that
        fallback by hand rather than only handling the acceptance case.
        `App.action_focus_next` is itself nothing but `self.screen.
        focus_next()`, so calling that directly is not a shortcut around
        anything -- it is the same call the default binding would have made.
        """
        pane = self.app.query_one(TerminalPane)
        if not pane.accept_suggestion():
            self.screen.focus_next()

    def action_previous_suggestion(self) -> None:
        """Move the stacked suggestion highlight up, without filling it."""
        self.app.query_one(TerminalPane).move_suggestion(-1)

    def action_next_suggestion(self) -> None:
        """Move the stacked suggestion highlight down, without filling it."""
        self.app.query_one(TerminalPane).move_suggestion(1)

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
        # -- per-session state -------------------------------------------
        # Tab id -> session key, for turning a `TabActivated` back into
        # which session it is -- mirrors `aprs_pane._tab_callsigns`. Real
        # tabs only; `""` (the pre-connection view) never has one.
        self._tab_session_keys: dict[str, str] = {}
        # Session key -> replay buffer of (renderable, expand) pairs, in
        # the order `#session-log` last saw them. `""` is seeded here so
        # every write method always has somewhere to go, connected or not.
        self._buffers: dict[str, list[tuple[object, bool]]] = {"": []}
        self._placeholders: dict[str, str] = {"": "not connected -- Ctrl+N to connect"}
        # Incoming bytes not yet written to a session's log -- see
        # `_flush_incoming` for why a chunk boundary must never become a
        # visible line break. Kept per session so a background connection's
        # partial line is not lost or mis-split while nobody is looking at it.
        self._pending_incoming: dict[str, bytes] = {"": b""}
        self._flush_timers: dict[str, Timer | None] = {"": None}
        self._unread: set[str] = set()
        #: Whose session is currently rendered into `#session-log`. `""`
        #: is the pre-connection view -- see the module docstring.
        self.active_session_key: str = ""
        #: Ordered candidates and the one Tab will choose next. Kept apart
        #: from the input text so successive Tabs can walk a shared prefix.
        self._suggestion_matches: tuple = ()
        self._suggestion_index = 0
        self._cycling_value: str | None = None
        # A slide-out changes the scrollback's usable width after this pane's
        # Resize handler runs.  A generation lets the one post-layout replay
        # for the newest resize win when a window is dragged continuously.
        self._reflow_generation = 0
        self._reflow_width = -1

    def compose(self) -> ComposeResult:
        # The main column holds everything this pane has always shown;
        # the address book is a second column, hidden until Ctrl+G, docked
        # on the right -- see `toggle_addressbook` and the module docstring.
        with Horizontal():
            with Vertical(id="terminal-main-column"):
                # No initial `Tab`, unlike `aprs_pane`'s "All" -- there is no
                # always-there default view to compose in, and an `add_tab`
                # on this EMPTY strip is exactly right the first time
                # (nothing else could be showing to steal the view from).
                # Hidden until a second session exists -- see
                # `_sync_strip_visibility`; a single connection looks
                # exactly like it always has.
                yield _SessionTabs(id="terminal-session-tabs")
                # Hidden until Ctrl+F -- see `open_find`/`action_close_find`.
                # Sits above the scrollback, not the send row, so it never
                # shifts where the operator types.
                with Horizontal(id="find-row"):
                    yield Input(
                        placeholder="find in this session -- Enter: next, Shift+Enter: previous",
                        id="find-input",
                    )
                    yield Static("", id="find-status")
                    yield Button("Close", id="find-close")
                # A RichLog is not editable, so the transcript cannot be typed
                # into by accident. Textual's selection support keeps it
                # copyable anyway.
                # `WrapLog`, not a plain `RichLog`: a plain one renders every
                # line 78 cells wide whatever the column it is in, so on an
                # 80-column terminal -- or any width with the Address Book
                # open beside it -- a node's `?` listing arrived cut off
                # mid-word. See `kissterm/ui/wraplog.py`, which also explains
                # why the obvious `min_width=0` is the wrong fix.
                yield WrapLog(
                    id="session-log",
                    wrap=True,
                    markup=False,
                    highlight=False,
                    max_lines=5000,
                    auto_scroll=True,
                )
                # Hidden whenever there is nothing to suggest -- see
                # `_update_suggestions`. Sits directly above the send row,
                # the same "strip anchored to the thing it annotates"
                # placement `#find-row` uses above the scrollback.
                yield Static("", id="suggestion-strip")
                with Horizontal(id="session-send-row"):
                    yield _SendInput(
                        placeholder="not connected -- Ctrl+N to connect",
                        id="session-input",
                    )
                    yield Button("Send", id="session-send", variant="primary")
            with Vertical(id="terminal-addressbook-column"):
                yield AddressBookPane()

    def on_mount(self) -> None:
        self._tabs().display = False
        self._slideout = slideouts.SlideOut(
            self.query_one("#terminal-addressbook-column"),
            self.query_one("#terminal-main-column"),
        )
        self.query_one("#terminal-addressbook-column").display = False

    def on_resize(self) -> None:
        """Re-decide whether the Address Book column is showing, and how wide.

        On `Resize` rather than in `on_mount` because a pane has no width
        until it has been laid out. `SlideOut` ignores this once the operator
        has used `Ctrl+G`, and an auto-opened column deliberately does NOT
        take focus -- see `AprsPane.on_resize` for the full reasoning; the two
        panes share one rule and one implementation on purpose.
        """
        was_open = self._slideout.open
        self._slideout.resized(
            self.size.width,
            allowed=getattr(self.app.config, "slideouts_auto_open", True),  # type: ignore[attr-defined]
        )
        if self._slideout.open and not was_open:
            self.query_one(AddressBookPane).refresh_from(self.app.addressbook)  # type: ignore[attr-defined]
        self._request_scrollback_reflow()

    def _request_scrollback_reflow(self) -> None:
        """Replay the visible session after layout has chosen its new width.

        `RichLog` wraps only when a line is written; its old display strips do
        not react when Ctrl+G adds or removes the Address Book column.  The
        pane already owns a bounded source buffer for session-tab replay, so
        use that source rather than trying to reverse-engineer wrapped strips.
        Deferring until after refresh is essential: before then the log still
        reports the width it had before the column changed.
        """
        self._reflow_generation += 1
        generation = self._reflow_generation
        self.call_after_refresh(lambda: self._reflow_scrollback(generation))

    def _reflow_scrollback(self, generation: int) -> None:
        if generation != self._reflow_generation:
            return
        log = self._scrollback()
        if log is None:
            return
        width = log.scrollable_content_region.width
        if width <= 0 or width == self._reflow_width:
            return
        self._reflow_width = width
        old_max = log.max_scroll_y
        old_y = log.scroll_y
        at_end = old_y >= old_max - 1
        log.min_width = width
        log.clear()
        for renderable, expand in self._buffers[self.active_session_key]:
            log.write(renderable, expand=expand)
        if not at_end and old_max > 0:
            # Preserve the reader's approximate place through the transcript.
            # Absolute line numbers no longer mean the same thing after a
            # word-wrap width changes, while this relative position does.
            fraction = old_y / old_max
            self.call_after_refresh(
                lambda: log.scroll_to(
                    y=round(log.max_scroll_y * fraction), animate=False, immediate=True
                )
            )
        self._recompute_matches(self.query_one("#find-input", Input).value.strip())

    # ------------------------------------------------------------------
    # Session tabs
    # ------------------------------------------------------------------
    def _tabs(self) -> _SessionTabs:
        return self.query_one("#terminal-session-tabs", _SessionTabs)

    @property
    def session_count(self) -> int:
        """Real, open session tabs -- never counts the `""` default view."""
        return len(self._tab_session_keys)

    def has_room_for(self, session_key: str) -> bool:
        """Whether `session_key` can get a tab -- already having one always
        counts as room, so reconnecting to (or re-activating) an existing
        session is never blocked by the cap that stops a brand new one."""
        return session_key in self._buffers or self.session_count < MAX_TERMINAL_TABS

    def _label(self, session_key: str) -> str:
        """A tab's label: `*` in front while it has something unread.

        An asterisk rather than colour alone -- see `aprs_pane._label`,
        which this mirrors exactly, including the reasoning.
        """
        return f"*{session_key}" if session_key in self._unread else session_key

    def _relabel(self, session_key: str) -> None:
        tab = self._tabs().get_tab(_tab_id(session_key))
        if tab is not None:
            tab.label = self._label(session_key)
            tab.set_class(session_key in self._unread, "-unread")

    def mark_unread(self, session_key: str) -> None:
        """A session got data (or a call) while some other tab was on
        screen. Marked, not shown -- see the module docstring's "never
        steal the view" rule."""
        if session_key and session_key not in self._unread:
            self._unread.add(session_key)
            self._relabel(session_key)

    def _sync_strip_visibility(self) -> None:
        # No strip at all below two sessions -- a single connection must
        # look exactly like it always has. See the module docstring.
        self._tabs().display = self.session_count > 1

    def open_tab(self, session_key: str, *, activate: bool) -> bool:
        """Make sure `session_key` has a tab. Returns False only when it
        does not exist yet AND `MAX_TERMINAL_TABS` is already full --
        callers that are about to spend real work on this session (a SABM,
        accepting a call) must check this BEFORE doing that, not after.
        """
        if session_key not in self._buffers:
            if not self.has_room_for(session_key):
                return False
            self._buffers[session_key] = []
            self._placeholders[session_key] = f"connected to {session_key}"
            self._pending_incoming[session_key] = b""
            self._flush_timers[session_key] = None
            tabs = self._tabs()
            tab_id = _tab_id(session_key)
            tabs.add_tab(Tab(self._label(session_key), id=tab_id))
            self._tab_session_keys[tab_id] = session_key
            self._sync_strip_visibility()
        if activate:
            self.activate_tab(session_key)
        return True

    def close_tab(self, session_key: str) -> None:
        """Remove a session's tab and forget its buffered state entirely.

        Never called for a still-CONNECTED session -- `close_active_tab`
        below routes that to a disconnect instead. If the closed tab was
        the one on screen, whatever the strip activates next repaints
        through the normal `TabActivated` handler; if nothing is left,
        falls back to the pre-connection `""` view by hand, since an empty
        strip posts no activation event to fall back through.
        """
        if session_key not in self._buffers or not session_key:
            return
        timer = self._flush_timers.pop(session_key, None)
        if timer is not None:
            timer.stop()
        self._buffers.pop(session_key, None)
        self._placeholders.pop(session_key, None)
        self._pending_incoming.pop(session_key, None)
        self._unread.discard(session_key)
        tab_id = _tab_id(session_key)
        self._tab_session_keys.pop(tab_id, None)
        was_active = self.active_session_key == session_key
        self._tabs().remove_tab(tab_id)
        self._sync_strip_visibility()
        if was_active and self.active_session_key == session_key:
            self.activate_tab("")

    def close_active_tab(self) -> None:
        """`Delete` on the focused strip. Dispatched to the app, which
        decides disconnect-vs-close -- see the module docstring."""
        key = self.active_session_key
        if not key:
            return
        handler = getattr(self.app, "disconnect_or_close_tab", None)
        if handler is not None:
            handler(key)

    def activate_tab(self, session_key: str) -> None:
        """Put `session_key`'s session on screen: repaint the shared log
        from its replay buffer, restore its placeholder, and clear its unread
        mark. The one place `#session-log`'s
        content actually changes for a tab switch."""
        if session_key not in self._buffers:
            session_key = ""
        self.active_session_key = session_key
        if session_key in self._unread:
            self._unread.discard(session_key)
            self._relabel(session_key)
        tabs = self._tabs()
        tab_id = _tab_id(session_key) if session_key else ""
        if tabs.active != tab_id and tab_id in self._tab_session_keys:
            tabs.active = tab_id  # posts TabActivated; harmless if it also repaints
        log = self.query_one("#session-log", RichLog)
        log.clear()
        for renderable, expand in self._buffers[session_key]:
            log.write(renderable, expand=expand)
        self.set_placeholder(session_key, self._placeholders.get(session_key, ""))
        refresh_status = getattr(self.app, "_refresh_status", None)
        if refresh_status is not None:
            refresh_status()
        # The reference this strip suggests from is session-scoped
        # (`self.app.reference`); recompute it for whatever is still typed
        # into the (shared) send line, or it would keep offering commands
        # for the tab just left.
        self._update_suggestions(self.query_one("#session-input", Input).value)

    @on(Tabs.TabActivated, "#terminal-session-tabs")
    def _session_tab_activated(self, event: Tabs.TabActivated) -> None:
        event.stop()
        key = self._tab_session_keys.get(event.tab.id or "")
        if key is not None and key != self.active_session_key:
            self.activate_tab(key)

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    def _scrollback(self) -> RichLog | None:
        """The scrollback widget, or None once this pane is being torn down.

        `KissTermApp._to_terminal` already documents why a link outlives the
        UI and guards against the *pane* being gone -- but that guard is one
        level too shallow. On shutdown there is a window where the pane is
        still in the widget tree and its children have already been removed,
        and a link callback landing in it made `query_one("#session-log")`
        raise `NoMatches` out of a worker with nowhere for the exception to
        go. That surfaced as an intermittent failure in an unrelated pilot
        test (`test_transmit_gate.py`), which is the worst way to find it:
        a flake makes "the suite is green" stop meaning anything.

        Only callers reachable from a background link callback need this.
        """
        for widget in self.query("#session-log").results(RichLog):
            return widget
        return None

    def _append(self, session_key: str, renderable, *, expand: bool) -> None:
        """Add one already-filtered renderable to `session_key`'s replay
        buffer, trimmed the same way `WrapLog`'s own `max_lines` caps the
        live widget. Writes straight through to the visible log if this is
        the active session; otherwise marks the tab unread instead."""
        buf = self._buffers.get(session_key)
        if buf is None:
            # The tab was closed out from under a still-arriving callback
            # (a link outliving the UI) -- nothing left to append to.
            return
        buf.append((renderable, expand))
        if len(buf) > _BUFFER_LINES:
            del buf[: len(buf) - _BUFFER_LINES]
        if session_key == self.active_session_key:
            log = self._scrollback()
            if log is not None:
                # RichLog's own auto-scroll asks for the bottom before the
                # new virtual height is incorporated by a refresh. A packet
                # node's final prompt often has no newline and no following
                # output, so it can remain exactly one row below the view.
                # Refresh first, then choose the end from the settled height.
                log.write(renderable, expand=expand, scroll_end=False)
                # RichLog sets ``virtual_size`` directly; a layout refresh is
                # what makes ScrollView recompute ``max_scroll_y`` from it.
                log.refresh(layout=True)
                log.call_after_refresh(
                    lambda: log.scroll_end(
                        animate=False, immediate=True, x_axis=False
                    )
                )
        else:
            self.mark_unread(session_key)

    def log(self, session_key: str, text: str) -> None:
        """Write locally-generated text: status notes, echoes of what we sent.

        Deliberately separate from `write_incoming`. Text kissterm produced is
        already trusted, and putting it through `sanitize` would strip
        formatting chosen on purpose. Flushes any buffered incoming bytes
        first, so a "*** Disconnecting..." note (or any other status line)
        cannot jump ahead of output the far end already sent -- and a link
        that drops mid-word never loses the word.
        """
        self._flush_incoming(session_key, final=True)
        self._append(session_key, text, expand=False)

    def write_incoming(self, session_key: str, data: bytes) -> None:
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
        if session_key not in self._pending_incoming:
            return
        self._pending_incoming[session_key] += data
        self._flush_incoming(session_key, final=False)

    def _flush_incoming(self, session_key: str, *, final: bool) -> None:
        """Write complete buffered lines for `session_key`; `final` also
        flushes a trailing partial one (a prompt with no newline, a dying
        link, Ctrl+L)."""
        buf = self._pending_incoming.get(session_key, b"")
        if not buf:
            return
        if final:
            ready, self._pending_incoming[session_key] = buf, b""
        else:
            # `\r` counts as a line end too, not just `\n` -- packet nodes
            # are CR-oriented. But a trailing CR is deliberately held until
            # the next frame (or the idle timer): it may be the first half
            # of CRLF. Flushing it now and the LF later renders a spurious
            # blank line, which a live BPQ BBS mail listing exposed. A CR
            # followed by any byte is unambiguously a complete bare-CR line;
            # a CR followed by LF is one CRLF terminator.
            end = 0
            index = 0
            while index < len(buf):
                byte = buf[index]
                if byte == 0x0A:  # LF
                    end = index + 1
                elif byte == 0x0D:  # CR
                    if index + 1 >= len(buf):
                        break  # could become CRLF in the next AX.25 frame
                    if buf[index + 1] == 0x0A:
                        index += 1
                    end = index + 1
                index += 1
            if end == 0:
                # No complete line yet -- wait for the rest of the word
                # instead of rendering the chunk boundary as a wrap point.
                self._schedule_flush(session_key)
                return
            ready, self._pending_incoming[session_key] = buf[:end], buf[end:]
        timer = self._flush_timers.get(session_key)
        if timer is not None:
            timer.stop()
            self._flush_timers[session_key] = None
        text = to_text(ready) if self.remote_color else Text(sanitize(ready))
        # RichLog puts a line break after every record. Passing it a Text that
        # still contains wire terminators therefore adds a second, empty row
        # after each BBS line. Write physical lines separately, discarding
        # exactly the final separator. `allow_blank` keeps genuine blank BBS
        # lines: "one\n\ntwo\n" stays one, blank, two.
        lines = list(text.split("\n", allow_blank=True))
        if text.plain.endswith("\n") and lines:
            lines.pop()
        for line in lines:
            self._append(session_key, linkify(line), expand=True)
        if not final and self._pending_incoming.get(session_key):
            self._schedule_flush(session_key)

    def _schedule_flush(self, session_key: str) -> None:
        # Only ever one in flight per session, and it is not rescheduled on
        # every byte -- a prompt with no trailing newline still has to
        # appear within a bounded time even if data keeps trickling in, not
        # "eventually".
        if self._flush_timers.get(session_key) is None:
            self._flush_timers[session_key] = self.set_timer(
                0.2, lambda: self._on_flush_timer(session_key)
            )
            logger.debug(
                "flush: scheduled Textual timer for %r, %d byte(s) pending",
                session_key,
                len(self._pending_incoming.get(session_key, b"")),
            )
            self._watch_flush(session_key)

    def _watch_flush(self, session_key: str) -> None:
        """DIAGNOSTIC ONLY -- observes, never flushes. Remove with the fix.

        `set_timer` wraps its callback in `call_next`, so the held-back tail
        of a line is only ever released if the PANE'S OWN message queue is
        being drained. `write_incoming` reaches this widget by a plain method
        call from the link callback instead, which is why a real session
        (2026-09-22, CCEMA) rendered every line whose continuation arrived in
        a later frame -- "Emergency Communications Team" came out whole
        across a 58 second gap that a 0.2s timer should have split -- while
        the one tail with no next frame, the node's prompt, was never written
        at all. Both facts fit a Textual timer whose callback never runs, and
        nothing reproduces it under `run_test`, where the pilot drains those
        queues itself.

        So this schedules the same delay directly on the event loop, which is
        demonstrably alive in that session (frames arrived and RRs went out
        on time throughout), and logs what it finds. If the loop callback
        logs and the timer callback does not, the message queue is the fault
        and the flush must not depend on it.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # no loop (a unit test constructing the pane)
            return
        loop.call_later(0.45, lambda: self._flush_watchdog_fired(session_key))

    def _flush_watchdog_fired(self, session_key: str) -> None:
        pending = self._pending_incoming.get(session_key, b"")
        logger.debug(
            "flush: loop watchdog for %r -- %d byte(s) still pending, "
            "Textual timer %s",
            session_key,
            len(pending),
            "still armed (its callback never ran)"
            if self._flush_timers.get(session_key) is not None
            else "already fired or was cleared",
        )
        if pending:
            logger.debug("flush: unflushed tail is %r", pending[:120])

    def _on_flush_timer(self, session_key: str) -> None:
        logger.debug("flush: Textual timer callback ran for %r", session_key)
        self._flush_timers[session_key] = None
        self._flush_incoming(session_key, final=True)

    def clear(self, session_key: str) -> None:
        if session_key not in self._buffers:
            return
        self._pending_incoming[session_key] = b""
        timer = self._flush_timers.get(session_key)
        if timer is not None:
            timer.stop()
            self._flush_timers[session_key] = None
        self._buffers[session_key] = []
        if session_key == self.active_session_key:
            self.query_one("#session-log", RichLog).clear()

    def clear_active(self) -> None:
        """`Ctrl+L` -- clear whichever session (or the pre-connection view)
        is on screen right now."""
        self.clear(self.active_session_key)

    def set_placeholder(self, session_key: str, text: str) -> None:
        if session_key not in self._placeholders:
            return
        self._placeholders[session_key] = text
        if session_key == self.active_session_key:
            self.query_one("#session-input", Input).placeholder = text

    # ------------------------------------------------------------------
    # Find in scrollback
    # ------------------------------------------------------------------
    def open_find(self) -> None:
        """Show the find bar and focus it. `Ctrl+F`'s target in `app.py`."""
        self.query_one("#find-row").display = True
        self.query_one("#find-input", Input).focus()

    def action_close_find(self) -> None:
        """Escape, or the Close button.

        Also the pane's one Escape handler for the address book slide-out
        (see `toggle_addressbook`) -- find is checked first, so if both were
        ever open at once Escape closes find before the slide-out, and a
        second Escape closes the slide-out. A no-op if neither is open, so
        binding it at the pane level (see the class docstring) never
        disturbs a plain Escape typed for some other reason.
        """
        row = self.query_one("#find-row")
        if row.display:
            row.display = False
            self._find_needle = None
            self._find_matches = []
            self._find_pos = -1
            self.query_one("#find-status", Static).update("")
            self.focus_input()
            return
        if self._slideout.close_by_hand():
            self.focus_input()

    # ------------------------------------------------------------------
    # Address book slide-out
    # ------------------------------------------------------------------
    def toggle_addressbook(self) -> None:
        """Show or hide the Address Book column. `Ctrl+G`'s target on this
        pane, dispatched from `KissTermApp.action_toggle_contacts`.

        Opening repaints from `KissTermApp.addressbook` -- same rule as the
        heard table and every other periodically-or-elsewhere-updated pane:
        correct the instant it becomes visible, not stale until the next
        unrelated event. (`AddressBookPane.on_mount` only ever runs once, at
        app mount, so an attempt recorded from Ctrl+N since then would
        otherwise never reach a slide-out that stays composed-but-hidden
        rather than being torn down and rebuilt like a `TabPane` was.) Also
        focuses the table so it is immediately keyboard-navigable, matching
        `open_find` above. Closing is handled by `action_close_find`
        (Escape), which checks find first -- see that method's docstring.
        """
        if self._slideout.toggle():
            self.query_one(AddressBookPane).refresh_from(self.app.addressbook)  # type: ignore[attr-defined]
            self.query_one(AddressBookPane).refresh_known_nodes(self.app.known_nodes)  # type: ignore[attr-defined]
            self.query_one("#addressbook-table", DataTable).focus()
        else:
            self.focus_input()
        self._request_scrollback_reflow()

    def close_addressbook_for_connection(self) -> None:
        """Clear the shared Address Book / NET/ROM column for a dial.

        A connection attempt has its own live status and terminal tab to
        watch. Leaving either side of this shared column open makes that the
        narrow, secondary view at the moment the operator needs the session
        output most. This is intentionally an explicit close rather than a
        toggle: a connection must never open a panel that was already hidden.
        """
        if self._slideout.close_by_hand():
            self._request_scrollback_reflow()

    def refresh_known_nodes(self) -> None:
        """Refresh passive NET/ROM claims when the slide-out is visible."""
        if self.query_one("#terminal-addressbook-column").display:
            self.query_one(AddressBookPane).refresh_known_nodes(self.app.known_nodes)  # type: ignore[attr-defined]

    def toggle_known_nodes(self) -> None:
        """Ctrl+PageDown: independently show or hide NET/ROM claims."""
        column = self.query_one("#terminal-addressbook-column")
        if not column.display:
            # The shortcut names the NET/ROM list, so it must be able to
            # summon the shared column by itself. It is a show operation in
            # this state, rather than an invisible state flip behind a closed
            # panel.
            self.toggle_addressbook()
            self.query_one(AddressBookPane).set_known_nodes_visible(True)
            return
        self.query_one(AddressBookPane).toggle_known_nodes()

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
    def focus_input(self) -> None:
        self.query_one("#session-input", Input).focus()

    def suggest(self, text: str) -> None:
        """Put a suggested command in the input WITHOUT sending it.

        The autocomplete path calls this. It fills the field and leaves the
        cursor at the end; the operator still has to commit deliberately.
        Nothing in this method can transmit, and it must stay that way. Not
        session-scoped -- it only ever fills whichever input is showing.

        Assigning `.value` is itself what recomputes the suggestion strip:
        `Input.value` is a reactive whose `_watch_value` posts `Changed`
        even for a programmatic assignment, and `_session_input_changed`
        below is what actually calls `_update_suggestions`.
        """
        field = self.query_one("#session-input", Input)
        field.value = text
        field.action_end()
        field.focus()

    def accept_suggestion(self) -> bool:
        """`_SendInput`'s Tab target: fill the next matching command.

        Returns whether there was one to accept, so Tab can fall back to
        ordinary focus-cycling instead of doing nothing when the strip is
        empty -- see `_SendInput.action_accept_suggestion`.
        """
        if not self._suggestion_matches:
            return False
        command = self._suggestion_matches[self._suggestion_index]
        # Retain the original candidate list after this programmatic fill,
        # then visibly mark what the next Tab will choose.
        self._cycling_value = command.name
        self._suggestion_index = (self._suggestion_index + 1) % len(self._suggestion_matches)
        self.suggest(command.name)
        return True

    def move_suggestion(self, direction: int) -> bool:
        """Move the selection in the visible suggestion list.

        Up/Down only choose which candidate Tab will fill; they never alter
        the input or send a command. With no candidates they deliberately do
        nothing, preserving ordinary single-line input behaviour rather than
        making an arrow key unexpectedly move focus elsewhere.
        """
        if not self._suggestion_matches:
            return False
        self._suggestion_index = (self._suggestion_index + direction) % len(
            self._suggestion_matches
        )
        # `_update_suggestions` owns the strip rendering. Keeping this input
        # as the cycling value tells it to retain the candidate tuple and our
        # newly chosen index instead of recomputing/resetting them.
        self._cycling_value = self.query_one("#session-input", Input).value
        self._update_suggestions(self._cycling_value)
        return True

    def _update_suggestions(self, prefix: str) -> None:
        """Recompute `#suggestion-strip` for `prefix` against the active
        session's command reference.

        Called on every keystroke in the send line (`_session_input_changed`)
        and again whenever the operator switches session tabs
        (`activate_tab`) -- `self.app.reference` is session-scoped, so a
        strip left over from a different tab's node would offer commands
        for the wrong station. An empty or no-match prefix hides it rather
        than leaving stale candidates on screen; `CommandReference.complete`
        already returns nothing for an empty prefix on its own.
        """
        reference = getattr(self.app, "reference", None)
        if prefix == self._cycling_value and self._suggestion_matches:
            matches = self._suggestion_matches
        else:
            command_matches = reference.complete(prefix) if reference is not None else ()
            # The shipped BPQMail reference is a baseline, not a guess made
            # from whatever a particular node happened to reveal. Offer its
            # complete documented command set beside the session reference,
            # so typing "L" can explain LM/LB/LL before the operator spends
            # any channel time. A BBS command that happens to share a name
            # with a node command appears once, with the node reference's
            # richer per-session provenance taking precedence.
            bbs_matches = complete_bbs(prefix)
            bbs_by_name = {macro.name.upper(): macro for macro in bbs_matches}
            # A learned BBS command proves the name is present on THIS
            # station, but harvesting knows only names, not meanings. Keep
            # that local command when it already has a description; otherwise
            # replace its display entry with the shipped helper's explained
            # one. The command text is identical, and this avoids the
            # unhelpful duplicate `LM` rows a simple append would create.
            matches = tuple(
                bbs_by_name.get(command.name.upper(), command)
                if not command.summary
                else command
                for command in command_matches
            )
            seen = {command.name.upper() for command in matches}
            matches += tuple(
                macro
                for macro in bbs_matches
                if macro.name.upper() not in seen
            )
            self._suggestion_matches = matches
            self._suggestion_index = 0
            self._cycling_value = None
        strip = self.query_one("#suggestion-strip", Static)
        if not matches:
            self._suggestion_matches = ()
            self._suggestion_index = 0
            self._cycling_value = None
            strip.display = False
            strip.update("")
            return
        # Command names alone make a new operator guess at exactly the point
        # they are looking for help. The shipped reference already carries a
        # concise summary for each one, so surface it here instead of asking
        # the node (which would cost airtime). One candidate per line keeps
        # the command and its meaning together on narrow terminals; a wide
        # horizontal row would put exactly that explanation off-screen.
        text = Text(overflow="fold")
        for index, command in enumerate(matches):
            if index:
                text.append("\n")
            text.append(command.name, style="bold" if index == self._suggestion_index else "dim")
            if command.summary:
                text.append(f" - {command.summary}", style="dim")
        text.append("\nUp/Down: choose  Tab: fill", style="dim italic")
        strip.update(text)
        strip.display = True

    @on(Input.Changed, "#session-input")
    def _session_input_changed(self, event: Input.Changed) -> None:
        self._update_suggestions(event.value)

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
        transmitter?" is this method and nothing else. Always targets
        `active_session_key`: whichever tab is on screen is the one the
        operator is typing to.
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
        if link is None or not link.connected:
            self.app.notify("Not connected.", severity="warning")
            return
        gate = getattr(self.app, "gate", None)
        if gate is not None and not gate.enabled:
            # A line the operator just typed and committed with Enter or
            # Send, to a station they are already connected to, is exactly
            # the "confirmed, targeted" shape `KissTermApp._arm_for` exists
            # for -- refusing it with DISABLED_MESSAGE would be the same
            # dead end AGENTS.md calls out for Connect: the one thing the
            # operator asked for is the one thing the refusal would not do.
            # Checked only after `link.connected` above, so a closed gate on
            # a session with nothing to send to never arms anything.
            arm_for = getattr(self.app, "_arm_for", None)
            if arm_for is not None:
                arm_for(f"sending to {self.active_session_key}")
            else:
                self.app.notify(DISABLED_MESSAGE, severity="warning")
                return
        field.value = ""
        # latin-1, not UTF-8: packet is byte-oriented, and a character the
        # operator pasted must not fail to encode mid-session. CR, not LF --
        # see the module docstring.
        await link.send(text.encode("latin-1", "replace") + b"\r")
        self.log(self.active_session_key, text + "\n")
        # The durable half of the same echo. Still one `link.send` in this
        # module: recording what went out is not another way to transmit.
        recorder = getattr(self.app, "log_sent", None)
        if recorder is not None:
            recorder(self.active_session_key, text)
