"""Messages: APRS conversations as a chat app shows them. A list of
correspondents, newest first, with an unread dot; a thread of bubbles,
mine on the right with a tick once acknowledged.

**Send position** sits above the conversations (the terminal's P on
its APRS tab), asking first like every transmission; **Map** beside it
opens the map of what was heard with a position (`aprs_map.py`, the
terminal's APRS > Map), and **Object** an object report to send
(`aprs_object.py`, APRS > Object), as a long press on the map does.

**Send is the commitment** (the station arms the gate for it, as the
terminal's Send does: `Aprs.compose`); opening, scrolling or swiping a
thread never sends. Retries are the station's, never this client's.
"""

from __future__ import annotations

import time

import flet as ft

from . import sheets


def ago(when: float, now: float | None = None) -> str:
    """"just now", "5 min", "3 h", "2 d": how long ago `when` (epoch) was."""
    seconds = max(0, (now or time.time()) - when)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h"
    return f"{int(seconds // 86400)} d"


def bubble(message: dict) -> ft.Control:
    mine = message.get("direction") == "out"
    status = []
    if mine and message.get("number"):
        status = [ft.Icon(ft.Icons.DONE_ALL if message.get("acked") else ft.Icons.DONE,
                          size=14, color=ft.Colors.PRIMARY if message.get("acked") else None,
                          tooltip="Acknowledged" if message.get("acked") else "Sent, not yet acknowledged")]
    return ft.Row(alignment=ft.MainAxisAlignment.END if mine else ft.MainAxisAlignment.START,
                  controls=[ft.Container(
                      padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                      border_radius=16, margin=ft.Margin.symmetric(vertical=2),
                      bgcolor=ft.Colors.PRIMARY_CONTAINER if mine else ft.Colors.SURFACE_CONTAINER_HIGH,
                      content=ft.Column(tight=True, spacing=2, controls=[
                          ft.Text(message.get("text", ""), selectable=True),
                          ft.Row(tight=True, spacing=4, controls=[
                              ft.Text(ago(message.get("timestamp", 0)), size=11,
                                      color=ft.Colors.OUTLINE), *status])]))])


