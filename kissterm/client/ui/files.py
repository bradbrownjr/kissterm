"""The Files viewer on the phone: a zip's members, Markdown and HTML
formatted, other text (the terminal's `FileViewerScreen`, Enter on a file).

The station reads and prepares the file (`file_open`, `files_view.describe`):
a zip is read in memory and never extracted, HTML becomes Markdown with its
scripts and images dropped, and every byte is sanitized. So nothing here
runs, fetches or follows anything: **links are shown, never followed**
(`auto_follow_links=False`), and the Markdown has no images left to load.

A member of a zip opens one level deeper (a zip inside a zip too); Back goes
up a level, and from the first level to the reader.
"""

from __future__ import annotations

import flet as ft

from .text import MONO


class FileViewer:
    def __init__(self, view, ref: str, on_close) -> None:
        self.view = view
        self.ref = ref
        self.on_close = on_close
        #: Member names from the file down to what is shown.
        self.path: list[str] = []
        self.control = ft.Column(expand=True, spacing=0)

    @property
    def app(self):
        return self.view.app

    async def show(self) -> None:
        data = await self.app.command("file_open", ref=self.ref, member=self.path)
        if not data:
            return
        body = self._body(data)
        fill = []
        if data.get("form"):
            # A PKTNET page is a form kissterm has (the terminal's Enter on it):
            # filled in on its own page and saved to the Outbox.
            async def fill_in(_e) -> None:
                await self.view.fill_in(data["form"])

            fill = [ft.FilledTonalButton(content="Fill in", icon=ft.Icons.EDIT_NOTE,
                                         on_click=fill_in)]
        self.control.controls = [
            ft.Row(controls=[
                ft.IconButton(icon=ft.Icons.ARROW_BACK, tooltip="Back", on_click=self._back),
                ft.Text(data["name"], expand=True, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                        theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                *fill,
                ft.Text(f"{data['size']:,} bytes", size=11, color=ft.Colors.OUTLINE),
                ft.Container(width=8)]),
            ft.Container(expand=True, padding=ft.Padding.all(16), content=body)]
        self.app.page.update()

    def _body(self, data: dict) -> ft.Control:
        kind = data["kind"]
        if kind == "zip":
            return ft.ListView(expand=True, controls=[ft.ListTile(
                title=ft.Text(name, font_family=MONO, size=13),
                trailing=ft.Text(f"{size:,}", size=11, color=ft.Colors.OUTLINE),
                on_click=self._opener(name)) for name, size in data["members"]] or [
                ft.Text("(empty zip)", color=ft.Colors.OUTLINE)])
        if kind in ("markdown", "html"):
            return ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, controls=[ft.Markdown(
                data["markdown"], selectable=True, auto_follow_links=False,
                extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED)])
        if kind == "text":
            return ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, controls=[
                ft.Text(data["text"], font_family=MONO, size=12, selectable=True)])
        return ft.Text(data["problem"] or "Not a text file; the viewer does not open it.")

    def _opener(self, name: str):
        async def open_member(_e) -> None:
            self.path.append(name)
            await self.show()
        return open_member

    async def _back(self, _e) -> None:
        if self.path:
            self.path.pop()
            await self.show()
        else:
            await self.on_close()
