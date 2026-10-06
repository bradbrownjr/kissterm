"""Stations: the Address Book and who has been heard, as two swipeable
pages. Contacts first: they are what an operator connects to; Heard is
mostly to look at (operator, 2026-10-06).

**Swipe actions open a sheet; they never act** (DESIGN.md, "A swipe
never transmits"). Swiping a row right offers to connect to it, left
offers to add or edit the contact. `on_confirm_dismiss` always answers
"stay" and opens the sheet, so the row springs back and nothing has
happened until the sheet's own button is pressed. Tapping a row offers
the same connect sheet.
"""

from __future__ import annotations

import flet as ft

from . import sheets
from .messages import ago

RIGHT = ft.DismissDirection.START_TO_END
LEFT = ft.DismissDirection.END_TO_START


def swipe_backgrounds() -> tuple[ft.Control, ft.Control]:
    """What shows under a row while it is dragged: connect, and edit."""
    connect = ft.Container(bgcolor=ft.Colors.PRIMARY_CONTAINER, alignment=ft.Alignment.CENTER_LEFT,
                           padding=ft.Padding.only(left=20),
                           content=ft.Row(tight=True, controls=[
                               ft.Icon(ft.Icons.ADD_LINK), ft.Text("Connect")]))
    edit = ft.Container(bgcolor=ft.Colors.SECONDARY_CONTAINER, alignment=ft.Alignment.CENTER_RIGHT,
                        padding=ft.Padding.only(right=20),
                        content=ft.Row(tight=True, controls=[
                            ft.Text("Contact"), ft.Icon(ft.Icons.EDIT)]))
    return connect, edit


class StationsView:
    def __init__(self, app) -> None:
        self.app = app
        self.heard = ft.ListView(expand=True)
        self.contacts = ft.ListView(expand=True)
        self.book: dict[str, dict] = {}
        self.control = ft.Tabs(
            length=2, selected_index=0, expand=True,
            content=ft.Column(expand=True, spacing=0, controls=[
                ft.TabBar(tabs=[ft.Tab(label="Contacts"), ft.Tab(label="Heard")]),
                ft.TabBarView(expand=True, controls=[self.contacts, self.heard])]))
        self._stale = False

    def fab(self):
        return ft.FloatingActionButton(icon=ft.Icons.PERSON_ADD, tooltip="New contact",
                                       on_click=self._new_contact, mini=True)

    async def shown(self) -> None:
        await self.reload()

    def on_state(self, kind: str, data) -> None:
        if kind == "stale" and data in ("heard", "addressbook") and self.app.index == 3:
            # Heard goes stale with every frame: refresh at most once at a time.
            if not self._stale:
                self._stale = True
                self.app.page.run_task(self.reload)

    async def reload(self) -> None:
        self._stale = False
        heard = await self.app.command("heard") or []
        book = await self.app.command("addressbook") or []
        self.book = {e["target"].upper(): e for e in book if e.get("target")}
        self.heard.controls = [self.row(
            h["callsign"],
            f"{ago(h.get('last_heard', 0))}  x{h.get('count', 1)}"
            + (f"  via {h['last_path']}" if h.get("last_path") else ""),
            h["callsign"].upper() in self.book) for h in heard] or [self._empty("Nothing heard yet.")]
        self.contacts.controls = [self.row(
            e["target"], "  ".join(p for p in (e.get("frequency", ""), e.get("note", "")) if p)
            or ("Internet" if e.get("connect_by") else ""), True) for e in book] or [
            self._empty("No contacts. Swipe a heard station left, or add one.")]
        self.app.page.update()

    @staticmethod
    def _empty(text: str) -> ft.Control:
        return ft.Container(padding=ft.Padding.all(24), content=ft.Text(text, color=ft.Colors.OUTLINE))

    def row(self, callsign: str, detail: str, known: bool) -> ft.Dismissible:
        connect_bg, edit_bg = swipe_backgrounds()
        return ft.Dismissible(
            key=f"row-{callsign}", data=callsign,
            background=connect_bg, secondary_background=edit_bg,
            dismiss_direction=ft.DismissDirection.HORIZONTAL,
            on_confirm_dismiss=self.on_swipe,
            content=ft.ListTile(
                leading=ft.Icon(ft.Icons.CONTACTS if known else ft.Icons.CELL_TOWER),
                title=ft.Text(callsign), subtitle=ft.Text(detail, size=12),
                on_click=self._tapped(callsign)))

    async def on_swipe(self, e) -> None:
        """A swipe: the row stays, and a sheet asks (module docstring)."""
        await e.control.confirm_dismiss(False)
        callsign = e.control.data
        if e.direction == RIGHT:
            self.ask_connect(callsign)
        else:
            self.edit_contact(callsign)

    def _tapped(self, callsign: str):
        async def handler(_e) -> None:
            self.ask_connect(callsign)
        return handler

    def ask_connect(self, callsign: str) -> None:
        entry = self.book.get(callsign.upper())

        async def go() -> None:
            if entry is not None:
                self.app.start_connect(entry=entry["target"])
            else:
                self.app.start_connect(target=callsign)

        detail = " ".join(p for p in ((entry or {}).get("frequency", ""),
                                       (entry or {}).get("note", "")) if p)
        sheets.confirm(self.app.page, f"Connect to {callsign}?",
                       detail or "The station asks first if its contact has a reminder.",
                       "Connect", go)

    def edit_contact(self, callsign: str) -> None:
        entry = self.book.get(callsign.upper(), {})
        target = ft.TextField(label="Station", value=entry.get("target", callsign),
                              capitalization=ft.TextCapitalization.CHARACTERS)
        frequency = ft.TextField(label="Frequency", value=entry.get("frequency", ""))
        hops = ft.TextField(label="Node hops", value=entry.get("hops", ""),
                            hint_text="e.g. N1QFY, AB1KI-15")
        note = ft.TextField(label="Note", value=entry.get("note", ""))

        async def go() -> None:
            name = (target.value or "").strip().upper()
            if not name:
                return
            saved = await self.app.command("addressbook_save", entry={
                "target": name, "original_target": entry.get("target", ""),
                "frequency": frequency.value or "", "hops": hops.value or "",
                "note": note.value or ""})
            if saved:
                sheets.snack(self.app.page, f"Saved {name}.")
                await self.reload()

        sheets.form(self.app.page, "Edit contact" if entry else "Add contact",
                    [target, frequency, hops, note], "Save", go)

    async def _new_contact(self, _e) -> None:
        self.edit_contact("")
