"""`kissterm --client LINK`: the phone's app in a desktop window, paired
by the same link (ROADMAP P7a M8). Needs the `desktop` extra; Flet
fetches its window program the first time.
"""

from __future__ import annotations

from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"
#: What `run` imports beyond kissterm's own dependencies.
EXTRA_MODULES = ("flet", "flet_desktop", "websockets")


def available() -> bool:
    import importlib.util

    return all(importlib.util.find_spec(name) is not None for name in EXTRA_MODULES)


def run(link: str) -> int:
    import flet as ft

    from ..connection import parse_link
    from .shell import run as run_app
    from .text import MONO

    url, token = parse_link(link)

    async def main(page: ft.Page) -> None:
        page.fonts = {MONO: "fonts/0xProto-Regular-NL.ttf"}
        page.theme = ft.Theme(color_scheme_seed=ft.Colors.INDIGO)
        page.dark_theme = ft.Theme(color_scheme_seed=ft.Colors.INDIGO)
        page.theme_mode = ft.ThemeMode.SYSTEM
        await run_app(page, url, token)

    ft.run(main, assets_dir=str(ASSETS))
    return 0
