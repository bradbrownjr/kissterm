"""Mail: the station's message store, read from the phone, and Send/
Receive started from it.

Reading is free; **Send/Receive is a button**, the same request as the
terminal's G, and dials the Home BBS or Winlink through the station's own
connect flow (the reminder, the gate, a login question here if one is
missing). Writing mail from the phone is not in protocol v1.
"""

from __future__ import annotations

import flet as ft

from . import sheets

ALL_INBOXES = ""


class MailView:
    def __init__(self, app) -> None:
        self.app = app
        self.folder = "Mail/BBS/Inbox"
        self.folders = ft.Dropdown(dense=True, expand=True, on_select=self._folder_changed,
                                   options=[])
        self.list = ft.ListView(expand=True)
        self.reader: ft.Control | None = None
        self.control = ft.Container(expand=True)
        self._show_list()

    def fab(self):
        if self.reader is not None:
            return None
        return ft.FloatingActionButton(icon=ft.Icons.SYNC, tooltip="Send/Receive",
                                       on_click=self._send_receive)

    async def shown(self) -> None:
        await self.reload()

    def on_state(self, kind: str, data) -> None:
        if kind == "stale" and data == "mail":
            self.app.page.run_task(self.reload)
        elif kind == "activity" and self.reader is None:
            self._show_list()

    def _show_list(self) -> None:
        self.reader = None
        activity = self.app.state.activity
        self.control.content = ft.Column(expand=True, spacing=0, controls=[
            ft.Container(padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                         content=ft.Row(controls=[self.folders])),
            *([ft.Container(padding=ft.Padding.symmetric(horizontal=16, vertical=4),
                            content=ft.Text(activity, color=ft.Colors.PRIMARY))] if activity else []),
            self.list])

    async def reload(self) -> None:
        folders = await self.app.command("mail_folders") or []
        if folders and self.folder not in folders:
            self.folder = next((f for f in folders if f.endswith("Inbox")), folders[0])
        self.folders.options = [ft.DropdownOption(key=f, text=f.removeprefix("Mail/")) for f in folders]
        self.folders.value = self.folder
        messages = await self.app.command("mail_list", folder=self.folder) or []
        self.list.controls = [ft.ListTile(
            title=ft.Text(m.get("subject", "") or "(no subject)", max_lines=1,
                          overflow=ft.TextOverflow.ELLIPSIS),
            subtitle=ft.Text(f"{m.get('sender', '')}  {m.get('date', '')}", size=12),
            on_click=self._opener(m.get("ref", ""))) for m in messages] or [ft.Container(
                padding=ft.Padding.all(24),
                content=ft.Text("Nothing in this folder.", color=ft.Colors.OUTLINE))]
        self.app.page.update()

    async def _folder_changed(self, e) -> None:
        self.folder = e.control.value
        await self.reload()

    def _opener(self, ref: str):
        async def handler(_e) -> None:
            await self.open(ref)
        return handler

    async def open(self, ref: str) -> None:
        message = await self.app.command("mail_read", ref=ref)
        if not message:
            return
        head = [f"From: {message.get('sender', '')}", f"To: {message.get('to', '')}",
                f"Date: {message.get('date', '')}"]
        self.reader = ft.Column(expand=True, spacing=0, controls=[
            ft.Row(controls=[ft.IconButton(icon=ft.Icons.ARROW_BACK, tooltip="Back to the list",
                                           on_click=self._back),
                             ft.Text(message.get("subject", ""), expand=True, max_lines=2,
                                     theme_style=ft.TextThemeStyle.TITLE_MEDIUM)]),
            ft.Container(expand=True, padding=ft.Padding.all(16), content=ft.Column(
                scroll=ft.ScrollMode.AUTO, controls=[
                    ft.Text("\n".join(head), color=ft.Colors.OUTLINE, selectable=True),
                    ft.Divider(),
                    ft.Text(message.get("body", ""), selectable=True)]))])
        self.control.content = self.reader
        self.app.page.floating_action_button = None
        self.app.page.update()

    async def _back(self, _e) -> None:
        self._show_list()
        self.app.page.floating_action_button = self.fab()
        await self.reload()

    async def _send_receive(self, _e) -> None:
        folder = self.folder

        async def go() -> None:
            await self.app.command("send_receive", folder=folder)

        sheets.confirm(self.app.page, "Send and receive mail?",
                       "The station connects by radio, sends the Outbox and reads new mail.",
                       "Send/Receive", go)
