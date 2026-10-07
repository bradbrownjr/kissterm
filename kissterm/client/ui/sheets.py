"""Confirmations and small forms as bottom sheets, and notices as snack
bars: the shapes every view shares.

**The confirm button is the commitment.** A sheet opened by a swipe or a
tap says what will happen ("Connect to W1AW-7?") and does it only when
its own button is pressed; dragging it away, the scrim, or Cancel does
nothing (DESIGN.md, "A swipe never transmits").
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import flet as ft

Action = Callable[[], Awaitable[None]]

#: A sheet's width: the Material 3 bottom-sheet limit. A narrower screen
#: clamps it, so a sheet is always as wide as the phone; without a width it
#: shrinks to its longest line.
SHEET_WIDTH = 640


def sheet(controls: list[ft.Control], *, scrollable: bool = False,
          on_dismiss=None) -> ft.BottomSheet:
    """The one sheet shape: a drag handle, padded content, full width.

    `scrollable` lets the sheet grow to the screen's height, and its
    content then scrolls: Flet's own `scrollable` only does the first, so
    a form taller than the phone ran off the bottom with its button."""
    return ft.BottomSheet(
        show_drag_handle=True, scrollable=scrollable, on_dismiss=on_dismiss,
        content=ft.Container(
            width=SHEET_WIDTH, padding=ft.Padding.only(left=24, right=24, bottom=24),
            content=ft.Column(tight=True, spacing=12, controls=controls,
                              scroll=ft.ScrollMode.AUTO if scrollable else None,
                              horizontal_alignment=ft.CrossAxisAlignment.STRETCH)))


def confirm(page, title: str, detail: str, go_label: str, on_go: Action, *,
            danger: bool = False) -> ft.BottomSheet:
    """A sheet asking `title`; `on_go` runs only from its own button."""

    async def go(_e) -> None:
        page.pop_dialog()
        await on_go()

    async def cancel(_e) -> None:
        page.pop_dialog()

    go_button = ft.FilledButton(
        content=go_label, on_click=go,
        bgcolor=ft.Colors.ERROR if danger else None,
        color=ft.Colors.ON_ERROR if danger else None)
    shown = sheet([
        ft.Text(title, theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
        *([ft.Text(detail)] if detail else []),
        ft.Row(alignment=ft.MainAxisAlignment.END, controls=[
            ft.TextButton(content="Cancel", on_click=cancel), go_button])])
    page.show_dialog(shown)
    return shown


def choose(page, title: str, detail: str, choices: list[tuple[str, Action]]) -> ft.BottomSheet:
    """A sheet asking `title` with several ways to do it (By radio, By
    Internet); each runs only from its own button, the last one filled
    as the usual choice. Cancel, the scrim or a drag does nothing."""

    def run(on_go: Action):
        async def go(_e) -> None:
            page.pop_dialog()
            await on_go()
        return go

    async def cancel(_e) -> None:
        page.pop_dialog()

    buttons: list[ft.Control] = [ft.TextButton(content="Cancel", on_click=cancel)]
    for i, (label, on_go) in enumerate(choices):
        kind = ft.FilledButton if i == len(choices) - 1 else ft.OutlinedButton
        buttons.append(kind(content=label, on_click=run(on_go)))
    shown = sheet([
        ft.Text(title, theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
        *([ft.Text(detail)] if detail else []),
        ft.Row(alignment=ft.MainAxisAlignment.END, wrap=True, controls=buttons)])
    page.show_dialog(shown)
    return shown


def form(page, title: str, fields: list[ft.Control], go_label: str, on_go: Action,
         detail: str = "") -> ft.BottomSheet:
    """A sheet with `fields` and one button; `on_go` reads the fields."""

    async def go(_e) -> None:
        page.pop_dialog()
        await on_go()

    async def cancel(_e) -> None:
        page.pop_dialog()

    controls: list[ft.Control] = [ft.Text(title, theme_style=ft.TextThemeStyle.TITLE_MEDIUM)]
    if detail:
        controls.append(ft.Text(detail))
    controls += fields
    controls.append(ft.Row(alignment=ft.MainAxisAlignment.END, controls=[
        ft.TextButton(content="Cancel", on_click=cancel),
        ft.FilledButton(content=go_label, on_click=go)]))
    shown = sheet(controls, scrollable=True)
    page.show_dialog(shown)
    return shown


def snack(page, text: str, *, error: bool = False, seconds: float = 4,
          action: str = "", on_action: Action | None = None) -> ft.SnackBar:
    """A floating note; with `action` ("Undo"), a button that runs
    `on_action` while it shows."""

    async def act(_e) -> None:
        if on_action is not None:
            await on_action()

    shown = ft.SnackBar(
        content=ft.Text(text, color=ft.Colors.ON_ERROR if error else None),
        bgcolor=ft.Colors.ERROR if error else None,
        duration=int(max(seconds, 4) * 1000), show_close_icon=True,
        behavior=ft.SnackBarBehavior.FLOATING,
        action=action or None, on_action=act if action else None)
    page.show_dialog(shown)
    return shown
