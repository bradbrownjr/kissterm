"""More: the station itself (callsign, transport, what it is doing), the
channel as the Monitor shows it, recent notices, the terminal's look on
this device, and Settings.

**Terminal is this device's choice and Settings the station's**, so they
are separate sections: changing the panel to light on a phone changes
nothing on the station or on another phone (`shell.py`).
"""

from __future__ import annotations

import flet as ft

from .settings import SettingsEditor
from .text import MONO, MONO_BOLD, TEXT_COLOURS, Look

#: Monitor lines shown (the model keeps more).
MONITOR_SHOWN = 200


class MoreView:
    def __init__(self, app) -> None:
        self.app = app
        self.settings = SettingsEditor(app)
        self.station = ft.Column(tight=True, spacing=4)
        self.monitor = ft.ListView(height=260, auto_scroll=True, spacing=0)
        self.notices = ft.Column(tight=True, spacing=4)
        self.background = ft.SegmentedButton(
            selected=[app.look.background], on_change=self._background_changed,
            segments=[ft.Segment(value="dark", label="Dark", icon=ft.Icons.DARK_MODE),
                      ft.Segment(value="light", label="Light", icon=ft.Icons.LIGHT_MODE)])
        self.swatches = ft.Row(wrap=True, spacing=12, run_spacing=8)
        self.preview = ft.Container(border_radius=8, padding=ft.Padding.all(12))
        self.control = ft.ListView(expand=True, padding=ft.Padding.all(12), controls=[
            ft.Card(content=ft.Container(padding=ft.Padding.all(16), content=self.station)),
            ft.ExpansionTile(title=ft.Text("Monitor"), subtitle=ft.Text(
                "Every frame the station hears or sends", size=12),
                controls=[self.monitor]),
            ft.ExpansionTile(title=ft.Text("Notices"), controls=[self.notices]),
            ft.ExpansionTile(title=ft.Text("Terminal"), subtitle=ft.Text(
                "How session text looks on this device", size=12),
                controls=[ft.Container(padding=ft.Padding.symmetric(horizontal=16, vertical=8),
                                       content=ft.Column(spacing=12, controls=[
                    ft.Text("Background", size=12, color=ft.Colors.OUTLINE), self.background,
                    ft.Text("Text colour", size=12, color=ft.Colors.OUTLINE), self.swatches,
                    self.preview]))]),
            ft.ExpansionTile(title=ft.Text("Settings"), subtitle=ft.Text(
                "The station's settings, checked by the station", size=12),
                controls=[self.settings.column,
                          ft.Row(alignment=ft.MainAxisAlignment.END,
                                 controls=[self.settings.save_button])],
                on_change=self._settings_opened),
        ])
        self._paint()
        self.look_changed()

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

    def look_changed(self) -> None:
        """Show the app's current `Look` as chosen, with a sample."""
        look = self.app.look
        self.background.selected = [look.background]
        self.swatches.controls = [self._swatch(name, look) for name in TEXT_COLOURS]
        self.preview.bgcolor = look.bgcolor
        self.preview.content = ft.Column(spacing=2, controls=[
            ft.Text("W1AWND:W1AW-7} BBS CHAT NODES BYE", font_family=MONO, size=13,
                    color=look.color),
            ft.Text("NODES", font_family=MONO_BOLD, size=13, color=look.outgoing)])

    def _swatch(self, name: str, look: Look) -> ft.Control:
        sample = Look(look.background, name)
        chosen = name == look.text

        async def pick(_e) -> None:
            await self.app.set_look(Look(look.background, name))

        # The swatch and its name are one target: a thumb, not a pointer.
        return ft.Container(on_click=pick, border_radius=8, padding=ft.Padding.all(4),
                            content=ft.Column(tight=True, spacing=4,
                                              horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                              controls=[
            ft.Container(width=40, height=40, border_radius=20, bgcolor=sample.bgcolor,
                         alignment=ft.Alignment.CENTER,
                         border=ft.Border.all(3 if chosen else 1,
                                              ft.Colors.PRIMARY if chosen else ft.Colors.OUTLINE),
                         content=ft.Text("Aa", font_family=MONO, size=13, color=sample.color)),
            ft.Text(name.title(), size=11,
                    weight=ft.FontWeight.BOLD if chosen else None)]))

    async def _background_changed(self, e) -> None:
        selected = list(e.control.selected or [])
        if selected:
            await self.app.set_look(Look(selected[0], self.app.look.text))

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
