"""APRS templates: what to say to a gateway, and the operator's saved
messages (the terminal's Ctrl+R picker, `AprsServiceScreen`), as a sheet over
a conversation. Everything is the station's (`aprs_templates`,
`aprs_template_save`, `aprs_template_forget`).

**A pick fills the compose box and never sends** (AGENTS.md: suggestions
fill the input); Send in the thread is the commitment. The shipped lines
show how far to trust them (`confidence`: some are "recalled", not
confirmed against the service's source) and the service's note and source.
"""

from __future__ import annotations

import flet as ft

from . import sheets
from .text import MONO


def _matches(needle: str, *parts: str) -> bool:
    needle = needle.strip().lower()
    return not needle or any(needle in part.lower() for part in parts)


class TemplatesSheet:
    def __init__(self, view, callsign: str, data: dict) -> None:
        self.view = view
        self.callsign = callsign
        self.data = data
        self.rows = ft.Column(tight=True, spacing=0)
        self.search = ft.TextField(label="Search", dense=True, on_change=self._search)

    def show(self) -> None:
        service = self.data.get("service")
        head: list[ft.Control] = [ft.Text(
            f"{service['name']} ({service['callsign']})" if service
            else f"Messages for {self.callsign or 'this recipient'}",
            theme_style=ft.TextThemeStyle.TITLE_MEDIUM)]
        if service:
            note = [service.get("note", "")]
            if service.get("region"):
                note.append(f"Coverage: {service['region']}.")
            if any(c["confidence"] == "recalled" for c in service["commands"]):
                note.append("Lines marked recalled were not confirmed against the "
                            "source; check one before spending airtime on it.")
            checked = f" (checked {service['checked']})" if service.get("checked") else ""
            note.append(f"Source: {service['source']}{checked}")
            head.append(ft.Text(" ".join(n for n in note if n), size=12, color=ft.Colors.OUTLINE))
        else:
            head.append(ft.Text("Not one of the gateway services kissterm ships, so only "
                                "your own saved messages are here.", size=12,
                                color=ft.Colors.OUTLINE))
        self._paint("")
        self.view.app.page.show_dialog(sheets.sheet([
            *head, self.search, self.rows,
            ft.Text("Choosing one puts it in the message box. Nothing is sent until you "
                    "press Send.", size=12),
            ft.Row(alignment=ft.MainAxisAlignment.END, controls=[
                ft.TextButton(content="Close", on_click=self._close),
                ft.OutlinedButton(content="New", on_click=self._new)])], scrollable=True))

    async def _close(self, _e=None) -> None:
        self.view.app.page.pop_dialog()

    async def _search(self, e) -> None:
        self._paint(e.control.value or "")
        self.view.app.page.update()

    def _paint(self, needle: str) -> None:
        rows: list[ft.Control] = []
        for saved in self.data.get("saved", []):
            if _matches(needle, saved["name"], saved["text"]):
                rows.append(self._saved_row(saved))
        service = self.data.get("service")
        for command in (service["commands"] if service else []):
            if _matches(needle, command["name"], command["summary"], command["text"]):
                rows.append(ft.ListTile(
                    title=ft.Text(command["name"]),
                    subtitle=ft.Text(f"{command['text']}\n{command['summary']}".strip(),
                                     font_family=MONO, size=11),
                    trailing=ft.Text(command["confidence"], size=11, color=ft.Colors.OUTLINE),
                    on_click=self._picker(command["text"])))
        if not rows:
            rows.append(ft.Text("Nothing matches.", color=ft.Colors.OUTLINE))
        self.rows.controls = rows

    def _saved_row(self, saved: dict) -> ft.Control:
        return ft.ListTile(
            title=ft.Text(saved["name"]),
            subtitle=ft.Text(saved["text"], font_family=MONO, size=11),
            trailing=ft.Row(tight=True, spacing=0, controls=[
                ft.IconButton(icon=ft.Icons.EDIT_OUTLINED, tooltip="Edit",
                              on_click=self._editor(saved)),
                ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip="Forget",
                              on_click=self._forgetter(saved))]),
            on_click=self._picker(saved["text"]))

    def _picker(self, text: str):
        async def pick(_e) -> None:
            self.view.app.page.pop_dialog()
            self.view.compose.fill(text)
            self.view.app.page.update()
        return pick

    def _editor(self, saved: dict):
        async def edit(_e) -> None:
            self.view.app.page.pop_dialog()
            self.edit(saved)
        return edit

    def _forgetter(self, saved: dict):
        async def forget(_e) -> None:
            self.view.app.page.pop_dialog()
            await self.view.app.command("aprs_template_forget", **saved)
            await self.view.open_templates()
        return forget

    async def _new(self, _e) -> None:
        self.view.app.page.pop_dialog()
        self.edit(None)

    def edit(self, saved: dict | None) -> None:
        """The form for a saved message, new or edited. It belongs to the
        service shown (the terminal's default) or, with none, to every
        recipient."""
        service = self.data.get("service")
        name = ft.TextField(label="Name", value=saved["name"] if saved else "")
        text = ft.TextField(label="Message", value=saved["text"] if saved else "",
                            multiline=True)
        problem = ft.Text("", color=ft.Colors.ERROR)
        gateway = saved["gateway"] if saved else (service["id"] if service else "")

        async def go() -> None:
            result = await self.view.app.command(
                "aprs_template_save", name=name.value or "", text=text.value or "",
                gateway=gateway, **({"old": saved} if saved else {}))
            if result and result.get("problems"):
                sheets.snack(self.view.app.page, result["problems"][0], error=True)
            await self.view.open_templates()

        sheets.form(self.view.app.page, "Saved message", [name, text, problem], "Save", go)
