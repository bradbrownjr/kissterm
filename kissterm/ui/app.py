"""The `KissTermApp` class: bindings, pane assembly, and the frame fan-out.

Layout follows the shape a packet operator already has in their head from
BPQTerminal and EasyTerm, because the goal is a familiar tool that happens to
be modern, not a novel one they have to relearn:

    F1 Terminal  F2 Monitor  F3 Heard  F4 APRS  F5 Settings
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
Heard  f4 APRS  f5 Settings` right below a tab bar already showing those same
five names -- the same words twice, in two different corners of the screen.
All five `Binding`s stay registered (`show=False`) so the keys still work;
only the redundant on-screen label moves. `Ctrl+1..5` remain as unlabelled
fallback aliases for terminals that intercept function keys.

**Function keys are tabs. Ctrl sequences are actions and modals.** That is
the whole rule, and it is why Settings is F5 (the fifth tab, left to right)
rather than the command reference, and why the command reference -- a modal
opened over whatever tab is active -- is `Ctrl+R`, not a function key. A
non-tab action squatting on the next free F-number breaks the "F<n> is the
n-th tab" pattern the moment an n-th tab exists to expect it, which already
happened once here.

This also reserves the F-row for the tabs still to come (Mail, Bulletins,
Files -- see docs/ROADMAP.md). Note the ceiling: F1..F8 are delivered
reliably by essentially every terminal, F9+ are not, so **eight tabs is the
practical maximum** for this scheme. Five exist and three are planned, which
lands exactly on it -- a ninth tab needs a different navigation scheme, not a
ninth function key.

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

**One shared frame fan-out.** The station, the monitor pane, and the heard
table all end up fed from the same two subscriptions --
`station.on_unhandled` and `station.on_incoming` -- registered exactly once,
in this class's `on_mount`. A frame is decoded once. Adding a second decode
path for a new pane, anywhere, is the wrong instinct -- add a subscriber to
the existing fan-out instead. `KissTermApp` is deliberately the *only* place
that touches `self.station` for this reason: a pane that subscribed to the
station on its own would be a second fan-out.

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

import logging
from pathlib import Path

from rich.table import Table
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Static, TabbedContent, TabPane

from .. import __version__
from ..ax25 import AX25Station, parse_path
from ..beacon import Beaconer
from ..config import BeaconConfig
from ..ax25.frame import AX25Frame
from ..heard import HeardTable
from ..hotplug import PortEvent, SerialPortWatcher
from ..monitor import MonitorFilter, format_frame, sanitize
from ..session_log import SessionLog
from ..transport.base import SessionState, TransportError
from .aprs_pane import AprsPane
from . import themes
from .clock import KissTermHeader
from ..nodes import CommandReference
from ..nodes.reference import identify_family
from .dialogs import CallsignScreen, CommandReferenceScreen, ConnectScreen
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
        Binding("f5", "show_tab('settings')", "Settings", show=False),
        Binding("ctrl+5", "show_tab('settings')", "Settings", show=False),
        Binding("ctrl+n", "connect", "Connect"),
        Binding("ctrl+d", "disconnect", "Disconnect"),
        Binding("ctrl+k", "set_callsign", "Callsign"),
        Binding("ctrl+r", "command_reference", "Commands"),
        Binding("ctrl+l", "clear_log", "Clear", show=False),
    ]

    def __init__(self, config, station: AX25Station | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.config = config
        # Applied before the rest of __init__ so the very first frame paints
        # in the configured theme rather than Textual's own default and then
        # visibly flashing over to the right one a moment later.
        self.apply_theme()
        self.station = station
        self.heard = HeardTable()
        self.monitor_filter = MonitorFilter()
        #: The one active link, if any. Panes read this off `self.app` rather
        #: than tracking their own copy -- see this module's docstring.
        self.link = None
        self._status = "starting"
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
            with TabPane("F5 Settings", id="settings"):
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
            self.station.on_unhandled.append(self._on_monitor_frame)
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
        if why and self.beaconer.config.enabled:
            # Only worth saying when the operator asked for a beacon and did
            # not get one. "beaconing is off" is not news.
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
    def _on_monitor_frame(self, frame: AX25Frame, port: int = 0) -> None:
        """Every frame not belonging to a link. Feeds monitor and heard list."""
        self.heard.record(frame, port)
        if self.monitor_filter.allows(frame, port):
            line = format_frame(frame, port)
            for pane in self._base_query(MonitorPane):
                pane.write_line(line.as_text())

    def _on_incoming_link(self, link) -> None:
        self._to_terminal("log", f"\n*** Incoming connection from {link.peer}\n")
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
        mycall = str(self.station.mycall) if self.station is not None else ""
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
    def action_show_tab(self, tab: str) -> None:
        self.query_one("#main-tabs", TabbedContent).active = tab

    def action_clear_log(self) -> None:
        active = self.query_one("#main-tabs", TabbedContent).active
        if active == "monitor":
            self.query_one(MonitorPane).clear()
        else:
            self.query_one(TerminalPane).clear()

    @work
    async def action_connect(self) -> None:
        if self.station is None:
            self.notify("No transport is open.", severity="error")
            return
        target = await self.push_screen_wait(ConnectScreen())
        if not target:
            return
        path = parse_path(target)
        self.query_one(TerminalPane).log(f"\n*** Connecting to {path.destination}...\n")
        try:
            link = await self.station.connect(path)
        except TransportError as exc:
            self.notify(str(exc), severity="error")
            return
        if link is None:
            self.query_one(TerminalPane).log(f"*** No connection to {path.destination}\n")
            self.notify(f"Could not connect to {path.destination}", severity="warning")
            return
        self._bind_link(link)
        self.query_one(TerminalPane).focus_input()

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
        if self.link is None or not self.link.connected:
            self.notify("Not connected.", severity="warning")
            return
        self.query_one(TerminalPane).log("\n*** Disconnecting...\n")
        await self.link.disconnect()

    # ------------------------------------------------------------------
    # Periodic UI refresh
    # ------------------------------------------------------------------
    def _refresh_status(self) -> None:
        parts = [f"kissterm {__version__}", self._status]
        if self.station is not None:
            parts.append(str(self.station.mycall))
        if self.link is not None:
            stats = self.link.stats
            parts.append(f"{self.link.peer} {self.link.state.value}")
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
        elif event.pane.id == "settings":
            # Same rule as the heard table: a pane must be correct the instant
            # it is visible. Re-rendering also discards half-typed edits the
            # operator navigated away from without saving, which is the
            # behaviour that matches "this shows what is in effect".
            self.query_one(SettingsPane).render_settings(self.config)
        self._refresh_status()
