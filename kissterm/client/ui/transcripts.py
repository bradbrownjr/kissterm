"""Transcripts on the phone: past sessions, found and read (the terminal's
Session > Transcripts; `Sessions.transcripts`, `read_transcript`).

Read-only, as at the terminal: a session record is something to consult.
The station lists them newest first and filters by callsign or by what
was said; a transcript reads in the terminal panel's own look, its last
256 KB if it is longer. Nothing here transmits.
"""

from __future__ import annotations

import flet as ft

from .text import MONO


def size_text(size: int) -> str:
    return f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} B"


class TranscriptsSection:
    """The Transcripts fold in More, and the page one opens to."""

    def __init__(self, app, show) -> None:
        #: `show(control | None)`: put a page over More, or take it away.
        self.app = app
        self.show = show
        self.search = ft.TextField(dense=True, hint_text="Callsign or words said",
                                   prefix_icon=ft.Icons.SEARCH, on_submit=self._searched)
        self.list = ft.Column(tight=True, spacing=0)
        self.tile = ft.ExpansionTile(
            title=ft.Text("Transcripts"),
            subtitle=ft.Text("Past sessions, newest first", size=12),
            on_change=self._opened,
            controls=[ft.Container(padding=ft.Padding.symmetric(horizontal=16, vertical=8),
                                   content=ft.Column(
                                       tight=True, spacing=8,
                                       horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                                       controls=[self.search, self.list]))])

    async def _opened(self, e) -> None:
        if getattr(e.control, "expanded", True):
            await self.load()

    async def _searched(self, _e) -> None:
        await self.load()

    async def load(self) -> None:
        found = await self.app.command("transcripts", needle=self.search.value or "") or []
        self.list.controls = [ft.ListTile(
            dense=True, title=ft.Text(t.get("peer") or t.get("name", "")),
            subtitle=ft.Text(f"{t.get('started') or ''}  {size_text(t.get('size', 0))}".strip(),
                             size=12),
            on_click=self._opener(t.get("name", ""))) for t in found] or [
            ft.Text("No transcripts." if not self.search.value else "Nothing matches.",
                    color=ft.Colors.OUTLINE)]
        self.app.page.update()

    def _opener(self, name: str):
        async def handler(_e) -> None:
            await self.open(name)
        return handler

    async def open(self, name: str) -> None:
        text = await self.app.command("transcript_read", file=name)
        if text is None:
            return
        look = self.app.look

        async def back(_e) -> None:
            self.show(None)

        self.show(ft.Column(expand=True, spacing=0, controls=[
            ft.Row(controls=[ft.IconButton(icon=ft.Icons.ARROW_BACK, tooltip="Back",
                                           on_click=back),
                             ft.Text(name, expand=True, max_lines=1,
                                     overflow=ft.TextOverflow.ELLIPSIS,
                                     theme_style=ft.TextThemeStyle.TITLE_SMALL)]),
            ft.Container(expand=True, bgcolor=look.bgcolor, padding=ft.Padding.all(12),
                         content=ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, controls=[
                             ft.Text(text, font_family=MONO, size=13, color=look.color,
                                     selectable=True)]))]))
