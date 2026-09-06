"""The `KissTermApp` class: bindings, pane assembly, and the frame fan-out.

Layout follows the shape a packet operator already has in their head from
BPQTerminal and EasyTerm, because the goal is a familiar tool that happens to
be modern, not a novel one they have to relearn:

    F1 Terminal  F2 Monitor  F3 Heard  F4 APRS  F5 Address Book  F6 Settings
    +--------------------------------------------+
    | session output (scrollback, selectable)     |
    +--------------------------------------------+
    | > type here                          [Send] |
    +--------------------------------------------+
      ^r Commands  ^n Connect  ^d Disconnect  ...   <- shortcut keys
      kissterm 0.1 | transport | callsign | heard N <- status, BELOW them

The F-key for each tab is printed IN THE TAB LABEL (`F1 Terminal`, keyboard-
shortcut-first, matching how a menu shows an accelerator), not in the footer.
Textual's `Footer` widget would otherwise show `f1 Terminal  f2 Monitor  f3
Heard  f4 APRS  f5 Address Book  f6 Settings` right below a tab bar already
showing those same six names -- the same words twice, in two different
corners of the screen. All six `Binding`s stay registered (`show=False`) so
the keys still work; only the redundant on-screen label moves. `Ctrl+1..6`
remain as unlabelled fallback aliases for terminals that intercept function
keys.

**Function keys are tabs. Ctrl sequences are actions and modals.** That is
the whole rule, and it is why Address Book is F5 and Settings F6 (left to
right, in the order they were added) rather than either being the command
reference, and why the command reference -- a modal opened over whatever tab
is active -- is `Ctrl+R`, not a function key. A non-tab action squatting on
the next free F-number breaks the "F<n> is the n-th tab" pattern the moment
an n-th tab exists to expect it, which already happened once here. Address
Book moved OUT of a Settings tab and onto its own F-key for the same
reason it existed at all: it turned out to be used far more often than a
one-time setup screen, closer to Terminal/Monitor in how often an operator
reaches for it than to Settings.

This also reserves the F-row for the tabs still to come (Mail, Bulletins,
Files -- see docs/ROADMAP.md). The ceiling was originally set at F8 (some
terminals are unreliable past it), but KC1JMH reports F9/F10 work fine in
practice on the terminals actually in use here, and Midnight Commander --
about as widely deployed a terminal-UI precedent as exists -- has used
F1-F10 for its whole menu row for decades without it being a practical
problem. **F1..F10 is the working ceiling now, ten tabs the practical
maximum.** F11 is out regardless: it is "toggle fullscreen" in enough
terminal emulators and window managers that it rarely reaches the
application at all. Six tabs exist and three more are planned, landing at
F9 with F10 spare -- see docs/ROADMAP.md's P10 section for the assignment.

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
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Static, TabbedContent, TabPane

from .. import __version__
from ..addressbook import AddressBook
from ..ax25 import AX25Station, parse_path
from ..beacon import Beaconer
from ..config import BeaconConfig, find_credential
from ..ax25.frame import AX25Frame
from ..heard import HeardTable
from ..hotplug import PortEvent, SerialPortWatcher
from ..monitor import MonitorFilter, format_frame, sanitize
from ..session_log import SessionLog
from ..transport.base import SessionState, TransportError, TransportState
from ..tx import DISABLED_MESSAGE, TransmitGate
from .addressbook_pane import AddressBookPane
from .aprs_pane import AprsPane
from . import themes
from .clock import KissTermHeader
from ..nodes import CommandReference
from ..nodes.reference import identify_family
from .dialogs import (
    CallsignScreen,
    CommandReferenceScreen,
    ConnectRequest,
    ConnectScreen,
    RadioReminderScreen,
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


class KissTermApp(App):
    """The application.

    `config` and `station` are injected rather than constructed here so a
    headless test can mount the app against a loopback transport with no radio,
    no serial port, and no real config directory. Constructing them internally
    would make every UI test require hardware.
    """

    TITLE = "kissterm"

    CSS = APP_CSS

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        # Hidden from the footer: the tab bar already shows these, and at 80
        # columns -- a perfectly ordinary terminal -- the footer overflows and
        # starts truncating the ACTION bindings, which are not discoverable
        # anywhere else.
        Binding("f1", "show_tab('terminal')", "Terminal", show=False),
        Binding("f2", "show_tab('monitor')", "Monitor", show=False),
        Binding("f3", "show_tab('heard')", "Heard", show=False),
        Binding("f4", "show_tab('aprs')", "APRS", show=False),
        Binding("ctrl+1", "show_tab('terminal')", "Terminal", show=False),
        Binding("ctrl+2", "show_tab('monitor')", "Monitor", show=False),
        Binding("ctrl+3", "show_tab('heard')", "Heard", show=False),
        Binding("ctrl+4", "show_tab('aprs')", "APRS", show=False),
        Binding("f5", "show_tab('addressbook')", "Address Book", show=False),
        Binding("ctrl+5", "show_tab('addressbook')", "Address Book", show=False),
        Binding("f6", "show_tab('settings')", "Settings", show=False),
        Binding("ctrl+6", "show_tab('settings')", "Settings", show=False),
        Binding("ctrl+t", "toggle_transmit", "TX"),
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
        Binding("ctrl+d", "disconnect", "Disconnect"),
        Binding("ctrl+k", "set_callsign", "Callsign"),
        Binding("ctrl+r", "command_reference", "Commands"),
        Binding("ctrl+l", "clear_log", "Clear"),
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
        #: Watches local serial ports only. The network is never scanned on a
        #: timer -- see kissterm/hotplug.py for the cost argument.
        self.port_watcher = SerialPortWatcher()
        #: Shipped command reference for whatever node we are talking to.
        #: Populated by sniffing the banner -- never by asking the node, which
        #: costs real airtime (see kissterm/nodes/__init__.py).
        self.reference = CommandReference()
        self._detect_buffer = ""
        #: Transcript for the current session, or None. Owned here rather
        #: than by the pane: it records what crossed the *link*, and the pane
        #: is only one of the things watching that.
        self.transcript: SessionLog | None = None
        #: Plain-text beacon. Constructed unconditionally so there is one
        #: object to ask "is this station transmitting on a timer?"; it does
        #: nothing at all until `start()` succeeds, and `start()` refuses
        #: unless the operator opted in AND set some text.
        self.beaconer = Beaconer(
            station, getattr(config, "beacon", None) or BeaconConfig(),
            on_sent=self._on_beacon_sent,
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
            with TabPane("F5 Address Book", id="addressbook"):
                yield AddressBookPane()
            with TabPane("F6 Settings", id="settings"):
                yield SettingsPane()
        # Status bar and Footer share one bottom-docked container. Docking
        # them both individually puts them in the SAME region -- the Footer
        # paints over the status bar and it is invisible, in either yield
        # order. One docked parent with an explicit height lays them out as
        # two distinct rows. Verified in tests/pilot/test_app_mounts.py.
        with Vertical(id="bottom-bar"):
            yield Footer()
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
            self.station.transport.on_sent.append(self._on_sent_frame)
            self.station.on_incoming.append(self._on_incoming_link)
            self._status = f"{self.station.transport.info.detail}"
        self.query_one(TerminalPane).log(
            f"kissterm {__version__} -- Ctrl+N to connect, Ctrl+H for help.\n"
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

    def on_unmount(self) -> None:
        """Disarm the beacon as the app goes away.

        Not merely tidy: a beacon task still armed while the UI is being torn
        down would transmit under the operator's callsign with nothing on
        screen to show it -- and nowhere to show it.
        """
        self.beaconer.cancel()
        self._unsubscribe_monitor()
        self._close_transcript()

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
        self.link = link
        self._start_transcript(link)
        link.on_data.append(self._on_link_data)
        link.on_state.append(self._on_link_state)
        link.on_error.append(lambda why: self._note(f"\n*** {why}\n"))
        self._to_terminal("set_placeholder", f"connected to {link.peer}")

    # ------------------------------------------------------------------
    # Transcript
    # ------------------------------------------------------------------
    def _start_transcript(self, link) -> None:
        """Open a transcript for this session, and say where it is.

        The path goes on screen because a file appearing on disk without the
        operator being told is a surprise, and this is on by default. A
        transcript that cannot be opened is reported once and then forgotten
        about -- see `session_log.py` on why a failed log must never be
        allowed to disturb a live link.
        """
        self._close_transcript()
        if not getattr(self.config, "log_sessions", True):
            return
        from ..config import log_path

        directory = Path(self.config.log_dir) if self.config.log_dir else log_path()
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
        self._to_terminal("log", f"\n*** Transcript: {transcript.path}\n")

    def _close_transcript(self) -> None:
        if self.transcript is not None:
            self.transcript.close()
            self.transcript = None

    def _note(self, text: str) -> None:
        """A local note: to the terminal pane, and to the transcript."""
        self._to_terminal("log", text)
        if self.transcript is not None:
            self.transcript.note(text.strip().lstrip("* "))

    def log_sent(self, text: str) -> None:
        """Record a line the operator transmitted. Called from `send_line`.

        The pane echoes it to the scrollback itself; this is the durable half.
        """
        if self.transcript is not None:
            self.transcript.sent(text)

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
        if state is SessionState.DISCONNECTED:
            self._to_terminal("set_placeholder", "not connected -- Ctrl+N")
            self._close_transcript()

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

    def action_clear_log(self) -> None:
        active = self.query_one("#main-tabs", TabbedContent).active
        if active == "monitor":
            self.query_one(MonitorPane).clear()
        else:
            self.query_one(TerminalPane).clear()

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
                await self._connect_session_transport()
                return
            self.notify("No transport is open.", severity="error")
            return
        if prefill is not None:
            request = ConnectRequest(
                prefill.target, prefill.script, prefill.hops, prefill.credential
            )
            # A dial is an attempt like any other -- see AddressBook.record_
            # attempt's docstring for why this is recorded on the attempt,
            # not on success.
            self.addressbook.record_attempt(
                prefill.target, prefill.script, prefill.hops, prefill.credential
            )
        else:
            request = await self.push_screen_wait(
                ConnectScreen(self.addressbook, self.config.credentials)
            )
            if not request:
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
                f"an RF problem -- check the TNC, then Settings (F6) > Test "
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
            link = await self.station.connect(path)
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
        login_text = (
            find_credential(self.config, request.credential)
            if request.credential
            else request.script
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
        self._bind_link(_SessionLinkAdapter(session))
        self.query_one(TerminalPane).focus_input()

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
        elif event.pane.id == "addressbook":
            # Same rule: an attempt recorded from Ctrl+N since this pane was
            # last open must show up the instant the operator switches to it.
            self.query_one(AddressBookPane).refresh_from(self.addressbook)
        elif event.pane.id == "settings":
            # Same rule as the heard table: a pane must be correct the instant
            # it is visible. Re-rendering also discards half-typed edits the
            # operator navigated away from without saving, which is the
            # behaviour that matches "this shows what is in effect".
            self.query_one(SettingsPane).render_settings(self.config)
        self._refresh_status()