class MessagesView:
    def __init__(self, app) -> None:
        self.app = app
        self.thread_of: str | None = None
        #: The map page while it is open (`aprs_map.MapPage`).
        self.map = None
        #: The object form while it is open (`aprs_object.ObjectForm`).
        self.object_form = None
        self.list = ft.ListView(expand=True)
        self.thread = ft.ListView(expand=True, auto_scroll=True, padding=ft.Padding.all(8))
        self.compose = ft.TextField(expand=True, hint_text="Message", dense=True,
                                    on_submit=self._send, max_length=67)
        #: APRS > Send position, the terminal's P on its APRS tab.
        self.toolbar = ft.Container(
            padding=ft.Padding.symmetric(horizontal=12, vertical=6),
            # Wraps on a narrow phone rather than pushing Object off the edge.
            content=ft.Row(wrap=True, spacing=8, run_spacing=8, controls=[
                ft.OutlinedButton(content="Send position", icon=ft.Icons.MY_LOCATION,
                                  on_click=self._send_position),
                ft.OutlinedButton(content="Map", icon=ft.Icons.MAP_OUTLINED,
                                  on_click=self._open_map),
                ft.OutlinedButton(content="Object", icon=ft.Icons.ADD_LOCATION_ALT_OUTLINED,
                                  on_click=self._new_object)]))
        self.control = ft.Container(expand=True)
        self._show_list()

    def fab(self):
        if self.thread_of is not None or self.map is not None or self.object_form is not None:
            return None
        return ft.FloatingActionButton(icon=ft.Icons.EDIT, tooltip="New message",
                                       on_click=self._new, mini=True)

    async def shown(self) -> None:
        if self.object_form is not None:
            return  # what is typed stays
        if self.map is not None:
            await self.map.reload()
            return
        await self.reload()

    def on_state(self, kind: str, data) -> None:
        if kind == "stale" and data == "aprs":
            # Only while in front, as Mail (`mail.MailView.on_state`):
            # `shown` reloads when it comes back.
            from .shell import MESSAGES

            if self.app.index == MESSAGES:
                self.app.page.run_task(self.reload)
        elif kind == "stale" and data == "heard" and self.map is not None:
            from .shell import MESSAGES

            if self.app.index == MESSAGES:
                self.map.stale()

    async def reload(self) -> None:
        convos = await self.app.command("aprs_conversations") or []
        unread = self.app.state.unread_aprs
        self.list.controls = [self.toolbar] + [ft.ListTile(
            leading=ft.CircleAvatar(content=ft.Text(c["callsign"][:2])),
            title=ft.Text(c["callsign"], weight=ft.FontWeight.BOLD if c["callsign"] in unread else None),
            subtitle=ft.Text(c.get("last", ""), max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            trailing=ft.Row(tight=True, spacing=6, controls=[
                ft.Text(ago(c.get("last_activity", 0)), size=11, color=ft.Colors.OUTLINE),
                *([ft.Container(width=10, height=10, border_radius=5, bgcolor=ft.Colors.PRIMARY)]
                  if c["callsign"] in unread else [])]),
            on_click=self._opener(c["callsign"])) for c in convos]
        if not convos:
            self.list.controls.append(ft.Container(
                padding=ft.Padding.all(24),
                content=ft.Text("No APRS messages yet.", color=ft.Colors.OUTLINE)))
        if self.thread_of is not None:
            await self._load_thread()
        self.app.page.update()

    def _opener(self, callsign: str):
        async def handler(_e) -> None:
            await self.open(callsign)
        return handler

    async def _open_map(self, _e) -> None:
        from .aprs_map import MapPage

        self.map = MapPage(self)
        self.control.content = self.map.root
        self.app.page.floating_action_button = None
        self.app.page.update()
        await self.map.reload()

    async def _new_object(self, _e) -> None:
        await self.open_object_form()

    async def open_object_form(self, latitude: float | None = None,
                               longitude: float | None = None, name: str = "") -> None:
        """The object form, here or at the place given (a long press on the
        map); `name`, one of this station's objects, moves it."""
        from .aprs_object import ObjectForm

        args = {"name": name}
        if latitude is not None:
            args.update(latitude=latitude, longitude=longitude)
        start = await self.app.command("aprs_object_start", **args)
        if not start:
            return
        self.object_form = ObjectForm(self, start, moving=bool(name))
        self.control.content = self.object_form.control()
        self.app.page.floating_action_button = None
        self.app.page.update()

    async def close_object_form(self) -> None:
        """Back to where the form was opened from: the map, else the list."""
        self.object_form = None
        if self.map is not None:
            self.control.content = self.map.root
            self.app.page.update()
            await self.map.reload()
            return
        await self._back(None)

    async def open(self, callsign: str) -> None:
        self.map = None
        self.object_form = None
        self.thread_of = callsign
        self.app.state.unread_aprs.discard(callsign)
        await self._load_thread()
        self.control.content = ft.Column(expand=True, spacing=0, controls=[
            ft.Row(controls=[ft.IconButton(icon=ft.Icons.ARROW_BACK, tooltip="All messages",
                                           on_click=self._back),
                             ft.Text(callsign, theme_style=ft.TextThemeStyle.TITLE_MEDIUM)]),
            self.thread,
            ft.Container(padding=ft.Padding.all(8), content=ft.Row(controls=[
                self.compose, ft.IconButton(icon=ft.Icons.SEND, tooltip="Send",
                                            on_click=self._send)]))])
        self.app.page.floating_action_button = None
        self.app.page.update()

    async def _load_thread(self) -> None:
        messages = await self.app.command("aprs_thread", callsign=self.thread_of) or []
        self.thread.controls = [bubble(m) for m in messages]

    async def _back(self, _e) -> None:
        self._show_list()
        self.app.page.floating_action_button = self.fab()
        await self.reload()

    def _show_list(self) -> None:
        self.thread_of = None
        self.map = None
        self.object_form = None
        self.control.content = self.list

    async def _send(self, _e) -> None:
        text = (self.compose.value or "").strip()
        if not text or self.thread_of is None:
            return
        result = await self.app.command("aprs_send", to=self.thread_of, text=text)
        if result:
            self.compose.value = ""
            await self._load_thread()
        self.app.page.update()

    async def _send_position(self, _e) -> None:
        async def go() -> None:
            await self.app.command("aprs_position")

        sheets.confirm(self.app.page, "Send your position now?",
                       "Turns transmit on and sends one APRS position report from "
                       "the station. The position beacon's timer is not changed.", "Send", go)

    async def _new(self, _e) -> None:
        to = ft.TextField(label="To", hint_text="Callsign, e.g. W1AW-7", autofocus=True,
                          capitalization=ft.TextCapitalization.CHARACTERS)
        text = ft.TextField(label="Message", max_length=67, multiline=True)

        async def go() -> None:
            call = (to.value or "").strip().upper()
            if call and (text.value or "").strip():
                if await self.app.command("aprs_send", to=call, text=text.value.strip()):
                    await self.open(call)

        sheets.form(self.app.page, "New APRS message", [to, text], "Send", go)
