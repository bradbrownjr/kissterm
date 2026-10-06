"""A remote client's connection to a station (docs/PROTOCOL.md), with no UI.

**It reconnects on its own and picks up where it left off**: every hello
carries `since`, the last event number seen, so a phone that slept or a
Wi-Fi blip loses nothing the station still has (PROTOCOL.md section 5).
A wrong token (close code 4401) is the one failure it does not retry:
the link was rotated, and only a new one helps.

**A command is a future**: `await command("send_line", key=..., text=...)`
returns the result's value or raises `CommandFailed` with the station's
words. Nothing is retried after a reconnect -- a line sent twice is a line
transmitted twice.

Every message goes to `on_message`, in order; `state.StationState.apply`
is the usual one.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
from collections.abc import Callable
from typing import Any

from .. import __version__

log = logging.getLogger(__name__)

#: Close code for a wrong or rotated token (`serve/server.py`).
UNAUTHORIZED = 4401
#: Seconds between reconnect attempts, growing to the last.
BACKOFF = (1, 2, 5, 10, 30)


class CommandFailed(Exception):
    """The station refused a command; the message is its reason."""


class NotConnected(CommandFailed):
    def __init__(self) -> None:
        super().__init__("Not connected to the station.")


class Connection:
    """One station at `url` (`ws://host:7425/v1`), admitted by `token`.

    `status` is "connecting", "connected", "offline" (retrying) or
    "refused" (the token is wrong: pair again); `on_status` hears each
    change.
    """

    def __init__(self, url: str, token: str, *, on_message: Callable[[dict], None],
                 on_status: Callable[[str], None] | None = None,
                 client: str = f"kissterm-client {__version__}", ssl=None) -> None:
        self.url = url
        self.token = token
        self.on_message = on_message
        self.on_status = on_status
        self.client = client
        self.ssl = ssl
        self.status = "connecting"
        #: The last event number seen; the next hello asks for what follows.
        self.since = 0
        self._ws = None
        self._ids = itertools.count(1)
        self._pending: dict[str, asyncio.Future] = {}
        self._task: asyncio.Task | None = None
        self._closed = False

    # ------------------------------------------------------------------
    def start(self) -> asyncio.Task:
        self._task = asyncio.ensure_future(self._run())
        return self._task

    async def close(self) -> None:
        self._closed = True
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        self._fail_pending()

    async def wait_connected(self, timeout: float = 10.0) -> bool:
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while self.status != "connected":
            if self.status == "refused" or loop.time() > end:
                return False
            await asyncio.sleep(0.02)
        return True

    # ------------------------------------------------------------------
    async def command(self, name: str, /, **args) -> Any:
        if self._ws is None or self.status != "connected":
            raise NotConnected()
        cid = f"c{next(self._ids)}"
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[cid] = future
        try:
            await self._send({"type": "command", "id": cid, "name": name, "args": args})
            return await future
        finally:
            self._pending.pop(cid, None)

    async def answer(self, qid: str, value: Any) -> None:
        """Answer question `qid`; None is cancel."""
        if self._ws is not None:
            await self._send({"type": "answer", "id": qid, "value": value})

    async def _send(self, message: dict) -> None:
        try:
            await self._ws.send(json.dumps(message))
        except Exception as exc:  # noqa: BLE001 - a dropped socket
            raise NotConnected() from exc

    # ------------------------------------------------------------------
    def _set_status(self, status: str) -> None:
        if status != self.status:
            self.status = status
            if self.on_status is not None:
                self.on_status(status)

    def _fail_pending(self) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(NotConnected())

    async def _run(self) -> None:
        from websockets.asyncio.client import connect
        from websockets.exceptions import ConnectionClosed

        for attempt in itertools.count():
            if self._closed:
                return
            self._set_status("connecting" if attempt == 0 else "offline")
            code = None
            try:
                async with connect(self.url, ssl=self.ssl, max_size=2**22) as ws:
                    self._ws = ws
                    await ws.send(json.dumps({"type": "hello", "token": self.token,
                                              "client": self.client, "since": self.since}))
                    async for raw in ws:
                        self._dispatch(json.loads(raw))
                    code = ws.close_code
            except ConnectionClosed as exc:
                code = exc.rcvd.code if exc.rcvd else None
            except (OSError, asyncio.TimeoutError, ValueError) as exc:
                log.info("station %s unreachable: %s", self.url, exc)
            finally:
                self._ws = None
                self._fail_pending()
            if code == UNAUTHORIZED:
                self._set_status("refused")
                return
            if self._closed:
                return
            self._set_status("offline")
            await asyncio.sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)])

    def _dispatch(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "welcome":
            self._set_status("connected")
        elif kind == "event":
            self.since = max(self.since, int(message.get("seq", 0)))
        elif kind == "result":
            future = self._pending.get(str(message.get("id")))
            if future is not None and not future.done():
                if message.get("ok"):
                    future.set_result(message.get("value"))
                else:
                    future.set_exception(CommandFailed(str(message.get("error", ""))))
            return
        try:
            self.on_message(message)
        except Exception:  # noqa: BLE001 - a UI bug must not drop the connection
            log.exception("client could not apply %s", kind)


def parse_link(link: str) -> tuple[str, str]:
    """A pairing link (`http://host:7425/#t=TOKEN`, as the station shows
    it) as the WebSocket URL and the token. Raises ValueError for a link
    with no token."""
    from urllib.parse import urlsplit

    parts = urlsplit(link.strip())
    token = ""
    for item in parts.fragment.lstrip("/").split("&"):
        if item.startswith("t="):
            token = item[2:]
    if not token:
        raise ValueError("the link has no token (#t=...): copy it from Remote pairing")
    scheme = {"https": "wss", "wss": "wss"}.get(parts.scheme, "ws")
    return f"{scheme}://{parts.netloc}/v1", token
