# CHANGELOG.md — kissterm

Format: keep newest at top. One entry per meaningful change, a few lines
long, with a **Files:** line. Entries from before 2026-09-22 (the P0
stabilization rewrite) are in `docs/CHANGELOG-archive.md`; read it only when
you need the history of a specific change.

## [2026-10-08] — Phone and web: New contact and New login in Settings lists

### Improvements

- **Contact and login dropdowns in Settings end "New contact..." / "New
  login..."**, as the terminal's do: a short form (a station; or name, Telnet
  or SSH, host and port for an Internet contact; a login's name, user and
  password) saves through `addressbook_save` / `login_save` and picks the new
  entry. Cancelling leaves the field as it was.
- **A contact field has Edit contact**: the same form for the selected
  contact, so its frequency, hops, note or host are reachable from Settings.

**Files:** `kissterm/client/ui/settings.py`, `tests/unit/test_client_ui.py`

## [2026-10-08] — Phone and web: Clear icon, GPS Scan, Open on Monitor

### Improvements

- **Clear is a broom**, not the stacked lines that read as a menu (operator,
  2026-10-08).
- **Settings > APRS > GPS device has the terminal's Scan**: lists the
  station's local serial ports (GPS first) and fills the field (`gps_scan`).
- **Open on > Monitor opens More with its Monitor section expanded.**

**Files:** `kissterm/client/ui/sessions.py`, `settings.py`, `more.py`,
`shell.py`, `kissterm/serve/server.py`, `docs/PROTOCOL.md`

## [2026-10-08] — Phone and web: one toolbar design

### Improvements

- **One interface design for every place** (operator, 2026-10-08: "3 or 4
  competing interface designs ... we really need to settle on a design
  scheme"): one toolbar row, tabs at the left, secondary actions, the main
  action last and filled with a word on it; no floating buttons. Width decides
  the labels: from a desktop-wide window every action has its word, on a phone
  in portrait only the main one does. Replaces the outlined chip row (Messages),
  the stacked mini and full-size FABs (Mail, Messages, Stations), the icon strip
  at the end of Terminal's tabs, the segmented section switch (Mail's sections
  are tabs now), Categories and Add file beside the folder picker, and the
  Disconnect and Reconnect chips beside the transmit switch (Terminal's
  toolbar has them). The reader's actions are the same row with Reply as the
  main one. DESIGN.md 8a has the rule. (`client/ui/toolbar.py`.)

**Files:** `kissterm/client/ui/toolbar.py`, `sessions.py`, `stations.py`,
`messages.py`, `mail.py`, `shell.py`, `more.py`, `DESIGN.md`, `docs/GUIDE.md`

## [2026-10-08] — Phone and web: the station's theme and a real Settings form

### New Features

