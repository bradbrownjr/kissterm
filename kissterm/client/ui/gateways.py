"""RMS gateways (the terminal's F10 > Session > RMS gateways): Winlink
gateways nearest first, one to use as the Winlink Dial.

The station owns the list (`rms_gateways`, from the file it saved), the
Refresh (`rms_refresh`: an Internet request to winlink.org, only when
pressed, and only once kissterm has its Winlink API key) and what choosing
one does (`rms_use`: an Address Book entry and the Winlink Dial). **Nothing
here goes on the air**; choosing asks first only because a thumb is easily
misplaced on a long list.
"""

from __future__ import annotations

import flet as ft

from . import sheets


class GatewaysSheet:
    def __init__(self, view) -> None:
        self.view = view
        self.mode = "packet"
        self.data: dict = {}
        self.rows = ft.Column(tight=True, spacing=0)
        self.note = ft.Text("", size=12, color=ft.Colors.OUTLINE)
        self.picker = ft.Dropdown(label="Mode", value="packet", dense=True,
                                  on_select=self._mode_picked, options=[])
        self.refresh = ft.OutlinedButton(content="Refresh", on_click=self._refresh)

    @property
    def app(self):
        return self.view.app

    async def show(self) -> None:
        await self._load()
        self.app.page.show_dialog(sheets.sheet([
            ft.Text("RMS gateways", theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
            self.note, self.picker, self.rows,
            ft.Row(alignment=ft.MainAxisAlignment.END, controls=[
                ft.TextButton(content="Close", on_click=self._close), self.refresh])],
            scrollable=True))

    async def _load(self) -> None:
        self.data = await self.app.command("rms_gateways", mode=self.mode) or {}
        self.note.value = self.data.get("note", "")
        self.picker.options = [ft.DropdownOption(key=value, text=label)
                               for label, value in self.data.get("modes", [])]
        self.picker.value = self.mode
        self.refresh.disabled = not self.data.get("can_refresh")
        self.rows.controls = [ft.ListTile(
            title=ft.Text(c["callsign"]),
            subtitle=ft.Text("  ".join(p for p in (c["frequency"], c["modes"], c["grid"],
                                                    c["hours"]) if p), size=12),
            trailing=ft.Text(c["distance"], size=11, color=ft.Colors.OUTLINE),
            on_click=self._chooser(c)) for c in self.data.get("channels", [])]

    async def _mode_picked(self, e) -> None:
        self.mode = e.control.value or ""
        await self._load()
        self.app.page.update()

    async def _refresh(self, _e) -> None:
        self.note.value = "Fetching the list from winlink.org..."
        self.app.page.update()
        problem = await self.app.command("rms_refresh")
        await self._load()
        if problem:
            self.note.value = f"{problem} {self.note.value}"
        self.app.page.update()

    def _chooser(self, channel: dict):
        async def choose(_e) -> None:
            self.app.page.pop_dialog()

            async def go() -> None:
                await self.app.command(
                    "rms_use", callsign=channel["callsign"], frequency=channel["frequency"],
                    modes=channel["modes"], grid=channel["grid"])

            sheets.confirm(
                self.app.page, f"Use {channel['callsign']} for Winlink?",
                f"{channel['frequency']}, {channel['modes']}. It goes in the Address Book and "
                "becomes the Winlink Dial. Nothing is dialed or sent.", "Use", go)
        return choose

    async def _close(self, _e=None) -> None:
        self.app.page.pop_dialog()
