"""Mail: the station's message store, read from the phone, and Send/
Receive started from it.

Reading is free; **Send/Receive is a button**, the same request as the
terminal's G, and dials the Home BBS or Winlink through the station's own
connect flow (the reminder, the gate, a login question here if one is
missing). Writing mail from the phone is not in protocol v1.

**A run shows it is still going** (operator, 2026-10-06: after the first
notice, nothing said it was). While the station reports one running
(`MailRunChanged`), the Send/Receive button's icon turns, and the
progress line ("Receiving 2 of 2") is followed by dots counting one to
three. **Tapping the turning button cancels the run** with no sheet:
stopping only ends the exchange (`mail_cancel`, a DISC if the link is
up), as the transmit switch turns off without asking.
"""

from __future__ import annotations

import asyncio
import math

import flet as ft

from . import sheets

ALL_INBOXES = ""
#: Seconds per step of the turning icon and the counting dots.
TICK = 0.4


class MailView:
    def __init__(self, app) -> None:
        self.app = app
        self.folder = "Mail/BBS/Inbox"
        self.folders = ft.Dropdown(dense=True, expand=True, on_select=self._folder_changed,
                                   options=[])
        self.list = ft.ListView(expand=True)
        self.reader: ft.Control | None = None
        self.control = ft.Container(expand=True)
        self.activity = ft.Text("", color=ft.Colors.PRIMARY)
        self.sync_icon = ft.Icon(ft.Icons.SYNC, rotate=0,
                                 animate_rotation=ft.Animation(int(TICK * 1000), ft.AnimationCurve.LINEAR))
        self.button = ft.FloatingActionButton(content=self.sync_icon, on_click=self._send_receive)
        self._ticking = False
        self._dots = 0
        self._paint_button()
        self._show_list()

    def fab(self):
        if self.reader is not None:
            return None
        return self.button

    def _paint_button(self) -> None:
        running = self.app.state.mail_running
        self.button.tooltip = ("Sending and receiving: tap to cancel" if running
                               else "Send/Receive")

    async def shown(self) -> None:
        await self.reload()

    def on_state(self, kind: str, data) -> None:
        if kind == "stale" and data == "mail":
            self.app.page.run_task(self.reload)
        elif kind == "activity" and self.reader is None:
            self._show_list()
        elif kind in ("mail_running", "station"):  # "station": a (re)join mid-run
            self._paint_button()
            if self.app.state.mail_running and not self._ticking:
                self._ticking = True
                self.app.page.run_task(self._tick)

    async def _tick(self) -> None:
        """Turn the icon and count the dots while a run is going."""
        try:
            while self.app.state.mail_running:
                self.sync_icon.rotate = (self.sync_icon.rotate or 0) + math.pi / 2
                self._dots = self._dots % 3 + 1
                self._paint_activity()
                self.app.page.update()
                await asyncio.sleep(TICK)
        finally:
            self._ticking = False
            self._dots = 0
            self._paint_activity()
            self.app.page.update()

    def _paint_activity(self) -> None:
        text = self.app.state.activity
        dots = "." * self._dots if self.app.state.mail_running else ""
        # The dots in a fixed width, so the line does not shuffle as they count.
        self.activity.value = f"{text}{dots:<3}" if text else ""

    def _show_list(self) -> None:
        self.reader = None
        self._paint_activity()
        self.control.content = ft.Column(expand=True, spacing=0, controls=[
            ft.Container(padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                         content=ft.Row(controls=[self.folders])),
            *([ft.Container(padding=ft.Padding.symmetric(horizontal=16, vertical=4),
                            content=self.activity)] if self.app.state.activity else []),
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
        if self.app.state.mail_running:
            # Stopping never asks (module docstring).
            if await self.app.command("mail_cancel"):
                sheets.snack(self.app.page, "Cancelling Send/Receive...")
            return
        folder = self.folder

        async def go() -> None:
            await self.app.command("send_receive", folder=folder)

        sheets.confirm(self.app.page, "Send and receive mail?",
                       "The station connects by radio, sends the Outbox and reads new mail.",
                       "Send/Receive", go)
