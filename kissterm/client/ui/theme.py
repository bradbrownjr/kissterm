"""The station's theme, drawn by the phone and browser.

`Settings > Appearance > Theme` is one choice for the terminal and every
client (operator, 2026-10-08): the station sends its palette (`theme`
command, `kissterm/themes.py`) and this turns it into a Material colour
scheme, so the bars, sheets, switches and the terminal panel all change
together. The page's own light/dark follows the theme's `dark` flag, not
the browser's, or "dark mode off" would still be dark.

Pure functions (the page is set in `shell.py`), so the mapping is tested
without Flutter.
"""

from __future__ import annotations

import flet as ft

from .colourpicker import parse, to_hex


def _mix(a: str, b: str, amount: float) -> str:
    """`a` moved `amount` (0..1) of the way to `b`."""
    ra, rb = parse(a) or (0, 0, 0), parse(b) or (0, 0, 0)
    return to_hex(*(round(x + (y - x) * amount) for x, y in zip(ra, rb)))


def _luma(colour: str) -> float:
    r, g, b = parse(colour) or (0, 0, 0)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def on(colour: str) -> str:
    """Text on `colour`: black or white, whichever reads."""
    return "#000000" if _luma(colour) > 0.55 else "#FFFFFF"


def scheme(palette: dict) -> ft.ColorScheme:
    """A Material 3 scheme from the station's palette. The page is the
    theme's background, cards and bars its surface and panel, the accent
    its tertiary; the containers and outline are steps between them."""
    dark = bool(palette.get("dark", True))
    background = palette.get("background") or ("#121212" if dark else "#E0E0E0")
    foreground = palette.get("foreground") or on(background)
    primary = palette.get("primary") or "#6750A4"
    secondary = palette.get("secondary") or primary
    accent = palette.get("accent") or secondary
    error = palette.get("error") or "#BA1A1A"
    surface = palette.get("surface") or background
    panel = palette.get("panel") or surface
    # Some themes leave the surface the same as the page; the bars and
    # cards still need to stand off it.
    step = _mix(background, foreground, 0.06)
    low = surface if surface != background else step
    high = panel if panel != background else _mix(background, foreground, 0.12)
    return ft.ColorScheme(
        primary=primary, on_primary=on(primary),
        primary_container=_mix(background, primary, 0.30),
        on_primary_container=foreground,
        secondary=secondary, on_secondary=on(secondary),
        secondary_container=_mix(background, secondary, 0.28),
        on_secondary_container=foreground,
        tertiary=accent, on_tertiary=on(accent),
        tertiary_container=_mix(background, accent, 0.30), on_tertiary_container=foreground,
        error=error, on_error=on(error),
        error_container=_mix(background, error, 0.30), on_error_container=foreground,
        surface=background, on_surface=foreground,
        on_surface_variant=_mix(foreground, background, 0.25),
        surface_dim=background, surface_bright=high,
        surface_container_lowest=_mix(background, "#000000" if dark else "#FFFFFF", 0.25),
        surface_container_low=low, surface_container=low,
        surface_container_high=high, surface_container_highest=_mix(high, foreground, 0.08),
        outline=_mix(background, foreground, 0.55), outline_variant=_mix(background, foreground, 0.25),
        inverse_surface=foreground, on_inverse_surface=background, inverse_primary=primary,
        surface_tint=primary, shadow="#000000", scrim="#000000")


def apply(page: ft.Page, palette: dict) -> None:
    """Draw `page` in `palette`; both scheme slots hold it so the system's
    own preference never picks the other one."""
    theme = ft.Theme(color_scheme=scheme(palette))
    page.theme = theme
    page.dark_theme = theme
    page.bgcolor = palette.get("background") or None
    page.theme_mode = ft.ThemeMode.DARK if palette.get("dark", True) else ft.ThemeMode.LIGHT
