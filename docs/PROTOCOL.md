# kissterm remote protocol, version 1

**Status: built (`kissterm/serve/`, 2026-10-05); the station serves its
own client, a Flet web app, at `/` (`kissterm/client/`).**
This is how a phone, desktop or browser client talks to a station running
`kissterm --serve` (ROADMAP P7a M7). The server's code and
`tests/unit/test_serve.py` are the reference where this page is unclear.

The station keeps the radio, the TNC and the core
(`kissterm/core/`). A client is a remote control: it shows what the core
says happened and sends the operator's requests. It never sees the
transport and cannot transmit except by asking the core, which applies
the same transmit-gate rules as the terminal.

## 1. Connection

- **WebSocket**, one per client, at `ws://<station>:<port>/v1`, or
  `wss://` natively or through a reverse proxy (section 7).
  Default port **7425** (Settings > Remote).
- **Every message is one JSON object** with a `type`. Text frames only.
- **The web client** is served at `/` on the same port when the station
  has the `web` extra; it reaches `/v1` on the station's own loopback.
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
 "snapshot": {"gate": false, "transport": {}, "sessions": [], "connecting": [], "mail_running": false, "activity": ""} }
```

`seq` is the last event sequence number included in `snapshot`. Events
after it follow.

### 3.2 event

```json
{"type": "event", "seq": 1235, "name": "SessionOpened",
 "data": {"key": "WS1EC-15", "peer": "WS1EC-15", "activate": true, "incoming": false} }
```

`name` is the core event's class name (`kissterm/core/events.py`);
`data` is its fields. Each event's wire form is listed in section 6.
Sequence numbers rise by one; a gap means the client missed events and
should reconnect with `since`. A replayed event (section 5) also carries
`"replay": true`.

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
 "data": {"frequency": "145.090", "connection_type": "", "note": ""} }
```

`name` is the `Question` class (`kissterm/core/questions.py`), `data` its
fields; the answer type is in each class's docstring. Sent to every
connected client. **The first answer wins**; every client then gets
`{"type": "question_closed", "id": "q17"}`. Headless, a question asked
with no client connected is cancelled at once, and the last client
leaving cancels any still open (an answer of null); a cancelled flow
transmits nothing. Inside the terminal UI the station's own screen asks
too, and whichever answers first wins. A client that connects while a
question is open is sent it after the welcome.

The answer forms: `RadioReminder`, `TrustHostKey`: true or false.
`HomeBbsRoute`, `CallsignAsk`, `ChooseSessionTransport`: a string.
`WinlinkGateway`: `{target, remember}`. `InternetLoginAsk`: `{target,
username, password}`. `LoginAsk`: the password, or with `username` set
`{username, password}`. `ChooseCategories`: `{categories, all}`.
`PickFiles`: a list of names. `ChooseSessionTransport`'s `data` names
the configured transports (`transports`, `active`) and never sends
their config, which can hold a password. A setup question also takes `"skip"`
(leave this service out) and `"go"` (cancel; `SetupRequested` follows).

### 3.5 result

The reply to a command (section 4): `{"type": "result", "id": "c5",
"ok": true, "value": ...}` or `{"type": "result", "id": "c5", "ok":
false, "error": "..."}`. A command's notices (why nothing was sent, say)
arrive before its result.

### 3.6 error

`{"type": "error", "error": "..."}`, with `id` when it was an answer
that did not fit its question (the question stays open).

### 3.7 close codes

4401: wrong or missing token, or the token was rotated. 4408: the client
fell too far behind (5,000 messages); reconnect with `since`.

## 4. Client to server

### 4.1 answer

`{"type": "answer", "id": "q17", "value": true}`. `null` is cancel.

### 4.2 command

`{"type": "command", "id": "c5", "name": "send_line", "args": {"key":
"WS1EC-15", "text": "BBS"} }`. Each command is one core method; none is a
lighter path around a rule the terminal follows.

