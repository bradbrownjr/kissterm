"""The web client the station serves at its pairing link (ROADMAP P7a M8).

**The token arrives in the fragment** (`/#t=...`), which a browser never
sends in an HTTP request; with Flet's hash routing it reaches this
Python as the page's route (verified in headless Chromium, 2026-10-05).
It is then kept in the browser's storage for this station, so the app
launched from a home-screen icon (no fragment) still pairs, and the
route is reset so the address bar stops showing it. A rotated token is
refused (4401): the stored one is dropped and the page says to pair
again.

**This Python runs on the station**, one page per browser, and talks to
the station over the loopback with the same protocol as any client --
never a shortcut into the core (`client/AGENTS.md`).

**Everything is served from here** (`no_cdn`): a station on a LAN with
no Internet, the usual emergency case, still serves a working app.
"""

from __future__ import annotations

import ssl
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"
TOKEN_KEY = "kissterm.token"


def available() -> bool:
    import importlib.util

    return all(importlib.util.find_spec(m) is not None for m in ("flet", "flet_web"))


def token_from_route(route: str) -> str:
    """The token in a route of `t=TOKEN` (or `/t=TOKEN`), else ""."""
    for item in (route or "").lstrip("/").split("&"):
        if item.startswith("t=") and len(item) > 2:
            return item[2:]
    return ""


def loopback_url(serve, port: int) -> tuple[str, ssl.SSLContext | None]:
    """How this station's own web pages reach its `/v1`."""
    # A wildcard listen (dual-stack for "::") answers on 127.0.0.1.
    host = serve.listen if serve.listen not in ("", "0.0.0.0", "::") else "127.0.0.1"
    if ":" in host:
        host = f"[{host}]"
    if not serve.tls_cert:
        return f"ws://{host}:{port}/v1", None
    # Our own certificate, over our own loopback: there is nobody in
    # between to check it against.
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return f"wss://{host}:{port}/v1", context


def build(server):
    """The Flet ASGI app for `server` (`serve.server.RemoteServer`)."""
    import flet as ft
    import flet_web.fastapi as flet_fastapi

    from ..connection import Connection
    from ..state import StationState
    from .shell import ClientApp
    from .text import FONTS

    async def main(page: ft.Page) -> None:
        page.fonts = {family: f"/{path}" for family, path in FONTS.items()}
        page.theme = ft.Theme(color_scheme_seed=ft.Colors.INDIGO)
        page.dark_theme = ft.Theme(color_scheme_seed=ft.Colors.INDIGO)
        page.theme_mode = ft.ThemeMode.SYSTEM
        prefs = ft.SharedPreferences()
        token = token_from_route(page.route)
        if token:
            await prefs.set(TOKEN_KEY, token)
            await page.push_route("/")
        else:
            token = await prefs.get(TOKEN_KEY) or ""
        if not token:
            page.add(ft.SafeArea(content=ft.Container(padding=ft.Padding.all(24), content=ft.Text(
                "Open this station's pairing link to use it: on the station, "
                "Session > Remote pairing, or the link kissterm --serve printed."))))
            return
        url, context = loopback_url(server.core.config.serve, server.port)
        state = StationState()
        app: ClientApp | None = None

        async def on_status(status: str) -> None:
            if status == "refused":
                await prefs.remove(TOKEN_KEY)

        def status(text: str) -> None:
            if app is not None:
                app.on_status(text)
            if text == "refused":
                page.run_task(on_status, text)

        conn = Connection(url, token, on_message=state.apply, on_status=status,
                          client=f"kissterm-web {page.client_ip or ''}".strip(), ssl=context)
        app = ClientApp(page, conn, state)
        app.build()
        conn.start()

        async def closed(_e=None) -> None:
            await conn.close()

        page.on_disconnect = closed
        page.on_close = closed

    return flet_fastapi.app(
        main, route_url_strategy=ft.RouteUrlStrategy.HASH, assets_dir=str(ASSETS),
        no_cdn=True, app_name="kissterm", app_short_name="kissterm",
        app_description="Remote control for a kissterm packet radio station")
