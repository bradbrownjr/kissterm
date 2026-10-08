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
 "station": {"callsign": "KC1JMH-1", "kissterm": "0.1.405", "on_air": "CCEMA"},
 "snapshot": {"gate": false, "transport": {}, "sessions": [], "connecting": [], "mail_running": false, "activity": ""} }
```

`on_air` is the call the station is on the air as: the tactical call while operating as one, else `callsign`.

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
`PickFiles`: a list of names. `HowManyBulletins` (`data`: `bbs`,
`count`, `categories`, `newest`, `radio`): how many of the newest to
read, a number from 0 to `count`; `null` reads none. `ChooseSessionTransport`'s `data` names
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
| `reconnect` `{key}` | `Connector.reconnect`: that session's own last request again | yes, after the reminder |
| `send_line` `{key, text}` | `Sessions.send_line` | yes, while connected |
| `aprs_send` `{to, text}` | `Aprs.compose` | yes |
| `aprs_position` | `Aprs.send_position_now` | yes |
| `aprs_conversations` / `aprs_thread` `{callsign}` | `Aprs.conversations` | no |
| `aprs_object_start` `{latitude, longitude, name}` | `Aprs.object_start`: a new object's form, at here or the place given (a long press on the map), with `symbol`, `comment`, `scopes` and `symbols` (key, description); `name` one of this station's objects fills in its symbol and comment (Move, Kill) | no |
| `aprs_object` `{name, alive, latitude, longitude, symbol, comment, scope}`, or `format` (`grid`, `mgrs`, `utm`) and `reference` in place of the coordinates (`aprs_object_start` lists `formats`) | `Aprs.send_object_now`, after `object_problems`: returns `problems` (nothing sent) and `sent`; the object is on this station's map at once, `mine` true. `alive` false kills it | yes |
| `aprs_templates` `{callsign}` / `aprs_template_save` `{name, text, gateway, old}` / `aprs_template_forget` `{name, text, gateway}` | `Aprs.templates` (the shipped gateway service for that callsign, or the contact's own, with `commands` (`name`, `summary`, `text`, `confidence`), `note`, `source`, `checked`; and the saved messages for it) / `template_save` (returns `problems`; `old` replaces that saved message, matched on its content) / `template_forget`. A client puts a chosen `text` in its message box; nothing here sends | no |
| `session_reference` `{key}` / `session_suggest` `{key, text}` / `glossary` `{needle}` | `Sessions.reference_view` (the command sets in effect and reachable from this session, each command with `name`, `aliases`, `usage`, `summary`, `detail`, `context`, `sysop`, `source`; `can_harvest`, `peer`, `context`, `learned`, `airtime` low and high) / `Sessions.suggest` (the terminal's suggestion strip: sysop commands left out) / `glossary.search`. Nothing here sends | no |
| `bbs_helpers` / `bbs_render` `{profile, macro, values}` | `Sessions.bbs_helpers` (dialects and macros with their `fields`) / `Sessions.bbs_render` (returns `text` or `error`; fills a message box, never sends) | no |
| `session_harvest` `{key, context}` / `session_forget_learned` `{key}` | `Sessions.harvest_commands` (asks the node's `?` once, opt-in: a client shows `airtime` and asks first; sent through the gate, which it does not arm; returns `learned`, `captured`, `text`) / `Sessions.forget_learned` | no |
| `rms_gateways` `{mode}` / `rms_refresh` / `rms_use` `{callsign, frequency, modes, grid}` | `Mail.rms_gateways` (the saved Winlink gateway list in that mode, nearest first, with `note`, `can_refresh`, `modes`; reads the file only) / `Mail.rms_refresh` (an Internet request to winlink.org, only when asked, and only with kissterm's Winlink API key; returns "" or why not) / `Mail.use_gateway` (the Address Book entry and the Winlink Dial) | no |
| `transfer_start` `{key, protocol, mode, ref}` | `Transfers.begin`: one YAPP or AutoBIN transfer on session `key` (`protocol` `yapp` or `autobin`; `mode` `upload` of the file `ref` under Files, or `download` into Files > Downloads); refused when the session is not connected, cannot carry binary (SSH) or already runs one; answers at once, the outcome is a notice | yes, a committed send |
| `beacon_now` | `Aprs.beacon_now` | no (refused while closed) |
| `broadcast_info` `{text}` / `broadcast_send` `{to, text}` (an empty `to` reads a `QST:` style prefix off `text`) | `Broadcast` (`core/broadcast.py`): where a broadcast may go (`destinations`), what `text` costs the channel (`cost`), and the broadcasts heard and sent (`heard`: `source`, `to`, `text`, `at`, `own`) / one unproto UI frame to `to` now, `error` empty when it went out. The `BroadcastHeard` event makes a client re-read `broadcast_info` | yes: Send is the operator's commitment |
| `send_receive` `{folder, internet}` | `Mail.send_receive` | through its connect |
| `get_bulletins` `{internet}` / `get_files` | `Mail` | through its connect |
| `restart_plan` | `Restarter.plan`: `{sessions, aprs_unacked}`, what a restart would end (for the confirmation) | no |
| `restart` | `Restarter.start`: answers `true` at once, then stops beacons and runs, disconnects every session (forced after 5 s), and starts the station again with the same command line; the client's connection drops and reconnects with the same token | a DISC per connected link |
| `shutdown` | `Restarter.start(again=False)`: as `restart`, but the station stays stopped (nothing remote can start it again) | a DISC per connected link |
| `mail_cancel` | `Mail.cancel`: the run's session is disconnected (or its SABMs stopped), an Internet run stopped; false if none was running | a DISC, if its link is up |
| `settings_schema` | `SETTINGS_SCHEMA`, each field with its `value` (a secret's is null) and, for a contact, login or map-symbol field, its `options` as `[label, value]`; fields marked `tui_only` are left out, and the Theme field's `choices` are filled | no |
| `theme` | the station's theme as one palette: `id`, `drawn_as`, `dark` and `#rrggbb` for `primary`, `secondary`, `accent`, `foreground`, `background`, `surface`, `panel`, `warning`, `error`, `success` (the ANSI themes are drawn as Textual's dark and light) | no |
| `settings_save` `{draft, active_transport}` | `Settings.save`; a new transport is opened | no |
| `addressbook` / `addressbook_save` `{entry}` | `Core.addressbook` | no |
| `heard` | `Core.heard.entries` | no |
| `map_points` | `Aprs.map_points`: what the APRS map shows, this station first (`kind` `me`), then each heard station with a position (`station`) and each live object or item (`object`, `item`); every one has `name`, `lat`, `lon`, `symbol` (APRS table and code), `symbol_name`, `comment`, `when`, `by` (who reported an object), `mine` (an object this station sent), and `where` (distance and bearing from here) when this station's position is known. Refreshed on `stale heard` | no |
| `radiogram_start` `{ics213}` / `radiogram_check` `{fields, ics213}` / `radiogram_write` `{fields, ics213}` | `Mail.radiogram_start`, `radiogram_check`, `write_radiogram`: a new radiogram's defaults (next number, last place, ARL texts), what the form shows as it is filled (check, routing, title, the text as it will go, problems), and filing it in the BBS Outbox; `fields` are `nts.Radiogram`'s (`core.mail.RADIOGRAM_FIELDS`) | no |
| `forms` / `form_start` `{form, reply_to}` / `form_check` `{form, values}` / `form_mail_log` `{form, field, since}` / `form_write` `{form, values, to, at, title, body, send_type, reply_to}` | `Mail.forms_list` (id and title of each form a new message can be written on) / `Mail.form_start` (`form` is a shipped id or `strip:` and an information strip's text; with `reply_to`, that message's reply form with the original's blocks filled in; the form as `mail/forms.py` defines it, every field with its kind, label, limits, choices, columns, and the `values` it opens with: dates now, this station's call and grid, what was remembered; `key` is what to pass back to check and write) / `Mail.form_check` (`problems`, or the message it makes: `to`, `at`, `title`, `body`, `send_type`; for the paste-a-strip form, `next_form`, the strip's questions; files nothing; `mail_read` carries `reply_on`: `form` (a reply form exists) and `strip` (the key to answer it)) / `Mail.form_mail_log` (the ICS-309's lines for the mail since a time) / `Mail.write_form` (checks and files it in its Outbox: `problems`, or `folder` and a `note`; a Winlink message on a form with a Winlink viewer carries its XML unless the body no longer matches the form) | no (Send/Receive sends it) |
| `mail_folders` / `mail_list` `{folder}` / `mail_read` `{ref}` | `Mail.store`; `mail_list` also takes `"All Inboxes"`, every Inbox under Mail together, as the terminal's view of that name; a folder under Files lists files, not messages (`{ref, subject, size, date, file: true}`, subject being the name), and reading one gives the terminal's preview as `body`, with `kind` (`zip`, `broken`, `binary`, `markdown`, `html`, `text`); a read also carries `routing`, the `R:` lines of a message from a BBS (`Mail.routing`), and `reply_all`, true when Reply all would reach anyone besides the sender | no |
| `mail_reply_start` `{ref, quoted, all}` | `Mail.reply_start`: `to`, `title`, `body`, `send_type`, `by_number`, `heading`, `note` for a reply (`quoted` null: as Settings says; `all`: Reply all) | no |
| `mail_write` `{to, at, title, body, send_type, reply_to}` | `Mail.write`: checked, then filed in its Outbox; returns `problems` (nothing filed) or `folder`. `send_type` is `P`, `B` or `W`; a reply goes as its original's kind | no (Send/Receive sends it) |
| `bulletin_categories` / `bulletin_categories_save` `{picked, all}` | `Mail.bulletin_categories` (`bbs`, `seen` with counts, `chosen`, `all`; null before any collection listed them) / `Mail.choose_bulletin_categories` | no (offline) |
| `transcripts` `{needle}` / `transcript_read` `{file}` | `Sessions.transcripts` (`name`, `started`, `peer`, `mycall`, `size`, newest first) / `Sessions.read_transcript`, by a listed name only, the last 256 KB | no |
| `file_open` `{ref, member}` | `files_view.describe`: the terminal's file viewer on a file under Files, or on the zip member named by the path `member` (a zip inside a zip): `kind`, `members` (name, size), `markdown` (HTML converted, images never kept, scripts dropped), `text`, `problem`, `form` (the kissterm form a PKTNET page is). Read in memory, never extracted; sanitized and capped | no |
| `mail_delete` / `mail_restore` `{ref}` | `Mail.delete` / `Mail.restore`; returns the new ref, which the other puts back (Undo) | no |

**The Address Book never sends a login script** (it may hold a
password): `addressbook` returns each contact without `script`, and
`has_script` true when one is saved. `addressbook_save` merges the fields
it is given onto the saved contact (`original_target` names it when
renaming), so a script it never saw survives, and refuses a field it does
not know. A successful `settings_save` is followed by `ConfigChanged`, so
every client refreshes.

A file from a phone's own storage goes up in pieces (`file_upload`
`{id, filename, offset, data, done}`: `data` is base64, a piece at most
about 192 KiB so a message stays under the 1 MiB limit, `offset` what the
station already holds under `id`; a wrong offset or bad base64 starts it
over; at most 1 MiB in all, `Mail.MAX_UPLOAD`). On `done` it is kept in
Files/Uploads (`Mail.save_upload`: the name cleaned, never replacing a
file) and `ref` says where; nothing transmits. Sending it is the
separate, confirmed `transfer_start`. Compose-with-attachments is not in v1.

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
| `FrameSeen` | `port, outgoing, line` (`monitor.format_frame`), `raw` (base64), and for a client's Monitor filter `kind` (`I`, `S`, `U`), `ui`, `calls` (source, destination, digipeaters), `text` (payload, filtered) |
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
