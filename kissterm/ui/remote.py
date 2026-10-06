"""The remote-control server inside the terminal UI (ROADMAP P7a M7).

With Settings > Remote > Remote control on, the station's own screen and
any phone or browser share one core (`kissterm/serve/`): every notice goes
to both, and a question goes to both and the first answer wins
(`serve.operator.FanOutOperator`). Off, the core's operator is the
terminal alone, exactly as before.

**Started and stopped only from Settings** (`reconcile`, run after every
save and at launch), restarted when the port, interface or certificate
changes; a Public URL change needs no restart, it only changes the link.
A server that cannot start (the port taken, a bad certificate, the
`serve` extra missing) is one notice, and the terminal carries on.

**The web app is imported off the event loop** (`_preload`). Flet and its
FastAPI host take seconds to import (5.6 s cold on the dev machine), and
importing them inside `start` froze the whole terminal from Save until the
"Remote control on" notice (operator, 2026-10-06: "locked up the whole
program"). A thread imports them while the screen keeps drawing.

**Turned on from Settings, the pairing screen opens** with its QR code, the
one thing a phone needs next (operator, 2026-10-06: "there is no QR
code"). Not when it was already on at launch: nothing changed then.
"""

from __future__ import annotations

import asyncio
import logging

from ..core.operator import Notice, Severity

log = logging.getLogger(__name__)

#: What a client needs to install for the server and the QR code.
EXTRA_HINT = "Remote control needs the serve extra: pip install 'kissterm[serve]'."


def _preload() -> None:
    """Import the server and the web app, in a thread (module docstring)."""
    import importlib

    from ..client.ui import web
    from ..serve import http, server  # noqa: F401 - imported for their cost

    # uvicorn, and the protocol modules it imports by name as it starts.
    for name in ("uvicorn", "uvicorn.protocols.http.auto",
                 "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.off",
                 "uvicorn.loops.auto"):
        try:
            importlib.import_module(name)
        except ImportError:
            pass

    if web.available():
        import flet  # noqa: F401
        import flet_web.fastapi  # noqa: F401

        from ..client.ui import shell  # noqa: F401 - what `web.build` imports


def serve_available() -> bool:
    from ..serve import available

    return available()


class RemoteControl:
    """The server's lifecycle for `app` (a `KissTermApp`)."""

    def __init__(self, app) -> None:
        self.app = app
        self.server = None
        #: The terminal's own operator, put back when the server stops.
        self.local = app.core.operator
        #: The settings the running server was started with.
        self._running_with: tuple | None = None
        self._told_missing = False
        #: False until the first `reconcile` (launch) has run.
        self._settled = False

    @property
    def core(self):
        return self.app.core

    @property
    def clients(self) -> int:
        return len(self.server.clients) if self.server is not None else 0

    def wanted(self) -> tuple | None:
        serve = self.core.config.serve
        if not serve.enabled:
            return None
        return (serve.port, serve.listen, serve.tls_cert, serve.tls_key)

    async def reconcile(self) -> None:
        """Make the server match Settings: start, stop or restart it."""
        launch, self._settled = not self._settled, True
        want = self.wanted()
        if want == self._running_with:
            return
        was_on = self._running_with is not None
        await self.stop()
        if want is None:
            return
        if not serve_available():
            if not self._told_missing:
                self._told_missing = True
                self.local.notice(Notice(EXTRA_HINT, Severity.WARNING))
            return
        if not launch:
            self.local.notice(Notice("Starting remote control..."))
        await asyncio.to_thread(_preload)
        await self.start(want)
        if self.server is not None and not launch and not was_on:
            self.app.show_pairing()

    async def start(self, want: tuple) -> None:
        from ..serve.operator import FanOutOperator
        from ..serve.server import RemoteServer

        server = RemoteServer(self.core, standalone=False)
        self.core.operator = FanOutOperator(self.local, server.operator)
        try:
            await server.start()
        except Exception as exc:  # noqa: BLE001 - a port in use, a bad certificate
            log.exception("remote server did not start")
            self.core.operator = self.local
            await server.stop()
            port, listen = want[0], want[1]
            self.local.notice(Notice(
                f"Remote control did not start on {listen}:{port}: {exc}", Severity.ERROR))
            return
        self.server = server
        self._running_with = want
        self.local.notice(Notice(f"Remote control on, port {server.port}."))

    async def stop(self) -> None:
        server, self.server, self._running_with = self.server, None, None
        if server is None:
            return
        self.core.operator = self.local
        await server.stop()

    def close_now(self) -> None:
        """At unmount, where nothing can be awaited."""
        if self.server is not None:
            self.server.close()
            self.core.operator = self.local
            self.server = self._running_with = None

    def rotate(self) -> str:
        """A new token: running, every client is dropped too."""
        from ..serve import pairing

        if self.server is not None:
            return self.server.rotate()
        return pairing.rotate_token()

    def token(self) -> str:
        from ..serve import pairing

        if self.server is not None:
            return self.server.token
        return pairing.load_token()
