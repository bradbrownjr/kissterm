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
import logging
import re
import time
from datetime import datetime
from pathlib import Path

from rich.table import Table
from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Static, TabbedContent, TabPane, Tabs
from textual.widgets._footer import FooterKey

from .. import __version__
from ..addressbook import AddressBook, adopt_internet_transports
from ..netrom import KnownNodes
from ..ax25 import AX25Station, parse_path
from ..core import Core, GateChanged, TransportChanged
from ..core.events import (
    ActivityChanged,
    Alert,
    AprsAcked,
    AprsBulletinHeard,
    AprsMessage,
    AprsPacketHeard,
    AprsRetried,
    ConnectingChanged,
    LineSent,
    SessionData,
    SessionOpened,
    SessionStateChanged,
    SessionUpdated,
)
from ..core.connect import ConnectRequest
from ..core.connect import session_key as _session_key_of
from ..core.hops import HopConfirmation as _HopConfirmation
from ..core.links import SessionLinkAdapter as _SessionLinkAdapter
from ..ax25.address import AX25Address
from ..config import (
    credential_store,
    credential_username,
    find_credential,
    move_credentials_to_keyring,
    rescue_typed_secrets,
    set_credential,
    login_text as saved_login_text,
    mail_path,
    state_path,
)
from ..mail import MessageStore
from ..mail.store import ALL_INBOXES, INBOX, MAIL, SENT
from ..mail.winlink_collect import WINLINK_FOLDER
from .. import desktop_notify
from .. import updater
from ..ax25.frame import PID_NO_LAYER3, AX25Frame, UType
from ..hotplug import PortEvent, SerialPortWatcher
from ..monitor import MonitorFilter, format_frame, mail_waiting_for, sanitize
from ..session_log import SessionLog
from ..transport.base import SessionState, TransportError, TransportState
from ..tx import TransmitGate
from ..watched_notify import WatchNotifier, claimed_callsigns, normalize_callsigns
from ..autobin import AutoBinError, receive_file as receive_autobin, send_file as send_autobin
from ..yapp import YappError, receive_file, send_file, starts_download
from .aprs_pane import AprsPane
from . import themes
from .clock import KissTermHeader
from . import commands as cmdreg
from .commands import TAB_ORDER, KeyBindingsProvider
from .menu import MenuScreen
from ..nodes import Command, CommandReference
from .dialogs import (
    CallsignScreen,
    CommandReferenceScreen,
    ConnectScreen,
    AprsObjectScreen,
    AprsObjectRequest,
    AprsIsWatchScreen,
    SETUP_GO,
    SETUP_SKIP,
    GatewayChoice,
    HomeBbsSetupScreen,
    Credential,
    InternetLogin,
    InternetLoginScreen,
    login_where,
    WinlinkGatewayScreen,
    LoginAskScreen,
    TranscriptsScreen,
    FileTransferScreen,
    UpdateScreen,
)
from .heard_pane import HeardPane
from .monitor_pane import MonitorPane
from .settings_pane import SettingsPane
from .help_pane import HelpPane
from .mail_pane import MessageBrowser, MessageList, bulletins_browser, files_browser, mail_browser
from .styles import APP_CSS
from .operator import TextualOperator
from .terminal_pane import TerminalPane

log = logging.getLogger(__name__)


_HOST_PORT = re.compile(r"^(\[[^\]]+\]|[^:\s]+):\d+(?:/\d+)?$")


def _without_port(detail: str) -> str:
    """A transport's detail with any `host:port` cut to the host, for the
    status bar (operator, 2026-10-02: room for the fields that change).
    `10.6.26.128:8001` -> `10.6.26.128`, `me@node:22` -> `me@node`, VARA's
    `host:8300/8301` -> `host`. A bare IPv6 address has colons of its own
    and is left whole rather than cut in the wrong place; a serial device
    or Bluetooth address has no port to cut."""
    return " ".join(
        match[1] if (match := _HOST_PORT.match(word)) else word
        for word in detail.split(" ")
    )


def _short_peer(peer: str) -> str:
    """A link peer as the status bar names it. An AX.25 call is itself; an
    Internet session's `user@host:port` is its host's first label in
    capitals (`packet@ws1ec.mainepacketradio.org:4722` -> `WS1EC`), which
    for a packet node's own domain is its callsign. An IP address stays
    whole. The full address made the field wrap, and the bar showed only
    "kc1uix-3 via" (operator, 2026-10-02: "plenty of room to say WS1EC")."""
    host = _without_port(peer).rsplit("@", 1)[-1]
    if "." not in host or re.fullmatch(r"[\d.]+|\[.*\]|.*:.*", host):
        return host
    return host.split(".", 1)[0].upper()


def _status_row(parts: list[str | Text]) -> Table:
    """Lay `parts` out across the FULL width of the status bar, not bunched
    at the left with the rest of the row empty.

    A plain ``"  |  ".join(parts)`` string looks fine on a narrow terminal and
    leaves most of a wide one blank -- exactly the "half the screen is empty"
    look this replaces. A `Table.grid` with one equal-ratio column per field
    re-flows automatically as the terminal is resized and as the number of
    fields changes (there are more of them once a link is connected), which a
    hand-computed padding string would not do without being recomputed on
    every resize event. The first field reads as a left anchor (the
    transport), the last as a right anchor, and everything
    between is centered in its own share of the row -- the conventional shape
    of an editor or IDE status bar.

    Each field is as wide as its text and only the spare room is shared out
    (no `ratio`). Equal shares cut a long field to a ninth of the row
    while short ones sat in empty space: "Checking for" with "mail" lost
    on a second line nobody sees (operator, 2026-10-02). When even the text
    does not fit, a field ends in an ellipsis rather than wrapping out of
    sight.
    """
    # pad_edge: the one-space margin at each end, here rather than as the
    # widget's CSS padding, which crops the last field (styles.py).
    table = Table.grid(expand=True, padding=(0, 1), pad_edge=True)
    for i in range(len(parts)):
        justify = "left" if i == 0 else "right" if i == len(parts) - 1 else "center"
        table.add_column(justify=justify, no_wrap=True, overflow="ellipsis")
    table.add_row(*parts)
    return table




#: How long after the operator sends `YAPP <name>` a YAPP send init is
#: taken as the file they asked for (`KissTermApp._watch_for_download`).
#: WS1EC-2 answered in 3 s over the air (2026-10-03); a minute covers a
#: slow path without leaving a stale request armed.
DOWNLOAD_WAIT_SECONDS = 60.0

#: BPQMail's download command (`YAPP <name>`, LinBPQ `BBSUtilities.c`
#: matches its first four letters, any case).
_YAPP_REQUEST = re.compile(r"^\s*YAPP\s+\S", re.IGNORECASE)

