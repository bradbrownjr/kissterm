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

import flet as ft

from ..connection import CommandFailed, Connection
from ..state import StationState
from . import sheets
from .mail import MailView
from .messages import MessagesView
from .more import MoreView
from .questions import QuestionSheets
from .sessions import SessionsView
from .stations import StationsView
from .text import Look

log = logging.getLogger(__name__)

#: Preference keys for the terminal's look (`Look`).
LOOK_KEYS = ("kissterm.terminal.background", "kissterm.terminal.text")

#: Width (logical pixels) from which destinations move to a side rail.
WIDE = 720

DESTINATIONS = (
    ("Sessions", ft.Icons.TERMINAL_OUTLINED, ft.Icons.TERMINAL),
    ("Messages", ft.Icons.CHAT_BUBBLE_OUTLINE, ft.Icons.CHAT_BUBBLE),
    ("Mail", ft.Icons.MAIL_OUTLINE, ft.Icons.MAIL),
    ("Stations", ft.Icons.CELL_TOWER_OUTLINED, ft.Icons.CELL_TOWER),
    ("More", ft.Icons.MORE_HORIZ, ft.Icons.MORE_HORIZ),
)


class ClientApp:
    """One page's client of one station."""

    def __init__(self, page: ft.Page, conn: Connection, state: StationState) -> None:
        self.page = page
        self.conn = conn
        self.state = state
        self.index = 0
        #: Set by a connect asked from another view: the next new session
        #: brings Sessions to the front. A session another screen opened
        #: never moves this one.
        self.follow_next_session = False
        self.look = Look()
        self.views = [SessionsView(self), MessagesView(self), MailView(self),
                      StationsView(self), MoreView(self)]
        self.questions = QuestionSheets(self)
        self.gate_button = ft.Container(on_click=self._gate_clicked, border_radius=16,
                                        padding=ft.Padding.symmetric(horizontal=12, vertical=6))
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
                          for label, i, s in DESTINATIONS])
        self.layout = ft.Row(expand=True, spacing=0)
        state.subscribe(self._on_state)

    # ------------------------------------------------------------------
    def build(self) -> None:
        page = self.page
        page.title = "kissterm"
        page.padding = 0
        page.appbar = ft.AppBar(title=ft.Text("kissterm"), center_title=False, actions=[
            ft.Container(content=self.gate_button, padding=ft.Padding.only(right=12))])
        page.on_resize = self._on_resize
        self._paint_gate()
        self._place()
        page.run_task(self.load_look)
        page.add(ft.SafeArea(expand=True, content=ft.Column(
            expand=True, spacing=0, controls=[self.status, self.layout])))
        self.go(0)

    async def load_look(self) -> None:
        try:
            prefs = ft.SharedPreferences()
            background, text = [await prefs.get(key) for key in LOOK_KEYS]
        except Exception:  # noqa: BLE001 - no storage: the default look
            log.debug("terminal look not loaded", exc_info=True)
            return
        self.apply_look(Look(str(background or ""), str(text or "")))

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
        self.views[0].restyle()
        self.views[4].look_changed()
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
            self.page.update()

    async def _nav_changed(self, e) -> None:
        self.go(int(e.control.selected_index))

    def go(self, index: int) -> None:
        self.index = index
        self.bar.selected_index = self.rail.selected_index = index
        view = self.views[index]
        self.body.content = view.control
        self.page.floating_action_button = view.fab()
        self.page.appbar.title = ft.Text(self._title())
        self.page.run_task(view.shown)
        self.page.update()

    def _title(self) -> str:
        call = self.state.callsign or "kissterm"
        return f"{call}  {DESTINATIONS[self.index][0]}"

    # ------------------------------------------------------------------
    async def command(self, name: str, **args):
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
        self.page.update()

    def _on_state(self, kind: str, data) -> None:
        if kind in ("gate", "station"):
            self._paint_gate()
            self.page.appbar.title = ft.Text(self._title())
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
        elif (kind == "session" and self.follow_next_session
              and data.key not in self.views[0].terminals):
            self.follow_next_session = False
            self.go(0)  # Sessions selects a new session as it adds it
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
