"""The Flet client's frame: the top bar with the transmit switch, the
destinations, the connection's state, notices and the station's
questions (ROADMAP P7a M8).

**Phone first.** Under `WIDE` logical pixels the destinations are a
bottom navigation bar, the thumb's reach; wider (a tablet, a desktop
window) they are a rail at the side. Destinations themselves never
swipe: a horizontal swipe belongs to the rows and sub-tabs inside them
(DESIGN.md, "Phone and browser").

**The transmit switch is always in the top bar**, red while on. Turning
it on asks first and buzzes the phone; turning it off never asks
(stopping is always safe). It sends the protocol's `transmit` command:
the station reports it on every screen.

**Disconnect and Reconnect are in Terminal's toolbar** (`sessions.py`), not
the top bar: Disconnect while the session shown is connected, Reconnect in
its place once it has dropped (Ctrl+R in the terminal). The row that used
to repeat the session's name above the terminal is gone, and its height is
the terminal's. Every place's actions are one toolbar row (`toolbar.py`).

**A connect runs in the background** (`start_connect`): Terminal comes to
the front at once and the session shows its hourglass there, never a
screen waiting on the station's answer.

**Mail, Bulletins and Files are one view** (`MailView`) with three
sections: on the phone a switch at the top of the Mail page, on a wide
screen three places in the rail, where there is room (operator,
2026-10-06: "Desktop will have room for the additional section
buttons"). The bottom bar stays at five.

**Titles name the place, not the station** ("APRS messages", not
"KC1JMH Messages", and "BBS Mail" for Mail): the callsign is in More,
and the room is the title's (operator, 2026-10-06).

**Every station question is a sheet** (`questions.py`), the first answer
anywhere wins (`question_closed` takes it down here).

**The terminal's look belongs to the device**, not the station: a phone
in the sun wants a light panel while the station's own screen stays
dark. It is kept in the browser's (or desktop's) preferences, never sent
to the station, and a value this version does not know is the default.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

import flet as ft

from ..connection import CommandFailed, Connection
from ..state import StationState
from . import sheets
from .mail import SECTIONS, MailView
from .messages import MessagesView
from .more import MoreView
from .questions import QuestionSheets
from .sessions import SessionsView
from .stations import StationsView
from . import theme
from .text import Look

log = logging.getLogger(__name__)

#: Preference keys for the terminal's look (`Look`).
LOOK_KEYS = ("kissterm.terminal.background", "kissterm.terminal.text")

#: Width (logical pixels) from which destinations move to a side rail.
WIDE = 720

#: The top bar's title on each destination, where the bar's label is
#: too short to say it (Mail's comes from its section: `MailView.title`).
TITLES = {"Messages": "APRS messages", "Mail": "BBS Mail"}

#: The places, in the bar's order (operator, 2026-10-06: "Mail, Messages,
#: Terminal (renamed from Sessions), Stations"; More stays last). The app
#: opens on the first. Code names a place by these, never by a number.
MAIL, MESSAGES, TERMINAL, STATIONS, MORE = range(5)

DESTINATIONS = (
    ("Mail", ft.Icons.MAIL_OUTLINE, ft.Icons.MAIL),
    ("Messages", ft.Icons.CHAT_BUBBLE_OUTLINE, ft.Icons.CHAT_BUBBLE),
    ("Terminal", ft.Icons.TERMINAL_OUTLINED, ft.Icons.TERMINAL),
    ("Stations", ft.Icons.CELL_TOWER_OUTLINED, ft.Icons.CELL_TOWER),
    ("More", ft.Icons.MORE_HORIZ, ft.Icons.MORE_HORIZ),
)


#: The rail's places: the bar's, with Mail's three sections each a place
#: of its own (there is room at the side; on the phone they are the Mail
#: page's switch). (label, icon, selected icon, view, section)
RAIL = tuple(
    item for label, icon, selected in DESTINATIONS for item in (
        [(value, i, s, MAIL, value) for value, _title, i, s in SECTIONS]
        if label == "Mail" else
        [(label, icon, selected, [d[0] for d in DESTINATIONS].index(label), None)]))


def rail_index(view: int, section: str) -> int:
    return next(i for i, (_l, _i, _s, v, sec) in enumerate(RAIL)
                if v == view and sec in (None, section))


def session_chips(index: int, session) -> tuple[bool, bool]:
    """(Disconnect, Reconnect) beside the transmit switch: on Terminal
    only, Disconnect while the session shown is connected, Reconnect once
    it has dropped (never while it is still connecting: Cancel is on its
    hourglass)."""
    if index != TERMINAL or session is None or not session.key:
        return False, False
    return bool(session.connected), not session.connected and not session.connecting

class ClientApp:
    """One page's client of one station."""

    def __init__(self, page: ft.Page, conn: Connection, state: StationState) -> None:
        self.page = page
        self.conn = conn
        self.state = state
        self.index = MAIL
        #: Set by a connect asked here (`start_connect`): the session it opens
        #: is selected in Terminal. A session another screen opened never
        #: moves this one.
        self.follow_next_session = False
        self.look = Look()
        self._opened_on_start = False
        self.questions = QuestionSheets(self)
        self.gate_button = ft.Container(on_click=self._gate_clicked, border_radius=16,
                                        padding=ft.Padding.symmetric(horizontal=12, vertical=6))
        #: Every place's toolbar (`toolbar.py`), repainted when the width
        #: crosses `WIDE`, which decides whether its buttons carry words.
        self.toolbars: list = []
        views = {MAIL: MailView(self), MESSAGES: MessagesView(self),
                 TERMINAL: SessionsView(self), STATIONS: StationsView(self),
                 MORE: MoreView(self)}
        self.views = [views[i] for i in range(len(DESTINATIONS))]
        #: The connection's state, a strip above everything while it is
        #: not "connected" (never a dialog: it must not cover a question).
        self.status = ft.Container(visible=False, bgcolor=ft.Colors.TERTIARY_CONTAINER,
                                   padding=ft.Padding.symmetric(horizontal=16, vertical=8),
                                   content=ft.Text(""))
        self.body = ft.Container(expand=True)
        self.bar = ft.NavigationBar(
            selected_index=0, on_change=self._nav_changed,
            destinations=[ft.NavigationBarDestination(icon=i, selected_icon=s, label=label)
                          for label, i, s in DESTINATIONS])
        self.rail = ft.NavigationRail(
            selected_index=0, on_change=self._nav_changed,
            label_type=ft.NavigationRailLabelType.ALL,
            destinations=[ft.NavigationRailDestination(icon=i, selected_icon=s, label=label)
                          for label, i, s, _view, _section in RAIL])
        self.layout = ft.Row(expand=True, spacing=0)
        state.subscribe(self._on_state)

    # ------------------------------------------------------------------
    def build(self) -> None:
        page = self.page
        page.title = "kissterm"
        page.padding = 0
        page.appbar = ft.AppBar(title=ft.Text("kissterm"), center_title=False, actions=[
            ft.Container(padding=ft.Padding.only(right=12), content=ft.Row(
                tight=True, spacing=8, controls=[self.gate_button]))])
        page.on_resize = self._on_resize
        self._paint_gate()
        self._place()
        page.run_task(self.load_look)
        page.add(ft.SafeArea(expand=True, content=ft.Column(
            expand=True, spacing=0, controls=[self.status, self.layout])))
        self.go(MAIL)

    async def load_look(self) -> None:
        try:
            prefs = ft.SharedPreferences()
            background, text = [await prefs.get(key) for key in LOOK_KEYS]
        except Exception:  # noqa: BLE001 - no storage: the default look
            log.debug("terminal look not loaded", exc_info=True)
            return
        self.apply_look(Look(str(background or "") or "theme", str(text or "") or "theme",
                             self.look.palette))

    #: Settings > Appearance > Open on, as this client's places. The terminal's
    #: Monitor is More's Monitor section here.
    START_PLACE = {"terminal": TERMINAL, "aprs": MESSAGES, "monitor": MORE}

    async def open_on_start_tab(self) -> None:
        """Once, on the first connect: the place the station says to open
        on, unless the operator has already moved."""
        if self._opened_on_start or self.index != MAIL:
            return
        self._opened_on_start = True
        place = self.START_PLACE.get(await self.command("start_tab") or "")
        if place is not None and self.index == MAIL:
            if place == MORE:
                self.views[MORE].open_monitor()
            self.go(place)

    async def load_theme(self) -> None:
        """The station's theme (Settings > Appearance), drawn here too: the
        page's colour scheme, and the terminal panel where this device has
        not chosen its own look (`Look`)."""
        palette = await self.command("theme")
        if palette:
            self.apply_theme(palette)

    def apply_theme(self, palette: dict) -> None:
        theme.apply(self.page, palette)
        self.apply_look(replace(self.look, palette=Look.pack(palette)))
        self.page.update()

    async def set_look(self, look: Look) -> None:
        """Use `look` on this device and remember it."""
        self.apply_look(look)
        try:
            prefs = ft.SharedPreferences()
            for key, value in zip(LOOK_KEYS, (look.background, look.text)):
                await prefs.set(key, value)
        except Exception:  # noqa: BLE001 - shown now, just not remembered
            log.debug("terminal look not saved", exc_info=True)

    def apply_look(self, look: Look) -> None:
        if look == self.look:
            return
        self.look = look
        self.views[TERMINAL].restyle()
        self.views[MORE].look_changed()
        self.page.update()

    @property
    def wide(self) -> bool:
        return (self.page.width or 0) >= WIDE

    def _place(self) -> None:
        if self.wide:
            self.page.navigation_bar = None
            self.layout.controls = [self.rail, ft.VerticalDivider(width=1), self.body]
        else:
            self.page.navigation_bar = self.bar
            self.layout.controls = [self.body]

    async def _on_resize(self, _e) -> None:
        was = self.page.navigation_bar is None
        if was != self.wide:
            self._place()
            for toolbar in self.toolbars:
                toolbar.paint()
            self.views[MAIL].relayout()
            self.page.update()

    async def _nav_changed(self, e) -> None:
        picked = int(e.control.selected_index)
        if e.control is self.rail:
            _label, _icon, _selected, view, section = RAIL[picked]
            self.go(view, section)
        else:
            self.go(picked)

    def go(self, index: int, section: str | None = None) -> None:
        self.index = index
        if section is not None:
            self.views[MAIL].set_section(section)
        self.bar.selected_index = index
        self.rail.selected_index = rail_index(index, self.views[MAIL].section)
        view = self.views[index]
        self.body.content = view.control
        self.page.appbar.title = ft.Text(self._title())
        self.paint_actions()
        if self.connected:
            # Otherwise it loads when the connection comes up (`on_status`):
            # asked before then, the station's answer is "Not connected".
            self.page.run_task(view.shown)
        self.page.update()

    @property
    def connected(self) -> bool:
        return getattr(self.conn, "status", "connected") == "connected"

    def _title(self) -> str:
        if self.index == MAIL:
            return self.views[MAIL].title()
        label = DESTINATIONS[self.index][0]
        return TITLES.get(label, label)

    def section_changed(self) -> None:
        """Mail's switch moved: the title and the rail follow."""
        self.rail.selected_index = rail_index(self.index, self.views[MAIL].section)
        self.page.appbar.title = ft.Text(self._title())

    def paint_actions(self) -> None:
        """Disconnect or Reconnect in the Terminal's toolbar, by the state of
        the session shown."""
        views = getattr(self, "views", None)  # None while they are built
        if views:
            views[TERMINAL].paint_actions()

    def start_connect(self, **args) -> None:
        """Ask the station to connect, without waiting on it here: Terminal
        comes to the front now, and the new session follows (module
        docstring)."""
        self.follow_next_session = True
        self.go(TERMINAL)

        async def run() -> None:
            await self.command("connect", **args)
            self.follow_next_session = False

        self.page.run_task(run)

    # ------------------------------------------------------------------
    async def command(self, name: str, /, **args):
        """Run a station command; a refusal is a snack bar, never a crash.
        Returns the value, or None when it failed."""
        try:
            return await self.conn.command(name, **args)
        except CommandFailed as exc:
            sheets.snack(self.page, str(exc), error=True)
            return None

    def _paint_gate(self) -> None:
        on = self.state.gate
        self.gate_button.bgcolor = ft.Colors.ERROR if on else None
        self.gate_button.border = None if on else ft.Border.all(1, ft.Colors.OUTLINE)
        self.gate_button.content = ft.Row(tight=True, spacing=6, controls=[
            ft.Icon(ft.Icons.CELL_TOWER if on else ft.Icons.PORTABLE_WIFI_OFF, size=18,
                    color=ft.Colors.ON_ERROR if on else None),
            ft.Text("TX ON" if on else "TX OFF", weight=ft.FontWeight.BOLD,
                    color=ft.Colors.ON_ERROR if on else None)])
        self.gate_button.tooltip = ("Transmit is on: tap to turn it off" if on
                                    else "Transmit is off: tap to turn it on")

    async def _gate_clicked(self, _e) -> None:
        if self.state.gate:
            await self.command("transmit", enabled=False)
            return

        async def arm() -> None:
            if await self.command("transmit", enabled=True):
                await self.haptic()

        sheets.confirm(self.page, "Turn transmit on?",
                       "This station can then key its radio, under its callsign.",
                       "Turn on", arm, danger=True)

    async def haptic(self) -> None:
        try:
            await ft.HapticFeedback().heavy_impact()
        except Exception:  # noqa: BLE001 - a browser or desktop has none
            pass

    # ------------------------------------------------------------------
    def on_status(self, status: str) -> None:
        text = {
            "connected": "",
            "connecting": "Connecting to the station...",
            "offline": "Lost the station. Reconnecting...",
            "refused": "This pairing link no longer works. Open the new one from the "
                       "station (Session > Remote pairing).",
        }.get(status, status)
        self.status.content = ft.Text(text)
        self.status.visible = bool(text)
        if status == "connected":
            # First connect or back after a drop: the place in front loads
            # (again) from the station, and so does its theme.
            self.page.run_task(self.views[self.index].shown)
            self.page.run_task(self.load_theme)
            self.page.run_task(self.open_on_start_tab)
        self.page.update()

    def _on_state(self, kind: str, data) -> None:
        if kind in ("gate", "station"):
            self._paint_gate()
            self.page.appbar.title = ft.Text(self._title())
        if kind == "stale" and data == "config":
            self.page.run_task(self.load_theme)
        if kind == "notice":
            sheets.snack(self.page, data.get("text", ""),
                         error=data.get("severity") == "error",
                         seconds=data.get("timeout") or 4)
        elif kind == "alert":
            sheets.snack(self.page, f"{data.get('title', '')}: {data.get('body', '')}",
                         error=bool(data.get("urgent")))
            self.page.run_task(self.haptic)
        elif kind == "question":
            self.questions.show(data)
        elif kind == "question_closed":
            self.questions.closed(data)
        for view in self.views:
            view.on_state(kind, data)
        self.page.update()


async def run(page: ft.Page, url: str, token: str) -> ClientApp:
    """Connect `page` to the station at `url` and build the app."""
    state = StationState()
    app: ClientApp | None = None

    def status(text: str) -> None:
        if app is not None:
            app.on_status(text)

    conn = Connection(url, token, on_message=state.apply, on_status=status,
                      client="kissterm-flet")
    app = ClientApp(page, conn, state)
    app.build()
    conn.start()

    async def closed(_e=None) -> None:
        await conn.close()

    page.on_disconnect = closed
    page.on_close = closed
    await asyncio.sleep(0)
    return app
