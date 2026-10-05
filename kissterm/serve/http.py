"""The HTTP side of the remote server: one port for the WebSocket API
(`/v1`) and, with the `web` extra, the web client at `/` (ROADMAP P7a M8).

**One port, because the pairing link is the whole setup** (operator,
2026-10-05: the station serves the client). A phone that opens
`http://station:7425/#t=...` gets the app from the same place it then
connects to, and a reverse proxy (Caddy) has one upstream to forward.
That needs an ASGI server rather than a bare WebSocket library, so the
listener is uvicorn with Starlette routes; the protocol logic in
`server.py` sees only `Socket`, the small surface it used before.

**uvicorn runs inside kissterm's loop**, never its own: `Server.serve`
is a task on the station's loop, with uvicorn's signal capture turned
off (Ctrl+C belongs to kissterm, and inside the terminal UI there is no
signal to take) and the socket bound here first, so a port in use is an
`OSError` to report rather than uvicorn's `sys.exit`. Access logs are
off: a path is all they would add, and the token never travels in one.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket

log = logging.getLogger(__name__)

#: The largest message a client may send (a settings draft is the biggest).
MAX_MESSAGE = 2**20


class Socket:
    """A Starlette `WebSocket` with the methods `RemoteServer` uses:
    `recv`, `send`, `close`, async iteration, `request.headers`,
    `remote_address`."""

    def __init__(self, ws) -> None:
        self._ws = ws
        self.request = ws  # `.headers`, as the websockets library's had
        client = ws.client
        self.remote_address = (client.host, client.port) if client else None

    async def recv(self) -> str:
        from starlette.websockets import WebSocketDisconnect

        message = await self._ws.receive()
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))
        if message.get("text") is None:
            raise ValueError("binary frame")
        return message["text"]

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        from starlette.websockets import WebSocketDisconnect

        try:
            return await self.recv()
        except WebSocketDisconnect:
            raise StopAsyncIteration from None

    async def send(self, text: str) -> None:
        await self._ws.send_text(text)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        with contextlib.suppress(Exception):
            await self._ws.close(code, reason)


def build_app(server, version: str, web_app=None):
    """The ASGI app: `/v1` for `server` (`RemoteServer`), then the web
    client when there is one, else a line saying where clients connect."""
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Mount, Route, WebSocketRoute

    async def api(ws) -> None:
        await ws.accept()
        await server.handle(Socket(ws))

    async def page(request):
        return PlainTextResponse(
            f"kissterm {version}: remote clients connect to {server.PATH}. "
            "Install kissterm[web] on the station for the web client.\n")

    routes = [WebSocketRoute(server.PATH, api)]
    if web_app is not None:
        routes.append(Mount("/", app=web_app))
    else:
        routes.append(Route("/{path:path}", page))
    return Starlette(routes=routes)


def bind(listen: str, port: int) -> socket.socket:
    """The listening socket, bound here so a port in use is an OSError."""
    family = socket.AF_INET6 if ":" in listen else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((listen, port))
    except OSError:
        sock.close()
        raise
    sock.set_inheritable(True)
    return sock


class Listener:
    """uvicorn serving `app` on one socket, inside the running loop."""

    def __init__(self, app, sock: socket.socket, *, tls_cert: str = "", tls_key: str = "") -> None:
        import uvicorn

        class _Server(uvicorn.Server):
            def capture_signals(self):  # noqa: D102 - see the module docstring
                return contextlib.nullcontext()

        config = uvicorn.Config(
            app, log_level="warning", access_log=False, lifespan="off",
            server_header=False, proxy_headers=False, ws_max_size=MAX_MESSAGE,
            ssl_certfile=tls_cert or None, ssl_keyfile=tls_key or None,
        )
        self._sock = sock
        self.port = sock.getsockname()[1]
        self._server = _Server(config)
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.ensure_future(self._server.serve(sockets=[self._sock]))
        while not self._server.started:
            if self._task.done():
                # A bad certificate surfaces here, as uvicorn loads it.
                self._task.result()
                raise OSError("the remote server stopped while starting")
            await asyncio.sleep(0.01)

    def close(self) -> None:
        self._server.should_exit = True

    async def stop(self) -> None:
        self.close()
        if self._task is not None:
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(self._task, 5)
        with contextlib.suppress(OSError):
            self._sock.close()
