"""The `KissTermApp` class: bindings, pane assembly, and the frame fan-out.

Layout follows the shape a packet operator already has in their head from
BPQTerminal and EasyTerm, because the goal is a familiar tool that happens to
be modern, not a novel one they have to relearn:

    F2 Mail  F3 Bulletins  F4 Files  F5 Terminal  F6 APRS  F7 Heard  F8 Monitor  F9 Settings
    +--------------------------------------------+---------+
    | session output (scrollback, selectable)     | Address |
    +--------------------------------------------+ Book,   |
    | > type here                          [Send] | Ctrl+G  |
    +--------------------------------------------+---------+
      F1 Help  ^T TX  ^N Connect  ^G Book ...  F10 Menu     <- keys for this tab
      kissterm 0.1 | transport | callsign | heard N          <- status, BELOW them

Keys follow IBM CUA as Midnight Commander uses it: F1 Help, F10 the menu,
function keys for tabs, a small set of terminal-safe Ctrl keys, and every
command in the menu. All of it is generated from `commands.COMMANDS`; see
that module and DESIGN.md section 5. A tab's key is printed in its label
(`F5 Terminal`), never in the Footer as well.

**A modal is never a function key.** The command reference -- a modal opened
over whatever tab is active -- is a menu command (and `Ctrl+R` on APRS), not a function key. A non-tab action
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

This also kept the F-row free for Mail, Bulletins and Files (ROADMAP P2). The ceiling was originally set at F8 (some
terminals are unreliable past it), but KC1JMH reports F9/F10 work fine in
practice on the terminals actually in use here, and Midnight Commander --
about as widely deployed a terminal-UI precedent as exists -- has used
F1-F10 for its whole menu row for decades without it being a practical
problem. F11 is out regardless: it is "toggle fullscreen" in enough
terminal emulators and window managers that it rarely reaches the
application at all. **F1 is Help and F10 is the menu, permanently**, so
tabs have F2-F9, and Mail, Bulletins and Files took F2-F4 in front of
Terminal, which fills the whole allowance -- see `commands.COMMANDS` and DESIGN.md
section 5 for the assignment.

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
import contextvars
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from rich.table import Table
from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.timer import Timer
from textual.widgets import Footer, Static, TabbedContent, TabPane, Tabs
from textual.widgets._footer import FooterKey

from .. import __version__
from ..addressbook import AddressBook
from ..netrom import KnownNodes
from .. import aprs
from ..aprs_is import AprsIsWatch
from ..aprs_conversations import ConversationStore, MessageDeduplicator
from ..aprs_notify import Cooldown, evaluate_packet
from ..ax25 import AX25Station, LinkParams, parse_path
from ..ax25.address import AX25Address, AX25AddressError
from ..aprs_beacon import AprsBeaconer
from ..beacon import Beaconer
from ..config import (
    AprsConfig,
    BeaconConfig,
    find_credential,
    find_script,
    mail_path,
    state_path,
)
from ..mail import MessageStore
from ..mail.store import INBOX, MAIL, SENT
from .. import desktop_notify
from ..ax25.frame import PID_NO_LAYER3, AX25Frame, UType
from ..heard import HeardTable
from ..gps import GpsReader
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
from . import commands as cmdreg
from .commands import TAB_ORDER, KeyBindingsProvider
from .menu import MenuScreen
from ..harvested import HarvestedCommands
from ..nodes import Command, CommandReference
from ..nodes.reference import (
    application_named,
    applications_of,
    identify_family,
    parse_harvested,
)
from .dialogs import (
    CallsignScreen,
    CommandReferenceScreen,
    ConnectRequest,
    ConnectScreen,
    AprsObjectScreen,
    AprsObjectRequest,
    AprsIsWatchScreen,
    RadioReminderScreen,
    HomeBbsSetupScreen,
    TranscriptsScreen,
    FileTransferScreen,
)
from .heard_pane import HeardPane
from .monitor_pane import MonitorPane
from .settings_pane import SettingsPane
from .help_pane import HelpPane
from .mail_pane import MessageBrowser, MessageList, bulletins_browser, files_browser, mail_browser
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
    #: session. The Node commands screen shows it after parsing so the operator can
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
    #: The application the node said it handed this session to ("BBS",
    #: "CHAT", a sysop's "CALENDAR"), upper-cased; "" while at the node.
    #: See `KissTermApp._track_application`.
    application: str = ""
    #: The node's own command set, put aside while an application's is in
    #: effect and restored when the node says the session came back.
    node_reference: "CommandReference | None" = None
    #: The unterminated tail of the last chunk received, so a line split
    #: across two frames is still matched whole.
    line_buffer: str = ""


def _status_row(parts: list[str | Text]) -> Table:
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
    """The context bar: the keys that work on this tab, right now.

    Drawn from `commands.COMMANDS` rather than from `Binding.show`, for two
    reasons Textual's own `Footer` cannot meet. It shows only what works
    here (rule 5 of the key standard): an action for another tab, or
    Disconnect with nothing connected, is absent rather than shown and then
    answered with a toast. And it fits the width: Textual's `Footer` scrolls
    its overflow off the right edge with no sign anything is missing, so
    this keeps the longest prefix of `commands.FOOTER_ORDER` that fits and
    pins `F10 Menu` to the end, where everything dropped can still be found.

    A focused list's own `show=True` bindings (Address Book: Enter, Ins, E,
    Del) come right after Help, because while a list has focus those are the
    keys in use. `_on_resize` re-runs the fit: Textual recomposes a Footer
    only when the set of bindings changes, never on width alone.
    """

    def compose(self) -> ComposeResult:
        if not self._bindings_ready:
            return
        app = self.app
        tab = app.active_tab()
        active = self.screen.active_bindings
        chips: list[tuple[str, str, str, str]] = []  # key, display, label, action
        for command in cmdreg.footer_commands(tab):
            if command.action == "menu" or app.command_unavailable(command):
                continue
            chips.append((
                command.key, cmdreg.key_label(command.key), command.footer_label,
                command.action,
            ))
        # The focused widget's own keys, which exist only while it has focus.
        local = [
            (b.key, app.get_key_display(b), b.description, b.action)
            for (node, b, enabled, _tip) in active.values()
            if node is not app and b.show and enabled and b.description
        ]
        if chips and chips[0][3] == "help":
            chips = chips[:1] + local + chips[1:]
        else:
            chips = local + chips
        menu = cmdreg.command_for("menu", tab)
        reserved = cmdreg.chip_width("F10", menu.footer_label) if menu else 0
        fitted = cmdreg.fit_footer(
            [(display, label) for _k, display, label, _a in chips],
            max(self.size.width - reserved, 0),
        )
        chips = chips[: len(fitted)]
        if menu is not None:
            chips.append((menu.key, "F10", menu.footer_label, menu.action))
        for key, display, label, action in chips:
            yield FooterKey(key, display, label, action).data_bind(compact=Footer.compact)

    def _on_resize(self, event: events.Resize) -> None:
        self.refresh_bindings()


#: The launch tab when `Config.start_tab` is empty. Mail: the operator opens
#: kissterm to their messages, not to a prompt (ROADMAP P2, the OutpostPM
#: model). `tests/pilot/conftest.py` pins it to Terminal for the tests
#: written before Mail existed.
DEFAULT_START_TAB = "mail"


class KissTermApp(App):
    """The application.

    `config` and `station` are injected rather than constructed here so a
    headless test can mount the app against a loopback transport with no radio,
    no serial port, and no real config directory. Constructing them internally
    would make every UI test require hardware.
    """

    TITLE = "kissterm"

    CSS = APP_CSS

    #: Adds the registry (`commands.KeyBindingsProvider`) to Textual's own
    #: system commands, so Ctrl+P finds every kissterm command by name,
    #: including the ones with no key.
    COMMANDS = App.COMMANDS | {KeyBindingsProvider}

    #: Generated from `commands.COMMANDS`, the one table the Footer, the F10
    #: menu, F1 help and Ctrl+P also read. Do not add a `Binding` here: add a
    #: `Command` there, inside the key standard that
    #: `tests/unit/test_key_standard.py` enforces (DESIGN.md section 5).
    BINDINGS = cmdreg.app_bindings()

    def __init__(
        self,
        config,
        station: AX25Station | None = None,
        session_transport=None,
        transport_problem: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.config = config
        #: The message store behind Mail, Bulletins and Files. Under the
        #: platformdirs data directory, so `_isolate` redirects it in tests.
        self.mail_store = MessageStore(mail_path())
        try:
            self.mail_store.ensure_default_tree()
        except OSError:
            # An unwritable data directory must not stop the terminal from
            # starting; the Mail tab just shows nothing.
            pass
        #: Why the configured transport would not open at launch, when the
        #: operator chose to start anyway (`kissterm/__main__.py`). On mount
        #: the app lands on Settings > Radio with this in front of them,
        #: because that is the page that fixes it -- see `_show_transport_problem`.
        self._transport_problem = transport_problem
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
        #: True while Send/Receive runs (`action_get_mail`); one at a time.
        self._collecting = False
        #: A background job's status-bar field ("Receiving 1 of 3"), shown green.
        self._activity = ""
        # What each Terminal tab last dialed, for Ctrl+R Reconnect: the whole
        # request (hops, login, port), not just the callsign, so a reconnect
        # to a station reached through two nodes goes back the same way.
        self._last_connect: dict[str, ConnectRequest] = {}
        self._last_connect_key = ""
        #: The one in-flight SessionTransport.connect() call, if any. Session
        #: transports have no AX.25 link for Ctrl+D to close during setup, so
        #: the task itself is the cancellation handle. It is set only while
        #: awaiting connect(), not for an established session or login script.
        self._session_connect_task: asyncio.Task[object] | None = None
        # Launching without a transport is intentional: Settings is where an
        # operator adds or repairs one, and refusing to mount the TUI turns a
        # missing entry into a command-line dead end.
        self._status = "NO TRANSPORT - F9 Settings"
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
        #: APRS-IS diagnostics are separate from the RF transport fan-out.
        #: The current UI opens this object only with a ``pass -1`` login.
        self.aprs_is_watch = AprsIsWatch()
        self._aprs_is_background_started = False
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
            position_source=self._gps_position if config.aprs.gps_device.strip() else None,
            motion_source=self._gps_fix if config.aprs.gps_device.strip() else None,
        )
        #: A GPS reader is optional and wholly local; it never participates in
        #: the AX.25/KISS transport fan-out.
        self.gps_reader: GpsReader | None = None
        self._gps_had_fix = False

    # ------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield KissTermHeader(show_clock=True)
        with TabbedContent(initial=self._start_tab(), id="main-tabs"):
            # Help first: it is on F1, and the row reads F1 to F9 left to
            # right. See `help_pane.py` for why it is a tab, not a modal.
            with TabPane("F1 Help", id="help"):
                yield HelpPane()
            with TabPane("F2 Mail", id="mail"):
                yield mail_browser(self.mail_store)
            with TabPane("F3 Bulletins", id="bulletins"):
                yield bulletins_browser(self.mail_store)
            with TabPane("F4 Files", id="files"):
                yield files_browser(self.mail_store)
            with TabPane("F5 Terminal", id="terminal"):
                yield TerminalPane()
            with TabPane("F6 APRS", id="aprs"):
                yield AprsPane()
            with TabPane("F7 Heard", id="heard"):
                yield HeardPane()
            with TabPane("F8 Monitor", id="monitor"):
                yield MonitorPane()
            with TabPane("F9 Settings", id="settings"):
                yield SettingsPane()
        # Status bar and Footer share one bottom-docked container. Docking
        # them both individually puts them in the SAME region -- the Footer
        # paints over the status bar and it is invisible, in either yield
        # order. One docked parent with an explicit height lays them out as
        # two distinct rows. Verified in tests/pilot/test_app_mounts.py.
        with Vertical(id="bottom-bar"):
            yield KissTermFooter(show_command_palette=False)
            yield Static(id="status-bar")

    def _start_tab(self) -> str:
        """`Config.start_tab` when it names a tab, else `DEFAULT_START_TAB`."""
        wanted = getattr(self.config, "start_tab", "")
        return wanted if wanted in TAB_ORDER else DEFAULT_START_TAB

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
        self._attach_station()
        if self._transport_problem:
            banner = (
                f"kissterm {__version__} -- the modem did not answer at startup "
                f"({self._transport_problem}). Fix it in F9 Settings > Radio, "
                "then Save to try again.\n"
            )
        elif self.station is None and self.session_transport is None:
            banner = (
                f"kissterm {__version__} -- no transport configured. "
                "Open F9 Settings, then Transports to add one.\n"
            )
        else:
            banner = (
                f"kissterm {__version__} -- Ctrl+N to connect, F1 for help, "
                "F10 for the menu.\n"
            )
        self.query_one(TerminalPane).write_note("", banner)
        self.apply_runtime_settings()
        if not self.config.mycall or (
            self.station is None
            and self.session_transport is None
            and not self.config.transports
        ):
            # Defer until the root screen has completed its first layout.
            # Pushing a modal directly from on_mount races Textual's initial
            # focus pass and can leave the callsign box unfocused.
            self.call_after_refresh(self._show_onboarding)
        elif self._transport_problem:
            self.call_after_refresh(self._show_transport_problem)
        else:
            self.call_after_refresh(self._focus_start_tab)

    def _focus_start_tab(self) -> None:
        """Focus the launch tab's working widget, as a tab switch does, so
        the Mail list's keys (G) work and show from the first keystroke."""
        # The tab showing now, not the configured one, and only into a
        # vacuum: focusing a widget in a pane already left re-activates it
        # (`action_show_tab`'s docstring).
        tabs = self.query_one("#main-tabs", TabbedContent)
        # Textual's own first focus lands on the tab strip; that is not a
        # choice anyone made, so it counts as empty.
        strip = isinstance(self.focused, Tabs) and self.focused.parent is tabs
        if (self.focused is not None and not strip) or self.screen is not self.screen_stack[0]:
            return
        # Only the message tabs: Terminal and APRS have their own startup
        # focus, and a tab already switched away from is left alone.
        if tabs.active != self._start_tab() or tabs.active not in ("mail", "bulletins", "files"):
            return
        target = self._TAB_FOCUS.get(tabs.active)
        if target is not None:
            # `set_focus`, not `widget.focus()`: that one is deferred, and a
            # tab switch landing in between would have it pull focus -- and
            # the tab -- back to the pane just left.
            with contextlib.suppress(Exception):
                self.set_focus(self.query_one(target))
                # The Footer is redrawn on a tab switch, not on focus; without
                # this the list's keys (G) stayed off it until something else
                # redrew it.
                self.query_one(KissTermFooter).refresh_bindings()

    def _show_transport_problem(self) -> None:
        """Land on Settings > Radio after a startup open failed.

        The operator was asked at the shell and chose to start anyway; the
        point of starting is to fix the transport, so put them on the page
        that does it instead of making a newcomer find it. Saving there
        retries the open (`SettingsPane._save` -> `_switch_frame_transport`),
        so once the modem software is running, Save is all it takes.
        """
        self.query_one("#main-tabs", TabbedContent).active = "settings"
        self.query_one(SettingsPane).show_section("Radio")
        self.notify(
            f"Could not open the modem: {self._transport_problem}. Start your modem "
            "software or check the address here, then Save to try again.",
            severity="warning",
            timeout=15,
        )

    def _show_onboarding(self) -> None:
        """Guide a fresh install through its one required identity setting.

        This is deliberately UI-first: a missing callsign should not force a
        newcomer back to a shell prompt.  `--setup` remains the plain-terminal
        recovery route for operators who explicitly ask for it.
        """
        from .dialogs import OnboardingScreen

        self.push_screen(OnboardingScreen(self.config.mycall), self._finish_onboarding)

    def _finish_onboarding(self, request) -> None:
        if request is None:
            # There is no useful terminal session without an identity, and
            # quitting is clearer than leaving a new operator at a disabled
            # send line that cannot ever connect.
            if not self.config.mycall:
                self.exit()
            else:
                self.notify("Add a transport in Settings when you are ready.")
            return

        self.config.mycall = request.callsign
        # Existing profiles may carry the old explicit empty defaults.  Seed
        # the onboarding defaults without overwriting a gateway an operator
        # already chose deliberately.
        if not self.config.aprs_sms_gateway:
            self.config.aprs_sms_gateway = "SMSGTE"
        if not self.config.aprs_email_gateway:
            self.config.aprs_email_gateway = "EMAIL-2"
        # A guided setup is an explicit safety reset: it must never carry an
        # old, opaque "enable at startup" value into a newly configured
        # station.  The operator can still deliberately enable that advanced
        # option later in Settings.
        self.config.tx_armed_at_start = False
        self.gate.set(False)
        saved = self._save_config()
        self.query_one(SettingsPane).render_settings(self.config)
        if request.set_up_transport:
            main_tabs = self.query_one("#main-tabs", TabbedContent)
            main_tabs.active = "settings"
            self.query_one(SettingsPane).show_section("Radio")
            self.notify(
                "Callsign saved. Add a transport with New or Scan for hardware.",
                severity="information",
            )
        else:
            where = "saved" if saved else "kept for this session only"
            self.notify(f"Callsign {request.callsign} {where}. Set up a transport when ready.")

    def _attach_station(self) -> None:
        """Attach the one frame fan-out after a station becomes available."""
        if self.station is None:
            return
        self._attach_transport(self.station.transport)
        self.station.on_incoming.append(self._on_incoming_link)

    def _attach_transport(self, transport) -> None:
        """Wire the app onto `transport`: gate, context and fan-out.

        Called at startup and again after a live transport switch, which is
        why the station's own `on_incoming` is not in here -- that belongs to
        the station and survives a switch. Everything below belongs to the
        transport and does not.
        """
        transport.gate = self.gate
        # Runs on the app's own message loop, so this is a context in which
        # Textual's `active_app` is this app. The transport was opened before
        # the app existed; see `FrameTransport.callback_context` for what
        # breaks if received frames are not handled in this context.
        transport.callback_context = contextvars.copy_context()
        self._unsubscribe_monitor = transport.subscribe(self._on_received_frame)
        self._unsubscribe_aprs = transport.subscribe(self._on_aprs_frame)
        transport.on_sent.append(self._on_sent_frame)
        self._status = f"{transport.info.detail}"

    def _detach_transport(self, transport) -> None:
        """Undo `_attach_transport`, so a replaced transport feeds nothing."""
        self._unsubscribe_monitor()
        self._unsubscribe_aprs()
        self._unsubscribe_monitor = lambda: None
        self._unsubscribe_aprs = lambda: None
        with contextlib.suppress(ValueError):
            transport.on_sent.remove(self._on_sent_frame)

    async def _open_initial_transport(self, name: str) -> bool:
        """Open the first saved transport in an already-mounted onboarding app.

        Opening a transport does not transmit.  It merely makes the same
        station/fan-out wiring that normal startup builds available now, so
        the operator can proceed directly from onboarding to APRS or a
        connection instead of having to understand why a restart is needed.
        """
        if self.station is not None or self.session_transport is not None:
            return False
        entry = next((item for item in self.config.transports if item.get("name") == name), None)
        if entry is None:
            return False
        from .. import transport as transport_mod
        from ..transport.base import FrameTransport

        try:
            transport = transport_mod.build_transport(entry)
            await transport.open()
        except Exception as exc:
            log.exception("could not open initial transport %s", name)
            self.notify(f"Saved {name}, but could not open it: {exc}", severity="error")
            return False

        transport.gate = self.gate
        if isinstance(transport, FrameTransport):
            self.station = AX25Station(
                AX25Address.parse(self.config.mycall),
                transport,
                LinkParams(
                    paclen=self.config.paclen, window=self.config.window,
                    modulo=self.config.modulo, retries=self.config.retries,
                    connect_retries=self.config.connect_retries,
                    sabm_on_poll=self.config.sabm_on_poll, t1=self.config.t1,
                    t2=self.config.t2, t3=self.config.t3,
                ),
                aliases=tuple(AX25Address.parse(item) for item in self.config.mycall_aliases),
                accept_incoming=self.config.accept_incoming,
                max_links=MAX_TERMINAL_TABS,
            )
            self.beaconer.station = self.station
            self.aprs_beaconer.station = self.station
            self._attach_station()
        else:
            self.session_transport = transport
            self._status = transport.info.detail
        self._refresh_status()
        return True

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
        self._restart_gps()
        self._restart_aprs_beacon()
        self._reconcile_aprs_is_debug_watch()
        self._watch_notifier = self._make_watch_notifier()

    def _reconcile_aprs_is_debug_watch(self) -> None:
        """Apply the opt-in background APRS-IS diagnostic setting.

        It is deliberately tied to actual debug logging: a background TCP
        stream is useful only when its correlation evidence is being kept.
        A manually opened or SMS-triggered watcher is never stopped here.
        """
        enabled = self._aprs_is_background_requested()
        debug_logging = log.isEnabledFor(logging.DEBUG)
        if enabled and debug_logging and not self.aprs_is_watch.running:
            try:
                self.aprs_is_watch.start(callsign=self._active_aprs_identity())
            except ValueError as exc:
                log.debug("APRS-IS background watch not started: %s", exc)
            else:
                self._aprs_is_background_started = True
                log.debug("APRS-IS background watch enabled")
        elif self._aprs_is_background_started and (not enabled or not debug_logging):
            self.aprs_is_watch.stop()
            self._aprs_is_background_started = False

    def _aprs_is_background_requested(self) -> bool:
        """Whether the configured debug monitor owns the APRS-IS client."""
        return bool(
            getattr(self.config, "aprs_is_watch_debug", False)
            and log.isEnabledFor(logging.DEBUG)
        )

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
        self._to_terminal(self._active_key(), "write_note", f"\n*** Beacon sent to {frame.path.destination}\n")

    def _gps_position(self) -> tuple[float, float] | None:
        """The receiver's live position, never copied into configuration."""
        fix = self.gps_reader.fix if self.gps_reader is not None else None
        return (fix.latitude, fix.longitude) if fix is not None else None

    def _gps_fix(self):
        """The live GPS motion record, never persisted or transmitted alone."""
        return self.gps_reader.fix if self.gps_reader is not None else None

    def _on_gps_fix(self, fix) -> None:
        """Start a waiting periodic beacon when a receiver first fixes."""
        had_fix, self._gps_had_fix = self._gps_had_fix, fix is not None
        # A GPS-configured beacon correctly refuses to start without a fix.
        # Starting it on the false->true edge retains its normal sleep-first
        # behavior while avoiding a stale-coordinate fallback or a polling
        # timer that would only keep discovering it has no position.
        if fix is not None and not had_fix:
            self._restart_aprs_beacon()
        # This only changes the existing beaconer's next deadline or queues
        # a corner peg. It never arms TX; its send path rechecks the gate.
        self.aprs_beaconer.note_fix(fix)

    @work
    async def _restart_gps(self) -> None:
        """Replace the local NMEA reader after a Settings save."""
        if self.gps_reader is not None:
            await self.gps_reader.stop()
        device = self.config.aprs.gps_device.strip()
        self.gps_reader = GpsReader(device) if device else None
        self._gps_had_fix = False
        if self.gps_reader is not None:
            self.gps_reader.subscribe(self._on_gps_fix)
            self.gps_reader.start()

    @work
    async def _restart_aprs_beacon(self) -> None:
        """Stop then start the APRS position beacon -- see `_restart_beacon`
        for why a live mutation is wrong here too: a half-changed config
        transmitting under the operator's callsign is never acceptable.
        """
        await self.aprs_beaconer.stop()
        self.aprs_beaconer.station = self.station
        self.aprs_beaconer.config = getattr(self.config, "aprs", None) or AprsConfig()
        self.aprs_beaconer.position_source = (
            self._gps_position if self.aprs_beaconer.config.gps_device.strip() else None
        )
        self.aprs_beaconer.motion_source = (
            self._gps_fix if self.aprs_beaconer.config.gps_device.strip() else None
        )
        why = self.aprs_beaconer.start()
        if why and self.aprs_beaconer.config.enabled and why != "transmit is disabled":
            self.notify(f"APRS beacon not started: {why}", severity="warning")

    def _on_aprs_beacon_sent(self, frame: AX25Frame) -> None:
        """Same rule as `_on_beacon_sent`: every transmission is visible."""
        self._to_terminal(self._active_key(), "write_note", "\n*** APRS position beacon sent\n")

    def on_unmount(self) -> None:
        """Disarm the beacons as the app goes away.

        Not merely tidy: a beacon task still armed while the UI is being torn
        down would transmit under the operator's callsign with nothing on
        screen to show it -- and nowhere to show it.
        """
        self.beaconer.cancel()
        self.aprs_beaconer.cancel()
        self.aprs_is_watch.stop()
        if self.gps_reader is not None:
            self.gps_reader.cancel()
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
                self._active_key(), "write_note", f"\n*** Plugged in: {event.device} -- {event.detail}\n"
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
            self._to_terminal(self._active_key(), "write_note", f"\n*** {event.device} was unplugged\n")
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
            "write_note",
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
                    "write_note",
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
        self._to_terminal(self._active_key(), "write_note", f"\n*** Auto-ack sent to {addressee} (msg {number})\n")

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
        self._to_terminal(self._active_key(), "write_note", f"\n*** {verb} APRS {kind} to {addressee}\n")
        return True

    def start_aprs_is_watch_for_debug(self) -> None:
        """Begin a receive-only observation before a deliberate SMS request.

        This starts no RF activity and does not wait for the Internet before
        sending: delaying a requested RF message for a diagnostic connection
        would be the wrong priority. The debug log records whether APRS-IS
        later saw the packet and any reply addressed back to this identity.
        """
        if not log.isEnabledFor(logging.DEBUG) or self.aprs_is_watch.running:
            return
        try:
            callsign = self._active_aprs_identity()
            self.aprs_is_watch.start(callsign=callsign)
            log.debug("APRS-IS watch auto-started for SMS diagnostic: %s", callsign)
        except ValueError as exc:
            log.debug("APRS-IS watch not started for SMS diagnostic: %s", exc)

    def action_aprs_gateway_form(self) -> None:
        """Open the APRS gateway form only in its relevant pane."""
        self.query_one(AprsPane).show_gateway_form()

    def action_aprs_bulletin(self) -> None:
        """Prepare a bulletin in APRS context; preparation never sends."""
        self.query_one(AprsPane).action_compose_bulletin()

    async def _send_aprs_object(self, request: AprsObjectRequest) -> bool:
        """Encode and transmit one deliberately composed APRS object report."""
        if self.station is None:
            return False
        gate = getattr(self.station.transport, "gate", None)
        if gate is not None and not gate.enabled:
            return False
        try:
            target = parse_path(f"APRS {self.config.aprs.path}".strip())
            via = target.repeaters
            if request.scope == "rf_only":
                # APRS reserves RFONLY in the digi field as the originating
                # operator's instruction not to gate RF traffic to APRS-IS.
                # Keep the configured RF path so an EOC beyond direct range
                # can still receive the exercise object over radio.
                if not any(str(digi) == "RFONLY" for digi in via):
                    via = (*via, AX25Address.parse("RFONLY"))
            elif request.scope == "direct":
                via = ()
            timestamp = datetime.now(UTC).strftime("%d%H%Mz")
            payload = aprs.object_report(
                request.name, request.alive, timestamp, request.latitude,
                request.longitude, request.symbol[0], request.symbol[1], request.comment,
            )
            outframe = aprs.beacon_frame(
                self.config.aprs.source_for(str(self.station.mycall)),
                target.destination, via, payload,
            )
            await self.station.transport.send_frame(outframe, 0)
        except Exception as exc:
            log.debug("APRS object %s not sent: %s", request.name, exc)
            return False
        # This is deliberately after ``send_frame``: the transport only
        # returns once its backend accepted the frame. The object payload is
        # strict printable ASCII, so retaining it verbatim gives an
        # independently inspectable on-air record without logging arbitrary
        # received bytes.
        log.debug("APRS object transmission accepted: %s:%s", outframe.path, payload.decode("ascii"))
        state = "live" if request.alive else "killed"
        self._to_terminal(self._active_key(), "write_note", f"\n*** Sent {state} APRS object {request.name.strip()}\n")
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

    def can_disconnect_active_session(self) -> bool:
        """Whether Ctrl+D has something real to disconnect or cancel."""
        key = self._active_key()
        link = self.link
        return bool(
            (link is not None and getattr(link, "connected", False))
            or key in self._connecting
            or (
                key == ""
                and self._session_connect_task is not None
                and not self._session_connect_task.done()
            )
        )

    def can_transfer_on_active_session(self) -> bool:
        """Whether the active terminal session has a live byte stream."""
        link = self.link
        return bool(link is not None and getattr(link, "connected", False))

    def _refresh_context_footer(self) -> None:
        """Recompose footer keys when tab or active-link state changes."""
        for footer in self._base_query(KissTermFooter):
            footer.refresh_bindings()

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
        self._to_terminal(key, "write_note", f"\n*** Incoming connection from {link.peer}\n")
        if not self.gate.enabled:
            # The UA never went out, so the caller is talking to nobody. Say
            # so: "somebody called and you could not answer" is exactly the
            # thing an operator wants to find in the scrollback later.
            self._to_terminal(
                key,
                "write_note",
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
        session.reference = CommandReference(learned=self._learned(str(link.peer), "node"))
        self._sessions[key] = session
        self.query_one(TerminalPane).open_tab(key, activate=activate)
        self._start_transcript(key, link)
        link.on_data.append(lambda data: self._on_link_data(key, data))
        link.on_state.append(lambda state: self._on_link_state(key, state))
        link.on_error.append(lambda why: self._note(key, f"\n*** {why}\n"))
        self._to_terminal(key, "set_placeholder", f"connected to {link.peer}")
        self._refresh_context_footer()
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
        """Open a transcript for `session_key`, if recording is enabled.

        The status bar carries the compact recording indicator; a full path
        is available from the menu (Session > Transcripts) without consuming live terminal rows.
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
            self._to_terminal(session_key, "write_note", f"\n*** No transcript: {transcript.failed}\n")
            return
        session = self._sessions.get(session_key)
        if session is not None:
            session.transcript = transcript
        self._refresh_status()

    def _close_transcript(self, session_key: str) -> None:
        session = self._sessions.get(session_key)
        if session is not None and session.transcript is not None:
            session.transcript.close()
            session.transcript = None
            self._refresh_status()

    def _close_all_transcripts(self) -> None:
        """Every session's, on shutdown -- see `on_unmount`."""
        for key in list(self._sessions):
            self._close_transcript(key)

    def _note(self, session_key: str, text: str) -> None:
        """A local note for one session: to its tab, and to its transcript."""
        self._to_terminal(session_key, "write_note", text)
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
        # A node's prompt has no line end ("CCEMA:WS1EC-15} "); the line the
        # operator typed ends it. Without this the node's reply is read as a
        # continuation of the prompt and "Connected to BBS" never matches.
        session.line_buffer = ""
        if session.transcript is not None:
            session.transcript.sent(text)
        if watch_hop:
            self._watch_typed_hop(session_key, text)
        self._cancel_reply_timer(session_key)
        # Not for a blank line: that is a nudge, and a node owes it no reply.
        # From a real report (CCEMA, 2026-09-22): with the prompt hidden, the
        # operator pressed Enter on an empty line, the node rightly said
        # nothing, and this note then blamed the far end while the node was
        # waiting on the operator.
        if text.strip() and session.link is not None and session.link.connected:
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
        session.reference = CommandReference(learned=self._learned(node, "node"))
        session.detect_buffer = ""
        session.application = ""
        session.node_reference = None
        session.line_buffer = ""
        self._refresh_status()
        self.query_one(KissTermFooter).refresh_bindings()

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
            session.transcript.received_stream(data, sanitize)
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
        forever would let ordinary message text trigger a false match. Once
        the family is known, `_track_application` watches for the family's
        own, specific enter/return lines for the rest of the session.
        """
        session = self._sessions.get(session_key)
        if session is None:
            return
        text = sanitize(data)
        if (
            session.reference.family is None
            and not session.application
            and len(session.detect_buffer) <= 2048
        ):
            session.detect_buffer += text
            family = identify_family(session.detect_buffer)
            if family is not None:
                # Set the `family` field in place rather than replacing the
                # whole `CommandReference` -- a wholesale replacement here
                # would silently drop `learned` commands `_bind_link` already
                # pre-populated from a past harvest of this same peer.
                #
                # No inline terminal note here -- the family name is shown in
                # the status bar instead (`_refresh_status`). Announcing it a
                # second time in the scrollback is the duplication AGENTS.md's
                # "one place for each fact" rule covers.
                session.reference.family = family
                if family.kind == "application":
                    # Connected straight to a BBS: its harvested names, not
                    # the node-context ones `_bind_link` assumed.
                    session.reference.learned = self._learned(
                        session.current_node, family.harvest_context
                    )
                self._refresh_status()
        self._track_application(session, text)

    def _learned(self, node: str, context: str) -> tuple[Command, ...]:
        """Names harvested from `node` in one context, as `Command`s.

        Filtered by context because "L" harvested inside the BBS and "L"
        harvested at the node prompt are different commands; offering the
        BBS's at the node is the mix-up the command catalog (docs/CHANGELOG.md, 2026-09-23) ended.
        """
        return tuple(
            Command(name=command.name, confidence="learned", context=command.context)
            for command in self._harvested.records_for_callsign(node)
            if command.context == context
        )

    @staticmethod
    def _context_of(session: _TerminalSession) -> str:
        """The harvest context (node / bbs / application) in effect."""
        family = session.reference.family
        if family is not None and family.kind == "application":
            return family.harvest_context
        return "application" if session.application else "node"

    def learned_node(self, session_key: str) -> tuple[str, int]:
        """The node this session's learned commands are filed under, and how
        many there are -- for the reference screen's "Forget learned"."""
        session = self._sessions.get(session_key)
        if session is None or session.link is None:
            return ("", 0)
        node = session.current_node or str(session.link.peer)
        return (node, len(self._harvested.records_for_callsign(node)))

    def forget_learned(self, session_key: str) -> int:
        """Drop everything learned from this session's node, from the cache
        and from the live references. Sends nothing."""
        node, _count = self.learned_node(session_key)
        if not node:
            return 0
        dropped = self._harvested.forget(node)
        session = self._sessions[session_key]
        session.reference.learned = ()
        if session.node_reference is not None:
            session.node_reference.learned = ()
        self._to_terminal(
            session_key, "write_note", f"\n*** Forgot {dropped} learned command(s) for {node}.\n"
        )
        return dropped

    def reference_sections(self, session_key: str) -> tuple[CommandReference, ...]:
        """The command sets reachable from where this session is, other than
        the one in effect: the node's while inside its BBS, and the node's
        applications (BPQMail, BPQChat) either way.

        The Node commands screen lists these after the current context's commands,
        so an operator at a node prompt can look up a BBS command before
        spending the airtime to enter the BBS.
        """
        session = self._sessions.get(session_key)
        if session is None:
            return ()
        current = session.reference
        node_reference = session.node_reference if session.application else current
        sections: list[CommandReference] = []
        if session.application and node_reference is not None:
            sections.append(node_reference)
        node_family = node_reference.family if node_reference is not None else None
        if node_family is not None and node_family.kind == "node":
            for family in applications_of(node_family):
                if family is current.family:
                    continue
                sections.append(
                    CommandReference(
                        family=family,
                        learned=self._learned(session.current_node, family.harvest_context),
                    )
                )
        return tuple(sections)

    def harvest_context(self, session_key: str) -> str:
        """What a `?` asked now would be answered by, for the confirm
        screen's default -- the operator can still change it."""
        session = self._sessions.get(session_key)
        return self._context_of(session) if session is not None else "node"

    def _track_application(self, session: _TerminalSession, text: str) -> None:
        """Follow the session into and out of a node's applications.

        A BPQ32 node says "CCEMA:WS1EC-15} Connected to BBS" when it hands
        the session to its BBS, and "Returned to Node" when one hands it
        back. Between the two, BPQMail's commands are in effect and the
        node's are not -- "L" lists mail there and links at the node, so a
        suggestion from the wrong one is a wrong command. Both lines come
        from the identified node family's data (`enter_pattern`,
        `return_pattern`), so nothing here is BPQ-specific, and a node with
        neither is simply never tracked.

        An application kissterm ships no reference for (a sysop's own
        CALENDAR) gets an empty command set: suggesting the node's commands
        there would be a guess. The node uses the same "Connected to" words
        for a STAY hop to another node (G8BPQ's example: "Connected to
        GB7YDX"), so while a typed hop is being watched an unknown name is
        left to `_commit_hop`; only a shipped application's name is taken.
        """
        node = (
            session.node_reference.family
            if session.node_reference is not None
            else session.reference.family
        )
        if node is None or node.kind != "node" or not (node.enter_pattern or node.return_pattern):
            return
        pending = session.line_buffer + text
        *lines, tail = re.split(r"\r\n|\r|\n", pending)
        session.line_buffer = tail[-512:]
        try:
            if session.application:
                # The return line is followed by the node's prompt with no
                # line end, so the unterminated tail counts too.
                if node.return_pattern and any(
                    re.search(node.return_pattern, line) for line in (*lines, tail)
                ):
                    session.reference = session.node_reference or CommandReference()
                    session.node_reference = None
                    session.application = ""
                    session.line_buffer = ""
                    self._refresh_status()
                return
            if not node.enter_pattern:
                return
            for line in lines:
                match = re.search(node.enter_pattern, line)
                if match is None:
                    continue
                name = match.group(1).upper()
                family = application_named(name)
                if family is None and session.hop_watch_task is not None:
                    continue
                session.node_reference = session.reference
                session.application = name
                context = family.harvest_context if family is not None else "application"
                session.reference = CommandReference(
                    family=family, learned=self._learned(session.current_node, context)
                )
                self._refresh_status()
                return
        except re.error:
            log.warning("bad enter/return pattern in family %s", node.id)

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
        # Do not let a second, unanswered harvest make the Node commands screen
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
        self._to_terminal(session_key, "write_note", "?\n")
        self.log_sent(session_key, "?")
        self._to_terminal(
            session_key, "write_note", "\n*** Asked the node for its command list...\n"
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
                session_key, "write_note", "\n*** No commands recognised in the reply.\n"
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
        session.reference.learned = self._learned(node, self._context_of(session))
        self._to_terminal(
            session_key,
            "write_note",
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
        self._refresh_context_footer()

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
            "write_note",
            f"\n*** {link.peer} acknowledged that -- no reply yet. See "
            "Monitor (F8) for what has come back since.\n",
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
            self._to_terminal(self._active_key(), "write_note", "\n*** Transmit enabled\n")
        else:
            blocked = ""
            self.notify(
                "Transmit DISABLED. Nothing will be sent." + blocked,
                severity="warning",
            )
            self._to_terminal(self._active_key(), "write_note", "\n*** Transmit disabled\n")
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
        step (the manual text beacon) still does not arm: that is
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
            self._active_key(), "write_note", f"\n*** Transmit enabled automatically for: {what}\n"
        )
        self.notify(f"Transmit ENABLED for {what}. Ctrl+T turns it back off.")
        self._refresh_status()

    @work
    async def action_beacon_now(self) -> None:
        """Send one BTEXT beacon now (menu: Session > Send beacon).

        The timed beacon waits a full interval before its first
        transmission, because launching the app is not a request to key the
        radio. This is how an operator says "yes it is, right now" -- the
        role JS8Call's heartbeat button plays. It does not enable the timer
        and does not need it on. It does not arm the gate: a closed gate is
        reported and nothing is sent.
        """
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
        """Menu: APRS > Send position -- transmit one position report now.

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

    @work
    async def action_aprs_is_watch(self) -> None:
        """Open the receive-only APRS-IS diagnostic stream for this call."""
        await self.push_screen_wait(
            AprsIsWatchScreen(
                self.aprs_is_watch,
                self._active_aprs_identity(),
                stop_on_close=not self._aprs_is_background_requested(),
            )
        )

    @work
    async def action_toggle_aprs_beacon(self) -> None:
        """Menu: APRS > Position beacon on/off."""
        await self._toggle_aprs_beacon_quick()

    async def _toggle_aprs_beacon_quick(self) -> None:
        """Flip `config.aprs.enabled` from the menu (APRS > Position beacon),
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
        direction: the text beacon's Send beacon is a one-shot
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
        """Flip `Config.aprs.filter_by_ssid` (menu: APRS > SSID filter) -- see
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

    # --- The command registry, applied --------------------------------
    #: Cached because `check_action` runs for every binding on every Footer
    #: render, and a DOM query per check is work done thousands of times a
    #: session for a widget that never moves.
    _main_tabs: TabbedContent | None = None

    def active_tab(self) -> str:
        """The main tab's id, or "" before it is composed."""
        tabs = self._main_tabs
        if tabs is None or not tabs.is_attached:
            tabs = None
            for found in self._base_query("#main-tabs"):
                tabs = found
                break
            self._main_tabs = tabs
        return tabs.active if tabs is not None else ""

    def command_unavailable(self, command: cmdreg.Command) -> str:
        """Why this command cannot run now, or "" if it can. The tab is not
        a reason: the menu switches to the command's tab first. This is only
        the state the operator would have to change."""
        action = command.action
        if action == "disconnect" and not self.can_disconnect_active_session():
            return "not connected"
        if action == "file_transfer" and not self.can_transfer_on_active_session():
            return "not connected"
        if action == "close_tab":
            if self.active_tab() == "aprs":
                if not any(p.can_close_active_tab() for p in self._base_query(AprsPane)):
                    return "no conversation open"
            elif not self._active_key():
                return "no session open"
        if action == "reconnect" and self.station is not None:
            # Session tier: Reconnect is Ctrl+N's flow, always available.
            if self.can_disconnect_active_session():
                return "still connected"
            if self._reconnect_request() is None:
                return "nothing dialed yet"
        return ""

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Keys work only where they mean something (key standard rule 5).

        Returning False here does two things: the Footer leaves the key out,
        and the keystroke falls through to the focused widget -- so Ctrl+D
        in the entry line is delete-right until there is something to
        disconnect, and a key pressed on the wrong tab does nothing instead
        of answering with a toast.
        """
        try:
            tab = self.active_tab()
            if tab and not cmdreg.applies_on(action, tab):
                return False
            if action == "disconnect":
                # Never from under a dialog: its text fields use Ctrl+D too.
                if len(self.screen_stack) > 1:
                    return False
                return self.can_disconnect_active_session()
            if action == "close_tab" and len(self.screen_stack) > 1:
                # Ctrl+W in a dialog's text field stays delete-word (Input's
                # own binding) rather than closing a tab behind the dialog.
                return False
        except Exception:
            # A binding check runs on every Footer render; never let one
            # take the app down.
            log.debug("check_action(%s) failed", action, exc_info=True)
        return True

    def get_key_display(self, binding: Binding) -> str:
        """"^N", "F10", "Ins": the same short form the registry uses."""
        if binding.key_display:
            return binding.key_display
        return cmdreg.key_label(binding.key)

    def run_command(self, command: cmdreg.Command) -> None:
        """Run a command chosen from the menu or Ctrl+P, exactly as its key
        would, after switching to its tab if it belongs to one."""
        if command.tabs and self.active_tab() not in command.tabs:
            self.action_show_tab(command.tabs[0])
            self.call_after_refresh(self._run_command_action, command.action)
        else:
            self.call_later(self._run_command_action, command.action)

    async def _run_command_action(self, action: str) -> None:
        await self.run_action(action)

    def action_menu(self, group: str = "") -> None:
        """F10: the menu bar, opened at the heading for this tab's work, or
        at `group` when a heading in the header was clicked."""
        if isinstance(self.screen, MenuScreen):
            self.screen.dismiss(None)
            return
        tab = self.active_tab()
        groups = [
            (title, [(c, self.command_unavailable(c)) for c in entries])
            for title, entries in cmdreg.menu_groups()
        ]
        start_title = group or cmdreg.MENU_GROUP_FOR_TAB.get(tab, "View")
        start = next(i for i, (title, _e) in enumerate(groups) if title == start_title)

        def _chosen(command: cmdreg.Command | None) -> None:
            if command is not None:
                self.run_command(command)

        self.push_screen(MenuScreen(groups, start), _chosen)

    def action_help(self, section: str = "help-keys") -> None:
        """F1: the Help tab, open on the keys of the tab it was pressed from.

        F1 again, from Help, goes back where it came from -- Help is visited,
        and the way back should be the way in. `section` opens a different
        part of it (the F10 menu's Guides, Glossary and About entries).
        """
        current = self.active_tab()
        if current == "help" and section == "help-keys":
            self.action_show_tab(self._help_return_tab)
            return
        if current and current != "help":
            self._help_return_tab = current
        pane = self.query_one(HelpPane)
        pane.show_keys(self._help_return_tab)
        # Node commands opens on the node the operator is talking to, when
        # it has been identified -- that is the list they came for.
        family = self.reference.family
        if family is not None:
            pane.select_family(family.id)
        self.action_show_tab("help")
        self.query_one("#help-tabs", TabbedContent).active = section

    #: Where F1 returns to from Help, and whose keys Help opens on.
    _help_return_tab = "terminal"

    def help_renderable(self, tab: str):
        """`tab`'s purpose and keys, from the registry, with this moment's
        state: which commands cannot run now, and why."""
        from .addressbook_pane import _AddressBookTable
        from .aprs_pane import _AprsContactTable, _ConvoTabs
        from .terminal_pane import _SessionTabs

        widgets = {
            "terminal": [("Address Book", _AddressBookTable), ("session tabs", _SessionTabs)],
            "aprs": [("contacts", _AprsContactTable), ("conversation tabs", _ConvoTabs)],
            "mail": [("the folder and message lists", MessageList)],
            "bulletins": [("the folder and message lists", MessageList)],
            "files": [("the file list", MessageList)],
        }.get(tab, [])
        list_keys = [
            (where, b.key, b.description)
            for where, cls in widgets
            for b in cls.BINDINGS
            if isinstance(b, Binding) and b.description
        ]
        unavailable = {
            c.action: why for c in cmdreg.COMMANDS if (why := self.command_unavailable(c))
        }
        return cmdreg.help_renderable(tab, list_keys, unavailable=unavailable)

    #: Where focus goes when a tab is opened, so the operator can act
    #: immediately: type at the node, type a message, search the monitor.
    #: A tab with nothing worth typing into (Heard, Settings) is absent and
    #: keeps whatever Textual's own activation does.
    _TAB_FOCUS = {
        "terminal": "#session-input",
        "aprs": "#aprs-compose-input",
        "monitor": "#monitor-query",
        # The list, so its keys (Enter, Delete, G) work and show at once.
        "mail": "#mail-browser .mail-list",
        "bulletins": "#bulletins-browser .mail-list",
        "files": "#files-browser .mail-list",
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
        The tab keys from the Terminal pane's send line and from the APRS compose
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

        def _refresh_context_footer() -> None:
            if tabs.active == tab:
                self.query_one(KissTermFooter).refresh_bindings()

        # `TabbedContent.TabActivated` fires before its new pane has fully
        # settled. Refreshing there alone left one stale Footer render (with
        # Terminal's Connect/Disconnect) until a click changed focus. Queue a
        # second refresh after the tab switch's layout pass instead.
        self.call_after_refresh(_refresh_context_footer)
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
        elif active in ("mail", "bulletins", "files"):
            self.query_one(f"#{active}-browser", MessageBrowser).toggle_addressbook()

    def action_toggle_known_nodes(self) -> None:
        """Menu: View > NET/ROM nodes. Collapse passive NET/ROM claims."""
        active = self.query_one("#main-tabs", TabbedContent).active
        if active == "terminal":
            self.query_one(TerminalPane).toggle_known_nodes()

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
            # Nothing is open yet -- a first run, or a launch whose transport
            # would not open and the operator started anyway. There is no
            # station to rebind, so open this one as the first.
            if self.session_transport is None:
                opened = await self._open_initial_transport(name)
                if opened:
                    self._transport_problem = None
                return opened
            return False
        entry = next((t for t in self.config.transports if t.get("name") == name), None)
        if entry is None:
            return False

        from .. import transport as transport_mod
        from ..transport.base import FrameTransport

        try:
            new_transport = transport_mod.build_transport(entry)
            # The operator's gate, before anything can send on it. A freshly
            # built transport's own gate is OPEN (kissterm/tx.py), and left in
            # place it would transmit while the status bar reads TX off.
            new_transport.gate = self.gate
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

        # `rebind_transport` moved only the station's own subscription; the
        # monitor, heard list, APRS decoder and on_sent are the app's to move.
        self._detach_transport(old_transport)
        self._attach_transport(new_transport)
        with contextlib.suppress(Exception):
            await old_transport.close()

        self._refresh_status()
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
            # The operator's gate, before anything can send on it. A freshly
            # built transport's own gate is OPEN (kissterm/tx.py), and left in
            # place it would transmit while the status bar reads TX off.
            new_transport.gate = self.gate
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
        return True

    @work
    async def action_connect(
        self,
        prefill=None,
        target: str = "",
        redial: ConnectRequest | None = None,
        on_link=None,
        on_reached=None,
        focus_session: bool = True,
    ) -> None:
        """Connect to a station, via the dialog or dialed directly.

        `prefill` is an `addressbook.Entry`, passed by `AddressBookPane`
        when the operator dials a saved station instead of typing one into
        Ctrl+N -- everything past this point is the same flow either way:
        the transmit gate, the transport check, the hop chain, the login.
        Dialing is a faster way to reach this method, never a second,
        lighter-weight path into it. `target` only prepopulates the dialog
        for a passive NET/ROM claim; it never dials or arms the transmit gate.
        `redial` is Ctrl+R Reconnect: the request this tab last dialed,
        replayed through the same flow (reminder, gate, hops, login).
        `on_link(link, key)` is called the moment the link is up, before
        anything awaits, and `on_reached(bool)` once the hop chain has (or
        has not) reached the target -- Send/Receive's hooks (`action_get_mail`).
        `focus_session=False` leaves focus alone: Send/Receive runs from the Mail
        tab, and focus in the hidden send line would switch to Terminal.
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
        if redial is not None:
            request = redial
        elif prefill is not None:
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
            # Screen.dismiss() resolves push_screen_wait before Textual's
            # queued screen replacement paints. Yield once before beginning
            # the connect work: a fast local/nearby node could otherwise
            # complete the whole attempt while the just-dismissed "Before
            # connecting" modal was still the visible screen.
            await asyncio.sleep(0)
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
        if key in self._connecting:
            # A second request while the first is still calling (a double
            # click on the dial and on the reminder's Connect, 2026-09-24).
            # Two SABM streams key the radio over the peer's UA, and a join
            # would run the login script twice; say so and drop this one.
            self.notify(f"Already connecting to {path.destination}.", severity="warning")
            return
        self._last_connect[key] = request
        self._last_connect_key = key
        if not pane.has_room_for(key):
            self.notify(
                f"Close a session first -- {MAX_TERMINAL_TABS} connections are "
                "already open.",
                severity="warning",
            )
            return
        # The Address Book and passive NET/ROM claims deliberately share one
        # slide-out. A dial has just become a live session to watch, so close
        # either view before shrinking the terminal column and opening its
        # connection tab. This is after every validation/reminder above: a
        # cancelled dialog must not change the operator's layout.
        pane.close_addressbook_for_connection()
        # A dial from a mail tab's Address Book: the slide-out has done its
        # job, and the connect is watched on Terminal, as from Terminal's own
        # (Send/Receive's `focus_session=False` stays on the Mail tab).
        dialed_from_mail = False
        for browser in self.query(MessageBrowser):
            dialed_from_mail |= browser.close_addressbook(refocus=False)
        if dialed_from_mail and focus_session:
            self.action_show_tab("terminal")
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
                "write_note",
                f"\n*** Not connecting: the link to the TNC at {where} is "
                f"{state.value}, so nothing would reach the air. This is not "
                f"an RF problem -- check the TNC, then Settings (F9) > Test "
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
        self._to_terminal(key, "write_note", f"\n*** Connecting to {path.destination} on port {port}...\n")
        # Set before the await, not after: `AX25Station.connect` registers the
        # link synchronously before it awaits anything, so by the time this
        # coroutine yields control the link is already reachable by peer
        # address -- which is what lets Ctrl+D find and cancel it mid-attempt.
        self._connecting[key] = (path.destination, port)
        self._refresh_context_footer()
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
            self._refresh_context_footer()
        if link is None:
            failed = self.station.link_to(path.destination, port)
            reason = getattr(failed, "last_error", "") if failed else ""
            if reason == CANCELLED_REASON:
                self._to_terminal(key, "write_note", f"*** Connect to {path.destination} cancelled.\n")
                return
            # Say WHY. "No connection" alone cannot be acted on: a DM means
            # the node heard us and refused, which is a configuration problem
            # at one end or the other; silence after N2 tries means the path
            # did not carry, which is an antenna, power or propagation
            # problem. On a marginal path that distinction is the whole
            # diagnosis, and it is already known here.
            attempts = getattr(failed, "rc", 0) if failed else 0
            detail = f" -- {reason}" if reason else ""
            self._to_terminal(key, "write_note", f"*** No connection to {path.destination}{detail}\n")
            if attempts:
                self._to_terminal(
                    key,
                    "write_note",
                    f"*** {attempts} attempt(s) sent. Check the Monitor tab (F8) "
                    "for what went out and what came back.\n",
                )
            # It was up when we started or we would not be here, so a
            # transport that is down NOW dropped during the attempt -- and
            # some of those SABMs never left the process. Say so, or the
            # operator spends the evening on an antenna that is fine.
            if self.station.transport.state is not TransportState.OPEN:
                self._to_terminal(
                    key,
                    "write_note",
                    "*** The link to the TNC dropped during this attempt, so "
                    "some of those frames never reached the radio. Fix that "
                    "first -- this is not an RF failure.\n",
                )
            self.notify(
                f"Could not connect to {path.destination}{detail}", severity="warning"
            )
            return
        self._bind_link(link, key)
        if on_link is not None:
            on_link(link, key)
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
        if focus_session and pane.active_session_key == key:
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
            if on_reached is not None:
                on_reached(False)
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
        if on_reached is not None:
            on_reached(True)

    async def _connect_session_transport(self) -> None:
        """Connect through a session-tier transport (Telnet, SSH, VARA,
        Mercury, kernel AX.25) -- no target dialog, no hop chain, no
        address book.

        There is exactly one destination a session transport can reach:
        whatever host and port (or callsign, for VARA/kernel AX.25) it was
        configured with at startup, in Settings > Radio. Routing that
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
        self.query_one(TerminalPane).close_addressbook_for_connection()
        for browser in self.query(MessageBrowser):
            if browser.close_addressbook(refocus=False):
                self.action_show_tab("terminal")
        self._arm_for(f"connect via {transport.info.detail}")
        self.query_one(TerminalPane).clear("")
        self._to_terminal("", "write_note", f"\n*** Connecting to {transport.info.detail}...\n")
        connect_task = asyncio.current_task()
        assert connect_task is not None
        self._session_connect_task = connect_task
        self._refresh_context_footer()
        try:
            session = await transport.connect()
        except asyncio.CancelledError:
            # Ctrl+D is an operator decision, not a failed connection.
            # SessionTransport implementations clean up their partly-open
            # connection before propagating this cancellation.
            self._to_terminal("", "write_note", "*** Connect cancelled by operator.\n")
            return
        except TransportError as exc:
            self._to_terminal("", "write_note", f"*** Could not connect: {exc}\n")
            self.notify(str(exc), severity="error")
            return
        finally:
            if self._session_connect_task is connect_task:
                self._session_connect_task = None
                self._refresh_context_footer()
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
                self._to_terminal(session_key, "write_note", "*** Hop chain stopped: no longer connected.\n")
                return False
            if not self.gate.enabled:
                self._to_terminal(session_key, "write_note", "*** Hop chain stopped: transmit is off.\n")
                return False
            ok, detail = await self._hop_to(link, session_key, node)
            if not ok:
                extra = f" -- {detail}" if detail else ""
                self._to_terminal(session_key, "write_note", f"*** No connection to {node}{extra}\n")
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
            self._to_terminal(session_key, "write_note", cmd + "\n")
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
        self._to_terminal(session_key, "write_note", f"\n*** Auto-login: sending {len(lines)} line(s)...\n")
        for line in lines:
            if not link.connected:
                self._to_terminal(session_key, "write_note", "*** Auto-login stopped: no longer connected.\n")
                return
            if not self.gate.enabled:
                self._to_terminal(session_key, "write_note", "*** Auto-login stopped: transmit is off.\n")
                return
            await link.send(line.encode("latin-1", "replace") + b"\r")
            self._to_terminal(session_key, "write_note", line + "\n")
            self.log_sent(session_key, line)
            await asyncio.sleep(CONNECT_SCRIPT_LINE_DELAY)

    @work(exclusive=False)
    async def action_compose_mail(self, reply: str = "", quoted: bool | None = False) -> None:
        """Write a message into Mail/BBS/Outbox (Mail tab: Insert, R, Q).

        `reply` is the store ref of the message answered; `quoted` None
        means "as Settings > Mail says" (R), True always quotes (Q).
        Nothing transmits: the message waits in the Outbox.
        """
        from ..config import state_path
        from ..locator import to_grid
        from ..mail import forms
        from ..mail.compose import BBS_OUTBOX, bulletin_choices, radiogram_defaults
        from .compose import (
            ANSWER_STRIP, FORM_PREFIX, RADIOGRAM, RADIOGRAM_ICS213, REPLY_FORM, ComposeScreen,
            reply_form_for,
        )
        from .form_screen import FormScreen
        from .radiogram import RadiogramScreen

        original = None
        if reply:
            try:
                original = self.mail_store.read(reply)
            except (OSError, ValueError) as exc:
                self.notify(f"Cannot open that message: {exc}", severity="error")
                return
        if quoted is None:
            quoted = self.config.reply_quote
        message = await self.push_screen_wait(
            ComposeScreen(str(self.config.mycall or ""), reply_to=original, quoted=bool(quoted),
                          bulletins=bulletin_choices(self.mail_store))
        )
        remembered_at = state_path() / "forms.json"
        aprs = self.config.aprs
        grid = to_grid(aprs.latitude, aprs.longitude) if aprs.latitude or aprs.longitude else ""

        async def fill(form: forms.FormDef, values: forms.Values | None = None):
            draft = await self.push_screen_wait(FormScreen(
                form, mycall=str(self.config.mycall or ""), grid=grid,
                remembered=forms.load_remembered(remembered_at, form.id),
                mail=self._mail_log_entries, values=values,
            ))
            if draft is not None:
                forms.save_remembered(remembered_at, form.id,
                                      forms.to_remember(form, draft.form_values))
            return draft

        if message == REPLY_FORM and original is not None:
            # The original's own blocks, read-only, and the reply's to fill;
            # it goes out as any reply (SR, or SP to the sender).
            found = reply_form_for(original)
            if found is None:
                return
            draft = await fill(*found)
            if draft is None:
                return
            message = await self.push_screen_wait(ComposeScreen(
                str(self.config.mycall or ""), reply_to=original, draft=draft,
            ))
        if message == ANSWER_STRIP and original is not None:
            # The original's request strip as a form; the answer is the
            # reply's text, addressed and titled as any reply.
            draft = await fill(forms.strip_form(forms.find_strip(original.body)))
            if draft is None:
                return
            message = await self.push_screen_wait(ComposeScreen(
                str(self.config.mycall or ""), reply_to=original, draft=draft,
            ))
        if isinstance(message, str) and message.startswith(FORM_PREFIX):
            # A form: fill it in, then address it in the compose screen.
            # A pasted strip is two forms: the paste, then its questions.
            form = forms.get_form(message.removeprefix(FORM_PREFIX))
            draft = await fill(form)
            if draft is not None and form is forms.PASTE_STRIP:
                draft = await fill(forms.strip_form(forms.find_strip(draft.form_values["strip"])))
            if draft is None:
                return
            message = await self.push_screen_wait(
                ComposeScreen(str(self.config.mycall or ""), draft=draft)
            )
        if message in (RADIOGRAM, RADIOGRAM_ICS213):
            # A radiogram has its own form; the compose screen hands over.
            number, place = radiogram_defaults(self.mail_store)
            message = await self.push_screen_wait(RadiogramScreen(
                str(self.config.mycall or ""), number=number, place=place,
                ics213=message == RADIOGRAM_ICS213,
            ))
        if message is None:
            return
        self.mail_store.add(BBS_OUTBOX, message)
        self._reload_mail_tabs()
        self.notify(f"Saved to the Outbox: {message.subject}", timeout=4)

    def _mail_log_entries(self) -> list:
        """Every dated message in a Mail Inbox or Sent folder (BBS,
        Winlink, and their subfolders): what an ICS-309 logs."""
        from ..mail import forms

        entries = []
        for folder in self.mail_store.folders():
            parts = folder.split("/")
            if parts[0] != MAIL or not {INBOX, SENT} & set(parts):
                continue
            for summary in self.mail_store.list(folder):
                if summary.date is not None:
                    entries.append(forms.MailEntry(summary.date, summary.sender, summary.to,
                                                   summary.subject))
        return entries

    @work(exclusive=False)
    async def action_get_mail(self) -> None:
        """Collect mail from the Home BBS (Mail tab, G). ROADMAP P2.

        The connect is `action_connect` with the Home BBS route as a dial:
        the reminder, the transmit gate, the hop chain and the route's own
        login all apply, and nothing here arms anything. The collector
        (`kissterm/mail/collect.py`) subscribes the moment the link is up,
        so the BBS's greeting is not missed, and starts once the chain has
        reached the target. The operator stays where they are: a toast says
        it started, the status bar shows its phase in green while it runs
        ("Sending 1 of 2", "Receiving 2 of 4"),
        and a toast gives the outcome (DESIGN.md section 6). Every line it
        sends is echoed in the session's Terminal tab and the transcript.
        When it finishes, the link is disconnected; Ctrl+D stops it.
        """
        from ..mail.collect import BbsCollector, CollectOptions

        home = self.config.home_bbs
        if self._collecting:
            self.notify("Already getting mail.", severity="warning")
            return
        entry = self.addressbook.find(home.route.strip()) if home.route.strip() else None
        if entry is None:
            # First use, or the entry was forgotten: ask for the one thing
            # Send/Receive cannot run without, then carry on.
            chosen = await self.push_screen_wait(
                HomeBbsSetupScreen(
                    [e.target for e in self.addressbook.entries], missing=home.route.strip()
                )
            )
            entry = self.addressbook.find(chosen) if chosen else None
            if entry is None:
                return
            home.route = entry.target
            self._save_config()
            self.query_one(SettingsPane).render_settings(self.config)
        first = [h.strip() for h in entry.hops.split(",") if h.strip()] or [entry.target]
        peer = parse_path(first[0]).destination
        if any(
            s.link is not None and s.link.connected
            and (s.link.peer.callsign, s.link.peer.ssid) == (peer.callsign, peer.ssid)
            for s in self._sessions.values()
        ):
            self.notify(
                f"Already connected to {peer}. Disconnect first, then press G.",
                severity="warning",
            )
            return
        options = CollectOptions(
            bbs_call=home.call,
            software=home.software,
            ready_text=home.ready_text,
            login_prompt=home.login_prompt,
            login_text=find_credential(self.config, home.credential) if home.credential else "",
        )
        state: dict = {"collector": None, "key": "", "reached": False}

        def on_link(link, key: str) -> None:
            state["key"] = key
            state["collector"] = BbsCollector(
                link,
                self.mail_store,
                options,
                note=lambda text: self._mail_note(key, text),
                sent=lambda text: self._mail_sent(key, text),
                gate_open=lambda: self.gate.enabled,
                progress=self._mail_status,
            )

        def on_reached(reached: bool) -> None:
            state["reached"] = reached

        self._collecting = True
        # The operator stays on the Mail tab: a toast says a connect is under
        # way, and the status bar follows it. The whole session is in the
        # Terminal tab (F5) for anyone who wants to watch.
        self.notify(f"Connecting to {entry.target} to send and receive mail...", timeout=4)
        self._mail_status(f"Connecting to {entry.target}")
        try:
            worker = self.action_connect(
                prefill=entry, on_link=on_link, on_reached=on_reached, focus_session=False
            )
            await worker.wait()
            collector = state["collector"]
            if collector is None:
                self.notify(
                    f"Send/Receive: could not connect to {entry.target}. "
                    "The Terminal tab (F5) says why.",
                    severity="error",
                )
                return
            if not state["reached"]:
                collector.close()
                self.notify(
                    f"Send/Receive: did not reach {entry.target}. The Terminal tab (F5) says why.",
                    severity="error",
                )
                return
            result = await collector.run()
            key = state["key"]
            sent = f"{len(result.sent)} sent, " if result.sent else ""
            if result.stopped:
                self.notify(
                    f"Send/Receive stopped: {result.stopped}. "
                    f"{sent}{len(result.filed)} received.",
                    severity="warning",
                )
            elif result.filed:
                self.notify(f"{sent}{len(result.filed)} new message(s) from the Home BBS.")
            elif result.sent:
                self.notify(f"{len(result.sent)} sent. No new mail on the Home BBS.")
            else:
                self.notify("No new mail on the Home BBS.", timeout=4)
            self._reload_mail_tabs()
            await self._disconnect_session(key)
        finally:
            self._collecting = False
            self._mail_status("")

    def _mail_note(self, key: str, text: str) -> None:
        """A Send/Receive progress sentence, for the session log."""
        self._to_terminal(key, "write_note", f"*** Mail: {text}\n")

    def _mail_status(self, phase: str) -> None:
        """Send/Receive's status-bar field, in green ("Sending 1 of 2"); ""
        removes it.

        Ongoing state goes in the status bar, never in a line inserted
        above a pane's content (DESIGN.md section 6)."""
        self._activity = phase
        self._refresh_status()

    def _success_colour(self) -> str:
        """The theme's `$success` for a Rich renderable, which cannot name
        a CSS variable (the same lookup the APRS pane uses for `$warning`)."""
        try:
            return self.get_css_variables().get("success", "") or "green"
        except Exception:  # noqa: BLE001 -- before the theme is applied
            return "green"

    def _mail_sent(self, key: str, text: str) -> None:
        """Echo a line Send/Receive sent, as a typed line is echoed."""
        self._to_terminal(key, "write_note", text + "\n")
        self.log_sent(key, text, watch_hop=False)

    def _reload_mail_tabs(self) -> None:
        from .mail_pane import MessageBrowser

        for browser in self.query(MessageBrowser):
            browser.reload()

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
        self._to_terminal(self._active_key(), "write_note", f"\n*** Callsign changed to {new_call}\n")

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

        **Context-aware, dispatched on the active tab.** It asks one
        question -- "what can I say to the thing I am talking to?" -- and on
        the APRS pane the answer comes from `kissterm/aprs_services/` instead
        of `kissterm/nodes/`. Same question, same key, different source; this
        is the same per-tab dispatch `action_toggle_contacts` (`Ctrl+G`) uses,
        and the registry gives it a label for each tab (Node commands,
        Services). On APRS it is `Ctrl+R`; on Terminal it is a menu command,
        since Ctrl+R there is Reconnect and F1 shows the same reference.

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
                others=self.reference_sections(key),
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
        """Ctrl+D -- disconnect the visible Terminal session.

        Also the DISC half of `Delete` on the session-tab strip's focused
        tab (`disconnect_or_close_tab`), since `Delete` there only ever
        fires for the active tab -- see `terminal_pane.py`'s module
        docstring on why closing a session is two `Delete`s, not one.
        """
        if self.query_one("#main-tabs", TabbedContent).active != "terminal":
            self.notify("Open Terminal to disconnect from a station.")
            return
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
            self._to_terminal(session_key, "write_note", "\n*** Disconnecting...\n")
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
                    "write_note",
                    f"\n*** Cancelling connect to {connecting.peer} -- no "
                    "further SABMs will be sent.\n",
                )
                connecting.close(reason=CANCELLED_REASON)
                return
        session_connect_task = self._session_connect_task
        if (
            session_key == ""
            and session_connect_task is not None
            and not session_connect_task.done()
        ):
            self._to_terminal(
                session_key,
                "write_note",
                "\n*** Cancelling session transport connect...\n",
            )
            session_connect_task.cancel()
            return
        self.notify("Not connected.", severity="warning")

    def session_is_live(self, session_key: str) -> bool:
        """Connected or still connecting: closing it would disconnect first."""
        session = self._sessions.get(session_key)
        connected = session is not None and session.link is not None and session.link.connected
        return connected or session_key in self._connecting

    def _reconnect_request(self) -> ConnectRequest | None:
        """What Ctrl+R would dial: the Terminal tab on screen's own last
        request; for a tab that answered an incoming call, its peer; with no
        tab on screen, the last thing dialed at all."""
        key = self._active_key()
        request = self._last_connect.get(key)
        if request is None and key:
            call, _, port = key.partition(":")
            request = ConnectRequest(call, port=int(port) if port.isdigit() else 0)
        if request is None:
            request = self._last_connect.get(self._last_connect_key)
        return request

    def action_reconnect(self) -> None:
        """Ctrl+R: connect again to the station the Terminal tab on screen
        was connected to (requested 2026-09-23, replacing Ctrl+R Node
        commands, which moved to F1 and the menu).

        Replays the tab's own last request -- hops, login and port
        included -- through `action_connect`, so the radio reminder, the
        transport check and `_arm_for`'s visible arming all happen exactly
        as for a dial from the Address Book, which is the same kind of act:
        one key on a station already named. A tab that answered an incoming
        call has no request of its own, so its peer is dialed directly. A
        live tab is left alone: reconnecting it would mean disconnecting it.
        """
        if self.station is None:
            # Session tier: there is one far end, and connecting to it again
            # is what Ctrl+N already does there.
            self.action_connect()
            return
        key = self._active_key()
        if key and self.session_is_live(key):
            self.notify(f"Already connected to {key}.", severity="information")
            return
        request = self._reconnect_request()
        if request is None:
            self.notify(
                "Nothing to reconnect to yet. Ctrl+N connects to a station.",
                severity="warning",
            )
            return
        self.action_connect(redial=request)

    def action_close_tab(self) -> None:
        """Session > Close tab, APRS > Close conversation: whichever tab
        row the operator is looking at."""
        if self.query_one("#main-tabs", TabbedContent).active == "aprs":
            for pane in self._base_query(AprsPane):
                pane.close_active_tab()
            return
        for pane in self._base_query(TerminalPane):
            pane.close_active_tab()

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
        self.call_after_refresh(self._refresh_context_footer)

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
            session = self._sessions.get(self._active_key())
            if session is not None and session.application:
                # Inside an application: say which, after the node it was
                # reached through, so "BPQ32 > BPQMAIL" and a sysop's own
                # "BPQ32 > CALENDAR" (no reference, no suggestions) are both
                # explained where the operator is already looking.
                node_family = (
                    session.node_reference.family if session.node_reference else None
                )
                where_in = family.id.upper() if family is not None else session.application
                if node_family is not None:
                    where_in = f"{node_family.id.upper()} > {where_in}"
                peer_part += f" {where_in}"
            elif family is not None:
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
        else:
            # No session on screen -- at launch, or after its tab was closed.
            # The link-state field used to vanish instead, so the bar said
            # "connected" while there was a session and nothing at all
            # otherwise (requested 2026-09-23: "I would like to see a
            # Disconnected status as well"). Not with no transport at all:
            # "NO TRANSPORT" already says more, and needs the room.
            if self.station is not None or self.session_transport is not None:
                parts.append("disconnected")
        if self._activity:
            # Green, like a status light: something is under way that the
            # operator started, and the words say how far it has got.
            parts.append(Text(self._activity, style=f"bold {self._success_colour()}"))
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
        if self.transcript is not None:
            parts.append("LOGGING")
        if self.gps_reader is not None and self.gps_reader.running:
            parts.append("GPS FIX" if self.gps_reader.fix is not None else "GPS NO FIX")
        parts.append(f"heard {len(self.heard)}")
        renderable = _status_row(parts)
        for bar in self._base_query("#status-bar"):
            bar.update(renderable)
        # Link state changes land here, so the Close button's label follows
        # connect and disconnect without a second hook.
        for pane in self._base_query(TerminalPane):
            pane.sync_close_button()

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

    def on_text_selected(self, event: events.TextSelected) -> None:
        """Copy a mouse selection when the drag ends.

        The terminal cannot select text itself while the app holds the
        mouse, so a multiplexer that copies on highlight (herdr, tmux's
        copy-on-select) never sees one. Copying on release gives the same
        behaviour; Ctrl+C still works too. A plain click, which clears the
        selection, copies nothing.
        """
        text = self.screen.get_selected_text()
        if text:
            self.copy_to_clipboard(text)

    @on(TabbedContent.TabActivated, "#main-tabs")
    def _on_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Populate a pane the instant it becomes visible, not on the next tick.

        Any pane whose content is built by a periodic refresh needs a hook
        here, or it shows stale or empty content for up to one interval every
        time the operator switches to it.
        """
        if event.pane.id == "heard":
            self._refresh_heard(force=True)
        elif event.pane.id in ("mail", "bulletins", "files"):
            # Files arrive from outside the tab (a BBS session, a download,
            # an operator's own editor), so re-read on every visit.
            for browser in self._base_query(MessageBrowser):
                if browser.parent is event.pane:
                    browser.reload()
        elif event.pane.id == "settings":
            # Same rule as the heard table: a pane must be correct the instant
            # it is visible. Re-rendering also discards half-typed edits the
            # operator navigated away from without saving, which is the
            # behaviour that matches "this shows what is in effect".
            # `_base_query`, not `query_one`: an activation still queued when
            # the app shuts down arrives after the widgets are gone, and a
            # `NoMatches` raised out of a message handler ends the app.
            for pane in self._base_query(SettingsPane):
                pane.render_settings(self.config)
        self._refresh_status()
        # Clicking a tab changes ``TabbedContent.active`` directly and never
        # passes through ``action_show_tab``.  Refresh after this activation's
        # layout pass too, otherwise Footer can retain Terminal's context
        # until an APRS child receives focus.
        self.call_after_refresh(self._refresh_context_footer)
