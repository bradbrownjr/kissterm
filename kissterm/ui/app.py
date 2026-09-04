"""The `KissTermApp` class: bindings, pane assembly, and the frame fan-out.

Layout follows the shape a packet operator already has in their head from
BPQTerminal and EasyTerm, because the goal is a familiar tool that happens to
be modern, not a novel one they have to relearn:

    Terminal  Monitor  Heard  APRS  Settings          <- Ctrl+1..5 / F1..F4
    +--------------------------------------------+
    | session output (scrollback, selectable)     |
    +--------------------------------------------+
    | > type here                                 |
    +--------------------------------------------+
      status: transport - link state - queue depth

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

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from .. import __version__
from ..ax25 import AX25Station, parse_path
from ..ax25.frame import AX25Frame
from ..heard import HeardTable
from ..monitor import MonitorFilter, format_frame
from ..transport.base import SessionState, TransportError
from .aprs_pane import AprsPane
from .dialogs import ConnectScreen
from .heard_pane import HeardPane
from .monitor_pane import MonitorPane
from .settings_pane import SettingsPane
from .styles import APP_CSS
from .terminal_pane import TerminalPane

log = logging.getLogger(__name__)


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
        Binding("f1", "show_tab('terminal')", "Terminal"),
        Binding("f2", "show_tab('monitor')", "Monitor"),
        Binding("f3", "show_tab('heard')", "Heard"),
        Binding("f4", "show_tab('aprs')", "APRS"),
        Binding("ctrl+1", "show_tab('terminal')", "Terminal", show=False),
        Binding("ctrl+2", "show_tab('monitor')", "Monitor", show=False),
        Binding("ctrl+3", "show_tab('heard')", "Heard", show=False),
        Binding("ctrl+4", "show_tab('aprs')", "APRS", show=False),
        Binding("ctrl+5", "show_tab('settings')", "Settings", show=False),
        Binding("ctrl+n", "connect", "Connect"),
        Binding("ctrl+d", "disconnect", "Disconnect"),
        Binding("ctrl+l", "clear_log", "Clear", show=False),
    ]

    def __init__(self, config, station: AX25Station | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.config = config
        self.station = station
        self.heard = HeardTable()
        self.monitor_filter = MonitorFilter()
        #: The one active link, if any. Panes read this off `self.app` rather
        #: than tracking their own copy -- see this module's docstring.
        self.link = None
        self._status = "starting"

    # ------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="terminal", id="main-tabs"):
            with TabPane("Terminal", id="terminal"):
                yield TerminalPane()
            with TabPane("Monitor", id="monitor"):
                yield MonitorPane()
            with TabPane("Heard", id="heard"):
                yield HeardPane()
            with TabPane("APRS", id="aprs"):
                yield AprsPane()
            with TabPane("Settings", id="settings"):
                yield SettingsPane()
        yield Static(id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(SettingsPane).render_settings(self.config)
        self.set_interval(1.0, self._refresh_status)
        self.set_interval(2.0, self._refresh_heard)
        if self.station is not None:
            self.station.on_unhandled.append(self._on_monitor_frame)
            self.station.on_incoming.append(self._on_incoming_link)
            self._status = f"{self.station.transport.info.detail}"
        self.query_one(TerminalPane).log(
            f"kissterm {__version__} -- Ctrl+N to connect, Ctrl+H for help.\n"
        )

    # ------------------------------------------------------------------
    # Frame fan-out
    # ------------------------------------------------------------------
    def _on_monitor_frame(self, frame: AX25Frame, port: int = 0) -> None:
        """Every frame not belonging to a link. Feeds monitor and heard list."""
        self.heard.record(frame, port)
        if self.monitor_filter.allows(frame, port):
            line = format_frame(frame, port)
            self.query_one(MonitorPane).write_line(line.as_text())

    def _on_incoming_link(self, link) -> None:
        self.query_one(TerminalPane).log(f"\n*** Incoming connection from {link.peer}\n")
        if self.link is None or not self.link.connected:
            self._bind_link(link)
        self.notify(f"Connection from {link.peer}", severity="information")

    def _bind_link(self, link) -> None:
        self.link = link
        link.on_data.append(self._on_link_data)
        link.on_state.append(self._on_link_state)
        link.on_error.append(
            lambda why: self.query_one(TerminalPane).log(f"\n*** {why}\n")
        )
        self.query_one(TerminalPane).set_placeholder(f"connected to {link.peer}")

    def _on_link_data(self, data: bytes) -> None:
        self.query_one(TerminalPane).write_incoming(data)

    def _on_link_state(self, state: SessionState) -> None:
        self.query_one(TerminalPane).log(f"\n*** {state.value}\n")
        if state is SessionState.DISCONNECTED:
            self.query_one(TerminalPane).set_placeholder("not connected -- Ctrl+N")

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
        parts.append(f"heard {len(self.heard)}")
        self.query_one("#status-bar", Static).update("  |  ".join(parts))

    def _refresh_heard(self) -> None:
        if self.query_one("#main-tabs", TabbedContent).active != "heard":
            return
        self.query_one(HeardPane).refresh_from(self.heard)
