"""A colour picker for the Settings form (Flet has none): a palette to tap,
red, green and blue sliders, and the hex value for anyone who has one.

**It changes the form, never the station.** Use sets the field's draft and
the form's Save sends it, checked by the station like any other value
(`#RRGGBB`, `settings_schema.coerce`). A bad hex typed here never leaves
the sheet.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

import flet as ft

from . import sheets

_HEX = re.compile(r"#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})")

#: A tappable palette: greys, then the hues at a dark, a mid and a light step.
PALETTE = (
    "#000000", "#333333", "#666666", "#999999", "#cccccc", "#ffffff",
    "#7f1d1d", "#b91c1c", "#ef4444", "#7c2d12", "#c2410c", "#f97316",
    "#713f12", "#ca8a04", "#facc15", "#14532d", "#16a34a", "#4ade80",
    "#134e4a", "#0d9488", "#2dd4bf", "#0c4a6e", "#0284c7", "#38bdf8",
    "#1e3a8a", "#3b82f6", "#93c5fd", "#4c1d95", "#8b5cf6", "#c4b5fd",
    "#831843", "#db2777", "#f9a8d4",
)


def parse(text: str) -> tuple[int, int, int] | None:
    """`#RGB`, `#RRGGBB` (the `#` optional) as red, green, blue; else None."""
    match = _HEX.fullmatch((text or "").strip())
    if match is None:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)


def to_hex(red: int, green: int, blue: int) -> str:
    return f"#{red:02X}{green:02X}{blue:02X}"


def swatch(value: str, size: int = 28) -> ft.Container:
    """A small square of `value` (grey when it is not a colour)."""
    rgb = parse(value)
    return ft.Container(width=size, height=size, border_radius=6,
                        bgcolor=to_hex(*rgb) if rgb else ft.Colors.SURFACE_CONTAINER_HIGHEST,
                        border=ft.Border.all(1, ft.Colors.OUTLINE))


def pick(page, label: str, current: str,
         on_use: Callable[[str], Awaitable[None]]) -> ft.BottomSheet:
    """The sheet; `on_use("#RRGGBB")` runs only from its Use button."""
    red, green, blue = parse(current) or (128, 128, 128)
    state = {"rgb": (red, green, blue)}
    preview = ft.Container(height=48, border_radius=8, border=ft.Border.all(1, ft.Colors.OUTLINE))
    hex_field = ft.TextField(label="Hex", dense=True, width=140, max_length=7,
                             text_style=ft.TextStyle(font_family="monospace"))
    sliders: list[ft.Slider] = []

    def show(rgb: tuple[int, int, int], *, skip: ft.Control | None = None) -> None:
        state["rgb"] = rgb
        preview.bgcolor = to_hex(*rgb)
        if skip is not hex_field:
            hex_field.value = to_hex(*rgb)
            hex_field.error = None
        for slider, part in zip(sliders, rgb):
            slider.value = part
        page.update()

    def slider(name: str, index: int) -> ft.Row:
        async def moved(e) -> None:
            rgb = list(state["rgb"])
            rgb[index] = int(e.control.value)
            show((rgb[0], rgb[1], rgb[2]))
        control = ft.Slider(min=0, max=255, divisions=255, value=state["rgb"][index],
                            expand=True, on_change=moved)
        sliders.append(control)
        return ft.Row(controls=[ft.Text(name, width=16), control])

    async def typed(e) -> None:
        rgb = parse(e.control.value or "")
        if rgb is None:
            hex_field.error = "Like #1A1B26"
            page.update()
        else:
            show(rgb, skip=hex_field)

    hex_field.on_change = typed

    def tile(value: str) -> ft.Container:
        async def tapped(_e) -> None:
            show(parse(value))
        return ft.Container(width=34, height=34, border_radius=17, bgcolor=value,
                            border=ft.Border.all(1, ft.Colors.OUTLINE), on_click=tapped,
                            tooltip=value)

    async def use(_e) -> None:
        if hex_field.error:
            return
        page.pop_dialog()
        await on_use(to_hex(*state["rgb"]))

    async def cancel(_e) -> None:
        page.pop_dialog()

    controls: list[ft.Control] = [
        ft.Text(label, theme_style=ft.TextThemeStyle.TITLE_MEDIUM), preview,
        ft.Row(wrap=True, spacing=6, run_spacing=6, controls=[tile(c) for c in PALETTE]),
        slider("R", 0), slider("G", 1), slider("B", 2), hex_field,
        ft.Row(alignment=ft.MainAxisAlignment.END, controls=[
            ft.TextButton(content="Cancel", on_click=cancel),
            ft.FilledButton(content="Use", on_click=use)])]
    shown = sheets.sheet(controls, scrollable=True)
    show(state["rgb"])
    page.show_dialog(shown)
    return shown
