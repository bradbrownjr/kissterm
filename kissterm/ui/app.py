"""The `KissTermApp` class: bindings, pane assembly, and the frame fan-out.

Layout follows the shape a packet operator already has in their head from
BPQTerminal and EasyTerm, because the goal is a familiar tool that happens to
be modern, not a novel one they have to relearn:

    F1 Terminal  F2 Monitor  F3 Heard  F4 APRS  F5 Settings
    +--------------------------------------------+---------+
    | session output (scrollback, selectable)     | Address |
    +--------------------------------------------+ Book,   |
    | > type here                          [Send] | Ctrl+G  |
    +--------------------------------------------+---------+
      ^r Commands  ^n Connect  ^d Disconnect  ^G Contacts ...  <- shortcut keys
      kissterm 0.1 | transport | callsign | heard N          <- status, BELOW them

The F-key for each tab is printed IN THE TAB LABEL (`F1 Terminal`, keyboard-
shortcut-first, matching how a menu shows an accelerator), not in the footer.
Textual's `Footer` widget would otherwise show `f1 Terminal  f2 Monitor  f3
Heard  f4 APRS  f5 Settings` right below a tab bar already showing those same
five names -- the same words twice, in two different corners of the screen.
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

Keys deliberately avoid `Ctrl+C` for anything but quit, and avoid single-letter
bindings while the input line has focus: this is a *terminal*, and a key that
does something other than type a character into a live BBS session is a bug the
operator will hit at the worst moment.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
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
from .. import aprs
from ..aprs_conversations import ConversationStore
from ..aprs_notify import Cooldown, evaluate_packet
from ..ax25 import AX25Station, parse_path
from ..ax25.address import AX25Address
from ..aprs_beacon import AprsBeaconer
from ..beacon import Beaconer
from ..config import AprsConfig, BeaconConfig, find_credential, find_script
from .. import desktop_notify
from ..ax25.frame import PID_NO_LAYER3, AX25Frame, UType
from ..heard import HeardTable
from ..hotplug import PortEvent, SerialPortWatcher
from ..monitor import MonitorFilter, callsign_matches, format_frame, mail_waiting_for, sanitize
from ..session_log import SessionLog
from ..transport.base import SessionState, TransportError, TransportState
from ..tx import DISABLED_MESSAGE, TransmitGate
from .aprs_pane import AprsPane
from . import themes
from .clock import KissTermHeader
from .commands import KeyBindingsProvider, fit_footer_bindings
from ..nodes import CommandReference
from ..nodes.reference import identify_family
from .dialogs import (
    CallsignScreen,
    CommandReferenceScreen,
    ConnectRequest,
    ConnectScreen,
    RadioReminderScreen,
    TranscriptsScreen,
)
from .heard_pane import HeardPane
from .monitor_pane import MonitorPane
from .settings_pane import SettingsPane
from .styles import APP_CSS
from .terminal_pane import TerminalPane

log = logging.getLogger(__name__)


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

#: How long after sending a line, with nothing back, before saying so
#: (`KissTermApp._note_if_no_reply`). From a real report: WS1EC-15
#: acknowledged a line at the AX.25 layer (an RR came back within 3
#: seconds) and then said nothing for 22 seconds before the operator gave
#: up and disconnected, having no way to tell "they got it, they are just
#: slow" from "this went nowhere" without reading the Monitor tab and
#: knowing to look for a hidden-by-default supervisory frame. Long enough
#: that an ordinary node's response time does not trip it on every line.
REPLY_WAIT_SECONDS = 15.0


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
        Binding("f1", "show_tab('terminal')", "Terminal", show=False),
        Binding("f2", "show_tab('monitor')", "Monitor", show=False),
        Binding("f3", "show_tab('heard')", "Heard", show=False),
        Binding("f4", "show_tab('aprs')", "APRS", show=False),
        Binding("ctrl+1", "show_tab('terminal')", "Terminal", show=False),
        Binding("ctrl+2", "show_tab('monitor')", "Monitor", show=False),
        Binding("ctrl+3", "show_tab('heard')", "Heard", show=False),
        Binding("ctrl+4", "show_tab('aprs')", "APRS", show=False),
        Binding("f5", "show_tab('settings')", "Settings", show=False),
        Binding("ctrl+5", "show_tab('settings')", "Settings", show=False),
        Binding("ctrl+t", "toggle_transmit", "TX"),
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
        #: The one active link, if any. Panes read this off `self.app` rather
        #: than tracking their own copy -- see this module's docstring.
        self.link = None
        #: The peer of a connect attempt still in the SABM/retry phase, or
        #: None. Set only for that window -- see `action_connect` and
        #: `action_disconnect`. Needed because `self.link` is not bound until
        #: the attempt SUCCEEDS, so without this Ctrl+D during a stuck connect
        #: has nothing to act on and can only say "Not connected", leaving
        #: the operator to wait out N2 retries with no way to stop them.
        self._connect_target = None
        self._status = "starting"
        #: Stations already tried, offered in the connect dialog. Owned here
        #: rather than by the dialog so a successful connect can be recorded
        #: after the dialog has closed, and so the file is read once at
        #: startup instead of on every Ctrl+N.
        self.addressbook = AddressBook()
        self.addressbook.load()
        #: APRS message history, keyed by correspondent -- see
        #: kissterm/aprs_conversations.py. Loaded here rather than by the
        #: APRS pane so a message that arrives before the operator ever
        #: visits F4 is still recorded, the same reasoning `self.heard`
        #: is built and loaded before any pane asks for it.
        self.aprs_conversations = ConversationStore()
        self.aprs_conversations.load()
        #: Suppresses a repeat desktop notification for the same (source,
        #: reason) pair within its window -- see kissterm/aprs_notify.py.
        #: An Emergency Mic-E flag always bypasses it.
        self._aprs_notify_cooldown = Cooldown()
        #: Watches local serial ports only. The network is never scanned on a
        #: timer -- see kissterm/hotplug.py for the cost argument.
        self.port_watcher = SerialPortWatcher()
        #: Shipped command reference for whatever node we are talking to.
        #: Populated by sniffing the banner -- never by asking the node, which
        #: costs real airtime (see kissterm/nodes/__init__.py).
        self.reference = CommandReference()
        self._detect_buffer = ""
        #: (source callsign, matched callsign) pairs already surfaced by
        #: `_check_mail_for`, so a beacon repeating on its own interval does
        #: not re-notify the operator every time it is heard again -- the
        #: point is "you have not seen this yet", not a running tally.
        self._mail_notified: set[tuple[str, str]] = set()
        #: Transcript for the current session, or None. Owned here rather
        #: than by the pane: it records what crossed the *link*, and the pane
        #: is only one of the things watching that.
        self.transcript: SessionLog | None = None
        #: Armed by `log_sent`, cancelled by `_on_link_data` or a state
        #: change -- see `_note_if_no_reply` and `REPLY_WAIT_SECONDS`.
        self._reply_timer: Timer | None = None
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
            with TabPane("F2 Monitor", id="monitor"):
                yield MonitorPane()
            with TabPane("F3 Heard", id="heard"):
                yield HeardPane()
            with TabPane("F4 APRS", id="aprs"):
                yield AprsPane()
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
            f"kissterm {__version__} -- Ctrl+N to connect, Ctrl+R for commands, "
            "Ctrl+O for past transcripts.\n"
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
        self._to_terminal("log", f"\n*** Beacon sent to {frame.path.destination}\n")

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
        self._to_terminal("log", "\n*** APRS position beacon sent\n")

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
        self._close_transcript()
        self._cancel_reply_timer()

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
                "log", f"\n*** Plugged in: {event.device} -- {event.detail}\n"
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
            self._to_terminal("log", f"\n*** {event.device} was unplugged\n")
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
            "log", f"\n*** {source} is holding mail for {matched} (heard on the channel)\n"
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

        if packet.kind == "message" and isinstance(packet.data, aprs.Message):
            msg = packet.data
            source = str(packet.source)
            if not (msg.is_ack or msg.is_rej):
                self.aprs_conversations.record_incoming(source, msg.text, number=msg.number)
                mycalls = [self.config.mycall, *self.config.mycall_aliases]
                if callsign_matches(msg.addressee, mycalls):
                    if getattr(self.config, "aprs_auto_ack", True) and msg.number:
                        await self._send_aprs_ack(source, msg.number, port)
            elif msg.is_ack and msg.number:
                # Flips `MessageEntry.acked` in the persisted log. A pending-
                # send retry loop (APRS pane, not built yet) reads that flag
                # back off `self.aprs_conversations` on its own timer rather
                # than needing a live callback wired here for a consumer
                # that does not exist yet.
                self.aprs_conversations.mark_acked(source, msg.number)

        decision = evaluate_packet(packet, self.config.mycall, self.config.mycall_aliases)
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

    async def _send_aprs_ack(self, addressee: str, number: str, port: int) -> None:
        """Auto-ack an APRS message addressed to us -- see
        `Config.aprs_auto_ack`'s docstring for why this defaults on and is
        still just as gated by the transmit switch as everything else this
        app sends. Every auto-ack is written to the terminal pane, the same
        rule a beacon or a connect-script line follows: a station that
        transmits without the operator being able to see that it did is
        exactly what that rule exists to prevent.
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
            return
        try:
            payload = aprs.ack(addressee, number)
            dest = AX25Address.parse("APRS")
            outframe = aprs.beacon_frame(self.station.mycall, dest, (), payload)
            await self.station.transport.send_frame(outframe, port)
        except Exception as exc:  # never let an ack failure disturb the link
            log.debug("APRS auto-ack to %s not sent: %s", addressee, exc)
            return
        self.aprs_conversations.record_outgoing(addressee, f"ack{number}", number=None)
        self._to_terminal("log", f"\n*** Auto-ack sent to {addressee} (msg {number})\n")

    async def _send_aprs_message(
        self, addressee: str, text: str, number: str, *, port: int = 0, retry: bool = False
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
            outframe = aprs.beacon_frame(self.station.mycall, dest, (), payload)
            await self.station.transport.send_frame(outframe, port)
        except Exception as exc:
            log.debug("APRS message to %s not sent: %s", addressee, exc)
            return False
        verb = "Resent" if retry else "Sent"
        self._to_terminal("log", f"\n*** {verb} APRS message {number} to {addressee}\n")
        return True

    def _on_incoming_link(self, link) -> None:
        self._to_terminal("log", f"\n*** Incoming connection from {link.peer}\n")
        if not self.gate.enabled:
            # The UA never went out, so the caller is talking to nobody. Say
            # so: "somebody called and you could not answer" is exactly the
            # thing an operator wants to find in the scrollback later.
            self._to_terminal(
                "log",
                f"*** Could not answer {link.peer} -- transmit is disabled (Ctrl+T)\n",
            )
            self.notify(
                f"{link.peer} called, but transmit is disabled.", severity="warning"
            )
        if self.link is None or not self.link.connected:
            self._bind_link(link)
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

    def _bind_link(self, link) -> None:
        # A new conversation may be a different node; forget the last one's
        # identification rather than offering its commands for this one.
        self.reference = CommandReference()
        self._detect_buffer = ""
        self._cancel_reply_timer()
        self.link = link
        self._start_transcript(link)
        link.on_data.append(self._on_link_data)
        link.on_state.append(self._on_link_state)
        link.on_error.append(lambda why: self._note(f"\n*** {why}\n"))
        self._to_terminal("set_placeholder", f"connected to {link.peer}")

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
    def _start_transcript(self, link) -> None:
        """Open a transcript for this session, and say where it is.

        The path goes on screen -- as a fixed header above the scrollback,
        not a line inside it (`TerminalPane.set_transcript_note`) -- because a
        file appearing on disk without the operator being told is a surprise,
        and this is on by default. A header survives Ctrl+L and scrolling;
        a log line would not stay findable through either. A transcript that
        cannot be opened is reported once, as a log line since there is no
        path to keep showing, and then forgotten about -- see `session_log.py`
        on why a failed log must never be allowed to disturb a live link.
        """
        self._close_transcript()
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
            self._to_terminal("log", f"\n*** No transcript: {transcript.failed}\n")
            return
        self.transcript = transcript
        self._to_terminal("set_transcript_note", f"Transcript: {transcript.path}")

    def _close_transcript(self) -> None:
        if self.transcript is not None:
            self.transcript.close()
            self.transcript = None
            self._to_terminal("set_transcript_note", "")

    def _note(self, text: str) -> None:
        """A local note: to the terminal pane, and to the transcript."""
        self._to_terminal("log", text)
        if self.transcript is not None:
            self.transcript.note(text.strip().lstrip("* "))

    def log_sent(self, text: str) -> None:
        """Record a line the operator transmitted. Called from `send_line`.

        The pane echoes it to the scrollback itself; this is the durable
        half -- and this also (re)arms the reply-watch timer (`_note_if_no_
        reply`), cancelling any previous one so it is the LAST line typed
        that starts the clock, not the first.
        """
        if self.transcript is not None:
            self.transcript.sent(text)
        self._cancel_reply_timer()
        if self.link is not None and self.link.connected:
            self._reply_timer = self.set_timer(REPLY_WAIT_SECONDS, self._note_if_no_reply)

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

    def _to_terminal(self, method: str, *args) -> None:
        """Call a `TerminalPane` method, tolerating the pane not existing.

        A link outlives the UI. On shutdown `__main__` exits the app first and
        *then* calls `station.close()`, which fires every link's state callback
        -- at which point the widget tree is gone and a bare `query_one` raises
        `NoMatches` out of a callback nothing is catching. That turned a clean
        quit with a live link into a traceback. `query()` returns an empty
        result set instead of raising, so a torn-down UI is simply nothing to
        write to.
        """
        for pane in self._base_query(TerminalPane):
            getattr(pane, method)(*args)
            return

    def _on_link_data(self, data: bytes) -> None:
        # Any data back answers the "did they get it" question the reply
        # timer exists for -- see `_note_if_no_reply`.
        self._cancel_reply_timer()
        self._to_terminal("write_incoming", data)
        if self.transcript is not None:
            # Sanitized, never raw. A transcript is read later by a person in
            # a terminal, so wire bytes with escape sequences in them would
            # reintroduce exactly the problem the pane's filter solves --
            # `cat` on the file would run them.
            self.transcript.received(sanitize(data))
        self._sniff_node(data)

    def _sniff_node(self, data: bytes) -> None:
        """Identify the node family from what it already sent us.

        Passive on purpose. Asking a node for its command list with `?` costs
        roughly twenty seconds of a 1200-baud channel for a couple of
        kilobytes, and over a minute for a verbose one -- airtime nobody else
        can use. The banner and prompt arrive anyway, so they are free.

        Only the first couple of kilobytes are examined; a node identifies
        itself in its greeting or not at all, and scanning the whole session
        forever would let ordinary message text trigger a false match.
        """
        if self.reference.family is not None or len(self._detect_buffer) > 2048:
            return
        from ..monitor import sanitize

        self._detect_buffer += sanitize(data)
        family = identify_family(self._detect_buffer)
        if family is None:
            return
        self.reference = CommandReference(family=family)
        self._to_terminal(
            "log", f"\n*** Node looks like {family.name} -- Ctrl+R for its commands\n"
        )

    def _on_link_state(self, state: SessionState) -> None:
        self._note(f"\n*** {state.value}\n")
        if state is not SessionState.CONNECTED:
            # Anything other than a plain, steady CONNECTED -- disconnecting,
            # failed, timer recovery -- already gets its own note above; the
            # "acknowledged but silent" one below would only repeat that with
            # less information, or fire after the link is no longer there to
            # ask a question about.
            self._cancel_reply_timer()
        if state is SessionState.DISCONNECTED:
            self._to_terminal("set_placeholder", "not connected -- Ctrl+N")
            self._close_transcript()

    # ------------------------------------------------------------------
    # Reply watch -- "they got it, are they just not answering?"
    # ------------------------------------------------------------------
    def _cancel_reply_timer(self) -> None:
        if self._reply_timer is not None:
            self._reply_timer.stop()
            self._reply_timer = None

    def _note_if_no_reply(self) -> None:
        """Fired `REPLY_WAIT_SECONDS` after a send with nothing back since.

        Only says anything when the AX.25 layer has nothing outstanding
        (`link.va == link.vs`) -- i.e. the far end already acknowledged the
        line. If it has NOT been acknowledged, T1/timer recovery is already
        retrying it and already wrote its own note to the terminal; this
        would only be a vaguer echo of that. This is exactly the gap a real
        report exposed: WS1EC-15 ACKed a line within 3 seconds and then said
        nothing for 22 more, and the only place that ACK showed up was an RR
        frame the Monitor tab hides by default.
        """
        self._reply_timer = None
        link = self.link
        if link is None or not link.connected or link.va != link.vs:
            return
        self._to_terminal(
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
            self._to_terminal("log", "\n*** Transmit enabled\n")
        else:
            blocked = ""
            self.notify(
                "Transmit DISABLED. Nothing will be sent." + blocked,
                severity="warning",
            )
            self._to_terminal("log", "\n*** Transmit disabled\n")
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
            "log", f"\n*** Transmit enabled automatically for: {what}\n"
        )
        self.notify(f"Transmit ENABLED for {what}. Ctrl+T turns it back off.")
        self._refresh_status()

    @work
    async def action_beacon_now(self) -> None:
        """Ctrl+Shift+B -- send one beacon immediately.

        The timed beacon deliberately waits a full interval before its first
        transmission, because launching the app is not a request to key the
        radio. This is how an operator says "yes it is, right now" without
        having to wait out the interval or shorten it -- the same role
        JS8Call's heartbeat button plays. It does not enable the timer and
        does not need the timer to be on.
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

    def action_show_tab(self, tab: str) -> None:
        self.query_one("#main-tabs", TabbedContent).active = tab

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
        else:
            self.query_one(TerminalPane).clear()

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
    async def action_connect(self, prefill=None) -> None:
        """Connect to a station, via the dialog or dialed directly.

        `prefill` is an `addressbook.Entry`, passed by `AddressBookPane`
        when the operator dials a saved station instead of typing one into
        Ctrl+N -- everything past this point is the same flow either way:
        the transmit gate, the transport check, the hop chain, the login.
        Dialing is a faster way to reach this method, never a second,
        lighter-weight path into it.
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
        if reminder is not None and (reminder.frequency or reminder.connection_type):
            proceed = await self.push_screen_wait(
                RadioReminderScreen(reminder.frequency, reminder.connection_type)
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
        # The TNC link, before the RF link. Sending six SABMs into a socket
        # that is down produces "no answer from WS1EC-15" -- a diagnosis
        # pointing at the antenna when the fault is in the room. Unlike a
        # closed transmit gate this is not something a keystroke can fix, so
        # it is worth saying before spending the attempt.
        state = self.station.transport.state
        if state is not TransportState.OPEN:
            where = self.station.transport.info.detail
            self._to_terminal(
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
        # A fresh screen for a fresh session. Without this, the top of the
        # scrollback is whatever the LAST station sent -- a new connect
        # attempt scrolling in below an old, unrelated conversation reads as
        # one continuous session when it is not.
        self.query_one(TerminalPane).clear()
        self.query_one(TerminalPane).log(f"\n*** Connecting to {path.destination}...\n")
        # Set before the await, not after: `AX25Station.connect` registers the
        # link synchronously before it awaits anything, so by the time this
        # coroutine yields control the link is already reachable by peer
        # address -- which is what lets Ctrl+D find and cancel it mid-attempt.
        self._connect_target = path.destination
        try:
            link = await self.station.connect(
                path,
                paclen=_entry_link_override(reminder.paclen) if reminder else None,
                window=_entry_link_override(reminder.window) if reminder else None,
            )
        except TransportError as exc:
            self.notify(str(exc), severity="error")
            return
        finally:
            self._connect_target = None
        if link is None:
            failed = self.station.link_to(path.destination)
            reason = getattr(failed, "last_error", "") if failed else ""
            if reason == CANCELLED_REASON:
                self._to_terminal("log", f"*** Connect to {path.destination} cancelled.\n")
                return
            # Say WHY. "No connection" alone cannot be acted on: a DM means
            # the node heard us and refused, which is a configuration problem
            # at one end or the other; silence after N2 tries means the path
            # did not carry, which is an antenna, power or propagation
            # problem. On a marginal path that distinction is the whole
            # diagnosis, and it is already known here.
            attempts = getattr(failed, "rc", 0) if failed else 0
            detail = f" -- {reason}" if reason else ""
            self._to_terminal("log", f"*** No connection to {path.destination}{detail}\n")
            if attempts:
                self._to_terminal(
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
                    "log",
                    "*** The link to the TNC dropped during this attempt, so "
                    "some of those frames never reached the radio. Fix that "
                    "first -- this is not an RF failure.\n",
                )
            self.notify(
                f"Could not connect to {path.destination}{detail}", severity="warning"
            )
            return
        self._bind_link(link)
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
        self._note(f"\n*** Connected to {link.peer}\n")
        self.query_one(TerminalPane).focus_input()
        reached_target = True
        if len(chain) > 1:
            # The AX.25 link is only to the FIRST node -- everything past
            # it is that node's own onward routing, invisible to kissterm's
            # state machine and driven purely by watching what comes back
            # over this one link. See `_hop_through`.
            reached_target = await self._hop_through(link, chain[1:])
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
            self._run_connect_script(link, login_text)

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

        Known gap: unlike the FrameTransport path, there is no way to
        cancel a connect attempt that hangs here (a slow or unreachable
        host) short of waiting for it to time out or fail on its own --
        see docs/ROADMAP.md's Telnet/SSH entry.
        """
        transport = self.session_transport
        if self.link is not None and self.link.connected:
            self.notify("Already connected.", severity="warning")
            return
        self._arm_for(f"connect via {transport.info.detail}")
        self.query_one(TerminalPane).clear()
        self.query_one(TerminalPane).log(f"\n*** Connecting to {transport.info.detail}...\n")
        try:
            session = await transport.connect()
        except TransportError as exc:
            self._to_terminal("log", f"*** Could not connect: {exc}\n")
            self.notify(str(exc), severity="error")
            return
        link = _SessionLinkAdapter(session)
        self._bind_link(link)
        # Same gap as the frame-tier connect above (`action_connect`) and
        # the same fix -- see the comment there.
        self._note(f"\n*** Connected to {link.peer}\n")
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
            self._run_connect_script(link, login_text)

    async def _hop_through(self, link, nodes: list[str]) -> bool:
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

        Stops and reports on the first hop that does not come up, leaving
        the link connected to whichever node was last reached rather than
        tearing anything down -- the operator can continue by hand from
        there. Never sends the next hop's command after a failure: that
        would be transmitting into a link nothing has confirmed is ready
        for it.
        """
        for node in nodes:
            if not link.connected:
                self._to_terminal("log", "*** Hop chain stopped: no longer connected.\n")
                return False
            if not self.gate.enabled:
                self._to_terminal("log", "*** Hop chain stopped: transmit is off.\n")
                return False
            ok, detail = await self._hop_to(link, node)
            if not ok:
                extra = f" -- {detail}" if detail else ""
                self._to_terminal("log", f"*** No connection to {node}{extra}\n")
                self.notify(f"Hop to {node} did not connect{extra}", severity="warning")
                return False
        return True

    async def _hop_to(self, link, node: str) -> tuple[bool, str]:
        """Send ``C <node>`` and wait for that node's own CONNECTED reply.

        Watches everything the link receives from the moment the command
        goes out, via a temporary `link.on_data` subscriber -- non-
        destructively: the terminal pane has its own separate subscriber
        from `_bind_link` and keeps displaying the same bytes normally, the
        same one-fan-out-many-subscribers shape as the frame transport's own
        `subscribe()`. Removed again before returning either way, so it
        cannot keep matching against a later, unrelated hop's traffic.

        Returns ``(True, "")`` on a CONNECTED reply, or ``(False, detail)``
        on an explicit BUSY/FAILED/DISCONNECTED/TIMEOUT reply (a refusal --
        `detail` names which word) or on plain silence past `HOP_TIMEOUT`
        (`detail` says so) -- two different diagnoses that must not be
        reported with the same words, same reasoning as a DM versus an N2
        timeout one layer down in `AX25Station.connect`.
        """
        seen = bytearray()
        result: asyncio.Future[tuple[bool, str]] = asyncio.get_event_loop().create_future()

        def _watch(data: bytes) -> None:
            seen.extend(data)
            text = seen.decode("latin-1", "replace").upper()
            if "CONNECTED" in text:
                if not result.done():
                    result.set_result((True, ""))
                return
            for word in HOP_FAIL_WORDS:
                if word in text:
                    if not result.done():
                        result.set_result((False, f"{node} answered {word}"))
                    return

        link.on_data.append(_watch)
        try:
            cmd = f"C {node}"
            await link.send(cmd.encode("latin-1", "replace") + b"\r")
            self._to_terminal("log", cmd + "\n")
            self.log_sent(cmd)
            try:
                return await asyncio.wait_for(result, timeout=HOP_TIMEOUT)
            except asyncio.TimeoutError:
                return False, f"no response within {HOP_TIMEOUT:.0f}s"
        finally:
            with contextlib.suppress(ValueError):
                link.on_data.remove(_watch)

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
    async def _run_connect_script(self, link, script: str) -> None:
        """Send a station's saved auto-login script, one line at a time.

        Runs only right after a connect the operator just named and
        confirmed in the Connect dialog -- see `_arm_for` above, which is
        what actually armed transmit for this attempt. This does not arm or
        re-confirm anything itself; it rides the one the connect already
        got, the same way answering a poll rides an established link's own
        authorization rather than asking again per frame.

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
        self._to_terminal("log", f"\n*** Auto-login: sending {len(lines)} line(s)...\n")
        for line in lines:
            if not link.connected:
                self._to_terminal("log", "*** Auto-login stopped: no longer connected.\n")
                return
            if not self.gate.enabled:
                self._to_terminal("log", "*** Auto-login stopped: transmit is off.\n")
                return
            await link.send(line.encode("latin-1", "replace") + b"\r")
            self._to_terminal("log", line + "\n")
            self.log_sent(line)
            await asyncio.sleep(CONNECT_SCRIPT_LINE_DELAY)

    @work
    async def action_set_callsign(self) -> None:
        """Change the station callsign and persist it, without a restart.

        Refused while a link is up: the callsign is in the address field of
        every frame of an established conversation, and swapping it mid-session
        would make our own traffic unrecognisable to the peer -- it would keep
        answering the old call while we transmitted under the new one, and the
        link would die by N2 timeout rather than by anything the operator could
        diagnose. Disconnecting first is the honest requirement.
        """
        if self.link is not None and self.link.connected:
            self.notify(
                "Disconnect before changing callsign.", severity="warning"
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
        self.query_one(TerminalPane).log(f"\n*** Callsign changed to {new_call}\n")

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
        """
        chosen = await self.push_screen_wait(
            CommandReferenceScreen(self.reference)
        )
        if chosen:
            self.action_show_tab("terminal")
            self._to_terminal("suggest", chosen)

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
    async def action_disconnect(self) -> None:
        if self.link is not None and self.link.connected:
            # Same reasoning as connect, and more so: a DISC is how a link is
            # ended politely. Refusing to send it leaves the far station
            # holding a session open until ITS timers give up, which is a
            # worse outcome for the channel than the transmission we would
            # be avoiding.
            self._arm_for(f"disconnect from {self.link.peer}")
            self.query_one(TerminalPane).log("\n*** Disconnecting...\n")
            await self.link.disconnect()
            return
        # No established link -- but a connect attempt may still be working
        # through its SABM retries. Without this, the only way off a stuck
        # attempt was to wait out N2 in full: Ctrl+D said "Not connected"
        # (true, but useless) while the radio kept keying up on its own.
        if self._connect_target is not None and self.station is not None:
            connecting = self.station.link_to(self._connect_target)
            if connecting is not None and not connecting.connected:
                self.query_one(TerminalPane).log(
                    f"\n*** Cancelling connect to {connecting.peer} -- no "
                    "further SABMs will be sent.\n"
                )
                connecting.close(reason=CANCELLED_REASON)
                self.notify(f"Cancelled connect to {connecting.peer}.")
                return
        self.notify("Not connected.", severity="warning")

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
            parts.append(f"{self.link.peer} {self.link.state.value}")
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
        for pane in self._base_query(HeardPane):
            pane.refresh_from(self.heard)

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
