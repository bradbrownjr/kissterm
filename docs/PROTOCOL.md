# kissterm remote protocol (DRAFT for review)

**Status: draft, 2026-10-05. Nothing here is built yet.** This is how a
phone, desktop or browser client will talk to a station running
`kissterm --serve` (ROADMAP P7a M7). It becomes the reference once
approved; until then every part is open to change.

The station keeps the radio, the TNC and the core
(`kissterm/core/`). A client is a remote control: it shows what the core
says happened and sends the operator's requests. It never sees the
transport and cannot transmit except by asking the core, which applies
the same transmit-gate rules as the terminal.

## 1. Connection

- **WebSocket**, one per client, at `ws://<station>:<port>/v1`.
  Default port **7425** (unassigned; to confirm).
- **Every message is one JSON object** with a `type`. Text frames only.
- **Version** is in the path (`/v1`). A breaking change gets `/v2`; a
  client that sees fields it does not know ignores them.

## 2. Pairing and authentication

- **One token per machine**, made once (32 random bytes, URL-safe base64)
  and kept in kissterm's state folder (mode 0600). It survives restarts,
  so a bookmark keeps working, and differs on every machine (operator,
  2026-10-05).
- **Shown two ways** by `kissterm --serve` and in the terminal UI:
  - a URL, `http://<host>:7425/#t=<token>`: for a browser on the same
    machine, a laptop on the LAN, or a bookmark to share. The token is in
    the fragment, which browsers never send in an HTTP request, so it
    stays out of proxy and server logs;
  - a QR code of the same URL, for a phone.
- **The client's first message** is `{"type": "hello", "token": "...",
  "client": "kissterm-flet 0.1", "since": 0}`. A wrong token closes the
  connection with code 4401 and nothing else is sent.
- **Rotate** (`kissterm --serve --rotate-token`, and a button in the
  terminal UI): a new token is made, the old one stops working at once,
  and every connected client is closed with 4401. This is the answer to a
  leaked link (approved 2026-10-05).
- **A callsign is a claim, not an identity** (AGENTS.md): the token, not
  any callsign a client states, is what admits it. Holding the token is
  holding the station's transmitter. Treat it like a password.

## 3. Server to client

### 3.1 welcome

```json
{"type": "welcome", "version": 1, "seq": 1234,
 "station": {"callsign": "KC1JMH-1", "kissterm": "0.1.405"},
 "snapshot": {"gate": false, "transport": {}, "sessions": [], "activity": ""}}
```

`seq` is the last event sequence number included in `snapshot`. Events
after it follow.

### 3.2 event

```json
{"type": "event", "seq": 1235, "name": "SessionOpened",
 "data": {"key": "WS1EC-15", "peer": "WS1EC-15", "activate": true, "incoming": false}}
```

`name` is the core event's class name (`kissterm/core/events.py`);
`data` is its fields. Each event's wire form is listed in section 6.
Sequence numbers rise by one; a gap means the client missed events and
should reconnect with `since`.

### 3.3 notice

```json
{"type": "notice", "text": "Transmit ENABLED for connect to WS1EC-15. the Transmit switch turns it back off.",
 "severity": "information", "title": "", "timeout": null}
```

`text` is the core's wording rendered neutrally (`core/wording.py`):
no key or tab names. `timeout` is seconds, at least 10, or null for the
client's default. Sent to every connected client.

### 3.4 question

```json
{"type": "question", "id": "q17", "name": "RadioReminder",
 "data": {"frequency": "145.090", "connection_type": "", "note": ""}}