class _TerminalSessionView:
    """The connect flow's `SessionView` (kissterm/core/connect.py): which
    Terminal tab is on screen, whether there is room for another, and
    putting one in front of the operator. Sessions themselves are the
    core's; this is only how this app shows them."""

    def __init__(self, app: "KissTermApp") -> None:
        self._app = app

    def _pane(self) -> "TerminalPane":
        return self._app.query_one(TerminalPane)

    def active_key(self) -> str:
        return self._app._active_key()

    def has_room_for(self, key: str) -> bool:
        return self._pane().has_room_for(key)

    def open_session(self, key: str, *, kind: str, focus: bool) -> None:
        """Close the Address Book slide-outs a dial came from and put the
        session's tab on screen. Radio: always, the tab activated, Terminal
        shown if dialed from a mail tab and `focus`. Internet: only with
        `focus`, the tab activated only then. Session tier: the one `""`
        tab, cleared for the new connection."""
        app = self._app
        pane = self._pane()
        if kind == "internet" and not focus:
            pane.open_tab(key, activate=False)
            return
        pane.close_addressbook_for_connection()
        dialed_from_mail = False
        for browser in app.query(MessageBrowser):
            dialed_from_mail |= browser.close_addressbook(refocus=False)
        if dialed_from_mail and (focus or kind != "radio"):
            app.action_show_tab("terminal")
        if kind == "session":
            pane.clear("")
        else:
            pane.open_tab(key, activate=True)

    def is_active(self, key: str) -> bool:
        return self._pane().active_session_key == key

    def focus_input(self) -> None:
        self._pane().focus_input()


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

    TITLE = f"kissterm {__version__}"
    #: Seconds a toast stays up; nothing passes a shorter one (DESIGN.md
    #: section 6). Textual's 5, and the 4 some toasts had, went by before a
    #: pair could be read (operator, 2026-10-02).
    NOTIFICATION_TIMEOUT = 10

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
        check_updates: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.config = config
        #: Whether this launch may look on GitHub for a newer kissterm (once
        #: a day, `Config.update_check` permitting). False unless the real
        #: launch asks, so a test mounting the app never touches the network.
        self._check_updates = check_updates
        #: The newer version already announced, so it is toasted once.
        self._update_available: str | None = None
        #: Replaced in tests; see kissterm/updater.py.
        self._fetch_latest = updater.fetch_latest
        #: The message store behind Mail, Bulletins and Files. Under the
        #: platformdirs data directory, so `_isolate` redirects it in tests.
        self.mail_store = MessageStore(mail_path())
        try:
            self.mail_store.ensure_default_tree()
        except OSError:
            # An unwritable data directory must not stop the terminal from
            # starting; the Mail tab just shows nothing.
            pass
        if config.ascii_safe:
            # The stylesheet supplies ASCII alternatives only within this
            # application.  Do not mutate Textual's process-wide glyph tables:
            # other apps (and parallel tests) may be rendering at the same time.
            self.add_class("-ascii-safe")
        # Applied before the rest of __init__ so the very first frame paints
        # in the configured theme rather than Textual's own default and then
        # visibly flashing over to the right one a moment later.
        for extra in themes.EXTRA_THEMES.values():
            self.register_theme(extra)
        self.apply_theme()
        #: The station with no UI (`kissterm/core/`): transports, the
        #: transmit gate, and the flows as they move out of this class
        #: (ROADMAP P7a). It installs the operator's gate on the transport --
        #: a bare transport is a dumb pipe whose own gate is open -- closed
        #: unless `tx_armed_at_start`, so a fresh launch cannot key a radio
        #: until Ctrl+T. `station`, `session_transport` and `gate` below are
        #: read through to it. This app is its operator (`ui/operator.py`)
        #: and its frame fan-out's subscribers, registered once here and
        #: moved by the core when the transport changes.
        self.core = Core(
            config,
            station,
            session_transport=session_transport,
            transport_problem=transport_problem,
            operator=TextualOperator(self),
        )
        self.core.frame_subscribers += [self._on_received_frame, self._on_aprs_frame]
        self.core.sent_subscribers.append(self._on_sent_frame)
        self.core.events.subscribe(self._on_core_event)
        #: The sessions (`kissterm/core/sessions.py`) and the connect flow
        #: (`connect.py`), shown in this app's Terminal tabs. A file transfer
        #: still reads session bytes here until it moves into the core.
        self.core.attach_view(_TerminalSessionView(self))
        self.core.sessions.data_interceptors.append(self._intercept_link_data)
        self.core.sessions.sent_hooks.append(self._yapp_requested)
        self.gate.on_change.append(self._on_transmit_change)
        self.monitor_filter = MonitorFilter()
        #: True while Send/Receive runs (`action_get_mail`); one at a time.
        self._collecting = False
        #: While G or I on All Inboxes prepares its runs: (key, service
        #: being asked about), so each question says why it is asked and
        #: offers to skip that service (`_all_inboxes_ask`).
        self._all_inboxes: tuple[str, str] | None = None
        #: A background job's status-bar field ("Receiving 1 of 3"), shown green.
        self._activity = ""
        #: Stations already tried, offered in the connect dialog. Owned here
        #: rather than by the dialog so a successful connect can be recorded
        #: after the dialog has closed, and so the file is read once at
        #: startup instead of on every Ctrl+N.
        self.addressbook = AddressBook()
        self.addressbook.load()
        self.known_nodes = KnownNodes()
        from ..mail.bulletins import SubscriptionBook

        #: Bulletin categories chosen per BBS (`mail/bulletins.py`).
        self.bulletin_subscriptions = SubscriptionBook()
        self.bulletin_subscriptions.load()
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

    # ------------------------------------------------------------------
    # Read through to the core (`kissterm/core/service.py`)
    # ------------------------------------------------------------------
    @property
    def station(self) -> AX25Station | None:
        """The AX.25 station on a frame transport; None on a session one
        (Telnet, SSH, VARA, Mercury, kernel AX.25), where there is no AX.25
        state machine to run underneath. At most one of `station` and
        `session_transport` is set; `action_connect` brings the two paths
        to the same terminal-pane binding through `_SessionLinkAdapter`."""
        return self.core.station

    @property
    def session_transport(self):
        return self.core.session_transport

    @property
    def config(self):
        """The one configuration, the core's. Settings saves by replacing
        it (`SettingsPane`), so the core must see the replacement too: a
        copy here would leave the connect flow and the beacons on the old
        one."""
        core = self.__dict__.get("core")
        return core.config if core is not None else self.__dict__["_config"]

    @config.setter
    def config(self, config) -> None:
        self.__dict__["_config"] = config
        core = self.__dict__.get("core")
        if core is not None:
            core.config = config

    # APRS, the heard list, both beacons and GPS (`kissterm/core/aprs.py`)
    @property
    def heard(self):
        return self.core.heard

    @property
    def aprs_conversations(self):
        return self.core.aprs.conversations

    @aprs_conversations.setter
    def aprs_conversations(self, store) -> None:
        self.core.aprs.conversations = store

    @property
    def beaconer(self):
        return self.core.aprs.beaconer

    @property
    def aprs_beaconer(self):
        return self.core.aprs.aprs_beaconer

    @property
    def aprs_is_watch(self):
        return self.core.aprs.is_watch

    @property
    def gps_reader(self):
        return self.core.aprs.gps_reader

    @property
    def _aprs_notify_cooldown(self):
        return self.core.aprs.notify_cooldown

    @_aprs_notify_cooldown.setter
    def _aprs_notify_cooldown(self, cooldown) -> None:
        self.core.aprs.notify_cooldown = cooldown

    @property
    def gate(self) -> TransmitGate:
        """The master transmit switch (kissterm/tx.py)."""
        return self.core.gate

    @property
    def _transport_problem(self) -> str | None:
        """Why the configured transport would not open at launch, when the
        operator chose to start anyway (`kissterm/__main__.py`). On mount
        the app lands on Settings > Radio with this in front of them,
        because that is the page that fixes it -- see `_show_transport_problem`."""
        return self.core.transport_problem

    @property
    def addressbook(self):
        """Stations already tried, offered in the connect dialog; held by
        the core, which the connect flow reads and records into."""
        return self.core.addressbook

    @addressbook.setter
    def addressbook(self, book) -> None:
        self.core.addressbook = book

    # The connect flow's state, held by `core.connector`: attempts still
    # calling (Ctrl+D cancels them), what each tab last dialed (Ctrl+R).
    @property
    def _connecting(self) -> dict:
        return self.core.connector.connecting

    @property
    def _internet_connecting(self) -> dict:
        return self.core.connector.internet_connecting

    @property
    def _session_connect_task(self):
        return self.core.connector.session_connect_task

    @property
    def _last_connect(self) -> dict:
        return self.core.connector.last_connect

    def _on_core_event(self, seq: int, event) -> None:
        """Show what the core says happened. The status bar follows
        transport, gate and session changes at once, not on the next
        one-second refresh; session events reach the Terminal tabs."""
        if isinstance(event, (TransportChanged, GateChanged)):
            self._refresh_status()
        elif isinstance(event, SessionData):
            self._to_terminal(event.key, "write_incoming", event.data)
        elif isinstance(event, LineSent):
            self._to_terminal(event.key, "write_note", event.text + "\n")
        elif isinstance(event, SessionOpened):
            self._show_session(event)
        elif isinstance(event, SessionUpdated):
            self._refresh_status()
            self._refresh_context_footer()
        elif isinstance(event, SessionStateChanged):
            if event.state == SessionState.DISCONNECTED.value:
                self._to_terminal(event.key, "set_placeholder", "not connected -- Ctrl+N")
            self._refresh_context_footer()
        elif isinstance(event, ConnectingChanged):
            self._refresh_context_footer()
        elif isinstance(event, ActivityChanged):
            self._set_activity(event.text)
        elif isinstance(event, AprsMessage):
            self._note_aprs_incoming(event.correspondent, to_me=event.to_me)
        elif isinstance(event, (AprsAcked, AprsRetried)):
            self._repaint_aprs_conversation()
        elif isinstance(event, AprsPacketHeard):
            for pane in self._base_query(AprsPane):
                pane.note_packet(event.line, event.at, event.packet)
        elif isinstance(event, AprsBulletinHeard):
            for pane in self._base_query(AprsPane):
                pane.note_bulletin(event.source, event.addressee, event.text, event.at)
        elif isinstance(event, Alert):
            self._notify_aprs_desktop(event.title, event.body, urgent=event.urgent)

    def _show_session(self, event: SessionOpened) -> None:
        """A tab for a session the core just bound. A call that came in
        while another session is on screen opens a tab without stealing
        the view, and is marked unread instead."""
        for pane in self._base_query(TerminalPane):
            activate = event.activate
            if event.incoming:
                activate = pane.session_count == 0
            pane.open_tab(event.key, activate=activate)
            if event.incoming and not activate:
                pane.mark_unread(event.key)
            pane.set_placeholder(event.key, f"connected to {event.peer}")
        self._refresh_context_footer()

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

    def _adopt_internet_transports(self) -> None:
        """Telnet and SSH connections become Address Book contacts
        (`addressbook.adopt_internet_transports`); before the keyring move,
        which then takes their passwords out of config.toml."""
        from .addressbook_pane import AddressBookPane

        added = adopt_internet_transports(self.addressbook, self.config)
        if not added:
            return
        self._save_config()
        for pane in self.query(AddressBookPane):
            pane.refresh_from(self.addressbook)
        self.notify("In the Address Book now: " + ", ".join(added)
                    + " (Telnet and SSH connections are contacts).")

    @work(thread=True, exclusive=True, group="keyring")
    def _move_credentials_to_keyring(self) -> None:
        """Logins saved as text in config.toml move to the OS keyring when
        there is one (`kissterm/keystore.py`); off the UI thread, since a
        keyring may be slow to answer or ask to be unlocked."""
        from ..addressbook import fold_ssh_usernames
        from ..config import fold_home_bbs_user, split_old_logins

        try:
            rescued = rescue_typed_secrets(self.config)
            moved = move_credentials_to_keyring(self.config)
            # Logins became a username and a password (operator, 2026-09-28).
            split = split_old_logins(self.config)
            folded = fold_home_bbs_user(self.config)
            folded = bool(fold_ssh_usernames(self.addressbook, self.config)) or folded
        except Exception as exc:  # noqa: BLE001 - never disturb the launch
            log.warning("keyring: moving saved logins failed: %s", exc)
            return
        if split or folded:
            self.call_from_thread(self._save_config)
        if rescued:
            self.call_from_thread(self._save_config)
            self.call_from_thread(
                self.notify,
                "A password was typed into a login-name setting and was in "
                "config.toml; it is now the saved login "
                + ", ".join(f'"{n}"' for n in rescued) + ", and gone from the file.",
                timeout=10)
        if moved:
            self.call_from_thread(self._save_config)
            self.call_from_thread(
                self.notify,
                f"Moved {moved} saved login{'s' if moved != 1 else ''} from config.toml "
                "into the system keyring.")

    def on_mount(self) -> None:
        self.query_one(SettingsPane).render_settings(self.config)
        # Paint once immediately, then on a timer. Without the eager call the
        # status bar is blank for the first second of every launch, which
        # reads as "the app has not connected to anything" at exactly the
        # moment the operator is looking for confirmation that it has.
        self._refresh_status()
        self._start_port_watcher()
        self._adopt_internet_transports()
        self._move_credentials_to_keyring()
        self.set_interval(1.0, self._refresh_status)
        self.set_interval(2.0, self._refresh_heard)
        self._attach_station()
        self.core.aprs.start()
        if self._check_updates and getattr(self.config, "update_check", True):
            # After the first screen, so the check never competes with it.
            self.set_timer(3.0, lambda: self._update_check_worker(False))
        # No banner in the Terminal: it holds only what the far end sent and
        # what the operator sent (operator, 2026-10-02). The version is in
        # the title bar, the keys in the Footer, a transport problem in the
        # status bar and `_show_transport_problem`.
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
        self.core.attach_station()

    async def _open_initial_transport(self, name: str) -> bool:
        """Open the first saved transport in an already-mounted onboarding
        app (`Core.open_initial_transport`), and point the beacons at the
        station it built."""
        return await self.core.open_initial_transport(name)

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
        """`Aprs.reconcile_is_debug_watch` (kissterm/core/aprs.py)."""
        self.core.aprs.reconcile_is_debug_watch()

    def _aprs_is_background_requested(self) -> bool:
        return self.core.aprs.is_background_requested()

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
        """`Aprs.restart_beacon`: stop then start, never a live mutation."""
        await self.core.aprs.restart_beacon()

    @work
    async def _restart_gps(self) -> None:
        """`Aprs.restart_gps`: replace the local NMEA reader."""
        await self.core.aprs.restart_gps()

    @work
    async def _restart_aprs_beacon(self) -> None:
        """`Aprs.restart_aprs_beacon`: stop then start the position beacon."""
        await self.core.aprs.restart_aprs_beacon()

    def _fatal_error(self) -> None:
        """Textual's crash report, without local variables. Textual prints
        every frame's locals, and a crash inside Get mail printed the
        Winlink password among them (operator, 2026-10-03). The stack alone
        names the line; the full report also goes to kissterm.log, still
        without locals, so a crash can be sent in without editing it.
        Overrides a private Textual method (8.2.8);
        `tests/pilot/test_crash_report.py` fails if it stops being called."""
        import rich
        from rich.segment import Segments
        from rich.traceback import Traceback

        log.error("kissterm crashed", exc_info=True)
        self.bell()
        traceback = Traceback(show_locals=False, width=None, suppress=[rich])
        self._exit_renderables.append(
            Segments(self.console.render(traceback, self.console.options))
        )
        self._close_messages_no_wait()

    def on_unmount(self) -> None:
        """Disarm the beacons as the app goes away.

        Not merely tidy: a beacon task still armed while the UI is being torn
        down would transmit under the operator's callsign with nothing on
        screen to show it -- and nowhere to show it.
        """
        self.core.aprs.shutdown()
        self.core.detach_transport()
        self.core.connector.cancel_tasks()
        self.core.sessions.shutdown()
        # An Internet contact's connection is the app's own to close: the
        # radio's transport is closed by whoever built it, these by nobody.
        for session in self._sessions.values():
            link = session.link
            if getattr(link, "internet", False):
                link.close()
                asyncio.get_event_loop().create_task(link._close_transport())

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
            self.notify(
                f"{event.device} looks like a TNC ({event.detail}). "
                f"Settings (F9) > Radio to use it.",
                title="New device",
                timeout=10,
            )
            return

        # Removed. Only worth shouting about if it is the one in use.
        if self._active_device() == event.device:
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
        """`Aprs.active_identity` (kissterm/core/aprs.py)."""
        return self.core.aprs.active_identity()

    async def _on_aprs_frame(self, frame: AX25Frame, port: int = 0) -> None:
        """`Aprs.on_frame`, a subscriber on the one fan-out after the heard
        list's own, so a decoded position lands on an entry that exists."""
        await self.core.aprs.on_frame(frame, port)

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

    def _purge_stale_synthetic_messages(self) -> None:
        self.core.aprs.purge_stale_synthetic_messages()

    async def _send_aprs_ack(self, addressee: str, number: str, port: int) -> None:
        await self.core.aprs.send_ack(addressee, number, port)

    async def _send_aprs_message(
        self, addressee: str, text: str, number: str | None, *, port: int = 0, retry: bool = False
    ) -> bool:
        """`Aprs.send_message`: one message frame; never arms the gate."""
        return await self.core.aprs.send_message(addressee, text, number, port=port, retry=retry)

    def start_aprs_is_watch_for_debug(self) -> None:
        self.core.aprs.start_is_watch_for_debug()

    def action_aprs_gateway_form(self) -> None:
        """Open the APRS gateway form only in its relevant pane."""
        self.query_one(AprsPane).show_gateway_form()

    def action_aprs_bulletin(self) -> None:
        """Prepare a bulletin in APRS context; preparation never sends."""
        self.query_one(AprsPane).action_compose_bulletin()

    async def _send_aprs_object(self, request: AprsObjectRequest) -> bool:
        return await self.core.aprs.send_object(request)

    def _session_key(self, peer, port: int = 0) -> str:
        """The identity a Terminal-pane tab is keyed on (`core.connect.session_key`)."""
        return _session_key_of(peer, port)

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
            or key in self._internet_connecting
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
        session must read `LiveSession.current_node` through its own
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
        """`Sessions.on_incoming_link`: a station called and was answered."""
        self.core.sessions.on_incoming_link(link)

    def _on_stray_poll(self, peer, port: int) -> None:
        """`Sessions.on_stray_poll`: a node polls a link kissterm does not hold."""
        self.core.sessions.on_stray_poll(peer, port)

    # ------------------------------------------------------------------
    # Updates (Internet only; see kissterm/updater.py)
    # ------------------------------------------------------------------
    def action_check_updates(self) -> None:
        self.notify("Checking GitHub for a newer kissterm...")
        self._update_check_worker(True)

    @work(thread=True, exclusive=True, group="update")
    def _update_check_worker(self, manual: bool) -> None:
        """Learn the version on GitHub. A launch check asks at most once a
        day and otherwise reuses what it last heard; the menu always asks."""
        stamp = state_path() / "update-check.json"
        if manual or updater.due(stamp):
            latest = self._fetch_latest()
            updater.record_check(stamp, latest)
        else:
            latest = updater.cached_latest(stamp)
        self.call_from_thread(self._on_update_result, latest, manual)

    def _on_update_result(self, latest: str | None, manual: bool) -> None:
        if latest is not None and updater.is_newer(latest):
            first = self._update_available != latest
            self._update_available = latest
            if manual:
                self._offer_update(latest)
            elif first:
                # A toast, not a Terminal line: the operator may be on Mail
                # all session and never see the terminal (DESIGN.md 6).
                self.notify(
                    f"kissterm {latest} is available (you have {__version__}). "
                    "F10 > Help > Check for updates installs it.",
                    title="Update available",
                    timeout=15,
                )
            return
        if not manual:
            return
        if latest is None:
            self.notify(
                "Could not reach GitHub to check for updates.", severity="warning"
            )
        else:
            self.notify(f"kissterm {__version__} is the latest.")

    def _update_blocker(self) -> str | None:
        """Why updating now would hurt something under way, or None."""
        for session in self._sessions.values():
            if getattr(session.link, "connected", False):
                return "a session is connected; disconnect it first."
        if self._connecting or self._internet_connecting:
            return "a connect is under way; let it finish or cancel it first."
        if self._activity:
            return f"{self._activity} is under way; let it finish first."
        return None

    def _offer_update(self, latest: str) -> None:
        method = updater.detect_install()

        def _chosen(go: bool | None) -> None:
            if not go:
                return
            # Asked again at the moment of running: a connect may have
            # started while the dialog was open.
            blocker = self._update_blocker()
            if blocker:
                self.notify(f"Not updating: {blocker}", severity="warning")
                return
            self.notify(f"Running {method.advice}...")
            self._run_upgrade_worker(method)

        self.push_screen(
            UpdateScreen(__version__, latest, method, self._update_blocker()), _chosen
        )

    # Its own group: `exclusive` cancels within a group, and a check started
    # from the menu mid-upgrade must not cancel the upgrade's result.
    @work(thread=True, exclusive=True, group="upgrade")
    def _run_upgrade_worker(self, method: updater.InstallMethod) -> None:
        result = updater.run_upgrade(method)
        logging.getLogger(__name__).info(
            "upgrade (%s): ok=%s version=%s\n%s",
            " ".join(method.command or ()), result.ok, result.version, result.output,
        )
        self.call_from_thread(self._on_upgrade_result, result)

    def _on_upgrade_result(self, result: updater.UpgradeResult) -> None:
        if result.ok:
            self._update_available = None
            self.notify(
                f"kissterm {result.version} is installed. Quit (Ctrl+Q) and start "
                f"kissterm again to use it; this window is {__version__} until you do.",
                title="Updated",
                timeout=20,
            )
        else:
            # The full output is in the log (`_run_upgrade_worker`).
            tail = "\n".join(result.output.splitlines()[-4:]) or "(no output)"
            self.notify(
                f"Still {result.version or __version__}. {sanitize(tail)}",
                title="The update did not install",
                severity="error",
                timeout=30,
            )

    # ------------------------------------------------------------------
    # Sessions: `kissterm/core/sessions.py`. These read through to it, under
    # the names the panes and the mail flows have always used.
    # ------------------------------------------------------------------
    @property
    def _sessions(self) -> dict:
        """Per-session state (`sessions.LiveSession`) by session key; the
        permanent `""` entry is the pre-connection view."""
        return self.core.sessions.by_key

    @property
    def _harvested(self):
        return self.core.sessions.harvested

    @_harvested.setter
    def _harvested(self, store) -> None:
        self.core.sessions.harvested = store

    async def _send_banner(self, link) -> None:
        await self.core.sessions.send_banner(link)

    def _bind_link(self, link, session_key: str | None = None, *, activate: bool = True) -> str:
        """`Sessions.bind`: a connected link becomes a session and a tab."""
        return self.core.sessions.bind(link, session_key, activate=activate)

    def _transcript_directory(self) -> Path:
        return self.core.sessions.transcript_directory()

    def _close_transcript(self, session_key: str) -> None:
        self.core.sessions.close_transcript(session_key)

    def _note(self, session_key: str, text: str) -> None:
        self.core.sessions.note(session_key, text)

    def _record(self, session_key: str, text: str) -> None:
        """`Sessions.record`: to the transcript or kissterm.log, never the Terminal."""
        self.core.sessions.record(session_key, text)

    def log_sent(self, session_key: str, text: str, *, watch_hop: bool = True) -> None:
        """`Sessions.log_sent`: the record of a line sent, and the reply watch."""
        self.core.sessions.log_sent(session_key, text, watch_hop=watch_hop)

    def _cancel_hop_watch(self, session_key: str) -> None:
        self.core.sessions.cancel_hop_watch(session_key)

    def _commit_hop(self, session_key: str, node: str) -> None:
        self.core.sessions.commit_hop(session_key, node)

    def _on_link_data(self, session_key: str, data: bytes) -> None:
        self.core.sessions.on_link_data(session_key, data)

    def _on_link_state(self, session_key: str, state: SessionState) -> None:
        self.core.sessions.on_link_state(session_key, state)

    def _cancel_reply_timer(self, session_key: str) -> None:
        self.core.sessions.cancel_reply_timer(session_key)

    def _note_if_no_reply(self, session_key: str) -> None:
        self.core.sessions.note_if_no_reply(session_key)

    def _learned(self, node: str, context: str) -> tuple[Command, ...]:
        return self.core.sessions.learned(node, context)

    def learned_node(self, session_key: str) -> tuple[str, int]:
        return self.core.sessions.learned_node(session_key)

    def forget_learned(self, session_key: str) -> int:
        return self.core.sessions.forget_learned(session_key)

    def reference_sections(self, session_key: str) -> tuple[CommandReference, ...]:
        return self.core.sessions.reference_sections(session_key)

    def harvest_context(self, session_key: str) -> str:
        return self.core.sessions.harvest_context(session_key)

    async def harvest_commands(self, session_key: str, *, context: str = "node") -> tuple[str, ...]:
        """`Sessions.harvest_commands`: the opt-in `?`, once, cached forever."""
        return await self.core.sessions.harvest_commands(session_key, context=context)

    def last_harvest_text(self, session_key: str) -> str:
        return self.core.sessions.last_harvest_text(session_key)

    def _intercept_link_data(self, session_key: str, data: bytes) -> bool:
        """A file transfer's bytes are its own, not the session's: a run
        reading them (`_transfer_active`) or a YAPP download the operator
        asked for (`_watch_for_download`)."""
        if session_key in self._transfer_active:
            return True
        return self._watch_for_download(session_key, data)

    def _yapp_requested(self, session_key: str, text: str, session) -> None:
        """`YAPP <name>` sent: a YAPP send init in the next minute is that
        download -- not while G on the Files tab fetches it itself
        (`collect.BbsCollector._get_file`)."""
        if _YAPP_REQUEST.match(text) and session_key not in self._transfer_active:
            session.download_until = time.monotonic() + DOWNLOAD_WAIT_SECONDS

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
            self._record(self._active_key(), "Transmit enabled")
        else:
            blocked = ""
            self.notify(
                "Transmit DISABLED. Nothing will be sent." + blocked,
                severity="warning",
            )
            self._record(self._active_key(), "Transmit disabled")
        self._refresh_status()

    def _arm_for(self, what: str, toast: bool = True) -> bool:
        """`Connector.arm_for` (kissterm/core/connect.py), recorded on the
        Terminal tab on screen. The flows that still call this from the app
        (APRS send, file transfer) move into the core in later milestones."""
        return self.core.connector.arm_for(what, toast=toast)

    def _connect_problem(self, report, text: str, severity: str = "error") -> None:
        """Why a connect did not happen: a toast, or handed to `report` when
        the caller (Send/Receive) raises its own, so one failure is one
        notice, not two (operator, 2026-10-02; DESIGN.md section 6)."""
        if report is not None:
            report(text)
        else:
            self.notify(text, severity=severity)

    @work
    async def action_beacon_now(self) -> None:
        """Send one BTEXT beacon now (menu: Session > Send beacon).

        The timed beacon waits a full interval, because launching is not a
        request to key the radio; this is how an operator says "right now".
        It neither enables the timer nor arms the gate (`Aprs.beacon_now`).
        """
        await self.core.aprs.beacon_now()

    @work
    async def action_aprs_beacon_now(self) -> None:
        """Menu: APRS > Send position -- one position report now, which
        arms the gate as a committed send (`Aprs.send_position_now`)."""
        await self.core.aprs.send_position_now()

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
        await self.core.aprs.send_object_now(request)

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
        if action == "rms_gateways":
            from ..winlink import gateways

            if not gateways.ACCESS_KEY and gateways.load_cached(self._gateway_cache()) is None:
                return "needs an API key"
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
        self.call_after_refresh(self._focus_tab_target, tab)

    def _focus_tab_target(self, tab: str) -> None:
        """Focus `tab`'s `_TAB_FOCUS` widget, after the switch has settled,
        so this focus lands in the pane that is now visible. A missing
        widget is not an error: a pane can legitimately not have composed
        it yet.

        Re-checks the active tab first: two tab keys pressed in quick
        succession queue two of these, and the first one firing late would
        focus a widget in a pane the operator has already left --
        re-activating it, the very bug `action_show_tab` exists to fix.

        A FALLBACK, not an override: anything focused by now was claimed
        deliberately (`action_find_in_terminal` switches to the Terminal and
        focuses the find box; stealing that back put the operator's typing
        in the wrong widget). Only a vacuum is filled -- no focus, or focus
        on the tab row itself, which is where a click on a tab's label
        leaves it. Until 2026-10-04 a click took no part in this, so
        clicking Bulletins left G and I out of the Footer until the list
        was clicked too, and a click on Terminal left the send line without
        focus (operator: "a section isn't automatically selected").
        """
        target = self._TAB_FOCUS.get(tab)
        tabs = self.query_one("#main-tabs", TabbedContent)
        if target is None or tabs.active != tab:
            return
        if self.focused is not None and not isinstance(self.focused, Tabs):
            return
        for widget in self._base_query(target):
            widget.focus()
            return

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
        return self.core.frame_tier_transports()

    def _session_tier_transports(self) -> list[dict]:
        return self.core.session_tier_transports()

    async def _switch_frame_transport(self, name: str) -> bool:
        """`Core.switch_frame_transport`, then the beacons follow. Shared by
        `SettingsPane` (Save with a different Active transport) and
        `action_connect`'s transport picker, so "open the newly selected
        transport" has one implementation."""
        opened = await self.core.switch_frame_transport(name)
        if opened and self.station is not None:
            self.core.aprs.follow_station()
        return opened

    async def _switch_session_transport(self, name: str) -> bool:
        return await self.core.switch_session_transport(name)

    @work
    async def action_connect(
        self,
        prefill=None,
        target: str = "",
        redial: ConnectRequest | None = None,
        on_link=None,
        on_reached=None,
        focus_session: bool = True,
        announce: str = "",
        report=None,
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
        `announce` is the caller's "Connecting..." toast, raised when the
        SABMs are about to go (with the gate's arming in the same toast), and
        `report(text)` receives a failure's reason instead of a toast here:
        Send/Receive says both in its own words, once each.
        """
        # An Internet contact dials its own connection, radio or no radio
        # (`_dial_internet`); a redial of one finds it by name.
        contact = prefill if prefill is not None else (
            self.addressbook.find(redial.target) if redial is not None else None)
        if contact is not None and contact.is_internet:
            await self._dial_internet(contact, on_link=on_link, on_reached=on_reached,
                                      focus_session=focus_session, report=report)
            return
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
            self._connect_problem(report, "No transport is open.")
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
            contact = self.addressbook.find(request.target)
            if contact is not None and contact.is_internet:
                await self._dial_internet(contact, on_link=on_link, on_reached=on_reached,
                                          focus_session=focus_session, report=report)
                return
            if request.transport_name and request.transport_name != self.config.active_transport:
                self.config.active_transport = request.transport_name
                self._save_config()
                if not await self._switch_frame_transport(request.transport_name):
                    return
        # Everything from here -- the radio reminder, the gate, the SABMs,
        # the failure diagnosis, the hop chain and the login -- is the
        # core's (`Connector.connect`), the same for every front end.
        await self.core.connector.connect(
            request, entry=prefill, on_link=on_link, on_reached=on_reached,
            focus=focus_session, announce=announce, report=report,
        )

    async def _session_connect(self, transport):
        """`Connector.session_connect`: connect, asking to trust a new SSH server."""
        return await self.core.connector.session_connect(transport)

    async def _dial_internet(self, entry, *, on_link=None, on_reached=None,
                             focus_session: bool = True, report=None) -> None:
        """`Connector.dial_internet`: an Internet contact in its own tab."""
        await self.core.connector.dial_internet(
            entry, on_link=on_link, on_reached=on_reached, focus=focus_session, report=report)

    async def _connect_session_transport(self) -> None:
        """`Connector.connect_session_transport`: the session tier's one far end."""
        await self.core.connector.connect_session_transport()

    async def _await_hop_confirmation(self, link, node: str, timeout: float | None = None,
                                      watch: _HopConfirmation | None = None) -> tuple[bool, str]:
        """`Connector.await_hop_confirmation`, for a hand-typed hop (`log_sent`)."""
        return await self.core.connector.await_hop_confirmation(link, node, timeout, watch)

    @work(exclusive=False)
    async def action_compose_mail(self, reply: str = "", quoted: bool | None = False,
                                  form: str = "") -> None:
        """Write a message into Mail/BBS/Outbox, or Mail/Winlink/Outbox
        for a Winlink one (Mail tab: Insert, R, Q).

        `reply` is the store ref of the message answered; `quoted` None
        means "as Settings > Mail says" (R), True always quotes (Q).
        `form` starts at a Type as the compose screen returns it
        (`FORM_PREFIX` + id, or `RADIOGRAM`): Enter on a PKTNET form in the
        Files viewer. Nothing transmits: the message waits in the Outbox.
        """
        from ..config import state_path
        from ..locator import to_grid
        from ..mail import form_xml, forms
        from ..mail.compose import BBS_OUTBOX, SEND_WINLINK, bulletin_choices, radiogram_defaults
        from ..mail.winlink_collect import WINLINK_OUTBOX
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
        folder = self._mail_folder()
        on_winlink = folder == WINLINK_FOLDER or folder.startswith(f"{WINLINK_FOLDER}/")
        message = form or await self.push_screen_wait(
            ComposeScreen(str(self.config.mycall or ""), reply_to=original, quoted=bool(quoted),
                          bulletins=bulletin_choices(self.mail_store), winlink=on_winlink)
        )
        remembered_at = state_path() / "forms.json"
        aprs = self.config.aprs
        grid = to_grid(aprs.latitude, aprs.longitude) if aprs.latitude or aprs.longitude else ""

        filled: list = []  # (form, draft) of the last form filled in

        async def fill(form: forms.FormDef, values: forms.Values | None = None):
            draft = await self.push_screen_wait(FormScreen(
                form, mycall=str(self.config.mycall or ""), grid=grid,
                remembered=forms.load_remembered(remembered_at, form.id),
                mail=self._mail_log_entries, values=values,
            ))
            if draft is not None:
                forms.save_remembered(remembered_at, form.id,
                                      forms.to_remember(form, draft.form_values))
                filled[:] = [form, draft]
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
                ComposeScreen(str(self.config.mycall or ""), draft=draft, winlink=on_winlink)
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
        winlink = message.extra.get("Send-Type") == SEND_WINLINK
        xml, note = None, ""
        if winlink and filled and filled[0].winlink_viewer:
            # A Winlink form carries its XML (`mail/form_xml.py`), unless
            # the text was changed after the form: the XML would then
            # show a Winlink viewer something other than what was sent.
            form, draft = filled
            if message.body.rstrip() == draft.body.rstrip():
                try:
                    xml = form_xml.build(
                        form, draft.form_values, callsign=str(self.config.mycall or ""),
                        grid=grid, reply=original is not None,
                        extra={"theMsgSender": original.sender} if original is not None else None)
                except form_xml.TooManyRows as exc:
                    note = f" {exc}, so it goes as text only."
            else:
                note = " The text was changed after the form, so it goes as text only."
        self.mail_store.add(WINLINK_OUTBOX if winlink else BBS_OUTBOX, message,
                            raw=xml, raw_suffix=".xml")
        self._reload_mail_tabs()
        where = "Winlink Outbox" if winlink else "Outbox"
        self.notify(f"Saved to the {where}: {message.subject}.{note}")

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
        """Send/Receive (Mail tab, G). ROADMAP P2.

        G follows the folder in front (operator, 2026-09-26,
        `send_receive_kind`): a Winlink folder runs Winlink, a BBS folder
        the Home BBS, and All Inboxes each one in use, the Home BBS first
        (`send_receive_kind`). Missing logins are asked before the first dial
        (`_bbs_prepare`, `_winlink_prepare`). Each run dials through
        `_dial_for_mail`, so the
        reminder, the transmit gate, the hop chain and the route's own
        login all apply, and nothing here arms anything. The operator stays
        where they are: a toast says it started, the status bar shows its
        phase in green while it runs ("Sending 1 of 2", "Receiving 2 of
        4"), and a toast gives the outcome (DESIGN.md section 6). Every
        line sent is echoed in the session's Terminal tab and the
        transcript. When it finishes, the link is disconnected; Ctrl+D
        stops it.
        """
        if self._collecting:
            self.notify("Already sending and receiving.", severity="warning")
            return
        self._collecting = True
        try:
            kind = self.send_receive_kind(self._mail_folder())
            # Everything that has to be asked is asked before the first
            # dial, so a run of both never stops in between for a question.
            runs = await self._prepare_runs(kind, "G", (
                ("Home BBS", self._bbs_prepare, self._bbs_run),
                ("Winlink", self._winlink_prepare, self._winlink_run),
            ))
            for run, (entry, options) in runs or ():
                await run(entry, options)
        finally:
            self._collecting = False
            self._set_activity("")

    async def _prepare_runs(self, kind: str, key: str, services) -> list | None:
        """Ask everything each service in `kind` needs, in order; the runs
        to make, or None if the operator cancelled. On All Inboxes each
        question says why it is asked and can skip its service (operator,
        2026-09-27: make it "clear why they're being prompted")."""
        wanted = [s for s in services
                  if kind == "all" or s[0] == ("Winlink" if kind == "winlink" else "Home BBS")]
        runs = []
        try:
            for name, prepare, run in wanted:
                self._all_inboxes = (key, name) if kind == "all" else None
                try:
                    prepared = await prepare()
                except _SkipService:
                    self.notify(f"Skipping {name} this time.")
                    continue
                if prepared is None:
                    return None
                runs.append((run, prepared))
        finally:
            self._all_inboxes = None
        if not runs:
            self.notify("Nothing to send or receive: every service was skipped.")
        return runs

    def _all_inboxes_ask(self) -> tuple[str, str]:
        """(note, skip label) for a question asked on All Inboxes, else ("", "")."""
        if self._all_inboxes is None:
            return "", ""
        key, name = self._all_inboxes
        how = " over the Internet" if key == "I" else ""
        # The operator's wording, 2026-09-27.
        return (
            f"You have All Inboxes selected, therefore kissterm will check mail "
            f"for both BBS and Winlink{how}.",
            f"Skip {name}",
        )

    def _setup_answer(self, answer, place: str):
        """A setup question's answer: SETUP_SKIP raises `_SkipService`,
        SETUP_GO opens `place` and returns None (the run is cancelled),
        anything else is returned."""
        if answer == SETUP_SKIP:
            raise _SkipService
        if answer == SETUP_GO:
            self._go_to_setup(place)
            return None
        return answer

    def _go_to_setup(self, place: str) -> None:
        """Where a setup question's go button leads."""
        if place == "connect":
            self.action_connect()
            return
        path = {
            "winlink": "winlink.account",
            "bbs": "home_bbs.route",
        }[place]
        self.query_one("#main-tabs", TabbedContent).active = "settings"
        pane = self.query_one(SettingsPane)
        self.call_after_refresh(pane.open_field, path)

    def send_receive_kind(self, folder: str, internet: bool = False) -> str:
        """What G does from `folder` (operator, 2026-09-26): "winlink" on a
        Winlink folder; "bbs" anywhere else. On All Inboxes, "all" (the
        Home BBS, then Winlink) when both are in use, else whichever is,
        and "bbs" when neither is yet (the Home BBS's first-run question).

        In use = set up for G or for I, whichever key was pressed: what the
        key still needs is then asked for, with its Skip button (operator,
        2026-09-28: I "didn't ask for BBS over internet settings" when the
        Home BBS had a radio route but no Internet contact). A service set
        up for neither is not asked about, so a BBS-only station is not
        asked about Winlink at every G."""
        if folder == WINLINK_FOLDER or folder.startswith(f"{WINLINK_FOLDER}/"):
            return "winlink"
        if folder == ALL_INBOXES:
            home, winlink_config = self.config.home_bbs, self.config.winlink
            bbs = bool(home.route.strip() or home.internet.strip())
            winlink = bool(winlink_config.route.strip() or winlink_config.credential.strip())
            if bbs and winlink:
                return "all"
            if winlink:
                return "winlink"
        return "bbs"

    def _mail_folder(self) -> str:
        from .mail_pane import MessageBrowser

        browser = self.query("#mail-browser")
        return browser.first(MessageBrowser).folder if browser else ""

    async def _winlink_gateway(self):
        """The Address Book contact to reach Winlink through: the favourite
        gateway (Settings > Mail > Gateway contact) when it is in the book,
        else the one chosen now (`WinlinkGatewayScreen`), added to the book
        and remembered as the favourite if asked. None if cancelled."""
        from ..winlink import gateways

        favourite = self.config.winlink.route.strip()
        entry = self.addressbook.find(favourite) if favourite else None
        if entry is not None:
            return entry
        note, skip = self._all_inboxes_ask()
        has_list = bool(gateways.ACCESS_KEY) or gateways.load_cached(self._gateway_cache()) is not None
        answer = self._setup_answer(await self.push_screen_wait(WinlinkGatewayScreen(
            [e.target for e in self.addressbook.entries if not e.is_internet], favourite,
            gateway_list=has_list, all_note=note, skip=skip)), "winlink")
        if not isinstance(answer, GatewayChoice):
            return None
        entry = self.addressbook.find(answer.target)
        if entry is None:
            channel = answer.channel
            details = {} if channel is None else {
                "frequency": channel.frequency,
                "note": f"Winlink RMS, {channel.modes}" + (f", {channel.grid}" if channel.grid else ""),
            }
            entry = self.addressbook.upsert(answer.target, **details)
            from .addressbook_pane import AddressBookPane

            for pane in self.query(AddressBookPane):
                pane.refresh_from(self.addressbook)
        if answer.remember and self.config.winlink.route != entry.target:
            self.config.winlink.route = entry.target
            self._save_config()
            self.query_one(SettingsPane).render_settings(self.config)
        return entry

    async def _mail_route(self, route: str):
        """The Address Book entry `route` names, asking for one (and saving
        the answer) on first use or when the entry is gone; None if the
        operator cancelled."""
        entry = self.addressbook.find(route.strip()) if route.strip() else None
        if entry is not None:
            return entry
        # First use, or the entry was forgotten: ask for the one thing
        # Send/Receive cannot run without, then carry on.
        note, skip = self._all_inboxes_ask()
        targets = [e.target for e in self.addressbook.entries]
        chosen = self._setup_answer(await self.push_screen_wait(
            HomeBbsSetupScreen(targets, missing=route.strip(), all_note=note, skip=skip)
        ), "connect" if not targets else "bbs")
        entry = self.addressbook.find(chosen) if chosen else None
        if entry is None:
            return None
        self.config.home_bbs.route = entry.target
        self._save_config()
        self.query_one(SettingsPane).render_settings(self.config)
        return entry

    async def _ask_login(self, current: str, default_name: str, title: str, detail: str,
                         *, secret: bool = True,
                         username: bool = False) -> tuple[str, str] | None:
        """The saved login `current` names, as (name, password); if there
        is none or it cannot be read, ask for it before dialing and save it
        (`LoginAskScreen`; with `username`, its username too). None if the
        operator cancelled."""
        from ..config import set_credential

        text = find_credential(self.config, current) if current else ""
        if text:
            return current, text
        # A name that is no saved login may be a password typed in its place:
        # never show it, save under the fixed name instead.
        name = current if current and credential_store(self.config, current) else default_name
        note, skip = self._all_inboxes_ask()
        answer = self._setup_answer(await self.push_screen_wait(LoginAskScreen(
            title, detail, name, secret=secret, all_note=note, skip=skip,
            username=credential_username(self.config, name) if username else None,
            where=login_where() if username else "")), "")
        if not answer:
            return None
        text = answer.text if isinstance(answer, Credential) else answer
        where = set_credential(self.config, name, text, username=(
            answer.username if isinstance(answer, Credential) else None))
        self._save_config()
        self.notify(
            f"Saved the login \"{name}\" in "
            + ("the system keyring." if where == "keyring" else "config.toml (no system keyring here)."),
        )
        return name, text

    def _connected_to(self, peer: AX25Address) -> bool:
        """Whether a Terminal session is already connected to `peer` over
        AX.25. Only an AX.25 link has an address to compare: a session-tier
        link's peer is a host or a modem's name, a string (operator,
        2026-10-03: G on Mail with WS1EC's SSH login open crashed here)."""
        return any(
            s.link is not None and s.link.connected
            and isinstance(s.link.peer, AX25Address)
            and (s.link.peer.callsign, s.link.peer.ssid) == (peer.callsign, peer.ssid)
            for s in self._sessions.values()
        )

    async def _dial_for_mail(self, entry, build, doing: str, label: str = "Send/Receive"):
        """Dial `entry` for a Home BBS or Winlink run. `build(link, key)`
        makes the runner the moment the link is up, before anything awaits,
        so the far end's first bytes are not missed; it starts once the
        chain has reached the target. Returns (runner, key), or None having
        said why. `doing` ("get files") goes in the connect toast and
        `label` ("Get files") leads a failure's, so each says what was
        asked for (operator, 2026-10-04: G on Files said "to get mail").
        """
        first = [h.strip() for h in entry.hops.split(",") if h.strip()] or [entry.target]
        peer = parse_path(first[0]).destination
        if self._connected_to(peer):
            self.notify(
                f"Already connected to {peer}. Disconnect first, then press G.",
                severity="warning",
            )
            return None
        state: dict = {"runner": None, "key": "", "reached": False}

        def on_link(link, key: str) -> None:
            state["key"] = key
            state["runner"] = build(link, key)

        def on_reached(reached: bool) -> None:
            state["reached"] = reached

        # The operator stays on the Mail tab: one toast says a connect is
        # under way (and that transmit was enabled, if it was), and the
        # status bar follows it. The whole session is in the Terminal tab
        # (F5) for anyone who wants to watch. A failure is one toast too: the
        # connect hands its reason here (`report`) rather than raising its
        # own beside this one (operator, 2026-10-02: two toasts per event).
        reasons: list[str] = []
        announce = f"Connecting to {entry.target} to {doing}..."
        if entry.is_internet:
            # No transmit gate on the Internet, so nothing to fold in.
            self.notify(announce)
            announce = ""
        self._set_activity(f"Connecting to {entry.target}")
        worker = self.action_connect(
            prefill=entry, on_link=on_link, on_reached=on_reached, focus_session=False,
            announce=announce, report=reasons.append,
        )
        await worker.wait()
        runner = state["runner"]
        why = reasons[-1].rstrip(".") if reasons else f"did not reach {entry.target}"
        if runner is None:
            # No reason means the operator cancelled (the reminder, Ctrl+D):
            # nothing to tell them.
            if reasons:
                self.notify(f"{label}: {why}.",
                            severity="error")
            return None
        if not state["reached"]:
            runner.close()
            self.notify(f"{label}: {why}.",
                        severity="error")
            return None
        return runner, state["key"]

    async def _bbs_prepare(self):
        """Everything the Home BBS run needs before dialing, asking for
        what is missing: (entry, options), or None if cancelled."""
        from ..mail.collect import CollectOptions

        home = self.config.home_bbs
        entry = await self._mail_route(home.route)
        if entry is None:
            return None
        login_text = ""
        if home.login_prompt:
            # Settings says the BBS asks for a login: have it before dialing.
            login = await self._ask_login(
                home.credential, "Home BBS", "Home BBS login", "", username=True)
            if login is None:
                return None
            if home.credential != login[0]:
                home.credential = login[0]
                self._save_config()
                self.query_one(SettingsPane).render_settings(self.config)
            # The username line, then the password (a saved login's shape).
            login_text = saved_login_text(self.config, login[0]) or login[1]
        options = CollectOptions(
            bbs_call=home.call,
            software=home.software,
            ready_text=home.ready_text,
            login_prompt=home.login_prompt,
            login_text=login_text,
        )
        return entry, options

    async def _bbs_run(self, entry, options) -> None:
        """The Home BBS: `kissterm/mail/collect.py` drives it."""
        from ..mail.collect import BbsCollector

        def build(link, key: str):
            return BbsCollector(
                link,
                self.mail_store,
                options,
                note=lambda text: self._mail_note(key, text),
                sent=lambda text: self._mail_sent(key, text),
                gate_open=lambda: self.gate.enabled,
                progress=self._set_activity,
                subscriptions=self.bulletin_subscriptions,
                choose=self._choose_categories,
                pick_files=self._pick_bbs_files,
                files_dir=self._downloads_dir() if options.files else None,
                transferring=lambda on: self._transferring(key, on),
            )

        if options.files:
            doing, label = "get files", "Get files"
        elif options.bulletins:
            doing, label = "get bulletins", "Get bulletins"
        else:
            doing, label = "send and receive mail", "Send/Receive"
        dialed = await self._dial_for_mail(entry, build, doing, label)
        if dialed is None:
            return
        collector, key = dialed
        result = await collector.run()
        self._bbs_report(result, bulletins=options.bulletins, files=options.files)
        await self._disconnect_session(key)

    def _transferring(self, key: str, on: bool) -> None:
        """A files run's download starting or ending on session `key`: the
        Terminal holds the YAPP bytes meanwhile, as for a typed request."""
        if on:
            self._transfer_active.add(key)
        else:
            self._transfer_active.discard(key)

    def _bbs_report(self, result, bulletins: bool = False, files: bool = False) -> None:
        """The outcome toast of a Home BBS run, over radio or the Internet."""
        sent = f"{len(result.sent)} sent, " if result.sent else ""
        if files:
            got = len(result.downloaded)
            if result.stopped:
                self.notify(f"Getting files stopped: {result.stopped}. {got} downloaded.",
                            severity="warning")
            elif got:
                self.notify(f"{got} file(s) downloaded into Files > Downloads.")
            elif not result.listed:
                self.notify("The Home BBS lists no files.")
            self._reload_mail_tabs()
            return
        if bulletins:
            if result.stopped:
                self.notify(f"Getting bulletins stopped: {result.stopped}. "
                            f"{len(result.filed)} received.", severity="warning")
            elif result.filed:
                self.notify(f"{len(result.filed)} new bulletin(s) from the Home BBS.")
            else:
                self.notify("No new bulletins on the Home BBS.")
            self._reload_mail_tabs()
            return
        if "unknown client type" in result.stopped.lower():
            # The CMS's own words (operator's first session, 2026-09-28):
            # its production servers turn away a client program they do not
            # know, by the name in the SID (ROADMAP, Blockers). The published
            # B2F specification names no registry; how a program becomes
            # known is still to be learned. Not the password, network or radio.
            self.notify(
                "Winlink refused kissterm itself, not your login: its production servers "
                "accept only client programs they know, and kissterm is not one of them yet. "
                "Nothing was sent. Settings > Mail > Internet server can use Winlink's test "
                "server instead.",
                severity="warning", timeout=15,
            )
        elif result.stopped:
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
            self.notify("No new mail on the Home BBS.")
        self._reload_mail_tabs()

    async def _winlink_prepare(self):
        """Everything the Winlink run needs before dialing, asking for what
        is missing: (entry, options), or None if cancelled."""
        from ..mail.winlink_collect import WinlinkOptions

        winlink = self.config.winlink
        entry = await self._winlink_gateway() if await self._winlink_account() else None
        if entry is None:
            return None
        login = await self._winlink_login()
        if login is None:
            return None
        account, password = login
        return entry, WinlinkOptions(
            account,
            password=password,
            target=str(parse_path(entry.target).destination),
            locator=winlink.locator or self.config.aprs.grid_square,
        )

    async def _winlink_account(self) -> str:
        """The Winlink account, asking for the callsign it defaults to when
        neither is set; "" if the operator cancelled."""
        from ..config import winlink_account

        if not winlink_account(self.config):
            await self.action_set_callsign().wait()
        return winlink_account(self.config)

    async def _winlink_login(self) -> tuple[str, str] | None:
        """(account, password), asking for the password if no saved login
        holds it; None if cancelled."""
        winlink = self.config.winlink
        account = await self._winlink_account()
        if not account:
            return None
        # Have the password before dialing, so a missing one never costs a
        # connect. UNVERIFIED: that every gateway challenges (Winlink
        # accounts have passwords; wl2k-go answers ;PQ whenever it comes).
        login = await self._ask_login(
            winlink.credential, "Winlink", f"Winlink password for {account}", "")
        if login is None:
            return None
        if winlink.credential != login[0]:
            winlink.credential = login[0]
            self._save_config()
            self.query_one(SettingsPane).render_settings(self.config)
        return account, login[1]

    async def _winlink_run(self, entry, options) -> None:
        """Winlink over the route Settings > Mail names:
        `kissterm/mail/winlink_collect.py` drives the B2F exchange.

        While it runs, the session's Terminal tab shows the protocol lines
        as text, not the link's raw bytes: a message travels compressed,
        and its binary would only fill the pane with noise (the same
        suppression a file transfer uses, `_transfer_active`). What arrived
        before the exchange started (the node's banner, the hop chain) was
        shown as usual."""
        from ..mail.winlink_collect import WinlinkCollector

        def build(link, key: str):
            return WinlinkCollector(
                link,
                self.mail_store,
                options,
                note=lambda text: self._mail_note(key, text),
                sent=lambda text: self._mail_sent(key, text),
                received=lambda text: self._winlink_received(key, text),
                gate_open=lambda: self.gate.enabled,
                progress=self._set_activity,
            )

        dialed = await self._dial_for_mail(entry, build, "send and receive Winlink mail")
        if dialed is None:
            return
        collector, key = dialed
        self._transfer_active.add(key)
        try:
            result = await collector.run()
        finally:
            self._transfer_active.discard(key)
        self._winlink_report(result)
        await self._disconnect_session(key)
        await self._winlink_password_refused(result)

    async def _winlink_password_refused(self, result) -> None:
        """The gateway refused the password: ask for it again here, rather
        than say where to set it (operator, 2026-09-27: go there, don't
        point). Saved for the next run; nothing is dialed now, so a retry
        costs airtime only when the operator presses G again."""
        from ..config import set_credential, winlink_account

        if "password" not in (result.stopped or "").lower():
            return
        text = await self.push_screen_wait(LoginAskScreen(
            "Winlink password refused",
            f"The gateway said: {result.stopped}. Type the password for "
            f"{winlink_account(self.config)} again.",
            "Winlink", go_label="Save"))
        if not text or text == SETUP_SKIP:
            return
        where = set_credential(self.config, "Winlink", text)
        self.config.winlink.credential = "Winlink"
        self._save_config()
        self.query_one(SettingsPane).render_settings(self.config)
        self.notify("Saved in " + ("the system keyring" if where == "keyring" else "config.toml")
                    + ". Send/Receive again to use it.")

    def _winlink_report(self, result) -> None:
        """The outcome toast of a Winlink run, over radio or the Internet."""
        sent = f"{len(result.sent)} sent, " if result.sent else ""
        if "unknown client type" in result.stopped.lower():
            # The CMS's own words (operator's first session, 2026-09-28):
            # its production servers turn away a client program they do not
            # know, by the name in the SID (ROADMAP, Blockers). The published
            # B2F specification names no registry; how a program becomes
            # known is still to be learned. Not the password, network or radio.
            self.notify(
                "Winlink refused kissterm itself, not your login: its production servers "
                "accept only client programs they know, and kissterm is not one of them yet. "
                "Nothing was sent. Settings > Mail > Internet server can use Winlink's test "
                "server instead.",
                severity="warning", timeout=15,
            )
        elif result.stopped:
            self.notify(
                f"Winlink stopped: {result.stopped}. {sent}{len(result.filed)} received.",
                severity="warning",
            )
        elif result.filed:
            self.notify(f"{sent}{len(result.filed)} new Winlink message(s).")
        elif result.sent:
            self.notify(f"{len(result.sent)} sent. No new Winlink mail.")
        else:
            self.notify("No new Winlink mail.")
        self._reload_mail_tabs()

    @work(exclusive=False)
    async def action_get_mail_internet(self) -> None:
        """Send/Receive by Internet (Mail tab, I), parallel to G
        (operator, 2026-09-26): the same folders decide what runs, the Home
        BBS through its Telnet or SSH connection
        (`home_bbs.internet`, e.g. WS1EC's SSH login into its node) and
        Winlink through the CMS by Telnet. Anything missing is asked for
        before the first connection.

        The transmit gate is not involved: nothing here can key a radio,
        and arming it would open RF for everything else too. Each run is
        written to a transcript (Session > Transcripts) as protocol lines,
        so a first session can become a test fixture."""
        if self._collecting:
            self.notify("Already sending and receiving.", severity="warning")
            return
        self._collecting = True
        try:
            kind = self.send_receive_kind(self._mail_folder(), internet=True)
            runs = await self._prepare_runs(kind, "I", (
                ("Home BBS", self._bbs_internet_prepare, self._bbs_internet_run),
                ("Winlink", self._winlink_login, self._winlink_cms_run),
            ))
            for run, args in runs or ():
                await run(*args)
        finally:
            self._collecting = False
            self._set_activity("")

    @work(exclusive=False)
    async def action_get_bulletins(self, internet: bool = False) -> None:
        """Get bulletins (Bulletins tab, G; I over the Internet). ROADMAP P2.

        The Home BBS run with `CollectOptions.bulletins`: the same dial,
        reminder, gate and logins as Send/Receive, then the categories
        chosen (`mail/bulletins.py`), offered on the first run and when a
        check finds a new one (`_choose_categories`)."""
        if self._collecting:
            self.notify("Already sending and receiving.", severity="warning")
            return
        self._collecting = True
        try:
            prepared = await (self._bbs_internet_prepare() if internet
                              else self._bbs_prepare())
            if prepared is None:
                return
            entry, options = prepared
            home = self.config.home_bbs
            options.bulletins = True
            options.check_days = home.bulletin_check_days
            options.first_days = home.bulletin_days
            run = self._bbs_internet_run if internet else self._bbs_run
            await run(entry, options)
        except _SkipService:
            pass
        finally:
            self._collecting = False
            self._set_activity("")

    def action_get_bulletins_internet(self) -> None:
        self.action_get_bulletins(internet=True)

    @work(exclusive=False)
    async def action_get_files(self) -> None:
        """Get files from the Home BBS (Files tab, G). ROADMAP P2, Files.

        The Home BBS run with `CollectOptions.files`, by radio only: the
        same dial, reminder, gate and login as Send/Receive, then `FILES`,
        the operator's pick (`_pick_bbs_files`) and a YAPP download of each.
        No Internet twin: YAPP does not survive a server's telnet (SSH
        refuses transfers, `refuse_line`)."""
        if self._collecting:
            self.notify("Already sending and receiving.", severity="warning")
            return
        self._collecting = True
        try:
            prepared = await self._bbs_prepare()
            if prepared is None:
                return
            entry, options = prepared
            options.files = True
            await self._bbs_run(entry, options)
        except _SkipService:
            pass
        finally:
            self._collecting = False
            self._set_activity("")

    async def _pick_bbs_files(self, files):
        """The collector's question (`collect.PickFiles`), asked mid-run."""
        from .bbs_files_screen import BbsFilesScreen

        folder = self._downloads_dir()
        have = {p.name: p.stat().st_size for p in folder.iterdir() if p.is_file()}
        return await self.push_screen_wait(BbsFilesScreen(
            self._bulletin_bbs() or "the BBS", files, have=have))

    def _bulletin_bbs(self) -> str:
        """The Home BBS's callsign as its choices are kept, or ""."""
        home = self.config.home_bbs
        if home.call:
            return home.call
        route = home.route or home.internet
        return str(parse_path(route).destination.callsign) if route else ""

    async def _choose_categories(self, offer: list[str], counts: dict[str, int],
                                 first: bool):
        """The collector's question (`collect.Choose`), asked mid-run."""
        from .bulletin_screen import BulletinCategoriesScreen

        bbs = self._bulletin_bbs() or "the BBS"
        return await self.push_screen_wait(BulletinCategoriesScreen(
            bbs, {c: counts.get(c, 0) for c in offer}, new_only=not first))

    @work
    async def action_bulletin_categories(self) -> None:
        """S on the Bulletins tab: change which categories are collected,
        offline, from those the BBS listed last."""
        from .bulletin_screen import BulletinCategoriesScreen

        bbs = self._bulletin_bbs()
        subs = self.bulletin_subscriptions.for_bbs(bbs) if bbs else None
        if subs is None or not subs.seen:
            self.notify("No categories yet: G asks the BBS for its list on the first "
                        "collection.")
            return
        answer = await self.push_screen_wait(BulletinCategoriesScreen(
            bbs, subs.seen, ticked=subs.chosen, all_=subs.all))
        if answer is None:
            return
        picked, all_ = answer
        subs.choose(list(subs.seen), picked, all_=all_)
        self.bulletin_subscriptions.save()
        self.notify("Collecting " + ("every category." if subs.all
                                     else (", ".join(subs.chosen) or "no categories") + "."))

    async def _internet_run(self, transport, peer: str, what: str, build,
                            label: str = "Send/Receive"):
        """Connect a session `transport` and run the collector
        `build(link, note, sent, received)` makes over it, with a
        transcript. Returns its result, or None having said why, led by
        `label` (`_dial_for_mail`)."""
        self.notify(f"Connecting to {what} over the Internet...")
        self._set_activity(f"Connecting to {what}")
        link = transcript = None
        try:
            await transport.open()
            try:
                session = await self._session_connect(transport)
            except TransportError as exc:
                self.notify(f"{label} by Internet: {exc}", severity="error")
                return None
            link = _SessionLinkAdapter(session)
            mycall = str(self.config.mycall or "").upper()
            transcript = SessionLog(self._transcript_directory(), mycall, peer)
            if not transcript.open():
                transcript = None
            log = transcript

            def note(text: str) -> None:
                if log is not None:
                    log.note(f"*** Mail: {text}")

            collector = build(
                link, note,
                lambda text: log.sent(self._masked(text)) if log is not None else None,
                lambda text: log.received(text) if log is not None else None,
            )
            return await collector.run()
        finally:
            if link is not None:
                with contextlib.suppress(Exception):
                    await link.disconnect()
            with contextlib.suppress(Exception):
                await transport.close()
            if transcript is not None:
                transcript.close()
            self._set_activity("")

    async def _winlink_cms_run(self, account: str, password: str) -> None:
        """Winlink through the CMS by Telnet (`winlink_collect.CMS_*`,
        from wl2k-go): its login, then the same exchange as over radio."""
        from ..mail.winlink_collect import (
            CMS_PORT, CMS_TARGET, WinlinkCollector, WinlinkOptions, cms_host,
        )
        from ..transport import build_transport

        options = WinlinkOptions(
            account, password=password, target=CMS_TARGET,
            locator=self.config.winlink.locator or self.config.aprs.grid_square,
            telnet_login=True,
        )

        def build(link, note, sent, received):
            return WinlinkCollector(link, self.mail_store, options, note=note, sent=sent,
                                    received=received, progress=self._set_activity,
                                    early_lines_shown=False)

        server = self.config.winlink.server
        transport = build_transport({"kind": "telnet", "host": cms_host(server), "port": CMS_PORT})
        what = "Winlink's test server" if server == "test" else "the Winlink CMS"
        result = await self._internet_run(transport, CMS_TARGET, what, build)
        if result is not None:
            self._winlink_report(result)
            await self._winlink_password_refused(result)

    def _internet_contacts(self) -> list:
        """The Address Book's Telnet and SSH contacts: what I reaches the
        Home BBS through (ROADMAP P2, every contact in the Address Book)."""
        return [e for e in self.addressbook.entries if e.is_internet]

    async def _bbs_internet_prepare(self):
        """Everything the Home BBS needs over the Internet, asking for what
        is missing: (connection, options), or None if cancelled."""
        from ..mail.collect import CollectOptions

        home = self.config.home_bbs
        contacts = self._internet_contacts()
        wanted = home.internet.strip().upper()
        entry = next((e for e in contacts if e.target.upper() == wanted), None)
        # A name that is no saved login may be a password typed in its
        # place: never shown, replaced by a login made here.
        name = (home.internet_credential
                if credential_store(self.config, home.internet_credential) else "")
        password = find_credential(self.config, name) if name else ""
        if not password and entry is not None and entry.credential:
            # The contact's own Node login is the node's sign-in already;
            # asking for it again here was a second copy (operator,
            # 2026-10-02: "It includes the node credentials, yet I still
            # have to enter the credentials").
            node_password = find_credential(self.config, entry.credential)
            if node_password:
                name, password = entry.credential, node_password
        user = (credential_username(self.config, name) or home.internet_user
                or str(self.config.mycall or "").split("-")[0].upper())
        if entry is None or not password:
            # One question for all of it: the contact, the username and the
            # password, saved as one login (operator, 2026-09-28).
            note, skip = self._all_inboxes_ask()
            answer = self._setup_answer(await self.push_screen_wait(InternetLoginScreen(
                [e.target for e in contacts], entry.target if entry else "",
                missing=home.internet.strip() if entry is None else "",
                username=user, saved=bool(password), where=login_where(),
                all_note=note, skip=skip)), "")
            if not isinstance(answer, InternetLogin):
                return None
            entry = self.addressbook.find(answer.target)
            if entry is None or not entry.is_internet:
                return None
            name = name or f"{entry.target} login"
            password = answer.password or password
            user = answer.username
            where = set_credential(self.config, name, password, username=user)
            home.internet, home.internet_credential, home.internet_user = entry.target, name, ""
            self._save_config()
            self.query_one(SettingsPane).render_settings(self.config)
            self.notify(
                f"Saved the login \"{name}\" for {entry.target}, its password in "
                + ("the system keyring." if where == "keyring"
                   else "config.toml (no system keyring here)."),
            )
        return entry, CollectOptions(
            bbs_call=home.call,
            software=home.software,
            ready_text=home.ready_text,
            telnet_user=user,
            telnet_password=password,
            after_login=home.internet_command.strip(),
        )

    async def _bbs_internet_run(self, entry, options) -> None:
        """The Home BBS over its Telnet or SSH contact, built the one way
        every connection is (`build_transport`)."""
        from ..mail.collect import BbsCollector
        from ..transport import build_transport

        label = "Get bulletins" if options.bulletins else "Send/Receive"
        try:
            transport = build_transport(entry.transport_config(
                lambda name: find_credential(self.config, name),
                lambda name: credential_username(self.config, name)))
        except (TransportError, TypeError, ValueError) as exc:
            self.notify(f"{label} by Internet: {entry.target}: {exc}", severity="error")
            return

        def build(link, note, sent, received):
            return BbsCollector(link, self.mail_store, options, note=note, sent=sent,
                                progress=self._set_activity,
                                subscriptions=self.bulletin_subscriptions,
                                choose=self._choose_categories)

        result = await self._internet_run(transport, entry.target, entry.target, build, label)
        if result is not None:
            self._bbs_report(result, bulletins=options.bulletins)

    def _winlink_received(self, key: str, text: str) -> None:
        """A line from the Winlink gateway, shown and kept in the
        transcript as received text (the raw bytes are suppressed)."""
        data = (text + "\r").encode("latin-1", errors="replace")
        self._to_terminal(key, "write_incoming", data)
        session = self._sessions.get(key)
        if session is not None and session.transcript is not None:
            session.transcript.received_stream(data, sanitize)

    def _mail_note(self, key: str, text: str) -> None:
        """A Send/Receive progress sentence, for the transcript only."""
        self._record(key, f"Mail: {text}")

    def _set_activity(self, phase: str) -> None:
        """The status-bar field for a job the operator started, in green
        ("Sending 1 of 2", "YAPP send"); "" removes it.

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

    def _masked(self, text: str) -> str:
        """`text`, or `********` when it is a saved login's password
        (`Connector.masked`)."""
        return self.core.connector.masked(text)

    def _mail_sent(self, key: str, text: str) -> None:
        """Echo a line Send/Receive sent, as a typed line is echoed."""
        self._to_terminal(key, "write_note", self._masked(text) + "\n")
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

    def _own_position(self) -> tuple[float, float] | None:
        """The operator's APRS position, or None while it is unset (0, 0)."""
        aprs = self.config.aprs
        if aprs.latitude or aprs.longitude:
            return aprs.latitude, aprs.longitude
        return None

    def _gateway_cache(self):
        from ..config import state_path
        from ..winlink import gateways

        return gateways.cache_path(state_path())

    @work
    async def action_rms_gateways(self) -> None:
        """F10 > Session > RMS gateways: choose a Winlink gateway from the
        list (`ui/gateways_screen.py`). The one chosen becomes an Address
        Book contact and the Winlink Dial; nothing is dialed or sent."""
        from .addressbook_pane import AddressBookPane
        from .gateways_screen import RmsGatewaysScreen

        channel = await self.push_screen_wait(
            RmsGatewaysScreen(self._gateway_cache(), self._own_position()))
        if channel is None:
            return
        # An entry already there keeps its hops, login and note: upsert
        # would replace them all.
        if self.addressbook.find(channel.callsign) is None:
            note = f"Winlink RMS, {channel.modes}"
            if channel.grid:
                note += f", {channel.grid}"
            self.addressbook.upsert(channel.callsign, frequency=channel.frequency, note=note)
            for pane in self.query(AddressBookPane):
                pane.refresh_from(self.addressbook)
        self.config.winlink.route = channel.callsign
        self._save_config()
        self.query_one(SettingsPane).render_settings(self.config)
        self.notify(f"{channel.callsign} ({channel.frequency}) is in the Address Book "
                    "and is now the Winlink Dial.")

    @work
    async def action_show_transcripts(self) -> None:
        """Find, read and export a past session's transcript.

        The screen reads from the same directory `_start_transcript` writes
        to (`_transcript_directory`), so this always shows what a live
        session would have just written -- including one in progress right
        now, since `SessionLog` is line-buffered.
        """
        await self.push_screen_wait(TranscriptsScreen(self._transcript_directory()))

    def _downloads_dir(self) -> Path:
        """Files > Downloads in the message store, where a YAPP or AutoBIN
        download is saved, so the Files tab (F4) shows it. It went to the
        state folder's `downloads` until 2026-10-03, out of sight."""
        from ..mail.store import FILES

        folder = self.mail_store.root / FILES / "Downloads"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def refuse_line(self, text: str) -> bool:
        """Whether `TerminalPane.send_line` should hold `text` back, having
        said why. Only `YAPP <name>` over a link that cannot carry a file
        (`_SessionLinkAdapter.carries_binary`): sent, it would leave the
        BBS waiting on a transfer that cannot finish, reading the next lines
        typed as YAPP data."""
        link = self.link
        if _YAPP_REQUEST.match(text) and not getattr(link, "carries_binary", True):
            self.notify(
                "File transfers are not supported over SSH: the server's telnet holds "
                "YAPP's replies. Connect by radio to download a file.",
                severity="warning",
            )
            return True
        return False

    def _watch_for_download(self, session_key: str, data: bytes) -> bool:
        """Start a YAPP download by itself when the file the operator asked
        for arrives: True if `data` began one.

        Only after the operator sent `YAPP <name>` (`log_sent`), and only
        for `DOWNLOAD_WAIT_SECONDS`: a request they made, never a sender
        that turns up unasked (that is the unattended mailbox, ROADMAP P9).
        BPQ sends its `ENQ 1` alone and then waits for the answer
        (`yapp.py`), so nothing can arrive before the receiver subscribes.
        Until 2026-10-03 a download had to be armed first from F10 > File
        transfer; the operator: "this is the only application that
        requires me to start a file download session"."""
        session = self._sessions.get(session_key)
        if session is None or not session.download_until:
            return False
        if time.monotonic() > session.download_until:
            session.download_until = 0.0
            return False
        if not starts_download(data):
            return False
        session.download_until = 0.0
        self._transfer_active.add(session_key)
        self._receive_requested(session_key, bytes(data))
        return True

    @work
    async def _receive_requested(self, key: str, initial: bytes) -> None:
        """The YAPP download `_watch_for_download` saw start, into Files >
        Downloads, its progress in the status bar."""
        session = self._sessions.get(key)
        if session is None or session.link is None:
            self._transfer_active.discard(key)
            return

        def progress(name: str, done: int, size: int) -> None:
            self._set_activity(f"YAPP {name} {done}/{size}")

        await self._run_transfer(key, "YAPP", "download", receive_file(
            session.link, self._downloads_dir(), initial=initial, progress=progress,
        ))

    async def _run_transfer(self, key: str, protocol: str, mode: str, transfer) -> None:
        """Await one transfer on session `key` (already in
        `_transfer_active`, so the Terminal does not print its bytes), then
        say how it went: a note in the transcript and one toast."""
        self._note(key, f"{protocol} {mode} starting")
        self._set_activity(f"{protocol} {mode}")
        try:
            result = await transfer
        except (OSError, ValueError, YappError, AutoBinError) as exc:
            self._note(key, f"{protocol} {mode} failed: {exc}")
            self.notify(f"{protocol} {mode} failed: {exc}", severity="warning")
        else:
            self._note(key, f"{protocol} {mode} complete: {result.path.name} ({result.size} bytes)")
            if mode == "upload":
                self.notify(f"{protocol} upload complete: {result.path.name}")
            else:
                self.notify(f"{protocol} download complete: {result.path.name}, in Files > Downloads (F4).")
                self._reload_mail_tabs()
        finally:
            self._transfer_active.discard(key)
            self._set_activity("")

    def can_send_file(self) -> bool:
        """Whether S on the Files tab can send: a connected session in the
        Terminal and no transfer already running on it."""
        key = self._active_key()
        session = self._sessions.get(key)
        return (session is not None and session.link is not None and session.link.connected
                and getattr(session.link, "carries_binary", True)
                and key not in self._transfer_active)

    @work
    async def action_file_transfer(self, path: Path | None = None) -> None:
        """Start one explicit YAPP/AutoBIN upload or arm an explicit download.
        `path` (S on the Files tab) fills in an upload of that file; the
        operator still chooses the protocol and presses Start."""
        key = self._active_key()
        session = self._sessions.get(key)
        if session is None or session.link is None or not session.link.connected:
            self.notify("Connect before starting a file transfer.", severity="warning")
            return
        if not getattr(session.link, "carries_binary", True):
            self.notify("File transfers are not supported over SSH: the server's telnet "
                        "holds YAPP's replies. Connect by radio to send a file.",
                        severity="warning")
            return
        request = await self.push_screen_wait(FileTransferScreen(path))
        if request is None:
            return
        if self.gate is not None and not self.gate.enabled:
            self._arm_for(f"{request.protocol.upper()} {request.mode}")
        self._transfer_active.add(key)
        if request.protocol == "yapp":
            sender, receiver = send_file, receive_file
        else:
            sender, receiver = send_autobin, receive_autobin
        if request.mode == "upload":
            transfer = sender(session.link, request.path)
        else:
            transfer = receiver(session.link, self._downloads_dir())
        await self._run_transfer(key, request.protocol.upper(), request.mode, transfer)

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
        """`Connector.disconnect`: DISC a live link, or cancel its connect."""
        await self.core.connector.disconnect(session_key)

    def session_is_live(self, session_key: str) -> bool:
        """Connected or still connecting: closing it would disconnect first."""
        return self.core.connector.session_is_live(session_key)

    def _reconnect_request(self) -> ConnectRequest | None:
        """What Ctrl+R would dial for the Terminal tab on screen
        (`Connector.reconnect_request`)."""
        return self.core.connector.reconnect_request(self._active_key())

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
        key = self._active_key()
        request = self._reconnect_request()
        contact = self.addressbook.find(request.target) if request is not None else None
        internet = contact is not None and contact.is_internet
        if self.station is None and not internet:
            # Session tier: there is one far end, and connecting to it again
            # is what Ctrl+N already does there.
            self.action_connect()
            return
        if key and self.session_is_live(key):
            self.notify(f"Already connected to {key}.", severity="information")
            return
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
        self.core.sessions.close(session_key)
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
        transport = self.core.transport
        if transport is None:
            # Launching without a transport is intentional: Settings is where
            # an operator adds or repairs one, and refusing to mount the TUI
            # turns a missing entry into a command-line dead end.
            return "NO TRANSPORT - F9 Settings"
        state = transport.state
        detail = _without_port(transport.info.detail)
        if state is TransportState.OPEN:
            return detail
        if state is TransportState.OPENING:
            return f"{detail} RECONNECTING"
        if state is TransportState.ERROR:
            return f"{detail} DOWN"
        return f"{detail} {state.value}"

    def _refresh_status(self) -> None:
        # No app name or version: the title bar has both (operator,
        # 2026-10-02), and the room goes to the fields that remain.
        parts = [self._transport_status()]
        if not self.gate.enabled:
            # First after the transport, and always present while it is true.
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
            peer = str(self.link.peer)
            node = self.current_node or peer
            where = (_short_peer(peer) if node == peer
                     else f"{node.upper()} via {_short_peer(peer)}")
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
        # No heard count (operator, 2026-10-02): the Heard tab has the list,
        # and the room goes to the job under way.
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
        # A click on a tab's label focuses the tab row; give the pane's own
        # widget focus as the tab keys do (`_focus_tab_target`).
        self.call_after_refresh(self._focus_tab_target, event.pane.id)


class _SkipService(Exception):
    """The operator pressed Skip on an All Inboxes setup question."""