- **The phone and browser are drawn in the station's theme.** Settings >
  Appearance > Theme (and the custom colours and Dark flag) now restyles the
  web client as well as the terminal, light or dark as the theme is, instead
  of a fixed indigo page that ignored it (operator, 2026-10-08: "I turned off
  dark mode and it's still dark"). More > Terminal keeps a per-device choice
  for session text only, defaulting to Theme. (`themes.palette`, command
  `theme`, `client/ui/theme.py`.)
- **A colour picker** for colour settings (palette, RGB sliders, hex).
- **Radio, Logins and Scripts on the phone and browser**: choose the radio
  in use, Scan for hardware, New, Edit, Test and Forget a transport, and
  save logins and scripts (a password and a script's text never leave the
  station; an empty field on an edit keeps what is saved). One core class,
  `core/radio.py`, with `build_transport` proving a transport before it is
  saved; the transport form table moved to `transport/forms.py`.
- **Open on** (Settings > Appearance) opens the phone on that place.
- **Send beacon moved from More to the Terminal strip** (an icon beside Clear and
  Connect), leaving More with the system functions, Restart and Shut down, on
  one row on a phone (operator, 2026-10-08).
- **A Clear button** on the Terminal strip (the terminal's `Ctrl+L`).

### Improvements

- **Settings on the phone uses the schema in full**: dropdowns for choices,
  contacts, logins and the map symbol, the Custom option for the APRS path,
  `only_when` (custom colours only while Theme is Custom), an Advanced fold,
  headings, number limits, and "Needs a restart" notes. The theme list is
  served by a headless station too (it was empty, which is why Theme was a
  text box).
- **The message count sits inside the field** (`0/67` at its right end),
  not under it, where it pushed the box out of line with the buttons beside
  it (operator, 2026-10-08).
- **Settings only the terminal draws are not offered to the phone**
  (`Field.tui_only`: clocks, ASCII-safe, slide-outs, remote-control server,
  default monitor filter).

**Files:** `kissterm/themes.py` (moved from `ui/themes.py`, which re-exports),
`kissterm/core/settings_schema.py`, `kissterm/serve/server.py`,
`kissterm/client/ui/settings.py`, `colourpicker.py`, `theme.py`, `text.py`,
`shell.py`, `more.py`, `radio.py`, `messages.py`, `kissterm/core/radio.py`,
`kissterm/transport/forms.py`, `docs/GUIDE.md`, `docs/PROTOCOL.md`

## [2026-10-08] — Phone and web: Clear

### Improvements

- **A Clear button on the phone and web Terminal** (the terminal's `Ctrl+L`):
  empties the shown session or the Broadcast page. The view only; the
  station keeps the transcript and nothing is sent.

**Files:** `kissterm/client/ui/sessions.py`, `tests/unit/test_client_ui.py`,
`docs/GUIDE.md`

## [2026-10-08] — Broadcast: free text with no connection

### New Features

- **A Broadcast tab, first in the Terminal's session strip**, in the
  terminal and on the phone and web client: type a line (prefix `CQ:`,
  `QST:`, `TEST:`, `BEACON:`, `ID:` or `MAIL:` to pick the address, ALL
  otherwise; there is no standard, ALL is the neutral choice), and Enter sends it once as an unproto frame with nobody
  connected: an announcement, a test, an ad hoc chat on a frequency
  (operator, 2026-10-08). The tab lists the plain-text broadcasts heard to those addresses (APRS reports
  are left to the APRS tab) and the ones sent. Enter is the commitment and
  arms the transmit gate; opening it or typing transmits nothing. A
  callsign in the list is clickable and opens Connect filled in, to send
  a file or mail drop (operator, 2026-10-08). Under a tactical call the licensed call is
  identified after it. (`core/broadcast.py`, commands `broadcast_info`
  and `broadcast_send`, event `BroadcastHeard`, `TerminalPane.note_broadcast`.)

**Files:** `kissterm/core/broadcast.py`, `kissterm/core/events.py`,
`kissterm/core/service.py`, `kissterm/serve/server.py`,
`kissterm/core/sessions.py`, `kissterm/ui/terminal_pane.py`,
`kissterm/ui/commands.py`, `kissterm/ui/app.py`, `kissterm/client/ui/sessions.py`,
`kissterm/client/ui/more.py`, `kissterm/client/state.py`,
`scripts/generate_phone_screenshots.py`,
`assets/screenshot-phone-broadcast.png`, `docs/GUIDE.md`,
`docs/PROTOCOL.md`, `docs/ON-AIR-TESTS.md`

## [2026-10-08] — Operating as a tactical call (P11)

### New Features

- **Tactical call** (Settings > Station): `tactical_call` (`CCEMA`),
  **Operate as the tactical call**, and **Identify with my callsign**
  (on). Operating as it makes the AX.25 source of connects and the call
  answered on the tactical call; the status bar shows `CCEMA` and `ID
  KC1JMH`; the phone's More shows the same (`welcome.station.on_air`).
  A change waits until no session is up. APRS, Winlink and VARA keep the
  real call.
- **Automatic identification** (`core/identifier.py`): `DE KC1JMH-7
  (CCEMA)` as a UI frame to `ID` from the real call when a link made under
  the tactical call ends (including one that never came up) and every 10
  minutes while one is up; debounced, only while operating as tactical,
  and a closed gate is said in words, never reported as sent. AGENTS.md's
  unattended-transmitter rule names it.
- `AX25Station.on_link_created` (each link as it is made); a Settings
  `optional` callsign field.

**Files:** `kissterm/identity.py`, `kissterm/core/identifier.py`,
`kissterm/ax25/station.py`, `kissterm/core/service.py`,
`kissterm/core/settings.py`, `kissterm/core/settings_schema.py`,
`kissterm/config.py`, `kissterm/serve/server.py`, `kissterm/ui/app.py`,
`kissterm/client/state.py`, `kissterm/client/ui/more.py`,
`config.toml.example`, `AGENTS.md`, `docs/GUIDE.md`, `docs/PROTOCOL.md`,
`docs/ON-AIR-TESTS.md`

## [2026-10-07] — Delivery and read receipts (P11)

### New Features

- **Outpost-style receipts** (Settings > Mail, four switches, off by
  default): ask for a Delivery and/or Read Receipt on private BBS messages
  you write (`!RDR!`/`!RRR!` at the start of the first line when sent; the
  stored text stays clean), and answer such a request by queueing
  `DELIVERED: <title>` (after a Send/Receive downloaded it) or `READ:
  <title>` (the first time it is opened) in the BBS Outbox. Nothing is
  sent unattended: the operator's next Send/Receive sends it. Received
  flags become `Request-DR`/`Request-RR` headers; a receipt from such a
  station is marked and never answered. Wire text from the Outpost 3.7
  guide and rothskeller/packet's `message/receipt` (read; no live capture
  yet, so the on-air check is in ON-AIR-TESTS). Opening a message on the
  phone now marks it read, as the terminal does (`Mail.opened`).

**Files:** `kissterm/mail/receipts.py`, `kissterm/mail/collect.py`,
`kissterm/mail/numbering.py`, `kissterm/core/mail.py`, `kissterm/config.py`,
`kissterm/core/settings_schema.py`, `kissterm/serve/server.py`,
`kissterm/ui/mail_pane.py`, `config.toml.example`, `docs/GUIDE.md`,
`docs/SOURCES.md`, `docs/ROADMAP.md`, `docs/ON-AIR-TESTS.md`

## [2026-10-07] — Numbered BBS messages (P11)

### New Features

- **Number my BBS messages** (Settings > Mail, off by default): a private
  or bulletin message written in either front end is titled
  `ABC-12P: title`, with a prefix (the callsign's last three, or
  Settings' own), a counter kept across restarts and never reused, and
  the P or B type letter. Not numbered: Winlink, forms, radiograms,
  replies by number, a title already numbered. The title gives way to a
  60-character BPQMail limit, never the number. Done once in
  `Mail.file_outbox`, so both front ends get it.

### Fixed

- `tests/unit/test_config.py`'s two CLI tests had a fake app without the
  `core.restarter` that `_amain` reads after a run (broken since the
  Restart work).

**Files:** `kissterm/mail/numbering.py`, `kissterm/core/mail.py`,
`kissterm/config.py`, `kissterm/core/settings_schema.py`,
`config.toml.example`, `docs/GUIDE.md`, `docs/ROADMAP.md`,
`docs/ON-AIR-TESTS.md`

## [2026-10-07] — Add a file from the phone's own storage

### New Features

- **Add file** on the Files folders of the web and phone client: pick a
  file on the device, it goes up to the station in pieces and is kept in
  Files > Uploads (cleaned name, never replaces a file, 1 MiB at most).
  Sending it by YAPP or AutoBIN is the file's Send over the radio, which
  asks first; adding transmits nothing. (`Mail.save_upload`, command
  `file_upload`; `Files/Uploads` joins the store's folders.) This closes
  the remote client's parity list.

**Files:** `kissterm/mail/store.py`, `kissterm/core/mail.py`,
`kissterm/serve/server.py`, `kissterm/client/ui/mail.py`,
`docs/PROTOCOL.md`, `docs/GUIDE.md`, `docs/ROADMAP.md`

## [2026-10-07] — Reply on form, Answer strip and Paste strip on the web and phone

### New Features

- **Reply on form** and **Answer strip** in the message reader (shown
  when the message is a form with a reply form, or carries an information
  strip), and **Information strip (paste)** in Mail > Write > Type: the
  terminal's three, on one core method each (`Mail.reply_choices`,
  `form_start(reply_to=)`, a `strip:` form key, `form_check`'s `next_form`,
  `write_form(reply_to=)`). The answer is a reply (SR to a BBS message
  number); nothing transmits until Send/Receive. `reply_form_for` moved to
  `mail/form_parse.py` so the core shares it.

**Files:** `kissterm/mail/form_parse.py`, `kissterm/ui/compose.py`,
`kissterm/core/mail.py`, `kissterm/serve/server.py`,
`kissterm/client/ui/forms.py`, `kissterm/client/ui/mail.py`, `docs/PROTOCOL.md`,
`docs/GUIDE.md`, `docs/ROADMAP.md`

## [2026-10-07] — BBS mail helpers on the web and phone

### New Features

- **Commands > BBS mail** in the phone and web client: pick a documented
  BBS command, give the message number or callsign, and Put in message box
  fills the box; nothing is sent. The station renders it
  (`Sessions.bbs_helpers`, `bbs_render`; commands `bbs_helpers`,
  `bbs_render`).

**Files:** `kissterm/core/sessions.py`, `kissterm/serve/server.py`,
`kissterm/client/ui/reference.py`, `docs/PROTOCOL.md`, `docs/GUIDE.md`,
`docs/ROADMAP.md`

## [2026-10-07] — Message forms on the web and phone

### New Features

- **Forms in Mail > Write > Type** (ICS-213, ICS-205, ICS-214, ICS-309,
  the Winlink check-in, damage assessment, severe weather and the rest):
  each on its own page laid out from the station's description of it
  (text, multi-line, choices, dates, ticks, tables of lines with Add and
  Remove, fields beside one another, the ICS-309's Fill from mail).
  **Next** checks it and opens the writer with the text, title and To it
  made; Save files it, and a Winlink message carries the form's XML unless
  the text was changed after. **Fill in** on a PKTNET page in the Files
  viewer opens that form. (Reply on form, Answer strip and
  Paste strip followed the same day.)
- Station side: `Mail.forms_list`, `form_start`, `form_check`,
  `form_mail_log`, `write_form` (commands `forms`, `form_start`,
  `form_check`, `form_mail_log`, `form_write`); the terminal's mail-log
  entries moved to `Mail.mail_log_entries`. A new scene in the phone
  screenshots.

**Files:** `kissterm/core/mail.py`, `kissterm/ui/app.py`,
`kissterm/serve/server.py`, `kissterm/client/ui/forms.py`,
`kissterm/client/ui/mail.py`, `kissterm/client/ui/files.py`,
`scripts/generate_phone_screenshots.py`, `assets/screenshot-phone-forms.png`,
`docs/PROTOCOL.md`, `docs/GUIDE.md`, `docs/ROADMAP.md`,
`tests/unit/test_core_mail_write.py`, `tests/unit/test_client_ui.py`

## [2026-10-07] — Send and receive files on the web and phone

### New Features

- **Send over the radio** on a file in Files (the terminal's S) and
  **Receive file** in Terminal > Commands (its File transfer dialog, in
  download mode): YAPP or AutoBIN over a connected session, after asking
  which session and protocol. The station runs it (`Transfers.begin`,
  command `transfer_start`, which answers at once; the outcome is a
  notice) and arms the gate for the named request. A file from the
  phone's own storage is not uploaded. On-air tests listed.

**Files:** `kissterm/core/transfers.py`, `kissterm/serve/server.py`,
`kissterm/client/ui/transfer.py`, `kissterm/client/ui/mail.py`,
`kissterm/client/ui/reference.py`, `docs/PROTOCOL.md`, `docs/GUIDE.md`,
`docs/ROADMAP.md`, `docs/ON-AIR-TESTS.md`, `tests/unit/test_core_sessions.py`,
`tests/unit/test_serve.py`, `tests/unit/test_client_ui.py`

## [2026-10-07] — RMS gateways on the web and phone

### New Features

- **RMS gateways** as the first row of Stations > Contacts (the terminal's
  F10 > Session): the saved Winlink gateways nearest first, by mode;
  choosing one, after asking, files it in the Address Book as the Winlink
  Dial. Refresh is there and waits on the Winlink API key, as in the
  terminal. The station does it all (`Mail.rms_gateways`, `rms_refresh`,
  `use_gateway`, now shared with the terminal's own choice).

**Files:** `kissterm/core/mail.py`, `kissterm/ui/app.py`,
`kissterm/serve/server.py`, `kissterm/client/ui/gateways.py`,
`kissterm/client/ui/stations.py`, `docs/PROTOCOL.md`, `docs/GUIDE.md`,
`docs/ROADMAP.md`, `tests/unit/test_core_mail.py`, `tests/unit/test_client_ui.py`

## [2026-10-07] — Open a file from Files on the web and phone

### New Features

- **Open on a file in Files** (the terminal's Enter): a zip's members as
  a list, a tap opening one a level deeper; Markdown and HTML formatted;
  other text. The station reads and prepares it (`file_open`,
  `files_view.describe`): in memory, never extracted, HTML's scripts and
  images dropped, Markdown images replaced by `[image: alt]` so nothing is
  fetched, links shown and never followed. `files_view.MAX_FILE` moved
  there from the viewer. A new scene in the phone screenshots.

**Files:** `kissterm/files_view.py`, `kissterm/ui/file_viewer.py`,
`kissterm/serve/server.py`, `kissterm/client/ui/files.py`,
`kissterm/client/ui/mail.py`, `scripts/generate_phone_screenshots.py`,
`assets/screenshot-phone-files.png`, `docs/PROTOCOL.md`, `docs/GUIDE.md`,
`docs/ROADMAP.md`, `tests/unit/test_files_view.py`, `tests/unit/test_serve.py`,
`tests/unit/test_client_ui.py`

## [2026-10-07] — The node's command reference and suggestions on the web and phone

### New Features

- **Terminal > Commands** (the terminal's F1 reference). The commands the
  node or BBS in effect understands, with the others reachable from it,
  each with its source and a sysop mark, a packet-radio **Glossary**, and
  a search. **Learn from node** shows the airtime range and the choice of
  list, then asks once; **Forget learned** asks first. A choice fills the
  message box and sends nothing. While typing, matching commands show
  over the box (the suggestion strip); a tap fills it.
- Station side: `Sessions.reference_view` and `Sessions.suggest`; commands
  `session_reference`, `session_suggest`, `session_harvest`,
  `session_forget_learned` and `glossary`. A new scene in the phone
  screenshots.

**Files:** `kissterm/core/sessions.py`, `kissterm/serve/server.py`,
`kissterm/client/ui/reference.py`, `kissterm/client/ui/sessions.py`,
`scripts/generate_phone_screenshots.py`, `assets/screenshot-phone-commands.png`,
`docs/PROTOCOL.md`, `docs/GUIDE.md`, `docs/ROADMAP.md`,
`tests/unit/test_core_sessions.py`, `tests/unit/test_client_ui.py`

## [2026-10-07] — An object's place as a grid square, MGRS or UTM on the web and phone

### Improvements

- **The object form has "Place as"**, as the terminal's: decimal degrees,
  a Maidenhead grid square, MGRS or WGS-84 UTM. The station converts it
  (`core.aprs.place_from`, now the one converter for both front ends) and
  answers a bad reference with what to enter, sending nothing.

**Files:** `kissterm/core/aprs.py`, `kissterm/serve/server.py`,
`kissterm/ui/dialogs.py`, `kissterm/client/ui/aprs_object.py`,
`assets/screenshot-phone-map.png`, `docs/PROTOCOL.md`, `docs/GUIDE.md`,
`docs/ROADMAP.md`, `tests/unit/test_core_aprs.py`, `tests/unit/test_client_ui.py`

## [2026-10-07] — APRS templates in the web and phone client

### New Features

- **Templates beside the message box in a conversation** (the terminal's
  Ctrl+R). The sheet shows the gateway the callsign is (the contact's own
  setting first, then the shipped directory) with its note, source and
  each command's confidence, and your saved messages, which can be added,
  edited and forgotten. A choice fills the message box and sends nothing.
  Three protocol commands on `Aprs.templates`, `template_save`,
  `template_forget`; a new scene in the phone screenshots.

**Files:** `kissterm/core/aprs.py`, `kissterm/serve/server.py`,
`kissterm/client/ui/templates.py`, `kissterm/client/ui/messages.py`,
`scripts/generate_phone_screenshots.py`, `assets/screenshot-phone-templates.png`,
`docs/PROTOCOL.md`, `docs/GUIDE.md`, `docs/ROADMAP.md`,
`tests/unit/test_core_aprs.py`, `tests/unit/test_client_ui.py`

## [2026-10-07] — The web and phone Monitor filters like the terminal's

### Improvements

- **More > Monitor has the terminal's filters.** A box for a callsign or
  text, a port picker, and switches for Supervisory, Unnumbered,
  Information and UI frames; loosening a filter brings back the frames it
  hid. The station's `FrameSeen` now carries each frame's type, calls and
  payload text so the client never parses AX.25, and a test checks that
  the two filters agree frame for frame.

### Housekeeping

- Closed the web-remote reload bug (operator, 2026-10-07: reloads fine
  after many returns to the browser). The browser client is the desktop
  front end: the native desktop GUI and its binaries are off the roadmap.

**Files:** `scripts/generate_phone_screenshots.py`, `assets/screenshot-phone-monitor.png`,
`kissterm/client/monitorfilter.py`, `kissterm/client/ui/more.py`,
`kissterm/client/state.py`, `kissterm/serve/wire.py`, `docs/PROTOCOL.md`,
`docs/GUIDE.md`, `docs/ROADMAP.md`, `tests/unit/test_client_monitorfilter.py`

## [2026-10-07] — The link backs off to shorter frames on a weak path

### Improvements

- **A stuck long frame no longer retries forever.** Sending a reply to
  Brian through WS1EC-2 put the whole message in one 180-byte frame; the
  node answered every poll but never took it (30 resends in 10 minutes,
  as on 2026-09-25). Now, when two polls in a row show the far end still
  wants the same frame, the link halves its frame size (floor 32 bytes),
  re-cuts the waiting data and sends it again, and doubles back up after
  clean frames. The configured paclen is the ceiling, so a good path
  still uses full frames. Logged in kissterm.log.

**Files:** `kissterm/ax25/session.py`, `kissterm/ax25/window.py`,
`kissterm/ax25/AGENTS.md`, `tests/loopback.py`,
`tests/unit/test_ax25_link.py`, `docs/GUIDE.md`, `docs/ON-AIR-TESTS.md`

## [2026-10-07] — The phone's mail folders are a tree

### Improvements

- **The folder dropdown on the phone's Mail, Bulletins and Files is now a
  tree.** Tap the folder row (it shows "BBS / Inbox") and a panel opens
  under it, as wide as the section switch: BBS and Winlink fold open and
  shut, a folder picks and closes the panel. The tree opens on the
  service holding the folder shown.

**Files:** `kissterm/client/ui/mail.py`, `scripts/generate_phone_screenshots.py`,
`assets/screenshot-phone-mail.png`, `docs/GUIDE.md`, `DESIGN.md`,
`tests/unit/test_client_ui.py`

## [2026-10-07] — The routing line says "Routing", with an arrow

### Improvements

- **"Routed W1BKW > WS1EC" is now "Routing ▸"** in the terminal reader
  and the phone's Mail, with no callsigns. The arrow says the line unfolds
  (T, or a tap) and turns to ▾ while the `R:` lines are shown. The phone
  draws it as a Material icon: its font has no U+25B8 and showed a box.
- **The `routed` field is gone from `mail_read`**, with `route_bbses`: the
  `R:` lines (`routing`) already carry each BBS.

**Files:** `kissterm/ui/mail_pane.py`, `kissterm/client/ui/mail.py`,
`kissterm/mail/bpqmail.py`, `kissterm/serve/server.py`,
`docs/PROTOCOL.md`, `DESIGN.md`, `docs/GUIDE.md`,
`tests/pilot/test_mail_pane.py`, `tests/unit/test_client_ui.py`

## [2026-10-07] — A restarted station brings the phone's page back

### Improvements

- **The browser page reloads after Restart station or Shut down.** The
  web client runs inside the station, so after a restart Flet's page
  stayed blank. The page now moves to `/restarting`, which waits for
  the station and opens the app again (the stored token signs it in);
  after a shutdown it says so and does the same if the station is
  started. The desktop client still reconnects by itself.
- **The `--serve` console says what is happening**: "Restarting kissterm
  (asked from a remote client)..." at the request, "Starting kissterm
  again..." before the new process, "shut down" after a shutdown.

**Files:** `kissterm/serve/http.py`, `kissterm/serve/headless.py`,
`kissterm/core/restart.py`, `kissterm/client/ui/more.py`,
`docs/GUIDE.md`, `docs/ON-AIR-TESTS.md`, `tests/unit/test_serve.py`,
`tests/unit/test_client_ui.py`

## [2026-10-07] — `--serve` says which version is running

### Improvements

- **`kissterm --serve` prints "kissterm <version> serving <callsign>"
  first**, so the console shows the version, and after a Restart that
  the new code is in. The phone's More already showed it.

**Files:** `kissterm/serve/headless.py`, `docs/GUIDE.md`,
`tests/unit/test_serve.py`

## [2026-10-07] — Shut down from the phone

### New Features

- **Shut down on the phone's More**, beside Restart station: the same
  disconnect-first sequence (forced after 5 s, watchdog after 15 s),
  but the station stays stopped; its confirmation says nothing remote
  can start it again. The terminal's Quit already does this locally.

**Files:** `kissterm/core/restart.py`, `kissterm/serve/headless.py`,
`kissterm/serve/server.py`, `kissterm/__main__.py`,
`kissterm/client/ui/more.py`, `kissterm/core/AGENTS.md`, `AGENTS.md`,
`docs/GUIDE.md`, `docs/PROTOCOL.md`, `docs/ON-AIR-TESTS.md`, tests

## [2026-10-07] — Restart kissterm, from the menu or the phone

### New Features

- **Session > Restart kissterm, and Restart station on the phone's
  More**: stops and starts kissterm again with the same command line
  (new code after an update; a reset for a station you are not at). It
  never refuses: beacons and runs stop, every session is disconnected,
  a DISC unanswered in 5 s is forced closed, and a watchdog restarts
  anyway after 15 s if shutdown hangs. Logged at WARNING with who asked.

**Files:** `kissterm/core/restart.py`, `kissterm/core/service.py`,
`kissterm/__main__.py`, `kissterm/serve/headless.py`,
`kissterm/serve/server.py`, `kissterm/ax25/station.py`,
`kissterm/aprs_conversations.py`, `kissterm/ui/app.py`,
`kissterm/ui/commands.py`, `kissterm/ui/dialogs.py`,
`kissterm/client/ui/more.py`, `AGENTS.md`, `docs/GUIDE.md`,
`docs/PROTOCOL.md`, `docs/ON-AIR-TESTS.md`, tests

## [2026-10-07] — Phone: the bulletin category list scrolls

### Improvements

- **Categories on the phone scrolls again**: WS1EC's 14 categories ran
  past the bottom of the screen with Save, and nothing scrolled (Flet's
  scrollable sheet only grows). The list scrolls in its own box, and any
  form sheet taller than the screen scrolls as a whole.

**Files:** `kissterm/client/ui/mail.py`, `kissterm/client/ui/sheets.py`,
`DESIGN.md`, `tests/unit/test_client_ui.py`

## [2026-10-07] — Files folders list on the phone

### Improvements

- **The phone's Files folders were always empty**: `mail_list` asked
  the message index, which holds no files. A Files folder now lists its
  files (name, size, date) from the same `MailStore.list_files` as the
  terminal, and tapping one shows the terminal's preview
  (`files_view.preview`). Opening a zip member or a formatted view stays
  terminal-only (ROADMAP P7a).
- On-air tests: a second YAPP download kept beside the first, and the
  phone's Files listing, delete, preview and Undo, ticked.

**Files:** `kissterm/mail/store.py`, `kissterm/files_view.py`,
`kissterm/serve/server.py`, `kissterm/ui/mail_pane.py`,
`kissterm/client/ui/mail.py`, `docs/GUIDE.md`, `docs/PROTOCOL.md`,
`docs/ROADMAP.md`, `docs/ON-AIR-TESTS.md`, tests

## [2026-10-06] — Bulletins: ask before a long read; small categories in one listing

### Improvements

- **More than 20 new bulletins asks first**: Newest 20 (the default),
  All, or None, on the terminal and the phone (`HowManyBulletins`), since
  each is read with its own command (72 on WS1EC-2's first run).
- **A category the list counts 20 or fewer in is listed whole** with
  `LB> CAT`, not window by window (NTS's 1 bulletin cost 7 windows).
- On-air tests: the phone's Get bulletins ticked (mobile web UI); Files
  and By Internet from the phone stay open.

**Files:** `kissterm/mail/bulletins.py`, `kissterm/mail/collect.py`,
`kissterm/core/questions.py`, `kissterm/core/mail.py`, `kissterm/serve/wire.py`,
`kissterm/ui/bulletin_screen.py`, `kissterm/ui/operator.py`,
`kissterm/client/ui/questions.py`, `docs/GUIDE.md`, `docs/PROTOCOL.md`,
`docs/ON-AIR-TESTS.md`, tests

## [2026-10-06] — On-air results: bulletins over the Internet

### Improvements

- **The first bulletin collection over the Internet passed on WS1EC-2**
  (SSH): the window form `LB> WX n-m` is confirmed, no longer marked
  unverified. Over the air, the same run failed twice right after `LC`
  (no reply, link failed after 11 retries); noted in ON-AIR-TESTS with
  how to capture it next time.

**Files:** `kissterm/mail/bulletins.py`, `docs/ON-AIR-TESTS.md`,
`docs/SOURCES.md`

## [2026-10-06] — Phone: Position, Map, Object on one row

### Improvements

- **Send position is "Position" on the phone**, so Position, Map and
  Object fit one row above the conversations instead of wrapping.

**Files:** `kissterm/client/ui/messages.py`, `kissterm/client/ui/aprs_map.py`,
`kissterm/client/ui/aprs_object.py`, `scripts/generate_phone_screenshots.py`,
`DESIGN.md`, `docs/GUIDE.md`, `tests/unit/test_client_ui.py`

## [2026-10-06] — Place, move and kill APRS objects from the map

### New Features

- **Place an object from the map.** Terminal: Insert on the map's list
  opens the object form at the map's centre (the `x`). Phone: a long
  press on the map, or **Object** beside Map; sending objects from the
  phone is new. Only the form's Send transmits, after asking on the
  phone, arming the gate as APRS > Object does.
- **Your objects show on your map at once**, marked as yours; on one,
  M or Move puts it somewhere new and Delete or Kill kills it.
- Protocol: `aprs_object_start` and `aprs_object`; map points carry
  `mine`.

### Fixes

- The phone's `command` takes its name positionally only, so a command
  argument called `name` (an object's) no longer collides with it.

**Files:** `kissterm/core/aprs.py`, `kissterm/geo/placemarks.py`,
`kissterm/serve/server.py`, `kissterm/client/connection.py`,
`kissterm/client/ui/shell.py`, `kissterm/client/ui/aprs_object.py`,
`kissterm/client/ui/aprs_map.py`, `kissterm/client/ui/messages.py`,
`kissterm/ui/map_screen.py`, `kissterm/ui/dialogs.py`, `kissterm/ui/app.py`,
`DESIGN.md`, `docs/GUIDE.md`, `docs/PROTOCOL.md`, `docs/ROADMAP.md`,
`docs/ON-AIR-TESTS.md`, `tests/unit/test_map.py`,
`tests/unit/test_client_ui.py`, `tests/pilot/test_aprs_map.py`,
`assets/screenshot-aprs-map.png`, `assets/screenshot-phone-map.png`

## [2026-10-06] — The APRS map, offline, on the phone and in the terminal

### New Features

- **A map of what was heard with a position**: stations (an APRS
  report or a grid square), objects and items with coordinates, and this
  station, with each one's reported distance and bearing, when it was
  heard and its comment. A killed object leaves the map. On the phone,
  **Map** beside Send position (drag, pinch, tap a point; Message opens
  a conversation); in the terminal, F10 > APRS > Map, drawn in braille
  dots over a nearest-first list (I, O, F, Enter; arrows and PgUp/PgDn
  on the map).
- **The map ships with kissterm** (Natural Earth, public domain, 1.8 MB):
  coast, country and state lines everywhere; zoomed in, US counties,
  main roads and highways, rivers, lakes and a detailed coast. No
  Internet needed. `map_points` on the protocol, from `Aprs.map_points`.

### Improvements

- `kissterm/geo.py` (bearing and distance) is now the `kissterm.geo`
  package's `distance` module; its imports are unchanged.

**Files:** `kissterm/geo/`, `scripts/build_basemap.py`,
`kissterm/core/aprs.py`, `kissterm/serve/server.py`,
`kissterm/client/ui/aprs_map.py`, `kissterm/client/ui/messages.py`,
`kissterm/ui/map_screen.py`, `kissterm/ui/app.py`,
`kissterm/ui/commands.py`, `kissterm/ui/styles.py`, `pyproject.toml`,
`scripts/generate_screenshot.py`, `scripts/generate_phone_screenshots.py`,
`assets/`, `DESIGN.md`, `AGENTS.md`, `docs/GUIDE.md`, `docs/PROTOCOL.md`,
`docs/ROADMAP.md`, `docs/SOURCES.md`, `docs/ON-AIR-TESTS.md`,
`tests/unit/test_map.py`, `tests/unit/test_client_ui.py`,
`tests/pilot/test_aprs_map.py`

## [2026-10-06] — Phone: Mail first, Sessions is Terminal

### Improvements

- **The places are Mail, Messages, Terminal, Stations, More**, and the
  app opens on Mail; Sessions is renamed Terminal. Code names the
  places (`shell.MAIL` ...) rather than numbering them.

### Fixes

- **No "Not connected to the station." at start**: the place in front
  loads once the connection is up, and again after a reconnect.
- **A message no longer shows twice** after mail arrived while another
  place was in front: Mail and Messages reload only while in front
  (a list rebuilt off screen was drawn with a duplicate row, Flet 1.0.3).

**Files:** `kissterm/client/ui/shell.py`, `kissterm/client/ui/mail.py`,
`kissterm/client/ui/messages.py`, `kissterm/client/ui/sessions.py`,
`kissterm/client/ui/questions.py`, `kissterm/client/ui/stations.py`,
`scripts/generate_phone_screenshots.py`, `assets/screenshot-phone*.png`,
`assets/screenshot-desktop.png`, `DESIGN.md`, `docs/GUIDE.md`,
`tests/unit/test_client_ui.py`

## [2026-10-06] — kissterm --serve stops on Esc or Ctrl+Q

### Improvements

- **Esc or Ctrl+Q stops `kissterm --serve`** at its terminal, as Ctrl+C
  does, shutting down the same way. Flow control is off while it runs
  so Ctrl+Q arrives, and the terminal's settings are restored on exit;
  an arrow key does not stop it, and with no terminal nothing changes.

**Files:** `kissterm/serve/headless.py`, `SETUP.md`, `docs/GUIDE.md`,
`tests/unit/test_serve_keys.py`

## [2026-10-06] — Radiograms from the phone

### New Features

- **NTS radiograms on the phone**: New Message's Type offers NTS
  radiogram (ST) and Radiogram-ICS213 (ST), which open the radiogram
  form, with the text converted as typed and the check, routing and
  title following each change. Save files it in the BBS Outbox.
- **One set of radiogram rules for both front ends**:
  `Mail.radiogram_start`, `radiogram_check`, `write_radiogram` and
  `radiogram_problems`; the terminal's form takes its number and its
  save check from them. Protocol: `radiogram_start`, `radiogram_check`,
  `radiogram_write`.

**Files:** `kissterm/core/mail.py`, `kissterm/serve/server.py`,
`kissterm/client/ui/radiogram.py`, `kissterm/client/ui/mail.py`,
`kissterm/ui/radiogram.py`, `kissterm/ui/app.py`, `docs/GUIDE.md`,
`docs/PROTOCOL.md`, `docs/ROADMAP.md`, `docs/ON-AIR-TESTS.md`,
`tests/unit/test_core_mail_write.py`, `tests/unit/test_serve.py`,
`tests/unit/test_client_ui.py`

## [2026-10-06] — Routing is one small line

### Improvements

- **A BBS message's routing is one line under the date**, "Routed
  W1BKW > WS1EC" (the BBSes in travel order), on the phone and in the
  terminal; a tap (T) shows the `R:` lines. The explanation is gone.
  Protocol: `mail_read` adds `routed`.

**Files:** `kissterm/mail/bpqmail.py`, `kissterm/serve/server.py`,
`kissterm/client/ui/mail.py`, `kissterm/ui/mail_pane.py`, `DESIGN.md`,
`docs/GUIDE.md`, `docs/PROTOCOL.md`, `tests/unit/test_client_ui.py`,
`tests/pilot/test_mail_pane.py`

## [2026-10-06] — Phone: All Inboxes; the pencil against the edge

### Improvements

- **All Inboxes on the phone**: first in Mail's folder list and where
  Mail opens, as on the terminal's Mail tab, each row marked BBS or
  Winlink. Protocol: `mail_list` takes `"All Inboxes"`.
- **Write's pencil lines up on the right** with Send/Receive, so both
  hug the screen's edge.

**Files:** `kissterm/serve/server.py`, `kissterm/client/ui/mail.py`,
`assets/screenshot-phone-mail.png`, `DESIGN.md`, `docs/GUIDE.md`,
`docs/PROTOCOL.md`, `tests/unit/test_serve.py`,
`tests/unit/test_client_ui.py`

## [2026-10-06] — Phone: Mail, Bulletins and Files as sections

### Improvements

- **Mail has three sections**, as the terminal has three tabs: a
  Mail | Bulletins | Files switch at the top of the page on the phone,
  and a rail place each on a wide screen; the title follows (BBS Mail,
  Bulletins, Files) and the folder list holds that section's folders.
- A section opens where it was left, else on its Inbox or first folder;
  Deleted is listed last and never opened by default.

**Files:** `kissterm/client/ui/mail.py`, `kissterm/client/ui/shell.py`,
`assets/screenshot-phone-mail.png`, `assets/screenshot-desktop.png`,
`DESIGN.md`, `docs/GUIDE.md`, `tests/unit/test_client_ui.py`

## [2026-10-06] — Phone: BBS Mail title, Write pencil, Beacon asks which

### Improvements

- **Mail is titled "BBS Mail"**, as Messages is "APRS messages".
- **Write is a small pencil above Send/Receive**, with no label, in
  place of the toolbar's Write button.
- **More > Send beacon asks Packet or APRS**: the beacon text once
  (Session > Send beacon) or one position report (APRS > Send position).

**Files:** `kissterm/client/ui/shell.py`, `kissterm/client/ui/mail.py`,
`kissterm/client/ui/more.py`, `scripts/generate_phone_screenshots.py`,
`assets/screenshot-phone-mail.png`, `DESIGN.md`, `docs/GUIDE.md`,
`docs/ON-AIR-TESTS.md`, `tests/unit/test_client_ui.py`

## [2026-10-06] — Web remote: coming back to the page works

### Improvements

- **A page left asleep starts afresh** rather than rejoining Flet's
  dropped session, which did not redraw and had already lost its
  station connection; the station replays its state to the new one.
- **The browser's kept key read is retried**; if it still does not
  answer, the page says so with Try again instead of staying blank.

**Files:** `kissterm/client/ui/web.py`, `docs/GUIDE.md`,
`docs/ROADMAP.md`, `tests/unit/test_client_ui.py`

## [2026-10-06] — Phone parity: Reconnect, bulletin categories, transcripts

### Improvements

- **Reconnect on the phone**: a chip in Disconnect's place once the
  session shown has dropped; after asking, the station redials it as
  Ctrl+R does (`Connector.reconnect`, now Ctrl+R's path too).
- **Categories** on a Bulletins folder: tick what Get bulletins
  collects, offline, as S does (`Mail.bulletin_categories`).
- **Transcripts** in More: past sessions, searched and read, by listed
  name only (`Sessions.transcripts`, `read_transcript`).
- Protocol: `reconnect`, `bulletin_categories`(`_save`), `transcripts`,
  `transcript_read`.

**Files:** `kissterm/core/connect.py`, `kissterm/core/mail.py`,
`kissterm/core/sessions.py`, `kissterm/serve/server.py`,
`kissterm/client/ui/shell.py`, `kissterm/client/ui/sessions.py`,
`kissterm/client/ui/mail.py`, `kissterm/client/ui/more.py`,
`kissterm/client/ui/transcripts.py`, `kissterm/ui/app.py`, `DESIGN.md`,
`docs/GUIDE.md`, `docs/PROTOCOL.md`, `docs/ROADMAP.md`,
`docs/ON-AIR-TESTS.md`, `tests/unit/test_core_parity_more.py`,
`tests/unit/test_serve.py`, `tests/unit/test_client_ui.py`

## [2026-10-06] — Phone parity: write, reply, reply all, delete, restore

### New Features

- **The phone writes mail**: Write on a Mail folder (private, bulletin
  or Winlink), and Reply, Reply all, Reply with quote and Delete (or
  Restore) in the reader. Save files it in the Outbox with the
  terminal's checks; nothing transmits until Send/Receive.
- **Swipe a message to delete it** (restore in Deleted), halfway to
  count, slide back to cancel, and Undo on the note (operator,
  2026-10-06).
- **The terminal's A replies to all** on a Winlink message with other
  recipients, for parity.
- The core does both front ends' writing, deleting and restoring
  (`Mail.reply_start`, `write`, `file_outbox`, `delete`, `restore`);
  protocol `mail_reply_start`, `mail_write`, `mail_delete`,
  `mail_restore`, and `reply_all` on `mail_read`.

**Files:** `kissterm/core/mail.py`, `kissterm/mail/compose.py`,
`kissterm/serve/server.py`, `kissterm/client/ui/mail.py`,
`kissterm/client/ui/sheets.py`, `kissterm/ui/app.py`,
`kissterm/ui/compose.py`, `kissterm/ui/mail_pane.py`, `DESIGN.md`,
`docs/GUIDE.md`, `docs/PROTOCOL.md`, `docs/ROADMAP.md`,
`docs/ON-AIR-TESTS.md`, `tests/unit/test_core_mail_write.py`,
`tests/unit/test_serve.py`, `tests/unit/test_client_ui.py`,
`tests/pilot/test_compose.py`

## [2026-10-06] — The web terminal is an opt-in: kissterm --web-terminal

### Improvements

- **The terminal UI in a browser is a separate, deliberate choice**
  (operator: "a toggle for web based terminal, vs the actual web UI,
  with the warning in the command line"). `kissterm --web-terminal
  [HOST:PORT]` runs it through `textual-serve` (the `webterm` extra),
  on 127.0.0.1:8765 by default, and first prints that it has no pairing
  and no login and that the remote control is the way for a browser.

**Files:** `kissterm/webterm.py`, `kissterm/__main__.py`, `pyproject.toml`,
`docs/GUIDE.md`, `SETUP.md`, `tests/unit/test_webterm.py`

## [2026-10-06] — Settings > Radio names the transport launch opened

### Improvements

- **With transports configured but none named in use**, Radio in use
  now shows the first one, the one launch opened, with its settings.
  It had said "No transport configured" beside it.

**Files:** `kissterm/ui/settings_pane.py`, `tests/pilot/test_settings.py`,
`docs/ROADMAP.md`

## [2026-10-06] — kissterm runs under textual-serve in a browser

### Improvements

- **With the modem off, kissterm under `textual-serve` starts** and
  shows the problem in the page. It had exited, since there was no
  terminal to ask "Start anyway?" on, and the browser said only
  "Application failed to start". Tried in Chromium: F9 and the rest
  of the keys work there. The GUIDE says how, and that it has no
  login. P6's TTY check is done.

**Files:** `kissterm/__main__.py`, `docs/GUIDE.md`, `docs/ROADMAP.md`,
`tests/unit/test_tcp_kiss_connect_timeout.py`

## [2026-10-06] — SETUP.md: a TNC on the Raspberry Pi's GPIO pins

### Improvements

- **SETUP.md section 2 covers a HAT TNC on the Pi's UART**: turning off
  the serial console, `disable-bt` on a Pi 3/4/Zero W, `/dev/serial0`
  (or `/dev/ttyAMA0` on a Pi 5) typed in, from Raspberry Pi's own
  documentation. Experimental until a HAT is tried. With the serial
  fallback and `dialout` notes already there, P7's Pi note is done.

**Files:** `SETUP.md`, `docs/ROADMAP.md`, `docs/SOURCES.md`

## [2026-10-06] — Two tests that failed under full-suite load wait on conditions

### Improvements

- **The scan-coverage test no longer races the clock**: the sweep's
  deadline now runs out after the first wave of probes has started,
  not after 0.5 s of wall time. With every core busy, the first wave
  had not started by then.
- **The drag-select test waits for the lines to be drawn**, and for the
  selection, rather than for one pause. Under load it had selected
  nothing (reproduced, then 6 of 6 passed).

**Files:** `tests/unit/test_scan_coverage.py`,
`tests/pilot/test_text_selection.py`, `docs/ROADMAP.md`

## [2026-10-06] — A tab key pressed at launch is no longer undone

### Improvements

- **A tab key pressed in the first moment after launch stays put.** F9
  went to Settings and then flipped back to Terminal: the send line's
  startup focus told the tab row "Terminal" after the key had moved on.
  The tab row now ignores that message once focus has left the pane
  (`ui/main_tabs.py`). Found by the test suite (ROADMAP P0.1).

**Files:** `kissterm/ui/main_tabs.py`, `kissterm/ui/app.py`,
`docs/ROADMAP.md`

## [2026-10-06] — Phone parity: bulletins, files, By Internet, position, beacon

### Improvements

- **The phone's Mail button does what G and I do** for the folder shown:
  Send/Receive or Get bulletins, each By radio or By Internet in one
  sheet (`sheets.choose`); on Files, Get files.
- **Send position** heads APRS messages, and **Send beacon** sits on
  More's station card; both ask first.

**Files:** `kissterm/client/ui/mail.py`, `kissterm/client/ui/messages.py`,
`kissterm/client/ui/more.py`, `kissterm/client/ui/sheets.py`,
`DESIGN.md`, `docs/GUIDE.md`, `docs/ROADMAP.md`,
`tests/unit/test_client_ui.py`

## [2026-10-06] — Terminal parity: routing (T) and cancelling a run (G)

### Improvements

- **The terminal's mail reader shows a message's routing**, folded as on
  the phone: "Routing: 2 BBSes (T shows it)" under the header, and T
  unfolds the `R:` lines. One function reads them for both readers
  (`bpqmail.routes_of`).
- **G cancels a run that is going** on Mail, Bulletins and Files, as the
  phone's turning button does; the Footer says "Cancel run".
- AGENTS.md: the front ends keep parity in functionality.

**Files:** `kissterm/ui/mail_pane.py`, `kissterm/ui/app.py`,
`kissterm/mail/bpqmail.py`, `kissterm/core/mail.py`, `AGENTS.md`,
`DESIGN.md`, `docs/GUIDE.md`, `tests/pilot/test_mail_pane.py`

## [2026-10-06] — Mail runs sign off with B; a message's routing on the phone

### Improvements

- **A Home BBS run ends with `B`**, as an operator would: the BBS's
  goodbye shows in the session and it hangs up; kissterm disconnects
  only if it has not within 30 s (10 s over the Internet). The outcome
  notice comes first, so a slow path never delays it. LinBPQ saves the
  same "last listed" record on a plain disconnect (`BBSUtilities.c`), so
  nothing changes at the BBS. Winlink runs end as before.
- **The phone's mail reader has a folded Routing section** with the
  message's `R:` lines (`mail_read` now carries `routing`), saying they
  are not the sender's address.

**Files:** `kissterm/mail/collect.py`, `kissterm/mail/bpqmail.py`,
`kissterm/core/mail.py`, `kissterm/serve/server.py`,
`kissterm/client/ui/mail.py`, `DESIGN.md`, `docs/GUIDE.md`,
`docs/PROTOCOL.md`, `docs/ON-AIR-TESTS.md`, tests

## [2026-10-06] — Send/Receive shows it is running and can be cancelled

### Improvements

- **On the phone, a running Send/Receive is visible**: the button's icon
  turns and the progress line counts dots; tapping it again cancels the
  run. The station gained `Mail.cancel` (`mail_cancel`, `MailRunChanged`):
  it stops the SABMs or disconnects the run's session, or stops an
  Internet run, and says "cancelled".

### Fixes

- **A mail run noticed a dropped link only after its 300 s idle
  timeout.** Both collectors now wake when the link's state changes.

**Files:** `kissterm/core/mail.py`, `kissterm/core/events.py`,
`kissterm/mail/collect.py`, `kissterm/mail/winlink_collect.py`,
`kissterm/serve/server.py`, `kissterm/client/state.py`,
`kissterm/client/ui/mail.py`, `DESIGN.md`, `docs/GUIDE.md`, `docs/PROTOCOL.md`,
`tests/unit/test_core_mail.py`, `tests/unit/test_client_ui.py`

## [2026-10-06] — Remote control: more terminal, a connect you can watch and cancel, its own icon

### Improvements

- **More room for the session.** The row above the terminal that
  repeated the session's name with Connect and Disconnect is gone:
  Connect ends the session tabs, and Disconnect is a chip beside the
  transmit switch.
- **A connect no longer freezes the screen.** It runs in the background;
  Sessions comes to the front at once, with an hourglass and Cancel over
  the session while the station calls. The station now tells clients
  which sessions are connecting (`ConnectingChanged` carries `keys`, the
  snapshot a `connecting` list), and ends an attempt only after its
  session has opened.
- **Stations opens on Contacts**, Heard second. **Titles drop the
  callsign**, and Messages is titled "APRS messages".
- **kissterm's own icon** replaces Flet's logo on the loading screen, the
  browser tab and the home screen (`scripts/generate_web_icons.py`).

**Files:** `kissterm/client/ui/sessions.py`, `kissterm/client/ui/shell.py`,
`kissterm/client/ui/stations.py`, `kissterm/client/state.py`,
`kissterm/client/ui/assets/icons/`, `kissterm/client/ui/assets/favicon.png`,
`kissterm/core/connect.py`, `kissterm/serve/wire.py`, `kissterm/serve/server.py`,
`scripts/generate_web_icons.py`, `scripts/generate_phone_screenshots.py`,
`pyproject.toml`, `DESIGN.md`, `docs/GUIDE.md`, `docs/PROTOCOL.md`,
`assets/screenshot-phone*.png`, `assets/screenshot-desktop.png`, tests

## [2026-10-06] — The pairing screen: a Settings button, and no pop-up once paired

### Improvements

- **Settings > Remote has a Pairing link button** that opens the link and
  QR code. Only the terminal shows it; a phone's Settings does not.
- **Turning remote control on opens the pairing screen only until a
  device has paired** with the link. The station remembers that a client
  signed in (a hash of the token, never the token); Rotate starts over.

**Files:** `kissterm/serve/pairing.py`, `kissterm/serve/server.py`,
`kissterm/ui/remote.py`, `kissterm/ui/settings_pane.py`,
`kissterm/ui/styles.py`, `kissterm/core/settings_schema.py`,
`docs/GUIDE.md`, `tests/pilot/test_remote_pairing.py`

## [2026-10-06] — Turning on remote control no longer freezes the terminal; the QR code shows

### Improvements

- **Turning on Remote control no longer freezes the screen.** Starting
  the server imported the web app (Flet, uvicorn) on the UI's own loop,
  5.6 s cold here and longer on a slow disk; a thread does it now, with
  a "Starting remote control..." notice, and the start itself takes
  about 20 ms.
- **The pairing screen opens when you turn it on** in Settings and Save,
  so the QR code is in front of you when the phone needs it. It does not
  open at launch with remote control already on.

**Files:** `kissterm/ui/remote.py`, `kissterm/ui/app.py`,
`kissterm/core/settings_schema.py`, `docs/GUIDE.md`,
`tests/pilot/test_remote_pairing.py`

## [2026-10-06] — Start without the modem: Enter skips the wait

### Improvements

- **Enter skips the startup wait for the modem.** With the modem
  software or TNC off, kissterm counted down its connect timeout with no
  way past it, though Telnet and SSH contacts need no modem. Enter now
  starts without it, stays on the usual tab, and says that Save on
  Settings > Radio opens the modem later. The half-open transport is
  closed so it does not keep redialling. Unix terminals only.

**Files:** `kissterm/__main__.py`, `kissterm/core/service.py`,
`kissterm/core/__init__.py`, `kissterm/ui/app.py`, `docs/GUIDE.md`,
`tests/unit/test_tcp_kiss_connect_timeout.py`, `tests/pilot/test_app_mounts.py`

## [2026-10-06] — Remote control on the README's front page

### Improvements

- **The README shows remote control**: the station's pairing dialog
  (now drawn running, `REMOTE 2`), the app in a laptop's browser (the side
  rail), and on a phone, each image large enough to read. The phone
  screenshots are now pairs, not a strip of four, and the GUIDE adds the
  laptop view.
- **A browser that joins late no longer pops up old alerts.** The replay
  that brings it the session text also carried past `Alert` and
  `SetupRequested` events, which it raised as new; they are now history.

**Files:** `README.md`, `docs/GUIDE.md`, `docs/PROTOCOL.md`,
`kissterm/client/state.py`, `tests/unit/test_client.py`,
`scripts/generate_phone_screenshots.py`, `scripts/generate_screenshot.py`,
`assets/screenshot-desktop.png`, `assets/screenshot-phone.png`,
`assets/screenshot-phone-connect.png`, `assets/screenshot-remote-pairing.png`

## [2026-10-06] — The remote control's terminal: a dark panel, real bold, a choice of colours

### Improvements

- **Sessions in the remote control are a terminal panel**, dark with grey
  text by default. More > Terminal picks Dark or Light and a text colour
  (Grey, Contrast, Green, Amber, Cyan) for that device, remembered by its
  browser; colours a node sends for a dark screen are darkened on a light
  panel. Bold text is 0xProto's own Bold (2.502, the release the Regular
  came from), about 210 KB more for a phone to load once.

**Files:** `kissterm/client/ui/text.py`, `sessions.py`, `more.py`, `shell.py`,
`web.py`, `desktop.py`, `assets/fonts/0xProto-Bold-NL.ttf`,
`tests/unit/test_client_ui.py`, `DESIGN.md`, `docs/GUIDE.md`,
`assets/screenshot-phone.png`

## [2026-10-06] — Phone screenshots of the remote control

### Improvements

- **The GUIDE shows the remote control on a phone**: the swipe that asks
  before connecting, the radio reminder, a session with transmit on, and
  an APRS conversation. `scripts/generate_phone_screenshots.py` drives
  the web client against a scratch station in a browser (a browserless
  server via `BROWSERLESS_WS`, or Playwright's Chromium), tapping by name
  through Flutter's accessibility tree and waiting on the station rather
  than the clock. New `screenshots` extra; `test_readme_assets` checks
  both screenshot scripts.

**Files:** `scripts/generate_phone_screenshots.py`, `assets/screenshot-phone.png`,
`pyproject.toml`, `tests/unit/test_readme_assets.py`, `docs/GUIDE.md`,
`README.md`, `AGENTS.md`, `kissterm/client/AGENTS.md`

## [2026-10-05] — A remote control for phones and browsers

### New Features

- **The station serves a remote control at its pairing link**
  (`kissterm/client/ui/`, ROADMAP P7a M8): a Flet web app for a phone's
  browser, installable to the home screen, with Sessions, Messages
  (APRS as conversations), Mail, Stations (Heard and Contacts) and More
  (station, Monitor, notices, Settings). The transmit switch is always in
  the top corner. **A swipe never transmits**: swiping a station opens a
  sheet, and only its button connects. Questions arrive as sheets;
  dragging one away is Cancel. Needs the new `web` extra; `kissterm
  --client LINK` opens it in a desktop window (`desktop` extra, not yet
  tried on a desktop).

### Improvements

- The Address Book over the protocol never sends a login script, and a
  save merges onto the saved contact; a transport question sends names,
  not config entries; `settings_save` announces `ConfigChanged`.
- A key named at the start of a sentence is capitalised ("The Transmit
  switch turns it back off").
- The rotate-link test waits for the rotation instead of one pause (it
  failed under parallel load).

**Files:** `kissterm/client/ui/` (new: `shell.py`, `sessions.py`,
`messages.py`, `mail.py`, `stations.py`, `more.py`, `settings.py`,
`questions.py`, `sheets.py`, `text.py`, `web.py`, `desktop.py`,
`assets/fonts/`), `kissterm/client/connection.py`, `state.py`,
`AGENTS.md`, `kissterm/serve/server.py`, `wire.py`,
`kissterm/core/wording.py`, `kissterm/ui/app.py`, `kissterm/__main__.py`,
`pyproject.toml`, `DESIGN.md`, `docs/GUIDE.md`, `SETUP.md`,
`docs/PROTOCOL.md`, `docs/ON-AIR-TESTS.md`,
`tests/unit/test_client_ui.py` (new), `test_serve.py`,
`test_core_wording.py`, `tests/pilot/test_remote_pairing.py`,
`docs/CHANGELOG.md`

## [2026-10-05] — The remote client's connection and model

### New Features

- **`kissterm/client/`** (ROADMAP P7a M8's second step): a remote
  client's connection to a station, which reconnects by itself and asks
  only for the events it missed, stops for good on a rotated link, and
  answers questions; and a model of the station built from the protocol
  alone. No screen yet. The server adds `aprs_conversations` and
  `aprs_thread` for reading APRS conversations remotely.

**Files:** `kissterm/client/` (new: `connection.py`, `state.py`,
`AGENTS.md`), `kissterm/serve/server.py`, `docs/PROTOCOL.md`, `AGENTS.md`,
`tests/unit/test_client.py` (new), `tests/unit/test_serve.py`,
`docs/CHANGELOG.md`

## [2026-10-05] — The remote server moves onto uvicorn, ready to serve a web client

### Improvements

- **The remote server runs on uvicorn and Starlette** (`kissterm/serve/
  http.py`, ROADMAP P7a M8's first step), inside kissterm's own loop, so
  the pairing port can serve the web client at `/` beside `/v1`. The
  protocol is unchanged and its tests pass as they were. The `serve`
  extra now installs uvicorn and Starlette too.

**Files:** `kissterm/serve/http.py` (new), `server.py`, `__init__.py`,
`AGENTS.md`, `kissterm/__main__.py`, `kissterm/ui/remote.py`,
`pyproject.toml`, `SETUP.md`, `docs/PROTOCOL.md`, `docs/CHANGELOG.md`

## [2026-10-05] — Remote control inside the terminal, and Remote pairing

### New Features

- **Settings > Remote > Remote control** runs the remote-control server
  inside the terminal UI: the screen and every client share the station,
  a question goes to both and the first answer wins, and the status bar
  shows `REMOTE` (with the client count) while it runs. Restarted when
  the port, interface or certificate changes.
- **Session > Remote pairing** shows the link and its QR code (drawn
  black on white whatever the theme), with Copy link, Rotate (confirmed
  first; every client is dropped) and Settings.

**Files:** `kissterm/ui/remote.py` (new), `ui/app.py`, `ui/dialogs.py`,
`ui/commands.py`, `ui/styles.py`, `kissterm/serve/pairing.py`,
`serve/server.py`, `core/settings_schema.py`, `core/wording.py`,
`config.toml.example`, `scripts/generate_screenshot.py`,
`assets/screenshot-remote-pairing.png` (new), `assets/`,
`tests/pilot/test_remote_pairing.py` (new), `tests/pilot/test_settings.py`,
`docs/GUIDE.md`, `DESIGN.md`, `AGENTS.md`, `docs/ON-AIR-TESTS.md`,
`docs/ROADMAP.md` (the core extraction item: shipped), `docs/CHANGELOG.md`

## [2026-10-05] — Settings help names no keys for remote clients

### Improvements

- **Settings help no longer names keys in the core's schema**: where it
  said "Ctrl+T" or "F10 > Session > RMS gateways" it now carries a
  wording token, so the terminal shows the same words as before and a
  remote client shows "the Transmit switch" or "RMS gateways". A
  menu-only command in a token is shown as its F10 menu path.

**Files:** `kissterm/core/settings_schema.py`, `core/wording.py`,
`kissterm/ui/operator.py`, `ui/settings_pane.py`, `kissterm/serve/server.py`,
`tests/unit/test_core_wording.py`, `tests/unit/test_serve.py`,
`docs/CHANGELOG.md`

## [2026-10-05] — Remote control server (experimental)

### New Features

- **`kissterm --serve`** runs the station with no screen for remote
  clients over a WebSocket (ROADMAP P7a M7; `docs/PROTOCOL.md`, now
  version 1). Paired by a link and QR code whose token is the same every
  launch and different on every machine; `--rotate-token` replaces it.
  Every command is the core's own method, so the transmit gate holds as
  at the keyboard. Settings > Remote: port, LAN or this machine only, a
  Public URL for a reverse proxy, or a certificate for native `wss://`.
  Needs the new `serve` extra. No client ships yet.

**Files:** `kissterm/serve/` (new: `pairing.py`, `wire.py`, `operator.py`,
`server.py`, `headless.py`, `AGENTS.md`), `kissterm/__main__.py`,
`config.py`, `core/settings_schema.py`, `config.toml.example`,
`pyproject.toml`, `tests/unit/test_serve.py` (new),
`tests/pilot/test_settings.py`, `docs/PROTOCOL.md`, `docs/GUIDE.md`,
`SETUP.md`, `AGENTS.md`, `docs/ON-AIR-TESTS.md`, `docs/CHANGELOG.md`

## [2026-10-05] — The core's messages name no keys

### Improvements

- **The core's notices name no key and no tab** (`kissterm/core/
  wording.py`, ROADMAP P7a M7's first step): where one would, it writes
  a token that each client renders. The terminal still says "Ctrl+T" and
  "the Monitor tab (F8)"; a phone or browser will say "the Transmit
  switch" and "the Monitor". Transcripts no longer add "(Ctrl+T)" to "Could
  not answer ... -- transmit is disabled".

**Files:** `kissterm/core/wording.py` (new), `aprs.py`, `connect.py`,
`sessions.py`, `mail.py`, `transfers.py`, `operator.py`, `AGENTS.md`,
`kissterm/ui/operator.py`, `kissterm/tx.py`,
`tests/unit/test_core_wording.py` (new), `tests/pilot/test_transmit_gate.py`,
`docs/CHANGELOG.md`

## [2026-10-05] — The channel and Settings move into the core

### Improvements

- **What the station hears is the core's** (`kissterm/core/channel.py`,
  ROADMAP P7a sixth step): the heard list, NET/ROM node claims, "mail
  for" beacons and watched callsigns, with every frame each way handed
  to clients for their monitor. The Address Book is loaded by the core.
- **Settings are saved and applied by the core** (`core/settings.py`,
  with the schema moved to `core/settings_schema.py`), so a phone or
  browser can edit the same settings with the same rules. Nothing changes
  on screen; checks on the air are in docs/ON-AIR-TESTS.md.

**Files:** `kissterm/core/channel.py` (new), `settings.py` (new),
`settings_schema.py` (moved from `kissterm/ui/`), `events.py`, `aprs.py`,
`service.py`, `AGENTS.md`, `kissterm/ui/app.py`, `settings_pane.py`,
`settings_schema.py` (now the core's with the theme list), `AGENTS.md`,
`kissterm/config.py`, `__main__.py`, `nodes/__init__.py`,
`tests/unit/test_core_channel_settings.py` (new),
`tests/unit/test_core_service.py`, `AGENTS.md`, `docs/ON-AIR-TESTS.md`,
`docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-10-05] — Mail, bulletins and files move into the core

### Improvements

- **Send/Receive is the core's** (`kissterm/core/mail.py`, ROADMAP P7a
  fifth step): G and I for the Home BBS and Winlink, Get bulletins, Get
  files, the message store and bulletin subscriptions, and every setup
  question, now asked as typed questions any client can draw. YAPP and
  AutoBIN transfers moved too (`core/transfers.py`), so only the core
  ever turns transmit on. Nothing changes on screen; checks on the air
  are in docs/ON-AIR-TESTS.md.

### Bug Fixes

- **Closing kissterm while a question was open could raise an error** on
  the way out: taking the question down read a screen stack that was
  already gone. It is now skipped at shutdown.

**Files:** `kissterm/core/mail.py` (new), `transfers.py` (new),
`questions.py`, `events.py`, `connect.py`, `service.py`, `AGENTS.md`,
`kissterm/ui/app.py`, `operator.py`, `dialogs.py`, `AGENTS.md`,
`tests/unit/test_core_mail.py` (new), `tests/pilot/test_transmit_gate.py`,
`AGENTS.md`, `docs/ON-AIR-TESTS.md`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-10-05] — APRS moves into the core

### Improvements

- **APRS is the core's** (`kissterm/core/aprs.py`, ROADMAP P7a fourth
  step): the decode on the frame fan-out, conversations and auto-ack,
  sending a typed message (which arms the gate), the ack-and-retry queue
  (now on the core's own timer, so it runs with the APRS tab never
  opened), objects, Send position, both beacons, GPS and the APRS-IS debug
  watch. The heard list moves with it. The APRS tab follows through
  events. Nothing changes on screen; checks on the air are in
  docs/ON-AIR-TESTS.md.

### Bug Fixes

- **A Settings save left the core on the old configuration** (since the
  connect flow moved, 0.1.399): Save replaces the app's configuration, and
  the core kept its own reference. `app.config` now reads through to the
  core's, so one configuration is in use.

**Files:** `kissterm/core/aprs.py` (new), `kissterm/core/events.py`,
`service.py`, `AGENTS.md`, `kissterm/ui/app.py`, `aprs_pane.py`,
`dialogs.py`, `AGENTS.md`, `kissterm/aprs_beacon.py`, `config.py`,
`heard.py`, `locator.py`, `kissterm/aprs/messages.py`,
`tests/unit/test_core_aprs.py` (new), `tests/pilot/test_app_mounts.py`,
`test_aprs_object_send.py`, `test_aprs_send.py`, `test_aprs_templates.py`,
`AGENTS.md`, `docs/ON-AIR-TESTS.md`, `docs/CHANGELOG.md`

## [2026-10-05] — Sessions move into the core

### Improvements

- **Every session is the core's** (`kissterm/core/sessions.py`, ROADMAP
  P7a third step): binding a link, transcripts and records, the typed-line
  send path, passive node identification and application tracking, the
  hop watch, the opt-in command harvest, the reply watch, incoming calls
  and stray polls. The Terminal follows it through events (bytes received,
  line sent, state changed); the pane itself no longer sends anything.
  Nothing changes on screen; checks on the air are in
  docs/ON-AIR-TESTS.md.

**Files:** `kissterm/core/sessions.py` (new), `kissterm/core/events.py`,
`connect.py`, `service.py`, `AGENTS.md`, `kissterm/ui/app.py`,
`terminal_pane.py`, `AGENTS.md`, `tests/unit/test_core_sessions.py` (new),
`tests/unit/test_core_connect.py`, `tests/pilot/_records.py`,
`tests/pilot/test_terminal_ux.py`, `tests/pilot/test_transcript_and_color.py`,
`AGENTS.md`, `docs/ON-AIR-TESTS.md`, `docs/CHANGELOG.md`

## [2026-10-05] — A bulletin test no longer fails by the calendar

### Bug Fixes

- **`test_g_offers_the_categories_then_files_the_chosen` failed from
  2026-10-05 on its own**: its listing (2026-10-02) fell outside the
  two-day window on the real clock. "Today" is now pinned to 2026-10-03
  in that test; kissterm itself was right. The other suite failure found
  with it, a tab key at launch being undone, is filed in ROADMAP P0.

**Files:** `tests/pilot/test_get_bulletins.py`, `docs/ROADMAP.md`,
`docs/CHANGELOG.md`

## [2026-10-05] — The connect flow moves into the core

### Improvements

- **Connecting is the core's** (`kissterm/core/connect.py`, ROADMAP P7a
  second step): arming the transmit gate, the radio reminder, the dial and
  its failure wording, Internet contacts, the session tier, hop chains,
  auto-login, Ctrl+D cancel and Ctrl+R's request. The reminder and the SSH
  trust question are typed questions the core asks, so another client can
  draw them its own way. Nothing changes on screen; a check on the air is
  in docs/ON-AIR-TESTS.md. A notice can no longer ask for a toast shorter
  than 10 seconds, whichever client shows it.

**Files:** `kissterm/core/connect.py`, `questions.py`, `hops.py`, `links.py`
(new), `kissterm/core/service.py`, `operator.py`, `AGENTS.md`,
`kissterm/ui/app.py`, `operator.py`, `dialogs.py`,
`tests/unit/test_core_connect.py` (new), `tests/unit/test_toast_dwell.py`,
`tests/pilot/test_connect_scripts.py`, `tests/pilot/test_terminal_ux.py`,
`AGENTS.md`, `kissterm/transport/AGENTS.md`, `docs/ROADMAP.md`,
`docs/ON-AIR-TESTS.md`, `docs/CHANGELOG.md`

## [2026-10-05] — The core begins: transports and the gate leave the Textual app

### Improvements

- **`kissterm/core/`**, the station with no user interface (ROADMAP P7a,
  first step). `Core` now owns the station, the transmit gate and the
  transport lifecycle (opening the first transport, switching live, moving
  every frame subscriber across). It speaks to a front end only through
  an `Operator` port (notices, typed questions) and a sequence-numbered
  event bus, so a WebSocket client can drive it later. Nothing changes on
  screen; a test fails if the core ever imports Textual.

**Files:** `kissterm/core/` (new), `kissterm/ui/operator.py` (new),
`kissterm/ui/app.py`, `kissterm/ui/terminal_pane.py`, `kissterm/__main__.py`,
`tests/unit/test_core_boundary.py`, `tests/unit/test_core_service.py`,
`AGENTS.md`, `kissterm/ui/AGENTS.md`, `docs/CHANGELOG.md`

## [2026-10-04] — G on Files and Bulletins says what it is getting

### Bug Fixes

- **G on Files said "Connecting to WS1EC-2 to send and receive mail"**
  (operator report). The Home BBS dial always named mail; it now says
  "to get files" or "to get bulletins", and a failure toast leads with
  "Get files:" or "Get bulletins:" instead of "Send/Receive:", over the
  Internet as well.

**Files:** `kissterm/ui/app.py`, `tests/pilot/test_get_files.py`,
`docs/CHANGELOG.md`

## [2026-10-04] — A failed YAPP transfer is cancelled at the BBS

### Improvements

- **When kissterm gives up on a YAPP transfer** (a timeout, a file it
  will not save, a local error), it sends YAPP `CAN` with the reason.
  BPQ then answers "File Rejected" and leaves YAPP mode; before, it
  stayed in it and ate the operator's next typed line ("Unexpected
  message during YAPP Transfer"). Not sent when the peer ended it.

**Files:** `kissterm/yapp.py`, `tests/unit/test_yapp.py`, `docs/GUIDE.md`,
`docs/SOURCES.md`, `docs/ON-AIR-TESTS.md`, `docs/CHANGELOG.md`

## [2026-10-04] — A screenshot of the bulletin category checklist

### Improvements

- **The guide shows the category checklist** the first G on Bulletins
  offers, drawn from WS1EC-2's own `LC` reply with its counts.

**Files:** `scripts/generate_screenshot.py`,
`assets/screenshot-bulletin-categories.png`, `docs/GUIDE.md`,
`docs/CHANGELOG.md`

## [2026-10-04] — kissterm.log is rotated at launch

### Improvements

- **kissterm.log no longer grows without limit**: at launch, one over
  5 MB becomes `kissterm.log.1`, the earlier ones move up, and three are
  kept. Only at launch, so a live session's log is never renamed under
  it (which fails on Windows while another kissterm has it open).

**Files:** `kissterm/__main__.py`, `tests/unit/test_log_rotation.py`,
`docs/GUIDE.md`, `docs/CHANGELOG.md`

## [2026-10-04] — ^T TX only on tabs that can transmit

### Improvements

- **The Footer shows `^T TX` only on Mail, Bulletins, Files, Terminal
  and APRS**, where a key can transmit; Heard, Monitor and Settings
  transmit nothing and no longer show it. Ctrl+T still works on every
  tab, and `TX OFF` stays in the status bar. The Help page's Mail,
  Bulletins and Files paragraphs now say which of their keys transmit
  (they said "Nothing here transmits", stale since G).

**Files:** `kissterm/ui/commands.py`, `tests/unit/test_commands.py`,
`DESIGN.md`, `assets/screenshot-heard.png`, `assets/screenshot-monitor.png`,
`assets/screenshot-settings.png`, `docs/CHANGELOG.md`

## [2026-10-04] — G on the Files tab gets files from the Home BBS

### New Features

- **G on the Files tab** dials the Home BBS by radio, sends `FILES`,
  and shows a checklist of what it lists with each file's size and
  airtime (and the total ticked), then downloads each ticked file by
  YAPP into Files > Downloads. The Terminal holds the binary while a
  file comes in; a name the BBS no longer has is noted and skipped.
  Radio only (no I), as SSH cannot carry YAPP. Built against WS1EC-2's
  2026-10-03 listing and LinBPQ's `YAPPSendFile`; not yet on the air.

**Files:** `kissterm/mail/bbs_files.py`, `kissterm/mail/collect.py`,
`kissterm/ui/bbs_files_screen.py`, `kissterm/ui/app.py`,
`kissterm/ui/mail_pane.py`, `tests/unit/test_bbs_files.py`,
`tests/pilot/test_get_files.py`, `tests/unit/data/bpqmail/`,
`docs/GUIDE.md`, `README.md`, `DESIGN.md`, `docs/ROADMAP.md`,
`docs/ON-AIR-TESTS.md`, `docs/CHANGELOG.md`, `assets/screenshot-files.png`

## [2026-10-04] — A first bulletin collection keeps its oldest day

### Bug Fixes

- **G on Bulletins no longer drops the first day of a first collection.**
  The cutoff was set to midnight with the clock's seconds left on, so a
  bulletin listed on that day (BPQ lists dates without a time) fell just
  before it and was never read, except in the first minute of an hour.
  Found when the Bulletins test failed at 02:21.

**Files:** `kissterm/mail/collect.py`, `tests/unit/test_mail_bulletins.py`,
`docs/CHANGELOG.md`

## [2026-10-04] — A clicked tab is focused like a tab opened by its key

### Bug Fixes

- **Clicking a tab's label focuses that tab's list or input**, as its F
  key always did: a click left focus on the tab row, so Bulletins showed
  no G or I until the list was clicked, Mail and Files lost their keys,
  and on Terminal, APRS and Monitor typing went nowhere.

**Files:** `kissterm/ui/app.py`, `tests/pilot/test_tab_focus.py`,
`tests/pilot/test_mail_pane.py`, `DESIGN.md`, `docs/CHANGELOG.md`

## [2026-10-04] — The file picker has a Choose button

### Improvements

- **Browse files has a Choose button** beside Cancel, doing what Enter
  does on the highlighted row (open a folder, pick a file); it had only
  Cancel, so the way to pick was a key it never showed. DESIGN.md now
  asks every list dialog for such a button, and a test checks it. The
  YAPP upload to WS1EC-2 worked over the air with it.

**Files:** `kissterm/ui/dialogs.py`, `tests/unit/test_dialog_consistency.py`,
`tests/pilot/test_files_downloads.py`, `DESIGN.md`, `docs/GUIDE.md`,
`SETUP.md`, `docs/CHANGELOG.md`

## [2026-10-04] — File transfers refused over SSH

### Improvements

- **`YAPP <name>` is not sent over SSH**: WS1EC's SSH login runs
  `telnet` into BPQ in line mode, which held kissterm's YAPP replies
  until the next line typed, so the download stalled and the BBS read
  later lines as YAPP data (operator's test). The line stays in the send
  field with a notice; File transfer and S on Files are refused there
  too. Over the air nothing changes.

**Files:** `kissterm/ui/app.py`, `kissterm/ui/terminal_pane.py`,
`tests/pilot/test_session_transport.py`, `docs/GUIDE.md`, `SETUP.md`,
`docs/ON-AIR-TESTS.md`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-10-03] — PKTNET ICS-213, FSR, Severe WX and Form 309 forms

### New Features

- **Four more PKTNET forms**, in the pages' own layouts (Winlink's stay
  as they were): ICS-213, Field Situation Report, Severe Weather Report
  and Form 309 Log. Mail > Insert offers them, and Enter on the page in
  the Files viewer opens them. Each is tested against its page's own
  Generate handler.

### Improvements

- **A received form reads a number and its unit apart** (`14. High Wind
  Speed: 45 MPH`): a choice variable straight after another matches only
  its choices.

**Files:** `kissterm/mail/data/forms/pktnet_ics213.toml`,
`kissterm/mail/data/forms/pktnet_fsr.toml`,
`kissterm/mail/data/forms/pktnet_severe_wx.toml`,
`kissterm/mail/data/forms/pktnet_form309.toml`, `kissterm/mail/form_parse.py`,
`kissterm/files_view.py`, `tests/tools/pktnet_generate.js`,
`tests/unit/test_pktnet_forms.py`, `tests/unit/data/pktnet/`, `docs/GUIDE.md`,
`docs/PROTOCOL_GUIDE.md`, `docs/CHANGELOG.md`

## [2026-10-03] — Enter fills in a PKTNET form from the Files viewer

### New Features

- **Enter on a PKTNET form page** (vden.org/pktnet, the zips WS1EC-2 offers)
  opens kissterm's form for it: a new PKTNET Bulletin form, the PKTNET
  Check-in, or the NTS radiogram. It goes to compose and the Outbox like
  any form. Each kissterm form is tested against the page's own Generate
  handler, run under Node with jQuery stubbed.

**Files:** `kissterm/files_view.py`, `kissterm/ui/file_viewer.py`,
`kissterm/ui/app.py`, `kissterm/mail/data/forms/pktnet_bulletin.toml`,
`tests/tools/pktnet_generate.js`, `tests/unit/test_pktnet_forms.py`,
`tests/unit/data/pktnet/`, `tests/pilot/test_files_downloads.py`,
`assets/screenshot-file-viewer.png`, `docs/GUIDE.md`, `docs/PROTOCOL_GUIDE.md`,
`DESIGN.md`, `docs/CHANGELOG.md`

## [2026-10-03] — Files viewer: zips, Markdown and HTML

### New Features

- **Enter on a file opens it full screen**: a zip lists its files and
  opens each one, read in memory and never unpacked to disk; Markdown is
  shown formatted; HTML is converted to Markdown with the standard library
  (no scripts run, nothing fetched, links never followed, form boxes drawn
  as blanks). A click still previews; a zip's preview lists its files.

**Files:** `kissterm/files_view.py`, `kissterm/ui/file_viewer.py`,
`kissterm/ui/mail_pane.py`, `scripts/generate_screenshot.py`,
`assets/screenshot-file-viewer.png`, `tests/unit/test_files_view.py`,
`tests/unit/data/pktnet/bulletin.html`, `tests/pilot/test_files_downloads.py`,
`docs/GUIDE.md`, `DESIGN.md`, `docs/CHANGELOG.md`

## [2026-10-03] — Browse files no longer crashes

### Bug Fixes

- **Browse files in the File transfer dialog opens the picker**: its
  helper was named `_render`, which replaced the method Textual draws a
  widget with, and the first redraw crashed the app. A new test fails if
  any kissterm widget replaces a private Textual method unlisted.

**Files:** `kissterm/ui/dialogs.py`, `tests/unit/test_textual_overrides.py`,
`tests/pilot/test_files_downloads.py`, `docs/CHANGELOG.md`

## [2026-10-03] — A YAPP download starts by itself when you ask for it

### Improvements

- **`YAPP <name>` typed at a BPQ BBS downloads the file without arming
  anything**: the BBS's send init within a minute of asking starts the
  download into Files > Downloads, the status bar counts the bytes and
  the Terminal stays quiet. A sender nobody asked for is ignored. The
  File transfer dialog's Download stays for AutoBIN.

**Files:** `kissterm/ui/app.py`, `kissterm/yapp.py`, `kissterm/ui/dialogs.py`,
`tests/pilot/test_files_downloads.py`, `docs/GUIDE.md`, `SETUP.md`,
`docs/ON-AIR-TESTS.md`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-10-03] — YAPP speaks BPQ's two-byte control packets

### Bug Fixes

- **A YAPP download from a BPQ BBS works**: kissterm read BPQ's opening
  `ENQ 1` as the start of a longer packet and never answered, so the
  download timed out while the BBS waited (WS1EC-2, over the air). YAPP's
  control packets are two bytes; only the header, data, refusal and
  cancel carry a length (LinBPQ `BBSUtilities.c`). An upload had the same
  fault, sent 256-byte packets BPQ reads as empty, and now reports a
  BBS's refusal with its reason ("already exists").

**Files:** `kissterm/yapp.py`, `tests/unit/test_yapp.py`, `docs/SOURCES.md`,
`docs/CHANGELOG.md`

## [2026-10-03] — Two crashes over SSH; no secrets in a crash report

### Bug Fixes

- **G on Mail no longer crashes while an SSH or Telnet session is open**:
  the "already connected" check read the session's peer, a host name,
  as an AX.25 address.
- **No crash 25 s after a line typed over SSH or Telnet**: the "no reply
  yet" note read AX.25 sequence numbers a session link does not have.
- **A crash report no longer prints local variables**: Textual's showed
  the Winlink password among them. The report (stack only) also goes to
  kissterm.log, and password-holding options are left out of their repr.

**Files:** `kissterm/ui/app.py`, `kissterm/mail/collect.py`,
`kissterm/mail/winlink_collect.py`, `tests/pilot/test_session_transport.py`,
`tests/pilot/test_crash_report.py`, `tests/unit/test_login_mask.py`,
`docs/CHANGELOG.md`

## [2026-10-03] — Files tab: Delete, U and S

### New Features

- **S on the Files tab sends the highlighted file** over the connected
  session, opening the YAPP/AutoBIN dialog with the file filled in;
  shown only while a session is connected, and nothing goes out before
  Start.

### Improvements

- **Delete works on files**: moves one to a new Files > Deleted folder,
  and U puts it back where it was, under its own name (a hidden note
  beside it records both).

**Files:** `kissterm/mail/store.py`, `kissterm/ui/mail_pane.py`,
`kissterm/ui/app.py`, `kissterm/ui/dialogs.py`, `tests/unit/test_mail_store.py`,
`tests/pilot/test_files_downloads.py`, `tests/pilot/test_mail_pane.py`,
`docs/GUIDE.md`, `DESIGN.md`, `docs/ROADMAP.md`, `assets/screenshot-files.png`,
`docs/CHANGELOG.md`

## [2026-10-03] — Downloads in Files > Downloads

### Improvements

- **A YAPP or AutoBIN download is saved in Files > Downloads** and shows
  in the Files tab (F4) at once; it went to the state folder's
  `downloads`, out of sight. The toast names it. Received is kept for
  files that arrive unattended (ROADMAP P9).
- **A YAPP download never overwrites an earlier file of the same name**:
  it is saved as `name-1.ext`, as AutoBIN already did.

**Files:** `kissterm/ui/app.py`, `kissterm/ui/dialogs.py`, `kissterm/yapp.py`,
`tests/unit/test_yapp.py`, `tests/pilot/test_files_downloads.py`,
`docs/GUIDE.md`, `SETUP.md`, `README.md`, `docs/ON-AIR-TESTS.md`,
`docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-10-03] — Get bulletins: G, I and S on the Bulletins tab

### New Features

- **G on the Bulletins tab gets bulletins from the Home BBS** (I over the
  Internet). The first time, the BBS's categories are offered as a
  checklist with their counts, plus All; a category that appears later is
  offered at the next check (Settings > Mail > Category check, 7 days),
  and one left unticked is not offered again. **S** changes the choice
  offline. The first collection from a category goes back Settings > Mail
  > First collection (7 days). Filed under Bulletins, one folder per
  category.

**Files:** `kissterm/ui/bulletin_screen.py`, `kissterm/ui/app.py`,
`kissterm/ui/mail_pane.py`, `kissterm/ui/styles.py`,
`kissterm/ui/settings_schema.py`, `kissterm/config.py`,
`kissterm/mail/bulletins.py`, `config.toml.example`,
`tests/pilot/test_get_bulletins.py`, `tests/pilot/test_get_mail.py`,
`docs/GUIDE.md`, `README.md`, `DESIGN.md`, `docs/ON-AIR-TESTS.md`,
`docs/ROADMAP.md`, `docs/CHANGELOG.md`, `assets/screenshot-bulletins.png`

## [2026-10-03] — Bulletins: a first run that works without paging

### Improvements

- **A first collection from a category asks for numbered windows**
  (`LB> WX 3005-3104`, then the hundred before, while every bulletin is
  still inside the N days), back from the greeting's latest number or
  `LL 1`'s. Most users do not page (operator), and a bare listing of 310
  WX bulletins cannot be stopped once it starts; `A` at a page prompt
  remains for those who do.

**Files:** `kissterm/mail/bulletins.py`, `kissterm/mail/collect.py`,
`tests/unit/test_mail_bulletins.py`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-10-02] — Bulletin collection: the BBS conversation

### New Features

- **Collecting bulletins by category, the part that talks to the BBS**
  (no key yet; ROADMAP P2 has the screens left). `LC` on the first run
  and then weekly, new categories offered once and declined ones
  remembered, `LB> <category> <n>-` asking only for what is newer, and a
  first run that goes back 7 days, ending the listing with `A`. Built
  from LinBPQ's source and checked against the operator's WS1EC-2
  capture (`LC`, `LB> WX`, `R 3104`).

**Files:** `kissterm/mail/bulletins.py`, `kissterm/mail/collect.py`,
`kissterm/mail/store.py`, `tests/unit/test_mail_bulletins.py`,
`tests/unit/data/bpqmail/`, `docs/SOURCES.md`, `docs/ROADMAP.md`,
`docs/CHANGELOG.md`

## [2026-10-02] — Copying from the Terminal no longer crashes

### Improvements

- **A mouse selection that starts below the last line of the Terminal
  copies nothing instead of crashing kissterm** (`IndexError` in
  Textual's `Selection.extract`, which indexes the start line unchecked).

**Files:** `kissterm/ui/wraplog.py`, `tests/pilot/test_wraplog_selection.py`,
`docs/CHANGELOG.md`

## [2026-10-02] — Status bar shows every field whole; themes in order

### Improvements

- **A job's progress is no longer cut off** ("Checking for" without
  "mail", the link state and retry count likewise): each status field is
  as wide as its text and only the spare room is shared out, where equal
  shares hid the rest of a long field on a line nobody sees.
- **The theme list is alphabetical**, with Custom last.

**Files:** `kissterm/ui/app.py`, `kissterm/ui/themes.py`,
`tests/unit/test_status_row.py`, `tests/unit/test_themes.py`, `DESIGN.md`,
`assets/*.png`, `docs/CHANGELOG.md`

## [2026-10-02] — A Midnight Commander theme

### New Features

- **`midnight-commander` theme** (Settings > Appearance): mc's standard
  skin, lightgray on blue with a black-on-cyan cursor bar, menu and
  footer and yellow column headings, transcribed from mc's
  `misc/skins/default.ini` in the Linux console's VGA colours, so it
  survives a terminal without truecolor almost unchanged. The GUIDE now explains why the other themes look off when
  `COLORTERM` is not set (Tokyo Night's panels turn navy over SSH).

**Files:** `kissterm/ui/themes.py`, `kissterm/ui/app.py`, `kissterm/ui/styles.py`,
`tests/unit/test_themes.py`, `config.toml.example`, `docs/GUIDE.md`,
`docs/SOURCES.md`, `docs/CHANGELOG.md`

## [2026-10-02] — Screenshots drawn with Pillow, no browser

### Improvements

- **The README screenshots are drawn cell by cell** (`scripts/cellshot.py`,
  Pillow, 0xProto Nerd Font, downloaded once from a pinned Nerd Fonts
  release and checked by SHA-256). Box-drawing and block characters are
  drawn from their Unicode names, so every border joins; a glyph the font
  lacks comes from an installed monospace font, as a terminal falls back.
  The browserless renderer (`KISSTERM_SHOT_RENDERER`) is gone: it refused
  any page scale but 1, then every page. All ten screenshots regenerated.

**Files:** `scripts/cellshot.py`, `scripts/generate_screenshot.py`,
`tests/unit/test_cellshot.py`, `assets/*.png`, `AGENTS.md`,
`pyproject.toml`, `docs/CHANGELOG.md`

## [2026-10-02] — Status bar: the right-most field keeps its last letter

### Improvements

- **`LOGGING` no longer shows as `LOGGIN`.** Textual drew the status
  table one cell wider than the padded bar and cropped it; the margin is
  now the table's own. Found once the heard count stopped being the field
  that lost its letter.

**Files:** `kissterm/ui/app.py`, `kissterm/ui/styles.py`, `docs/CHANGELOG.md`

## [2026-10-02] — Settings: the editor stays on its row when the list scrolls

### Improvements

- **Scrolling with a field open no longer leaves its editor floating** over
  other rows. The editor moves with its row, and closes (keeping what was
  typed) once the row scrolls out of sight.

**Files:** `kissterm/ui/settings_pane.py`, `tests/pilot/test_settings.py`,
`docs/CHANGELOG.md`

## [2026-10-02] — SSH to WS1EC: one echo, no password, a short name

### Improvements

- **A line typed over Telnet or SSH shows once.** BPQ's Telnet port echoes
  everything but the password (`TelnetV6.c`); the session adapter now drops
  bytes that repeat what was just sent, and delivers them after all the
  moment they differ, so nothing the node said is lost.
- **A saved login's password is masked** as `********` in the Terminal and
  the transcript; it was written there in plain text.
- **The status bar names an Internet peer briefly**: `KC1UIX-3 via WS1EC`,
  where the full `user@host:port` made the field wrap to "kc1uix-3 via".

**Files:** `kissterm/ui/app.py`, `tests/unit/test_session_echo.py`,
`tests/unit/test_login_mask.py`, `tests/unit/test_status_row.py`,
`tests/pilot/test_connect_scripts.py`, `tests/pilot/test_session_transport.py`,
`docs/GUIDE.md`, `docs/ON-AIR-TESTS.md`, `docs/CHANGELOG.md`

## [2026-10-02] — Status bar: no TNC port, no heard count

### Improvements

- **Room for a job's progress.** The transport field shows the TNC's host
  without its port (`10.6.26.128`, not `10.6.26.128:8001`; a bare IPv6
  address is left whole), and the heard count is gone (the Heard tab has
  it). On a crowded bar a Send/Receive step such as "Checking for mail"
  was cut to "Checking". Screenshots not regenerated: the renderer still
  fails on pages that load Google Fonts.

**Files:** `kissterm/ui/app.py`, `DESIGN.md`,
`tests/unit/test_status_row.py`, `tests/pilot/test_app_mounts.py`,
`docs/CHANGELOG.md`

## [2026-10-02] — Sources of what kissterm knows about the far end

### Improvements

- **`docs/SOURCES.md`** lists what each node, BBS and chat reference rests
  on: the LinBPQ and JNOS source files read (with commits and dates), G8BPQ's
  documentation, where the two disagreed, and the captured sessions. Linked
  from AGENTS.md, the README and the guide; `bpqmail.toml` now cites
  `BBSUtilities.c`.

**Files:** `docs/SOURCES.md`, `AGENTS.md`, `README.md`, `docs/GUIDE.md`,
`kissterm/nodes/data/bpqmail.toml`, `docs/CHANGELOG.md`

## [2026-10-02] — BPQ node and Chat commands, checked against LinBPQ

### Improvements

- **Node abbreviations are the ones the node accepts.** LinBPQ takes the
  first `COMMANDS[]` entry a word fits (`Cmd.c`), so NRR is NR, APRS is AP,
  and PASSWORD has no short form. T/TALK, never in the table, is gone; NC
  (connect offering AX.25 2.2), NPING and STREAMS are added; APRS lists
  STATUS, `?` and the sysop-only BEACON.
- **BPQChat** gains `/H` and `/?` (help), `/HISTORY` (`/HI`) and
  `/COLOURS`, with the short forms `HanksRT.c` matches (`/KEEP`, `/SHOW`,
  `/UTF`, `/COD`). `/Q` is QTH; only `/QUIT` disconnects.

**Files:** `kissterm/nodes/data/bpq32.toml`,
`kissterm/nodes/data/bpqchat.toml`, `tests/pilot/test_terminal_ux.py`,
`docs/CHANGELOG.md`

## [2026-10-02] — JNOS: the mailbox a caller reaches, from its source

### Improvements

- **The JNOS reference is the mailbox, not the console.** A caller lands
  in JNOS's mailbox (`mailbox.c` `Mbcmds`), so the old list (`ftp`, `route`,
  `who`, written from memory) never applied. Commands and abbreviations now
  follow the table order `cmdparse` matches in (CO is CONNECT, AL is AREA,
  RE is READ), with the L/K/R/S/X two-letter forms.
- **A JNOS node is recognised by its prompt** (the `?,A,B,...,X >` menu
  line or the expert `(#N) >`) and by its real greeting and SID, not the
  bare word "JNOS". Unverified on air; the test is in ON-AIR-TESTS.

**Files:** `kissterm/nodes/data/jnos.toml`, `tests/unit/test_nodes.py`,
`tests/pilot/test_terminal_ux.py`, `docs/ON-AIR-TESTS.md`,
`docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-10-02] — A BPQ node with no alias is recognised

### Improvements

- **`CALL}` is a BPQ node too.** A node with no alias answers `WS1EC-15}`
  rather than `CCEMA:WS1EC-15}` (LinBPQ `Cmd.c`, `DecodeNodeName`), and
  showed as an unknown node.

**Files:** `kissterm/nodes/data/bpq32.toml`, `tests/unit/test_nodes.py`,
`docs/CHANGELOG.md`

## [2026-10-02] — BPQMail: mail kissterm could not list or finish reading

### Improvements

- **Every listing shape BPQMail prints is read.** Mail with no `@BBS` and
  bulletins to a To of 7+ characters (`WEATHER@ALLUS`) were skipped by
  `LM`/`L`, so never fetched. **A read from Winlink or email finishes**:
  its end marker carries `@winlink.org` or an address after the sender,
  which kissterm took for an unfinished read and stopped on. Found by
  reading LinBPQ's `BBSUtilities.c` (`ListMessage`, `SendMessage`); tests
  build each line with BPQMail's own formats.

**Files:** `kissterm/mail/bpqmail.py`, `tests/unit/test_mail_bpqmail.py`,
`docs/CHANGELOG.md`

## [2026-10-02] — The Terminal holds only the session

### Improvements

- **No more `***` notes in the Terminal.** It shows what the node sent
  and what was sent to it; kissterm's notes (connecting, connected,
  auto-login, hop and mail progress, transmit enabled) go to the
  session's transcript, or kissterm.log when a connect never came up.
  Anything that was only a note is now a toast (a link error, a stray
  poll, a reply that never came, learned commands); beacons and APRS
  sends show in the Monitor. A failed connect's toast now carries the
  attempt count and a dropped TNC link. Operator request, 2026-10-02.

### New Features

- **Transcripts button on the Monitor tab**: the same list as Session >
  Transcripts, beside the frames.

**Files:** `kissterm/ui/app.py`, `kissterm/ui/monitor_pane.py`,
`kissterm/ui/terminal_pane.py`, `DESIGN.md`, `AGENTS.md`, `docs/GUIDE.md`,
tests (`tests/pilot/_records.py` and 17 pilot files), `docs/CHANGELOG.md`

## [2026-10-02] — The Terminal starts empty; the name leaves the status bar

### Improvements

- **No startup banner in the Terminal.** It repeated the title bar, the
  Footer and the status bar; the Terminal holds only what a node sent and
  what you sent. **The status bar no longer starts with "kissterm" and its
  version**; the title bar shows both, and the remaining fields share the
  row. Operator request, 2026-10-02. Screenshots not regenerated: the
  renderer could not load its web font.

**Files:** `kissterm/ui/app.py`, `tests/pilot/test_app_mounts.py`, `DESIGN.md`,
`docs/CHANGELOG.md`

## [2026-10-02] — Removed: Winlink through the node

### Improvements

- **Settings > Mail > Internet server is back to Winlink and Test.**
  "Through the node" (0.1.354-0.1.355) is gone: BPQ's Telnet user port
  echoes every byte and treats 0x08/0x7F as erase (LinBPQ `TelnetV6.c`),
  so Winlink cannot run over it, and the node would reach the same CMS
  anyway. AGENTS.md now says to read the far end's source first.
  Operator decision, 2026-10-02.

**Files:** `kissterm/mail/winlink_collect.py`, `kissterm/ui/app.py`,
`kissterm/config.py`, `kissterm/ui/settings_schema.py`,
`kissterm/transport/ssh.py`, `config.toml.example`, tests, `docs/GUIDE.md`,
`README.md`, `docs/ON-AIR-TESTS.md`, `docs/ROADMAP.md`, `AGENTS.md`,
`docs/CHANGELOG.md`

## [2026-10-02] — Winlink through the node over SSH: no terminal

### Improvements

- **Winlink through the node asks SSH for no terminal (pty).** WS1EC's
  pty echoed kissterm's own `;FW:` line back as if the CMS had sent it,
  stopping the first run; its control keys would also corrupt compressed
  messages. The operator's terminal and the BBS run keep their pty.

**Files:** `kissterm/transport/ssh.py`, `kissterm/ui/app.py`,
`tests/unit/test_ssh_transport.py`, `docs/ROADMAP.md`, `docs/ON-AIR-TESTS.md`,
`docs/CHANGELOG.md`

## [2026-10-02] — Winlink by Internet through the node's RMS

### New Features

- **Settings > Mail > Internet server: Through the node.** I logs in to
  the Home BBS's Telnet or SSH contact (its Node login) on a connection
  of its own and sends RMS (Node's Winlink command) instead of BBS, so
  the node reaches Winlink. The node's password is never written to the
  transcript. Direct Telnet to the CMS stays. Operator request, 2026-10-02.

**Files:** `kissterm/mail/winlink_collect.py`, `kissterm/ui/app.py`,
`kissterm/config.py`, `kissterm/ui/settings_schema.py`, `config.toml.example`,
`tests/unit/test_mail_winlink_collect.py`, `tests/pilot/test_winlink_send_receive.py`,
`docs/GUIDE.md`, `README.md`, `docs/ON-AIR-TESTS.md`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-10-02] — One toast per event for Send/Receive

### Improvements

- **A Send/Receive connect raises one toast at each end, not two.** The
  start toast says transmit was enabled, if it was (the gate's own toast
  is folded in), and a failed connect is one toast with the reason
  ("Send/Receive: Could not connect to WS1EC-2 -- ...") instead of the
  connect's toast beside Mail's. New DESIGN.md section 6 rule, "One event,
  one toast". Also recorded in ROADMAP: cms-z delivered real mail.
  Operator report, 2026-10-02.

**Files:** `kissterm/ui/app.py`, `tests/pilot/test_get_mail.py`, `DESIGN.md`,
`docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-10-02] — Evidence: Winlink's test server accepts kissterm

- Recorded in ROADMAP's blocker: cms-z.winlink.org logged kissterm in
  where the production CMS refuses its client name. No code change.

**Files:** `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-10-02] — A failed APRS beacon no longer retries in a tight loop

### Bug Fixes

- **The APRS beacon waits a full interval after a failed send.** The next
  beacon was timed from the last *successful* one, so once a send failed
  every later try was due at once: on 2026-10-01, with the TCP KISS host
  down, it retried about 582,000 times in four minutes (all refused at
  the transport, nothing transmitted, a 175 MB log). With the transmit
  gate closed it spun silently at full CPU. Found in the operator's log.

**Files:** `kissterm/aprs_beacon.py`, `tests/unit/test_aprs_beacon.py`,
`docs/CHANGELOG.md`

## [2026-10-02] — Toasts stay up 10 seconds

### Improvements

- **Every toast stays up at least 10 seconds** (was Textual's 5, and 4
  for Send/Receive's "Connecting..." and "No new mail"), so a job's start
  and outcome can both be read. New DESIGN.md section 6 rule, held by
  `tests/unit/test_toast_dwell.py`. Operator request, 2026-10-02.

**Files:** `kissterm/ui/app.py`, `kissterm/ui/mail_pane.py`, `DESIGN.md`,
`tests/unit/test_toast_dwell.py`, `docs/CHANGELOG.md`

## [2026-10-02] — I uses the contact's Node login

### Improvements

- **Send/Receive by Internet signs in with the contact's Node login** when
  the Home BBS has no Internet login of its own, instead of asking for the
  same username and password again. Operator report, 2026-10-02.

**Files:** `kissterm/ui/app.py`, `tests/pilot/test_winlink_send_receive.py`,
`docs/GUIDE.md`, `docs/CHANGELOG.md`

## [2026-10-02] — SSH asks to trust a new server instead of needing a file

### Improvements

- **An SSH contact saves without a known_hosts file.** The first connect
  shows the server's key fingerprint with Trust/Cancel (Cancel focused);
  Trust writes it to kissterm's own `ssh_known_hosts` (or the file named in
  Known) and connects. A changed key is refused with no prompt. The
  Address Book had refused to save until the operator ran `ssh-keyscan` by
  hand, which nothing said to do. Operator report, 2026-10-02.

**Files:** `kissterm/transport/ssh.py`, `kissterm/ui/dialogs.py`,
`kissterm/ui/app.py`, `tests/unit/test_ssh_transport.py`,
`tests/pilot/test_ssh_host_key.py`, `SETUP.md`, `docs/GUIDE.md`,
`config.toml.example`, `docs/ON-AIR-TESTS.md`, `docs/CHANGELOG.md`

## [2026-10-02] — The update notice is a pop-up, not a Terminal line

### Improvements

- **A newer version is announced in a toast**, as is the result of Update;
  no Terminal line and no `update X` status field (DESIGN.md section 6: one
  place per notice). An operator who stays on Mail never saw the terminal.
  New DESIGN.md rule: the Terminal record is for sessions only. Operator
  request, 2026-10-02.

**Files:** `kissterm/ui/app.py`, `kissterm/ui/settings_schema.py`,
`tests/pilot/test_update_check.py`, `DESIGN.md`, `docs/GUIDE.md`, `SETUP.md`,
`config.toml.example`, `docs/CHANGELOG.md`

## [2026-10-01] — Update check against GitHub

### New Features

- **kissterm says when a newer version is on GitHub.** Once a day, in the
  background, it reads `__version__` from `main` (one anonymous request,
  Internet only) and writes one Terminal note plus `update X` in the status
  bar. F10 > Help > Check for updates asks now and offers **Update**, which
  runs `pipx upgrade` or `uv tool upgrade` after showing the command, is
  refused while a session or Send/Receive is under way, and asks for a
  restart. Never upgrades by itself; a source checkout is told to
  `git pull`. Off with Settings > Station > Check for updates or
  `--no-update-check`. Install detection checked against a real pipx
  install; `uv tool upgrade` refetching a git source is UNVERIFIED.

**Files:** `kissterm/updater.py`, `kissterm/ui/app.py`, `kissterm/ui/dialogs.py`,
`kissterm/ui/commands.py`, `kissterm/ui/settings_schema.py`, `kissterm/config.py`,
`kissterm/__main__.py`, `config.toml.example`, `tests/unit/test_updater.py`,
`tests/pilot/test_update_check.py`, `docs/GUIDE.md`, `SETUP.md`, `README.md`, `AGENTS.md`,
`docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-29] — SSH sign-ins told apart, no lines box, one button style

### Improvements

- **The Address Book's SSH dialog names its two sign-ins**: **SSH** for the
  server's account and **Node login** for what is sent to the node after.
  The multi-line "one line per prompt" box is gone from the Address Book
  (saved logins and scripts replace it; lines an older version saved are
  kept, not dropped). A saved login may be a username with no password, for
  an account like WS1EC's `packet`. The same box is gone from Connect
  (Ctrl+N, with "+ Type lines to send...") and from the transport editor.
- **A dialog's buttons match its fields.** Five dialogs with compact fields
  had bordered buttons (the saved-login editor opened from an Address Book
  entry looked like another program). New rule in DESIGN.md section 3,
  enforced by `tests/unit/test_dialog_consistency.py`. Operator report,
  2026-09-29. No screenshot in `assets/` shows these dialogs.

**Files:** `kissterm/ui/dialogs.py`, `DESIGN.md`, `docs/GUIDE.md`, `SETUP.md`,
`tests/unit/test_dialog_consistency.py`, `tests/pilot/test_addressbook_pane.py`,
`tests/pilot/test_winlink_send_receive.py`, `tests/pilot/test_app_mounts.py`,
`kissterm/ui/styles.py`, `docs/CHANGELOG.md`

## [2026-09-29] — A station polling a connection kissterm does not have is explained

### Improvements

- **The terminal says so, once per station, when a node keeps polling a link
  left open by a closed kissterm.** kissterm already answered each poll
  DM (per spec, so the node stops); that was only in the DEBUG log, so the
  operator saw a node "calling back" with no explanation and read the
  standing `ANSWERING` label as a stuck state. With transmit off it says the
  DM was not sent. Quitting already sends DISC on every live link. Operator
  report, 2026-09-29 (ROADMAP P0.1).

**Files:** `kissterm/ax25/station.py`, `kissterm/ui/app.py`,
`tests/unit/test_station_max_links.py`, `docs/GUIDE.md`, `docs/ON-AIR-TESTS.md`,
`docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-29] — Documentation and screenshots ship with every change

### Improvements

- **AGENTS.md section 7: user documentation and screenshots ship in the
  same commit as the change** they describe, with honest claims
  (unproven means experimental or on the roadmap). Every release checks
  the same (ROADMAP P7). A new test keeps the screenshot script,
  `assets/` and the docs in step: every image shown exists, none is left
  over, and every one comes from the script. Operator request, 2026-09-29,
  as kissterm goes out to testers.

**Files:** `AGENTS.md`, `docs/ROADMAP.md`, `tests/unit/test_readme_assets.py`,
`scripts/generate_screenshot.py`, `docs/CHANGELOG.md`

## [2026-09-29] — Serial and Bluetooth TNCs labelled experimental

### Improvements

- **Serial and Bluetooth Classic KISS are labelled experimental** in
  Settings, the Address Book and `--doctor`, like VARA and BLE: built and
  loopback-tested, but no operator has reported one working with a real
  TNC. The README says they are on the roadmap; SETUP.md and the guide
  say the same; ROADMAP P3 and ON-AIR-TESTS have the checks. The README
  names UZ7HO SoundModem first, the modem in use on the air.

**Files:** `kissterm/transport/__init__.py`,
`tests/unit/test_transport_factory.py`, `README.md`, `docs/GUIDE.md`,
`SETUP.md`, `docs/ROADMAP.md`, `docs/ON-AIR-TESTS.md`, `docs/CHANGELOG.md`

## [2026-09-29] — README rewritten for newcomers, a user guide, new screenshots

### Improvements

- **The README is a front page for every operator, new to packet or
  not** (its headline says what kissterm is; being friendly to newcomers
  is one of its features, operator 2026-09-29; the Terminal is for the
  applications nodes offer, such as chat and weather): what kissterm
  is (cross-platform, open source, a desktop app and web version planned),
  a screenshot tour of Mail, forms, Bulletins, Files, Terminal, APRS,
  Heard, Monitor and Settings, a short "New to packet?" primer, install,
  keys, safety and status. The detail moved, reorganised by task, to
  **docs/GUIDE.md**, with stale facts corrected (connect retries are 10,
  logins are a username and a password). Install now points at GitHub:
  kissterm is not on PyPI yet (README and SETUP.md).
- **Screenshots without broken borders.** `scripts/generate_screenshot.py`
  renders its SVGs with headless Chrome (`KISSTERM_SHOT_RENDERER`), which
  loads the font cairosvg could not, and stages a whole invented station:
  mail, a received ICS-213, bulletins, files, a live node and BBS session
  with command suggestions, and APRS. Old and unused images removed.
  Operator request, 2026-09-29.

**Files:** `README.md`, `docs/GUIDE.md`, `SETUP.md`, `AGENTS.md`,
`docs/ROADMAP.md`, `scripts/generate_screenshot.py`, `assets/`,
`tests/unit/test_docs_keys.py`, `tests/unit/test_settings_paths.py`,
`docs/CHANGELOG.md`

## [2026-09-28] — G asks for a BBS login as a username and a password

### Improvements

- **G to a Home BBS with a login prompt and no saved login asks for
  Username and a masked Password**, saved as one login ("Home BBS", in
  the keyring); the BBS gets the username line, then the password. The
  Winlink password question stays password-only (the account has no
  username). The login questions now have the same title style and Esc
  footer as the other dialogs. Operator request, 2026-09-28.

**Files:** `kissterm/ui/dialogs.py`, `kissterm/ui/app.py`,
`kissterm/ui/styles.py`, `tests/pilot/test_get_mail.py`,
`tests/pilot/test_layout_fits.py`, `docs/ROADMAP.md`,
`docs/ON-AIR-TESTS.md`, `docs/CHANGELOG.md`

## [2026-09-28] — I asks for the contact, username and password in one question

### Improvements

- **I with no Telnet/SSH contact or no node password shows "Send and
  Receive by Internet"**: the contact (ending "New Telnet/SSH
  contact..."), the username (your callsign unless the login has one)
  and a masked password. "Save and continue" saves them as one login
  in the keyring, sets Settings > Mail, and runs. On All Inboxes it has
  Skip Home BBS. It replaces the contact question and the password-only
  question. Operator report, 2026-09-28 (ROADMAP P0.1).

**Files:** `kissterm/ui/dialogs.py`, `kissterm/ui/app.py`,
`kissterm/ui/styles.py`, `tests/pilot/test_winlink_send_receive.py`,
`tests/pilot/test_layout_fits.py`, `docs/ROADMAP.md`,
`docs/ON-AIR-TESTS.md`, `docs/CHANGELOG.md`

## [2026-09-28] — Mail and SSH sign in with a saved login

### Improvements

- **Settings > Mail's "BBS password", "Node username" and "Node password"
  are now "BBS login" and "Node login"**: a list of saved logins ending
  with "New login...". An Address Book SSH contact's "User" and
  "Password" are one "Sign in" login list the same way; an SSH connection
  moved from the old transports list keeps its username in its login.
  DESIGN.md section 8, "A login is one thing". Operator report,
  2026-09-28 (ROADMAP P0.1).

**Files:** `kissterm/ui/settings_schema.py`, `kissterm/ui/settings_pane.py`,
`kissterm/ui/dialogs.py`, `kissterm/ui/addressbook_pane.py`,
`kissterm/addressbook.py`, `DESIGN.md`, `tests/pilot/test_settings.py`,
`tests/pilot/test_addressbook_pane.py`, `tests/unit/test_addressbook.py`,
`docs/CHANGELOG.md`

## [2026-09-28] — The login editor asks for a username and a masked password

### Improvements

- **New login and Edit (Settings > Logins, Connect, Address Book) show
  Name, Username and a masked Password**, and say where the password is
  kept (system keyring, or config.toml when no keyring is available).
  Editing a login leaves the password alone unless a new one is typed.
  The Connect dialog's name-and-text box is gone; its login list ends
  with "New login...", like every other list of saved items. Operator
  report, 2026-09-28 (ROADMAP P0.1).

**Files:** `kissterm/ui/dialogs.py`, `kissterm/ui/settings_pane.py`,
`kissterm/ui/app.py`, `kissterm/ui/styles.py`,
`tests/pilot/test_settings.py`, `tests/pilot/test_addressbook_pane.py`,
`tests/pilot/test_app_mounts.py`, `docs/CHANGELOG.md`

## [2026-09-28] — A saved login is a username and a password

### Improvements

- **Saved logins hold a username (in config.toml) and a password (in the
  system keyring)**, and send the username line, then the password
  line, at a prompt. At launch, an older two-line login becomes username
  and password, and a one-line login its password. The Home BBS's "Node
  username" and an SSH contact's own username move into their logins.
  An SSH contact signs in with its login's username. The dialogs follow
  in the next changes. Operator report, 2026-09-28 (ROADMAP P0.1).

**Files:** `kissterm/config.py`, `kissterm/addressbook.py`,
`kissterm/ui/app.py`, `tests/unit/test_keystore.py`,
`tests/unit/test_addressbook.py`, `docs/CHANGELOG.md`

## [2026-09-28] — Settings: nothing above the box

### Improvements

- **The description above each Settings section is gone**, so every
  section's box lines up with the section list. The help line at the
  bottom already explains the highlighted setting. Three statements
  moved into their fields' help: Beacon is not APRS, Alerts never
  transmit and a callsign is a claim, and you remain the control
  operator when answering. DESIGN.md section 4 now has the rule,
  "Nothing above the box", first decided for the APRS pane and
  Address Book on 2026-09-10. Operator report, 2026-09-28 (ROADMAP P0.1).

**Files:** `kissterm/ui/settings_pane.py`, `kissterm/ui/settings_schema.py`,
`kissterm/ui/styles.py`, `tests/pilot/test_settings.py`, `DESIGN.md`,
`assets/`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-28] — Winlink B2F research filed

### Improvements

- **docs/PROTOCOL_GUIDE.md, "Winlink B2F"**: what Winlink's Open B2F
  specification and its Data Flow and Data Packaging document say (from
  the operator's copies), checked against wl2k-go and kissterm. Covers
  where they disagree (who speaks first, MIME, block size, the resume
  header), and that client registration is server policy, not
  protocol. The resume header is marked `# RESEARCH:` in `b2f.py`.

**Files:** `docs/PROTOCOL_GUIDE.md`, `kissterm/winlink/b2f.py`,
`kissterm/winlink/AGENTS.md`, `docs/CHANGELOG.md`

## [2026-09-28] — Winlink's test server as an option

### New Features

- **Settings > Mail > Internet server**: I can reach Winlink's test CMS
  (cms-z.winlink.org), the one the production CMS pointed kissterm at
  when it refused an unknown client, to try kissterm while it is not yet
  accepted. The refusal toast names the setting. Operator request,
  2026-09-28. Where mail sent through it goes is unverified.

**Files:** `kissterm/config.py`, `config.toml.example`,
`kissterm/mail/winlink_collect.py`, `kissterm/ui/settings_schema.py`,
`kissterm/ui/app.py`, `tests/pilot/test_winlink_send_receive.py`,
`docs/ON-AIR-TESTS.md`, `docs/CHANGELOG.md`

## [2026-09-28] — All Inboxes asks for the BBS; Winlink's refusal explained

### Improvements

- **I (or G) on All Inboxes asks for what a service in use still needs**:
  a Home BBS with a radio route but no Internet contact is asked for one
  (with Skip) instead of being left out. A service set up for neither key
  is still not asked about. Operator report, 2026-09-28 (ROADMAP P0.1).
- **"Unknown client types are not allowed"** from the CMS is explained as
  Winlink not knowing kissterm yet, not a login or network fault
  (ROADMAP, Blockers).
- **The `;PR:` secure-login answer is no longer written to transcripts**
  or the terminal: beside the `;PQ:` challenge it allowed offline
  password guessing.

**Files:** `kissterm/ui/app.py`, `kissterm/winlink/b2f.py`,
`tests/pilot/test_winlink_send_receive.py`,
`tests/unit/test_mail_winlink_collect.py`, `docs/ROADMAP.md`,
`docs/CHANGELOG.md`

## [2026-09-28] — Every shipped Winlink form carries its XML

### New Features

- **ICS-213RR, ICS-214, ICS-205, ICS-309, Field Situation Report,
  Severe WX, Damage Assessment and Incident Status** now go by Winlink
  with their XML too, and read from it when received. Each form's
  viewer variables and template version are taken from its Standard
  Forms 1.1.20.0 HTML. Table cells use Winlink's names (the 214's
  `Name1`...), every cell is written, and Damage Assessment categories
  take Winlink's twelve named slots, then Other13-15; a fourth category
  of your own sends the form as text only, and says why.

**Files:** `kissterm/mail/form_xml.py`, `kissterm/mail/forms.py`,
`kissterm/ui/app.py`, `kissterm/mail/data/forms/ics213rr.toml`,
`ics214.toml`, `ics205.toml`, `ics309.toml`, `fsr.toml`,
`severe_wx.toml`, `damage_assessment.toml`, `incident_status.toml`,
`tests/unit/test_form_xml.py`, `docs/ON-AIR-TESTS.md`, `docs/ROADMAP.md`,
`docs/CHANGELOG.md`

## [2026-09-28] — Winlink forms sent with their XML

### New Features

- **An ICS-213, its reply or a Winlink Check-in saved to the Winlink
  Outbox carries its `RMS_Express_Form_*.xml`**, so Winlink Express and
  Pat open it in the form's own viewer. Written as Pat writes it, with
  every variable the viewer reads and the ones the form's page computes
  (the ICS-213's Message2, template versions, the reply's original
  sender), transcribed from Standard Forms 1.1.20.0. A form whose text
  was changed after Continue goes as text only, and says so; a BBS
  message stays text only.

**Files:** `kissterm/mail/form_xml.py`, `kissterm/mail/forms.py`,
`kissterm/mail/winlink_collect.py`, `kissterm/ui/app.py`,
`kissterm/mail/data/forms/ics213.toml`, `ics213_reply.toml`,
`winlink_checkin.toml`, `tests/unit/test_form_xml.py`,
`tests/unit/test_mail_winlink_collect.py`, `tests/pilot/test_forms.py`,
`docs/ON-AIR-TESTS.md`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-28] — Winlink forms read from their XML

### New Features

- **A received Winlink form is shown from its XML attachment**
  (`RMS_Express_Form_*.xml`), exactly as filled in, when it has one; the
  text body is read against the template only when it does not. ICS-213,
  its reply and Winlink Check-in are matched by viewer name; any other
  Winlink form shows its filled variables as a list under its name. The
  XML is size-capped and one with a DOCTYPE is refused. Format from Pat's
  source (docs/PROTOCOL_GUIDE.md).

**Files:** `kissterm/mail/form_xml.py`, `kissterm/mail/forms.py`,
`kissterm/mail/data/forms/ics213.toml`, `ics213_reply.toml`,
`winlink_checkin.toml`, `kissterm/ui/mail_pane.py`,
`tests/unit/test_form_xml.py`, `tests/pilot/test_mail_pane.py`,
`kissterm/mail/AGENTS.md`, `docs/PROTOCOL_GUIDE.md`, `docs/ROADMAP.md`,
`docs/CHANGELOG.md`

## [2026-09-27] — Every list of saved things ends with New

### Improvements

- **Make what a form asks for without leaving it**: Settings' contact
  fields end with "New Telnet/SSH contact..." or "New radio contact...",
  and the Address Book entry and transport editors' login and script
  lists with "New login..." and "New script...". The editor opens on top;
  saving selects the new one, cancelling keeps the old choice. Written
  into DESIGN.md section 8 with the rule that a dialog's title names what
  the operator started. Operator report, 2026-09-27 (ROADMAP P0.1).

**Files:** `kissterm/ui/dialogs.py`, `kissterm/ui/settings_pane.py`,
`kissterm/ui/addressbook_pane.py`, `tests/pilot/test_settings.py`,
`tests/pilot/test_addressbook_pane.py`, `DESIGN.md`, `docs/ROADMAP.md`,
`docs/CHANGELOG.md`

## [2026-09-27] — All Inboxes questions titled for the run

### Improvements

- **A question asked during G or I on All Inboxes is titled "Send and
  Receive All Inboxes"** and says "You have All Inboxes selected, therefore
  kissterm will check mail for both BBS and Winlink." A password question
  names which password under it. Operator request, 2026-09-27.

**Files:** `kissterm/ui/app.py`, `kissterm/ui/dialogs.py`,
`kissterm/ui/styles.py`, `tests/pilot/test_winlink_send_receive.py`,
`docs/CHANGELOG.md`

## [2026-09-27] — Winlink gateway chosen at G, like Pat and RMS Express

### Improvements

- **G on a Winlink folder asks which gateway only when it must**: the
  favourite gateway dials at once if it is in the Address Book; otherwise
  a short "Winlink gateway" dialog offers it (added back on Connect), any
  radio contact, another callsign, or the gateway list, and "Remember as
  my gateway". Nothing has to be set up first. The Home BBS and password
  prompts lost their explanations. Operator report, 2026-09-27 (ROADMAP P0.1).

**Files:** `kissterm/ui/dialogs.py`, `kissterm/ui/app.py`,
`kissterm/ui/styles.py`, `tests/pilot/test_winlink_send_receive.py`,
`tests/pilot/test_get_mail.py`, `tests/pilot/test_layout_fits.py`,
`docs/ON-AIR-TESTS.md`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-27] — Settings: edit on the row, unsaved changes shown

### Improvements

- **Enter edits a setting on its own row**, not in a line under the list:
  Enter keeps the change, Esc puts the old value back, and choosing from a
  list finishes the edit. **What is not saved shows**: the row says
  "(unsaved)", its section is starred, and the count sits beside Save and
  Discard changes (was Reload), now at the left under the list. Operator
  report, 2026-09-27 (ROADMAP P0.1).

**Files:** `kissterm/ui/settings_pane.py`, `kissterm/ui/styles.py`,
`tests/pilot/test_settings.py`, `README.md`, `DESIGN.md`, `assets/`,
`docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-27] — Settings: every section boxed, headings ruled, plain labels

### Improvements

- **Radio and Logins are boxed like every other section**, with their
  description above the box. **Each heading has a line under it again**
  (a blank row in ASCII-safe mode), and an Advanced setting sits under
  "Advanced: <its group>", so Winlink's grid square is no longer under the
  BBS heading.
- **Contact settings are chosen from the Address Book**: BBS contact and
  Gateway contact list radio contacts, Telnet/SSH contact the Telnet and
  SSH ones; a contact since removed is kept and marked "not in the Address
  Book". **Labels are plain words**: Node username and password, Command
  after login, Command prompt, BBS password, Account callsign and
  password, Grid square, Addressed to, Transmit on at startup, Callsign
  alerts, Callsigns to watch, Quiet after typing, Open side panels, Radio
  in use. Operator report, 2026-09-27 (ROADMAP P0.1).

**Files:** `kissterm/ui/settings_pane.py`, `kissterm/ui/settings_schema.py`,
`kissterm/ui/styles.py`, `kissterm/ui/dialogs.py`,
`tests/pilot/test_settings.py`, `README.md`, `SETUP.md`, `DESIGN.md`,
`assets/`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-27] — RMS gateways: Winlink gateways nearest you

### New Features

- **F10 > Session > RMS gateways** lists Winlink gateway channels by mode
  (Packet, VARA FM, VARA HF, ARDOP, Pactor), nearest first from your APRS
  position with distance and direction. Enter or "Use for Winlink" adds
  the gateway to the Address Book (a contact already there is left as it
  is) and makes it the Winlink Dial; nothing is dialed or sent. The list
  comes from winlink.org only when Refresh is pressed and is kept in a
  file. The fetch needs an access key issued to kissterm, which it does
  not have yet: until then the menu entry says "needs an API key" and
  Refresh is off. Request and filter follow Pat (MIT).

**Files:** `kissterm/winlink/gateways.py`, `kissterm/winlink/__init__.py`,
`kissterm/ui/gateways_screen.py`, `kissterm/ui/app.py`,
`kissterm/ui/commands.py`, `kissterm/ui/styles.py`,
`tests/unit/test_winlink_gateways.py`,
`tests/unit/data/winlink/gateway_status.json`,
`tests/pilot/test_rms_gateways.py`, `README.md`, `docs/ROADMAP.md`,
`docs/CHANGELOG.md`

## [2026-09-27] — Settings as one list per section: the first screen 2 s sooner

### Improvements

- **The first screen comes in about 2.4 s instead of 4.5 s** (measured from
  local disk). Settings had a label and a control for every field, 434 of
  the app's 633 widgets, all built before anything was drawn. Each section
  is now one list of its settings with their values, and one editor under
  it changes the highlighted one: Enter edits (an on/off setting flips),
  Enter or Esc goes back to the list. Save still validates everything
  before writing anything. Advanced settings are listed last under a
  heading rather than folded; a latitude, longitude or grid square typed in
  updates the others, replacing the Decimal/Grid switch. Nothing is built
  on first use (the 2026-09-25 decision).
- Found on the way: from this checkout on the Unraid share, import alone
  takes about 4 s against 0.85 s from a local disk.

**Files:** `kissterm/ui/settings_pane.py`, `kissterm/ui/settings_schema.py`,
`kissterm/ui/styles.py`, `kissterm/ui/app.py`, `scripts/generate_screenshot.py`,
`tests/pilot/test_settings.py`, `tests/pilot/test_theming.py`,
`tests/pilot/test_app_mounts.py`, `tests/pilot/test_winlink_send_receive.py`,
`README.md`, `DESIGN.md`, `assets/`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-27] — Winlink attachments saved to Files > Attachments

### New Features

- **A received Winlink message's attachments are saved to Files >
  Attachments**, and its Attachments line says where each went. Names
  from the air are cleaned first: the path dropped, control and
  right-to-left override characters removed, reserved device names
  prefixed, the length capped keeping the real extension; nothing is
  overwritten (a repeat becomes `name-1.ext`), opened or run. A file that
  cannot be written is noted and the exchange goes on.

**Files:** `kissterm/mail/attachments.py`, `kissterm/mail/winlink_collect.py`,
`kissterm/mail/AGENTS.md`, `README.md`, `tests/unit/test_mail_attachments.py`,
`tests/unit/test_mail_winlink_collect.py`, `docs/ROADMAP.md`,
`docs/CHANGELOG.md`

## [2026-09-27] — Unverified transports are labelled experimental

### Improvements

- **Kernel AX.25, VARA HF/FM, Mercury and Bluetooth LE say
  "(experimental)"** wherever a transport kind is named (Settings > Radio,
  its New, the Address Book's connection type), in `--doctor`'s result for
  one, and in SETUP.md's section for each: none has been verified against
  real hardware (ROADMAP P3). A 1.0 finish-line item.

**Files:** `kissterm/transport/__init__.py`, `kissterm/doctor.py`,
`SETUP.md`, `tests/unit/test_transport_factory.py`, `docs/ROADMAP.md`,
`docs/CHANGELOG.md`

## [2026-09-27] — Every TCP connect gives up after 10 seconds

### Improvements

- **A host that is down fails in 10 seconds, and says so**, for Telnet
  contacts, AGWPE, VARA and the APRS-IS watch as already for TCP KISS:
  "no answer within 10s (host down or unreachable?)" instead of about two
  minutes of "Connecting..." and an empty reason. One helper,
  `transport.base.open_connection`, bounds them all.

**Files:** `kissterm/transport/base.py`, `kissterm/transport/tcp_kiss.py`,
`kissterm/transport/agwpe.py`, `kissterm/transport/telnet.py`,
`kissterm/transport/vara.py`, `kissterm/aprs_is.py`,
`tests/unit/test_tcp_kiss_connect_timeout.py`, `docs/ROADMAP.md`,
`docs/CHANGELOG.md`

## [2026-09-27] — Every contact in the Address Book (step 6 of 6, done)

### Improvements

- **The docs describe Telnet and SSH nodes as Address Book contacts**:
  SETUP section 6a rewritten (By Telnet or SSH, dialed beside the radio,
  the gate untouched, WS1EC's login shape), README's transport notes and
  the Settings > Radio passages updated. The ROADMAP item is closed:
  operator, 2026-09-26, "create all of their contacts in the address book
  regardless of transport."

**Files:** `SETUP.md`, `README.md`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-27] — Telnet and SSH leave Settings > Radio (step 5 of 6)

### Improvements

- **Settings > Radio is hardware only**: its New no longer offers Telnet
  or SSH, and its note says those are Address Book contacts. At launch,
  before any transport opens, a Telnet or SSH entry in config.toml is
  moved to the Address Book (password to the keyring) and removed; if it
  was the active transport, the first one left becomes active, so the
  radio opens rather than an SSH login. The terminal says what moved.

**Files:** `kissterm/addressbook.py`, `kissterm/__main__.py`,
`kissterm/ui/dialogs.py`, `kissterm/ui/settings_pane.py`,
`config.toml.example`, `tests/unit/test_addressbook.py`,
`tests/unit/test_config.py`, `tests/pilot/test_settings.py`,
`tests/pilot/test_addressbook_pane.py`, `tests/pilot/test_app_mounts.py`,
`docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-27] — I reaches the Home BBS through a contact (step 4 of 6)

### Improvements

- **I on a BBS folder uses a Telnet or SSH contact from the Address
  Book** (Settings > Mail > Home BBS, "Internet contact"), not a
  connection from Settings > Radio. A connection adopted at launch keeps
  its name, so the setting already made still works. With no contact,
  the question's "New contact" opens the editor By SSH.

**Files:** `kissterm/ui/app.py`, `kissterm/ui/dialogs.py`,
`kissterm/ui/addressbook_pane.py`, `kissterm/ui/settings_schema.py`,
`kissterm/ui/commands.py`, `config.toml.example`, `README.md`,
`tests/pilot/test_winlink_send_receive.py`, `docs/ON-AIR-TESTS.md`,
`docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-27] — Dialing a Telnet or SSH contact (step 3 of 6)

### New Features

- **A Telnet or SSH contact dials into its own Terminal tab, beside the
  radio**: Enter in the Address Book, Ctrl+N, Ctrl+R and Ctrl+D work as
  for a station, and its login script runs once it is up. It opens its
  own connection rather than replacing the radio's, and never checks or
  arms the transmit gate: typing to it, its login and hanging up all
  leave TX OFF. Its connection closes with the session and when kissterm
  exits.

**Files:** `kissterm/ui/app.py`, `kissterm/ui/terminal_pane.py`,
`tests/pilot/test_internet_contacts.py`,
`tests/pilot/test_winlink_send_receive.py`, `docs/ON-AIR-TESTS.md`,
`docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-27] — The Address Book editor makes Telnet and SSH contacts (step 2 of 6)

### New Features

- **Address Book > New or Edit has a "By" choice**: Radio shows the
  station, hops, frequency and link rows as before; Telnet and SSH show
  host and port, and SSH its user, password, key file, passphrase and
  known-hosts file. A password typed there is saved as a login (the
  keyring), shown only as "saved"; SSH is refused without a password or
  key, or without a known-hosts file.

**Files:** `kissterm/ui/dialogs.py`, `kissterm/ui/addressbook_pane.py`,
`kissterm/addressbook.py`, `kissterm/ui/styles.py`,
`tests/pilot/test_addressbook_pane.py`, `docs/ROADMAP.md`,
`docs/CHANGELOG.md`

## [2026-09-27] — Internet contacts in the Address Book (step 1 of 6)

### New Features

- **An Address Book entry can say how it is reached**: by radio (as
  before), Telnet or SSH, with its host, port, user, key and known-hosts
  file; passwords are saved logins, never text in addressbook.json. At
  launch each Telnet and SSH connection in Settings > Radio is added as a
  contact of the same name, its password moved to the keyring. Dialing
  them comes in step 3 (ROADMAP P2).

**Files:** `kissterm/addressbook.py`, `kissterm/ui/app.py`,
`tests/unit/test_addressbook.py`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-27] — Notices that do what they point at

### Improvements

- **A refused Winlink password is asked for again on the spot** and saved
  for the next Send/Receive, instead of a notice pointing at Settings.
  Nothing more is dialed.
- **Winlink with no callsign opens the callsign dialog** rather than
  saying where it is.
- The Heard radar's "(Settings)" names the section: Settings (F9) > APRS.

**Files:** `kissterm/ui/app.py`, `kissterm/ui/dialogs.py`,
`kissterm/ui/heard_pane.py`, `tests/pilot/test_winlink_send_receive.py`,
`docs/CHANGELOG.md`

## [2026-09-27] — Nothing off the screen at 80x24; Settings paths checked

### Bug Fixes

- **APRS contacts' buttons and the Terminal tab's "Use node" stay on an
  80x24 screen** (P0.1, awaiting confirmation). Button rows in the
  slide-outs go two by two when narrow (`ButtonRow`, shared with the
  Address Book), and the known-nodes section gives way when the Address
  Book is too short for it.
- **Every "Settings > ..." names a real section.** "Transports" (first-run
  greeting, setup guide, new-device notice, SETUP.md) is Radio, "Settings
  > Test" is Radio > Test, and README's "Open on" is under Appearance.

### Improvements

- **Two layout tests**: every tab and the Mail Address Book at 80x24,
  100x33 and 160x40, and the Send/Receive dialogs at 80x24, keep every
  control on screen; every Settings path in the code and docs names a
  section that exists.

**Files:** `kissterm/ui/button_row.py`, `kissterm/ui/addressbook_pane.py`,
`kissterm/ui/aprs_pane.py`, `kissterm/ui/styles.py`, `kissterm/ui/app.py`,
`kissterm/ui/dialogs.py`, `kissterm/guides.py`, `README.md`, `SETUP.md`,
`tests/pilot/test_layout_fits.py`, `tests/unit/test_settings_paths.py`,
`docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-27] — Passwords in Settings are masked and kept in the keyring

### Bug Fixes

- **A password typed into Settings is never shown or kept in config.toml**
  (P0.1, awaiting confirmation). Winlink's "Password login", the Home
  BBS's "Credential" and "Telnet password login" wanted a saved login's
  name and showed what was typed; a password typed there sat in
  config.toml and the password dialog showed it as a login name. They are
  now Password, Login and Telnet password: masked, saved in the system
  keyring as "Winlink", "Home BBS" and "Home BBS Telnet", empty keeps what
  is saved. A password already in one of those keys is moved at launch,
  with a notice; a name that is no saved login is never displayed.

**Files:** `kissterm/config.py`, `config.toml.example`,
`kissterm/ui/settings_schema.py`, `kissterm/ui/settings_pane.py`,
`kissterm/ui/app.py`, `tests/unit/test_config.py`,
`tests/pilot/test_settings.py`, `tests/pilot/test_winlink_send_receive.py`,
`docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-27] — Centred dialogs; Send/Receive questions say why and go there

### Bug Fixes

- **Every dialog is centred** (P0.1, awaiting confirmation). Most had no
  centring rule and sat in the top-left corner; one `ModalScreen` rule now
  covers them all, with the F10 menu and Ctrl+P palette kept in place.
  A dialog is never taller than the screen; past that it scrolls, so the
  Winlink question's buttons stay on an 80x24 terminal.

### Improvements

- **G or I on All Inboxes says why it is asking**: a setup or password
  question names the service it is for ("G on All Inboxes sends and
  receives with the Home BBS, then Winlink, and Winlink needs this
  first") and offers Skip, which runs the other service alone. Cancel
  still stops the whole run.
- **A setup question that names a place has a button to go there**:
  Winlink settings, Home BBS settings, Mail settings, Add a connection
  (Settings > Radio), or Connect when the Address Book is empty.

**Files:** `kissterm/ui/styles.py`, `kissterm/ui/dialogs.py`,
`kissterm/ui/app.py`, `tests/pilot/test_winlink_send_receive.py`,
`DESIGN.md`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-26] — Address Book buttons fit a narrow slide-out

### Bug Fixes

- **The Address Book's buttons no longer run off the screen** (P0.1,
  awaiting confirmation). On the Mail tab's Ctrl+G slide-out the four
  buttons need 44 columns and got 27; below that they now sit two by two.
- **The Home BBS setup dialog and ON-AIR-TESTS named a Settings section
  that does not exist** ("Connections"); an SSH connection is added under
  Settings > Radio > New, kind SSH.

**Files:** `kissterm/ui/addressbook_pane.py`, `kissterm/ui/styles.py`,
`kissterm/ui/dialogs.py`, `tests/pilot/test_app_mounts.py`,
`docs/ROADMAP.md`, `docs/ON-AIR-TESTS.md`, `docs/CHANGELOG.md`

## [2026-09-26] — I: Send/Receive by Internet

### New Features

- **I on the Mail tab sends and receives over the Internet**, parallel
  to G and chosen by folder the same way: the Home BBS through a Telnet
  or SSH connection (Settings > Mail > Home BBS over the Internet; WS1EC's
  SSH login telnets into its node), Winlink through the CMS. The node's
  BPQ Telnet login is answered (`user:`, `password:`, the option bytes
  BPQ sends before them allowed for), then After login (`BBS`). The
  connection and password are asked for on first use; the transmit gate
  is untouched; each run is kept as a transcript. It replaces the
  Session menu's "Winlink over the Internet".

**Files:** `kissterm/mail/collect.py`, `kissterm/config.py`,
`config.toml.example`, `kissterm/ui/app.py`, `kissterm/ui/dialogs.py`,
`kissterm/ui/mail_pane.py`, `kissterm/ui/commands.py`,
`kissterm/ui/settings_schema.py`, `tests/unit/test_mail_collect.py`,
`tests/pilot/test_winlink_send_receive.py`, `DESIGN.md`, `README.md`,
`docs/ROADMAP.md`, `docs/ON-AIR-TESTS.md`, `docs/CHANGELOG.md`

## [2026-09-26] — Winlink over the Internet

### New Features

- **Session > Winlink over the Internet** (Mail tab): the same Winlink
  send and receive through the Winlink CMS by Telnet
  (server.winlink.org:8772), no radio involved and the transmit gate
  untouched. It answers the CMS's own login (`CMSTelnet`, as wl2k-go
  does), asks for your Winlink password first if none is saved, and
  writes the exchange to a transcript. Not yet run against the real CMS.

**Files:** `kissterm/mail/winlink_collect.py`, `kissterm/ui/app.py`,
`kissterm/ui/commands.py`, `tests/unit/test_mail_winlink_collect.py`,
`tests/pilot/test_winlink_send_receive.py`, `README.md`,
`docs/ROADMAP.md`, `docs/ON-AIR-TESTS.md`, `docs/CHANGELOG.md`

## [2026-09-26] — Send/Receive asks first; All Inboxes does both

### Improvements

- **G asks for what is missing before dialing**: the Winlink password,
  and the Home BBS login when Settings > Mail names a login prompt, in
  a masked field saved as a login (the system keyring where there is
  one). A missing password no longer costs a connect.
- **G on All Inboxes sends and receives with the Home BBS, then
  Winlink**, each one that has a dial entry; everything is asked before
  the first dial. The Footer says "Send/Receive all".
- **A BPQ Telnet login prompt nobody answers stops the run in 20 s** by
  name -- no login set up, or ours refused -- instead of after the
  five-minute idle timeout (prompts from LinBPQ's `TelnetV6.c`).

**Files:** `kissterm/ui/app.py`, `kissterm/ui/dialogs.py`,
`kissterm/ui/mail_pane.py`, `kissterm/ui/commands.py`,
`kissterm/mail/collect.py`, `tests/unit/test_mail_collect.py`,
`tests/pilot/test_get_mail.py`, `tests/pilot/test_winlink_send_receive.py`,
`DESIGN.md`, `README.md`, `docs/ON-AIR-TESTS.md`, `docs/CHANGELOG.md`

## [2026-09-26] — Writing Winlink messages

### New Features

- **Type "Winlink message"** in the compose screen: no @ field, To takes
  several callsigns or email addresses, the title up to Winlink's 128
  characters, and Save files it in Mail/Winlink/Outbox for G on a Winlink
  folder. Insert on a Winlink folder starts as one (a form sent from
  there too), and R on a message received from Winlink answers by
  Winlink.

**Files:** `kissterm/mail/compose.py`, `kissterm/ui/compose.py`,
`kissterm/ui/app.py`, `tests/pilot/test_compose.py`, `README.md`,
`docs/ROADMAP.md`, `docs/ON-AIR-TESTS.md`, `docs/CHANGELOG.md`

## [2026-09-26] — Winlink Send/Receive over packet

### New Features

- **G on a Winlink folder sends and receives with Winlink**: it dials
  the Address Book entry Settings > Mail > Winlink names (an RMS `-10`
  SSID, a NET/ROM alias, a node whose login script sends `RMS`, or hops
  to a gateway whose Internet is up), answers the password challenge
  from the saved login, sends Mail/Winlink/Outbox and files new mail in
  Mail/Winlink/Inbox with its `.b2f` bytes. Anywhere else G is the Home
  BBS as before; the Footer says which. The Terminal tab shows the
  protocol lines, with messages summarised instead of binary. Not yet
  run against a real gateway (docs/ON-AIR-TESTS.md).
- **Settings > Mail > Winlink**: route, account (defaults to your
  callsign without SSID), password login, locator (defaults to the APRS
  grid square).

**Files:** `kissterm/mail/winlink_collect.py` (new), `kissterm/config.py`,
`config.toml.example`, `kissterm/ui/app.py`, `kissterm/ui/dialogs.py`,
`kissterm/ui/mail_pane.py`, `kissterm/ui/settings_schema.py`,
`kissterm/ui/commands.py`, `kissterm/mail/AGENTS.md`, `DESIGN.md`, `README.md`,
`tests/unit/test_mail_winlink_collect.py`,
`tests/pilot/test_winlink_send_receive.py`, `tests/pilot/test_settings.py`,
`tests/unit/test_config.py`, `docs/ROADMAP.md`, `docs/ON-AIR-TESTS.md`,
`docs/CHANGELOG.md`

## [2026-09-26] — Winlink B2F exchange

### New Features

- **The Winlink exchange itself**: the handshake with a gateway (secure
  login included), proposals, sending and receiving messages in blocks,
  every check the protocol has, and a clear reason when it stops (a
  wrong password in the gateway's own words, a damaged message, a
  dropped link). It waits for the gateway's `[WL2K-...]` line, so a
  node's own lines before it do no harm. Tested against wl2k-go's
  recorded CMS sessions; not yet run over a link, and no UI yet.

**Files:** `kissterm/winlink/b2f.py` (new), `kissterm/winlink/__init__.py`,
`tests/unit/test_winlink_b2f.py`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-26] — Winlink message format

### New Features

- **Winlink messages in B2 format**: read and write the headers, body and
  attachments a Winlink message carries, with new message IDs, the date
  layouts seen in the wild, and non-ASCII subjects and file names. A real
  message with a picture attached (wl2k-go's test data) reads and writes
  back byte for byte. No UI yet.

**Files:** `kissterm/winlink/message.py` (new), `kissterm/winlink/__init__.py`,
`tests/unit/test_winlink_message.py`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-26] — Winlink groundwork: secure login and LZHUF

### New Features

- **The first two pieces of Winlink over packet**, with no UI yet: the
  answer to the CMS's password challenge (`;PQ:`/`;PR:`, the password
  never sent), and LZHUF in the B2 container that every Winlink message
  travels in. Both are ports of wl2k-go (MIT) and match its test vectors
  byte for byte, including a real message with a picture attached.

**Files:** `kissterm/winlink/` (new: `__init__.py`, `secure.py`,
`lzhuf.py`, `AGENTS.md`), `tests/unit/test_winlink_secure.py`,
`tests/unit/test_winlink_lzhuf.py`, `tests/unit/data/winlink/` (new),
`README.md`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-26] — Saved logins in the system keyring

### Improvements

- **Saved logins go to the system keyring** (GNOME Keyring, KWallet,
  macOS Keychain, Windows Credential Locker) when there is one;
  config.toml keeps only their names. Logins already in config.toml
  move at launch, with a notice. Without a keyring (a headless SSH
  session) they stay in config.toml, and Settings > Logins says where
  each one is kept. Tests never touch the real keyring.
- New dependency: `keyring`.

**Files:** `kissterm/keystore.py` (new), `kissterm/config.py`,
`kissterm/_isolate.py`, `kissterm/ui/app.py`, `kissterm/ui/settings_pane.py`,
`pyproject.toml`, `tests/unit/test_keystore.py`, `README.md`,
`docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-26] — Bulletin categories and distributions

### Improvements

- **A bulletin offers its category and distribution**: with Type
  Bulletin, two pick-lists fill To and @ -- the ones you used before,
  the categories already in Bulletins, USA and WW, and "This BBS only"
  (no @). Typing anything else still works; picking sends nothing.
  Sources are in `mail/compose.py`'s docstring; ALLUS is not offered.
- Compose (steps 1-5) and BBS send are complete; the roadmap items are
  closed, the first SB and ST captures stay in ON-AIR-TESTS.

**Files:** `kissterm/mail/compose.py`, `kissterm/ui/compose.py`,
`kissterm/ui/app.py`, `kissterm/ui/styles.py`, `tests/pilot/test_compose.py`,
`docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-26] — ICS-213 reply on the form

### New Features

- **Reply on form**: R on a received ICS-213 offers the reply form,
  Winlink's ICS213_SendReply: the message's blocks 1-8 filled in and
  read-only, blocks 9-10 (Reply, Replied by, Position, Date/time) to
  fill. It goes out as any reply (SR on the BBS it came from), one
  record holding both halves. A received reply reads as the reply form.

**Files:** `kissterm/mail/data/forms/ics213_reply.toml` (new),
`kissterm/mail/data/forms/ics213.toml`, `kissterm/mail/forms.py`,
`kissterm/ui/form_screen.py`, `kissterm/ui/compose.py`, `kissterm/ui/app.py`,
`tests/pilot/test_forms.py`, `README.md`, `docs/ON-AIR-TESTS.md`,
`docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-26] — Received forms read as forms

### New Features

- **A received form is shown as the form**: the ICS-213, check-ins,
  situation reports, logs and information strips kissterm ships are
  recognised in Mail and Bulletins (by our own `Form:` header, or by the
  subject pattern and most of the form's labelled lines) and laid out
  label by label, a log's lines one under another. **V** on the list
  shows the text as received, and back. A message that is not clearly a
  form stays plain text.
- Each form file is its own parser: the round trip (fill, send, read
  back) is tested for every shipped form.

### Improvements

- The reader opens a message at its top rather than its end.
- A log's time column is named Time, its format shown as the hint.

**Files:** `kissterm/mail/form_parse.py` (new), `kissterm/ui/form_view.py`
(new), `kissterm/ui/mail_pane.py`, `kissterm/ui/wraplog.py`,
`kissterm/mail/forms.py`, `kissterm/ui/form_screen.py`,
`kissterm/mail/data/forms/`, `tests/unit/test_form_parse.py`,
`tests/pilot/test_mail_pane.py`, `README.md`, `DESIGN.md`,
`docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-26] — ICS-309 from mail

### New Features

- **Fill from mail** on the ICS-309: one log line per message in your
  Mail Inbox and Sent folders (BBS and Winlink, subfolders included)
  since the time you give, today by default, oldest first. It fills
  empty lines before adding new ones and never repeats a message
  already on the log. A form file turns it on with `mail_log`.

**Files:** `kissterm/mail/forms.py`, `kissterm/mail/data/forms/ics309.toml`,
`kissterm/ui/form_screen.py`, `kissterm/ui/app.py`, `kissterm/ui/styles.py`,
`tests/unit/test_mail_forms.py`, `tests/pilot/test_forms.py`, `README.md`,
`docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-26] — Radiogram preamble without NR

### Improvements

- A radiogram's preamble starts with its number (`46 R HXG ...`), as in
  RRI's 2026 guidelines and TPRFN's generator; the 2002 MPG's `NR` is
  dropped (operator's decision).

**Files:** `kissterm/mail/nts.py`, `tests/unit/test_mail_nts.py`,
`tests/pilot/test_radiogram.py`, `docs/PROTOCOL_GUIDE.md`,
`docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-26] — Radiogram-ICS213

### New Features

- **Radiogram-ICS213 (ST)** as a Type: the radiogram form with HXI
  filled in and a Subject row under the signature, sent as RRI's 2026
  guidelines give it for a traffic net: preamble with HXI, address, BT,
  text, BT, signer's name and position, the subject line. It is saved
  and routed like any radiogram, and must carry HXI.
- HXI is accepted as a handling code on any radiogram.

**Files:** `kissterm/mail/nts.py`, `kissterm/mail/compose.py`,
`kissterm/ui/radiogram.py`, `kissterm/ui/compose.py`, `kissterm/ui/app.py`,
`tests/unit/test_mail_nts.py`, `tests/pilot/test_radiogram.py`,
`README.md`, `docs/PROTOCOL_GUIDE.md`, `docs/ON-AIR-TESTS.md`,
`docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-26] — Forms: ICS-309, ICS-214 and ICS-205

### New Features

- **ICS-309 Communications Log**, **ICS-214 Activity Log** and **ICS-205
  Radio Plan**, from Winlink's standard templates: one line per logged
  message, activity or channel, with "Add line" up to Winlink's limit,
  and only the filled lines sent. Your name, position, agency and group
  title are remembered.
- The 205's bandwidth and mode are FEMA's codes (N/W; A, D or M), chosen
  from a list and checked; the 214's Prepared By is block 8 as on FEMA's
  form (Winlink's text calls it 4).

### Improvements

- A column chosen from a list is wide enough to show its name.

**Files:** `kissterm/mail/data/forms/`, `kissterm/mail/forms.py`,
`kissterm/ui/form_screen.py`, `tests/unit/test_mail_forms.py`, `README.md`,
`docs/ON-AIR-TESTS.md`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-26] — Forms: information strips

### New Features

- **Information strips** (`TITLE/question/.../question//`): GYX Weather
  Report (the NWS Gray SKYWARN strip) and MCF720 Price Survey ship as
  Types; "Information strip (paste)" answers any other. Each question is
  a field, your call and grid fill themselves, and the answer goes out
  as one line with an empty answer as three spaces.
- **Answer strip** on a reply whose original carries a request strip:
  the answer becomes the reply's text.
- A `/` inside parentheses stays in its question (MCF720's
  "Local/Regional Chain"), unlike bpq-apps, which splits it.

**Files:** `kissterm/mail/forms.py`, `kissterm/mail/data/forms/`,
`kissterm/ui/form_screen.py`, `kissterm/ui/compose.py`, `kissterm/ui/app.py`,
`tests/unit/test_mail_forms.py`, `tests/pilot/test_forms.py`, `README.md`,
`docs/PROTOCOL_GUIDE.md`, `docs/ON-AIR-TESTS.md`, `docs/ROADMAP.md`,
`kissterm/mail/AGENTS.md`, `docs/CHANGELOG.md`

## [2026-09-26] — Forms: situation reports

### New Features

- **Field Situation Report**, **Severe WX Report**, **Damage Assessment**
  and **Incident Status Report**, from Winlink's standard templates. The
  FSR's statuses start at "Unknown - N/A" with a comment beside each; the
  Severe WX report computes the metric figures from the imperial ones;
  the Damage Assessment totals each category and the cost; the Incident
  Status report prints the EOC status, declaration and evacuation
  details that Winlink's own text leaves out.
- A long title is cut at a word to BPQMail's 60 characters.

**Files:** `kissterm/mail/forms.py`, `kissterm/mail/data/forms/`,
`kissterm/ui/form_screen.py`, `kissterm/ui/styles.py`,
`tests/unit/test_mail_forms.py`, `tests/pilot/test_forms.py`, `README.md`,
`docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-26] — Forms: Winlink and PKTNET check-ins

### New Features

- **Winlink Check-in** (Winlink Wednesday and ARES Winlink nets), from
  Winlink's template 5.1.3: your call, grid square (from Settings >
  APRS) and the date fill themselves; the To you enter addresses the
  message. Band and session default to VHF packet.
- **PKTNET Check-in**, vden's PACKET CHECK-IN layout, which comes back to
  the compose screen already addressed `SB PKTNET@USA` and titled "Name,
  Call, Town, State" as the net asks.
- Your name, location, net address and band are remembered per form.

**Files:** `kissterm/mail/forms.py`, `kissterm/mail/data/forms/`,
`kissterm/mail/nts.py`, `kissterm/ui/form_screen.py`, `kissterm/ui/app.py`,
`tests/unit/test_mail_forms.py`, `tests/pilot/test_forms.py`, `README.md`,
`docs/PROTOCOL_GUIDE.md`, `docs/ROADMAP.md`, `docs/ON-AIR-TESTS.md`,
`docs/CHANGELOG.md`

## [2026-09-26] — Message forms: ICS-213 and ICS-213RR

### New Features

- **Forms in the compose screen.** Type now lists the ICS-213 General
  Message and ICS-213RR Resource Request. Fill in the form, Continue,
  and its text comes back to the compose screen to address and save.
  Your name and position are remembered between forms. The 213RR takes up
  to eight order lines.
- **Laid out as Winlink's standard forms** (Standard Forms 1.1.20.0,
  FEMA numbering), so a BBS reader, a Pat user or a Winlink Express user
  recognises them. The Winlink XML attachment comes with the Winlink
  client.
- A form is a data file: one engine and one screen serve every form,
  which is how check-ins, situation reports, strips and logs follow
  (ROADMAP P2 Forms, phases B-F).

**Files:** `kissterm/mail/forms.py`, `kissterm/mail/data/forms/`,
`kissterm/mail/compose.py`, `kissterm/mail/AGENTS.md`,
`kissterm/ui/form_screen.py`, `kissterm/ui/compose.py`,
`kissterm/ui/app.py`, `kissterm/ui/styles.py`, `pyproject.toml`,
`tests/unit/test_mail_forms.py`, `tests/pilot/test_forms.py`, `README.md`,
`docs/PROTOCOL_GUIDE.md`, `docs/ROADMAP.md`, `docs/ON-AIR-TESTS.md`,
`docs/CHANGELOG.md`

## [2026-09-26] — Radiogram sources recorded

### Improvements

- `docs/PROTOCOL_GUIDE.md` gains "NTS radiograms: sources and
  precedence": every source link behind `nts.py`, what each is used for,
  which wins where they disagree, and the open question (the BBS title).

**Files:** `docs/PROTOCOL_GUIDE.md`, `kissterm/mail/nts.py`,
`kissterm/mail/AGENTS.md`, `docs/CHANGELOG.md`

## [2026-09-26] — Radiograms: RRI 2026 layout and KY2D's title

### Improvements

- **BT separates the address, text and signature**, as in RRI/NTS 2.0's
  February 2026 radiogram guidelines, KY2D's review of the bpq-apps form
  and the Outpost packet guide; the 2002 MPG's blank lines are gone.
- **The BBS title is `CITY CALLSIGN`, `CITY NXX NXX` or `CITY - -`**
  (KY2D), replacing the MPG's `QTC CITY / NXX NXX`. The published guides
  disagree on the title; an on-air listing check is in ON-AIR-TESTS.
- An email address is written `ATSIGN` (RRI 2026) and `#` in an address
  is NR (KY2D). QUERY, spelled-out COMMA and the check rules were
  already what RRI 2026 says, so the Winlink-style punctuation in
  bpq-apps was not brought across.

**Files:** `kissterm/mail/nts.py`, `kissterm/mail/compose.py`,
`kissterm/mail/bpqmail.py`, `kissterm/mail/AGENTS.md`,
`tests/unit/test_mail_nts.py`, `tests/pilot/test_radiogram.py`,
`docs/ON-AIR-TESTS.md`, `docs/CHANGELOG.md`

## [2026-09-25] — Radiogram form: live conversion, Check field, compact

### Improvements

- **The radiogram text converts as you type**: each word becomes its
  radiogram form when you finish it (space or Enter), so `.` turns into X
  and `?` into QUERY in front of you; leaving the text drops a final X
  (MPG 1.3.1). An edit mid-text converts when you leave, so the cursor
  never jumps.
- **A read-only Check field** counts the groups beside the date.
- **The dialog is only as tall as its content** and narrower (90 columns);
  the form scrolls rather than push Save off an 80x24 screen.

**Files:** `kissterm/mail/nts.py`, `kissterm/ui/radiogram.py`,
`kissterm/ui/styles.py`, `tests/unit/test_mail_nts.py`,
`tests/pilot/test_radiogram.py`, `README.md`, `docs/CHANGELOG.md`

## [2026-09-25] — NTS radiograms (ST)

### New Features

- **Type: NTS radiogram** in the compose screen opens an ARRL radiogram
  form, saved to the Outbox and sent by G as `ST <zip> @ NTS<state>` with
  the `QTC <town> / <phone>` title (ARRL MPG 6.2.1). The preview shows the
  text as it will be sent and what each ARL number means; the status line
  shows the check, routing and title as you type. The next message number
  and place of origin are suggested from earlier radiograms.
- Formatting follows the MPG chapter 1 rules, and ARL numbered texts are
  the v3.0 list (2025-10-07). Where bpq-apps' `forms.py` differed, the MPG
  wins; `nts.py`'s docstring lists each difference.

**Files:** `kissterm/mail/nts.py`, `kissterm/mail/data/arl_numbered.json`,
`kissterm/mail/compose.py`, `kissterm/mail/AGENTS.md`, `kissterm/ui/radiogram.py`,
`kissterm/ui/compose.py`, `kissterm/ui/app.py`, `kissterm/ui/styles.py`,
`pyproject.toml`, `tests/unit/test_mail_nts.py`, `tests/pilot/test_radiogram.py`,
`README.md`, `docs/ROADMAP.md`, `docs/ON-AIR-TESTS.md`, `docs/CHANGELOG.md`

## [2026-09-25] — Settings, simplified

### Improvements

- **The sections are a list down the left**, all visible. The 16 tabs ran
  off the right edge and hid six sections. They are now 11: Station, Radio,
  Link, Mail, APRS, Beacon, Answering, Alerts, Appearance, Logging, Logins.
- **One row per field**, with the help for the focused field in one line
  at the bottom, including when it takes effect and any error in red. Save
  with a bad value opens that field and puts the cursor on it.
- **Tuning is folded under each section's Advanced**, shut by default: a
  new operator sees 38 fields instead of 83. The custom theme
  colours show only while Theme is Custom. On/off fields are a checkbox
  that says "on" or "off".
- Fits 80x24. Startup is about 0.6 s faster (Settings went from 677
  widgets to 407).

**Files:** `kissterm/ui/settings_pane.py`, `kissterm/ui/settings_schema.py`,
`kissterm/ui/symbol_picker.py`, `kissterm/ui/styles.py`, `kissterm/ui/app.py`,
`kissterm/ui/dialogs.py`, `kissterm/mail/collect.py`, `kissterm/guides.py`,
`kissterm/config.py`, `tests/pilot/test_settings.py`,
`tests/pilot/test_app_mounts.py`, `tests/pilot/test_addressbook_pane.py`,
`scripts/generate_screenshot.py`, `assets/`, `README.md`, `SETUP.md`,
`DESIGN.md`, `kissterm/ui/AGENTS.md`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-25] — The Address Book on Mail, Bulletins and Files

### Improvements

- **Ctrl+G on Mail, Bulletins or Files slides the Address Book in** to pick
  a BBS and dial it, without going to Terminal first. It never opens by
  itself there, lists stations only, and takes its width from the list and
  reader rather than the folder tree (on 80 columns it replaces them while
  open). A dial closes it and moves to Terminal; Escape closes it. An edit
  made in any copy shows in all of them.

**Files:** `kissterm/ui/mail_pane.py`, `kissterm/ui/addressbook_pane.py`,
`kissterm/ui/app.py`, `kissterm/ui/commands.py`, `kissterm/ui/styles.py`,
`tests/pilot/test_mail_addressbook.py`, `README.md`, `DESIGN.md`,
`docs/ON-AIR-TESTS.md`, `docs/CHANGELOG.md`

## [2026-09-25] — Address Book entry dialog: every field whole, fits 80x24

### Bug Fixes (awaiting operator confirmation)

- **The Paclen/Window row was drawn crushed behind the Note field**: it had
  no CSS, so it got no height. **Save and Cancel were below the bottom of
  an 80x24 screen**, unreachable. The dialog is now labelled one-row
  fields (Station, Hops, Freq/Port, Paclen/Window, Note, Login, the login
  lines), fits 80x24 whole, and scrolls its fields inside a capped box on
  anything smaller, with the buttons always on screen.

**Files:** `kissterm/ui/dialogs.py`, `kissterm/ui/styles.py`,
`tests/pilot/test_addressbook_pane.py`, `DESIGN.md`, `docs/CHANGELOG.md`

## [2026-09-25] — Send/Receive, green progress, and a stalled frame named

### Improvements

- **G is now Send/Receive** (menu: Session > Send/Receive, S), since it
  sends the Outbox as well as collecting.
- **The status bar shows its progress in green words**: `Connecting to
  WS1EC-2`, `Sending 1 of 2`, `Checking for mail`, `Receiving 2 of 4`,
  instead of `GET MAIL <phase>` (DESIGN.md section 6).
- **A send whose text never reaches the BBS says so.** On 2026-09-25 the
  body of a message to W1BKW went as one 182-byte frame, was retried
  30-37 times in each of three runs, and never arrived, while the node
  answered every poll; the run reported "nothing from the BBS for 300 s".
  It now reports that what was sent had not reached the BBS, the frame
  size, and that a smaller paclen on the Address Book entry sends shorter
  frames. `AX25Link.unacked_sizes` (read-only) is what tells the two apart.
- **`docs/ON-AIR-TESTS.md`**: the tests waiting for the radio, with what
  to do and what to expect (AGENTS.md section 7).

**Files:** `kissterm/ax25/session.py`, `kissterm/mail/collect.py`,
`kissterm/mail/compose.py`, `kissterm/ui/app.py`, `kissterm/ui/commands.py`,
`kissterm/ui/mail_pane.py`, `kissterm/ui/dialogs.py`,
`kissterm/ui/settings_schema.py`, `kissterm/config.py`,
`config.toml.example`, `tests/unit/test_mail_collect.py`,
`tests/pilot/test_get_mail.py`, `README.md`, `DESIGN.md`, `AGENTS.md`,
`docs/ON-AIR-TESTS.md`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-25] — Compose gives its rows to the text

### Improvements

- **The compose dialog has no empty rows**: one-row (compact) To, @ and
  Title fields, the SR note beside the heading, the buttons and any error
  on one row, and the message text takes everything left. At 80x24 the
  text went from 2 rows to 12 or more. DESIGN.md section 3, "Dense where
  the content is the point", makes this the rule for any screen whose
  job is writing or reading text, with compact controls that show focus
  as a tint.

**Files:** `kissterm/ui/compose.py`, `kissterm/ui/styles.py`,
`tests/pilot/test_compose.py`, `DESIGN.md`, `docs/CHANGELOG.md`

## [2026-09-25] — G sends the Outbox, then reads

### New Features

- **Get mail (G) sends Mail > BBS > Outbox before it lists and reads**,
  oldest first: `SR n` for a reply to that BBS's message n, else `SP` or
  `SB`, the title when asked, the body in as few frames as paclen allows,
  `/EX`. A message moves to Sent, with the BBS's number and BID, only
  after `Message: N Bid: ...`. A refusal (`*** ...`) stops the run, names
  the reason and leaves the message in the Outbox. The toast counts sent
  and received.

### Improvements

- **The BBS prompt pattern accepts LinBPQ's default `de CALL>`** as well
  as WS1EC's `de WS1EC#>`: the source says the default; only the captures
  had the `#`.

**Files:** `kissterm/mail/collect.py`, `kissterm/mail/bpqmail.py`,
`kissterm/mail/store.py`, `kissterm/ui/app.py`, `kissterm/ui/commands.py`,
`tests/unit/test_mail_collect.py`, `tests/unit/test_mail_bpqmail.py`,
`tests/pilot/test_get_mail.py`, `README.md`, `docs/ROADMAP.md`,
`docs/CHANGELOG.md`

## [2026-09-25] — Write, reply to and quote BBS mail into the Outbox

### New Features

- **Compose BBS mail from the Mail tab.** Insert writes a new private
  message (SP) or bulletin (SB); R replies; Q replies with the original
  quoted as `> ` lines. Saving files it in Mail > BBS > Outbox and
  transmits nothing; sending the Outbox is the next step.
- **A reply to a message read from the Home BBS goes out as `SR <n>`**:
  the BBS addresses and titles it, one prompt fewer on air. To and Title
  are shown but not editable, and the screen says why.
- **BPQMail's limits are checked before saving**: To of 6 characters with
  no SSID, a title of 1-60 characters, `@` of 40, and no body line that
  would end the message early (`/ex`, Ctrl-Z).
- **Settings > Mail > Quote in replies (R)**, off by default. Q always
  quotes; the quote is editable text either way. Esc asks before
  discarding typed text.

**Files:** `kissterm/mail/compose.py`, `kissterm/ui/compose.py`,
`kissterm/ui/mail_pane.py`, `kissterm/ui/app.py`, `kissterm/ui/commands.py`,
`kissterm/ui/styles.py`, `kissterm/ui/settings_schema.py`,
`kissterm/config.py`, `config.toml.example`, `tests/unit/test_mail_compose.py`,
`tests/pilot/test_compose.py`, `README.md`, `DESIGN.md`, `docs/ROADMAP.md`,
`docs/CHANGELOG.md`

## [2026-09-25] — BPQMail send researched; plan for compose and send

### Improvements

- **How BPQMail takes a message is written down**, from the LinBPQ source
  and the operator's SP and SR captures (`bpqmail.py` docstring, two new
  fixtures). Size in the acceptance line counts CRLF endings, which
  confirms the BBS stored the blank lines the transcript had dropped.
- **Rule: research a protocol from its source first, then verify with a
  capture** (AGENTS.md section 7, `kissterm/mail/AGENTS.md`).
- ROADMAP P2: the compose, reply (SR), send, SB and ST radiogram plan.

**Files:** `kissterm/mail/bpqmail.py`, `kissterm/mail/AGENTS.md`,
`AGENTS.md`, `tests/unit/data/bpqmail/`, `docs/ROADMAP.md`,
`docs/CHANGELOG.md`

## [2026-09-25] — Transcript keeps a blank line that ends a frame

### Bug Fixes (awaiting operator confirmation)

- **The session transcript dropped a blank line that fell at the end of a
  frame**, so messages 2801 and 2803 read back from WS1EC-2 looked as if
  BPQMail had lost blank lines between paragraphs. The frames carried
  them (the first ended `Hi Dave,\r\rI received y`); the terminal showed
  them; only the transcript file stripped them.

**Files:** `kissterm/session_log.py`, `tests/unit/test_session_log.py`,
`docs/CHANGELOG.md`

## [2026-09-25] — Get mail progress in the status bar; where messages go

- **Get mail says "1 received", not "1 filed"**: at a glance "filed" read
  as "failed" (2026-09-25). An incomplete read now says "nothing saved".

- **One click on a message shows it in the reader**, as Enter does; it
  used to take Enter (or a second click). The Address Book keeps
  click-to-select, since opening an entry there dials.

### Decisions

- **A poll that arrives after a connect has failed is still answered DM**,
  as AX.25 2.2 says. The WS1EC-2 log of 2026-09-25 02:00 showed the node
  accepting our last SABM and polling after we gave up, while hearing none
  of our 7 DMs: an uplink RF problem, not one to paper over in the stack.
  Recorded in AGENTS.md section 3.

### Improvements

- **Get mail no longer pushes a status line in above the message list.**
  Its progress is a status-bar field (`GET MAIL connecting WS1EC-2`,
  `GET MAIL reading 1/3`) that goes away when it ends; the start and the
  outcome (new messages, no new mail, stopped and why, could not connect)
  are toasts.
- **DESIGN.md section 6, "Where a message goes"**: a lasting state goes in
  the status bar, an event in a toast, the session record in the terminal;
  never a line inserted into a pane's content, and no message in two
  places.

**Files:** `kissterm/ui/app.py`, `kissterm/ui/mail_pane.py`,
`kissterm/ui/styles.py`, `kissterm/mail/collect.py`,
`kissterm/ui/mail_pane.py`, `tests/pilot/test_mail_pane.py`,
`tests/unit/test_mail_collect.py`, `tests/pilot/test_get_mail.py`, `DESIGN.md`, `AGENTS.md`, `docs/CHANGELOG.md`

## [2026-09-24] — Menu headings always shown; Get mail stays on the Mail tab

### Improvements

- **The menu headings are always on the top row** (Session, APRS, View,
  Help), as in Midnight Commander; a click opens one, and a click anywhere
  outside the open menu closes it. Textual's palette icon stays at the far
  left, with the headings to its right.
- **Get mail leaves you on the Mail tab**: a toast says it is connecting,
  and a status line above the list follows it (connecting, reading 1 of 2,
  done or why it stopped). The session is still in the Terminal tab. The
  connect no longer moves focus into the hidden send line, which is what
  switched tabs.

### Bug Fixes (closed)

- **G was missing from the bottom bar at launch** although the Mail list
  had focus: the bar is redrawn on a tab switch, not on focus. It is now
  redrawn when the launch tab takes focus.

**Files:** `kissterm/ui/clock.py`, `kissterm/ui/menu.py`,
`kissterm/ui/app.py`, `kissterm/ui/mail_pane.py`, `kissterm/ui/styles.py`,
`tests/pilot/test_get_mail.py`, `tests/pilot/test_menu_and_help.py`,
`tests/pilot/test_app_mounts.py`, `DESIGN.md`, `assets/`,
`docs/CHANGELOG.md`

## [2026-09-24] — Get mail: setup on first use, G in the bar and menu, calmer Settings

### Improvements

- **G with no Home BBS asks which Address Book entry reaches the BBS**,
  saves it and carries on, instead of pointing at Settings. With an empty
  Address Book it says to connect to the BBS once first. Nothing is sent
  until the normal connect.
- **G shows in the bottom bar and beside Get mail in the F10 menu.** The
  Mail tab now focuses its message list when it opens, including at
  launch, and G works from the folder tree too. Before, focus sat on the
  tab strip and the Mail keys were neither shown nor working.
- **Settings no longer prints "takes effect now" beside most fields**:
  Save applies them. "next connection" and "needs a restart" stay.
- **Home BBS sets off its last three fields** under a rule: "Only if the
  BBS software is not identified automatically".

**Files:** `kissterm/ui/app.py`, `kissterm/ui/dialogs.py`,
`kissterm/ui/mail_pane.py`, `kissterm/ui/commands.py`,
`kissterm/ui/menu.py`, `kissterm/ui/settings_pane.py`,
`kissterm/ui/settings_schema.py`, `kissterm/ui/styles.py`,
`tests/pilot/test_get_mail.py`, `tests/pilot/test_settings.py`,
`tests/unit/test_commands.py`, `tests/unit/test_key_standard.py`,
`README.md`, `DESIGN.md`, `docs/CHANGELOG.md`

## [2026-09-24] — Get mail: collect from the Home BBS (Mail tab, G)

### New Features

- **G on the Mail tab gets your mail from the Home BBS.** It dials the
  Address Book entry named in Settings > Home BBS the normal way (reminder,
  transmit gate, hops, the entry's login), switches to the Terminal tab,
  waits for the BBS prompt, lists with `LM` and reads only messages
  kissterm does not already have, oldest first. Each complete read is filed
  in Mail/BBS/Inbox with the raw reply beside it (`.bbs`); then it
  disconnects. Page prompts are answered with Enter. It stops by name on a
  dropped link, a closed transmit gate, five minutes of silence, a reply it
  does not recognise or a BBS that is not BPQMail. Messages stay on the
  BBS. Ctrl+D stops it at any time.
- **Settings > Home BBS**: the entry to dial, the BBS callsign (read from
  its prompt when empty), software (automatic or BPQMail), and for other
  BBSes a ready text and a login prompt with a saved credential.

**Files:** `kissterm/mail/collect.py`, `kissterm/mail/store.py`,
`kissterm/config.py`, `kissterm/ui/app.py`, `kissterm/ui/mail_pane.py`,
`kissterm/ui/commands.py`, `kissterm/ui/settings_schema.py`,
`config.toml.example`, `tests/unit/test_mail_collect.py`,
`tests/unit/test_mail_store.py`, `tests/unit/test_config.py`,
`tests/pilot/test_get_mail.py`, `tests/pilot/test_settings.py`,
`README.md`, `DESIGN.md`, `kissterm/mail/AGENTS.md`, `docs/ROADMAP.md`,
`docs/CHANGELOG.md`

## [2026-09-24] — Select and copy text in the scrollbacks

### Improvements

- **Drag to select text in the terminal, Monitor, APRS and mail reader, and
  `Ctrl+C` to copy it.** Nothing could be highlighted before: `RichLog`, which
  every scrollback is built on, has no selection support, and the app holds
  the mouse. `WrapLog` now supplies the selection, so all of them get it.
  The selection is copied when the drag ends, as herdr and other
  copy-on-highlight terminals do. The highlight keeps the text's own colour:
  tokyo-night's selection style is one colour on itself, which hid the text.

**Files:** `kissterm/ui/wraplog.py`, `kissterm/ui/app.py`, `tests/pilot/test_text_selection.py`,
`tests/unit/test_docs_keys.py`, `README.md`, `DESIGN.md`, `docs/CHANGELOG.md`

## [2026-09-24] — Default T2 is 1 s; the shipped timers failed their own check

### Bug Fixes (closed)

- **Saving Settings warned "T1 should be longer than T2" on the default
  config**: `t1` and `t2` both shipped as 3 s. T2 now defaults to 1 s, as
  `LinkParams` always did. A value already saved in config.toml is kept.

**Files:** `kissterm/config.py`, `config.toml.example`,
`tests/unit/test_config.py`, `docs/CHANGELOG.md`

## [2026-09-24] — A poll while connecting sends the next SABM at once

### Improvements

- **When the node polls during a connect, kissterm sends the next SABM
  straight away** instead of waiting out T1. A poll means the node accepted a
  SABM and its UA was lost; the fresh SABM gets a fresh UA. Counts against
  `connect_retries`. On by default; Settings > Link > "Retry at once when
  polled" (`sabm_on_poll`) turns it off, which follows AX.25 2.2 and ignores
  the poll.
- **A frame from the peer during a connect is no longer answered DM**, which
  told the node to drop the link it had just accepted.

**Files:** `kissterm/ax25/session.py`, `kissterm/config.py`,
`kissterm/ui/settings_schema.py`, `kissterm/ui/app.py`,
`kissterm/__main__.py`, `config.toml.example`, `AGENTS.md`,
`tests/unit/test_ax25_link.py`, `docs/CHANGELOG.md`

## [2026-09-24] — Connect retries back to 10, the AX.25 default

### Improvements

- **A connect now sends 11 SABMs (about 33 s) before giving up, not 6.** On
  the weak path to WS1EC-2 the node heard a SABM but its UA was lost, and
  its poll for the link it thought was up arrived 6 to 12 s after we had
  stopped. More SABMs give a UA more chances. Still a separate setting from
  N2; a `connect_retries` already in config.toml keeps its value.

**Files:** `kissterm/ax25/session.py`, `kissterm/config.py`,
`kissterm/ui/settings_schema.py`, `config.toml.example`, `README.md`,
`AGENTS.md`, `docs/CHANGELOG.md`

## [2026-09-24] — BPQMail: private read, kill and not-found from captures

### Improvements

- **The BPQMail parser now covers a private message read to its end, the
  reply to `K`, and `R` of a message that does not exist**, from the
  operator's WS1EC-2 session. `killed()` and `not_found()` read the last two.
- **`LM` captured**: it lists read mail as well as unread, so collection will
  go by BID, not status. `waiting()` reads the greeting's unread count.
  `LM` with no mail at all answers with the prompt alone (captured the same
  day, `list_lm_empty.txt`).

**Files:** `kissterm/mail/bpqmail.py`, `tests/unit/test_mail_bpqmail.py`,
`tests/unit/data/bpqmail/`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-24] — One click dialed; a double click dialed twice and jammed the connect

### Bug Fixes (open until confirmed on the air)

- **Connects to WS1EC-2 failed while the node was answering.** The log shows
  two connects to the same station 200-400 ms apart (a double click on the
  dial and again on the reminder's Connect), so every SABM went out twice.
  Our second SABM keyed the radio over the node's UA, so we never heard it;
  the node then polled a link it thought was up, and we answered DM. Now a
  second request while one is calling is refused ("Already connecting"),
  and `AX25Station.connect` joins a link still in its SABM phase instead of
  orphaning it.
- **One click on an Address Book row dialed it.** DataTable selects on a
  click of the row that already has the cursor (the top row at launch), so
  one click on WS1EC-2 transmitted, and a double click dialed twice. WS1EC-2
  has no frequency on file, so no "Before connecting" reminder stood in the
  way. Now one click selects; `Enter` or a double click dials once.

**Files:** `kissterm/ax25/session.py`, `kissterm/ax25/station.py`,
`kissterm/ui/app.py`, `kissterm/ui/addressbook_pane.py`,
`tests/unit/test_ax25_link.py`, `tests/pilot/test_connect_scripts.py`,
`tests/pilot/test_addressbook_pane.py`, `README.md`, `docs/CHANGELOG.md`

## [2026-09-24] — Tests could overwrite the operator's real config

### Bug Fixes (closed)

- **A test run replaced the operator's config.toml with test settings**
  (callsign N1ABC-1, no transports), so the next launch asked for the
  callsign and radio again. Cause: many unit test files import kissterm
  without `isolate()`; when one was listed ahead of pilot tests in a
  parallel run, that worker fixed `kissterm.config`'s paths on the real
  directories, and a pilot test that saves a callsign wrote the real file.
  Reproduced under a throwaway HOME. Fix: `tests/conftest.py` isolates
  before any test file loads, `isolate()` reuses one scratch tree per
  process, and `pytest_configure` refuses to run if the paths are not the
  scratch tree.

**Files:** `tests/conftest.py`, `kissterm/_isolate.py`, `AGENTS.md`

## [2026-09-23] — Mail, Bulletins and Files tabs; Mail is the launch tab

### New Features

- **Mail (F2), Bulletins (F3) and Files (F4)**, one shared widget
  (`kissterm/ui/mail_pane.py`): folder tree, list, reader. Mail's tree
  starts with All Inboxes; unread counts are on the folders; Enter opens
  and marks read, Delete moves to Deleted, U restores. The reader shows
  remote text sanitized and never as markup; Files lists files and
  previews text only. Nothing on these tabs transmits.
- **Mail is the launch tab**; Settings > Appearance > Open on
  (`start_tab`) keeps Terminal, APRS or Monitor instead.

### Improvements

- **Tabs renumbered** per DESIGN.md section 5: Terminal F5, APRS F6,
  Heard F7, Monitor F8. In the F10 View menu Mail is M and Monitor is O.
- The pilot tests launch on Terminal through `tests/pilot/conftest.py`
  (they were written before Mail); `tests/unit/test_start_tab.py` checks
  the real default.

**Files:** `kissterm/ui/mail_pane.py`, `kissterm/ui/app.py`,
`kissterm/ui/commands.py`, `kissterm/ui/styles.py`,
`kissterm/ui/settings_schema.py`, `kissterm/config.py`,
`config.toml.example`, `scripts/generate_screenshot.py`, `assets/`,
`tests/pilot/test_mail_pane.py`, `tests/pilot/conftest.py`,
`tests/pilot/test_app_mounts.py`, `tests/unit/test_start_tab.py`,
`README.md`, `DESIGN.md`, `docs/ROADMAP.md`

## [2026-09-23] — Mail: reading BPQMail's replies

### New Features

- **BPQMail parser (`kissterm/mail/bpqmail.py`)**, written from the
  operator's captured sessions with WS1EC-2: listing lines, a read split
  into headers, `R:` routing lines and body, page prompts dropped, the
  year supplied for `Date/Time:`. A read counts as complete only when
  `[End of Message #N from CALL]` arrives; an aborted read is never
  filed. The captures are test fixtures in `tests/unit/data/bpqmail/`.
  No session driver yet.
- **Page prompts are cut out wherever they appear**, including glued to
  text, and a read parses the same with paging on or off (`OP` is a
  per-user BBS setting).
- **All Inboxes**: one list of every Inbox under Mail, newest first
  (`MessageStore.list_inboxes`); a view, not a folder. **Mail/Local is no
  longer created** until P9's mailbox exists to fill it.

**Files:** `kissterm/mail/bpqmail.py`, `kissterm/mail/AGENTS.md`,
`kissterm/mail/store.py`, `tests/unit/test_mail_bpqmail.py`,
`tests/unit/test_mail_store.py`, `tests/unit/data/bpqmail/`, `docs/ROADMAP.md`

## [2026-09-23] — Mail: the message store

### New Features

- **Message store (`kissterm/mail/`), the first piece of P2 Mail.** One
  plain-text file per message (`Key: value` headers, blank line, body)
  in a folder tree that mirrors the planned Mail tab: Winlink, BBS
  accounts, Local, Bulletins by category, Files. The index is a cache
  rebuilt from the files. Deleted is a folder; restore puts a message
  back where it was, and only purge from Deleted removes a file. Raw
  copies (`.b2f`) move with their message. Lookup by Message-Id is there
  so BBS collection can avoid filing a message twice. No UI yet.
- **Folders separate kinds of mail, not sources** (operator's decision):
  one `Mail/BBS` mailbox and one `Bulletins` tree by category, however the
  home BBS was reached (node, NET/ROM alias, direct). Each message's
  `Source:` header names the BBS by its own callsign; duplicate checks use
  Message-Id plus that source, so a second route never re-downloads mail.

**Files:** `kissterm/mail/`, `kissterm/config.py` (`mail_path`),
`tests/unit/test_mail_store.py`, `AGENTS.md`, `docs/ROADMAP.md`

## [2026-09-23] — Documentation diet; P0 cleared

### Improvements

- **AGENTS.md is cut from 1,263 lines to about 420.** Each rule is now a
  sentence or two and points to the code or test that enforces it. The full
  version, with each rule's history, is in git at commit `6d81202`.
- **CHANGELOG entries from 2026-09-21 and earlier moved to
  `docs/CHANGELOG-archive.md`** (4,250 lines). This file keeps the entries
  since the P0 rewrite. The roadmap had planned this for after 1.0; it was
  done now because of the tokens every session spends reading this file.
- **DESIGN.md section 5 is the keyboard standard, without its history.**
  The suggestion-list paragraph now describes the current keys: Up/Down,
  Tab, Esc.
- The memory note that required the full test suite before every commit
  was wrong and has been replaced: run targeted tests only.

### Bug Fixes (closed)

- **The Terminal pane's message queue drains on a real station.** Closed on
  the operator's live session: the idle-flush timer that assembles node
  output ran correctly ("Text output from the node is perfect now"). Before
  the fix (`FrameTransport.callback_context`), that timer's callback never
  ran on air.
- **Flaky pilot tests under parallel load (P0.4).** Every test known to be
  flaky now waits on a condition (`tests/pilot/_wait.py`), and the one hang
  is fixed. A future flaky test is filed as a new P0.1 bug with its failure
  output; an open "confirming" item made a full-suite run a chore on every
  change.

P0 has no open items.

**Files:** `AGENTS.md`, `DESIGN.md`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`,
`docs/CHANGELOG-archive.md` (new), `kissterm/ui/commands.py`,
`kissterm/ui/app.py`, `kissterm/ui/terminal_pane.py` (comments only)

## [2026-09-23] — The status bar says "disconnected"; UTF-8 fix confirmed

### Improvements

- **The status bar shows `disconnected` when no session is on screen**, at
  launch or after its tab is closed. Before, it showed `WS1EC-7 connected`
  during a session and `WS1EC-7 disconnected` after one ended, but no link
  field at all otherwise. Requested: "I would like to see a Disconnected
  status as well". With no transport configured, it still shows only
  `NO TRANSPORT`.

### Bug Fixes

- The operator confirmed on air that `R 2738` now shows its UTF-8
  characters correctly. The item is removed from P0.1.
- A pilot test that could hang the whole suite now waits for its dialog to
  mount before pressing a button in it (P0.4).

**Files:** `kissterm/ui/app.py`, `tests/pilot/test_terminal_sessions.py`,
`tests/pilot/test_terminal_ux.py`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-23] — Ctrl+R reconnects; node commands move to F1 and the menu

### New Features

- **Ctrl+R on the Terminal tab reconnects** to the station that tab was
  last connected to. Requested: "Let's drop ^R Commands, and let the end user
  hit F1 for the context aware help tab, and change ^R to Reconnect".
  - The whole connect is replayed, hop chain, login and port included.
  - It goes through the ordinary connect flow: the radio reminder, the TNC
    link check, and the visible transmit arming, as for a dial from the
    Address Book.
  - It does nothing to a tab that is still connected. With nothing dialed
    yet, it says so and sends nothing.
  - A tab that answered an incoming call has no connect of its own to
    replay, so Reconnect dials that caller directly.

### Improvements

- **The node command reference has no key on the Terminal tab now.** F1
  shows the reference for the node you are on. F10 > Help > Node commands
  opens the screen that fills the send line, with the harvest and Forget
  learned buttons. On the APRS tab, Ctrl+R is still Services.
- The guides, README, DESIGN.md and the Help tab's note now point to F1 and
  the menu instead of Ctrl+R.

**Files:** `kissterm/ui/app.py`, `kissterm/ui/commands.py`,
`kissterm/ui/help_pane.py`, `kissterm/ui/terminal_pane.py`,
`kissterm/guides.py`, `tests/pilot/test_connect_scripts.py`,
`tests/pilot/test_terminal_ux.py`, `tests/pilot/test_menu_and_help.py`,
`tests/unit/test_commands.py`, `tests/pilot/test_app_mounts.py`, `README.md`,
`DESIGN.md`, `assets/`, `docs/CHANGELOG.md`

## [2026-09-23] — Close tab is a small X and Ctrl+W

### Improvements

- **The Close button is now a one-cell X at the end of the tab row, and the
  key is Ctrl+W.** The operator's verdict on the button was "an
  unnecessarily huge close tab button, and it's present when there are no
  2nd tab".
  - The X is one text row, like a tab label. Its tooltip says whether it
    will disconnect or close.
  - The Terminal row, X included, is hidden until there is a second
    session. The earlier version hid only the tabs, so the button showed
    anyway.
  - `^W Close` is in the Footer while there is a tab to close: any
    Terminal session, or an APRS conversation (not All or Bulletins).
    Reported: "I don't see ^w in the shortcut bar".
  - Ctrl+W is the tenth global Ctrl key (DESIGN.md section 5). It is
    priority-bound, so it works while you type in the send line. Inside a
    dialog it is still delete-word.
- **Ctrl+Backspace and Ctrl+Delete delete the word to the left and right**
  in the send line and the APRS To and compose boxes (`WordInput`). Textual
  had Ctrl+Backspace deleting to the right, and Ctrl+W, the old
  delete-word, is Close tab now. Some terminals send Ctrl+Backspace as plain
  Backspace; `scripts/keycheck.py` shows what yours sends.

**Files:** `kissterm/ui/tabclose.py` (new), `kissterm/ui/inputs.py` (new),
`kissterm/ui/terminal_pane.py`, `kissterm/ui/aprs_pane.py`,
`kissterm/ui/app.py`, `kissterm/ui/commands.py`, `kissterm/ui/styles.py`,
`tests/pilot/test_terminal_sessions.py`,
`tests/pilot/test_aprs_conversation_tabs.py`,
`tests/unit/test_key_standard.py`, `tests/unit/test_docs_keys.py`,
`DESIGN.md`, `AGENTS.md`, `README.md`, `assets/`, `docs/CHANGELOG.md`

## [2026-09-23] — Close tab is in the menu and on screen

### Improvements

- **Terminal and APRS tabs can be closed without knowing a hidden key.**
  Delete on the focused tab row was the only way (requested: "There needs to
  be a more evident way to do it"). Each tab row now has a Close button, and
  the F10 menu has Session > Close tab and APRS > Close conversation.
  - A connected Terminal tab is disconnected first. Its button reads
    Disconnect until then.
  - The APRS button is disabled on All and Bulletins, which stay open.
- No shortcut key was added. The nine global Ctrl keys are all taken, Ctrl+W
  is delete-word in the send line, and F6-F8 are reserved for the
  milestone-2 tabs.

### Bug Fixes

- **Switching to Settings no longer risks crashing the app on shutdown.** An
  activation still queued as the app closed reached for a pane that was
  already gone, and `NoMatches` escaped the handler. Found by a test.
- Two pilot tests that depended on timing now wait on their conditions
  (P0.4).

**Files:** `kissterm/ui/terminal_pane.py`, `kissterm/ui/aprs_pane.py`,
`kissterm/ui/app.py`, `kissterm/ui/commands.py`, `kissterm/ui/styles.py`,
`tests/pilot/test_terminal_sessions.py`,
`tests/pilot/test_aprs_conversation_tabs.py`, `tests/pilot/test_app_mounts.py`,
`tests/pilot/test_transcript_and_color.py`, `README.md`, `assets/`,
`docs/CHANGELOG.md`

## [2026-09-23] — BBS listing line breaks confirmed fixed

- The operator confirmed on a live session (0.1.221, WS1EC-2 `LR` and
  `R 2712`) that node output renders correctly; the transcript shows every
  listing line whole, with no blank lines. Removed from P0.1 after three
  attempts; the root cause is in the "slow frames" entry below.

**Files:** `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-23] — Esc hides the suggestion list

### Improvements

- **Esc hides the send line's suggestion list** so the scrollback under it
  can be read before a command is sent. The typed text stays, and the list
  returns on the next keystroke. On the Terminal pane, Esc closes one thing
  per press: the suggestion list, then the find bar, then the side panel.
  The list's hint line says so.

**Files:** `kissterm/ui/terminal_pane.py`, `tests/pilot/test_terminal_ux.py`,
`README.md`, `DESIGN.md`, `docs/CHANGELOG.md`

## [2026-09-23] — Forget a node's learned commands

### New Features

- **Ctrl+R has a "Forget learned" button** while the node has learned
  commands. It asks first, then drops everything learned from that node,
  in every context, from the cache and the open session. The shipped
  reference stays, and nothing is transmitted. Requested so a cache written
  before harvests were filed by context can be cleared: it held a node's
  and its BBS's `?` replies as one list, with prose words the old parser
  picked up.

### Confirmed

- The operator confirmed that the shortcut bar follows tab switches and that
  toasts no longer repeat what is on screen; both are removed from P0.1.

**Files:** `kissterm/harvested.py`, `kissterm/ui/app.py`,
`kissterm/ui/dialogs.py`, `tests/pilot/test_terminal_ux.py`,
`tests/unit/test_harvested.py`, `docs/CHANGELOG.md`, `docs/ROADMAP.md`

## [2026-09-23] — UTF-8 text from a BBS reads correctly

### Bug Fixes

- **Curly quotes, accents and other non-ASCII characters in BBS messages
  display correctly.** WS1EC-2 stores messages as UTF-8, and kissterm decoded
  everything as latin-1 and stripped bytes 0x80-0x9F. That turned
  "School No. 200" in curly quotes into `âSchool No. 200â` (`R 2738`).
  Remote text is now decoded as UTF-8 when it is valid UTF-8 and as latin-1
  otherwise. A corrupt frame still never raises or loses its readable part.
  C1 controls are removed after decoding, and bidirectional override
  characters are removed too, since UTF-8 makes them reachable and they can
  make a line read differently from what it says. The screen, the Monitor
  pane and transcripts all use the one decoder. AGENTS.md's
  "latin-1, never UTF-8" rule is replaced, at the operator's decision.

**Files:** `kissterm/ansi.py`, `kissterm/monitor.py`,
`kissterm/transport/ssh.py`, `tests/unit/test_ansi.py`, `AGENTS.md`,
`docs/CHANGELOG.md`, `docs/ROADMAP.md`

## [2026-09-23] — Six live bugs confirmed fixed

Confirmed by the operator on a live session with CCEMA/WS1EC-2 and checked
against that session's transcript and debug log, then removed from P0.1:
the last line or prompt never appearing; the focus highlight stuck on the
entry field; the "Before connecting" dialog staying up after Connect;
having to toggle transmit before the radio keyed (it was enabled at
12:51:03 and the first SABM went out 0.1 s later); the "Check the Monitor"
note for a node waiting on the operator (an empty line at a pager prompt,
answered 19 s later, raised no note); and duplicate WXBOT replies (one
query, one ack, one reply stored).

**Files:** `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-23] — A line split across slow frames stays one line

### Bug Fixes

- **BBS listings no longer break lines at frame boundaries or gain blank
  lines.** At 1200 baud the frames of one listing arrive about a second
  apart, which is longer than the 0.2 s idle after which the terminal shows
  a partial line. The pane then treated the rest of the line as a new row,
  and a line's CR arriving a frame late as an empty row (WS1EC-2 `L` and
  `R 2738`). A partial line shown on idle is now kept open and redrawn in
  place when the rest arrives. A prompt with no line end still appears
  after the idle.
- **Transcripts record whole lines.** They used to write one line per
  frame, so they showed the same breaks.
- The no-reply-note pilot test now waits on the note rather than a fixed
  0.5 s. It failed once under parallel load (P0.4).

**Files:** `kissterm/ui/terminal_pane.py`, `kissterm/ui/wraplog.py`,
`kissterm/session_log.py`, `kissterm/ui/app.py`,
`tests/pilot/test_terminal_ux.py`, `tests/pilot/test_transcript_and_color.py`,
`tests/unit/test_session_log.py`, `docs/CHANGELOG.md`, `docs/ROADMAP.md`

## [2026-09-23] — Keyboard standard and command catalog confirmed on air

- The operator confirmed on a live session that suggestions follow the
  node/BBS context and that F1 opens Help for the tab in use. The roadmap's
  P0.2 section is reduced to a pointer to DESIGN.md section 5, and the 1.0
  finish-line items for the keyboard and the command catalog are marked met.

**Files:** `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-23] — Every command row says where it came from

### Improvements

- **Harvested names are an overlay, not a second list.** A name from a
  node's own `?` reply that matches a documented command (or one of its
  aliases) marks that row **offered here** instead of adding a duplicate.
  A name that matches nothing is listed as "offered by this node, not in
  the published reference", in the suggestion strip and in Ctrl+R, and
  never gets an invented description.
- **Ctrl+R's Source column names the tier**: published, verified on air,
  recalled (unverified) or harvested only. It lists every context in reach:
  the current one first, then the node's applications, BPQMail and BPQChat
  at a BPQ32 node, or the node's commands while in its BBS. Sysop commands
  are labelled as such. The F1 Help node-command table uses the same tier
  names.
- README describes the context-following suggestions and the tiers. P0.3 is
  closed on the roadmap; FBB, the JNOS mailbox and capturing BPQChat on the
  air move to P8.

**Files:** `kissterm/nodes/reference.py`, `kissterm/ui/dialogs.py`,
`kissterm/ui/app.py`, `kissterm/ui/terminal_pane.py`,
`kissterm/ui/help_pane.py`, `tests/unit/test_nodes.py`,
`tests/pilot/test_terminal_ux.py`, `README.md`, `docs/CHANGELOG.md`,
`docs/ROADMAP.md`

## [2026-09-23] — Suggestions follow the session into the BBS and back

### Improvements

- **The send line suggests the commands of wherever the session is.** At a
  BPQ32 node, "L" offers LINKS. After the node says
  "CCEMA:WS1EC-15} Connected to BBS", it offers BPQMail's L, LR, LM ... LK,
  each with its description. After "Returned to Node", it offers the node's
  again. Both lines are read from what the node sends anyway, and the
  patterns live in the node's data file. BPQMail's commands are no longer
  offered at every prompt, where "L" meant something else.
- An application kissterm has no reference for (a sysop's own CALENDAR)
  and an unidentified prompt suggest nothing but names harvested from that
  station, rather than another system's commands. The status bar says where
  the session is: `BPQ32 > BPQMAIL`, `BPQ32 > CALENDAR`.
- Harvested names are filed and offered per context, so a BBS harvest's
  "L" is not offered at the node prompt. "Learn from node" defaults to the
  context the session is in.
- Sysop commands (PASSWORD, KH, ...) are listed in the reference but never
  suggested.
- Because G8BPQ uses the same "Connected to" words for a STAY hop to
  another node, an unknown name is treated as a hop while a typed hop is
  pending, and only a known application's name switches references.

**Files:** `kissterm/ui/app.py`, `kissterm/ui/terminal_pane.py`,
`kissterm/ui/dialogs.py`, `kissterm/nodes/reference.py`,
`tests/pilot/test_terminal_ux.py`, `docs/CHANGELOG.md`, `docs/ROADMAP.md`

## [2026-09-23] — BPQ32, BPQMail and BPQChat references from the published docs

### New Features

- **BPQMail and BPQChat have their own command references**
  (`kissterm/nodes/data/bpqmail.toml`, `bpqchat.toml`), as *application*
  families: reached from a node, with their own command language. BPQMail
  lists every user command in G8BPQ's BBS user-command page and in the
  WS1EC-2 BBS's own `?` reply (`LD`, `LF`, `LH`, `LK`, `LL`, `B`/`BYE`,
  `RMR`, `SB`, `ST`, `HOMEBBS` and the rest), with sysop commands marked.
  BPQChat lists the `/` commands from the chat server page. Each command
  records its source URL.

### Improvements

- **The BPQ32 node file is complete against G8BPQ's node command page**:
  abbreviations as documented, and the missing commands added (LINKS, STATS,
  VERSION, NRR, LISTEN, UNPROTO, PACLEN and others). Two entries written from
  memory were wrong: PING is an IP ping, not a node reachability test (that is
  NRR), and CQ works only in LISTEN mode. HELP is a sysop's help file,
  separate from `?`.
- **The BBS helper (Ctrl+R) reads BPQMail's reference file** instead of its
  own copy in `kissterm/bbs.py`, so the helper and the suggestions describe
  a command in the same words.

### Bug Fixes

- **A BPQ32 node's prompt is recognised from what the node sends.** The
  pattern expected `CALL-SSID:ALIAS}`; BPQ32 sends `ALIAS:CALL-SSID}`
  (`CCEMA:WS1EC-15}`), so it never matched, and the test fixture had been
  written to match the pattern rather than a node. CCEMA was identified only
  through its sysop's `de WS1EC>` sign-off.

**Files:** `kissterm/nodes/data/bpq32.toml`, `kissterm/nodes/data/bpqmail.toml`,
`kissterm/nodes/data/bpqchat.toml`, `kissterm/nodes/reference.py`,
`kissterm/bbs.py`, `tests/unit/test_nodes.py`, `tests/unit/test_bbs.py`,
`tests/pilot/test_terminal_ux.py`, `tests/pilot/test_connect_scripts.py`,
`docs/CHANGELOG.md`, `docs/ROADMAP.md`

## [2026-09-23] — README's key table is generated from the registry

### Improvements

- **README's key table comes from `COMMANDS`**, like the bindings, Footer,
  menu, Help keys page and palette already did. `scripts/sync_docs.py`
  rewrites it between markers; `tests/unit/test_docs_keys.py` fails if it is
  stale. Keys named in running prose are checked instead: every
  "Settings (F9)"-style tab mention in README, SETUP and DESIGN must match
  the tab's real key, and every Ctrl key README and SETUP name must be bound.
- The check found what the hand-kept copies had let drift: README sent
  operators to "Settings (F5)" in five places (F5 is Monitor), and DESIGN's
  Footer sketch still showed `F1 Help`, which moved to the tab row.

**Files:** `kissterm/ui/commands.py`, `scripts/sync_docs.py`, `README.md`,
`DESIGN.md`, `tests/unit/test_docs_keys.py`, `docs/CHANGELOG.md`,
`docs/ROADMAP.md`

## [2026-09-23] — Pilot tests wait on conditions, not the clock

### Bug Fixes

- **The Heard pane no longer crashes if refreshed before it has mounted.**
  The app's 2 s refresh and tab activation could reach `HeardPane` before its
  table existed, and `query_one` raised `NoMatches` out of a timer, which
  ends the app. Found through a flaky test (P0.4); an early refresh is now
  remembered and painted on mount.

### Improvements

- **The flaky pilot tests (P0.4) wait on the thing they test.** A shared
  `tests/pilot/_wait.py` polls a condition against a generous deadline and
  names what never happened. Converted: the BBS helper, footer, tab-key,
  Ctrl+D-cancel and APRS object tests, plus the harvest quiet-exit test,
  which is now bounded by its own ceiling rather than a 2 s budget. Two had
  real ordering bugs the old sleeps hid: Ctrl+D counted SABMs before the
  keypress landed, and the BBS helper was filled in before its `Select`
  posted its initial change.

**Files:** `kissterm/ui/heard_pane.py`, `tests/pilot/_wait.py`,
`tests/unit/test_heard_radar.py`, `tests/pilot/test_app_mounts.py`,
`tests/pilot/test_terminal_ux.py`, `tests/pilot/test_transmit_gate.py`,
`tests/pilot/test_aprs_object_send.py`, `docs/CHANGELOG.md`, `docs/ROADMAP.md`

## [2026-09-23] — Fewer toasts: none for what is already on screen

### Improvements

- **Sixteen confirmation toasts removed.** Requested from a real station:
  "we see what we did already". Saving or forgetting an Address Book entry,
  an APRS contact, or a Settings transport, credential or script changes the
  list in front of the operator; "Now using" a transport is in the status
  bar; "Cancelled connect" is already in the terminal log. The Settings save,
  the transport Test button and the GPS port scan now toast only when there
  is a problem, since their result is already written on the page. Errors,
  transmit notices and events from outside are unchanged.

**Files:** `kissterm/ui/addressbook_pane.py`, `kissterm/ui/app.py`,
`kissterm/ui/aprs_pane.py`, `kissterm/ui/settings_pane.py`,
`tests/pilot/test_settings.py`, `docs/CHANGELOG.md`, `docs/ROADMAP.md`

## [2026-09-23] — No "no reply yet" note for an empty line

### Bug Fixes

- **Pressing Enter on an empty line no longer arms the "acknowledged that
  -- no reply yet" note.** From the CCEMA session of 2026-09-22: with the
  prompt hidden, the operator sent a blank line to prod the node, the node
  rightly said nothing, and the note then blamed the far end while the node
  was waiting on the operator. A line with content still gets the note.

**Files:** `kissterm/ui/app.py`, `tests/pilot/test_transcript_and_color.py`,
`docs/CHANGELOG.md`, `docs/ROADMAP.md`

## [2026-09-23] — The orange border shows where you are typing

### Bug Fixes

- **The accent border follows focus.** Reported from a real station: the
  send box was orange permanently, so after clicking into the scrollback the
  operator typed and wondered why nothing reached the send line. Now
  whatever has focus -- a field, a log, a list or a table -- is drawn in
  `$accent`, and everything else in `$primary`, across every pane and dialog
  and in ASCII-safe mode. One type-level rule in `styles.py` does it; the
  per-widget border colours that pinned one colour are gone.
- Tables (Address Book, contacts, Heard, known nodes, transcripts) gain the
  same outlined border as every other panel, so their focus shows too. The
  known-nodes table is two rows shorter so the Address Book keeps three
  visible entries. The Ctrl+P palette and the F10 menu keep their own chrome.

**Files:** `kissterm/ui/styles.py`, `DESIGN.md`,
`tests/pilot/test_focus_border.py`, `assets/*`, `docs/CHANGELOG.md`,
`docs/ROADMAP.md`

## [2026-09-23] — The Terminal pane no longer hides Textual's logger

### Bug Fixes

- **`TerminalPane.log` is now `write_note`.** The pane's method for local
  notes was defined over Textual's own `log` property, which Textual calls as
  `self.log.warning(...)` from its timer and callback dispatch; on this pane
  that raised `AttributeError` inside Textual. The rename also exposed the
  hazard's other half: `KissTermApp._to_terminal` looks methods up by name,
  and a missed `"log"` would have landed silently on Textual's logger, so
  every one of those calls was renamed with it. The auto-login test in
  `tests/pilot/test_app_mounts.py` now waits on the peer receiving the lines
  instead of a fixed two-second sleep.

**Files:** `kissterm/ui/terminal_pane.py`, `kissterm/ui/app.py`,
`kissterm/ui/AGENTS.md`, `scripts/generate_screenshot.py`,
`tests/pilot/test_terminal_ux.py`, `tests/pilot/test_terminal_find.py`,
`tests/pilot/test_app_mounts.py`, `docs/CHANGELOG.md`, `docs/ROADMAP.md`

## [2026-09-23] — A transport switched in Settings keeps the transmit switch

### Bug Fixes

- **Switching transports live no longer bypasses the transmit gate.** A
  freshly built transport has its own gate, open by default, and the switch
  in Settings (or the Connect dialog's transport picker) never replaced it
  with the operator's. After a switch, anything the station sent went out
  while the status bar read TX off. Both tiers had it. Found by reading the
  code while fixing the item below; no report of it on the air.
- **The monitor, heard list and APRS decoder follow a switched transport.**
  `rebind_transport` moved only the station's own subscription, so after a
  switch those three kept listening to the closed transport and showed
  nothing. `tests/pilot/test_transport_switch.py` covers both.

**Files:** `kissterm/ui/app.py`, `tests/pilot/test_transport_switch.py`,
`docs/CHANGELOG.md`

## [2026-09-23] — Received frames are handled inside the app

### Bug Fixes

- **Timers armed by a received frame now fire.** The launch opens the
  transport before the app runs, so the task every received frame arrives on
  had no active Textual app. A `set_timer` armed anywhere downstream (the
  station, the link, the Terminal pane) died silently in its own task with
  `LookupError: active_app`. This was the root cause of the Terminal pane
  "message queue" never draining on a real station, and the reason it never
  reproduced: `run_test` runs the test itself inside the app's context. The
  app now hands the transport its context (`FrameTransport.callback_context`)
  and the frame fan-out runs in it. `tests/pilot/test_frame_context.py`
  delivers frames from a task started before the app, as the real launch
  does, and fails without the fix.

**Files:** `kissterm/transport/base.py`, `kissterm/ui/app.py`,
`kissterm/ui/terminal_pane.py`, `tests/pilot/test_frame_context.py`,
`tests/pilot/test_terminal_ux.py`, `docs/CHANGELOG.md`, `docs/ROADMAP.md`

## [2026-09-23] — The glossary is written for operators

### Improvements

- **Glossary definitions no longer point into the source tree.** Nine
  entries referred a newcomer to `kissterm/ax25/window.py`, AGENTS.md, the
  roadmap or `Config.modulo`, which mean nothing to someone learning what a
  digipeater is -- visible now that the glossary has its own page on the
  Help tab. Those pointers are replaced by what an operator can act on
  (where the setting is, what the Monitor tab shows), and backticks, which
  plain text shows literally, are gone. `tests/unit/test_glossary.py` now
  rejects both.
- **Path / Via no longer says it is the Address Book's hop field.** It is
  not: a digipeater only repeats frames, while a node hop connects to a node
  and asks it to connect onward. Confusing the two sends an operator to the
  wrong field.

**Files:** `kissterm/glossary.py`, `tests/unit/test_glossary.py`,
`docs/CHANGELOG.md`

## [2026-09-23] — Help is a tab, with guides, node commands, a glossary and About

### New Features

- **F1 Help is a full-page tab, first in the tab row.** Reported from a real
  station: reading "F2 Terminal ... F9 Settings" across the top, the operator
  looked for F1 there and reported it missing -- it was in the bottom bar,
  opening a modal. The row now reads F1 to F9, and because F1 is a tab key
  it leaves the bottom bar, like every other tab key. F1 still answers "what
  can I press here?": it opens on the keys of the tab it was pressed from,
  with a picker for any other tab, and F1 again goes back.
- **Guides** (`kissterm/guides.py`): six short how-tos for an operator new
  to packet -- getting on the air, a first connection, the transmit switch,
  reading a failed connect, APRS messaging, and sharing the channel. Keys in
  them are `{key:action}` placeholders resolved from the command registry,
  so a guide cannot tell anyone to press a key that has moved;
  `tests/unit/test_guides.py` renders every guide and rejects a key typed
  by hand.
- **Node commands**: every shipped node command reference, browsable by node
  type and searchable, without being connected to anything. Read-only on
  purpose -- Ctrl+R on the Terminal tab stays the one route from a reference
  to the send line, and a test asserts the pane has no send or fill path.
  While connected to a node kissterm has identified, it opens on that node
  type.
- **Glossary**, the same terms as the Ctrl+R reference's glossary, with
  room to read them.
- **About**: version, license, project and bug-report links, the config
  file and log directory this station actually uses, and the Python,
  Textual and OS versions -- what a bug report needs, without a shell.
- Guides, Glossary and About are in the F10 Help menu and Ctrl+P.

### Improvements

- The old F1 modal (`HelpScreen`) is gone; its content is the Keys page.

### Fixes

- **Closing the Address Book could leave old scrollback wrapped narrow.**
  The terminal rewrapped its scrollback when the pane resized, one refresh
  later, and remembered the width it last rewrapped at. Opening the column
  resizes only the log, and one refresh was not always enough for the
  column's layout to land, so the pane could record the pre-column width
  as done; closing the column then matched it and skipped the rewrap. The
  log now asks for the rewrap on its own resize. Found because adding the
  Help tab shifted startup timing enough to fail
  `test_existing_scrollback_rewraps_when_the_addressbook_closes`.

**Files:** `kissterm/ui/help_pane.py` (new), `kissterm/guides.py` (new),
`kissterm/ui/app.py`, `kissterm/ui/commands.py`, `kissterm/ui/menu.py`,
`kissterm/ui/styles.py`, `kissterm/ui/terminal_pane.py`,
`tests/unit/test_guides.py` (new),
`tests/unit/test_commands.py`, `tests/pilot/test_menu_and_help.py`,
`tests/pilot/test_app_mounts.py`, `README.md`, `DESIGN.md`, `AGENTS.md`,
`docs/CHANGELOG.md`

## [2026-09-23] — Connecting to the modem: fail fast, and say so

### Fixes

- **Starting kissterm against a KISS-over-TCP TNC that is down no longer sits
  on a blank terminal for about two minutes.** Reported from a real station:
  the TNC host was off the network, gave no RST, and `asyncio.open_connection`
  waited out the kernel's SYN retries before `Errno 110` appeared. Each connect
  attempt is now bounded at 10 seconds, the failure says "no answer within
  10s (host down or unreachable?)" rather than an empty `TimeoutError`
  message, and startup prints which transport it is opening before it waits.
  The same unbounded connect in the other TCP transports is on the roadmap.

### Improvements

- **Startup says what it is waiting for, and counts down.** Before the TUI
  opens, kissterm now prints `Connecting to modem '<name>'...` with a
  once-a-second countdown to the connect timeout (elapsed seconds for a
  transport with no fixed timeout), so a slow or absent TNC no longer looks
  like a frozen program. Requested by the operator with newcomers in mind, it
  also leads with a one-line reminder that fits the connection type -- start
  Direwolf or the UZ7HO soundmodem, plug in and power the TNC, start VARA --
  and repeats it if the open fails, because on a first night the commonest
  "fault" is a modem program that was never started. Telnet and SSH say
  "node" and carry no modem reminder. Redirected output gets the single line
  without the animation.
- **A modem that will not answer no longer ends at a shell prompt.** When the
  open fails on an interactive terminal, kissterm asks `Start kissterm anyway
  and open the TNC settings? [Y/n]`. Yes (or Enter) starts the app on
  Settings > Transports with the error in the banner and a toast, and Save
  there retries the open -- so starting the modem software and pressing Save
  is the whole fix, no restart. Two gaps made that retry impossible before:
  Save reopened only when Active had CHANGED, and `_switch_frame_transport`
  refused outright with no station to rebind; with nothing open, both now
  fall through to `_open_initial_transport`. A script, service or pipe is
  never prompted and keeps the old exit code 3.

**Files:** `kissterm/transport/tcp_kiss.py`, `kissterm/__main__.py`,
`kissterm/ui/app.py`, `kissterm/ui/settings_pane.py`,
`tests/unit/test_tcp_kiss_connect_timeout.py`,
`tests/pilot/test_app_mounts.py`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`

## [2026-09-22] — Enter sends again

### Fixes

- **Enter now commits the send line; it no longer silently does nothing.**
  Reported twice, and both earlier attempts guessed at the key NAME -- adding
  `shift+enter`/`ctrl+enter`/`alt+enter` bindings on the theory that an
  enhanced keyboard protocol was attaching a modifier. They could never have
  worked. A key probe run on the affected station showed Enter producing **no
  key event at all**: `b`, `y` and `e` logged, nothing for Enter, so no
  binding under any name would ever fire. The cause is Textual's enhanced
  (Kitty) keyboard protocol, enabled with report-all-keys, under which Enter
  stops being a plain CR and becomes a bare `CSI 13 u` sequence carrying no
  text while letters still arrive with theirs -- so once that protocol state
  went wrong after the window had sat in a session manager, typing kept
  working and Enter vanished, leaving the mouse as the only way to send.
  Confirmed by A/B in the same terminal tab: with the protocol disabled the
  same probe reported `key='enter' character='\r'` and the submit fired.
  kissterm now disables it in `kissterm/__init__.py`, before anything imports
  Textual, which is the only point where that setting is still read. It costs
  nothing -- the protocol only buys the Ctrl+Shift/Ctrl+Alt/Alt chords the
  keyboard standard already bans -- and `TEXTUAL_DISABLE_KITTY_KEY=0` is the
  way back in for a terminal that handles it correctly.
- **The three speculative Enter bindings are gone.** `alt+enter` violated the
  keyboard standard outright and `shift+enter` shadowed the pane's own
  find-previous binding while the send line had focus. The test that asserted
  each of them transmitted now asserts that plain Enter does.

### New

- **`scripts/keycheck.py`** prints the key name, character and aliases
  Textual actually receives, plus focus state and AppBlur/AppFocus, so "this
  key does nothing" can be measured instead of guessed. It is what settled
  this bug after two wrong theories.

**Files:** kissterm/__init__.py, kissterm/ui/terminal_pane.py,
scripts/keycheck.py, tests/unit/test_keyboard_protocol.py,
tests/pilot/test_terminal_ux.py, AGENTS.md, DESIGN.md, docs/ROADMAP.md.

## [2026-09-22] — The node's prompt appears

### Fixes

- **The last line of node output, usually the prompt, no longer goes
  missing.** Reported five times and fixed five times without sticking. The
  instrumentation below settled it on the operator's own station: the
  Textual timer that releases a held-back partial line was armed over and
  over and its callback ran **zero** times across a whole session, ending
  with `unflushed tail is b'de WS1EC>\r'`. `MessagePump.set_timer` wraps its
  callback in `call_next`, so that flush only happens if the pane's own
  message queue is drained, while `write_incoming` arrives by a plain method
  call from the link callback and works regardless -- which is exactly why
  every line whose continuation arrived in a later frame rendered fine while
  the prompt, the one tail with no next frame, never did. Two fixes, both
  measured against the real bytes: the idle flush is now scheduled with
  `loop.call_later` rather than `Widget.set_timer`, so it depends on the same
  event loop that delivered the bytes instead of the widget's queue; and a CR
  ending a chunk is no longer held back waiting to see whether it was half of
  a CRLF, because the node's prompt is CR-terminated and that hold made the
  most important line on the screen wait on a timer. The CRLF ambiguity is
  resolved from the other side now -- the line goes out immediately and a LF
  opening the next chunk is swallowed -- which cannot produce a blank line or
  lose one. Three tests replay the real 53-byte CCEMA frame and all three
  fail without the fix.
- **A known-broken assertion was corrected rather than worked around.**
  `test_crlf_split_across_frames_does_not_render_a_blank_line` asserted that
  a trailing CR was held back. That assertion *was* the defect, so it now
  asserts the opposite while keeping the guarantee it was written for.

### Known issue opened by this

- **That pane's message queue still does not drain**, which is a separate and
  wider bug now in the roadmap: anything reaching `TerminalPane` by
  `call_next`, `call_after_refresh` or a posted message is affected. The fix
  above routes around it; it does not explain it.

**Files:** kissterm/ui/terminal_pane.py, tests/pilot/test_terminal_ux.py,
docs/ROADMAP.md.

## [2026-09-22] — Instrument the held-back line tail

### Improvements

- **The debug log now says whether a held-back line tail was ever
  released.** An on-air re-test against CCEMA (WS1EC-15) showed the missing
  prompt has a second cause, unrelated to the scroll fix below: the
  transcript contained `de WS1EC>`, the debug log showed all four I-frames
  accepted, and the operator had about thirty empty rows below the last
  visible line -- so the prompt was never written rather than scrolled out
  of sight. `TerminalPane._flush_incoming` holds back everything after the
  last line terminator, so a word split across a frame boundary does not
  render as a break mid-word, and releases it on a newline or a 0.2s idle
  timer. The node's last frame ends in an unterminated prompt, so the
  prompt depended entirely on that timer, and the timer never ran: the
  Terminal pane showed `Emergency Communications Team` as one joined line
  across a 58 second gap that a 0.2s timer would have split, while the
  Monitor showed the two halves arriving in separate frames.
  `MessagePump.set_timer` wraps its callback in `call_next`, so the flush
  needs the pane's own message queue to be drained, while `write_incoming`
  arrives by a plain method call and works regardless. That is the leading
  hypothesis and it does not reproduce under `run_test`, so this ships as
  measurement rather than a sixth guess: `_watch_flush` schedules the same
  delay directly on the event loop and logs which mechanism fired. It
  observes and never flushes, so behaviour is unchanged. Diagnostic only --
  it comes out with the fix.

**Files:** kissterm/ui/terminal_pane.py, docs/ROADMAP.md.

## [2026-09-22] — Keep the last line of node output in view

### Fixes

- **The prompt no longer hides below the fold.** Reported four times and
  fixed four times without sticking (0.1.179-0.1.182), because every attempt
  changed what happens when a line is *written* -- and that half was already
  working. `RichLog.auto_scroll` acts on `write` and nowhere else, so a log
  sitting exactly at the bottom stopped being at the bottom the moment
  something took rows away from it, with no new write left to bring it back.
  Measured at 80x24 before the fix: 40 lines of node output ending in a
  prompt left `scroll_y=27` against `max_scroll_y=34` as soon as the
  suggestion strip appeared -- the last seven lines, prompt included, gone
  from view. The find bar reproduces it on its own, and so does closing the
  Address Book slide-out, which is why the fix is general rather than written
  against the strip. `WrapLog` now anchors itself (Textual's own
  `Widget.anchor()`), which the compositor re-applies on every arrange: if
  the log was at the bottom before the layout changed, it is at the bottom
  after. Scrolling up releases the anchor, so an operator reading back keeps
  their place; scrolling to the bottom resumes following it. All three
  scrollbacks -- terminal, monitor, APRS -- get this, since all three are
  `WrapLog`. This is what the operator saw as the node going quiet when it
  was in fact waiting on them.

- **Two find tests measured their baseline before the find bar opened.**
  They exist to prove that *counting matches* does not navigate, but they
  captured the scroll position before pressing Ctrl+F, so they also measured
  the bar's own three rows appearing -- which the anchor now correctly
  follows. The baseline moved to after the bar is open; what they assert is
  unchanged.

**Files:** `kissterm/ui/wraplog.py`, `tests/pilot/test_terminal_ux.py`,
`tests/pilot/test_terminal_find.py`, `docs/ROADMAP.md`, `assets/*`.

## [2026-09-22] — Fix three stale test failures at their cause

### Fixes

- **A test helper read padded widgets one character short.** `_plain()` --
  copied into six pilot test files -- rendered a widget at `Widget.size`,
  which is the CONTENT box, while `render_lines` paints the padded box. On
  `#suggestion-strip` (`padding: 0 1`) that cropped the left pad and the
  last real character, so a correctly wrapped command summary read back as
  truncated mid-word ("... or nod") and failed the assertion. The strip on
  screen was right the whole time. Every copy now renders at `outer_size`.
- **Two suggestion-strip assertions had outgone the code they guard.** The
  strip became one candidate per line as `NAME - summary` (0.1.17x) while
  the test still expected the old single-row `NAME: summary`; and the
  arrow-navigation test named `LB` as the third candidate under "L", which
  stopped being true when the shipped BPQMail reference grew from three L*
  commands to thirteen. The navigation test now reads the expected command
  off the candidate list -- what it is really about is that Tab fills
  whatever the arrows selected, not which command sits third in shipped
  data.
- **`aprs_sms_gateway`/`aprs_email_gateway` default to `SMSGTE`/`EMAIL-2`,
  and now say so.** The defaults changed from blank in 0.1.182 but the
  field comment still argued at length for leaving them blank, and the test
  named "no default gateway is configured" was using a default `Config`, so
  it was really asserting the old default and failing against the new one.
  The comment now records why naming a gateway became defensible (both are
  cited in `kissterm/aprs_services/`, and it is only a prefill into an empty
  field that the operator still confirms), the test configures the blank
  case it names, and a second test covers the shipped default prefilling.
  **Files:** `kissterm/config.py`, `tests/pilot/test_terminal_ux.py`,
  `tests/pilot/test_aprs_contacts_pane.py`, `tests/pilot/test_settings.py`,
  `tests/pilot/test_session_transport.py`, `tests/pilot/test_beacon_wiring.py`,
  `tests/pilot/test_aprs_beacon_wiring.py`, `tests/pilot/test_transmit_gate.py`,
  `tests/pilot/test_app_mounts.py`, `docs/CHANGELOG.md`.

## [2026-09-22] — One keyboard standard: F1 Help, F10 Menu, nine Ctrl keys

### Improvements

- **The keyboard follows IBM CUA, as Midnight Commander uses it.** Keys had
  been chosen one at a time, each against the collisions known that day, and
  the result was a Footer advertising `^O` for a key bound to Ctrl+Shift+O --
  which an ordinary terminal delivers as Ctrl+O, a different command. Every
  Ctrl+Shift, Ctrl+Alt, Alt and Ctrl+digit binding is gone, because without
  an enhanced keyboard protocol (which tmux and ssh in the path usually deny)
  Ctrl+Shift+X and Ctrl+X are the same byte. What is left: **F1 Help, F10
  Menu**, tabs on F2-F9, and nine Ctrl keys -- Q N D T F L G R P.
- **F10 opens a menu with every command in it**, grouped Session / APRS /
  View / Help, each with its key beside it and its mnemonic letter
  underlined; Left and Right move between headings. A command that cannot run
  now (Disconnect with nothing connected) is listed dimmed with the reason.
  Because nothing needs its own chord to be reachable, Send beacon, Send
  position, Object, Bulletin, Gateway form, Watch APRS-IS, SSID filter, File
  transfer, NET/ROM nodes, My callsign and Transcripts gave up their keys.
- **F1 is context help**: what this tab is for, every key that works on it,
  the keys a focused list adds, and a note that GNOME Terminal steals F1 and
  F10 until its menu accelerator is turned off.
- **The bottom bar shows only what works here, right now**, and pins `F10
  Menu` to the right so nothing dropped for width is unreachable. A key that
  does not apply on this tab is absent from the bar and falls through to the
  focused widget instead of raising a toast; seven "Open APRS to ..." toasts
  are gone with it.
- **Tabs moved to their long-term keys**: `F2 Terminal  F3 APRS  F4 Heard
  F5 Monitor  F9 Settings`. Help, Menu and Settings are now on the keys they
  keep when Mail, Bulletins and Files arrive (ROADMAP P2). `Ctrl+1`..`Ctrl+5`
  are gone -- xterm sends ESC for Ctrl+3.
- **Ctrl+D is Disconnect again, properly.** It is bound with priority and
  only while there is a session to end, so it disconnects from the send line
  where Ctrl+Shift+D used to be needed, and is still delete-right otherwise.
  In lists, Edit moved from F2 (now the Terminal tab) to `E`.
- **Shorter labels where the noun was already on screen**: "Edit selected"
  and "Forget selected" are Edit and Forget above the table they act on,
  "Use claimed callsign" is "Use node", "Reload from file" is Reload. In the
  menu and the bar, a command is a verb: TX, Connect, Book, Commands, Find.
- **One table generates all of it.** `kissterm/ui/commands.py`'s `COMMANDS`
  produces the bindings, the Footer, the menu, the help screen and the Ctrl+P
  palette -- which now finds commands with no key at all.
  `tests/unit/test_key_standard.py` fails the build on a key outside the
  allowlist, a plain letter bound off a list, a `key_display` naming a
  different chord, or more than nine global Ctrl keys.
  **Files:** `kissterm/ui/commands.py`, `kissterm/ui/menu.py` (new),
  `kissterm/ui/app.py`, `kissterm/ui/aprs_pane.py`,
  `kissterm/ui/addressbook_pane.py`, `kissterm/ui/dialogs.py`,
  `kissterm/ui/settings_schema.py`, `DESIGN.md`, `README.md`, `SETUP.md`,
  `AGENTS.md`, `kissterm/ui/AGENTS.md`, `docs/ROADMAP.md`,
  `tests/unit/test_key_standard.py` (new), `tests/unit/test_commands.py`,
  `tests/pilot/test_menu_and_help.py` (new), `tests/pilot/test_app_mounts.py`,
  `tests/pilot/test_transmit_gate.py`, `tests/pilot/test_beacon_key_dispatch.py`,
  `tests/pilot/test_aprs_messaging.py`, `tests/pilot/test_aprs_contacts_pane.py`,
  `tests/pilot/test_addressbook_pane.py`.

## [2026-09-22] — Roadmap reorganized around stabilization

### Documentation

- **ROADMAP.md now leads with P0 (stabilize) and a defined 1.0 finish
  line.** From a review of the Codex session history against git: live bug
  reports were tracked only in chat, so "what's next" kept resolving to new
  features. P0 lists every reported bug with its status, adopts IBM CUA (as
  used by Turbo Vision / Midnight Commander) as the keyboard standard with a
  terminal-safe key allowlist, and defines a layered, sourced command
  catalog. Shipped `[x]` items were removed; `ROADMAP_DEPENDENCIES.md` was
  stale and is folded into per-item "Needs:" notes. AGENTS.md points at the
  new working rules.
- **Tab layout decided and messaging client planned (P2).** F1 Help, F10
  Menu, F9 Settings now. Mail, Bulletins and Files will take F2-F4, with
  Terminal, APRS, Heard and Info after them. New P2 covers a folder-tree
  message store, Winlink (B2F over CMS Telnet, packet RMS and VARA, reusing
  the existing link seam), and BBS mail send/receive. The old P10 tab items
  moved there.
- **Forms and BBS retrieval policy planned.** P2 gains a Forms subsection:
  every bpq-apps `.frm` form, vden PKTNET parity, and Winlink standard
  forms, with golden-output tests against bpq-apps' forms.py. BBS messages
  stay on the node by default; kill is explicit, and re-downloads are
  prevented per account. P11's form items moved into P2.
- **Focus highlight bug added to P0.1.** The accent border is fixed on the
  terminal entry field instead of following focus.
  **Files:** `docs/ROADMAP.md`, `docs/ROADMAP_DEPENDENCIES.md` (removed),
  `AGENTS.md`, `docs/CHANGELOG.md`.

## [2026-09-22] — Add BBS mail helpers

### Fixes

- **Terminal pager prompts remain visible.** After each terminal-log write,
  the scrollback now refreshes its virtual layout before following the new
  bottom, without adding rows above the compose line. This prevents an
  unterminated `<A>bort, <CR> Continue...` prompt from looking like a silent
  node while preserving the terminal's full scrollback height.
  **Files:** `kissterm/ui/terminal_pane.py`,
  `tests/pilot/test_terminal_ux.py`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`.

- **Transcript recording is compact in the status bar.** The full transcript
  path no longer takes a terminal row; `LOGGING` marks the active session's
  recording state. Ctrl+O remains the place to browse transcript files.
  **Files:** `kissterm/ui/app.py`, `kissterm/ui/terminal_pane.py`,
  `kissterm/ui/styles.py`, `tests/pilot/test_transcript_and_color.py`,
  `docs/CHANGELOG.md`.

- **The radio reminder now clears before a connection begins.** A fast
  successful dial from an Address Book entry could start behind the just-
  confirmed "Before connecting" modal, leaving that stale dialog visibly on
  top of the live terminal. The connect flow now lets Textual complete its
  queued screen replacement first; direct modal-button interaction is covered
  for both regular and Address Book connects.
  **Files:** `kissterm/ui/app.py`, `tests/pilot/test_connect_scripts.py`,
  `docs/CHANGELOG.md`.

- **Multi-line BBS replies no longer gain blank rows.** The terminal receive
  buffer waits to see whether a trailing CR is followed by LF, then writes
  each normalized physical line without its terminator so `RichLog` does not
  add a second record break; genuine blank BBS lines and CR-only TNC output
  remain intact. This was confirmed by a live BPQ BBS mail listing.
  **Files:** `kissterm/ui/terminal_pane.py`,
  `tests/pilot/test_terminal_ux.py`, `docs/ROADMAP.md`,
  `docs/CHANGELOG.md`.

### Improvements

- **Starting a connection clears the Terminal view.** A real dial now closes
  the shared Address Book / NET/ROM slide-out before showing connection
  status, restoring the full terminal width for the live session. Cancelling
  a Connect or radio-reminder dialog leaves the operator's layout unchanged.
  **Files:** `kissterm/ui/app.py`, `kissterm/ui/terminal_pane.py`,
  `tests/pilot/test_terminal_ux.py`, `docs/CHANGELOG.md`.

### New Features

- **BBS mail commands now have a safe, visible starting point.** `Ctrl+R` >
  BBS mail helpers provides BPQMail/LinBPQ templates for listing mail,
  reading a numbered message, and starting personal mail to a callsign.
  Parameters reject control characters, selection only fills the normal
  compose box, and the existing Send/Enter action remains the sole transmit
  path. No BBS reply parser is introduced; further documented dialects are
  data additions in `kissterm/bbs.py`.
  **Files:** `kissterm/bbs.py`, `kissterm/ui/dialogs.py`,
  `kissterm/ui/styles.py`, `tests/unit/test_bbs.py`, `README.md`,
  `docs/ROADMAP.md`, `docs/CHANGELOG.md`.

- **Command suggestions are stacked and explained.** The terminal input now
  keeps each candidate and its short meaning on one row (`LM - List Mine`,
  `LB - List Bulletins`) rather than risking descriptions beyond a narrow
  terminal's right edge. Tab still only fills the input.
  **Files:** `kissterm/bbs.py`, `kissterm/ui/terminal_pane.py`,
  `tests/unit/test_bbs.py`, `tests/pilot/test_terminal_ux.py`, `README.md`,
  `docs/CHANGELOG.md`.

- **Up/Down now selects a command suggestion.** The arrow keys move the
  stacked highlight while preserving the typed prefix; Tab still performs the
  separate, non-transmitting fill step. Locally learned BBS command names
  with no description inherit the shipped helper's explanation, so `LM` does
  not mask `List Mine`.
  **Files:** `kissterm/ui/terminal_pane.py`,
  `tests/pilot/test_terminal_ux.py`, `README.md`, `docs/CHANGELOG.md`.

- **The BBS command list now includes `B` / `BYE`.** It is discoverable by
  either spelling and fills the short `B` form, consistent with BPQ BBS
  practice.
  **Files:** `kissterm/bbs.py`, `tests/unit/test_bbs.py`, `README.md`,
  `docs/CHANGELOG.md`.

## [2026-09-22] — Make NET/ROM claims collapsible

### Improvements

- **NET/ROM claims no longer have to crowd out saved stations.** `Ctrl+PageDown`
  collapses or restores the passive claims section independently from the
  Terminal Address Book; from a closed slide-out it opens the shared column
  with claims shown. `Ctrl+G` continues to show or hide the Address Book
  itself. Hiding claims returns focus to the saved-station table without a
  redundant notification, and the context-aware shortcut bar exposes the
  action on Terminal only.
  **Files:** `kissterm/ui/addressbook_pane.py`, `kissterm/ui/terminal_pane.py`,
  `kissterm/ui/app.py`, `kissterm/ui/commands.py`,
  `tests/pilot/test_app_mounts.py`, `README.md`, `DESIGN.md`,
  `docs/CHANGELOG.md`.