| Command | Core method | Arms the gate? |
|---|---|---|
| `transmit` `{enabled}` | the master switch (Ctrl+T) | it is the switch |
| `connect` `{target}` or `{entry}` | `Connector.dial_entry` / `connect` | yes, after the reminder |
| `disconnect` `{key}` | `Connector.disconnect` | no |
| `send_line` `{key, text}` | `Sessions.send_line` | yes, while connected |
| `aprs_send` `{to, text}` | `Aprs.compose` | yes |
| `aprs_position` | `Aprs.send_position_now` | yes |
| `aprs_conversations` / `aprs_thread` `{callsign}` | `Aprs.conversations` | no |
| `beacon_now` | `Aprs.beacon_now` | no (refused while closed) |
| `send_receive` `{folder, internet}` | `Mail.send_receive` | through its connect |
| `get_bulletins` `{internet}` / `get_files` | `Mail` | through its connect |
| `mail_cancel` | `Mail.cancel`: the run's session is disconnected (or its SABMs stopped), an Internet run stopped; false if none was running | a DISC, if its link is up |
| `settings_schema` | `SETTINGS_SCHEMA`, each field with its `value` (a secret's is null) | no |
| `settings_save` `{draft, active_transport}` | `Settings.save`; a new transport is opened | no |
| `addressbook` / `addressbook_save` `{entry}` | `Core.addressbook` | no |
| `heard` | `Core.heard.entries` | no |
| `mail_folders` / `mail_list` `{folder}` / `mail_read` `{ref}` | `Mail.store`; a read also carries `routing`, the `R:` lines of a message from a BBS (`Mail.routing`), and `reply_all`, true when Reply all would reach anyone besides the sender | no |
| `mail_reply_start` `{ref, quoted, all}` | `Mail.reply_start`: `to`, `title`, `body`, `send_type`, `by_number`, `heading`, `note` for a reply (`quoted` null: as Settings says; `all`: Reply all) | no |
| `mail_write` `{to, at, title, body, send_type, reply_to}` | `Mail.write`: checked, then filed in its Outbox; returns `problems` (nothing filed) or `folder`. `send_type` is `P`, `B` or `W`; a reply goes as its original's kind | no (Send/Receive sends it) |
| `mail_delete` / `mail_restore` `{ref}` | `Mail.delete` / `Mail.restore`; returns the new ref, which the other puts back (Undo) | no |

**The Address Book never sends a login script** (it may hold a
password): `addressbook` returns each contact without `script`, and
`has_script` true when one is saved. `addressbook_save` merges the fields
it is given onto the saved contact (`original_target` names it when
renaming), so a script it never saw survives, and refuses a field it does
not know. A successful `settings_save` is followed by `ConfigChanged`, so
every client refreshes.

File transfers (upload from a phone) and compose-with-attachments are
not in v1.

## 5. Reconnecting and history

The core keeps no scrollback; a terminal tab does. So that a phone that
sleeps, or a laptop that joins late, sees a session's recent text, the
server keeps a **ring buffer of the last 2,000 events**. Every connection
gets a `welcome` (the state now, and the current `seq`), then every
buffered event after the hello's `since`, marked `"replay": true` --
history to draw, not state to apply over the snapshot -- then live
events, with no gap between the two. `since: 0` replays the whole buffer.
A replayed `Alert` or `SetupRequested` already happened: a client shows
it as history, if at all, and never raises it again.

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
| `ConnectingChanged` | `keys`: every session with a connect still in progress (a `disconnect` cancels it). A radio session gets its `SessionOpened` only once the link is up, so a client shows a key here it has not seen as a session being dialled; the snapshot's `connecting` is the same list |
| `ActivityChanged` | `text` |
| `MailRunChanged` | `running`: a Send/Receive, Get bulletins or Get files started or ended (the snapshot's `mail_running` says the same) |
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

## 7. Decided (operator, 2026-10-05)

1. **The server runs headless (`kissterm --serve`) and inside the
   terminal UI**, so the station's screen and a phone share one core.
   Questions go to every screen; the first answer wins.
2. **It listens on the LAN by default** (all interfaces); the pairing URL
   shows this machine's LAN address. The token is what admits a client.
3. **TLS by a reverse proxy, or natively** (operator, 2026-10-05: Caddy
   on the firewall with a shared `*.lynwood.us` certificate, for the LAN
   and Tailscale). kissterm serves plain `ws://` behind the proxy; Settings
   > Remote's **Public URL** (`https://kissterm.example.org`) is what the
   pairing URL and QR show, so clients connect with `wss://` through the
   proxy, and the client address in the log is the proxy's
   `X-Forwarded-For`. Or give kissterm the certificate and key files and
   it serves `wss://` itself. Plain `ws://` with neither is for a trusted
   LAN or Tailscale only.
4. **An optional `[serve]` extra** (`pip install kissterm[serve]`):
   first `websockets` and `segno`; since M8, uvicorn and Starlette too,
   so the same port serves the web client at `/` beside `/v1` (operator,
   2026-10-05: the station serves the client).
