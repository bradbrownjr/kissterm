"""The APRS object form on the phone: name, place, symbol, comment and
where it goes, sent as one object report (the terminal's APRS > Object;
operator, 2026-10-06: "How do I place an object on the map?").

Opened by **Object** beside Send position (here), a **long press** on the
map (that spot), or **Move** on one of this station's objects (its name,
symbol and comment kept, the place long-pressed). What it starts with and
every rule are the station's (`aprs_object_start`, `aprs_object`,
`Aprs.object_start` and `core.aprs.object_problems`); this page collects
the fields and shows the station's problems.

**Send asks first**, as every transmission from the phone does: it turns
transmit on and sends one report. Nothing repeats it: an object stays on
other stations' maps only as long as they keep it. Kill (on the map's
panel) sends the same report marked killed.
"""

from __future__ import annotations

import flet as ft

from . import sheets


class ObjectForm:
    """One object being written, as a page of `MessagesView`."""

    def __init__(self, view, start: dict, *, moving: bool = False) -> None:
        self.view = view
        self.app = view.app
        self.moving = moving
        self.name = ft.TextField(label="Name", hint_text="1-9 characters, e.g. SHELTER",
                                 value=start.get("name", ""), dense=True, max_length=9,
                                 read_only=moving,
                                 capitalization=ft.TextCapitalization.CHARACTERS)
        self.latitude = ft.TextField(label="Latitude", value=f"{start.get('latitude', 0):.5f}",
                                     dense=True, expand=True,
                                     keyboard_type=ft.KeyboardType.NUMBER)
        self.longitude = ft.TextField(label="Longitude",
                                      value=f"{start.get('longitude', 0):.5f}", dense=True,
                                      expand=True, keyboard_type=ft.KeyboardType.NUMBER)
        self.symbol = ft.Dropdown(
            label="Symbol", value=start.get("symbol") or None, dense=True, expand=True,
            enable_filter=True, editable=True, menu_height=320,
            options=[ft.DropdownOption(key=key, text=f"{description} ({key})")
                     for key, description in start.get("symbols") or []])
        self.comment = ft.TextField(label="Comment", hint_text="optional",
                                    value=start.get("comment", ""), dense=True, max_length=43)
        self.scope = ft.Dropdown(
            label="Goes to", value="network", dense=True, expand=True,
            options=[ft.DropdownOption(key=key, text=label)
                     for key, label in start.get("scopes") or [["network", "Normal APRS network"]]])
        self.problems = ft.Text("", color=ft.Colors.ERROR)

    def control(self) -> ft.Control:
        heading = f"Move {self.name.value}" if self.moving else "APRS object"
        return ft.Column(expand=True, spacing=0, controls=[
            ft.Container(padding=ft.Padding.only(right=12), content=ft.Row(controls=[
                ft.IconButton(icon=ft.Icons.CLOSE, tooltip="Close", on_click=self.close),
                ft.Text(heading, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                        theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                ft.FilledButton(content="Send", on_click=self.send)])),
            ft.Container(expand=True, padding=ft.Padding.symmetric(horizontal=16, vertical=8),
                         content=ft.Column(
                             expand=True, spacing=10, scroll=ft.ScrollMode.AUTO,
                             horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=[
                                 # Room for the first field's floating label.
                                 ft.Container(height=6),
                                 self.name,
                                 ft.Row(controls=[self.latitude, self.longitude]),
                                 ft.Row(controls=[self.symbol]),
                                 self.comment,
                                 ft.Row(controls=[self.scope]),
                                 ft.Text("Send turns transmit on and sends one object report. "
                                         "Nothing repeats it.", size=12,
                                         color=ft.Colors.OUTLINE),
                                 self.problems]))])

    def values(self) -> dict:
        return {"name": (self.name.value or "").strip().upper(), "alive": True,
                "latitude": self.latitude.value, "longitude": self.longitude.value,
                "symbol": self.symbol.value or "", "comment": (self.comment.value or "").strip(),
                "scope": self.scope.value or "network"}

    async def send(self, _e) -> None:
        values = self.values()
        try:
            values["latitude"] = float(str(values["latitude"]).strip())
            values["longitude"] = float(str(values["longitude"]).strip())
        except ValueError:
            self.problems.value = "Latitude and longitude must be decimal numbers."
            self.app.page.update()
            return
        name = values["name"] or "this object"

        async def go() -> None:
            result = await self.app.command("aprs_object", **values)
            if not result:
                return
            if result.get("problems"):
                self.problems.value = "\n".join(result["problems"])
                self.app.page.update()
                return
            if result.get("sent"):
                sheets.snack(self.app.page, f"Object {name} sent.")
                await self.view.close_object_form()

        sheets.confirm(self.app.page, f"Send object {name}?",
                       "Turns transmit on and sends one APRS object report from the "
                       "station.", "Send", go)

    async def close(self, _e) -> None:
        await self.view.close_object_form()


async def kill(app, point: dict, done) -> None:
    """Kill one of this station's objects, after asking: the same report,
    marked killed, at its last place."""

    async def go() -> None:
        result = await app.command(
            "aprs_object", name=point["name"], alive=False, latitude=point["lat"],
            longitude=point["lon"], symbol=point.get("symbol") or "/.",
            comment=point.get("comment", ""), scope="network")
        if result and result.get("sent"):
            sheets.snack(app.page, f"Object {point['name']} killed.")
            await done()
        elif result and result.get("problems"):
            sheets.snack(app.page, "\n".join(result["problems"]), error=True)

    sheets.confirm(app.page, f"Kill object {point['name']}?",
                   "Turns transmit on and sends a report that it is gone; stations "
                   "that hear it take it off their maps.", "Kill", go, danger=True)
