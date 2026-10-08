"""Broadcast on the phone and web client: the terminal's Session >
Broadcast. Free text sent once to CQ, QST or ALL with no connection, and the
broadcasts heard and sent (`core/broadcast.py`, commands `broadcast_info`
and `broadcast_send`).

**Every rule is the station's**: where a broadcast may go, what it costs
the channel, who is heard, and that sending arms the transmit gate. This
sheet shows the cost as the text changes and sends only when Send is
pressed, which is the commitment; opening it, picking a destination or
typing transmits nothing.
"""

from __future__ import annotations

from datetime import datetime

import flet as ft

from . import sheets
from .text import MONO


class BroadcastSheet:
    def __init__(self, view) -> None:
        self.view = view
        self.to = ft.Dropdown(label="To", dense=True, value="CQ")
        self.text = ft.TextField(label="Text to send to everyone listening", dense=True,
                                 multiline=True, min_lines=2, max_length=200,
                                 on_change=self._edited)
        self.cost = ft.Text("", size=12, color=ft.Colors.OUTLINE)
        self.heard = ft.Column(tight=True, spacing=4)
        self.open = False

    @property
    def page(self):
        return self.view.app.page

    async def show(self) -> None:
        info = await self.view.app.command("broadcast_info", text="")
        if not info:
            return
        self.to.options = [ft.DropdownOption(key=d, text=d) for d in info["destinations"]]
        self._paint(info)
        self.open = True
        self.page.show_dialog(sheets.sheet([
            ft.Text("Broadcast", theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
            ft.Text("Sends once, now, to nobody in particular. No answer is expected or "
                    "acknowledged.", size=12),
            self.to, self.text, self.cost,
            ft.Text("Heard and sent", theme_style=ft.TextThemeStyle.TITLE_SMALL), self.heard,
            ft.Row(alignment=ft.MainAxisAlignment.END, controls=[
                ft.TextButton(content="Close", on_click=self._close),
                ft.FilledButton(content="Send", icon=ft.Icons.CAMPAIGN, on_click=self._send)])],
            scrollable=True, on_dismiss=self._dismissed))

    def _paint(self, info: dict) -> None:
        self.cost.value = f"This costs {info['cost']}."
        lines = []
        for h in info["heard"][-12:]:
            stamp = datetime.fromtimestamp(h["at"]).strftime("%H:%M")
            who = "you" if h["own"] else h["source"]
            lines.append(ft.Text(f"{stamp} {who} > {h['to']}: {h['text']}", font_family=MONO,
                                 size=12, selectable=True,
                                 color=ft.Colors.PRIMARY if h["own"] else None))
        self.heard.controls = lines or [ft.Text("Nothing heard yet.", size=12,
                                                color=ft.Colors.OUTLINE)]

    async def refresh(self) -> None:
        """A broadcast was heard or sent while the sheet is open."""
        if not self.open:
            return
        info = await self.view.app.command("broadcast_info", text=self.text.value or "")
        if info:
            self._paint(info)
            self.page.update()

    async def _edited(self, _e) -> None:
        await self.refresh()

    async def _send(self, _e) -> None:
        result = await self.view.app.command("broadcast_send", to=self.to.value or "CQ",
                                             text=self.text.value or "")
        if result is None:
            return
        if result.get("error"):
            sheets.snack(self.page, result["error"], error=True)
            return
        self.text.value = ""
        await self.refresh()

    def _dismissed(self, _e) -> None:
        self.open = False

    async def _close(self, _e) -> None:
        self.open = False
        self.page.pop_dialog()