```

`name` is the `Question` class (`kissterm/core/questions.py`), `data` its
fields; the answer type is in each class's docstring. Sent to every
connected client. **The first answer wins**; the others get
`{"type": "question_closed", "id": "q17"}`. A question nobody answers
waits; closing the last client cancels it (an answer of null), and a
cancelled flow transmits nothing.

### 3.5 result

The reply to a command (section 4): `{"type": "result", "id": "c5",
"ok": true, "value": ...}` or `{"type": "result", "id": "c5", "ok":
false, "error": "Not connected."}`.

## 4. Client to server

### 4.1 answer

`{"type": "answer", "id": "q17", "value": true}`. `null` is cancel.

### 4.2 command

`{"type": "command", "id": "c5", "name": "send_line", "args": {"key":
"WS1EC-15", "text": "BBS"}}`. Each command is one core method; none is a
lighter path around a rule the terminal follows.

| Command | Core method | Arms the gate? |
|---|---|---|
| `transmit` `{enabled}` | the master switch (Ctrl+T) | it is the switch |
| `connect` `{target}` or `{entry}` | `Connector.dial_entry` / `connect` | yes, after the reminder |
| `disconnect` `{key}` | `Connector.disconnect` | no |
| `send_line` `{key, text}` | `Sessions.send_line` | yes, while connected |
| `aprs_send` `{to, text}` | `Aprs.compose` | yes |
| `aprs_position` | `Aprs.send_position_now` | yes |
| `beacon_now` | `Aprs.beacon_now` | no (refused while closed) |
| `send_receive` `{folder, internet}` | `Mail.send_receive` | through its connect |
| `get_bulletins` `{internet}` / `get_files` | `Mail` | through its connect |
| `settings_schema` | `settings_schema.SETTINGS_SCHEMA` | no |
| `settings_save` `{draft, active_transport}` | `Settings.save` | no |
| `addressbook` / `addressbook_save` `{entry}` | `Core.addressbook` | no |
| `heard` | `Core.heard.entries` | no |
| `mail_list` `{folder}` / `mail_read` `{ref}` | `Mail.store` | no |

File transfers (upload from a phone) and compose-with-attachments are
not in v1.

## 5. Reconnecting and history

The core keeps no scrollback; a terminal tab does. So that a phone that
sleeps, or a laptop that joins late, sees a session's recent text, the
server keeps a **ring buffer of recent events** (proposed: the last
2,000, plus the last 64 KB of `SessionData` per session). `hello` with
`since: N` replays every buffered event after N, then live ones. If N is
older than the buffer, the server sends a fresh `welcome` snapshot
instead.

## 6. Events on the wire

| Event | data |
|---|---|
| `TransportChanged` | `name, tier, detail` |
| `GateChanged` | `enabled` |
| `SessionOpened` | `key, peer, activate, incoming` |
| `SessionData` | `key, text` (see below), `raw` (base64) |
| `LineSent` | `key, text` |
| `SessionStateChanged` | `key, state` |
| `SessionUpdated` | `key`, and the session's current summary |
| `SessionClosed` | `key` |
| `ActivityChanged` | `text` |
| `AprsMessage`, `AprsAcked`, `AprsBulletinHeard`, `AprsRetried` | as in `events.py` |
| `AprsPacketHeard` | `line, at` (the decoded packet stays on the station) |
| `Alert` | `title, body, urgent, topic` |
| `FrameSeen` | `port, outgoing, line` (`monitor.format_frame`), `raw` (base64) |
| `MailChanged`, `ConfigChanged`, `AddressBookChanged`, `KnownNodesChanged` | none: re-read |
| `SetupRequested` | `place` |

**Remote bytes are filtered on the station.** `SessionData.text` is the
payload through `ansi.decode_text` and the same filter the terminal uses
(AGENTS.md "Untrusted input"), with colour as a list of spans rather than
escape codes, so a browser never parses ANSI or control bytes from the
air. `raw` is there for a client that wants to do its own, and is never
rendered as-is.

## 7. Open questions for the operator

1. Run the server **inside the terminal UI** too (one core, the station's
   screen and a phone together), or only headless (`--serve`)?
2. **Where it listens** by default: this machine only (127.0.0.1; reach
   it from elsewhere by Tailscale or an SSH tunnel), or the LAN?
3. **TLS**: plain `ws://` on the LAN, or self-signed `wss://`?
4. **Libraries**: `websockets` (server) and `segno` (QR in the terminal),
   both pure Python, as an optional `[serve]` extra.
