"""The `KissTermApp` class: bindings, pane assembly, and the frame fan-out.

Layout follows the shape a packet operator already has in their head from
BPQTerminal and EasyTerm, because the goal is a familiar tool that happens to
be modern, not a novel one they have to relearn:

    F1 Terminal  F2 APRS  F3 Heard  F4 Monitor  F5 Settings
    +--------------------------------------------+---------+
    | session output (scrollback, selectable)     | Address |
    +--------------------------------------------+ Book,   |
    | > type here                          [Send] | Ctrl+G  |
    +--------------------------------------------+---------+
      ^r Commands  ^n Connect  ^d Disconnect  ^G Contacts ...  <- shortcut keys
      kissterm 0.1 | transport | callsign | heard N          <- status, BELOW them

The F-key for each tab is printed IN THE TAB LABEL (`F1 Terminal`, keyboard-
shortcut-first, matching how a menu shows an accelerator), not in the footer.
Textual's `Footer` widget would otherwise show `f1 Terminal  f2 APRS  f3
Heard  f4 Monitor  f5 Settings` right below a tab bar already showing those
same five names -- the same words twice, in two different corners of the screen.
All five `Binding`s stay registered (`show=False`) so the keys still work;
only the redundant on-screen label moves. `Ctrl+1..5` remain as unlabelled
fallback aliases for terminals that intercept function keys.

**Function keys are tabs. Ctrl sequences are actions and modals.** That is
the whole rule, and it is why the command reference -- a modal opened over
whatever tab is active -- is `Ctrl+R`, not a function key. A non-tab action
squatting on the next free F-number breaks the "F<n> is the n-th tab" pattern
the moment an n-th tab exists to expect it, which already happened once here
(Address Book briefly had its own F-key before this). Address Book is now a
collapsible slide-out on the Terminal pane instead of a tab -- `Ctrl+G`
(`action_toggle_contacts`, dispatched by whichever tab is active) opens or
closes it, focusing its table on open; Escape closes it, same as the find
bar. `AprsPane`'s contacts list is the same pattern, on the APRS tab, added
right after this in the same feature; Mail's own contacts panel is expected
to follow the identical recipe once that tab exists. See `DESIGN.md`'s
"slide-out panels" section for the pattern written down once, in one place,
rather than re-derived per pane. Dialing a station is something an operator
does *from* the terminal, not a separate destination, which is also why this
folded into Terminal rather than staying its own tab: it turned out to be
used far more often than a one-time setup screen, closer to Terminal/Monitor
in how often an operator reaches for it than to Settings -- but *reaching*
for it is now a keystroke inside the pane it dials from, not a tab switch
away from it.

This also reserves the F-row for the tabs still to come (Mail, Bulletins,
Files -- see docs/ROADMAP.md). The ceiling was originally set at F8 (some
terminals are unreliable past it), but KC1JMH reports F9/F10 work fine in
practice on the terminals actually in use here, and Midnight Commander --
about as widely deployed a terminal-UI precedent as exists -- has used
F1-F10 for its whole menu row for decades without it being a practical
problem. **F1..F10 is the working ceiling now, ten tabs the practical
maximum.** F11 is out regardless: it is "toggle fullscreen" in enough
terminal emulators and window managers that it rarely reaches the
application at all. Five tabs exist and three more are planned, landing at
F6-F8 with F9/F10 spare -- see docs/ROADMAP.md's P10 section for the
assignment.

The status bar sits BELOW the Footer's shortcut-key row, not above it -- the
keys you might press come first, reading top to bottom, and the passive status
readout comes last. See `#bottom-bar` in `styles.py` for the container that
makes this ordering deliberate rather than incidental.

Each pane's `compose()` fragment and widget handlers used to live inline in
this file. They now live one module per pane (`terminal_pane.py`,
`monitor_pane.py`, `heard_pane.py`, `aprs_pane.py`, `settings_pane.py`,
plus `dialogs.py` for modals and `styles.py` for the CSS), so that adding or
editing one pane means opening one file -- see `kissterm/ui/AGENTS.md`. What
stays here is only what genuinely has to be singular:

**One shared frame fan-out.** The monitor pane and the heard table are fed
from three subscriptions -- `transport.subscribe` (every frame received),
`transport.on_sent` (every frame transmitted), and `station.on_incoming` --
registered exactly once, in this class's `on_mount`. A frame is decoded once.
Adding a second decode path for a new pane, anywhere, is the wrong instinct --
add a subscriber to the existing fan-out instead. `KissTermApp` is
deliberately the *only* place that touches `self.station` for this reason: a
pane that subscribed to the station on its own would be a second fan-out.

The receive side hangs off the *transport*, not off `station.on_unhandled`:
the station routes a frame belonging to an open link straight to that link, so
`on_unhandled` never sees the UA that answers our SABM, nor any of the traffic
of a live conversation. A monitor fed from there goes quiet during the one
event an operator most wants to watch.

**Nothing in the UI knows which transport tier it is on.** Panes talk to
`Session`/link objects handed to them via `self.link`, a documented attribute
of this class. That is what lets a VARA link and a KISS link render
identically, and it is why `AX25Station.session_for` exists.

**`self.link`/`self.reference`/`self.transcript` mean "whichever session is
on screen right now", not "the only session".** The Terminal pane can hold
several simultaneous frame-tier connections at once, one per tab (see
`terminal_pane.py`'s module docstring for the tab strip itself); these three
are read-only properties backed by `self._sessions`, a dict keyed by session
identity (`_session_key`) with a permanent `""` entry for the pre-connection
view. Code reacting to a SPECIFIC link's own callback (`_on_link_data`,
`_on_link_state`, the reply-watch timer, `_sniff_node`) must never read
these properties -- the callback is bound to one session, not to whichever
one happens to be active when it fires, so it threads that session's key
through explicitly instead. Session-tier transports (Telnet, SSH, VARA,
Mercury, kernel AX.25) never have more than one session -- see
`terminal_pane.py` and the approved scope of this feature -- so for them
"the active session" and "the only session" are simply the same thing.

Keys deliberately avoid `Ctrl+C` for anything but quit, and avoid single-letter
bindings while the input line has focus: this is a *terminal*, and a key that
does something other than type a character into a live BBS session is a bug the
operator will hit at the worst moment.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from rich.table import Table
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.timer import Timer
from textual.widgets import Footer, Static, TabbedContent, TabPane
from textual.widgets._footer import FooterKey

from .. import __version__
from ..addressbook import AddressBook
from ..netrom import KnownNodes
from .. import aprs
from ..aprs_conversations import ConversationStore, MessageDeduplicator
from ..aprs_notify import Cooldown, evaluate_packet
from ..ax25 import AX25Station, parse_path
from ..ax25.address import AX25Address, AX25AddressError
from ..aprs_beacon import AprsBeaconer
from ..beacon import Beaconer
from ..config import AprsConfig, BeaconConfig, find_credential, find_script, state_path
from .. import desktop_notify
from ..ax25.frame import PID_NO_LAYER3, AX25Frame, UType
from ..heard import HeardTable
from ..hotplug import PortEvent, SerialPortWatcher
from ..locator import find_grid_in_text
from ..monitor import MonitorFilter, aprs_message_matches, format_frame, mail_waiting_for, sanitize
from ..session_log import SessionLog
from ..transport.base import SessionState, TransportError, TransportState
from ..tx import DISABLED_MESSAGE, TransmitGate
from ..watched_notify import WatchNotifier, claimed_callsigns, normalize_callsigns
from ..autobin import AutoBinError, receive_file as receive_autobin, send_file as send_autobin
from ..yapp import YappError, receive_file, send_file
from .aprs_pane import AprsPane
from . import themes
from .clock import KissTermHeader
from .commands import KeyBindingsProvider, fit_footer_bindings
from ..harvested import HarvestedCommands
from ..nodes import Command, CommandReference
from ..nodes.reference import identify_family, parse_harvested
from .dialogs import (
    CallsignScreen,
    CommandReferenceScreen,
    ConnectRequest,
    ConnectScreen,
    AprsObjectScreen,
    AprsObjectRequest,
    RadioReminderScreen,
    TranscriptsScreen,
    FileTransferScreen,
)
from .heard_pane import HeardPane
from .monitor_pane import MonitorPane
from .settings_pane import SettingsPane
from .styles import APP_CSS
from .terminal_pane import MAX_TERMINAL_TABS, TerminalPane

log = logging.getLogger(__name__)


@dataclass
class _TerminalSession:
    """Everything `KissTermApp` tracks for one Terminal-pane tab.

    Keyed in `KissTermApp._sessions` by `_session_key` (a peer's callsign,
    plus port if not 0). `link` is `None` only for the permanent `""` entry
    -- the pre-connection view, which has no link at all. A fresh instance
    IS the reset a reconnect to the same peer needs (a new node's banner
    must not be read against the last one's command reference) -- see
    `KissTermApp._bind_link`, which replaces rather than mutates.
    """

    link: object = None
    reference: "CommandReference" = field(default_factory=CommandReference)
    detect_buffer: str = ""
    transcript: SessionLog | None = None
    reply_timer: Timer | None = None
    #: Who the operator is currently, logically, talking to -- starts as
    #: `str(link.peer)` (the real AX.25 remote station, set in `_bind_link`
    #: since a dataclass default cannot read another field) and only changes
    #: once a hop to a different node is CONFIRMED to have succeeded (see
    #: `KissTermApp._commit_hop`). Distinct from `link.peer`, which never
    #: changes for the life of a connection even when the operator hops
    #: through intermediate nodes at the far node's application layer --
    #: conflating the two is what made `harvest_commands` cache a hopped-to
    #: node's command list under the FIRST node's callsign, silently
    #: corrupting that node's real entry in `harvested.py`'s store.
    current_node: str = ""
    #: The background watch started by `log_sent` for a hand-typed hop, so
    #: it can be cancelled -- a second hop sent before the first resolves
    #: must not leave two watchers racing on the same `link.on_data`. Kept
    #: as a plain `asyncio.Task` with a manual stop/clear, mirroring
    #: `reply_timer` above rather than introducing a worker-group pattern
    #: this file uses nowhere else.
    hop_watch_task: "asyncio.Task | None" = None
    #: `None` means "not harvesting right now" -- the common case. Set to an
    #: (initially empty) string by `KissTermApp.harvest_commands` for the
    #: duration of its capture window; `_capture_harvest` appends into it.
    #: See `HARVEST_CAPTURE_LIMIT` for why it cannot grow without bound.
    harvest_buffer: str | None = None
    #: Sanitized text from the most recent completed harvest on this live
    #: session. The Ctrl+R screen shows it after parsing so the operator can
    #: judge what the node actually said, rather than trusting a terse list
    #: of names extracted from an opaque exchange. It is deliberately
    #: per-session and in-memory: it is diagnostic context, not a second
    #: command cache or a new persistence promise.
    last_harvest_text: str = ""
    #: The last state `_on_link_state` was actually called with -- set on
    #: EVERY call, including a suppressed TIMER_RECOVERY one, never only on
    #: a call that wrote a note. See that method's docstring for why a
    #: "last state we wrote a note for" version of this field does not work.
    last_state: "SessionState | None" = None


def _status_row(parts: list[str]) -> Table:
    """Lay `parts` out across the FULL width of the status bar, not bunched
    at the left with the rest of the row empty.

    A plain ``"  |  ".join(parts)`` string looks fine on a narrow terminal and
    leaves most of a wide one blank -- exactly the "half the screen is empty"
    look this replaces. A `Table.grid` with one equal-ratio column per field
    re-flows automatically as the terminal is resized and as the number of
    fields changes (there are more of them once a link is connected), which a
    hand-computed padding string would not do without being recomputed on
    every resize event. The first field reads as a left anchor (the app
    identity), the last as a right anchor (heard count), and everything
    between is centered in its own share of the row -- the conventional shape
    of an editor or IDE status bar.
    """
    table = Table.grid(expand=True, padding=(0, 1))
    for i in range(len(parts)):
        justify = "left" if i == 0 else "right" if i == len(parts) - 1 else "center"
        table.add_column(justify=justify, ratio=1)
    table.add_row(*parts)
    return table


#: `AX25Link.last_error` set by `action_disconnect` when it cancels a connect
#: still in the SABM/retry phase. Checked back in `action_connect` so a
#: cancelled attempt is reported as cancelled, not run through the "no
#: answer" / "check the Monitor tab" wording meant for a genuine timeout.
CANCELLED_REASON = "cancelled by operator"


def _entry_link_override(text: str) -> int | None:
    """Turn an `addressbook.Entry.paclen`/`window` string into an override
    for `AX25Station.connect`, or `None` to mean "use the global default".

    `AddressBookEntryScreen` already refuses to save anything but blank or a
    positive whole number (`dialogs._validate_link_params`), but the address
    book is a JSON file an operator could still hand-edit into something
    invalid -- treating that the same as blank (fall back to the global
    default) is a data-format mismatch, not a reason to refuse a connect.
    """
    try:
        value = int(text.strip())
    except ValueError:
        return None
    return value if value >= 1 else None

#: Pause between auto-login lines (`KissTermApp._run_connect_script`). A
#: login sequence is normally two or three short commands, not a burst --
#: pacing them gives a BBS's own line handling a moment to catch up rather
#: than racing several commands in before it has processed the first.
CONNECT_SCRIPT_LINE_DELAY = 0.75

#: How long to wait for one intermediate node's own CONNECTED reply
#: (`KissTermApp._hop_to`) before giving up on that hop. Fixed rather than
#: scaled to the remaining chain length (unlike the bpq-apps node-map
#: crawler this is modelled on) -- that crawler walks up to ten
#: auto-discovered hops, this walks a short chain the operator typed by
#: hand, so a flat, generous timeout is simpler and does the job.
HOP_TIMEOUT = 20.0

#: A hop that answers with any of these has explicitly refused or dropped,
#: which is a different diagnosis from silence and must be reported
#: differently -- see `AX25Station.connect`'s DM-vs-timeout distinction for
#: the same reasoning one layer down. Matched case-insensitively as a
#: substring against everything received since the "C <node>" command went
#: out, the same heuristic bpq-apps' crawler uses against real BPQ nodes.
HOP_FAIL_WORDS = ("BUSY", "FAILED", "DISCONNECTED", "TIMEOUT")

#: The first word of an outgoing line that means "connect onward to a
#: different node" across every shipped family's own command set -- bpq32/
#: NET-ROM's "C"/"CONNECT" and JNOS's "connect" (its own alias table also
#: has "c"). `log_sent` starts a confirmation watch when it sees one of
#: these followed by a target, so an operator typing the command by hand
#: mid-session gets the same confirm-then-reset treatment the scripted hop
#: chain already gets from `_hop_to` -- see `log_sent`'s hop paragraph for
#: why detection otherwise never notices the switch, and `_commit_hop` for
#: why the reset must wait for the hop to actually come up.
HOP_COMMAND_WORDS = frozenset({"C", "CONNECT"})

#: How long after sending a line, with nothing back, before saying so
#: (`KissTermApp._note_if_no_reply`). From a real report: WS1EC-15
#: acknowledged a line at the AX.25 layer (an RR came back within 3
#: seconds) and then said nothing for 22 seconds before the operator gave
#: up and disconnected, having no way to tell "they got it, they are just
#: slow" from "this went nowhere" without reading the Monitor tab and
#: knowing to look for a hidden-by-default supervisory frame. Long enough
#: that an ordinary node's response time does not trip it on every line.
REPLY_WAIT_SECONDS = 15.0

#: `KissTermApp.harvest_commands` NEVER waits longer than this, no matter
#: what. From a real report: a fixed 5-second window (this constant's first
#: value) closed a harvest 12 seconds before WS1EC-15/CCEMA's reply even
#: started arriving -- its "?" needed three T1 retry/REJ recovery cycles
#: before the actual text came through, ~18.8 seconds after the request went
#: out, for a reply of all of two lines. That delay is real AX.25 behaviour
#: on a lossy link (AGENTS.md: "TIMER_RECOVERY is not an error state"), not
#: a hang, so the ceiling has to tolerate it -- 90s roughly matches
#: `describe_airtime(8192)`'s documented worst case plus headroom for
#: exactly this kind of retry overhead, which `describe_airtime` does not
#: model at all (it only prices wire time, not link-layer recovery).
HARVEST_MAX_WAIT_SECONDS = 90.0

#: Once a harvest has received AT LEAST ONE byte, this much silence after
#: the last one is treated as "the node is done sending" and the capture
#: ends early -- most replies are short, and nobody should have to wait out
#: the full 90-second ceiling for a two-line answer. This is deliberately
#: NOT the same heuristic AGENTS.md's testing section warns against ("do not
#: drain a lossy link with a went-quiet heuristic"): that warning is about
#: mistaking a mid-transfer T1 recovery gap for the end of an ongoing,
#: segmented transfer with no ceiling at all. This is a one-shot
#: request/reply exchange with a hard ceiling as the backstop, so a quiet
#: gap AFTER real content has already started arriving is a reasonable
#: signal, not a guess with no fallback.
HARVEST_QUIET_SECONDS = 3.0

#: How often `harvest_commands` checks the buffer while waiting. Small
#: enough that the quiet-exit above doesn't overshoot by much, cheap enough
#: that polling for up to 90 seconds costs nothing measurable.
HARVEST_POLL_INTERVAL = 0.5

#: Hard cap on how much text one harvest capture keeps, regardless of how
#: much the node actually sends. A chatty or verbose node must not turn one
#: opt-in harvest into unbounded memory growth for a session that stays open
#: for hours.
HARVEST_CAPTURE_LIMIT = 4096


class _HopConfirmation:
    """Watches one link for a node's own reply to a "C <node>" that has just
    gone out, and decides whether the hop came up.

    THE one definition of "the hop worked" in this app -- both the scripted
    hop chain (`KissTermApp._hop_to`) and a hand-typed hop
    (`KissTermApp.log_sent`'s background watch) go through it, so the two
    cannot drift apart on, say, whether DISCONNECTED counts as a refusal.

    A small class rather than a plain coroutine for one reason that is not
    cosmetic: it subscribes to `link.on_data` in `__init__`, SYNCHRONOUSLY.
    A coroutine can only subscribe once the event loop first runs it, and
    `log_sent` is a synchronous method that cannot await anything before
    returning -- so a reply arriving in that window would be fanned out to
    every other subscriber and missed by this one, and the hop would never
    be confirmed at all.

    Subscribing is non-destructive: the terminal pane has its own separate
    subscriber from `_bind_link` and goes on displaying the same bytes, the
    same one-fan-out-many-subscribers shape as the frame transport's own
    `subscribe()`. `stop()` must always be called -- a watcher left
    subscribed goes on matching a later, unrelated hop's traffic.
    """

    def __init__(self, link, node: str) -> None:
        self._link = link
        self._node = node
        self._seen = bytearray()
        self.result: asyncio.Future[tuple[bool, str]] = (
            asyncio.get_event_loop().create_future()
        )
        link.on_data.append(self._on_data)

    def _on_data(self, data: bytes) -> None:
        self._seen.extend(data)
        # latin-1 for the same reason every other payload decode in this app
        # uses it: a corrupt frame off a noisy channel must lose the noise,
        # not the readable part around it.
        text = self._seen.decode("latin-1", "replace").upper()
        if "CONNECTED" in text:
            if not self.result.done():
                self.result.set_result((True, ""))
            return
        for word in HOP_FAIL_WORDS:
            if word in text:
                if not self.result.done():
                    self.result.set_result((False, f"{self._node} answered {word}"))
                return

    def stop(self) -> None:
        """Unsubscribe. Idempotent -- it is called from both the awaiting
        coroutine's `finally` and the watching task's done callback, and
        either one may get there first."""
        with contextlib.suppress(ValueError):
            self._link.on_data.remove(self._on_data)


class _SessionLinkAdapter:
    """Presents a session-tier `Session` (VARA, Mercury, kernel AX.25,
    Telnet, SSH) with the same shape `AX25Link` already has, so every piece
    of connect-flow logic written once against `AX25Link` -- `_bind_link`,
    `_hop_through`/`_hop_to`, `_run_connect_script`, `action_disconnect` --
    works unchanged for either tier, with no branch scattered through any
    of them.

    The two really do differ: `Session.on_state_change` is a registration
    *method*, `AX25Link.on_state` a plain callback list; `Session` has no
    `on_data` at all, only an `incoming` queue fed by `deliver()`, because
    `Session` predates any real caller -- nothing in this app constructed
    one through `SessionTransport.connect()` before this adapter existed.
    Adapting here rather than reshaping `Session` to match keeps
    `kernel_ax25.py`/`vara.py`/`mercury.py` and their existing tests
    (`tests/unit/test_tx_gate.py` included) untouched.

    `Session` also has no error-reporting channel to match `AX25Link.
    on_error` -- `self.on_error` exists so `_bind_link` can append to it
    without a branch, but nothing here ever calls what is in it. Session
    transports do not have a "why" beyond a plain disconnect yet.
    """

    def __init__(self, session) -> None:
        self._session = session
        self.peer = session.peer
        self.on_data: list = []
        self.on_state: list = []
        self.on_error: list = []
        session.on_state_change(lambda _session, state: self._emit_state(state))
        self._pump_task = asyncio.get_event_loop().create_task(
            self._pump(), name=f"session-adapter-pump:{session.peer}"
        )

    @property
    def connected(self) -> bool:
        return self._session.connected

    @property
    def state(self):
        return self._session.state

    async def send(self, data: bytes) -> None:
        await self._session.send(data)

    async def disconnect(self) -> None:
        """The session-tier equivalent of `AX25Link.disconnect()` -- there
        is no DISC to send, only the connection itself to close."""
        self._pump_task.cancel()
        await self._session.close()

    def close(self) -> None:
        self._pump_task.cancel()

    def _emit_state(self, state) -> None:
        for cb in list(self.on_state):
            cb(state)

    async def _pump(self) -> None:
        try:
            while True:
                data = await self._session.incoming.get()
                for cb in list(self.on_data):
                    cb(data)
        except asyncio.CancelledError:
            pass


class KissTermFooter(Footer):
    """A Footer that hides its lowest-priority keys instead of scrolling
    them off-screen.

    Textual's own `Footer` is a horizontally-scrollable container with its
    scrollbar suppressed (`scrollbar-size: 0 0` in its own `DEFAULT_CSS`):
    at an ordinary 80-column terminal, kissterm's eleven action bindings plus
    the command-palette chip need about 140 columns, so roughly a third of
    them are pushed past the right edge, reachable only by a mouse-wheel
    scroll with no on-screen sign anything is missing. Reported directly
    from a real session; see `docs/CHANGELOG.md`.

    This override reimplements `Footer.compose()` (Textual's own version:
    `textual.widgets._footer.Footer.compose`) but replaces "show every
    `show=True` binding, however many columns that needs" with "show the
    highest-priority prefix of them that actually fits" --
    `commands.fit_footer_bindings`, ranked by `commands.ACTION_META`. A
    narrower terminal means fewer keys shown, never a key silently pushed
    out of reach; the full set stays one `Ctrl+P` away either way, since
    `commands.KeyBindingsProvider` reads the same `BINDINGS` list.

    Does NOT support `Binding.Group` the way the real `Footer.compose()`
    does -- nothing in this app groups bindings today. Add that back (see
    the real implementation) if a future `Binding` ever sets `group=`.

    `_on_resize` is what makes the fit re-run as the terminal is resized:
    Textual's own `Footer` only recomposes when the *set* of bindings
    changes (`bindings_updated_signal`), because which ones fit was never
    previously a function of width. `refresh_bindings()` republishes that
    same signal, which `Footer.bindings_changed` (inherited, unchanged) is
    already subscribed to.
    """

    def compose(self) -> ComposeResult:
        if not self._bindings_ready:
            return
        active_bindings = self.screen.active_bindings
        bindings = [
            (binding, enabled, tooltip)
            for (_, binding, enabled, tooltip) in active_bindings.values()
            if binding.show
        ]
        action_to_bindings: dict[str, list[tuple[Binding, bool, str]]] = {}
        for binding, enabled, tooltip in bindings:
            action_to_bindings.setdefault(binding.action, []).append(
                (binding, enabled, tooltip)
            )

        show_palette = self.show_command_palette and self.app.ENABLE_COMMAND_PALETTE
        palette_binding = None
        palette_reserved = 0
        if show_palette:
            try:
                _node, palette_binding, _enabled, _tooltip = active_bindings[
                    self.app.COMMAND_PALETTE_BINDING
                ]
            except KeyError:
                show_palette = False
            else:
                palette_reserved = (
                    len(self.app.get_key_display(palette_binding))
                    + len(palette_binding.description)
                    + 3
                )

        budget = max(self.size.width - palette_reserved, 0)
        items = [
            (
                action,
                self.app.get_key_display(group[0][0]),
                group[0][0].description,
            )
            for action, group in action_to_bindings.items()
        ]
        for action, key_display, description in fit_footer_bindings(items, budget):
            binding, enabled, tooltip = action_to_bindings[action][0]
            yield FooterKey(
                binding.key,
                key_display,
                description,
                binding.action,
                disabled=not enabled,
                tooltip=tooltip,
            ).data_bind(compact=Footer.compact)

        if show_palette:
            _node, binding, enabled, tooltip = active_bindings[
                self.app.COMMAND_PALETTE_BINDING
            ]
            yield FooterKey(
                binding.key,
                self.app.get_key_display(binding),
                binding.description,
                binding.action,
                classes="-command-palette",
                disabled=not enabled,
                tooltip=binding.tooltip or binding.description,
            )

    def _on_resize(self, event: events.Resize) -> None:
        self.refresh_bindings()


class KissTermApp(App):
    """The application.

    `config` and `station` are injected rather than constructed here so a
    headless test can mount the app against a loopback transport with no radio,
    no serial port, and no real config directory. Constructing them internally
    would make every UI test require hardware.
    """

    TITLE = "kissterm"

    CSS = APP_CSS

    #: Adds `KeyBindingsProvider` (`commands.py`) to Textual's own default
    #: `{get_system_commands_provider}` -- without this, Ctrl+P only ever
    #: listed Textual's small built-in System Commands (Theme, Quit, Keys,
    #: Maximize, Screenshot), and typing in its search box filtered that
    #: short list and nothing else: none of kissterm's own BINDINGS, visible
    #: or hidden, were searchable there at all.
    COMMANDS = App.COMMANDS | {KeyBindingsProvider}

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        # Hidden from the footer: the tab bar already shows these instead
        # (rule 16, `kissterm/ui/AGENTS.md`) -- unrelated to why every other
        # binding below stays discoverable even once `KissTermFooter` (this
        # module) runs out of room for it: `Ctrl+P` lists all of them,
        # `commands.KeyBindingsProvider` reads this same list.
        # Ordered by how often an operator actually visits them, requested
        # directly: "putting useful stuff to the left of Monitor and
        # Settings". Terminal and APRS are where the work happens; Monitor is
        # a diagnostic and Settings is a place you leave again. The TabPane
        # IDs deliberately did NOT change with this reordering -- every
        # `active == "aprs"` check, `_TAB_FOCUS` entry and `show_tab` caller
        # addresses a pane by id, so only the labels and the keys moved.
        Binding("f1", "show_tab('terminal')", "Terminal", show=False),
        Binding("f2", "show_tab('aprs')", "APRS", show=False),
        Binding("f3", "show_tab('heard')", "Heard", show=False),
        Binding("f4", "show_tab('monitor')", "Monitor", show=False),
        Binding("ctrl+1", "show_tab('terminal')", "Terminal", show=False),
        Binding("ctrl+2", "show_tab('aprs')", "APRS", show=False),
        Binding("ctrl+3", "show_tab('heard')", "Heard", show=False),
        Binding("ctrl+4", "show_tab('monitor')", "Monitor", show=False),
        Binding("f5", "show_tab('settings')", "Settings", show=False),
        Binding("ctrl+5", "show_tab('settings')", "Settings", show=False),
        Binding("ctrl+t", "toggle_transmit", "TX"),
        Binding("ctrl+shift+y", "file_transfer", "Files", key_display="^Y"),
        # The Address Book (Terminal) and APRS contacts slide-outs share this
        # one key -- see `action_toggle_contacts`. Checked against every
        # existing claim before picking "G": `Input`'s own bindings already
        # own ctrl+a *and* ctrl+shift+a (home / select-all), ctrl+e/w/u/k/x/
        # c/v/d for line editing; this app already owns ctrl+q/t/b/n/d/k/r/l/
        # o/f/1..5; Textual's own command palette owns ctrl+p; and Ctrl+C
        # (any shifted form included) is avoided everywhere in this file for
        # the SIGINT reason below. Ctrl+G collides with none of that and is
        # not a flow-control byte or job-control signal either, so it needs
        # no Ctrl+Shift+-plus-legacy-fallback pair the way Beacon/Disconnect
        # do below.
        Binding("ctrl+g", "toggle_contacts", "Contacts", key_display="^G"),
        # Ctrl+SHIFT+B, not Ctrl+B: Ctrl+B is tmux's default prefix (and
        # screen's, once remapped), so under a multiplexer -- which is how a
        # station PC in another room is usually reached -- the beacon key was
        # simply unreachable, eaten one layer up. Ctrl+Shift+B needs the
        # terminal's enhanced keyboard protocol to be distinguishable at all;
        # where it is not, the terminal collapses it to the same byte as
        # Ctrl+B, which is why the plain binding stays below.
        # `key_display` because Textual abbreviates `ctrl+x` to `^x` on its
        # own but has no such rule for `ctrl+shift+x`, so this one binding
        # would print the literal "ctrl+shift+b" -- five times the width of
        # every neighbour, in a footer that already truncates its rightmost
        # binding at 80 columns. `^B` is the same shape as `^t`/`^n`/`^d`
        # beside it, and the capital IS the shift.
        Binding("ctrl+shift+b", "beacon_now", "Beacon", key_display="^B"),
        # Legacy fallback, deliberately hidden. In a terminal that does not
        # speak the kitty/CSI-u keyboard protocol, Ctrl+Shift+B *is* 0x02 and
        # arrives here as "ctrl+b"; without this the beacon would have no key
        # at all on such a terminal, and there is no slash command for it.
        # This costs nothing under a multiplexer, which consumes Ctrl+B before
        # the app ever sees it.
        Binding("ctrl+b", "beacon_now", "Beacon", show=False),
        # A one-shot APRS position report is a different action from both the
        # context-aware Ctrl+Shift+B beacon shortcut and its periodic timer.
        # Ctrl+Alt+B makes that distinction reachable without moving focus to
        # the APRS pane or editing any settings.
        Binding("ctrl+alt+b", "aprs_beacon_now", "Position now"),
        Binding("ctrl+shift+o", "aprs_object", "Object", key_display="^O"),
        Binding("ctrl+n", "connect", "Connect"),
        # Ctrl+SHIFT+D, not plain Ctrl+D, for the same reason as Ctrl+Shift+B
        # above: Textual's `Input` and `TextArea` both bind plain `ctrl+d` to
        # delete-character-right for ordinary line editing (`show=False`),
        # and whichever of those has focus -- which is most of the session:
        # the terminal's own outgoing-message box -- wins over the app-level
        # binding of the same key. Before this, the Footer silently dropped
        # "Disconnect" the instant that box took focus, and the keystroke
        # deleted a character instead of disconnecting -- reported directly
        # ("^d went missing when I started to connect"). `key_display="^D"`
        # keeps the footer showing the same short glyph as every neighbour;
        # the capital is the shift, same convention as `^B`.
        Binding("ctrl+shift+d", "disconnect", "Disconnect", key_display="^D"),
        # Legacy fallback, hidden, for a terminal that collapses Ctrl+Shift+D
        # to plain Ctrl+D -- same reasoning as the Ctrl+B fallback below.
        # Still shadowed by a focused Input/TextArea exactly as before this
        # change; Ctrl+Shift+D above is what actually fixes the report.
        Binding("ctrl+d", "disconnect", "Disconnect", show=False),
        # Ctrl+K (Callsign) has the identical collision with Input/TextArea's
        # own delete-to-end-of-line binding and is not fixed here -- nobody
        # has hit it in practice, and TextArea's own Ctrl+Shift+K
        # (delete-line, used by the auto-login script boxes) means the same
        # Ctrl+Shift+ fix used above for Disconnect is not free for this key.
        # Worth the Ctrl+Shift+K trade-off only if this ever gets reported.
        Binding("ctrl+k", "set_callsign", "Callsign"),
        Binding("ctrl+r", "command_reference", "Commands"),
        Binding("ctrl+l", "clear_log", "Clear"),
        # "Open" is the standard mnemonic (most editors' Ctrl+O) for "open a
        # saved file", and there is nothing else on this key.
        Binding("ctrl+o", "show_transcripts", "Transcripts"),
        # The universal "Find" mnemonic (every browser, every editor).
        Binding("ctrl+f", "find_in_terminal", "Find"),
        # Ctrl+SHIFT+F, not plain Ctrl+F, because plain Ctrl+F is "Find"
        # right above -- same reason Beacon/Disconnect use Ctrl+Shift+
        # rather than collide with an existing key. UNLIKE those two,
        # there is no safe hidden legacy fallback to add here: on a
        # terminal without the kitty/CSI-u enhanced keyboard protocol,
        # Ctrl+Shift+F collapses to the same byte as Ctrl+F, and a
        # fallback bound to "ctrl+f" would just steal Find's key instead
        # of adding this one. On such a terminal this toggle is reachable
        # only through Settings -- same trade-off already accepted for
        # Ctrl+K (Callsign) above, not worth solving until reported.
        Binding("ctrl+shift+f", "toggle_aprs_ssid_filter", "SSID Filter", key_display="^F"),
    ]

    def __init__(
        self,
        config,
        station: AX25Station | None = None,
        session_transport=None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.config = config
        if config.ascii_safe:
            # The stylesheet supplies ASCII alternatives only within this
            # application.  Do not mutate Textual's process-wide glyph tables:
            # other apps (and parallel tests) may be rendering at the same time.
            self.add_class("-ascii-safe")
        # Applied before the rest of __init__ so the very first frame paints
        # in the configured theme rather than Textual's own default and then
        # visibly flashing over to the right one a moment later.
        self.apply_theme()
        self.station = station
        #: Set when the active transport is a `SessionTransport` (Telnet,
        #: SSH, VARA, Mercury, kernel AX.25) instead of a `FrameTransport` --
        #: `station` stays None in that case, since there is no AX.25 state
        #: machine for one of these to run underneath. Exactly one of
        #: `station`/`session_transport` is ever set; see `action_connect`
        #: for how the two paths converge on the same terminal-pane binding
        #: through `_SessionLinkAdapter`.
        self.session_transport = session_transport
        #: The master transmit switch, installed here rather than left to
        #: whatever built the transport: a bare transport is a dumb pipe with
        #: no operator, and the app is the thing that HAS an operator. Closed
        #: unless `tx_armed_at_start` says otherwise, so a fresh launch cannot
        #: key a radio until Ctrl+T. See kissterm/tx.py.
        self.gate = TransmitGate(enabled=getattr(config, "tx_armed_at_start", False))
        if station is not None:
            station.transport.gate = self.gate
        elif session_transport is not None:
            session_transport.gate = self.gate
        self.gate.on_change.append(self._on_transmit_change)
        self.heard = HeardTable()
        self.monitor_filter = MonitorFilter()
        #: Drops the monitor's receive subscription on unmount. Set in
        #: `on_mount`; a no-op until then so shutdown never has to ask
        #: whether mount happened.
        self._unsubscribe_monitor = lambda: None
        #: Same reasoning as `_unsubscribe_monitor` -- a no-op until
        #: `on_mount` replaces it, so shutdown never has to ask whether
        #: mount happened.
        self._unsubscribe_aprs = lambda: None
        #: Per-session state (link, node reference, transcript, reply-watch
        #: timer), keyed by `_session_key`. The permanent `""` entry is the
        #: pre-connection view -- see the module docstring and
        #: `_TerminalSession`'s. `self.link`/`self.reference`/`self.transcript`
        #: below are read-only properties over whichever entry is active.
        self._sessions: dict[str, _TerminalSession] = {"": _TerminalSession()}
        #: Targets of connect attempts still in the SABM/retry phase,
        #: session key -> the peer address. Needed because a session's
        #: `_sessions` entry does not exist until the attempt SUCCEEDS, so
        #: without this Ctrl+D during a stuck connect has nothing to act on
        #: and can only say "Not connected", leaving the operator to wait
        #: out N2 retries with no way to stop them. See `action_connect` and
        #: `action_disconnect`.
        self._connecting: dict[str, tuple[AX25Address, int]] = {}
        #: The one in-flight SessionTransport.connect() call, if any. Session
        #: transports have no AX.25 link for Ctrl+D to close during setup, so
        #: the task itself is the cancellation handle. It is set only while
        #: awaiting connect(), not for an established session or login script.
        self._session_connect_task: asyncio.Task[object] | None = None
        self._status = "starting"
        #: Stations already tried, offered in the connect dialog. Owned here
        #: rather than by the dialog so a successful connect can be recorded
        #: after the dialog has closed, and so the file is read once at
        #: startup instead of on every Ctrl+N.
        self.addressbook = AddressBook()
        self.addressbook.load()
        self.known_nodes = KnownNodes()
        #: Command names harvested from a node's own `?`, cached forever per
        #: callsign so the opt-in airtime is never spent twice for the same
        #: node -- see `kissterm/harvested.py` and `harvest_commands` below.
        self._harvested = HarvestedCommands()
        self._harvested.load()
        #: APRS message history, keyed by correspondent -- see
        #: kissterm/aprs_conversations.py. Loaded here rather than by the
        #: APRS pane so a message that arrives before the operator ever
        #: visits F2 is still recorded, the same reasoning `self.heard`
        #: is built and loaded before any pane asks for it.
        self.aprs_conversations = ConversationStore()
        self.aprs_conversations.load()
        self._purge_stale_synthetic_messages()
        #: Keeps an RF retry or a second copy from another relay path out of
        #: the conversation twice. It is deliberately in-memory-only: APRS
        #: message numbers may be reused, so a restart starts a new reception
        #: window instead of suppressing a later real message from history.
        self._aprs_message_deduplicator = MessageDeduplicator()
        #: Suppresses a repeat desktop notification for the same (source,
        #: reason) pair within its window -- see kissterm/aprs_notify.py.
        #: An Emergency Mic-E flag always bypasses it.
        self._aprs_notify_cooldown = Cooldown()
        #: Suppresses a repeat "could not ack -- transmit is off" toast for
        #: the same (addressee, number) pair -- a sender that retries an
        #: unacked message every 30-90 seconds must not repaint the same
        #: warning on top of itself each time. Separate instance from
        #: `_aprs_notify_cooldown` above: this is "did the ack go out",
        #: not "should a desktop notification fire", and the two must not
        #: consume each other's window.
        self._aprs_ack_blocked_cooldown = Cooldown()
        #: Watches local serial ports only. The network is never scanned on a
        #: timer -- see kissterm/hotplug.py for the cost argument.
        self.port_watcher = SerialPortWatcher()
        #: (source callsign, matched callsign) pairs already surfaced by
        #: `_check_mail_for`, so a beacon repeating on its own interval does
        #: not re-notify the operator every time it is heard again -- the
        #: point is "you have not seen this yet", not a running tally.
        self._mail_notified: set[tuple[str, str]] = set()
        self._transfer_active: set[str] = set()
        #: Monotonic time of local interaction.  This intentionally means
        #: active use, not merely an app window that happens to be open.
        self._last_operator_activity = time.monotonic()
        self._watch_notifier = self._make_watch_notifier()
        #: Plain-text beacon. Constructed unconditionally so there is one
        #: object to ask "is this station transmitting on a timer?"; it does
        #: nothing at all until `start()` succeeds, and `start()` refuses
        #: unless the operator opted in AND set some text.
        self.beaconer = Beaconer(
            station, getattr(config, "beacon", None) or BeaconConfig(),
            on_sent=self._on_beacon_sent,
        )
        #: APRS position beacon -- same shape as `beaconer` above, separate
        #: timer, separate config table, separate destination. See
        #: `kissterm/aprs_beacon.py`'s module docstring for why the two must
        #: never be conflated.
        self.aprs_beaconer = AprsBeaconer(
            station, getattr(config, "aprs", None) or AprsConfig(),
            on_sent=self._on_aprs_beacon_sent,
        )

    # ------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield KissTermHeader(show_clock=True)
        with TabbedContent(initial="terminal", id="main-tabs"):
            with TabPane("F1 Terminal", id="terminal"):
                yield TerminalPane()
            with TabPane("F2 APRS", id="aprs"):
                yield AprsPane()
            with TabPane("F3 Heard", id="heard"):
                yield HeardPane()
            with TabPane("F4 Monitor", id="monitor"):
                yield MonitorPane()
            with TabPane("F5 Settings", id="settings"):
                yield SettingsPane()
        # Status bar and Footer share one bottom-docked container. Docking
        # them both individually puts them in the SAME region -- the Footer
        # paints over the status bar and it is invisible, in either yield
        # order. One docked parent with an explicit height lays them out as
        # two distinct rows. Verified in tests/pilot/test_app_mounts.py.
        with Vertical(id="bottom-bar"):
            yield KissTermFooter()
            yield Static(id="status-bar")

    def apply_theme(self) -> None:
        """Resolve and activate `self.config.theme`.

        Called from `__init__` (so the first paint is already correct), and
        again whenever a theme change might have happened after that --
        saving Settings, or reloading config.toml from disk. Re-registering
        `"custom"` every time is cheap and means an edited `[custom_theme]`
        table takes effect on the next save/reload without a restart.
        """
        if self.config.theme == "custom":
            custom = self.config.custom_theme
            colors = {f: getattr(custom, f) for f in themes.CUSTOM_THEME_FIELDS}
            self.register_theme(themes.build_custom_theme(colors, dark=custom.dark))

        resolved, warning = themes.resolve_theme_id(self.config.theme)
        if warning:
            log.warning(warning)
        self.theme = resolved

    def on_mount(self) -> None:
        self.query_one(SettingsPane).render_settings(self.config)
        # Paint once immediately, then on a timer. Without the eager call the
        # status bar is blank for the first second of every launch, which
        # reads as "the app has not connected to anything" at exactly the
        # moment the operator is looking for confirmation that it has.
        self._refresh_status()
        self._start_port_watcher()
        self.set_interval(1.0, self._refresh_status)
        self.set_interval(2.0, self._refresh_heard)
        if self.station is not None:
            # Straight off the transport, not off `station.on_unhandled`: a
            # frame belonging to an open link never reaches `on_unhandled`,
            # so a monitor fed from there goes silent at exactly the moment
            # the operator most needs it -- during the connection they are
            # trying to diagnose. The monitor is a channel monitor or it is
            # nothing.
            self._unsubscribe_monitor = self.station.transport.subscribe(
                self._on_received_frame
            )
            # A second, independent subscriber on the same fan-out -- never a
            # second decode path for the same frame (AGENTS.md sec. 2b). This
            # one only ever looks at APRS traffic (position/message/status
            # UI frames); the monitor subscriber above still sees, and still
            # renders, everything.
            self._unsubscribe_aprs = self.station.transport.subscribe(self._on_aprs_frame)
            self.station.transport.on_sent.append(self._on_sent_frame)
            self.station.on_incoming.append(self._on_incoming_link)
            self._status = f"{self.station.transport.info.detail}"
        self.query_one(TerminalPane).log(
            "",
            f"kissterm {__version__} -- Ctrl+N to connect, Ctrl+R for commands, "
            "Ctrl+O for past transcripts.\n",
        )
        self.apply_runtime_settings()

    # ------------------------------------------------------------------
    # Settings that need something done, not just stored
    # ------------------------------------------------------------------
    def apply_runtime_settings(self) -> None:
        """Reconcile the running app with `self.config` after a change.

        Called on mount and after every Settings save. Everything here is
        idempotent, because "save" gets pressed repeatedly and the second
        press must not, for instance, leave two beacon timers running.
        """
        for pane in self._base_query(TerminalPane):
            pane.remote_color = getattr(self.config, "remote_color", True)
        self._restart_beacon()
        self._restart_aprs_beacon()
        self._watch_notifier = self._make_watch_notifier()

    def _make_watch_notifier(self) -> WatchNotifier:
        watched = self.config.watched_callsigns
        return WatchNotifier(
            cooldown_seconds=watched.cooldown_minutes * 60,
            hourly_cap=watched.hourly_cap,
            quiet_start_hour=watched.quiet_start_hour if watched.quiet_start_hour >= 0 else None,
            quiet_end_hour=watched.quiet_end_hour if watched.quiet_end_hour >= 0 else None,
        )

    def on_key(self, event: events.Key) -> None:
        """Mark deliberate local use so a visible frame does not raise a toast."""
        self._last_operator_activity = time.monotonic()

    @work
    async def _restart_beacon(self) -> None:
        """Stop then start, rather than mutating a running beaconer.

        A live edit would leave a window where the interval and the text
        disagree about what is going out -- and what goes out is transmitted
        under the operator's callsign, so "probably fine" is not the standard.
        """
        await self.beaconer.stop()
        self.beaconer.station = self.station
        self.beaconer.config = getattr(self.config, "beacon", None) or BeaconConfig()
        why = self.beaconer.start()
        # Only worth saying when the operator asked for a beacon and did not
        # get one. "beaconing is off" is not news, and "transmit is disabled"
        # is already the loudest thing in the status bar -- repeating it as a
        # toast on every launch and every Settings save is noise.
        if why and self.beaconer.config.enabled and why != "transmit is disabled":
            self.notify(f"Beacon not started: {why}", severity="warning")

    def _on_beacon_sent(self, frame: AX25Frame) -> None:
        """Every beacon is visible in the terminal pane, without exception.

        A station that transmits without the operator being able to see that
        it did is exactly what the opt-in exists to prevent. This is the
        record of it, not a debug aid.
        """
        self._to_terminal(self._active_key(), "log", f"\n*** Beacon sent to {frame.path.destination}\n")

    @work
    async def _restart_aprs_beacon(self) -> None:
        """Stop then start the APRS position beacon -- see `_restart_beacon`
        for why a live mutation is wrong here too: a half-changed config
        transmitting under the operator's callsign is never acceptable.
        """
        await self.aprs_beaconer.stop()
        self.aprs_beaconer.station = self.station
        self.aprs_beaconer.config = getattr(self.config, "aprs", None) or AprsConfig()
        why = self.aprs_beaconer.start()
        if why and self.aprs_beaconer.config.enabled and why != "transmit is disabled":
            self.notify(f"APRS beacon not started: {why}", severity="warning")

    def _on_aprs_beacon_sent(self, frame: AX25Frame) -> None:
        """Same rule as `_on_beacon_sent`: every transmission is visible."""
        self._to_terminal(self._active_key(), "log", "\n*** APRS position beacon sent\n")

    def on_unmount(self) -> None:
        """Disarm the beacons as the app goes away.

        Not merely tidy: a beacon task still armed while the UI is being torn
        down would transmit under the operator's callsign with nothing on
        screen to show it -- and nowhere to show it.
        """
        self.beaconer.cancel()
        self.aprs_beaconer.cancel()
        self._unsubscribe_monitor()
        self._unsubscribe_aprs()
        self._close_all_transcripts()
        self._cancel_all_reply_timers()
        self._cancel_all_hop_watches()

    # ------------------------------------------------------------------
    # Hardware hotplug (serial only -- never the network)
    # ------------------------------------------------------------------
    @work
    async def _start_port_watcher(self) -> None:
        """Notice a TNC being plugged in or unplugged, without scanning anything.

        `prime()` first, so ports that were already present at launch do not
        each produce a toast -- they are not news.
        """
        self.port_watcher.subscribe(self._on_port_event)
        await self.port_watcher.prime()
        self.port_watcher.start()

    def _on_port_event(self, event: PortEvent) -> None:
        if event.action == "added":
            if not event.likely_tnc:
                # An unrecognized port is more often a phone or a dongle than a
                # TNC. Log it for --doctor, do not interrupt the operator.
                log.info("serial port appeared: %s (%s)", event.device, event.note)
                return
            self._to_terminal(
                self._active_key(), "log", f"\n*** Plugged in: {event.device} -- {event.detail}\n"
            )
            self.notify(
                f"{event.device} looks like a TNC ({event.detail}). "
                f"Settings -> Transports to use it.",
                title="New device",
                timeout=10,
            )
            return

        # Removed. Only worth shouting about if it is the one in use.
        if self._active_device() == event.device:
            self._to_terminal(self._active_key(), "log", f"\n*** {event.device} was unplugged\n")
            self.notify(
                f"{event.device} -- the transport in use -- was unplugged.",
                severity="error",
                timeout=15,
            )
        else:
            log.info("serial port removed: %s", event.device)

    def _active_device(self) -> str | None:
        """The device path of the configured active transport, if it has one."""
        name = getattr(self.config, "active_transport", "")
        for entry in getattr(self.config, "transports", ()) or ():
            if entry.get("name") == name:
                return entry.get("device")
        return None

    # ------------------------------------------------------------------
    # Frame fan-out
    # ------------------------------------------------------------------
    def _on_received_frame(self, frame: AX25Frame, port: int = 0) -> None:
        """Every frame off the air, link-owned or not.

        Feeds the heard list and the monitor pane. Deliberately every frame:
        the peer we are linked to is a station we have heard, and its UA is
        the single most interesting frame of a connection attempt.
        """
        self.heard.record(frame, port)
        self._monitor(frame, port, outgoing=False)
        self._check_mail_for(frame)
        self._check_watched_callsigns(frame)
        if self.known_nodes.observe(frame):
            for pane in self._base_query(TerminalPane):
                pane.refresh_known_nodes()

    def _check_watched_callsigns(self, frame: AX25Frame) -> None:
        """Surface configured source/repeater *claims* from the existing fan-out."""
        watched = self.config.watched_callsigns
        if not watched.enabled or not watched.callsigns:
            return
        claimed = claimed_callsigns(frame.path)
        wanted = normalize_callsigns(watched.callsigns)
        active = time.monotonic() - self._last_operator_activity < watched.active_suppression_seconds
        now_local = datetime.now().astimezone()
        for callsign in sorted(claimed & wanted):
            if not self._watch_notifier.allow(
                callsign, now_monotonic=time.monotonic(), now_local=now_local, app_active=active
            ):
                continue
            title = f"Watched callsign claim: {callsign}"
            body = "Claim carried in a received AX.25 frame; not authenticated identity."
            self.notify(f"{title}. {body}", severity="information")
            self._notify_watched_desktop(title, body)

    @work
    async def _notify_watched_desktop(self, title: str, body: str) -> None:
        await desktop_notify.notify_any(title, body)

    def _on_sent_frame(self, frame: AX25Frame, port: int = 0) -> None:
        """Every frame that got past the transmit gate. Monitor only --
        hearing ourselves is not the same as hearing another station, and
        putting our own callsign in the heard list would be a lie."""
        self._monitor(frame, port, outgoing=True)

    def _monitor(self, frame: AX25Frame, port: int, outgoing: bool) -> None:
        if not self.monitor_filter.allows(frame, port):
            return
        line = format_frame(frame, port, outgoing=outgoing)
        for pane in self._base_query(MonitorPane):
            pane.write_line(line.as_text())

    def _check_mail_for(self, frame: AX25Frame) -> None:
        """Notice someone else's node beaconing mail for us -- see
        docs/ROADMAP.md P9, "Passive mail waiting notification".

        Passive, like `_sniff_node`: reads a beacon kissterm already decoded
        off the shared frame fan-out (AGENTS.md sec. 2b), asks no question,
        and needs no connection -- the modem being on frequency is enough to
        hear it. Restricted to UI frames because that is what a beacon
        actually is; a connected-mode chat line that happens to contain the
        words "mail for" is not a node advertising a mailbox.
        """
        if frame.kind != "U" or frame.utype is not UType.UI:
            return
        if not frame.info or frame.pid not in (PID_NO_LAYER3, None):
            return
        calls = [self.config.mycall, *self.config.mycall_aliases]
        matched = mail_waiting_for(sanitize(frame.info, keep_newlines=False), calls)
        if matched is None:
            return
        source = str(frame.path.source)
        key = (source, matched)
        if key in self._mail_notified:
            return
        self._mail_notified.add(key)
        self._to_terminal(
            self._active_key(),
            "log",
            f"\n*** {source} is holding mail for {matched} (heard on the channel)\n",
        )
        self.notify(f"{source} has mail waiting for {matched}.", severity="information")
        self._notify_mail_desktop(source, matched)

    @work
    async def _notify_mail_desktop(self, source: str, matched: str) -> None:
        # Best-effort only -- see kissterm/desktop_notify.py for why a
        # subprocess call here has to be async and never allowed to raise.
        await desktop_notify.notify_any(
            f"Mail waiting at {source}",
            f'Heard "MAIL FOR {matched}" on the channel.',
            sound="request",
        )

    # ------------------------------------------------------------------
    # APRS: message history, auto-ack, and Emergency/message notification
    # ------------------------------------------------------------------
    def _active_aprs_identity(self) -> str:
        """This station's real, currently-transmitted APRS identity
        (`Config.aprs.source_for`, stringified) -- what `aprs_message_matches`
        requires an exact match against when `Config.aprs.filter_by_ssid`
        is on. Falls back to the bare configured callsign on a parse
        failure rather than raising: this runs from the frame fan-out,
        and a malformed `mycall` must not take the whole handler down
        with it (AGENTS.md's "never let a decode error raise out of a
        background task" rule).
        """
        mycall = str(self.station.mycall) if self.station is not None else self.config.mycall
        try:
            return str(self.config.aprs.source_for(mycall))
        except AX25AddressError:
            return mycall

    async def _on_aprs_frame(self, frame: AX25Frame, port: int = 0) -> None:
        """Decode one frame as APRS, if it is APRS at all.

        A second subscriber on the same fan-out `_on_received_frame` uses --
        never a second decode path for the same bytes (AGENTS.md sec. 2b).
        `aprs.parse_packet` itself never raises (see its module docstring);
        everything past that point here is app-level routing: record a
        message into `self.aprs_conversations`, auto-ack it if addressed to
        us, and decide whether it is worth an unattended notification via
        `kissterm.aprs_notify.evaluate_packet`.
        """
        packet = aprs.parse_packet(frame)
        if packet is None:
            return

        if packet.kind in ("position", "mic-e") and isinstance(packet.data, aprs.Position):
            # Enriches the MHEARD entry this frame already produced via
            # `_on_received_frame` -> `heard.record` -- `HeardTable` never
            # decodes APRS itself (see its module docstring), so this is the
            # one place that feeds it a position. Feeds the Heard pane's
            # bearing/distance columns.
            self.heard.set_position(str(packet.source), packet.data.latitude, packet.data.longitude)
        elif packet.kind == "unparsed":
            # A UI/PID-0xF0 frame that is not APRS at all -- most often an
            # ordinary packet-node or BBS beacon, which by long-standing
            # convention (predating APRS, and still common alongside it)
            # often signs off with its own grid square in plain text ("de
            # W1AW FN31pr"). `find_grid_in_text` is a deliberately
            # conservative heuristic (see its own docstring); a real APRS
            # position above is never second-guessed by it. This is what
            # lets the Heard pane's Distance/Bearing columns work for a
            # plain packet node too, not just APRS stations.
            found = find_grid_in_text(sanitize(packet.info, keep_newlines=False))
            if found is not None:
                _grid, lat, lon = found
                self.heard.set_position(str(packet.source), lat, lon)

        # A message-relay service (WHO-IS, WXBOT, and message traffic
        # generally crossing between RF and APRS-IS) commonly has no RF
        # presence of its own: its ack and its reply reach us only as a
        # third-party relay wrapping the real message, with the relay
        # station (an igate) as the *outer* frame's source. Unwrapping it
        # here is what `AprsPane.note_incoming`'s own docstring already
        # promises -- "every message packet on the channel is recorded,
        # third-party traffic included" -- but nothing before this actually
        # did it: treating a wrapped ack/reply as "not a message" left an
        # answered query stuck retrying forever, even though it decoded
        # fine for the "All" tab's raw display below. `tp.source` (plain
        # text, not `tp.inner.source`) is used as the correspondent identity
        # for the same reason `format_packet` uses it for display -- the
        # inner `AprsPacket.source` a third-party header without a valid
        # AX.25 callsign (e.g. "WHO-IS") coerces to is the `NOCALL`
        # placeholder, which would file the reply under the wrong contact.
        message_packet, message_source = packet, str(packet.source)
        if (
            packet.kind == "third-party"
            and isinstance(packet.data, aprs.ThirdParty)
            and packet.data.inner.kind == "message"
            and isinstance(packet.data.inner.data, aprs.Message)
        ):
            message_packet, message_source = packet.data.inner, packet.data.source

        if message_packet.kind == "message" and isinstance(message_packet.data, aprs.Message):
            msg = message_packet.data
            source = message_source
            if aprs.is_bulletin_addressee(msg.addressee):
                self._note_aprs_bulletin(source, msg.addressee, msg.text)
                return
            if not (msg.is_ack or msg.is_rej or msg.is_telemetry_definition):
                to_me = aprs_message_matches(
                    msg.addressee,
                    self.config.mycall,
                    self.config.mycall_aliases,
                    filter_by_ssid=self.config.aprs.filter_by_ssid,
                    active_identity=self._active_aprs_identity(),
                )
                duplicate = self._aprs_message_deduplicator.is_duplicate(
                    source, msg.addressee, msg.text, msg.number
                )
                if to_me:
                    if getattr(self.config, "aprs_auto_ack", True) and msg.number:
                        # A sender may be retrying precisely because our first
                        # ack was lost. A duplicate belongs only once in the
                        # transcript, but it still deserves another ack.
                        await self._send_aprs_ack(source, msg.number, port)
                if duplicate:
                    return
                self.aprs_conversations.record_incoming(source, msg.text, number=msg.number)
                # `to_me` decides whether this opens a tab and raises an
                # unread marker, or is only recorded. Every message packet is
                # recorded either way -- see `AprsPane.note_incoming`.
                self._note_aprs_incoming(source, to_me=to_me)
            elif msg.is_ack and msg.number:
                # Flips `MessageEntry.acked` in the persisted log, which the
                # pane's retry loop also reads off its own timer.
                self.aprs_conversations.mark_acked(source, msg.number)
                # Repaint now rather than waiting up to a retry interval for
                # the pane's timer: an ack is the answer to "did that get
                # through?", and an operator watching the screen for it
                # should not see a stale "sent" for another ten seconds.
                self._repaint_aprs_conversation()
        elif packet.kind != "unparsed":
            # Everything that is not a person-to-person message (or an
            # undecodable frame the Monitor pane already shows raw) --
            # position, weather, status, telemetry readings, objects/items,
            # third-party relays. `ConversationStore` is chat history with a
            # correspondent and stays that way; these have no correspondent,
            # so they are shown in the "All" tab only, in memory only, via
            # `AprsPane.note_packet` -- never written to
            # `kissterm/aprs_conversations.py`'s persisted JSON. One decode
            # (`aprs.parse_packet`, already run above) feeds both this and
            # the heard-table enrichment above; `format_packet` is the one
            # place that turns any `AprsPacket` into a line, so a new packet
            # kind only ever needs a case added there (AGENTS.md sec. 2b).
            self._note_aprs_packet(packet)

        decision = evaluate_packet(
            packet,
            self.config.mycall,
            self.config.mycall_aliases,
            filter_by_ssid=self.config.aprs.filter_by_ssid,
            active_identity=self._active_aprs_identity(),
        )
        if decision is None:
            return
        if not self._aprs_notify_cooldown.allow(decision.key, urgent=decision.urgent):
            return
        self.notify(
            f"{decision.title}: {decision.body}" if decision.body else decision.title,
            severity="warning" if decision.urgent else "information",
            timeout=15 if decision.urgent else 5,
        )
        self._notify_aprs_desktop(decision.title, decision.body, urgent=decision.urgent)

    @work
    async def _notify_aprs_desktop(self, title: str, body: str, *, urgent: bool) -> None:
        await desktop_notify.notify_any(title, body, sound="request" if urgent else "none")

    def _repaint_aprs_conversation(self) -> None:
        """Ask the APRS pane to redraw the conversation on screen, if it is
        mounted. Tolerates it not being there -- this runs from the frame
        fan-out, which outlives the widget tree (same reasoning as
        `_to_terminal`)."""
        for pane in self._base_query(AprsPane):
            pane.refresh_conversation()
            return

    def _note_aprs_incoming(self, callsign: str, *, to_me: bool) -> None:
        """Tell the APRS pane a message arrived, and whether it was for us.

        Repaints as a side effect, so it replaces rather than accompanies
        `_repaint_aprs_conversation` on the incoming-message path. Tolerates
        the pane not being mounted, for the same reason that one does.
        """
        for pane in self._base_query(AprsPane):
            pane.note_incoming(callsign, to_me=to_me)
            return

    def _note_aprs_packet(self, packet: aprs.AprsPacket) -> None:
        """Forward one formatted non-message APRS line (a position, weather
        report, telemetry reading, status, or object/item) to the APRS
        pane's "All" tab. Tolerates the pane not being mounted, for the same
        reason `_note_aprs_incoming` does.
        """
        for pane in self._base_query(AprsPane):
            pane.note_packet(aprs.format_packet(packet), time.time(), packet)
            return

    def _note_aprs_bulletin(self, source: str, addressee: str, text: str) -> None:
        """Forward one BLNn/ANn channel announcement to the APRS pane."""
        for pane in self._base_query(AprsPane):
            pane.note_bulletin(source, addressee, text, time.time())
            return

    def _purge_stale_synthetic_messages(self) -> None:
        """One-time cleanup for `self.aprs_conversations` right after
        loading it: drop already-persisted lines that were never something
        a human (or a correspondent) typed, from a build that recorded them
        before the check that now excludes them existed.

        Two shapes, both fixed by a real-world report rather than found in
        review, so a history file written before either fix still carries
        them forever otherwise:

        * An incoming **telemetry-definition** line (`PARM.`/`UNIT.`/
          `EQNS.`/`BITS.`) -- excluded since 2026-09-10
          (`aprs.is_telemetry_definition_text`).
        * An outgoing **auto-ack recorded as a chat line** (`"ack407"`,
          with `number=None`) -- excluded since 2026-09-11; an incoming ack
          was never filed as a message either (`_on_aprs_frame` routes
          `msg.is_ack` to `mark_acked`, not `record_incoming`), so this
          brought the outgoing side in line with that rule.

        Runs on every launch; once purged there is nothing left to find, so
        this is cheap after the first run.
        """
        ack_number_re = re.compile(r"^ack[A-Za-z0-9]{1,5}$")
        changed = False
        for convo in self.aprs_conversations.conversations.values():
            kept = [
                m
                for m in convo.messages
                if not (m.direction == "in" and aprs.is_telemetry_definition_text(m.text))
                and not (
                    m.direction == "out" and m.number is None and ack_number_re.match(m.text)
                )
            ]
            if len(kept) != len(convo.messages):
                convo.messages = kept
                changed = True
        if changed:
            self.aprs_conversations.save()

    async def _send_aprs_ack(self, addressee: str, number: str, port: int) -> None:
        """Auto-ack an APRS message addressed to us -- see
        `Config.aprs_auto_ack`'s docstring for why this defaults on and is
        still just as gated by the transmit switch as everything else this
        app sends. Every auto-ack is written to the terminal pane, the same
        rule a beacon or a connect-script line follows: a station that
        transmits without the operator being able to see that it did is
        exactly what that rule exists to prevent.

        Transmits from `Config.aprs.source_for` -- the SAME identity every
        other piece of APRS traffic this station originates uses -- and
        deliberately NOT from whatever text the sender happened to put in
        the addressee field. A station has one consistent on-air identity;
        whether a message not addressed to that exact identity still
        counts as "for me" at all is `aprs_message_matches`'s decision
        (`_on_aprs_frame` above, gated on `Config.aprs.filter_by_ssid`) --
        that is the one place any SSID forgiveness belongs, and by
        default (as of `filter_by_ssid`'s introduction) there is none: an
        exact match is required, matching how a real APRS client's own
        message-tracking behaves. An earlier version of this method
        instead transmitted the ack under `Message.addressee` verbatim,
        reasoning that a peer's own message-tracking must be matching the ack's
        source callsign+SSID against exactly what it addressed. That
        reasoning does not hold: it made kissterm transmit under an
        identity (an arbitrary SSID, or none) that is not actually this
        station's configured identity, which is the exact "callsign is a
        claim" hazard AGENTS.md warns about elsewhere, and it made the ack
        path the only outgoing APRS traffic on a different identity than
        everything else this station sends. Do not reintroduce that.

        A closed gate is reported, not just silently obeyed. Found live: a
        station whose transmit gate had not been re-armed since its last
        launch (closed by default -- see the transmit-gate rules) received
        four retries of the same message over several minutes with no
        visible sign anything was wrong; the sender's own delivery tracker
        eventually gave up, and the only way to have known why was to read
        this app's debug log after the fact. "A failure the operator
        cannot diagnose is a bug" applies here exactly as much as it does
        to a dropped frame -- the difference from a beacon's version of the
        same check is that nobody just pressed a key to trigger this, so
        there is no natural moment for the warning except the message
        itself arriving. `_aprs_ack_blocked_cooldown` keeps a sender's own
        retries (every 30-90 seconds, typically) from repainting the same
        toast on top of itself.
        """
        if self.station is None:
            return
        # `send_frame` drops a gated frame silently and does not say so --
        # that is the whole point of TX BLOCKED not being an exception (see
        # its docstring). Checked here, the same way `Beaconer.problem()`
        # checks it, so a closed gate cannot make this method log or record
        # an ack as sent when nothing went out. Never report a suppressed
        # transmission as a sent one.
        gate = getattr(self.station.transport, "gate", None)
        if gate is not None and not gate.enabled:
            if self._aprs_ack_blocked_cooldown.allow((addressee, number)):
                self.notify(
                    f"{addressee} sent a message that needs an acknowledgment, but "
                    "Transmit is OFF, so nothing was sent back. Press Ctrl+T to turn "
                    "Transmit on.",
                    severity="warning",
                    timeout=10,
                )
                self._to_terminal(
                    self._active_key(),
                    "log",
                    f"\n*** Message from {addressee} needs an ack, but Transmit is OFF "
                    "-- press Ctrl+T\n",
                )
            return
        source = self.config.aprs.source_for(str(self.station.mycall))
        try:
            payload = aprs.ack(addressee, number)
            dest = AX25Address.parse("APRS")
            outframe = aprs.beacon_frame(source, dest, (), payload)
            await self.station.transport.send_frame(outframe, port)
        except Exception as exc:  # never let an ack failure disturb the link
            log.debug("APRS auto-ack to %s not sent: %s", addressee, exc)
            return
        # Deliberately NOT `self.aprs_conversations.record_outgoing(...)`.
        # An incoming ack is never filed as a chat line either (`_on_
        # aprs_frame` routes `msg.is_ack` to `mark_acked`, not `record_
        # incoming`) -- a protocol ack is not conversation content, and
        # showing "ack407" as if it were a message someone typed answered
        # nothing an operator asked and only invited "what does this mean?"
        # The terminal-pane line below is the transmission record; the gate
        # rule above (never claim a suppressed send went out) covers it the
        # same way a real message would be covered.
        self._to_terminal(self._active_key(), "log", f"\n*** Auto-ack sent to {addressee} (msg {number})\n")

    async def _send_aprs_message(
        self, addressee: str, text: str, number: str | None, *, port: int = 0, retry: bool = False
    ) -> bool:
        """Encode and transmit one APRS message frame -- the shared send
        primitive for both a fresh send from the APRS pane and a retry of
        one still awaiting an ack. Returns whether it actually went out.

        Deliberately does NOT touch `self.aprs_conversations` or any
        pending-ack tracking itself: a retry resending the exact same
        message must not create a second history entry, so whether this
        call is "the first send" (record it, start tracking) or "a retry"
        (already recorded, already tracked) is a decision only the caller
        (`kissterm.ui.aprs_pane.AprsPane`) has enough context to make.
        """
        if self.station is None:
            return False
        gate = getattr(self.station.transport, "gate", None)
        if gate is not None and not gate.enabled:
            # Same rule as `_send_aprs_ack`: never log or claim a send that
            # the gate silently dropped.
            return False
        try:
            payload = aprs.message(addressee, text, number=number)
            dest = AX25Address.parse("APRS")
            # Same APRS-only SSID override the position beacon uses, so a
            # message and a beacon go out under one identity rather than two.
            outframe = aprs.beacon_frame(
                self.config.aprs.source_for(str(self.station.mycall)), dest, (), payload
            )
            await self.station.transport.send_frame(outframe, port)
        except Exception as exc:
            log.debug("APRS message to %s not sent: %s", addressee, exc)
            return False
        verb = "Resent" if retry else "Sent"
        kind = "bulletin" if number is None else f"message {number}"
        self._to_terminal(self._active_key(), "log", f"\n*** {verb} APRS {kind} to {addressee}\n")
        return True

    async def _send_aprs_object(self, request: AprsObjectRequest) -> bool:
        """Encode and transmit one deliberately composed APRS object report."""
        if self.station is None:
            return False
        gate = getattr(self.station.transport, "gate", None)
        if gate is not None and not gate.enabled:
            return False
        try:
            target = parse_path(f"APRS {self.config.aprs.path}".strip())
            timestamp = datetime.now(UTC).strftime("%d%H%Mz")
            payload = aprs.object_report(
                request.name, request.alive, timestamp, request.latitude,
                request.longitude, request.symbol[0], request.symbol[1], request.comment,
            )
            outframe = aprs.beacon_frame(
                self.config.aprs.source_for(str(self.station.mycall)),
                target.destination, target.repeaters, payload,
            )
            await self.station.transport.send_frame(outframe, 0)
        except Exception as exc:
            log.debug("APRS object %s not sent: %s", request.name, exc)
            return False
        state = "live" if request.alive else "killed"
        self._to_terminal(self._active_key(), "log", f"\n*** Sent {state} APRS object {request.name.strip()}\n")
        return True

    def _session_key(self, peer, port: int = 0) -> str:
        """The identity a Terminal-pane tab is keyed on. Plain callsign for
        the overwhelmingly common `port=0` case, so tab labels stay exactly
        what an operator expects; the port is only appended when it would
        otherwise collide (two different ports genuinely can reach two
        different stations sharing a displayed callsign+SSID)."""
        return str(peer) if port == 0 else f"{peer}:{port}"

    def _active_key(self) -> str:
        for pane in self._base_query(TerminalPane):
            return pane.active_session_key
        return ""

    @property
    def link(self):
        """The link of whichever Terminal-pane tab is on screen right now,
        or None -- see the module docstring's `self.link` paragraph. Never
        read this from a callback bound to a SPECIFIC link (`_on_link_data`
        and friends thread their session's key through explicitly instead);
        it is only correct for "what is the operator looking at".
        """
        session = self._sessions.get(self._active_key())
        return session.link if session is not None else None

    @property
    def reference(self) -> CommandReference:
        """Shipped command reference for whichever session is active.
        Populated by `_sniff_node` sniffing the banner -- never by asking
        the node, which costs real airtime (see kissterm/nodes/__init__.py).
        """
        session = self._sessions.get(self._active_key())
        return session.reference if session is not None else CommandReference()

    @reference.setter
    def reference(self, value: CommandReference) -> None:
        session = self._sessions.get(self._active_key())
        if session is not None:
            session.reference = value

    @property
    def current_node(self) -> str:
        """Who the ACTIVE tab is logically talking to -- the link's own peer
        until a hop through it is confirmed, that node afterwards. Same
        "whichever tab is on screen" scoping as `link` and `reference`
        above, and the same warning applies: a callback bound to a specific
        session must read `_TerminalSession.current_node` through its own
        key instead.
        """
        session = self._sessions.get(self._active_key())
        return session.current_node if session is not None else ""

    @property
    def transcript(self) -> SessionLog | None:
        """Transcript file for whichever session is active, or None."""
        session = self._sessions.get(self._active_key())
        return session.transcript if session is not None else None

    @transcript.setter
    def transcript(self, value: SessionLog | None) -> None:
        session = self._sessions.get(self._active_key())
        if session is not None:
            session.transcript = value

    def _on_incoming_link(self, link) -> None:
        pane = self.query_one(TerminalPane)
        had_none = pane.session_count == 0
        key = self._bind_link(link, activate=had_none)
        if not had_none:
            # Opened a tab, did not steal the view -- see the module and
            # terminal_pane.py docstrings' "never steal the view" rule.
            pane.mark_unread(key)
        self._to_terminal(key, "log", f"\n*** Incoming connection from {link.peer}\n")
        if not self.gate.enabled:
            # The UA never went out, so the caller is talking to nobody. Say
            # so: "somebody called and you could not answer" is exactly the
            # thing an operator wants to find in the scrollback later.
            self._to_terminal(
                key,
                "log",
                f"*** Could not answer {link.peer} -- transmit is disabled (Ctrl+T)\n",
            )
            self.notify(
                f"{link.peer} called, but transmit is disabled.", severity="warning"
            )
        self._send_banner(link)
        self.notify(f"Connection from {link.peer}", severity="information")

    @work
    async def _send_banner(self, link) -> None:
        """Greet a caller, so the link does not open into silence.

        Without this a station that connects gets a UA and then nothing, and
        has no way to tell a working link from a broken one -- worse than a
        clean refusal. BPQ32 calls this CTEXT; the default is deliberately
        short, because every byte is airtime.

        Guarded on `accept_incoming` even though we only reach here after
        accepting: this is a transmission, and anything that transmits gets
        checked against the operator's explicit opt-in at the moment it
        happens, not only where the connection was accepted.
        """
        banner = (getattr(self.config, "connect_banner", "") or "").strip()
        if not banner or not getattr(self.config, "accept_incoming", False):
            return
        try:
            await link.send(banner.encode("latin-1", "replace") + b"\r")
        except Exception:
            log.exception("could not send connect banner to %s", link.peer)

    def _bind_link(self, link, session_key: str | None = None, *, activate: bool = True) -> str:
        """Wire a connected link into its `_TerminalSession` bookkeeping
        (transcript, node reference, reply-watch) and its Terminal-pane tab.

        `session_key` is computed from `link.peer`/`link.port` when not
        given -- every caller except `action_connect` needs exactly that,
        since that one must know the key before the link exists (to open
        the tab and show "Connecting..." first, and to let Ctrl+D find a
        still-connecting attempt). `activate` lets `_on_incoming_link` open
        a tab WITHOUT stealing the view when another session is already on
        screen -- see the module and terminal_pane.py docstrings.

        A fresh `_TerminalSession()` is what resets the node reference and
        detect buffer for a new conversation -- no separate reset needed,
        unlike the single-session version this replaced. Any reply timer or
        transcript left over from a PRIOR binding of this same key (a
        reconnect to a peer whose tab is still open) is torn down first, so
        neither leaks past the object that owned it.

        The one thing NOT reset from scratch: `harvest_commands` cached
        commands for this exact peer are re-applied immediately, so a
        reconnect to a node harvested before never re-asks and never
        re-spends the airtime -- see `HarvestedCommands.for_callsign`.
        """
        key = session_key if session_key is not None else self._session_key(link.peer, link.port)
        self._cancel_reply_timer(key)
        self._cancel_hop_watch(key)
        self._close_transcript(key)
        session = _TerminalSession(link=link)
        # A fresh connection is, by definition, talking to the link's own
        # peer -- any logical peer a previous hop chain established on this
        # key belonged to the session that just ended. See
        # `_TerminalSession.current_node` and `_commit_hop`.
        session.current_node = str(link.peer)
        # Apply anything harvested from THIS peer on a past connect --
        # cached forever, per AGENTS.md's opt-in-harvesting rule, so a
        # reconnect never re-asks and never re-spends the airtime.
        cached = self._harvested.records_for_callsign(str(link.peer))
        if cached:
            session.reference = CommandReference(
                learned=tuple(
                    Command(name=command.name, confidence="learned", context=command.context)
                    for command in cached
                )
            )
        self._sessions[key] = session
        self.query_one(TerminalPane).open_tab(key, activate=activate)
        self._start_transcript(key, link)
        link.on_data.append(lambda data: self._on_link_data(key, data))
        link.on_state.append(lambda state: self._on_link_state(key, state))
        link.on_error.append(lambda why: self._note(key, f"\n*** {why}\n"))
        self._to_terminal(key, "set_placeholder", f"connected to {link.peer}")
        return key

    def _transcript_directory(self) -> Path:
        """Where transcripts are read from AND written to.

        One method so `_start_transcript` (writing) and
        `action_show_transcripts` (reading them back later) can never drift
        onto two different ideas of "the log directory".
        """
        from ..config import log_path

        return Path(self.config.log_dir) if self.config.log_dir else log_path()

    # ------------------------------------------------------------------
    # Transcript
    # ------------------------------------------------------------------
    def _start_transcript(self, session_key: str, link) -> None:
        """Open a transcript for `session_key`, and say where it is, on ITS
        tab -- not necessarily the one on screen.

        The path goes on screen -- as a fixed header above the scrollback,
        not a line inside it (`TerminalPane.set_transcript_note`) -- because a
        file appearing on disk without the operator being told is a surprise,
        and this is on by default. A header survives Ctrl+L and scrolling;
        a log line would not stay findable through either. A transcript that
        cannot be opened is reported once, as a log line since there is no
        path to keep showing, and then forgotten about -- see `session_log.py`
        on why a failed log must never be allowed to disturb a live link.
        """
        self._close_transcript(session_key)
        if not getattr(self.config, "log_sessions", True):
            return
        directory = self._transcript_directory()
        # `self.station` is None on the session-transport tier (Telnet, SSH,
        # VARA, Mercury, kernel AX.25) -- there is no AX25Station to read an
        # operating callsign off, but the operator's own callsign is still
        # `config.mycall` regardless of which tier is active.
        mycall = str(self.station.mycall) if self.station is not None else str(
            getattr(self.config, "mycall", "") or ""
        )
        transcript = SessionLog(directory, mycall, str(link.peer))
        if not transcript.open():
            self._to_terminal(session_key, "log", f"\n*** No transcript: {transcript.failed}\n")
            return
        session = self._sessions.get(session_key)
        if session is not None:
            session.transcript = transcript
        self._to_terminal(session_key, "set_transcript_note", f"Transcript: {transcript.path}")

    def _close_transcript(self, session_key: str) -> None:
        session = self._sessions.get(session_key)
        if session is not None and session.transcript is not None:
            session.transcript.close()
            session.transcript = None
            self._to_terminal(session_key, "set_transcript_note", "")

    def _close_all_transcripts(self) -> None:
        """Every session's, on shutdown -- see `on_unmount`."""
        for key in list(self._sessions):
            self._close_transcript(key)

    def _note(self, session_key: str, text: str) -> None:
        """A local note for one session: to its tab, and to its transcript."""
        self._to_terminal(session_key, "log", text)
        session = self._sessions.get(session_key)
        if session is not None and session.transcript is not None:
            session.transcript.note(text.strip().lstrip("* "))

    def log_sent(self, session_key: str, text: str, *, watch_hop: bool = True) -> None:
        """Record a line the operator transmitted on `session_key`. Called
        from `TerminalPane.send_line` with `active_session_key` -- the
        operator can only ever type into whichever tab is on screen -- and
        from `_hop_to`, which sends its "C <node>" the same way.

        The pane echoes it to the scrollback itself; this is the durable
        half -- and this also (re)arms that session's reply-watch timer
        (`_note_if_no_reply`), cancelling any previous one so it is the
        LAST line typed that starts the clock, not the first.

        Also where a HAND-TYPED hop to another node gets noticed.
        `_sniff_node` locks onto the first family it identifies and never
        looks again -- deliberately, so ordinary mid-conversation text
        cannot trigger a false match (AGENTS.md: "a wrong family shown
        confidently is worse than 'unknown node'"). But a real report found
        the gap that leaves: connect to a BPQ32 node, harvest it, then type
        "C <other-node>" to hop onward through it -- kissterm's own AX.25
        link never changes (it is still connected to the SAME peer; the hop
        happens entirely at the far node's application layer), so nothing
        else ever tells this session it might now be talking to a different
        kind of system.

        **The reset waits for the hop to be CONFIRMED, and that ordering is
        the whole point.** The first version of this reset detection the
        instant the command went out, which is wrong in the case that
        actually matters on a marginal path: a hop that answers BUSY, or
        that nothing answers at all, leaves the operator still talking to
        the SAME node they were already correctly identified against -- and
        blanking the identification there turns a working command reference
        and working autocomplete into "unknown node" for a node that never
        went anywhere. Caught in live testing against a real BPQ32 node.
        So a hop command starts a background watch
        (`_await_hop_confirmation`) and only a genuine CONNECTED reply
        reaches `_commit_hop`; a refusal or a timeout touches nothing at
        all. No note is written for a failed hop -- the node's own
        BUSY/FAILED text is already in the scrollback, and saying it again
        in kissterm's voice is the duplication AGENTS.md's "one place for
        each fact" rule argues against.

        This stays keyed on an OPERATOR-INITIATED command, the same trust
        model `_arm_for` uses for "confirmed and targeted" actions -- not on
        watching every byte forever, which would reopen the false-match risk
        `_sniff_node`'s lock exists to close.

        `watch_hop=False` is for `_hop_to` alone: the scripted hop chain
        already awaits `_await_hop_confirmation` itself and calls
        `_commit_hop` from there, so a second watcher started here would be
        two subscribers racing on the same `link.on_data` bytes for the same
        hop -- able to commit twice, and able to disagree.
        """
        session = self._sessions.get(session_key)
        if session is None:
            return
        if session.transcript is not None:
            session.transcript.sent(text)
        if watch_hop:
            self._watch_typed_hop(session_key, text)
        self._cancel_reply_timer(session_key)
        if session.link is not None and session.link.connected:
            session.reply_timer = self.set_timer(
                REPLY_WAIT_SECONDS, lambda: self._note_if_no_reply(session_key)
            )

    # ------------------------------------------------------------------
    # Hopping onward through a node, at the far end's application layer
    # ------------------------------------------------------------------
    def _watch_typed_hop(self, session_key: str, text: str) -> None:
        """If `text` is a connect-onward command with a target, start (or
        restart) the background watch that will commit the hop if it comes
        up. Called from `log_sent`; see its docstring for the ordering
        argument this exists to enforce.

        A bare "C" with nothing after it names no node to hop to, so there
        is nothing to confirm and nothing to reset -- it is left alone
        rather than being treated as a hop to the empty string.

        The target is the LAST word, not the first after the command:
        bpq32.toml documents two forms, "C <call>" and "C <port> <call>",
        and taking the first word after "C" would read a port-qualified hop
        like "C 2 JNOSNODE" as a hop to a node literally named "2" -- wrong
        in a way that would then confirm against the wrong node's traffic
        and cache a real harvest under a callsign that does not exist.
        """
        parts = text.strip().split(None, 1)
        if len(parts) < 2 or parts[0].upper() not in HOP_COMMAND_WORDS:
            return
        args = parts[1].strip().split()
        target = args[-1] if args else ""
        if not target:
            return
        session = self._sessions.get(session_key)
        if session is None or session.link is None:
            return
        # A second hop typed before the first resolved replaces it. Leaving
        # the old watcher subscribed would let it match the NEW hop's
        # traffic -- an unrelated node's CONNECTED committing the previous
        # target -- which is exactly the mislabelling this whole change is
        # about.
        self._cancel_hop_watch(session_key)
        # Subscribed HERE, synchronously, not inside the task: a task does
        # not start running until the event loop next gets a turn, and the
        # node's reply is fanned out to `link.on_data` the moment it
        # arrives. Anything received in that window would be invisible to a
        # watcher that had not subscribed yet, and the hop would never be
        # confirmed at all. See `_HopConfirmation`.
        # The link is captured now, not read back off the session later: a
        # reconnect on this key installs a whole new `_TerminalSession`, and
        # this watch must stay attached to the link it was started on (that
        # `_bind_link` cancels it first is belt and braces, not the reason).
        link = session.link
        watch = _HopConfirmation(link, target)

        async def _run() -> None:
            try:
                ok, _detail = await self._await_hop_confirmation(
                    link, target, watch=watch
                )
                if ok:
                    self._commit_hop(session_key, target)
            finally:
                current = self._sessions.get(session_key)
                if current is not None and current.hop_watch_task is task:
                    current.hop_watch_task = None

        task = asyncio.get_event_loop().create_task(
            _run(), name=f"hop-watch:{session_key}:{target}"
        )
        # Unsubscribe on EVERY ending, including a task cancelled before it
        # ever ran -- that one never enters `_run`'s body, so its `finally`
        # never fires and the subscriber would be left on the fan-out
        # matching unrelated traffic for the rest of the session. A done
        # callback runs in both cases; `_HopConfirmation.stop` is idempotent.
        task.add_done_callback(lambda _task: watch.stop())
        session.hop_watch_task = task

    def _cancel_hop_watch(self, session_key: str) -> None:
        session = self._sessions.get(session_key)
        if session is not None and session.hop_watch_task is not None:
            session.hop_watch_task.cancel()
            session.hop_watch_task = None

    def _cancel_all_hop_watches(self) -> None:
        """Every session's, on shutdown -- see `on_unmount`. A watcher left
        running past the UI would be a task holding a reference to a link
        and a session that are both on their way out."""
        for key in list(self._sessions):
            self._cancel_hop_watch(key)

    def _commit_hop(self, session_key: str, node: str) -> None:
        """Apply a CONFIRMED successful hop to `node`: from here on this
        session is logically talking to a different station than its AX.25
        link's fixed peer.

        The ONLY place a hop's success is applied, for both the scripted
        chain (`_hop_to`) and a hand-typed one (`log_sent`'s watch), so
        there is one answer to "what changes when a hop works" rather than
        two copies free to drift apart.

        Re-arms node detection (a fresh `CommandReference` and an empty
        detect buffer) so the new node's banner gets a clean, un-mixed read
        instead of the previous node's family and learned commands sticking
        around -- and re-applies anything already harvested from `node`,
        mirroring `_bind_link`'s own cache-reapply-on-connect for exactly
        the same reason: a hop BACK to a node harvested before must not
        re-spend the airtime AGENTS.md's opt-in-harvesting rule says is
        paid once and cached forever.

        Never call this for a hop that refused or timed out. The operator is
        still talking to whatever they were talking to before the attempt,
        and blanking a correct identification for a hop that never happened
        is the regression this method's ordering exists to prevent.
        """
        session = self._sessions.get(session_key)
        if session is None:
            return
        session.current_node = node
        cached = self._harvested.records_for_callsign(node)
        if cached:
            session.reference = CommandReference(
                learned=tuple(
                    Command(name=command.name, confidence="learned", context=command.context)
                    for command in cached
                )
            )
        else:
            session.reference = CommandReference()
        session.detect_buffer = ""
        self._refresh_status()

    def _base_query(self, selector):
        """Query the app's own screen, not whatever modal is on top of it.

        Two failure modes this exists to absorb, both of which produced real
        crashes:

        * `App.query_one` resolves against `self.screen`, the TOP of the screen
          stack. With a modal open, any periodic refresh reaching for a pane by
          id raises `NoMatches` -- so leaving the connect or callsign dialog
          open for more than a second crashed the status refresh. The panes are
          still visible behind a modal and still need updating, so addressing
          the base screen is right; skipping the refresh is not.
        * During shutdown the stack empties and even reading `self.screen`
          raises `ScreenStackError`. Returning an empty result set lets
          callbacks that outlive the UI simply do nothing.
        """
        stack = self.screen_stack
        if not stack:
            return ()
        return stack[0].query(selector)

    def _to_terminal(self, session_key: str, method: str, *args) -> None:
        """Call a per-session `TerminalPane` method, tolerating the pane not
        existing.

        A link outlives the UI. On shutdown `__main__` exits the app first and
        *then* calls `station.close()`, which fires every link's state callback
        -- at which point the widget tree is gone and a bare `query_one` raises
        `NoMatches` out of a callback nothing is catching. That turned a clean
        quit with a live link into a traceback. `query()` returns an empty
        result set instead of raising, so a torn-down UI is simply nothing to
        write to.

        `session_key` names WHICH tab the write belongs to -- it is passed
        through to `pane.<method>`, never resolved to "the active one" here,
        because half of this method's callers are per-link callbacks that
        must stay correct for a session sitting in the background. Callers
        that genuinely mean "wherever the operator is looking" (a global
        status note -- transmit toggled, a device unplugged) pass
        `self._active_key()` explicitly, same as any other caller.
        """
        for pane in self._base_query(TerminalPane):
            getattr(pane, method)(session_key, *args)
            return

    def _on_link_data(self, session_key: str, data: bytes) -> None:
        if session_key in self._transfer_active:
            return
        # Any data back answers the "did they get it" question the reply
        # timer exists for -- see `_note_if_no_reply`.
        self._cancel_reply_timer(session_key)
        self._to_terminal(session_key, "write_incoming", data)
        session = self._sessions.get(session_key)
        if session is not None and session.transcript is not None:
            # Sanitized, never raw. A transcript is read later by a person in
            # a terminal, so wire bytes with escape sequences in them would
            # reintroduce exactly the problem the pane's filter solves --
            # `cat` on the file would run them.
            session.transcript.received(sanitize(data))
        self._sniff_node(session_key, data)
        self._capture_harvest(session_key, data)

    def _sniff_node(self, session_key: str, data: bytes) -> None:
        """Identify the node family from what it already sent us, on
        `session_key`'s own reference -- never `self.reference`, which
        means "whichever tab is active" and this callback does not know
        that it is.

        Passive on purpose. Asking a node for its command list with `?` costs
        roughly twenty seconds of a 1200-baud channel for a couple of
        kilobytes, and over a minute for a verbose one -- airtime nobody else
        can use. The banner and prompt arrive anyway, so they are free.

        Only the first couple of kilobytes are examined; a node identifies
        itself in its greeting or not at all, and scanning the whole session
        forever would let ordinary message text trigger a false match.
        """
        session = self._sessions.get(session_key)
        if session is None or session.reference.family is not None or len(session.detect_buffer) > 2048:
            return
        from ..monitor import sanitize

        session.detect_buffer += sanitize(data)
        family = identify_family(session.detect_buffer)
        if family is None:
            return
        # Set the `family` field in place rather than replacing the whole
        # `CommandReference` -- a wholesale replacement here would silently
        # drop any `learned` commands `_bind_link` already pre-populated
        # from a past harvest of this same peer.
        #
        # No inline terminal note here -- the family name is shown in the
        # status bar instead (`_refresh_status`), which already carries the
        # peer callsign and link state right next to it. Announcing it a
        # second time in the scrollback is the same duplication AGENTS.md's
        # "one place for each fact" rule already covers for the tab label
        # vs. the footer; the operator asked for this one to move the same
        # way.
        session.reference.family = family
        self._refresh_status()

    def _capture_harvest(self, session_key: str, data: bytes) -> None:
        """Feed one session's harvest capture window, when one is open.

        A no-op the rest of the time (`harvest_buffer is None` is the
        overwhelming common case -- harvesting is opt-in and rare), so this
        adds no cost to ordinary traffic. Bounded by `HARVEST_CAPTURE_LIMIT`
        regardless of how much the node actually sends back.
        """
        session = self._sessions.get(session_key)
        if session is None or session.harvest_buffer is None:
            return
        session.harvest_buffer += sanitize(data)
        if len(session.harvest_buffer) > HARVEST_CAPTURE_LIMIT:
            session.harvest_buffer = session.harvest_buffer[:HARVEST_CAPTURE_LIMIT]

    async def harvest_commands(
        self, session_key: str, *, context: str = "node"
    ) -> tuple[str, ...]:
        """Ask the node's own `?` for its command list, once, and cache
        whatever comes back forever under its callsign.

        AGENTS.md's opt-in-harvesting rule in full: ask before spending the
        airtime (that confirm step is `HarvestConfirmScreen`, already done
        by the time this runs), then cache per node callsign forever so it
        is never paid twice -- `_bind_link` is the other half of that,
        re-applying the cache on every later connect to the same peer with
        no prompt and no airtime spent.

        Reuses `link.send` -- the same tx-gated path every other
        transmission in this app goes through -- rather than a second one;
        AGENTS.md is explicit that a new send path around the transmit gate
        is the one thing a backend or feature must never do. Returns the
        NEWLY learned names (empty if there is no connected link, the gate
        is closed, or nothing recognisable came back).

        The wait is `HARVEST_MAX_WAIT_SECONDS` at most, but exits early
        after `HARVEST_QUIET_SECONDS` of silence once something has actually
        arrived -- see that constant's docstring for why a fixed short sleep
        (this method's original implementation) is a real bug, not just
        overcautious, on anything but a fast, lossless link.
        """
        session = self._sessions.get(session_key)
        if session is None or session.link is None or not session.link.connected:
            return ()
        if not self.gate.enabled:
            self.notify(DISABLED_MESSAGE, severity="warning")
            return ()
        link = session.link
        # Do not let a second, unanswered harvest make the Ctrl+R screen
        # present the previous request's reply as though it were current.
        session.last_harvest_text = ""
        session.harvest_buffer = ""
        try:
            await link.send(b"?\r")
        except Exception:
            log.exception("could not send harvest request to %s", link.peer)
            session.harvest_buffer = None
            return ()
        # Recorded exactly like any other automated send (`_run_connect_
        # script`'s pattern) -- the operator sees it in the terminal and it
        # lands in the transcript, rather than harvesting being the one send
        # path in this app that leaves no record of what went out.
        self._to_terminal(session_key, "log", "?\n")
        self.log_sent(session_key, "?")
        self._to_terminal(
            session_key, "log", "\n*** Asked the node for its command list...\n"
        )
        waited = 0.0
        quiet = 0.0
        last_length = 0
        while waited < HARVEST_MAX_WAIT_SECONDS:
            await asyncio.sleep(HARVEST_POLL_INTERVAL)
            waited += HARVEST_POLL_INTERVAL
            buffer = session.harvest_buffer or ""
            if len(buffer) > last_length:
                # Still arriving -- reset the quiet clock. Only a buffer
                # that has stopped GROWING counts toward the quiet exit;
                # counting mere non-emptiness would end the capture after
                # exactly `HARVEST_QUIET_SECONDS` regardless of whether the
                # node was still actively sending more.
                last_length = len(buffer)
                quiet = 0.0
            elif buffer:
                quiet += HARVEST_POLL_INTERVAL
                if quiet >= HARVEST_QUIET_SECONDS:
                    break
        text = session.harvest_buffer or ""
        session.harvest_buffer = None
        session.last_harvest_text = text
        names = parse_harvested(text)
        if not names:
            self._to_terminal(
                session_key, "log", "\n*** No commands recognised in the reply.\n"
            )
            return ()
        # Keyed on the LOGICAL peer, not `link.peer`. After a confirmed hop
        # the AX.25 link is still to the first node while the `?` was
        # answered by whatever node the operator hopped to -- keying on the
        # link's peer wrote the second node's commands into the first one's
        # cache entry, corrupting a node's real reference with another
        # node's commands. See `_TerminalSession.current_node`.
        node = session.current_node or str(link.peer)
        self._harvested.add(node, names, context=context)
        session.reference.learned = tuple(
            Command(name=command.name, confidence="learned", context=command.context)
            for command in self._harvested.records_for_callsign(node)
        )
        self._to_terminal(
            session_key,
            "log",
            f"\n*** Learned {len(names)} command(s) from {node}: "
            f"{', '.join(names)}\n",
        )
        return names

    def last_harvest_text(self, session_key: str) -> str:
        """The sanitized reply captured by this session's latest harvest.

        Kept behind the app boundary rather than having `CommandReferenceScreen`
        reach into `_sessions`: the dialog owns presentation, while this app
        owns link-scoped state and its lifetime.
        """
        session = self._sessions.get(session_key)
        return session.last_harvest_text if session is not None else ""

    def _on_link_state(self, session_key: str, state: SessionState) -> None:
        """Note a state change inline in the terminal -- except a
        TIMER_RECOVERY excursion and its own resolution back to CONNECTED.

        From a real report: WS1EC-15/CCEMA's link flapped timer-recovery /
        connected three times waiting out T1 retry and REJ recovery for one
        reply, writing six `***` lines into the scrollback in between actual
        node text. `TIMER_RECOVERY` is not an error (AGENTS.md is explicit:
        "a busy 1200-baud channel or a marginal HF path spends real time
        there and recovers fine") and the status bar already shows live
        link state at 1Hz -- announcing it inline too is the same fact told
        twice, which DESIGN.md's "say what is true, in the place the
        operator is already looking" argues against, once is enough. The
        INITIAL connect still gets its own distinct "Connected to X" note
        from a different call site (`action_connect`/`_hop_to`), so this
        skip never hides that a session started.

        Checking the previous state (`last_state`), not just "is this
        TIMER_RECOVERY", is what makes the *return* to CONNECTED skip too --
        recovering silently and then announcing the recovery's end would
        still be noise, just delayed by one transition. `last_state` MUST be
        recorded on every call, including a suppressed one: an earlier
        version of this method only set it inside the `if not recovering`
        branch, which means it was never actually set to TIMER_RECOVERY
        (that write is the one being skipped) -- so the "did we just recover"
        check could never see it, and every return to CONNECTED after a real
        flap was announced anyway. That shipped once already, caught only by
        watching a live CCEMA session repeat "*** connected" on every T1
        retry cycle, not by the test that was supposed to guard this exact
        thing (its assertion checked "timer-recovery" was absent, not that
        "connected" stopped repeating).
        """
        session = self._sessions.get(session_key)
        previous = session.last_state if session is not None else None
        recovering = state is SessionState.TIMER_RECOVERY
        recovered = state is SessionState.CONNECTED and previous is SessionState.TIMER_RECOVERY
        if not recovering and not recovered:
            self._note(session_key, f"\n*** {state.value}\n")
        if session is not None:
            session.last_state = state
        if state is not SessionState.CONNECTED:
            # Anything other than a plain, steady CONNECTED -- disconnecting,
            # failed, timer recovery -- means there is nothing to ask "did
            # they get it and just not answer yet" about; the "acknowledged
            # but silent" note below would only repeat that with less
            # information, or fire after the link is no longer there.
            self._cancel_reply_timer(session_key)
        if state is SessionState.DISCONNECTED:
            # Only here, never on TIMER_RECOVERY: a hop over a marginal path
            # spends real time in recovery and comes back (AGENTS.md), and
            # cancelling its watch there would lose a hop that was about to
            # succeed. A link that is genuinely gone has no hop left to
            # confirm.
            self._cancel_hop_watch(session_key)
            self._to_terminal(session_key, "set_placeholder", "not connected -- Ctrl+N")
            self._close_transcript(session_key)

    # ------------------------------------------------------------------
    # Reply watch -- "they got it, are they just not answering?"
    # ------------------------------------------------------------------
    def _cancel_reply_timer(self, session_key: str) -> None:
        session = self._sessions.get(session_key)
        if session is not None and session.reply_timer is not None:
            session.reply_timer.stop()
            session.reply_timer = None

    def _cancel_all_reply_timers(self) -> None:
        """Every session's, on shutdown -- see `on_unmount`."""
        for key in list(self._sessions):
            self._cancel_reply_timer(key)

    def _note_if_no_reply(self, session_key: str) -> None:
        """Fired `REPLY_WAIT_SECONDS` after a send with nothing back since,
        on `session_key` -- bound with that key at the moment `log_sent`
        armed this timer, so switching tabs in the meantime cannot make it
        report on the wrong session.

        Only says anything when the AX.25 layer has nothing outstanding
        (`link.va == link.vs`) -- i.e. the far end already acknowledged the
        line. If it has NOT been acknowledged, T1/timer recovery is already
        retrying it and already wrote its own note to the terminal; this
        would only be a vaguer echo of that. This is exactly the gap a real
        report exposed: WS1EC-15 ACKed a line within 3 seconds and then said
        nothing for 22 more, and the only place that ACK showed up was an RR
        frame the Monitor tab hides by default.
        """
        session = self._sessions.get(session_key)
        if session is None:
            return
        session.reply_timer = None
        link = session.link
        if link is None or not link.connected or link.va != link.vs:
            return
        self._to_terminal(
            session_key,
            "log",
            f"\n*** {link.peer} acknowledged that -- no reply yet. See "
            "Monitor (F2) for what has come back since.\n",
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Transmit
    # ------------------------------------------------------------------
    def _on_transmit_change(self, enabled: bool) -> None:
        """React to the master switch moving, whoever moved it.

        The beacon is re-armed rather than left running with a closed gate in
        front of it, because `Beaconer.problem()` treats a closed gate as a
        reason not to beacon -- so a timer left running would spend every
        interval deciding to do nothing. Arming on enable is what makes
        Ctrl+T start a configured beacon without a second keystroke.
        """
        self._restart_beacon()
        self._refresh_status()

    def action_toggle_transmit(self) -> None:
        """Ctrl+T -- the master switch, in the WSJT-X sense.

        Deliberately not a config setting that a Settings save can flip
        underneath the operator: this is operational state for the session in
        front of them, the way "Enable Tx" is. `tx_armed_at_start` decides
        where it begins and nothing else writes to it.
        """
        enabled = self.gate.toggle()
        if enabled:
            self.notify("Transmit ENABLED. This station can now key the radio.")
            self._to_terminal(self._active_key(), "log", "\n*** Transmit enabled\n")
        else:
            blocked = ""
            self.notify(
                "Transmit DISABLED. Nothing will be sent." + blocked,
                severity="warning",
            )
            self._to_terminal(self._active_key(), "log", "\n*** Transmit disabled\n")
        self._refresh_status()

    def _arm_for(self, what: str) -> None:
        """Open the transmit gate because the operator just asked for
        something that cannot happen without transmitting.

        **The rule this implements.** The gate exists to stop transmissions
        the operator did not initiate -- the timed beacon, auto-answer,
        anything on a timer. It was never meant to veto a transmission they
        just asked for by name. `Ctrl+N` names a station and confirms it in a
        dialog; that IS the request to key the radio, and answering it with
        "transmit is disabled" is a dead end, because the one thing the
        operator wanted is the one thing the message will not do.

        So arming needs a CONFIRMED, TARGETED action -- a destination the
        operator typed and accepted. A single keystroke with no confirmation
        step (the manual beacon on `Ctrl+Shift+B`) still does not arm: that is
        exactly the shape of an accidental transmission, and there is no
        target to make the intent unambiguous.

        Arming is never silent. It is a notification, a line in the terminal
        log and a status-bar change, because "did this thing start
        transmitting behind my back?" must stay answerable from the screen.
        """
        if self.gate.enabled:
            return
        self.gate.set(True)
        self._to_terminal(
            self._active_key(), "log", f"\n*** Transmit enabled automatically for: {what}\n"
        )
        self.notify(f"Transmit ENABLED for {what}. Ctrl+T turns it back off.")
        self._refresh_status()

    @work
    async def action_beacon_now(self) -> None:
        """Ctrl+Shift+B -- context-aware by active tab, same dispatch shape
        as `action_toggle_contacts` (Ctrl+G).

        **On the APRS pane**: toggles `config.aprs.enabled` -- see
        `_toggle_aprs_beacon_quick` for why this is a plain toggle, never
        a transmission, and never touches the transmit gate.

        **On every other tab**: sends one BTEXT beacon immediately,
        unchanged from before this key became context-aware. The timed
        beacon deliberately waits a full interval before its first
        transmission, because launching the app is not a request to key
        the radio. This is how an operator says "yes it is, right now"
        without having to wait out the interval or shorten it -- the same
        role JS8Call's heartbeat button plays. It does not enable the
        timer and does not need the timer to be on.
        """
        active = self.query_one("#main-tabs", TabbedContent).active
        if active == "aprs":
            await self._toggle_aprs_beacon_quick()
            return
        if not self.gate.enabled:
            self.notify(DISABLED_MESSAGE, severity="warning")
            return
        why = self.beaconer.problem()
        # "beaconing is off" is about the TIMER, and a manual beacon is not
        # the timer -- so it is not a reason to refuse one. Anything else is.
        if why and why != "beaconing is off":
            self.notify(f"No beacon sent: {why}", severity="warning")
            return
        if await self.beaconer.send_once(force=True):
            self.notify("Beacon sent.")
        else:
            self.notify("Beacon not sent.", severity="warning")

    @work
    async def action_aprs_beacon_now(self) -> None:
        """Ctrl+Alt+B -- transmit one APRS position report immediately.

        This is an operator-committed transmission to the well-defined APRS
        destination, not an unattended timer action.  It therefore arms the
        transmit gate when necessary, just as a committed APRS message does.
        It deliberately does *not* enable, restart, or otherwise alter the
        periodic APRS beacon setting: ``force=True`` waives only that timer
        setting inside :meth:`AprsBeaconer.send_once`.
        """
        self._arm_for("APRS position beacon")
        why = self.aprs_beaconer.problem()
        if why and why != "APRS beaconing is off":
            self.notify(f"APRS position beacon not sent: {why}", severity="warning")
            return
        if await self.aprs_beaconer.send_once(force=True):
            self.notify("APRS position beacon sent.")
        else:
            self.notify("APRS position beacon not sent.", severity="warning")

    @work
    async def action_aprs_object(self) -> None:
        """Compose then deliberately send one APRS object report.

        The modal has no transport path: cancelling or merely selecting an
        object symbol cannot transmit.  Only its explicit Send object button
        returns a request here, which is the operator-committed action that
        may arm the transmit gate.
        """
        request = await self.push_screen_wait(
            AprsObjectScreen(
                latitude=self.config.aprs.latitude,
                longitude=self.config.aprs.longitude,
                symbol=self.config.aprs.symbol,
                ascii_safe=self.config.ascii_safe,
            )
        )
        if request is None:
            return
        if self.station is not None:
            self._arm_for(f"APRS object {request.name.strip()}")
        if await self._send_aprs_object(request):
            self.notify(f"APRS object {request.name.strip()} sent.")
        else:
            self.notify("APRS object not sent. Check its fields and APRS path.", severity="warning")

    async def _toggle_aprs_beacon_quick(self) -> None:
        """Flip `config.aprs.enabled` from the APRS pane's Ctrl+Shift+B,
        so an operator does not have to open Settings just to turn
        beaconing on -- identical in effect to the Settings checkbox plus
        Save, just faster to reach.

        **Deliberately does not arm the transmit gate.** AGENTS.md's
        transmit-gate rules are explicit that a bare keystroke -- no
        confirmation step, no named target -- must never do that, and
        name the manual BTEXT beacon key as exactly this case. Turning
        APRS beaconing on here is architecturally the same kind of action:
        if the gate is closed, the beacon simply will not fire yet, same
        as BTEXT's own manual send above when the gate is closed.

        **Turns the plain-text (BTEXT) timer off if it was running.**
        AGENTS.md's beaconing section is explicit that the two beacons
        must never be conflated, but that is about identity, not about
        whether both may run at once -- an operator reaching for this key
        to turn APRS beaconing on is very unlikely to also want BTEXT
        still repeating in the background unattended. Only this
        direction: BTEXT's own Ctrl+Shift+B (Terminal pane) is a one-shot
        send, not a timer toggle, so there is no symmetrical case where
        enabling BTEXT this way would need to disable APRS.
        """
        self.config.aprs.enabled = not self.config.aprs.enabled
        if self.config.aprs.enabled and self.config.beacon.enabled:
            self.config.beacon.enabled = False
            self._restart_beacon()
        self._restart_aprs_beacon()
        self._save_config()
        state = "enabled" if self.config.aprs.enabled else "disabled"
        message = f"APRS beaconing {state}."
        if self.config.aprs.enabled and not self.gate.enabled:
            message += " Ctrl+T to transmit."
        self.notify(message)

    def action_toggle_aprs_ssid_filter(self) -> None:
        """Flip `Config.aprs.filter_by_ssid` (Ctrl+Shift+F) -- see
        `aprs_message_matches`'s docstring for what it decides. A plain
        toggle, not a transmission, so none of the transmit-gate rules
        apply -- this only changes which already-received messages count
        as "for me".

        Named in plain language the operator asked for by name -- "an
        exact SSID match" and "TX BLOCKED" mean nothing to someone new to
        packet, so the toast says who this station currently answers as.
        """
        self.config.aprs.filter_by_ssid = not self.config.aprs.filter_by_ssid
        self._save_config()
        if self.config.aprs.filter_by_ssid:
            self.notify(
                f"APRS SSID filter ON -- only answering messages addressed to "
                f"{self._active_aprs_identity()} exactly."
            )
        else:
            self.notify(
                "APRS SSID filter OFF -- answering messages addressed to any "
                f"SSID of {self.config.mycall}."
            )

    #: Where focus goes when a tab is opened, so the operator can act
    #: immediately: type at the node, type a message, search the monitor.
    #: A tab with nothing worth typing into (Heard, Settings) is absent and
    #: keeps whatever Textual's own activation does.
    _TAB_FOCUS = {
        "terminal": "#session-input",
        "aprs": "#aprs-compose-input",
        "monitor": "#monitor-query",
    }

    def action_show_tab(self, tab: str) -> None:
        """Switch tabs, and take focus out of the tab being left.

        **Clearing focus first is load-bearing, not tidiness.** Textual
        re-activates a `TabPane` whenever a widget inside it takes focus.
        Setting `.active` alone left the old pane's `Input` still focused --
        Textual then moved focus to the next widget *within that same hidden
        pane*, which re-activated it and threw the operator straight back
        where they came from. The visible symptom was a tab flashing up and
        vanishing again.

        This affected EVERY pane with a focusable widget, not one of them:
        F2/F3/F5 from the Terminal pane's send line and from the APRS compose
        box were all equally dead, which is most of the time an operator is
        actually typing. It went unnoticed because every test drove
        `action_show_tab` without focusing anything first, and a fresh app
        has focus nowhere in particular.
        """
        tabs = self.query_one("#main-tabs", TabbedContent)
        # Blur BEFORE switching: a focused widget in the outgoing pane is
        # exactly what pulls the activation back.
        self.set_focus(None)
        tabs.active = tab
        target = self._TAB_FOCUS.get(tab)
        if target is None:
            return

        def _focus_target() -> None:
            # After the switch has settled, so this focus lands in the pane
            # that is now visible. Missing widget is not an error -- a pane
            # can legitimately not have composed it yet.
            #
            # Re-check the active tab first: two tab keys pressed in quick
            # succession queue two of these, and the first one firing late
            # would focus a widget in a pane the operator has already left --
            # re-activating it, which is the very bug this method exists to
            # fix, just with a different trigger.
            if tabs.active != tab:
                return
            # This is a FALLBACK, not an override. `set_focus(None)` above
            # left focus empty, so anything focused by now was claimed
            # deliberately by whoever called us -- `action_find_in_terminal`
            # switches to the Terminal tab and then focuses the find box, and
            # stealing that back to the send line put the operator's typing
            # in the wrong widget. Only fill a vacuum.
            if self.focused is not None:
                return
            for widget in self._base_query(target):
                widget.focus()
                return

        self.call_after_refresh(_focus_target)

    def action_toggle_contacts(self) -> None:
        """Ctrl+G: show or hide whichever slide-out belongs to the active
        tab -- the Address Book on Terminal, the contacts list on APRS. A
        silent no-op on every other tab (Monitor, Heard, Settings), same as
        pressing Ctrl+F outside the Terminal pane does nothing: the key
        always means the same thing, it just has nothing to act on there.
        """
        active = self.query_one("#main-tabs", TabbedContent).active
        if active == "terminal":
            self.query_one(TerminalPane).toggle_addressbook()
        elif active == "aprs":
            self.query_one(AprsPane).toggle_contacts()

    def action_clear_log(self) -> None:
        active = self.query_one("#main-tabs", TabbedContent).active
        if active == "monitor":
            self.query_one(MonitorPane).clear()
        elif active == "aprs":
            self.query_one(AprsPane).clear_active()
        else:
            self.query_one(TerminalPane).clear_active()

    def action_find_in_terminal(self) -> None:
        """Ctrl+F: find in the Terminal pane's scrollback.

        Switches to the Terminal tab first -- pressing Find should never
        leave the operator staring at whichever tab happened to be open
        wondering where the search box went.
        """
        self.action_show_tab("terminal")
        self.query_one(TerminalPane).open_find()

    def _frame_tier_transports(self) -> list[dict]:
        """This app's own configured transports of the SAME tier it is
        currently running on -- see `transport.FRAME_TIER_KINDS`'s
        docstring for why switching tiers live is not offered here. Empty
        when `self.station is None` (session-tier app)."""
        from ..transport import FRAME_TIER_KINDS

        if self.station is None:
            return []
        return [t for t in self.config.transports if t.get("kind") in FRAME_TIER_KINDS]

    def _session_tier_transports(self) -> list[dict]:
        """The session-tier counterpart of `_frame_tier_transports`. Empty
        when `self.session_transport is None` (frame-tier app)."""
        from ..transport import SESSION_TIER_KINDS

        if self.session_transport is None:
            return []
        return [t for t in self.config.transports if t.get("kind") in SESSION_TIER_KINDS]

    async def _switch_frame_transport(self, name: str) -> bool:
        """Open the transport named `name` and hand it to `self.station` in
        place of whatever it is currently using, via `AX25Station.rebind_
        transport`. Returns whether it worked; reports its own failure via
        `notify`, so a caller only needs to act on the boolean.

        Shared by `SettingsPane` (choosing a different Active transport and
        hitting Save) and `KissTermApp.action_connect` (the Connect
        dialog's own transport picker) -- one implementation of "actually
        open the newly-selected transport", not two that could drift apart.
        Frame-tier only: a session transport hands back an already-
        connected byte stream, not frames this station's state machine can
        run on, so swapping one in here would need a different app
        entirely. Restarting kissterm with it selected is the supported
        path for THAT case; this method refuses and says so rather than
        guessing.
        """
        if self.station is None:
            return False
        entry = next((t for t in self.config.transports if t.get("name") == name), None)
        if entry is None:
            return False

        from .. import transport as transport_mod
        from ..transport.base import FrameTransport

        try:
            new_transport = transport_mod.build_transport(entry)
            await new_transport.open()
        except Exception as exc:
            log.exception("could not open %s", name)
            self.notify(f"Could not open {name}: {exc}", severity="error")
            return False

        if not isinstance(new_transport, FrameTransport):
            self.notify(
                f"{name} is a session transport; switching to it live is not "
                "supported. Restart kissterm with it selected.",
                severity="warning",
            )
            with contextlib.suppress(Exception):
                await new_transport.close()
            return False

        try:
            old_transport = self.station.rebind_transport(new_transport)
        except RuntimeError as exc:
            self.notify(str(exc), severity="warning")
            with contextlib.suppress(Exception):
                await new_transport.close()
            return False

        with contextlib.suppress(Exception):
            await old_transport.close()

        self._refresh_status()
        self.notify(f"Now using {name}.")
        return True

    async def _switch_session_transport(self, name: str) -> bool:
        """The session-tier counterpart of `_switch_frame_transport`.

        Simpler in one way: a session transport has no state machine
        anything else is bound to, so this is just building the new one and
        replacing `self.session_transport` -- there is no `AX25Station.
        rebind_transport` equivalent because there is no station. Still
        calls `.open()` before handing it over, same as the frame-tier
        version and `__main__.py`'s own launch-time construction: for
        Telnet/SSH `.open()` is a no-op (the real work happens in
        `.connect()`), but for VARA/Mercury/kernel AX.25 it does the actual
        setup -- VARA's `.open()` connects to the local modem's own command
        and data TCP ports, entirely separate from the later AX.25-level
        `.connect()` to a remote station. Skipping it here would work by
        accident for Telnet/SSH and fail for the other three.
        """
        entry = next((t for t in self.config.transports if t.get("name") == name), None)
        if entry is None:
            return False

        from .. import transport as transport_mod

        try:
            new_transport = transport_mod.build_transport(entry)
            await new_transport.open()
        except Exception as exc:
            log.exception("could not open %s", name)
            self.notify(f"Could not open {name}: {exc}", severity="error")
            return False

        old_transport = self.session_transport
        self.session_transport = new_transport
        if old_transport is not None:
            with contextlib.suppress(Exception):
                await old_transport.close()

        self._refresh_status()
        self.notify(f"Now using {name}.")
        return True

    @work
    async def action_connect(self, prefill=None, target: str = "") -> None:
        """Connect to a station, via the dialog or dialed directly.

        `prefill` is an `addressbook.Entry`, passed by `AddressBookPane`
        when the operator dials a saved station instead of typing one into
        Ctrl+N -- everything past this point is the same flow either way:
        the transmit gate, the transport check, the hop chain, the login.
        Dialing is a faster way to reach this method, never a second,
        lighter-weight path into it. `target` only prepopulates the dialog
        for a passive NET/ROM claim; it never dials or arms the transmit gate.
        """
        if self.station is None:
            if self.session_transport is not None:
                candidates = self._session_tier_transports()
                if len(candidates) > 1:
                    from .dialogs import SessionTransportPickerScreen

                    chosen = await self.push_screen_wait(
                        SessionTransportPickerScreen(
                            candidates, self.config.active_transport
                        )
                    )
                    if chosen is None:
                        return
                    if chosen != self.config.active_transport:
                        self.config.active_transport = chosen
                        self._save_config()
                        if not await self._switch_session_transport(chosen):
                            return
                await self._connect_session_transport()
                return
            self.notify("No transport is open.", severity="error")
            return
        if prefill is not None:
            request = ConnectRequest(
                prefill.target,
                prefill.script,
                prefill.hops,
                prefill.credential,
                prefill.script_name,
            )
            # A dial is an attempt like any other -- see AddressBook.record_
            # attempt's docstring for why this is recorded on the attempt,
            # not on success.
            self.addressbook.record_attempt(
                prefill.target,
                prefill.script,
                prefill.hops,
                prefill.credential,
                prefill.script_name,
            )
        else:
            request = await self.push_screen_wait(
                ConnectScreen(
                    self.addressbook,
                    self.config.credentials,
                    self.config.scripts,
                    transports=self._frame_tier_transports(),
                    active_transport_name=self.config.active_transport,
                    ports=self.station.transport.ports,
                    target=target,
                )
            )
            if not request:
                return
            if request.new_credential_text and request.credential:
                # ConnectScreen's "+ Add new credential..." flow, named --
                # see ConnectRequest.new_credential_text's docstring. Replace
                # a same-named entry rather than append a shadowing
                # duplicate: `find_credential` returns the FIRST match, so a
                # second entry with the same name would silently never be
                # the one used.
                existing = next(
                    (
                        c
                        for c in self.config.credentials
                        if c.get("name") == request.credential
                    ),
                    None,
                )
                if existing is not None:
                    existing["text"] = request.new_credential_text
                else:
                    self.config.credentials.append(
                        {"name": request.credential, "text": request.new_credential_text}
                    )
                self._save_config()
            if request.transport_name and request.transport_name != self.config.active_transport:
                self.config.active_transport = request.transport_name
                self._save_config()
                if not await self._switch_frame_transport(request.transport_name):
                    return
        # A frequency or connection type on file is worth nothing if the
        # operator only sees it after the SABMs already went out -- ask
        # before arming anything. `find` is a read-only lookup (see its
        # docstring); `prefill` already IS the entry when dialing, so this
        # only does the lookup for the Ctrl+N path.
        reminder = prefill or self.addressbook.find(request.target)
        if reminder is not None and (
            reminder.frequency or reminder.connection_type or reminder.note
        ):
            proceed = await self.push_screen_wait(
                RadioReminderScreen(
                    reminder.frequency, reminder.connection_type, reminder.note
                )
            )
            if not proceed:
                return
        target = request.target
        # Node hops replace the "via DIGI" path entirely rather than
        # combining with it -- see `ConnectScreen._submit`, which already
        # refuses that combination, so `parse_path(target)` here is always
        # either a plain callsign (hops in use) or a full digipeater path
        # (hops empty). Either way the actual AX.25 SABM goes to the first
        # node of the chain, which is `path.destination` in both cases: the
        # chain's first hop when hops are given, the final target otherwise.
        hop_names = [h.strip() for h in request.hops.split(",") if h.strip()]
        chain = hop_names + [target] if hop_names else [target]
        path = parse_path(chain[0])
        # Computed before anything else here: the tab this whole attempt
        # belongs to, whether it comes up or not. An existing tab for this
        # exact peer (a reconnect) always counts as room, no matter how
        # many OTHER tabs are open -- see `TerminalPane.has_room_for`.
        port = request.port
        if port < 0 or port >= self.station.transport.ports:
            self.notify(f"Radio port {port} is not available on this transport.", severity="error")
            return
        key = self._session_key(path.destination, port)
        pane = self.query_one(TerminalPane)
        if not pane.has_room_for(key):
            self.notify(
                f"Close a session first -- {MAX_TERMINAL_TABS} connections are "
                "already open.",
                severity="warning",
            )
            return
        # This session's own tab, opened and put on screen before anything
        # below writes to it, including the TNC-link check right after --
        # a reconnect to a peer whose tab is still open reuses it (and its
        # history) rather than wiping it, which is what the old
        # single-session version had to do instead.
        pane.open_tab(key, activate=True)
        # The TNC link, before the RF link. Sending six SABMs into a socket
        # that is down produces "no answer from WS1EC-15" -- a diagnosis
        # pointing at the antenna when the fault is in the room. Unlike a
        # closed transmit gate this is not something a keystroke can fix, so
        # it is worth saying before spending the attempt.
        state = self.station.transport.state
        if state is not TransportState.OPEN:
            where = self.station.transport.info.detail
            self._to_terminal(
                key,
                "log",
                f"\n*** Not connecting: the link to the TNC at {where} is "
                f"{state.value}, so nothing would reach the air. This is not "
                f"an RF problem -- check the TNC, then Settings (F5) > Test "
                f"selected.\n",
            )
            self.notify(
                f"TNC link is {state.value} -- nothing would be transmitted.",
                severity="error",
            )
            return
        # A confirmed connect request ARMS the gate rather than being refused
        # by it. See `_arm_for` -- naming a station and confirming the dialog
        # is the operator asking to transmit, and refusing it here left them
        # with a dead end that only reads as "the far station is not there".
        self._arm_for(f"connect to {path.destination}")
        self._to_terminal(key, "log", f"\n*** Connecting to {path.destination} on port {port}...\n")
        # Set before the await, not after: `AX25Station.connect` registers the
        # link synchronously before it awaits anything, so by the time this
        # coroutine yields control the link is already reachable by peer
        # address -- which is what lets Ctrl+D find and cancel it mid-attempt.
        self._connecting[key] = (path.destination, port)
        try:
            link = await self.station.connect(
                path,
                port=port,
                paclen=_entry_link_override(reminder.paclen) if reminder else None,
                window=_entry_link_override(reminder.window) if reminder else None,
            )
        except TransportError as exc:
            self.notify(str(exc), severity="error")
            return
        finally:
            self._connecting.pop(key, None)
        if link is None:
            failed = self.station.link_to(path.destination, port)
            reason = getattr(failed, "last_error", "") if failed else ""
            if reason == CANCELLED_REASON:
                self._to_terminal(key, "log", f"*** Connect to {path.destination} cancelled.\n")
                return
            # Say WHY. "No connection" alone cannot be acted on: a DM means
            # the node heard us and refused, which is a configuration problem
            # at one end or the other; silence after N2 tries means the path
            # did not carry, which is an antenna, power or propagation
            # problem. On a marginal path that distinction is the whole
            # diagnosis, and it is already known here.
            attempts = getattr(failed, "rc", 0) if failed else 0
            detail = f" -- {reason}" if reason else ""
            self._to_terminal(key, "log", f"*** No connection to {path.destination}{detail}\n")
            if attempts:
                self._to_terminal(
                    key,
                    "log",
                    f"*** {attempts} attempt(s) sent. Check the Monitor tab (F2) "
                    "for what went out and what came back.\n",
                )
            # It was up when we started or we would not be here, so a
            # transport that is down NOW dropped during the attempt -- and
            # some of those SABMs never left the process. Say so, or the
            # operator spends the evening on an antenna that is fine.
            if self.station.transport.state is not TransportState.OPEN:
                self._to_terminal(
                    key,
                    "log",
                    "*** The link to the TNC dropped during this attempt, so "
                    "some of those frames never reached the radio. Fix that "
                    "first -- this is not an RF failure.\n",
                )
            self.notify(
                f"Could not connect to {path.destination}{detail}", severity="warning"
            )
            return
        self._bind_link(link, key)
        # Explicit, not left to the `on_state` callback `_bind_link` just
        # registered: `AX25Station.connect` already ran the SABM/UA exchange
        # to completion before returning this link, so the transition INTO
        # `connected` fired to whatever was listening at the time -- which
        # was nobody, since nothing could subscribe before the link existed.
        # Every later transition (disconnecting, timer recovery, ...) is
        # caught fine; only this first one is structurally too late for that
        # mechanism to catch, and it is the one an operator most needs to
        # see. From a real report: connecting to WS1EC-15 directly never
        # printed anything resembling EasyTerm's "*** Connected to station
        # WS1EC-15" -- with a node that has nothing to say until you type a
        # command, that silence was the only feedback there was at all.
        #
        # `_note`, not a bare `_to_terminal` call: a real transcript pulled
        # from this exact gap showed the file's own "* connected" line
        # arriving eleven seconds late, timed to the NEXT state transition
        # (a T1 timer-recovery retry) rather than the actual connect --
        # `_bind_link` wires `_on_link_state` (which calls `_note`) in too
        # late to see this first transition either, so writing straight to
        # the terminal pane fixed what the operator watched live but left
        # the durable transcript with the same hole.
        self._note(key, f"\n*** Connected to {link.peer}\n")
        if pane.active_session_key == key:
            # Only if the operator is still looking at this tab -- a long
            # SABM retry (or an HF hop chain below) can outlast several
            # tab switches, and stealing focus back would be exactly the
            # "steal the view" rule the module docstring forbids.
            pane.focus_input()
        reached_target = True
        if len(chain) > 1:
            # The AX.25 link is only to the FIRST node -- everything past
            # it is that node's own onward routing, invisible to kissterm's
            # state machine and driven purely by watching what comes back
            # over this one link. See `_hop_through`.
            reached_target = await self._hop_through(link, key, chain[1:])
        if not reached_target:
            # Left connected to whichever node was last reached -- the
            # operator can continue by hand from there, or Ctrl+D. Neither
            # the address book nor a login script should treat a chain that
            # stalled partway as having reached `target`.
            return
        # Separate from the attempt the dialog already recorded: "tried ten
        # times, never got in" is a different fact from "this one works", and
        # flattening them would hide exactly the pattern an operator wants to
        # see next to a callsign on a marginal path.
        self.addressbook.record_connect(target)
        login_text = self._resolve_login(
            request.credential, request.script_name, request.script
        )
        if login_text.strip():
            self._run_connect_script(link, key, login_text)

    async def _connect_session_transport(self) -> None:
        """Connect through a session-tier transport (Telnet, SSH, VARA,
        Mercury, kernel AX.25) -- no target dialog, no hop chain, no
        address book.

        There is exactly one destination a session transport can reach:
        whatever host and port (or callsign, for VARA/kernel AX.25) it was
        configured with at startup, in Settings > Transports. Routing that
        through the FrameTransport flow above would force AX.25-shaped
        concepts -- a target to parse, a digipeater path, per-station
        hops -- onto an addressing model that genuinely has none of them;
        see `SessionTransport.connect`'s docstring. An operator who needs
        to reach a further node once this session is up can still type
        "C <node>" by hand -- that has always worked and needs nothing
        from this method.

        An auto-login still runs after connecting, same as the address-book
        flow -- it just comes from `transport.script`/`transport.credential`
        (this transport's own config entry, see `Transport.script`'s
        docstring) rather than a per-attempt dialog, since there is no dialog
        on this path. This is the WS1EC case: the script's last line can be
        "C <node>" exactly like a hand-typed hop, so one saved script both
        logs in and reaches the actual node from the shell SSH lands in.

        Always binds into the permanent `""` session key rather than one
        derived from the peer, unlike the frame-tier path -- this tier
        never has more than one session (out of scope for the tabbed
        terminal; see `terminal_pane.py`'s module docstring), so there is
        never a second tab to distinguish it from.
        """
        transport = self.session_transport
        if self.link is not None and self.link.connected:
            self.notify("Already connected.", severity="warning")
            return
        self._arm_for(f"connect via {transport.info.detail}")
        self.query_one(TerminalPane).clear("")
        self._to_terminal("", "log", f"\n*** Connecting to {transport.info.detail}...\n")
        connect_task = asyncio.current_task()
        assert connect_task is not None
        self._session_connect_task = connect_task
        try:
            session = await transport.connect()
        except asyncio.CancelledError:
            # Ctrl+D is an operator decision, not a failed connection.
            # SessionTransport implementations clean up their partly-open
            # connection before propagating this cancellation.
            self._to_terminal("", "log", "*** Connect cancelled by operator.\n")
            self.notify("Cancelled connect.")
            return
        except TransportError as exc:
            self._to_terminal("", "log", f"*** Could not connect: {exc}\n")
            self.notify(str(exc), severity="error")
            return
        finally:
            if self._session_connect_task is connect_task:
                self._session_connect_task = None
        link = _SessionLinkAdapter(session)
        self._bind_link(link, "")
        # Same gap as the frame-tier connect above (`action_connect`) and
        # the same fix -- see the comment there.
        self._note("", f"\n*** Connected to {link.peer}\n")
        self.query_one(TerminalPane).focus_input()
        # Same auto-login as the address-book flow above (`request.script`/
        # `request.credential`/`request.script_name`), just sourced from the
        # transport's own config entry instead of a per-attempt dialog --
        # there is no target dialog on this path to carry one. See
        # `Transport.script`'s docstring.
        login_text = self._resolve_login(
            transport.credential, transport.script_name, transport.script
        )
        if login_text.strip():
            self._run_connect_script(link, "", login_text)

    async def _hop_through(self, link, session_key: str, nodes: list[str]) -> bool:
        """Walk a chain of node-to-node hops over an already-open link.

        For a station reached only by connecting through intermediate
        BPQ/NET-ROM nodes in turn -- no digipeater path exists, so this is
        done at the application level: send "C <node>", wait for that
        node's own CONNECTED reply, then the next, in order. Modelled on
        the send/wait-for-CONNECTED-or-BUSY/FAILED loop the sibling
        `bpq-apps` project's node-map crawler uses against real BPQ nodes,
        simplified to a flat per-hop timeout (`HOP_TIMEOUT`) since this
        walks a short chain the operator typed by hand, not an open-ended
        auto-discovery crawl.

        `session_key` is passed explicitly rather than derived from `link`
        -- this can run for several seconds to minutes across several hops,
        and the operator is free to switch to (or open) another tab while it
        runs. Every note here must keep landing on the ORIGINAL tab, not on
        whatever happens to be on screen when a given hop's reply arrives.

        Stops and reports on the first hop that does not come up, leaving
        the link connected to whichever node was last reached rather than
        tearing anything down -- the operator can continue by hand from
        there. Never sends the next hop's command after a failure: that
        would be transmitting into a link nothing has confirmed is ready
        for it.
        """
        for node in nodes:
            if not link.connected:
                self._to_terminal(session_key, "log", "*** Hop chain stopped: no longer connected.\n")
                return False
            if not self.gate.enabled:
                self._to_terminal(session_key, "log", "*** Hop chain stopped: transmit is off.\n")
                return False
            ok, detail = await self._hop_to(link, session_key, node)
            if not ok:
                extra = f" -- {detail}" if detail else ""
                self._to_terminal(session_key, "log", f"*** No connection to {node}{extra}\n")
                self.notify(f"Hop to {node} did not connect{extra}", severity="warning")
                return False
        return True

    async def _await_hop_confirmation(
        self,
        link,
        node: str,
        timeout: float | None = None,
        watch: "_HopConfirmation | None" = None,
    ) -> tuple[bool, str]:
        """Wait for `node`'s own CONNECTED reply after a "C <node>" (or
        JNOS "connect <node>") has just been sent on `link`.

        Returns ``(True, "")`` on a CONNECTED reply, or ``(False, detail)``
        on an explicit BUSY/FAILED/DISCONNECTED/TIMEOUT reply (a refusal --
        `detail` names which word) or on plain silence past `timeout`
        (`detail` says so) -- two different diagnoses that must not be
        reported with the same words, same reasoning as a DM versus an N2
        timeout one layer down in `AX25Station.connect`.

        Shared by `_hop_to` (the scripted hop chain) and `log_sent`'s
        hand-typed-hop watch, so there is exactly one place that knows what
        "the hop worked" means rather than two copies free to drift apart.

        `watch` lets a caller that already subscribed hand its listening
        `_HopConfirmation` over; either way this method owns stopping it.
        Both callers do subscribe first, for the same reason spelled out in
        that class's docstring -- `log_sent` because it is synchronous and
        cannot await, `_hop_to` because its own "C <node>" send is an await
        during which a reply could in principle already come back. Making
        one here is the fallback for a caller with nothing to race.

        `timeout=None` means `HOP_TIMEOUT`, resolved HERE rather than as a
        default argument value: a default is bound once at import, and
        `tests/pilot/test_connect_scripts.py` turns the real timeout down by
        monkeypatching the module constant, which a bound default would
        silently ignore.
        """
        if timeout is None:
            timeout = HOP_TIMEOUT
        if watch is None:
            watch = _HopConfirmation(link, node)
        try:
            return await asyncio.wait_for(watch.result, timeout=timeout)
        except asyncio.TimeoutError:
            return False, f"no response within {timeout:.0f}s"
        finally:
            watch.stop()

    async def _hop_to(self, link, session_key: str, node: str) -> tuple[bool, str]:
        """Send ``C <node>`` and wait for that node's own CONNECTED reply,
        applying the hop only if it actually comes up.

        `log_sent` is called with `watch_hop=False` because this method owns
        confirming its own hop: letting `log_sent` start a second watcher
        for the same command would put two subscribers on the same
        `link.on_data` bytes, both able to reach `_commit_hop`.

        Returns whatever `_await_hop_confirmation` decided, unchanged, so
        `_hop_through` can tell a refusal from silence. A failure leaves the
        session's node identification and logical peer completely untouched
        -- the operator is still talking to the node they were already
        connected to, and blanking a correct identification for a hop that
        never happened is a regression this shipped once already.
        """
        # Subscribed before the command goes out, not after: `link.send` is
        # an await, and a watcher that starts listening only once it returns
        # has a window -- however small -- in which the node's answer has
        # already been fanned out to everyone else. Same argument as
        # `_HopConfirmation`'s docstring makes for `log_sent`.
        watch = _HopConfirmation(link, node)
        try:
            cmd = f"C {node}"
            await link.send(cmd.encode("latin-1", "replace") + b"\r")
            self._to_terminal(session_key, "log", cmd + "\n")
            self.log_sent(session_key, cmd, watch_hop=False)
            ok, detail = await self._await_hop_confirmation(link, node, watch=watch)
        finally:
            # Belt and braces: `_await_hop_confirmation` stops it on every
            # path it reaches, but a send that raises (a closed transport)
            # never gets there, and a watcher left on the fan-out would go
            # on matching a later hop's traffic. `stop()` is idempotent.
            watch.stop()
        if ok:
            self._commit_hop(session_key, node)
        return ok, detail

    def _resolve_login(self, credential: str, script_name: str, script: str) -> str:
        """The text to actually send, from the three sources every auto-
        login carries -- `credential` (a name in `Config.credentials`),
        `script_name` (a name in `Config.scripts`), and `script` (literal
        text) -- checked in that order. `Config.credentials`'s docstring
        has the full reasoning for why a login and a script are kept as
        two separate saved lists rather than one.
        """
        if credential:
            return find_credential(self.config, credential)
        if script_name:
            return find_script(self.config, script_name)
        return script

    @work
    async def _run_connect_script(self, link, session_key: str, script: str) -> None:
        """Send a station's saved auto-login script, one line at a time.

        Runs only right after a connect the operator just named and
        confirmed in the Connect dialog -- see `_arm_for` above, which is
        what actually armed transmit for this attempt. This does not arm or
        re-confirm anything itself; it rides the one the connect already
        got, the same way answering a poll rides an established link's own
        authorization rather than asking again per frame.

        `session_key` is explicit for the same reason `_hop_through` takes
        one -- this runs across several awaited sends and the operator may
        have switched tabs by the time a later line goes out.

        Every line is echoed into the terminal log and the session
        transcript exactly the way `TerminalPane.send_line` echoes a typed
        one -- automation the operator cannot see on screen is exactly what
        the transmit-gate rules exist to prevent. A closed gate or a link
        that has dropped stops the script rather than losing lines
        silently: reporting a suppressed line as sent would be the one lie
        a transmit indicator must not tell.
        """
        lines = [ln for ln in script.splitlines() if ln.strip()]
        if not lines:
            return
        self._to_terminal(session_key, "log", f"\n*** Auto-login: sending {len(lines)} line(s)...\n")
        for line in lines:
            if not link.connected:
                self._to_terminal(session_key, "log", "*** Auto-login stopped: no longer connected.\n")
                return
            if not self.gate.enabled:
                self._to_terminal(session_key, "log", "*** Auto-login stopped: transmit is off.\n")
                return
            await link.send(line.encode("latin-1", "replace") + b"\r")
            self._to_terminal(session_key, "log", line + "\n")
            self.log_sent(session_key, line)
            await asyncio.sleep(CONNECT_SCRIPT_LINE_DELAY)

    @work
    async def action_set_callsign(self) -> None:
        """Change the station callsign and persist it, without a restart.

        Refused while ANY session is up, not just the active tab: the
        callsign is in the address field of every frame of every established
        conversation, and swapping it mid-session would make our own traffic
        unrecognisable to every one of those peers -- each would keep
        answering the old call while we transmitted under the new one, and
        every link would die by N2 timeout rather than by anything the
        operator could diagnose. Disconnecting first is the honest
        requirement.
        """
        if any(s.link is not None and s.link.connected for s in self._sessions.values()):
            self.notify(
                "Disconnect every session before changing callsign.", severity="warning"
            )
            return

        current = getattr(self.config, "mycall", "") or ""
        new_call = await self.push_screen_wait(CallsignScreen(current))
        if not new_call or new_call == current:
            return

        self.config.mycall = new_call
        if self.station is not None:
            # Update the live station too, not just the file. Without this the
            # change silently would not take effect until the next launch,
            # which is exactly the confusion this feature exists to remove.
            from ..ax25 import AX25Address

            self.station.mycall = AX25Address.parse(new_call)

        saved = self._save_config()
        self.query_one(SettingsPane).render_settings(self.config)
        where = "saved" if saved else "applied for this session only (could not write config)"
        self.notify(f"Callsign is now {new_call} -- {where}.")
        self._to_terminal(self._active_key(), "log", f"\n*** Callsign changed to {new_call}\n")

    def _save_config(self) -> bool:
        """Persist config, reporting failure rather than raising.

        A read-only or full config directory must not take the app off the air;
        the operator can keep working with the in-memory value.
        """
        try:
            from ..config import save_config

            save_config(self.config)
            return True
        except Exception:
            log.exception("could not save config")
            return False

    @work
    async def action_command_reference(self) -> None:
        """Show the shipped command reference; put a pick in the input line.

        Never sends. `TerminalPane.suggest` fills the field and the operator
        commits deliberately -- a reference that transmitted on selection would
        be a defect on a shared channel.

        **Context-aware, dispatched on the active tab.** `Ctrl+R` asks one
        question -- "what can I say to the thing I am talking to?" -- and on
        the APRS pane the answer comes from `kissterm/aprs_services/` instead
        of `kissterm/nodes/`. Same question, same key, different source; this
        is the third use of the per-tab dispatch `action_toggle_contacts`
        (`Ctrl+G`) and `action_beacon_now` (`Ctrl+Shift+B`) already use, and
        the operator learns one key rather than two. Terminal-pane behaviour
        below is untouched, and every other tab still gets it.

        `can_harvest`/`peer` let the screen offer its "Learn from node"
        button only when there is an actual connected link to ask -- see
        `harvest_commands`.
        """
        if self.query_one("#main-tabs", TabbedContent).active == "aprs":
            for pane in self._base_query(AprsPane):
                pane.show_templates()
                return
            return
        key = self._active_key()
        link = self.link
        chosen = await self.push_screen_wait(
            CommandReferenceScreen(
                self.reference,
                session_key=key,
                can_harvest=link is not None and link.connected,
                # The LOGICAL peer: "Ask X for its command list?" has to name
                # the node that will actually answer, which after a confirmed
                # hop is not the link's own peer -- and it is the same name
                # `harvest_commands` will file the answer under.
                peer=self.current_node or (str(link.peer) if link is not None else ""),
            )
        )
        if chosen:
            self.action_show_tab("terminal")
            self.query_one(TerminalPane).suggest(chosen)

    @work
    async def action_show_transcripts(self) -> None:
        """Find, read and export a past session's transcript.

        The screen reads from the same directory `_start_transcript` writes
        to (`_transcript_directory`), so this always shows what a live
        session would have just written -- including one in progress right
        now, since `SessionLog` is line-buffered.
        """
        await self.push_screen_wait(TranscriptsScreen(self._transcript_directory()))

    @work
    async def action_file_transfer(self) -> None:
        """Start one explicit YAPP/AutoBIN upload or arm an explicit download."""
        key = self._active_key()
        session = self._sessions.get(key)
        if session is None or session.link is None or not session.link.connected:
            self.notify("Connect before starting a file transfer.", severity="warning")
            return
        request = await self.push_screen_wait(FileTransferScreen())
        if request is None:
            return
        if self.gate is not None and not self.gate.enabled:
            self._arm_for(f"{request.protocol.upper()} {request.mode}")
        self._transfer_active.add(key)
        protocol = request.protocol.upper()
        self._note(key, f"\n*** {protocol} {request.mode} starting\n")
        try:
            if request.protocol == "yapp":
                sender, receiver = send_file, receive_file
            else:
                sender, receiver = send_autobin, receive_autobin
            if request.mode == "upload":
                result = await sender(session.link, request.path)
            else:
                downloads = state_path() / "downloads"
                downloads.mkdir(parents=True, exist_ok=True)
                result = await receiver(session.link, downloads)
        except (OSError, ValueError, YappError, AutoBinError) as exc:
            self._note(key, f"\n*** {protocol} {request.mode} failed: {exc}\n")
            self.notify(f"{protocol} {request.mode} failed: {exc}", severity="warning")
        else:
            self._note(key, f"\n*** {protocol} {request.mode} complete: {result.path.name} ({result.size} bytes)\n")
            self.notify(f"{protocol} {request.mode} complete: {result.path.name}")
        finally:
            self._transfer_active.discard(key)

    @work
    async def action_disconnect(self) -> None:
        """Ctrl+Shift+D / Ctrl+D -- disconnect whichever tab is on screen.

        Also the DISC half of `Delete` on the session-tab strip's focused
        tab (`disconnect_or_close_tab`), since `Delete` there only ever
        fires for the active tab -- see `terminal_pane.py`'s module
        docstring on why closing a session is two `Delete`s, not one.
        """
        await self._disconnect_session(self._active_key())

    async def _disconnect_session(self, session_key: str) -> None:
        session = self._sessions.get(session_key)
        if session is not None and session.link is not None and session.link.connected:
            # Same reasoning as connect, and more so: a DISC is how a link is
            # ended politely. Refusing to send it leaves the far station
            # holding a session open until ITS timers give up, which is a
            # worse outcome for the channel than the transmission we would
            # be avoiding.
            self._arm_for(f"disconnect from {session.link.peer}")
            self._to_terminal(session_key, "log", "\n*** Disconnecting...\n")
            await session.link.disconnect()
            return
        # No established link -- but a connect attempt may still be working
        # through its SABM retries. Without this, the only way off a stuck
        # attempt was to wait out N2 in full: Ctrl+D said "Not connected"
        # (true, but useless) while the radio kept keying up on its own.
        pending = self._connecting.get(session_key)
        if pending is not None and self.station is not None:
            target, port = pending
            connecting = self.station.link_to(target, port)
            if connecting is not None and not connecting.connected:
                self._to_terminal(
                    session_key,
                    "log",
                    f"\n*** Cancelling connect to {connecting.peer} -- no "
                    "further SABMs will be sent.\n",
                )
                connecting.close(reason=CANCELLED_REASON)
                self.notify(f"Cancelled connect to {connecting.peer}.")
                return
        session_connect_task = self._session_connect_task
        if (
            session_key == ""
            and session_connect_task is not None
            and not session_connect_task.done()
        ):
            self._to_terminal(
                session_key,
                "log",
                "\n*** Cancelling session transport connect...\n",
            )
            session_connect_task.cancel()
            return
        self.notify("Not connected.", severity="warning")

    def disconnect_or_close_tab(self, session_key: str) -> None:
        """`Delete` on the focused session tab. Disconnects a live session;
        removes an already-disconnected (or still-connecting) tab outright.
        Two keystrokes rather than one for a connected session, so the
        "*** Disconnecting..." note stays readable instead of the tab
        vanishing out from under it -- see `terminal_pane.py`'s module
        docstring.
        """
        session = self._sessions.get(session_key)
        if session is not None and session.link is not None and session.link.connected:
            self.action_disconnect()
            return
        if session_key in self._connecting:
            self.action_disconnect()
            return
        # Cancel BEFORE the session goes: `_cancel_hop_watch` finds the task
        # through `_sessions`, so popping first would strand a watcher on a
        # session that no longer exists.
        self._cancel_reply_timer(session_key)
        self._cancel_hop_watch(session_key)
        self._sessions.pop(session_key, None)
        self.query_one(TerminalPane).close_tab(session_key)

    # ------------------------------------------------------------------
    # Periodic UI refresh
    # ------------------------------------------------------------------
    def _transport_status(self) -> str:
        """The transport field of the status bar, from LIVE state.

        This used to be a string captured once at mount, which meant the
        status bar happily showed a healthy TNC address while the socket
        underneath it was gone. On the first real on-air test the connection
        to the TNC dropped mid-connect, every SABM after that was refused by
        the transport, and the only thing on screen was "no answer from
        WS1EC-15" -- which reads as a dead RF path when it was actually a
        dead TCP socket. A transport that is not carrying frames has to say
        so where the operator is already looking.
        """
        transport = self.station.transport if self.station is not None else self.session_transport
        if transport is None:
            return self._status
        state = transport.state
        detail = transport.info.detail
        if state is TransportState.OPEN:
            return detail
        if state is TransportState.OPENING:
            return f"{detail} RECONNECTING"
        if state is TransportState.ERROR:
            return f"{detail} DOWN"
        return f"{detail} {state.value}"

    def _refresh_status(self) -> None:
        parts = [f"kissterm {__version__}", self._transport_status()]
        if not self.gate.enabled:
            # First after the version, and always present while it is true.
            # "Why is nothing happening?" must be answerable without opening
            # a menu -- this is the state that explains a failed connect, a
            # silent send line and a beacon that never fires.
            blocked = f" ({self.gate.blocked} held)" if self.gate.blocked else ""
            parts.append(f"TX OFF{blocked}")
        if self.station is not None:
            parts.append(str(self.station.mycall))
        elif self.session_transport is not None:
            # No AX25Station on this tier to read a callsign off, but the
            # operator's own callsign is still `config.mycall` regardless.
            mycall = getattr(self.config, "mycall", "") or ""
            if mycall:
                parts.append(mycall)
        if self.link is not None:
            # The LOGICAL peer, which is the link's own until a hop through
            # it is confirmed (`_commit_hop`). After a hop the link is still
            # to the first node, so showing `link.peer` here left the status
            # bar naming one node while the family badge beside it described
            # a different one -- the same confusion the hop-detection work
            # exists to clear up. `via <link peer>` keeps the real link-layer
            # peer on screen rather than hiding which station is actually
            # carrying the session.
            node = self.current_node or str(self.link.peer)
            where = node if node == str(self.link.peer) else f"{node} via {self.link.peer}"
            peer_part = f"{where} {self.link.state.value}"
            family = self.reference.family
            if family is not None:
                # Short id (e.g. "BPQ32", not the long-form family.name) --
                # this is a status-bar field next to the callsign and link
                # state, not a sentence. Replaces the old inline terminal
                # note `_sniff_node` used to write; see that method.
                peer_part += f" {family.id.upper()}"
            parts.append(peer_part)
            # Frame-level counters exist only on the AX.25 tier -- a session
            # transport (Telnet, SSH, VARA, ...) has no frames to count, and
            # showing "tx 0 rx 0" for one would claim a stat that was never
            # tracked rather than one that is genuinely zero.
            stats = getattr(self.link, "stats", None)
            if stats is not None:
                parts.append(
                    f"tx {stats.frames_sent} rx {stats.frames_received} rtx {stats.retransmits}"
                )
        if getattr(self.config, "accept_incoming", False):
            # The honest counterpart to the opt-in: if this station will
            # transmit with nobody present, that fact is always on screen.
            parts.append("ANSWERING")
        if self.beaconer.running:
            # Same rule. A beacon is unattended transmission on a timer, so
            # it is on screen for as long as it is armed -- not only when it
            # happens to fire.
            parts.append("BEACON")
        if self.aprs_beaconer.running:
            parts.append("APRS BEACON")
        parts.append(f"heard {len(self.heard)}")
        renderable = _status_row(parts)
        for bar in self._base_query("#status-bar"):
            bar.update(renderable)

    def _refresh_heard(self, force: bool = False) -> None:
        """Repaint the heard table.

        Skipped while the tab is hidden -- rebuilding a 500-row table twice a
        second that nobody is looking at is pure waste. `force` exists for the
        moment the tab *becomes* visible: without it the operator switches to
        Heard and sees an empty table until the next interval tick, which reads
        as "nothing has been heard" when in fact everything has.
        """
        if not force:
            tabs = list(self._base_query("#main-tabs"))
            if not tabs or tabs[0].active != "heard":
                return
        # Same "no position set" test `AprsBeaconer` already uses (0.0/0.0 is
        # the field default, not a real station's QTH) -- one convention for
        # "has the operator entered a position", not a second one invented
        # here.
        my_pos = None
        if self.config.aprs.latitude != 0.0 or self.config.aprs.longitude != 0.0:
            my_pos = (self.config.aprs.latitude, self.config.aprs.longitude)
        for pane in self._base_query(HeardPane):
            pane.refresh_from(self.heard, my_position=my_pos)

    @on(TabbedContent.TabActivated, "#main-tabs")
    def _on_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Populate a pane the instant it becomes visible, not on the next tick.

        Any pane whose content is built by a periodic refresh needs a hook
        here, or it shows stale or empty content for up to one interval every
        time the operator switches to it.
        """
        if event.pane.id == "heard":
            self._refresh_heard(force=True)
        elif event.pane.id == "settings":
            # Same rule as the heard table: a pane must be correct the instant
            # it is visible. Re-rendering also discards half-typed edits the
            # operator navigated away from without saving, which is the
            # behaviour that matches "this shows what is in effect".
            self.query_one(SettingsPane).render_settings(self.config)
        self._refresh_status()
