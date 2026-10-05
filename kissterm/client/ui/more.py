"""More: the station itself (callsign, transport, what it is doing), the
channel as the Monitor shows it, recent notices, and Settings.
"""

from __future__ import annotations

import flet as ft

from .settings import SettingsEditor
from .text import MONO

#: Monitor lines shown (the model keeps more).
MONITOR_SHOWN = 200


class MoreView:
    def __init__(self, app) -> None:
        self.app = app
        self.settings = SettingsEditor(app)
        self.station = ft.Column(tight=True, spacing=4)
        self.monitor = ft.ListView(height=260, auto_scroll=True, spacing=0)
        self.notices = ft.Column(tight=True, spacing=4)
        self.control = ft.ListView(expand=True, padding=ft.Padding.all(12), controls=[
            ft.Card(content=ft.Container(padding=ft.Padding.all(16), content=self.station)),
            ft.ExpansionTile(title=ft.Text("Monitor"), subtitle=ft.Text(
                "Every frame the station hears or sends", size=12),
                controls=[self.monitor]),
            ft.ExpansionTile(title=ft.Text("Notices"), controls=[self.notices]),
            ft.ExpansionTile(title=ft.Text("Settings"), subtitle=ft.Text(
                "The station's settings, checked by the station", size=12),
                controls=[self.settings.column,
                          ft.Row(alignment=ft.MainAxisAlignment.END,
                                 controls=[self.settings.save_button])],
                on_change=self._settings_opened),
        ])
        self._paint()

    def fab(self):
        return None

    async def shown(self) -> None:
        self._paint()
        self.app.page.update()

    def on_state(self, kind: str, data) -> None:
        if kind in ("station", "transport", "gate", "activity"):
            self._paint()
        elif kind == "monitor":
            self.monitor.controls.append(ft.Text(data.get("line", ""), font_family=MONO,
                                                 size=11, selectable=True,
                                                 color=ft.Colors.PRIMARY if data.get("outgoing") else None))
            del self.monitor.controls[:-MONITOR_SHOWN]
        elif kind == "notice":
            self.notices.controls.insert(0, ft.Text(data.get("text", ""), size=12))
            del self.notices.controls[20:]
        elif kind == "stale" and data == "config":
            self.app.page.run_task(self.settings.load)

    def _paint(self) -> None:
        state = self.app.state
        transport = state.transport or {}
        lines = [
            ("Station", state.callsign or "(not set)"),
            ("kissterm", state.version),
            ("Transport", transport.get("detail") or transport.get("name") or "none open"),
            ("Transmit", "ON" if state.gate else "off"),
            ("Connection", self.app.conn.status),
        ]
        if state.activity:
            lines.append(("Doing", state.activity))
        self.station.controls = [ft.Row(controls=[
            ft.Text(name, width=100, color=ft.Colors.OUTLINE), ft.Text(value, expand=True)])
            for name, value in lines]

    async def _settings_opened(self, e) -> None:
        if e.control.expanded if hasattr(e.control, "expanded") else True:
            await self.settings.load()
            self.app.page.update()
