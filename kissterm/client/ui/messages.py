"""Messages: APRS conversations as a chat app shows them. A list of
correspondents, newest first, with an unread dot; a thread of bubbles,
mine on the right with a tick once acknowledged.

**Position** sits above the conversations (the terminal's APRS > Send
position), asking first like every transmission; one word, so it,
Map and Object fit one row on a phone (operator, 2026-10-06); **Map** beside it
opens the map of what was heard with a position (`aprs_map.py`, the
terminal's APRS > Map), and **Object** an object report to send
(`aprs_object.py`, APRS > Object), as a long press on the map does.

**Send is the commitment** (the station arms the gate for it, as the
terminal's Send does: `Aprs.compose`); opening, scrolling or swiping a
thread never sends. Retries are the station's, never this client's.

**Templates** beside the message box (the terminal's Ctrl+R) fill it and never
send (`templates.py`).
"""

from __future__ import annotations

import time

import flet as ft

from . import sheets
from .toolbar import Action, Toolbar


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


def counted_field(limit: int, **kwargs) -> ft.TextField:
    """A text field that stops at `limit` and shows "n/limit" inside its
    right end. Flet's own counter sits under the box, which pushed the
    field up out of line with the buttons beside it (operator, 2026-10-08:
    "does not look polished")."""
    count = ft.Text(f"0/{limit}", size=11, color=ft.Colors.OUTLINE)
    user_change = kwargs.pop("on_change", None)

    async def changed(e) -> None:
        count.value = f"{len(e.control.value or '')}/{limit}"
        if user_change is not None:
            await user_change(e)
        try:
            count.update()
        except RuntimeError:  # not on a page yet (a test, a sheet still opening)
            pass

    field = ft.TextField(max_length=limit, counter="", suffix=count, on_change=changed, **kwargs)

    def fill(text: str) -> None:
        """Set the text from code (a template, a send): the count follows."""
        field.value = text
        count.value = f"{len(text)}/{limit}"

    field.fill = fill
    return field


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
        self.compose = counted_field(67, expand=True, hint_text="Message", dense=True,
                                     on_submit=self._send)
        #: The one toolbar (`toolbar.py`): Position (the terminal's P on its
        #: APRS tab), Map, Object, and New message last.
        self.toolbar = Toolbar(app)
        self.toolbar.set([
            Action(ft.Icons.MY_LOCATION, "Position", self._send_position,
                   tooltip="Send position"),
            Action(ft.Icons.MAP_OUTLINED, "Map", self._open_map),
            Action(ft.Icons.ADD_LOCATION_ALT_OUTLINED, "Object", self._new_object,
                   tooltip="New object"),
            Action(ft.Icons.EDIT, "New message", self._new, primary=True)])
        self.control = ft.Container(expand=True)
        self._show_list()

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
        self.list.controls = [ft.Container(padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                                          content=self.toolbar.row)] + [ft.ListTile(
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
                # The terminal's Ctrl+R: what to say to a gateway, and saved messages.
                ft.IconButton(icon=ft.Icons.LIST_ALT, tooltip="Templates",
                              on_click=self._templates),
                self.compose, ft.IconButton(icon=ft.Icons.SEND, tooltip="Send",
                                            on_click=self._send)]))])
        self.app.page.update()

    async def _templates(self, _e) -> None:
        await self.open_templates()

    async def open_templates(self) -> None:
        """The templates sheet for the open conversation; a pick fills the
        compose box and sends nothing (`templates.py`)."""
        from .templates import TemplatesSheet

        if self.thread_of is None:
            return
        data = await self.app.command("aprs_templates", callsign=self.thread_of)
        if data:
            TemplatesSheet(self, self.thread_of, data).show()

    async def _load_thread(self) -> None:
        messages = await self.app.command("aprs_thread", callsign=self.thread_of) or []
        self.thread.controls = [bubble(m) for m in messages]

    async def _back(self, _e) -> None:
        self._show_list()
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
            self.compose.fill("")
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
        text = counted_field(67, label="Message", multiline=True)

        async def go() -> None:
            call = (to.value or "").strip().upper()
            if call and (text.value or "").strip():
                if await self.app.command("aprs_send", to=call, text=text.value.strip()):
                    await self.open(call)

        sheets.form(self.app.page, "New APRS message", [to, text], "Send", go)
