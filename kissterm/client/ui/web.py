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

**A dropped page is forgotten, never resumed.** Flet keeps a session
for an hour after the browser's socket drops (a phone asleep, a tab in
the background) and the browser rejoins it on waking, even across a
reload. Under Flet 1.0.3 a rejoined page does not redraw: taps reach
this Python and its updates go out, but the screen stays as it was. Our
side had also closed the station connection on the drop, so the page
came back looking normal with nothing behind it (operator, 2026-10-06:
"I returned to the web app and it reloaded and is unable to connect to
the server"; reproduced the same day by closing Flet's socket under
headless Chromium). A fresh session after the same drop works. So the
drop closes the station connection and deletes the session (`forget`);
the returning browser finds none, starts a new one from the stored
token, and the station replays its state to it.

**The browser's storage can fail to answer.** Flet reads it by a round
trip to the page, which times out after 10 s; a phone returning to a
reloaded, half-awake tab is where that happens, and it once left a dead
page with nothing to press (operator, 2026-10-06: "I returned to the web
app and it reloaded and is unable to connect to the server"; the log had
`TimeoutException ... SharedPreferences(9).get`). So the read is retried,
then the page says what happened and offers Try again, and tries again by
itself when the tab comes back to the front. Saving a token from the
link is best effort: the session goes ahead with the token in hand.

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


async def read_token(prefs, attempts: int = 2) -> str | None:
    """The token this browser kept, "" if none, None if it never answered."""
    for _ in range(attempts):
        try:
            return await prefs.get(TOKEN_KEY) or ""
        except Exception:
            continue
    return None


def session_key(manager, session) -> str | None:
    """`session`'s key in Flet's session registry, None if not there.

    Flet keys it by page name, session id and a hash of the client, a
    private formula; finding it by identity in the (also private) registry
    does not depend on the formula. `test_client_ui` fails if a Flet
    upgrade renames the registry."""
    sessions = getattr(manager, "_FletAppManager__sessions", None) or {}
    return next((key for key, value in sessions.items() if value is session), None)


async def forget(session) -> None:
    """Drop a session whose browser went away, so the browser's return
    starts a new one rather than rejoining this (module docstring)."""
    from flet_web.fastapi.flet_app_manager import app_manager

    key = session_key(app_manager, session)
    if key is not None:
        await app_manager.delete_session(key)


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
            try:
                await prefs.set(TOKEN_KEY, token)
            except Exception:
                pass
            await page.push_route("/")
            await start(page, prefs, token)
        else:
            await resume(page, prefs)

    async def resume(page, prefs) -> None:
        """Start from the stored token, or say why not and offer to retry."""
        token = await read_token(prefs)
        if token:
            await start(page, prefs, token)
            return

        async def again(_e=None) -> None:
            page.on_app_lifecycle_state_change = None
            page.controls.clear()
            page.update()
            await resume(page, prefs)

        async def back_in_front(e) -> None:
            if e.state in (ft.AppLifecycleState.SHOW, ft.AppLifecycleState.RESUME):
                await again()

        if token is None:
            text = ("This browser did not answer when asked for its pairing with the "
                    "station. The station is fine; try again.")
            page.on_app_lifecycle_state_change = back_in_front
            more = [ft.FilledButton("Try again", icon=ft.Icons.REFRESH, on_click=again)]
        else:
            text = ("Open this station's pairing link to use it: on the station, "
                    "Session > Remote pairing, or the link kissterm --serve printed.")
            more = []
        page.add(ft.SafeArea(content=ft.Container(padding=ft.Padding.all(24), content=ft.Column(
            tight=True, spacing=16, controls=[ft.Text(text), *more]))))

    async def start(page, prefs, token: str) -> None:
        url, context = loopback_url(server.core.config.serve, server.port)
        state = StationState()
        app: ClientApp | None = None

        async def on_status(status: str) -> None:
            if status == "refused":
                try:
                    await prefs.remove(TOKEN_KEY)
                except Exception:
                    pass

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

        async def dropped(_e=None) -> None:
            await conn.close()
            await forget(page.session)

        page.on_disconnect = dropped
        page.on_close = closed

    return flet_fastapi.app(
        main, route_url_strategy=ft.RouteUrlStrategy.HASH, assets_dir=str(ASSETS),
        no_cdn=True, app_name="kissterm", app_short_name="kissterm",
        app_description="Remote control for a kissterm packet radio station")
