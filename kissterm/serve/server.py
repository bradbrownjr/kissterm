"""`kissterm --serve`: the core over a WebSocket (docs/PROTOCOL.md).

**A client is a remote control, never a second station.** Every command
is one core method (`COMMANDS`), the same one the terminal calls, so a
phone obeys the transmit gate exactly as the keyboard does: a connect
still asks the radio reminder, a line still arms only while connected, a
beacon still refuses while the gate is closed. Nothing here sends on a
transport.

**The token, not a callsign, admits a client** (AGENTS.md "A callsign is
a claim"). It is checked with `hmac.compare_digest` in the first message,
never in the URL -- a path or query string lands in proxy logs -- and a
wrong one closes with 4401 before anything about the station is sent.
Cross-site WebSocket hijacking needs an ambient credential (a cookie) to
ride on; there is none, so no Origin check is needed.

**The bus is synchronous; a socket is not.** Each client has its own
queue and writer task, so a slow phone cannot hold up the station's
event loop; one that falls `QUEUE_LIMIT` behind is dropped and
reconnects with `since`. Events are kept in a ring (`HISTORY`) so a
client that slept, or joined late, replays recent session text.

**Every client is told about every other's actions** through the events
themselves (a line sent shows as `LineSent` on all of them), not by the
server echoing commands.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import dataclasses
import hmac
import json
import logging
import ssl
from http import HTTPStatus
from typing import Any

from .. import __version__
from ..core import events as ev
from ..core import wording
from ..core.operator import Notice, Severity
from . import pairing, wire
from .operator import RemoteOperator

log = logging.getLogger(__name__)

PATH = f"/v{wire.VERSION}"
#: Events kept for replay (PROTOCOL.md section 5).
HISTORY = 2000
#: Messages a client may fall behind by before it is dropped.
QUEUE_LIMIT = 5000
#: Seconds a new connection has to say hello.
HELLO_SECONDS = 10.0
#: Close codes: a wrong token, and a client too far behind to keep.
UNAUTHORIZED = 4401
TOO_SLOW = 4408


class CommandError(Exception):
    """A command the station refused, with the reason to show."""


class _Client:
    def __init__(self, ws, address: str) -> None:
        self.ws = ws
        self.address = address
        self.queue: asyncio.Queue = asyncio.Queue()
        self.writer: asyncio.Task | None = None

    def put(self, message: dict) -> bool:
        if self.queue.qsize() >= QUEUE_LIMIT:
            return False
        self.queue.put_nowait(message)
        return True

    async def write(self) -> None:
        with contextlib.suppress(Exception):
            while True:
                message = await self.queue.get()
                await self.ws.send(json.dumps(message, separators=(",", ":")))


def client_address(ws) -> str:
    """Who connected, for the log: behind a reverse proxy, the first
    `X-Forwarded-For` address (the proxy's own address says nothing)."""
    forwarded = ""
    with contextlib.suppress(Exception):
        forwarded = ws.request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    peer = getattr(ws, "remote_address", None)
    return str(peer[0]) if peer else "?"


def ssl_context(serve) -> ssl.SSLContext | None:
    """TLS from `serve.tls_cert`/`tls_key`, or None (plain ws://)."""
    if not serve.tls_cert:
        return None
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(serve.tls_cert, serve.tls_key)
    return context


class RemoteServer:
    """The WebSocket server for `core`. `operator` is set on the core by
    the caller: this server's `operator` alone (headless) or fanned out
    with the terminal's (`operator.FanOutOperator`)."""

    def __init__(self, core, *, token: str | None = None, standalone: bool = True) -> None:
        self.core = core
        self.token = token if token is not None else pairing.load_token()
        self.operator = RemoteOperator(self, standalone=standalone)
        self.clients: set[_Client] = set()
        self.history: collections.deque = collections.deque(maxlen=HISTORY)
        #: What a `welcome` reports that no core attribute holds.
        self._activity = ""
        self._transport: dict = {}
        self._server = None
        self._unsubscribe = core.events.subscribe(self._on_event)
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        from websockets.asyncio.server import serve

        serve_config = self.core.config.serve
        self._server = await serve(
            self._handle, serve_config.listen, serve_config.port,
            process_request=self._process_request,
            ssl=ssl_context(serve_config),
            max_size=2**20,
        )
        log.info("remote server listening on %s:%s", serve_config.listen, serve_config.port)

    @property
    def port(self) -> int:
        """The port actually bound (a test asks for port 0)."""
        return self._server.sockets[0].getsockname()[1]

    def close(self) -> None:
        """Stop at once, without waiting (the terminal UI's unmount): no
        more events, every open question cancelled, the socket closed."""
        self._unsubscribe()
        self.operator.cancel_all()
        for task in list(self._tasks):
            task.cancel()
        if self._server is not None:
            self._server.close()

    async def stop(self) -> None:
        self.close()
        if self._server is not None:
            with contextlib.suppress(Exception):
                await self._server.wait_closed()
            self._server = None

    def has_clients(self) -> bool:
        return bool(self.clients)

    def rotate(self) -> str:
        """A new token; every client is closed and must pair again."""
        self.token = pairing.rotate_token()
        for client in list(self.clients):
            self._drop(client, UNAUTHORIZED, "token rotated")
        log.info("remote token rotated")
        return self.token

    # ------------------------------------------------------------------
    # Outgoing
    # ------------------------------------------------------------------
    def broadcast(self, message: dict) -> None:
        for client in list(self.clients):
            if not client.put(message):
                self._drop(client, TOO_SLOW, "too far behind")

    def _drop(self, client: _Client, code: int, reason: str) -> None:
        self.clients.discard(client)
        self._spawn(client.ws.close(code, reason))

    def _on_event(self, seq: int, event: ev.Event) -> None:
        if isinstance(event, ev.ActivityChanged):
            self._activity = event.text
        elif isinstance(event, ev.TransportChanged):
            self._transport = {"name": event.name, "tier": event.tier, "detail": event.detail}
        try:
            message = wire.event(self.core, seq, event)
        except Exception:  # noqa: BLE001 - one odd event must not stop the stream
            log.exception("could not serialize %r", event)
            return
        self.history.append(message)
        self.broadcast(message)

    def snapshot(self) -> dict:
        core = self.core
        transport = self._transport or self._transport_now()
        sessions = []
        if core.sessions is not None:
            sessions = [wire.session_summary(core, key) for key in core.sessions.by_key if key]
        return {
            "gate": core.gate.enabled,
            "transport": transport,
            "sessions": sessions,
            "activity": self._activity,
        }

    def _transport_now(self) -> dict:
        core = self.core
        transport = core.transport
        if transport is None:
            return {"name": "", "tier": "", "detail": core.transport_problem or ""}
        tier = "frame" if core.station is not None else "session"
        return {"name": getattr(core.config, "active_transport", "") or "", "tier": tier,
                "detail": transport.info.detail}

    def welcome(self) -> dict:
        return {"type": "welcome", "version": wire.VERSION, "seq": self.core.events.seq,
                "station": {"callsign": self.core.config.mycall or "", "kissterm": __version__},
                "snapshot": self.snapshot()}

    # ------------------------------------------------------------------
    # A connection
    # ------------------------------------------------------------------
    def _process_request(self, connection, request):
        """Anything but `/v1` gets a short page, not a handshake error."""
        if request.path.split("?")[0] != PATH:
            return connection.respond(
                HTTPStatus.OK, f"kissterm {__version__}: remote clients connect to {PATH}.\n")
        return None

    async def _handle(self, ws) -> None:
        address = client_address(ws)
        try:
            hello = json.loads(await asyncio.wait_for(ws.recv(), HELLO_SECONDS))
            token = hello.get("token", "") if isinstance(hello, dict) else ""
        except Exception:  # noqa: BLE001 - a timeout, bad JSON or a binary frame
            hello, token = {}, ""
        if not isinstance(token, str) or not hmac.compare_digest(
                token.encode("utf-8", "replace"), self.token.encode("ascii")):
            log.warning("remote client %s refused: wrong or missing token", address)
            await ws.close(UNAUTHORIZED, "unauthorized")
            return
        client = _Client(ws, address)
        since = hello.get("since", 0)
        since = since if isinstance(since, int) and since >= 0 else 0
        # No await from here to `clients.add`: nothing published in between
        # can fall into a gap between the replay and the live stream.
        client.put(self.welcome())
        for message in self.history:
            if message["seq"] > since:
                client.put({**message, "replay": True})
        for question in self.operator.open_questions():
            client.put(question)
        self.clients.add(client)
        client.writer = asyncio.ensure_future(client.write())
        log.info("remote client %s connected (%s)", address,
                 wire.clean(str(hello.get("client", "")))[:60])
        try:
            async for raw in ws:
                await self._on_message(client, raw)
        except Exception:  # noqa: BLE001 - a dropped socket ends the client, nothing else
            log.debug("remote client %s: connection error", address, exc_info=True)
        finally:
            self.clients.discard(client)
            client.writer.cancel()
            log.info("remote client %s disconnected", address)
            if self.operator.standalone and not self.clients:
                self.operator.cancel_all()

    async def _on_message(self, client: _Client, raw) -> None:
        try:
            message = json.loads(raw)
            kind = message["type"]
        except Exception:  # noqa: BLE001
            client.put({"type": "error", "error": "not a protocol message"})
            return
        if kind == "answer":
            try:
                self.operator.answer(str(message.get("id", "")), message.get("value"))
            except wire.BadAnswer as exc:
                client.put({"type": "error", "id": message.get("id"), "error": str(exc)})
        elif kind == "command":
            cid = message.get("id")
            args = message.get("args") or {}
            self._spawn(self._run(client, cid, str(message.get("name", "")), args))
        else:
            client.put({"type": "error", "error": f"unknown message type {kind!r}"})

    async def _run(self, client: _Client, cid, name: str, args: dict) -> None:
        handler = COMMANDS.get(name)
        if handler is None:
            client.put({"type": "result", "id": cid, "ok": False,
                        "error": f"no command {name!r}"})
            return
        try:
            if not isinstance(args, dict):
                raise CommandError("args must be an object")
            value = await handler(self, **args)
        except CommandError as exc:
            client.put({"type": "result", "id": cid, "ok": False, "error": str(exc)})
        except TypeError as exc:
            client.put({"type": "result", "id": cid, "ok": False, "error": f"bad args: {exc}"})
        except Exception:  # noqa: BLE001 - reported to the client, logged here
            log.exception("remote command %s failed", name)
            client.put({"type": "result", "id": cid, "ok": False,
                        "error": "the station could not do that (see kissterm.log)"})
        else:
            client.put({"type": "result", "id": cid, "ok": True, "value": wire.jsonable(value)})

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # ------------------------------------------------------------------
    # Commands (PROTOCOL.md 4.2): each is one core method
    # ------------------------------------------------------------------
    def _need_sessions(self):
        if self.core.connector is None:
            raise CommandError("No sessions on this station.")
        return self.core.connector

    async def cmd_transmit(self, enabled: bool) -> bool:
        """The master switch. Turning it on from a phone is as deliberate
        as Ctrl+T and as loudly reported, on every screen."""
        if not isinstance(enabled, bool):
            raise CommandError("enabled must be true or false")
        now = self.core.gate.set(enabled)
        if now:
            self.operator_notice("Transmit ENABLED from a remote client. "
                                 "This station can now key the radio.")
        else:
            self.operator_notice("Transmit DISABLED from a remote client. Nothing will be sent.",
                                 Severity.WARNING)
        return now

    def operator_notice(self, text: str, severity: Severity = Severity.INFORMATION) -> None:
        self.core.operator.notice(Notice(text, severity))

    async def cmd_connect(self, target: str = "", entry: str = "", port: int = 0) -> None:
        from ..core.connect import ConnectRequest

        connector = self._need_sessions()
        if entry:
            found = self.core.addressbook.find(entry)
            if found is None:
                raise CommandError(f"{entry} is not in the Address Book.")
            await connector.dial_entry(found)
            return
        if not target:
            raise CommandError("Say what to connect to.")
        if self.core.station is None:
            raise CommandError("No radio transport is open.")
        await connector.connect(ConnectRequest(str(target).strip().upper(), port=int(port)))

    async def cmd_disconnect(self, key: str) -> None:
        await self._need_sessions().disconnect(str(key))

    async def cmd_send_line(self, key: str, text: str) -> bool:
        self._need_sessions()
        return await self.core.sessions.send_line(str(key), str(text))

    async def cmd_aprs_send(self, to: str, text: str) -> str:
        return await self.core.aprs.compose(str(to), str(text))

    async def cmd_aprs_position(self) -> None:
        await self.core.aprs.send_position_now()

    async def cmd_beacon_now(self) -> None:
        await self.core.aprs.beacon_now()

    async def cmd_send_receive(self, folder: str = "", internet: bool = False) -> None:
        await self.core.mail.send_receive(str(folder), internet=bool(internet))

    async def cmd_get_bulletins(self, internet: bool = False) -> None:
        await self.core.mail.get_bulletins(internet=bool(internet))

    async def cmd_get_files(self) -> None:
        await self.core.mail.get_files()

    async def cmd_settings_schema(self) -> list:
        """The schema with each field's current value; a secret's value is
        never sent (an empty field keeps what is saved)."""
        from ..core import settings_schema as schema

        sections = []
        for section in schema.SETTINGS_SCHEMA:
            fields = []
            for spec in section.fields:
                data = wire.jsonable(spec)
                data["help"] = wording.neutral(spec.help)
                try:
                    value = schema.get_value(self.core.config, spec.path)
                except AttributeError:
                    value = None
                data["value"] = None if spec.kind == "secret" else wire.jsonable(value)
                fields.append(data)
            sections.append({"title": section.title, "fields": fields})
        return sections

    async def cmd_settings_save(self, draft: dict, active_transport: str = "") -> dict:
        if not isinstance(draft, dict):
            raise CommandError("draft must be an object")
        core = self.core
        before = getattr(core.config, "active_transport", "")
        result = core.settings.save(draft, str(active_transport))
        if result.errors or not active_transport or (
                active_transport == before and core.transport is not None):
            return dataclasses.asdict(result)
        # A different transport chosen: open it now, as the terminal's
        # Settings Save does (`SettingsPane._reopen_transport`).
        if await core.switch_frame_transport(str(active_transport)) and core.station is not None:
            core.aprs.follow_station()
        return dataclasses.asdict(result)

    async def cmd_addressbook(self) -> list:
        return wire.jsonable(self.core.addressbook.entries)

    async def cmd_addressbook_save(self, entry: dict) -> dict:
        if not isinstance(entry, dict) or not entry.get("target"):
            raise CommandError("an entry needs a target")
        fields = {k: str(v) for k, v in entry.items() if k != "target"}
        saved = self.core.addressbook.upsert(str(entry["target"]), **fields)
        self.core.events.publish(ev.AddressBookChanged())
        return wire.jsonable(saved)

    async def cmd_heard(self) -> list:
        return wire.jsonable(self.core.heard.entries())

    async def cmd_mail_folders(self) -> list:
        return list(self.core.mail.store.folders())

    async def cmd_mail_list(self, folder: str) -> list:
        return [{k: wire.clean(v) if isinstance(v, str) else v
                 for k, v in wire.jsonable(s).items()}
                for s in self.core.mail.store.list(str(folder))]

    async def cmd_mail_read(self, ref: str) -> dict:
        message = wire.jsonable(self.core.mail.store.read(str(ref)))
        return {k: wire.clean(v) if isinstance(v, str) else v for k, v in message.items()}


COMMANDS: dict[str, Any] = {
    name[4:]: getattr(RemoteServer, name)
    for name in dir(RemoteServer) if name.startswith("cmd_")
}
