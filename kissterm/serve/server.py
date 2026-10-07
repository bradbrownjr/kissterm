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


#: Contact fields a client may set (`AddressBook.upsert`'s, besides the
#: Internet ones).
EDITABLE_CONTACT_FIELDS = ("script", "hops", "credential", "script_name", "frequency",
                           "connection_type", "paclen", "window", "note")


def redact_entry(entry: dict) -> dict:
    """A contact as a client sees it: everything but the script's text."""
    entry = dict(entry)
    entry["has_script"] = bool(entry.pop("script", ""))
    return entry


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


class RemoteServer:
    """The WebSocket server for `core`. `operator` is set on the core by
    the caller: this server's `operator` alone (headless) or fanned out
    with the terminal's (`operator.FanOutOperator`). `web`: serve the web
    client at `/` when the `web` extra is installed (`client/ui/web.py`)."""

    PATH = PATH

    def __init__(self, core, *, token: str | None = None, standalone: bool = True,
                 web: bool = True) -> None:
        self.core = core
        self.web = web
        self.token = token if token is not None else pairing.load_token()
        #: Whether a client has signed in with this token (`pairing.mark_paired`).
        self.paired = pairing.has_paired(self.token)
        self.operator = RemoteOperator(self, standalone=standalone)
        self.clients: set[_Client] = set()
        self.history: collections.deque = collections.deque(maxlen=HISTORY)
        #: What a `welcome` reports that no core attribute holds.
        self._activity = ""
        #: A file being sent up in pieces (`cmd_file_upload`): id -> bytes so far.
        self._uploads: dict[str, bytearray] = {}
        self._transport: dict = {}
        self._server = None
        self._unsubscribe = core.events.subscribe(self._on_event)
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """Listen (`http.py`). A port in use or a bad certificate raises."""
        from . import http

        serve_config = self.core.config.serve
        web_app = None
        if self.web:
            from ..client.ui import web

            if web.available():
                web_app = web.build(self)
        app = http.build_app(self, __version__, web_app)
        sock = http.bind(serve_config.listen, serve_config.port)
        listener = http.Listener(app, sock, tls_cert=serve_config.tls_cert,
                                 tls_key=serve_config.tls_key)
        try:
            await listener.start()
        except BaseException:
            await listener.stop()
            raise
        self._server = listener
        log.info("remote server listening on %s:%s", serve_config.listen, listener.port)

    @property
    def port(self) -> int:
        """The port actually bound (a test asks for port 0)."""
        return self._server.port

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
            await self._server.stop()
            self._server = None

    def has_clients(self) -> bool:
        return bool(self.clients)

    def rotate(self) -> str:
        """A new token; every client is closed and must pair again."""
        self.token = pairing.rotate_token()
        self.paired = False
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
            "connecting": wire.connecting_keys(core),
            "mail_running": bool(core.mail.collecting),
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
    async def handle(self, ws) -> None:
        """One connection on `/v1`, from hello to close (`http.Socket`)."""
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
        if not self.paired:
            self.paired = True
            pairing.mark_paired(self.token)
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

    def _sessions(self):
        if self.core.sessions is None:
            raise CommandError("No sessions on this station.")
        return self.core.sessions

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

    async def cmd_reconnect(self, key: str = "") -> None:
        """`Connector.reconnect`: session `key`'s own last request again,
        through the reminder and the gate."""
        await self._need_sessions().reconnect(str(key))

    async def cmd_disconnect(self, key: str) -> None:
        await self._need_sessions().disconnect(str(key))

    async def cmd_send_line(self, key: str, text: str) -> bool:
        self._need_sessions()
        return await self.core.sessions.send_line(str(key), str(text))

    async def cmd_aprs_send(self, to: str, text: str) -> str:
        return await self.core.aprs.compose(str(to), str(text))

    async def cmd_aprs_templates(self, callsign: str = "") -> dict:
        """`Aprs.templates`: the gateway service for `callsign` with its
        commands, and the saved messages for it. Never sends."""
        return self.core.aprs.templates(str(callsign))

    async def cmd_aprs_template_save(self, name: str, text: str, gateway: str = "",
                                     old: dict | None = None) -> dict:
        problems = self.core.aprs.template_save(str(name), str(text), str(gateway or ""),
                                                old if isinstance(old, dict) else None)
        return {"problems": problems, "saved": not problems}

    async def cmd_aprs_template_forget(self, name: str, text: str, gateway: str = "") -> bool:
        return self.core.aprs.template_forget(str(name), str(text), str(gateway or ""))

    async def cmd_aprs_position(self) -> None:
        await self.core.aprs.send_position_now()

    async def cmd_aprs_object_start(self, latitude: float | None = None,
                                    longitude: float | None = None, name: str = "") -> dict:
        """A new object's form: here or the place given; for `name`, one of
        this station's objects (Move, Kill)."""
        return self.core.aprs.object_start(
            None if latitude is None else float(latitude),
            None if longitude is None else float(longitude), str(name or ""))

    async def cmd_aprs_object(self, name: str, alive: bool, latitude: float | None = None,
                              longitude: float | None = None, symbol: str = "/.",
                              comment: str = "", scope: str = "network",
                              format: str = "decimal", reference: str = "") -> dict:
        """Send one object report, as the terminal's Send object does: checked
        first (nothing sent with a problem), then the gate armed by this
        operator-named request (`Aprs.send_object_now`). The place is the
        decimal `latitude`/`longitude`, or for `format` grid, mgrs or utm the
        `reference`, converted here (`place_from`)."""
        from ..core.aprs import AprsObjectRequest, object_problems, place_from

        if format != "decimal":
            try:
                latitude, longitude = place_from(str(format), str(reference))
            except ValueError as exc:
                return {"problems": [str(exc)], "sent": False}
        try:
            request = AprsObjectRequest(str(name), bool(alive), float(latitude),
                                        float(longitude), str(symbol), str(comment or ""),
                                        str(scope or "network"))
        except (TypeError, ValueError):
            return {"problems": ["The position must be two numbers."], "sent": False}
        problems = object_problems(request)
        if problems:
            return {"problems": problems, "sent": False}
        return {"problems": [], "sent": await self.core.aprs.send_object_now(request)}

    async def cmd_beacon_now(self) -> None:
        await self.core.aprs.beacon_now()

    async def cmd_send_receive(self, folder: str = "", internet: bool = False) -> None:
        await self.core.mail.send_receive(str(folder), internet=bool(internet))

    async def cmd_restart_plan(self) -> dict:
        """What a restart would end: `{sessions, aprs_unacked}`."""
        return self.core.restarter.plan()

    async def cmd_restart(self) -> bool:
        """Restart the station (`core.restart`): disconnects first, forced
        after a few seconds, then starts again; this client reconnects."""
        self.core.restarter.start("a remote client")
        return True

    async def cmd_shutdown(self) -> bool:
        """Shut the station down (`core.restart`, not started again): the
        same disconnect-first sequence; nothing remote can start it again."""
        self.core.restarter.start("a remote client", again=False)
        return True

    async def cmd_mail_cancel(self) -> bool:
        return await self.core.mail.cancel()

    async def cmd_get_bulletins(self, internet: bool = False) -> None:
        await self.core.mail.get_bulletins(internet=bool(internet))

    async def cmd_bulletin_categories(self) -> dict | None:
        """`Mail.bulletin_categories`, or null before any collection has
        listed them."""
        choice = self.core.mail.bulletin_categories()
        return wire.jsonable(choice) if choice is not None else None

    async def cmd_bulletin_categories_save(self, picked: list, all: bool = False) -> None:  # noqa: A002
        self.core.mail.choose_bulletin_categories([str(p) for p in picked or []],
                                                  all_=bool(all))

    async def cmd_transcripts(self, needle: str = "") -> list:
        """Past transcripts, newest first (`Sessions.transcripts`)."""
        return [{"name": info.path.name, "started": info.started, "peer": info.peer,
                 "mycall": info.mycall, "size": info.size}
                for info in (self.core.sessions.transcripts(str(needle))
                             if self.core.sessions is not None else [])]

    async def cmd_transcript_read(self, file: str) -> str:
        """One transcript by the `name` `transcripts` gave it."""
        try:
            return wire.clean(self.core.sessions.read_transcript(str(file)))
        except FileNotFoundError:
            raise CommandError(f"No transcript named {file!r}.") from None

    async def cmd_session_reference(self, key: str) -> dict:
        """`Sessions.reference_view`: the command reference for session `key`."""
        return wire.jsonable(self._sessions().reference_view(str(key)))

    async def cmd_session_suggest(self, key: str, text: str = "") -> list:
        """`Sessions.suggest`: commands for the partly-typed `text`."""
        return self._sessions().suggest(str(key), str(text))

    async def cmd_session_harvest(self, key: str, context: str = "node") -> dict:
        """`Sessions.harvest_commands`: ask the node's `?` once, the opt-in
        the terminal's Learn from node is (the client confirms the airtime
        first; it is sent through the gate, which it does not arm)."""
        sessions = self._sessions()
        names = await sessions.harvest_commands(str(key), context=str(context))
        text = sessions.last_harvest_text(str(key))
        return {"learned": list(names), "captured": len(text), "text": wire.clean(text)}

    async def cmd_session_forget_learned(self, key: str) -> int:
        """`Sessions.forget_learned`: drop what was learned from this node."""
        return self._sessions().forget_learned(str(key))

    async def cmd_bbs_helpers(self) -> list:
        """`Sessions.bbs_helpers`: the BBS mail helper's commands."""
        return self._sessions().bbs_helpers()

    async def cmd_bbs_render(self, profile: str, macro: str, values: dict) -> dict:
        """`Sessions.bbs_render`: the command a helper makes; never sends."""
        return self._sessions().bbs_render(str(profile), str(macro), dict(values or {}))

    async def cmd_glossary(self, needle: str = "") -> list:
        """`glossary.search`: packet-radio terms."""
        from .. import glossary

        return [{"name": t.name, "definition": t.definition}
                for t in glossary.search(str(needle))]

    async def cmd_transfer_start(self, key: str, protocol: str, mode: str, ref: str = "") -> bool:
        """`Transfers.begin`: one YAPP or AutoBIN transfer on session `key`,
        as the terminal's S on the Files tab (an upload of the file `ref`
        under Files) or its File transfer dialog (a download). The
        operator-named request arms the gate; it answers at once and the
        outcome is a notice."""
        path = None
        if str(mode) == "upload":
            try:
                path = self.core.mail.store.file_path(str(ref))
            except ValueError as exc:
                raise CommandError(wire.clean(str(exc))) from None
        try:
            self.core.transfers.begin(str(key), str(protocol), str(mode), path)
        except ValueError as exc:
            raise CommandError(str(exc)) from None
        return True

    async def cmd_rms_gateways(self, mode: str = "packet") -> dict:
        """`Mail.rms_gateways`: the saved Winlink gateway list in `mode`,
        nearest first. Reads the saved file; nothing is fetched or sent."""
        return self.core.mail.rms_gateways(str(mode))

    async def cmd_rms_refresh(self) -> str:
        """`Mail.rms_refresh`: fetch the list from winlink.org (Internet,
        only when asked); "" or why it was not refreshed."""
        return await self.core.mail.rms_refresh()

    async def cmd_rms_use(self, callsign: str, frequency: str = "", modes: str = "",
                          grid: str = "") -> str:
        """`Mail.use_gateway`: Address Book entry and Winlink Dial; sends nothing."""
        return self.core.mail.use_gateway(str(callsign).strip().upper(), str(frequency),
                                          str(modes), str(grid))

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
        if not result.errors:
            # Every screen redraws its settings (the terminal's Settings
            # tab included) and re-reads what it runs itself.
            core.events.publish(ev.ConfigChanged())
        if result.errors or not active_transport or (
                active_transport == before and core.transport is not None):
            return dataclasses.asdict(result)
        # A different transport chosen: open it now, as the terminal's
        # Settings Save does (`SettingsPane._reopen_transport`).
        if await core.switch_frame_transport(str(active_transport)) and core.station is not None:
            core.aprs.follow_station()
        return dataclasses.asdict(result)

    async def cmd_addressbook(self) -> list:
        """Every contact. A login script is literal text sent after the
        connect and may hold a password, so it never leaves the station:
        `has_script` says whether there is one."""
        return [redact_entry(wire.jsonable(e)) for e in self.core.addressbook.entries]

    async def cmd_addressbook_save(self, entry: dict) -> dict:
        """Create or edit a contact. Only the fields sent change: a phone
        editing a note must not wipe the script it was never shown."""
        from ..addressbook import INTERNET_FIELDS

        if not isinstance(entry, dict) or not entry.get("target"):
            raise CommandError("an entry needs a target")
        editable = EDITABLE_CONTACT_FIELDS + tuple(INTERNET_FIELDS)
        unknown = sorted(set(entry) - set(editable) - {"target", "original_target"})
        if unknown:
            raise CommandError(f"not contact fields: {', '.join(unknown)}")
        book = self.core.addressbook
        original = str(entry.get("original_target") or entry["target"])
        existing = book.find(original)
        fields = {name: getattr(existing, name) for name in editable} if existing else {}
        fields.update({k: str(v) for k, v in entry.items() if k in editable})
        saved = book.upsert(str(entry["target"]),
                            original_target=existing.target if existing else "", **fields)
        self.core.events.publish(ev.AddressBookChanged())
        return redact_entry(wire.jsonable(saved))

    async def cmd_heard(self) -> list:
        return wire.jsonable(self.core.heard.entries())

    async def cmd_map_points(self) -> list:
        """What the APRS map shows (`Aprs.map_points`): this station,
        heard stations with a position, live objects and items."""
        return self.core.aprs.map_points()

    async def cmd_aprs_conversations(self) -> list:
        """Every APRS conversation, most recent first, with its last line."""
        convos = sorted(self.core.aprs.conversations.conversations.values(),
                        key=lambda c: c.last_activity, reverse=True)
        return [{"callsign": c.callsign, "last_activity": c.last_activity,
                 "last": wire.clean(c.messages[-1].text) if c.messages else ""}
                for c in convos]

    async def cmd_aprs_thread(self, callsign: str) -> list:
        """One conversation's messages, oldest first (`MessageEntry`)."""
        convo = self.core.aprs.conversations.conversations.get(str(callsign).strip().upper())
        if convo is None:
            return []
        return [{**wire.jsonable(m), "text": wire.clean(m.text)} for m in convo.messages]

    async def cmd_mail_folders(self) -> list:
        return list(self.core.mail.store.folders())

    async def cmd_mail_list(self, folder: str) -> list:
        """A folder's messages; "All Inboxes" is the terminal's combined
        view of every Inbox under Mail (`MailStore.list_inboxes`). A Files
        folder holds files, not messages: each is `{ref, subject (its
        name), size, date (modified), file: true}` (`MailStore.list_files`)."""
        from ..mail.store import ALL_INBOXES, FILES

        store = self.core.mail.store
        if str(folder).split("/", 1)[0] == FILES:
            return [_file_entry(store.root, path) for path in store.list_files(str(folder))]
        items = store.list_inboxes() if folder == ALL_INBOXES else store.list(str(folder))
        return [{k: wire.clean(v) if isinstance(v, str) else v
                 for k, v in wire.jsonable(s).items()}
                for s in items]

    async def cmd_mail_read(self, ref: str) -> dict:
        from ..mail.store import FILES

        if str(ref).split("/", 1)[0] == FILES:
            return self._file_read(str(ref))
        message = wire.jsonable(self.core.mail.store.read(str(ref)))
        message = {k: wire.clean(v) if isinstance(v, str) else v for k, v in message.items()}
        # The `R:` lines: the BBSes it passed through, for a reader to unfold.
        message["routing"] = [wire.clean(line) for line in self.core.mail.routing(str(ref))]
        # Whether Reply all would reach anyone besides the sender.
        from ..mail.compose import has_others

        message["reply_all"] = has_others(self.core.mail.store.read(str(ref)),
                                          str(self.core.config.mycall or ""))
        # Answering on its form, or on the strip it carries (the terminal's
        # Reply on form and Answer strip).
        message["reply_on"] = self.core.mail.reply_choices(str(ref))
        return message

    async def cmd_mail_reply_start(self, ref: str, quoted: bool | None = None,
                                   all: bool = False) -> dict:  # noqa: A002 - the wire name
        start = self.core.mail.reply_start(
            str(ref), quoted=None if quoted is None else bool(quoted), everyone=bool(all))
        return {k: wire.clean(v) if isinstance(v, str) else v
                for k, v in wire.jsonable(start).items()}

    async def cmd_mail_write(self, to: str, title: str, body: str, at: str = "",
                             send_type: str = "P", reply_to: str = "") -> dict:
        """Check and file a message in its Outbox (`Mail.write`); nothing
        transmits. `problems` empty means it was filed in `folder`."""
        problems, folder = self.core.mail.write(
            to=str(to), at=str(at), title=str(title), body=str(body),
            send_type=str(send_type), reply_to=str(reply_to))
        return {"problems": problems, "folder": folder}

    async def cmd_forms(self) -> list:
        """The forms a new message can be written on (`Mail.forms_list`)."""
        return self.core.mail.forms_list()

    async def cmd_form_start(self, form: str, reply_to: str = "") -> dict:
        """A form's fields and the values it opens with (`Mail.form_start`);
        with `reply_to`, a message's reply form with its blocks filled in."""
        try:
            return wire.jsonable(self.core.mail.form_start(str(form), str(reply_to)))
        except (ValueError, KeyError, StopIteration) as exc:
            raise CommandError(f"No form {form!r}.") from exc

    async def cmd_form_check(self, form: str, values: dict) -> dict:
        """What stops the form being finished, or the message it makes
        (`Mail.form_check`); files nothing."""
        try:
            return self.core.mail.form_check(str(form), dict(values or {}))
        except (ValueError, KeyError, StopIteration) as exc:
            raise CommandError(f"No form {form!r}.") from exc

    async def cmd_form_mail_log(self, form: str, field: str, since: str) -> dict:
        """The lines a form's mail log takes (`Mail.form_mail_log`)."""
        try:
            return self.core.mail.form_mail_log(str(form), str(field), str(since))
        except (ValueError, KeyError, StopIteration) as exc:
            raise CommandError(f"No such form field {form}/{field}.") from exc

    async def cmd_form_write(self, form: str, values: dict, to: str, title: str, body: str,
                             at: str = "", send_type: str = "P", reply_to: str = "") -> dict:
        """File a message written on a form in its Outbox (`Mail.write_form`):
        `problems` (nothing filed), or `folder` and a `note`. Nothing transmits."""
        try:
            problems, folder, note = self.core.mail.write_form(
                form_id=str(form), values=dict(values or {}), to=str(to), at=str(at),
                title=str(title), body=str(body), send_type=str(send_type),
                reply_to=str(reply_to))
        except (ValueError, KeyError, StopIteration) as exc:
            raise CommandError(f"No form {form!r}.") from exc
        return {"problems": problems, "folder": folder, "note": note}

    async def cmd_radiogram_start(self, ics213: bool = False) -> dict:
        """A new radiogram's defaults and choices (`Mail.radiogram_start`)."""
        return self.core.mail.radiogram_start(bool(ics213))

    async def cmd_radiogram_check(self, fields: dict, ics213: bool = False) -> dict:
        """The check, routing, title, ARL texts and problems of a radiogram
        as filled so far (`Mail.radiogram_check`); files nothing."""
        return self.core.mail.radiogram_check(dict(fields or {}), bool(ics213))

    async def cmd_radiogram_write(self, fields: dict, ics213: bool = False) -> dict:
        """Check and file a radiogram in the BBS Outbox; nothing transmits."""
        problems, folder = self.core.mail.write_radiogram(dict(fields or {}), bool(ics213))
        return {"problems": problems, "folder": folder}

    def _file_read(self, ref: str) -> dict:
        """A file under Files as the reader shows it: the terminal's
        preview (`files_view.preview`), never the file itself."""
        from ..files_view import preview

        store = self.core.mail.store
        path = store.file_path(ref)
        kind, text, cut = preview(path)
        if cut:
            text += "\n[preview ends here]"
        return {**_file_entry(store.root, path), "body": text, "kind": kind}

    async def cmd_file_upload(self, id: str, filename: str, offset: int, data: str,
                              done: bool = False) -> dict:
        """A file from the client's own storage, in pieces (a message is at
        most `http.MAX_MESSAGE`): `data` is base64, `offset` what the station
        already holds under `id`. On `done` it is kept in Files/Uploads
        (`Mail.save_upload`) and `ref` says where; sending it is a separate,
        confirmed `transfer_start`. A wrong offset or too much starts over."""
        import base64
        import binascii

        pending = self._uploads
        key = str(id)[:64]
        held = pending.get(key)
        if int(offset) == 0:
            if held is None and len(pending) >= 4:
                raise CommandError("Too many uploads at once.")
            held = pending[key] = bytearray()
        if held is None or len(held) != int(offset):
            pending.pop(key, None)
            raise CommandError("The upload lost its place; start it again.")
        try:
            held += base64.b64decode(str(data), validate=True)
        except (binascii.Error, ValueError):
            pending.pop(key, None)
            raise CommandError("The upload was garbled; start it again.") from None
        if len(held) > self.core.mail.MAX_UPLOAD:
            pending.pop(key, None)
            raise CommandError("That file is too big to send by packet.")
        if not done:
            return {"received": len(held), "ref": ""}
        pending.pop(key, None)
        try:
            ref = self.core.mail.save_upload(wire.clean(str(filename)), bytes(held))
        except ValueError as exc:
            raise CommandError(wire.clean(str(exc))) from None
        return {"received": len(held), "ref": ref}

    async def cmd_file_open(self, ref: str, member: list | None = None) -> dict:
        """A file under Files as the terminal's viewer opens it
        (`files_view.describe`): a zip's members, Markdown and HTML as
        Markdown, other text as text. `member` is a path of zip member
        names into the file (a zip inside a zip). Read in memory, never
        extracted; nothing runs or is fetched."""
        from ..files_view import MAX_FILE, describe, zip_read

        try:
            path = self.core.mail.store.file_path(str(ref))
            with open(path, "rb") as handle:
                data, name = handle.read(MAX_FILE), path.name
            for part in member or ():
                data, name = zip_read(data, str(part)), str(part)
        except (OSError, ValueError) as exc:
            raise CommandError(wire.clean(str(exc))) from None
        return describe(name, data)

    async def cmd_mail_delete(self, ref: str) -> str:
        return self.core.mail.delete(str(ref))

    async def cmd_mail_restore(self, ref: str) -> str:
        return self.core.mail.restore(str(ref))



def _file_entry(root, path) -> dict:
    """One file under Files for `mail_list` and `mail_read`."""
    from datetime import datetime, timezone

    stat = path.stat()
    return {"ref": path.relative_to(root).as_posix(), "subject": wire.clean(path.name),
            "size": stat.st_size, "file": True,
            "date": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()}

COMMANDS: dict[str, Any] = {
    name[4:]: getattr(RemoteServer, name)
    for name in dir(RemoteServer) if name.startswith("cmd_")
}
