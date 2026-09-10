# CHANGELOG.md — kissterm

Format: keep newest at top. One entry per meaningful change. Reference files
touched and any breaking notes.

## [2026-09-10] — APRS telemetry-definition messages no longer clutter the messages view

### Improvements
- **A telemetry-equipped station labelling its own channels (`PARM.`/
  `UNIT.`/`EQNS.`/`BITS.`, addressed to itself) no longer shows up as a chat
  line in the APRS "All" view.** Found from a live screenshot that looked
  like garbage: lines like `< W1UWS-1: PARM.Vin,Rx1h,Eff1h,...` are real,
  correctly-decoded APRS traffic -- the APRS spec's telemetry chapter defines
  these as messages a station sends to itself to label its own `T#...`
  reports -- not a wrong decode of a non-APRS frame from a dual-mode node.
  kissterm does not decode telemetry channel labels into anything useful yet,
  so `aprs.Message.is_telemetry_definition` flags the four keywords the same
  way `is_ack`/`is_rej` already flag ack/reject, and `_on_aprs_frame` skips
  recording and notifying on it exactly like it already does for those.
  **Files:** `kissterm/aprs/types.py`, `kissterm/aprs/messages.py`,
  `kissterm/ui/app.py`, `kissterm/aprs_notify.py`.

## [2026-09-10] — bpq32.toml cross-checked against an independent 15-node crawl, RMS added

### Improvements
- **The `bpq32.toml` core command set is no longer evidenced by one node.**
  Cross-checked against the sibling `bpq-apps` repo's own node-map crawl
  (`utilities/nodemap.json`, 15 real captured "?" replies): the same 8 core
  commands (`CONNECT`/`BYE`/`INFO`/`NODES`/`PORTS`/`ROUTES`/`USERS`/`MHEARD`)
  independently confirmed, in long form, by 12 of the 15 nodes -- a
  single-node harvest is now a 13-node one. Full breakdown in the file's own
  top-of-file provenance comment.
- **Added `RMS`** at `confidence = "documented"`: 9 of the 15 crawled nodes
  (60%) list it as a configured application, common enough across
  independently-run nodes to be worth naming, unlike the clearly node-specific
  local additions (`CALENDAR`, `GYX`, `EOC`, ...) that stay out of the shipped
  file on purpose.
- **Flagged, not shipped: a candidate PBBS/AEA-TNC-mailbox family.** 3 of the
  15 crawled nodes are tagged `"type": "BPQ"` by the crawl's own heuristic but
  returned command sets (`B(ye)`, `J(heard)`, `[AEA PK-232M]`) that do not
  match this family's detection at all. Worth a real family of its own
  eventually; 2-3 samples from one crawl is not enough to write a confident
  `detect_prompt` yet. See `docs/ROADMAP.md` P8.
- **Documented the harvest-to-shipped-data promotion workflow.** Added to
  `kissterm/nodes/__init__.py`'s module docstring: how to compare a cached
  harvest against a family's TOML file by hand, when a found command earns
  `confidence = "verified"`/`"documented"`, and when it is a local
  `APPLICATION` addition that should stay out of the shipped file.
  **Files:** `kissterm/nodes/data/bpq32.toml`, `kissterm/nodes/__init__.py`,
  `docs/ROADMAP.md`.

## [2026-09-10] — A hop resets node detection only once it is CONFIRMED, and a harvest is filed under the node that answered

### Improvements
- **A hop that fails no longer blanks out the node you are still connected
  to.** The hop-detection reset shipped earlier today (entry below) fired
  the instant `C <node>` went out, with nothing yet knowing whether the hop
  worked. Found in live testing against a real BPQ32 node: when the hop
  answers BUSY, or nothing answers at all, the operator is still talking to
  the SAME node -- and a correctly identified node had just been turned into
  "unknown node", taking Ctrl+R's command list and the send line's
  autocomplete with it. The reset now waits for that node's own CONNECTED
  reply. `_hop_to`'s existing watcher (CONNECTED vs BUSY/FAILED/
  DISCONNECTED/TIMEOUT vs silence past `HOP_TIMEOUT`) was extracted into
  `_HopConfirmation` plus `_await_hop_confirmation`, so a hand-typed hop and
  a scripted hop chain share one definition of "the hop worked" rather than
  two copies free to drift apart, and `_commit_hop` is now the single place
  a success is applied. A refusal or a timeout changes nothing at all. A
  second hop typed before the first resolves cancels the first watch, so two
  watchers can never race to commit different nodes off the same bytes.
- **"Learn from node" is now cached under the node that actually answered.**
  Previously keyed on `link.peer` -- the AX.25 link's remote station, which
  stays the FIRST node's callsign for the life of a hop chain, because the
  hop happens at the far node's application layer and is invisible to the
  link layer. Harvesting after hopping therefore wrote the second node's
  commands into the first node's cache entry, silently corrupting a real
  node's reference with another node's syntax (noted as known-and-deferred
  in the entry below; fixed here). `_TerminalSession.current_node` is the new
  "logical peer": it starts as the link's own peer and moves only on a
  confirmed hop. Harvesting keys on it, the "Learned N command(s) from X"
  note and the Ctrl+R harvest prompt name it, and a hop *back* to a node
  harvested before re-applies that cache immediately -- the same
  never-pay-twice rule `_bind_link` already follows on a reconnect.
- **The status bar names the node you are talking to.** After a confirmed
  hop it reads `W1LH-6 via WS1EC-7 connected BPQ32` rather than showing the
  first node's callsign next to a family badge describing a different one.
- **A port-qualified hop no longer targets the port number.** `bpq32.toml`
  documents two forms, `C <call>` and `C <port> <call>`; reading the target
  as the first word after `C` took `C 2 JNOSNODE` as a hop to a node
  literally named `2`, which would then confirm against the wrong node's
  traffic and cache a real harvest under a callsign that was never reached.
  The target is now the LAST word either way.
  **Files:** `kissterm/ui/app.py`, `tests/pilot/test_terminal_ux.py`,
  `tests/pilot/test_connect_scripts.py`.

## [2026-09-10] — Node detection now survives hopping onward through a node

### Improvements
- **Connecting to a BPQ32 node, then typing `C <other-node>` to hop onward,
  no longer leaves Ctrl+R stuck showing the FIRST node's commands.**
  `_sniff_node` deliberately locks onto the first family it identifies and
  never looks again (AGENTS.md: "a wrong family shown confidently is worse
  than 'unknown node'" -- scanning forever would let ordinary chat text
  cause a false match) -- but that lock meant a hop was invisible to it:
  kissterm's own AX.25 link never changes on a hop, since the far node
  relays text onward at ITS application layer, so nothing else ever told
  the session it might now be a different kind of system. `log_sent` (which
  already sees both a hand-typed line and `_hop_to`'s own "C <node>", so
  this covers a scripted hop chain too) now resets node detection whenever
  the operator sends a recognized connect-onward command (`C`/`CONNECT`,
  matched as the whole first word so real commands like `CQ`/`CHAT` are
  never mistaken for one) -- the next banner gets a clean, un-mixed read.
  **Not changed**: harvesting ("Learn from node") still caches results
  under the AX.25 link's peer callsign, which stays the FIRST node's the
  whole time a hop chain is active -- harvesting from a hopped-to node
  would still mislabel the result. Known, deliberately out of scope here.
  **Files:** `kissterm/ui/app.py`, `tests/pilot/test_terminal_ux.py`.

## [2026-09-10] — Visual feedback from a live JNOS-crawl test session

### Improvements
- **A real repeated-"connected" bug, caught live.** The terminal-noise fix
  earlier today (`_on_link_state` skipping the TIMER_RECOVERY note and its
  own resolution) had a bug: `last_noted_state` was only ever set inside the
  branch that *writes* a note, so it was never actually set to
  TIMER_RECOVERY -- the one write that branch skips -- and the "did we just
  recover" check could never see it. Every return to CONNECTED after a real
  flap got announced anyway. Caught within hours by a live BPQ->JNOS crawl:
  CCEMA's link recovered three times over 62 real seconds (confirmed in
  `kissterm.log` -- legitimate T1/REJ recovery, `rc` climbing 0..9 of a
  10-retry budget each time, never a hang) and the transcript shows exactly
  three duplicate `* connected` lines for it. Renamed the field to
  `last_state` and set it on every call, including a suppressed one --
  `_on_link_state`'s docstring has the full account. The pilot test meant to
  guard this only checked "timer-recovery" was absent, not that "connected"
  stopped repeating; it now asserts both.
- **Node family detection no longer writes an inline `*** Node looks like
  X` terminal note.** Same duplication reasoning as the TIMER_RECOVERY fix:
  the status bar already carries the peer callsign and link state, so the
  detected family's short id (`BPQ32`, `JNOS`, `TNC2`) now appends there
  instead (`_refresh_status`) -- one place for the fact, not two, and it
  updates the moment `_sniff_node` identifies the node rather than only
  once a second later.
- **The Ctrl+R command reference dialog no longer squishes the command
  table to one row.** At a real 90x24 terminal, the fixed note/mode-row/
  search chrome above `#ref-table` already claimed about 11 of the box's
  15 content rows at the old 80% height, and the Learn-from-node/Close
  button row was being laid out several rows past the box's own bottom
  border with no way to reach it. `#ref-box` is now 92% height with
  `overflow-y: auto` (the box scrolls rather than clipping controls
  outside its border), and `#ref-table` carries a `min-height: 6` so it
  never collapses to a single row.
- **The Address Book pane no longer carries a note above the table or a
  key-hint line below the buttons.** Both were a second, static copy of
  facts already available elsewhere: `_AddressBookTable.BINDINGS` are
  already registered `show=False` specifically so Textual's own Footer is
  the context-aware shortcut bar for them (AGENTS.md's rule for exactly
  this). Removing both also lines this pane's button row up with the
  Terminal pane's input-and-Send row on the other side of the same split.
  **Files:** `kissterm/ui/app.py`, `kissterm/ui/styles.py`,
  `kissterm/ui/addressbook_pane.py`, `tests/pilot/test_terminal_ux.py`.

## [2026-09-10] — JNOS added to the command reference (P8 "more families")

### New Features
- **`kissterm/nodes/data/jnos.toml`**: a new node family for JNOS, the
  Phil Karn NOS lineage still widely run as a packet BBS/IP gateway.
  Deliberately **banner-only detection** (`detect_banner = ["JNOS"]`, no
  `detect_prompt`) -- JNOS's stock command prompt is commonly left at
  exactly the string `cmd:`, identical to `tnc2.toml`'s
  `^cmd:\s*$` pattern, and a wrong family shown confidently is worse than
  "unknown node" (AGENTS.md P8). Eleven commands
  (`?`/`bye`/`connect`/`telnet`/`ftp`/`finger`/`who`/`mheard`/`ax25
  status`/`route`/`ping`), all `confidence = "recalled"` -- written from
  long-standing JNOS documentation/convention, not checked against a live
  session yet. Next candidate for the "verify shipped references against
  live nodes" roadmap item, reachable via a BPQ->JNOS hop.
  **Files:** `kissterm/nodes/data/jnos.toml` (new),
  `tests/unit/test_nodes.py`, `docs/ROADMAP.md`.

## [2026-09-10] — 10 `bpq32.toml` commands verified against a real CCEMA session

### Improvements
- **10 `bpq32.toml` commands promoted to `confidence = "verified"`.**
  A live session against WS1EC-15/CCEMA's real `?` reply (`CCEMA:WS1EC-15}
  BBS CHAT AI ANTENNA BANDS CALENDAR ...`) confirms `?`/`B`/`C`/`I`/`N`/`P`/
  `R`/`U`/`MH`/`BBS`/`CHAT` for real, closing part of the P8 "verify shipped
  references against live nodes" roadmap item. `STATS`/`PING`/`CQ`/`T` stay
  `"recalled"` -- absent from this one node's menu, which proves nothing
  about other nodes -- and the node's own `APPLICATION` additions
  (CALENDAR, FORMS, DX, and the rest) are deliberately left out of this
  shipped file, since they are local to WS1EC-15 and belong in the
  per-callsign harvest cache instead.
  **Files:** `kissterm/nodes/data/bpq32.toml`, `docs/ROADMAP.md`.

## [2026-09-10] — Harvest timeout and terminal noise, found from a live CCEMA session

### Improvements
- **The harvest capture window no longer cuts off a slow reply.** A real
  session against WS1EC-15/CCEMA hit the fixed `HARVEST_WINDOW_SECONDS =
  5.0` window: CCEMA's `?` reply needed three T1 retry/REJ recovery cycles
  before any of it arrived, landing ~18.8 s after the request went out --
  legitimate AX.25 behaviour on a lossy link (`AGENTS.md`:
  "`TIMER_RECOVERY` is not an error state"), not a hang, but the old window
  had already given up 12 s before the reply started. Replaced with a poll
  loop: a 90 s hard ceiling (`HARVEST_MAX_WAIT_SECONDS`, matching
  `describe_airtime(8192)`'s worst case plus headroom this constant's
  predecessor did not budget for AX.25 recovery time at all) plus a 3 s
  quiet-exit (`HARVEST_QUIET_SECONDS`) once the buffer has started growing
  and then stopped, so a short reply still returns promptly. The outgoing
  `?` is now recorded via `log_sent` like every other automated send, and
  `HarvestConfirmScreen`'s copy now says a marginal link can run past the
  airtime estimate and that capture stops on quiet, not on a fixed timer.
- **Timer-recovery flapping no longer spams the terminal pane.** The same
  CCEMA session's retry cycles produced repeated inline `*** TIMER_RECOVERY`
  / `*** CONNECTED` notes in the terminal -- duplicating what the status
  bar already shows live, every second, per DESIGN.md's "say what is true,
  in the place the operator is already looking." `_on_link_state` now
  skips the inline note for a `TIMER_RECOVERY` excursion and for the
  `CONNECTED` transition that resolves one; genuine state changes
  (DISCONNECTING, FAILED, DISCONNECTED, and the separate dedicated
  "Connected to X" note) are unaffected.
  **Files:** `kissterm/ui/app.py`, `kissterm/ui/dialogs.py`,
  `tests/pilot/test_terminal_ux.py`.

## [2026-09-10] — Opt-in command harvesting from a live node

### New Features
- **The command reference (Ctrl+R) can now ask a connected node's own `?`
  for its command list, once, with the operator's confirmation** — the P8
  roadmap item, and the last of the three "Terminal assistance" gaps this
  closes today (glossary and per-node notes are the other two, each its own
  entry below). `CommandReference.learned` and `confidence = "learned"`
  already existed with nothing populating them; a "Learn from node" button
  (shown only on an actually-connected tab) now does, guarded by
  `HarvestConfirmScreen`, which shows the airtime cost as a RANGE
  (`nodes.reference.describe_airtime` at 512 B and 8 KB) rather than a false-
  precision number, since kissterm cannot know a given node's reply size in
  advance. Sends through the ordinary tx-gated `link.send` — no second send
  path — captures the reply for a bounded window
  (`KissTermApp.HARVEST_WINDOW_SECONDS`/`HARVEST_CAPTURE_LIMIT`), and
  `nodes.reference.parse_harvested` turns it into candidate command names
  (deliberately excluding single-letter tokens, which the shipped
  references already cover). Results are cached forever per callsign in the
  new `kissterm/harvested.py` (same persistence shape as `addressbook.py`),
  and `_bind_link` re-applies a peer's cache on every later connect with no
  prompt and no repeated airtime spend.
  **Files:** `kissterm/harvested.py` (new), `kissterm/nodes/reference.py`,
  `kissterm/nodes/__init__.py`, `kissterm/ui/app.py`, `kissterm/ui/dialogs.py`,
  `tests/unit/test_harvested.py` (new), `tests/unit/test_nodes.py`,
  `tests/pilot/test_terminal_ux.py`, `docs/ROADMAP.md`.

## [2026-09-10] — A packet-terminology glossary, in the command reference pane

### New Features
- **Ctrl+R (the command reference) now has a Commands/Glossary toggle**,
  closing the P8 roadmap item asking for a glossary "searchable in the same
  pane as commands" rather than a second binding or modal. New
  `kissterm/glossary.py` ships ~28 hardcoded terms (TNC, KISS, AX.25, paclen,
  T1/T2/T3, digipeater, and the like) aimed at an operator who knows radio
  but not packet — the audience `README.md` already writes for. Hardcoded
  Python, not a TOML data file, on purpose: unlike `kissterm/nodes/`'s
  per-family references this is one fixed list with nothing to hand-edit
  per node, the same reasoning `ui/themes.py`'s `THEME_CATALOG` already uses.
  **Files:** `kissterm/glossary.py` (new), `kissterm/ui/dialogs.py`,
  `kissterm/ui/styles.py`, `tests/unit/test_glossary.py` (new),
  `tests/pilot/test_terminal_ux.py`, `docs/ROADMAP.md`.

## [2026-09-10] — Per-node notes in the Address Book

### New Features
- **An Address Book entry can now carry a free-text note, shown on connect**
  — the P8 roadmap item ("BBS is on -2, chat needs a callsign"). Turned out
  to be mostly already built: `addressbook.Entry.note` existed in the
  dataclass and its JSON load/save, but nothing in
  `AddressBookEntryScreen` ever showed a field for it and nothing ever
  displayed it — a dead field since before this session. Wired it through
  `AddressBookEdit`/`AddressBook.upsert`/the editor's own `Input`, and into
  `RadioReminderScreen`, which now shows on connect whenever an entry has a
  note even with no frequency or connection type set (previously the
  reminder never fired on `note` alone).
  **Files:** `kissterm/addressbook.py`, `kissterm/ui/dialogs.py`,
  `kissterm/ui/addressbook_pane.py`, `kissterm/ui/app.py`,
  `tests/pilot/test_addressbook_pane.py`, `tests/pilot/test_connect_scripts.py`,
  `docs/ROADMAP.md`.

## [2026-09-10] — Inline command completion on the send line

### New Features
- **The Terminal pane's send line now offers inline completion**, closing
  the P2 roadmap item of the same name. `CommandReference.complete()` and
  `TerminalPane.suggest()` already existed and neither could transmit; what
  was missing was UI to reach them without opening the full-screen Ctrl+R
  reference. `#suggestion-strip` shows up to `complete()`'s matches for
  whatever is currently typed (the top one bold, the rest dim), and
  `_SendInput`'s new `tab` binding fills in the top match through the same
  `suggest()` path Ctrl+R already used — never a second way to reach the
  air. Deliberately a row of candidates rather than Textual's built-in
  single-candidate ghost-text suggester: a node's `C`/`CQ`/`CHAT` sharing a
  prefix is routine, and ghost text can only ever offer one. Tab with
  nothing suggested falls through to ordinary focus-cycling
  (`Screen.focus_next()`), so an operator who never triggers a suggestion
  never notices Tab behaves any differently than before. The strip is
  recomputed on every keystroke and on every session-tab switch, since
  `self.app.reference` is session-scoped and a stale strip would offer a
  different node's commands.
  **Files:** `kissterm/ui/terminal_pane.py`, `kissterm/ui/styles.py`,
  `tests/pilot/test_terminal_ux.py`, `tests/pilot/test_terminal_sessions.py`,
  `DESIGN.md`, `docs/ROADMAP.md`.

## [2026-09-10] — ARISS as a digipeater path preset

### New Features
- **The APRS beacon path picker (Settings) now offers ARISS as a preset**,
  alongside WIDE1-1,WIDE2-1 / WIDE1-1 / WIDE2-2 / Direct — the P4 roadmap
  item on the ISS and other APRS satellites, scoped to just the path
  preset (pass prediction and anything larger stayed out, per that item's
  own note). ISS digipeats anything carrying `ARISS` in its path; that is
  a route you send *through*, not a station you send commands *to*, which
  is why this lives in the existing `aprs.path` `custom_choice` picker
  (`kissterm/ui/settings_schema.py`) rather than as a new entry in
  `kissterm/aprs_services/`'s gateway-service directory — the distinction
  that item's own text called out for not shipping it there instead.
  `parse_path` already treats a bare token like `ARISS` as an ordinary
  single-element digipeater list, same as `WIDE1-1`, so no changes were
  needed in `kissterm/aprs_beacon.py` or `kissterm/ax25/address.py` — this
  is a one-entry addition to an already-generic preset picker.

**Files:** `kissterm/ui/settings_schema.py`, `docs/ROADMAP.md`,
`tests/pilot/test_settings.py`.

## [2026-09-10] — Tabbed packet terminal: multiple simultaneous connections

### New Features
- **The Terminal pane can now hold several simultaneous connections at
  once, one tab each** — the P2 roadmap item ("we'll be doing that with the
  packet terminal soon"), built on the APRS pane's already-shipped
  conversation-strip pattern (`_ConvoTabs` / DESIGN.md's "A second tab strip
  inside a pane") rather than re-deriving it. `AX25Station.links` was always
  a dict keyed by peer; what was missing was the UI, where `KissTermApp.link`/
  `.reference`/`.transcript` were single slots that a second connection
  silently clobbered. They are now read-only properties over whichever tab
  is on screen, backed by a `_TerminalSession` per session key
  (`kissterm/ui/app.py`); every link callback (`_on_link_data`,
  `_on_link_state`, the reply-watch timer, the hop-chain and auto-login
  loops) threads its own session's key through explicitly instead, so a
  background tab's own conversation, node reference and transcript stay
  correct no matter which tab the operator is actually looking at.
  `terminal_pane.py`'s new `#terminal-session-tabs` strip is one shared
  `#session-log`, repainted from a per-session replay buffer on
  `Tabs.TabActivated` — never a live widget per tab, same reasoning APRS's
  strip already established. No strip at all below two sessions, so a
  single connection looks exactly like it always has. An operator-initiated
  connect opens and activates its own tab; an incoming call accepted while
  another session is on screen opens a tab and marks it unread without
  moving the view. `Delete` on the focused tab disconnects a live session
  first and only removes the tab on a second `Delete`, once it reads
  DISCONNECTED — closing a live link is not the same action as tidying away
  a finished one. `MAX_TERMINAL_TABS` (8) caps how many tabs can be open at
  once; `AX25Station.max_links` (new, wired to the same number in
  `__main__.py`) enforces the same cap for incoming calls at the station
  layer, with a DM refusal rather than silence — "answer DM to traffic you
  do not have" applies here too, now that there is a real ceiling to hit.
  No new tabs for a live cap breach get evicted the way APRS's read
  conversations do: a terminal tab holds a live link with real resources
  (timers, an open transcript file), and silently disconnecting one to make
  room would be worse than refusing the new connection.
- **Out of scope, on purpose**: session-tier transports (Telnet, SSH, VARA,
  Mercury, kernel AX.25) still hold exactly one connection — `Session` has
  no per-peer keying the way `AX25Station.links` does, and building that is
  a separate, riskier change against transports already flagged unverified
  against real hardware (docs/ROADMAP.md and AGENTS.md §8).

**Files:** `kissterm/ax25/station.py`, `kissterm/ui/app.py`,
`kissterm/ui/terminal_pane.py`, `kissterm/ui/styles.py`, `kissterm/__main__.py`,
`DESIGN.md`, `docs/ROADMAP.md`, `tests/unit/test_station_max_links.py`,
`tests/pilot/test_terminal_sessions.py`, plus signature fixes in
`tests/pilot/test_terminal_ux.py`, `test_terminal_find.py`,
`test_transcript_and_color.py`, `test_app_mounts.py`, `test_transmit_gate.py`,
`test_transcripts_screen.py` for the now session-keyed `TerminalPane`/
`KissTermApp` methods.

## [2026-09-10] — Bearing/distance for plain packet nodes too, and MAIL FOR made a headline feature

### New Features
- **A plain (non-APRS) packet-node beacon can now feed the Heard pane's
  Distance/Bearing columns too.** Requested directly — a great many ordinary
  BBS/node beacons predate APRS and just say their grid square in plain text
  ("de W1AW FN31pr"), by long-standing convention rather than any protocol.
  `kissterm.locator.find_grid_in_text` is a deliberately conservative scan
  (see its docstring for the false-positive tradeoff, and why it never
  overrides a real APRS position) for a Maidenhead token bounded on both
  sides by `\b`, wired into `KissTermApp._on_aprs_frame` for exactly the case
  `aprs.parse_packet` already flags as "UI/PID-0xF0 but not APRS"
  (`kind == "unparsed"`) -- a real APRS position is read from its own precise
  field and never second-guessed by a text scan.

### Improvements
- **README's Features list now says out loud that kissterm watches for
  W0RLI/FBB "MAIL FOR" beacons** (`KissTermApp._check_mail_for`, shipped
  earlier and, as far as this project is aware, not something any other
  packet terminal does) and that the Heard pane's bearing/distance now
  covers plain packet nodes as well as APRS stations -- both were real,
  working capabilities that the README never actually mentioned.

**Files:** `kissterm/locator.py`, `kissterm/heard.py`, `kissterm/ui/app.py`,
`tests/unit/test_locator.py`, `tests/pilot/test_app_mounts.py`, `README.md`.

## [2026-09-09] — Heard pane: bearing and distance to every position-bearing station

### New Features
- **`kissterm/geo.py`** — great-circle bearing and distance (haversine),
  returning miles to match every other distance already in this codebase
  (`Position.range_mi`, `WeatherReport.wind_speed_mph`), plus a 16-point
  compass label (`compass_point`). No existing dependency covers this and
  the formulas are short, the same trade `locator.py` already made for
  Maidenhead conversion.
- **The Heard pane gained Distance and Bearing columns**, computed against
  the operator's own position (`Config.aprs.latitude`/`longitude` -- the
  same "no position set" test `AprsBeaconer` already uses) and each
  station's last known position. Click either header to sort by it, click
  again to reverse -- the "sorted bearing/distance-from-me list" P4's
  roadmap item called the realistic v1 of a heard-stations map. Recomputed
  fresh on every repaint, never cached, so a Settings change to the
  operator's own position shows up on the next refresh with nothing to
  invalidate.

### Fixes
- **`HeardTable.set_position` was dead code.** `heard.py`'s own module
  docstring already described it as fed by "the APRS layer after it decodes
  a position report", but nothing ever called it -- `HeardEntry.last_position`
  stayed `None` forever, silently, because the Heard pane never rendered it
  either, so there was nothing on screen to notice it missing. Wired into
  `KissTermApp._on_aprs_frame`, the same fan-out subscriber that already
  feeds message history and notifications, for `kind in ("position",
  "mic-e")` -- the two APRS kinds whose `data` names a station's own fix
  (an `object`/`item` report names something else, not the transmitting
  station, and is left alone).

**Files:** `kissterm/geo.py` (new), `kissterm/heard.py`, `kissterm/ui/app.py`,
`kissterm/ui/heard_pane.py`, `tests/unit/test_geo.py` (new),
`tests/pilot/test_app_mounts.py`, `docs/ROADMAP.md`.

## [2026-09-09] — Tabbed APRS conversations, with unread marked

### New Features
- **One conversation per tab in the APRS pane, plus an "All" tab.** Requested
  directly — APRS WebChat, which this pane was built to replicate, is tabbed:
  "tabs for active conversations, highlighted when a new message is
  received". Before this the pane had a single viewer showing whoever was
  picked last, so a message from anybody else left no mark on the screen at
  all and "who has written to me?" was answerable only from a toast that had
  already gone.
- **Tabs open on demand and none at launch**: picking a contact, sending to a
  callsign, or receiving a message **addressed to this station**. A tab that
  opens itself never steals the view — an arriving message must not move the
  screen out from under someone part-way through a reply to a third station.
- **Unread is marked twice**: `*` in front of the callsign and the theme's
  warning colour, on the tab *and* beside the callsign in the contacts table.
  The asterisk is what makes it readable for anyone who cannot see the colour;
  the colour is what makes it findable across a strip of tabs. Activating the
  tab clears both.
- **The "All" tab is always left-most and is where the pane opens** — every
  conversation merged, oldest line first, each line prefixed with the other
  station's callsign and outgoing lines keeping their `[ack]`/`[sent]`/
  `[retry N]`/`[no ack]` status. **It shows traffic between other stations
  too, deliberately**: every message packet decoded on the channel has always
  been recorded, and this is the first view that shows it, so All doubles as
  a channel message monitor.
- **`Delete` closes the tab you are on** (never "All"), shown in the Footer
  like every other panel key. Not `Ctrl+W`: `Input` already claims that for
  delete-word and the compose box is right beside the strip.
- Twelve conversation tabs are kept, evicting the least recently viewed —
  never "All", never the tab on screen, and **never one still holding
  something unread**, because throwing that away would lose the only record
  that somebody called.

### Improvements
- **The terminal, monitor and APRS logs no longer hide the end of a long
  line.** `RichLog` clamps every line up to its `min_width` (78) *after*
  shrinking it to the visible width, so in any column narrower than that —
  an 80-column terminal, or any width at all with a slide-out open beside it
  — lines were rendered 78 cells wide, not wrapped, and their tails left off
  the right-hand edge behind a horizontal scrollbar. A node's `?` listing
  arrived cut off mid-word ("`B to disconn`"), and in the new merged APRS
  view the missing tail was the delivery status. All three now use
  `kissterm/ui/wraplog.py`'s `WrapLog`, which tracks its own laid-out width.
  The obvious `min_width=0` is *not* the fix and read as one for exactly one
  test run: a widget on an inactive tab has a content width of zero, so
  everything written while the operator is on another tab renders as a blank
  line and is lost from the scrollback. Found by looking at a generated
  screenshot, not by a test — and one connect-script test had been passing
  *because* of the truncation, so it now runs with the slide-out closed.
- The contacts table's callsign column is 10 cells rather than 9, so an unread
  row's `*` cannot push the SSID off exactly the rows the marker points at.
- The APRS conversation tab strip is styled to read as *subordinate* to the
  F-key tab bar — muted inactive tabs, its underline bar dimmed to `$panel`.
  Textual's generic `Tabs Tab.-active` rule would otherwise have put two
  identical-looking navigations on one screen, which is not a hierarchy.

- **The screenshot script repaints both slide-outs after populating them.**
  They open themselves at mount, which is before the script has an address
  book or a contact list to show, and nothing repaints them again on its own
  — so every shot with a panel in it had become a picture of an empty table.

**Files:** `kissterm/ui/aprs_pane.py`, `kissterm/ui/app.py`,
`kissterm/ui/styles.py`, `kissterm/ui/terminal_pane.py`,
`kissterm/ui/monitor_pane.py`, `kissterm/ui/wraplog.py` (new),
`scripts/generate_screenshot.py`,
`tests/pilot/test_aprs_conversation_tabs.py`,
`tests/pilot/test_aprs_contacts_pane.py`,
`tests/pilot/test_connect_scripts.py`, `AGENTS.md`, `kissterm/ui/AGENTS.md`,
`DESIGN.md`, `docs/ROADMAP.md`, `assets/*.png`

## [2026-09-09] — The contact lists open themselves on a wide terminal

### New Features
- **The Terminal pane's Address Book and the APRS pane's contact list now
  open on their own** when the terminal is at least 80 columns wide — the
  width a terminal is unless someone changed it. A wide screen with half of
  it blank, and a `Ctrl+G` to press on every launch, was waste.
- **The split is a rule, not a percentage**: 58%, but never leaving the
  session or chat column beside it less than 40 columns, and capped at 74
  because past that a contact list is padding while the conversation next to
  it could use the space. Below 40 + 24 there is no useful split at all and
  the panel takes the pane while it is open — on a 40-column terminal you
  cannot have both, and half a contact list beside a two-character message box
  is worse than either alone. The contact table scrolls sideways when its
  share is tight, which was the explicitly accepted trade.
- **CSS cannot express that rule** — there is no arithmetic to relate a width
  to a sibling's minimum — so it lives in `kissterm/ui/slideouts.py` as pure
  arithmetic plus one small controller shared by both panes, and is applied on
  resize. `tests/unit/test_slideouts.py` checks it at every width from 1 to
  240; the `width` values left in `styles.py` are starting values only.
- `Config.slideouts_auto_open` (Settings > Display and logging) turns the
  behaviour off for an operator who wants the full-width viewer.

### Improvements
- **A panel that opens itself does not take the cursor.** DESIGN.md's
  "opening moves focus into the panel" is about a panel someone summoned to
  pick something from; stealing focus out of the message box because a window
  got wider is a different thing, and it now does not happen.
- **Picking a row closes only a panel the operator summoned.** One that opened
  itself is part of the layout, and closing it on a pick would take away
  something they never asked for.
- **A resize never overrules the operator.** Once `Ctrl+G` or Escape has been
  used on a pane, the width rule stops deciding for it that session — without
  that, dragging a window wider re-opened a panel someone had just closed.
- **The APRS compose row drops the Templates button when it runs out of
  room.** With the contact list open the conversation column can be 40 cells,
  and `To` + Templates + Send eat most of that before the message box gets
  anything — a two-character message box, which auto-opening would otherwise
  have made the default view rather than an edge case. Templates is the
  control that goes because it is purely a shortcut: `Ctrl+R` does the same
  thing and shows in the Footer as "Commands", so nothing becomes unreachable.

### Files
- `kissterm/ui/slideouts.py` (new), `kissterm/ui/aprs_pane.py`,
  `kissterm/ui/terminal_pane.py`, `kissterm/ui/styles.py`,
  `kissterm/config.py`, `kissterm/ui/settings_schema.py`, `DESIGN.md`,
  `AGENTS.md`, `tests/unit/test_slideouts.py` (new),
  `tests/pilot/test_slideout_auto_open.py` (new),
  `tests/pilot/test_addressbook_pane.py`, `tests/pilot/test_aprs_contacts_pane.py`

## [2026-09-09] — Tab order: APRS is F2, Monitor moves to F4

### Improvements
- **The tab bar is now ordered by how often an operator visits a pane**:
  `F1 Terminal  F2 APRS  F3 Heard  F4 Monitor  F5 Settings`. Requested
  directly — Terminal and APRS are where the work happens, while Monitor is a
  diagnostic and Settings is a place you leave again, so both belong to the
  right rather than in the middle of the run.
- **The `TabPane` ids did not move with the labels** (`terminal`, `aprs`,
  `heard`, `monitor`, `settings`). Every `active == "aprs"` check, every
  `_TAB_FOCUS` entry and every `action_show_tab` caller addresses a pane by
  id, so this was three labels and three key bindings rather than a search
  through the app — and DESIGN.md now records that as the reason to keep
  addressing panes by id.
- `tests/pilot/test_app_mounts.py` gained a single `TAB_BAR` table that the
  label test and a new key test both read, so a label saying `F2` while `F2`
  opens something else fails the suite. The key test presses from a focused
  input, which is the case the tab keys were silently broken in until
  yesterday's focus fix.

### Files
- `kissterm/ui/app.py`, `kissterm/ui/AGENTS.md`, `DESIGN.md`,
  `docs/ROADMAP.md`, `tests/pilot/test_app_mounts.py`,
  `tests/pilot/test_aprs_contacts_pane.py`

## [2026-09-09] — NTSGTE: the radiogram line format, cited at last

### New Features
- **`NTSGTE` now ships the full NTS radiogram line format** instead of only
  `INFO`. The previous entry stopped there on purpose — the gateway's own
  page documents no syntax, and a guessed format would have put a malformed
  radiogram into the National Traffic System under the operator's callsign.
  The operator supplied the missing source: chapter 14 of the APRS Protocol
  Reference 1.0.1 defines the `Nx\` line identifiers as part of the APRS
  message format itself (`N#\` preamble, `NA\` address, `NP\` phone,
  `N1\`-`N6\` text, `NS\` signature, `NR\` servicing record), along with
  the 67-character line limit, the six-line text maximum, and why the
  separator is a backslash — it exists in neither the RTTY nor the CW
  alphabet, so it cannot occur inside the traffic.
- **`QTC` and `NE\` are shipped as `recalled`, not `documented`.** Neither is
  in that chapter; both are transcribed from screenshots of one real NTSGTE
  session (WZ0C-5 filing message 487). `QTC <count>` announces how many
  radiograms are coming and the gateway answers when ready; `NE\` carries
  the addressee's email spoken out in radiogram form. They work, and saying
  they were sourced the same way as the rest would not be true.
- `tests/unit/test_aprs_services.py` closes the `Nx\` set against chapter
  14's list, asserts the confidence split, and checks every template still
  fits one 67-character message line.

### Files
- `kissterm/aprs_services/data/ntsgte.toml`, `tests/unit/test_aprs_services.py`

## [2026-09-09] — APRS contact list: callsign first, descriptions that fit, keys in the Footer

### Improvements
- **Callsign is the left-most column and each group is alphabetised.** It is
  what the operator is looking up and what the "To:" field wants.
- **The Service column says "Gateway Service", not "built-in".** The question
  it answers is what the row *is*, not where it came from.
- **The description moved into Detail, which was blank for a service**, and
  the operator's `detail` and `notes` now share that one column. Five columns
  do not fit the slide-out, and the column that fell off the right-hand edge
  was the description a shipped directory exists to show.
- **Column widths are computed from the table's actual width** rather than
  hard-coded (`aprs_pane._column_widths`, recomputed on resize). A
  `DataTable` scrolls sideways when its columns overflow — it does not shrink
  them — so a fixed set of widths only moves the problem to whichever
  terminal size they were not picked for. On a narrow table the kind marker
  shortens to "Gateway", a deliberate label rather than a mid-word clip.
- **The contacts and service-picker shortcut keys moved into the Footer.**
  They were printed as a hint line under the buttons; Textual's Footer
  already tracks focus and shows exactly these, so the second copy was the
  duplication DESIGN.md's "one place for each fact" rule exists to prevent.
  Removing it also puts the buttons at the same height as every other pane's.
- **Enter on a contact row, and a Message button, address the selected
  contact** and put the cursor in the message box — including for a gateway
  service row, which is a real callsign you really message.
- `assets/screenshot-aprs-contacts.png` is a new screenshot of the slide-out
  itself; the old set showed the pane only with it closed, which is how the
  overflow went unseen.

### Files
- `kissterm/ui/aprs_pane.py`, `kissterm/ui/dialogs.py`, `kissterm/ui/styles.py`,
  `scripts/generate_screenshot.py`, `tests/pilot/test_aprs_contacts_pane.py`,
  `assets/*`

## [2026-09-09] — APRS messages show sent, retry, ack, or no ack

### New Features
- **Every outgoing APRS message carries its delivery state** in the
  conversation view: `sent` (gone out, waiting), `retry N` (resent N times,
  still nothing), `ack` (the far end confirmed it), `no ack` (we stopped
  retrying and never heard one), `no ack requested` (sent unnumbered, so it
  is unackable by construction). Modelled on APRS WebChat, which this pane
  was built to replicate. Previously an acked message said `(acked)` and
  everything else said nothing at all, so "still trying" and "gave up" and
  "never sent" were indistinguishable — which is the whole question the
  numbered-message mechanism exists to answer.
- **An arriving ack repaints the open conversation immediately** rather than
  leaving a stale `sent` on screen for up to a retry interval.
- `PendingAcks.attempts_for` is a read-only lookup, deliberately separate
  from `due()`, so displaying a status cannot consume a retry.

### Files
- `kissterm/aprs_conversations.py`, `kissterm/ui/aprs_pane.py`,
  `kissterm/ui/app.py`, `tests/pilot/test_aprs_send.py`

## [2026-09-09] — APRS SSID

### New Features
- **`aprs.ssid` transmits APRS under its own SSID**, separate from the
  callsign connected-mode packet uses — conventionally -9 for a car, -7 for a
  handheld, -5 for a phone. It applies to the position beacon, outgoing
  messages, and auto-acks alike, so a station has one APRS identity rather
  than a beacon under one address and a message under another. Blank keeps
  the station callsign as-is, and an unparseable value degrades to it rather
  than transmitting something invented.

### Files
- `kissterm/config.py`, `kissterm/aprs_beacon.py`, `kissterm/ui/app.py`,
  `kissterm/ui/settings_schema.py`, `tests/unit/test_config.py`,
  `tests/unit/test_aprs_beacon.py`

## [2026-09-09] — Fix: F1-F5 bounced straight back while an input had focus

### Bug Fixes
- **Pressing a tab key while typing switched tabs and immediately switched
  back.** Textual re-activates a `TabPane` whenever a widget inside it takes
  focus; `action_show_tab` set `.active` without moving focus, so the pane
  being left still held it, Textual moved focus on within that now-hidden
  pane, and the activation snapped back. Reported against F2 from the APRS
  pane, but it affected **every** pane — F2/F3/F5 from the Terminal send line
  and from the APRS compose box were equally dead, which is most of the time
  anyone is actually typing. Fixed by clearing focus before switching and
  restoring it, after the switch settles, into the pane now on screen.
- The restored focus is a **fallback, never an override**: `Ctrl+F` switches
  to the Terminal tab and then focuses the find box, and stealing that back
  to the send line would put the operator's typing in the wrong widget. A
  late-firing focus also re-checks the active tab first, so two tab keys in
  quick succession cannot reintroduce the same bounce from the other side.
- It survived this long because every test drove `action_show_tab` without
  focusing anything first, and a fresh app has focus nowhere in particular.
  `tests/pilot/test_app_mounts.py` now presses the tab keys *from* a focused
  input.

### Files
- `kissterm/ui/app.py`, `tests/pilot/test_app_mounts.py`

## [2026-09-09] — Fix: the Settings symbol picker crashed the app

### Bug Fixes
- **Typing a filter word that matched no map symbol took the whole app
  down.** `Select.set_options([])` raises `EmptySelectError` when the widget
  was built with `allow_blank=False`, and it was raised out of a message
  handler, so there was nothing to catch it. Any word not in the symbol table
  was enough.
- **A second, quieter bug rode along**: `set_options` resets `.value`, and the
  old handler restored it only when the current symbol survived the filter —
  so narrowing past your own symbol silently blanked it, and saving then
  wrote an empty symbol. Both are fixed by one rule: the currently selected
  symbol is always pinned into the option list, whatever the filter says.
- This is the **third** distinct way this project has been bitten by
  `Select`'s value/option invariants; AGENTS.md sec. 7's `Select` entry now
  records all three.

### Files
- `kissterm/ui/settings_pane.py`, `tests/pilot/test_settings.py`

## [2026-09-09] — Roadmap: ISS is a path, not a contact; keeping the directory current

### Notes
- **`docs/ROADMAP.md`**: recorded why `RS0ISS`/`ARISS`/`APRSAT` were left out
  of the shipped service directory. They are a digipeater path you route
  *through*, not a bot you send commands *to*; shipping one as a service
  entry would have taught an operator something false. The real feature is a
  saved digipeat path preset, which overlaps the beacon path picker already
  in Settings far more than it overlaps messaging.
- **Added an item for keeping the directory current.** It ships a `checked`
  date per service and is explicitly a snapshot, not a liveness probe. There
  is no mechanism to notice a service that has gone away for good, and
  deliberately none that phones home — a periodic manual re-check against
  each entry's `source` URL is the honest answer.
- `Config.aprs_sms_gateway`/`aprs_email_gateway` now point at the shipped
  directory for the cited cases, while still defaulting to blank: which
  gateway an operator should use depends on their region and on who is
  running what this month, and picking one for them would be exactly the
  unearned confidence those fields' notes warn against.

### Files
- `docs/ROADMAP.md`, `kissterm/config.py`

## [2026-09-09] — Gateway services are built-in contacts, with a template picker

### New Features
- **The 17 shipped gateway services appear in the APRS contacts list**
  (`Ctrl+G`), after the operator's own contacts, marked `built-in`, with each
  service's one-line description in the Notes column. `WLNK-1` next to
  "Winlink radio email, read and sent over APRS" is the point — a bare
  callsign tells an operator nothing. They are rendered from
  `kissterm/aprs_services/` and never written into `Config.aprs_contacts`, so
  they improve when kissterm updates and can never masquerade as something
  the operator typed.
- **`Ctrl+R` on the APRS pane opens the template picker** for whoever is in
  the "To:" field — the service's commands, its description, its coverage,
  and its source URL. Same key as the Terminal pane's node command reference
  because it is the same question with a different answer; Terminal-pane
  behaviour is unchanged, and every other tab still gets the node reference.
  There is also a **Templates** button next to Send, because a discoverability
  feature reachable only by an undocumented key is not one.
- **Choosing a template fills the message box. It never sends.** This is
  AGENTS.md's existing completion rule, and it matters more here than for the
  terminal: several shipped commands *act* on arrival. APSPOT posts a public
  spot, SMSGTE texts a real phone. Two tests guard it — one drives the real
  selection handler for every one of the seventeen services with the transmit
  gate open and asserts nothing reached the wire, the other asserts it
  against the source.
- **Save your own messages** (Insert in the picker, `Config.aprs_templates`).
  Each one is either scoped to a service or global, which is what lets one
  list serve both "attach templates to the contact" and "keep a set of canned
  messages". Scoped entries sort above global ones, and both sort above the
  shipped commands.
- **`F2` on a built-in offers to save your own copy** rather than erroring —
  the reason to "edit" SMSGTE is to attach your own phone number, which is a
  new contact. **`Delete` hides it** (`Config.aprs_hidden_services`), since a
  built-in cannot be deleted and a key that does nothing looks broken.

### Notes
- The picker resolves a contact's own `gateway` field ahead of the shipped
  callsign table, so a gateway reachable at an unlisted callsign still gets
  its commands.
- Edits and deletions of saved messages match on content, not on a row index:
  the picker shows a filtered, re-ordered view, and treating a position in it
  as a position in the config list is how an edit silently rewrites the wrong
  entry.

### Files
- `kissterm/ui/aprs_pane.py`, `kissterm/ui/dialogs.py`, `kissterm/ui/app.py`,
  `kissterm/ui/styles.py`, `tests/pilot/test_aprs_templates.py`,
  `tests/pilot/test_aprs_contacts_pane.py`, `AGENTS.md`, `DESIGN.md`,
  `assets/*`

## [2026-09-09] — Fix a teardown race that wrote to a pane whose widgets were gone

### Bug Fixes
- **A link callback arriving during shutdown could raise `NoMatches` out of a
  worker.** `KissTermApp._to_terminal` already guards against the terminal
  pane being gone -- its docstring describes this exact class of bug -- but
  the guard was one level too shallow. There is a window on teardown where
  the pane is still in the widget tree and its children have already been
  removed, and `TerminalPane.log` / `_flush_incoming` queried `#session-log`
  directly. AX.25 retransmission runs on `call_later` callbacks with nowhere
  for an exception to go, so this violated the house rule that a background
  task never dies of one.
- **Found as an intermittent failure in an unrelated test**
  (`tests/pilot/test_transmit_gate.py`), which is the worst way to find
  anything: the failure pointed at the connect path, the cause was in the
  terminal pane, and a flake makes "the suite is green" stop meaning
  anything -- which in this repo is load-bearing, since a full green run is
  required before every commit.
- Only the two call sites reachable from a background callback changed.
  `clear` and the find helpers run from a keystroke, so the pane is
  necessarily alive; guarding those too would suggest a danger that is not
  there. The new regression test removes the pane's children and then calls
  both write paths -- it reproduces the original `NoMatches` exactly when
  the fix is reverted.

### Files
- `kissterm/ui/terminal_pane.py`, `tests/pilot/test_terminal_ux.py`

## [2026-09-09] — A shipped directory of 17 APRS gateway services

### New Features
- **`kissterm/aprs_services/` — what to say to an APRS gateway, shipped as
  data.** An operator who wants Winlink mail has to know `WLNK-1` understands
  `SP`, `L` and `/EX`; one who wants an SMS has to know `SMSGTE` wants
  `@5551234567 text`. None of that was discoverable from inside kissterm, and
  none of it should cost airtime to find out. Same reasoning that already put
  node command references in `kissterm/nodes/data/`, applied to the APRS side.
- **17 services, each with a cited source and a per-command confidence
  level**: `WLNK-1` (Winlink APRSLink), `SMSGTE` and `SMS` (SMS gateways),
  `EMAIL-2`, `MAIL`, `FIND`, `WXBOT`, `WXNOW`, `MPAD`, `CQSRVR`, `ANSRVR`
  (including the `CQ HOTG` / `U HOTG` pair for the worldwide weekly
  #APRSThursday net), `SOTA`/`APRS2SOTA`, `APSPOT`, `NTSGTE`, `WHO-IS`
  (and its `WHO-15` alias), `REPEAT`, `QRX`.
- **Every service carries a `summary` and a `note`, and the loader refuses a
  file without them.** A bare callsign like `MPAD` or `WLNK-1` in a contact
  list tells an operator nothing; the description is the feature here, not a
  nicety around it.

### Notes on provenance
- Commands are transcribed from the linked source, never reconstructed.
  `confidence` uses the same `verified`/`documented`/`recalled`/`learned`
  vocabulary `kissterm/nodes/reference.py` already shows, so there is one
  scale to learn. `QRX`'s and `MPAD`'s argument forms ship marked `recalled`
  because only their command *names* could be sourced.
- **`NTSGTE` ships exactly one command, `INFO`.** Its radiogram filing syntax
  is not published on the web -- it is in a training presentation and a
  video. Guessing a format would put a malformed radiogram into the National
  Traffic System under the operator's callsign, so kissterm asks the gateway
  instead. A test enforces this so a future session cannot helpfully fill
  the gap.
- **`ISS` is deliberately absent.** `RS0ISS`/`ARISS`/`APRSAT` are a digipeater
  path you route through, not a bot you send commands to; modelling it as a
  contact would teach something false.
- The directory is a snapshot, not a liveness probe -- several entries were
  reported down by a third-party health check while being written, and were
  shipped anyway with a `checked` date, because "down this afternoon" and
  "gone" are different facts this file cannot tell apart.

### Files
- `kissterm/aprs_services/__init__.py`, `kissterm/aprs_services/directory.py`,
  `kissterm/aprs_services/data/*.toml` (17), `tests/unit/test_aprs_services.py`,
  `pyproject.toml` (package-data), `AGENTS.md`

## [2026-09-09] — The WINLINK beacon flag is documented, not a guess

### Improvements
- **`Config.aprs.winlink_check` now cites its source instead of warning that
  it has none.** It shipped earlier the same day marked "UNVERIFIED, uncited
  convention", because nothing in reach confirmed it. The operator supplied
  the source -- <https://winlink.org/APRSLink>, which states it plainly: *"If
  you desire notification of pending Winlink email just add 'WINLINK'
  somewhere in your station's position comment (or status text)"* -- and
  confirmed it working on the air. APRSLink watches the APRS-IS feed for the
  token and sends a daily APRS alert while mail is waiting.
- The Settings help text no longer tells the operator the feature might not
  work. Overstating uncertainty is its own kind of wrong label: it invites
  someone to leave a working feature off.
- No behaviour change. The token, the placement, and the reserve-room-before-
  truncating logic in `AprsBeaconer.build_frame` were already right; only the
  provenance claim around them was wrong.

### Files
- `kissterm/config.py`, `kissterm/aprs_beacon.py`,
  `kissterm/ui/settings_schema.py`, `docs/CHANGELOG.md`

## [2026-09-09] — The full test suite runs in parallel now: ~15 min -> ~3 min

### Improvements
- **`pytest-xdist` added as a dev dependency, `-n auto` set as the default**
  (`[tool.pytest.ini_options]` in `pyproject.toml`). Measured on a 12-core
  machine: the full 815-test suite went from ~14.5 minutes serial to
  ~2m50s parallel, same tests, same result -- nothing removed, nothing
  weakened. Safe because `kissterm._isolate.isolate()` already gives every
  test file its own `tempfile.mkdtemp()` config directory and xdist
  workers are separate processes, so there is no shared state to collide
  on across workers. `-n0` still works for un-interleaved output when
  debugging one failing test.

### Files
- `pyproject.toml`, `AGENTS.md`

## [2026-09-09] — Roadmap: GPS integration scoped, object reports and APRS bulletins noted

### Improvements
- **GPS integration is now a fully scoped P4 roadmap item**, not built --
  the beacon Settings work above covers a fixed station only (static
  decimal-degree or grid-square entry); a mobile/portable operator with a
  GPS puck has nothing to plug into yet. Scoped module shape
  (`kissterm/gps.py`, modeled on `kissterm/hotplug.py`'s
  `SerialPortWatcher`), config field, device-discovery reuse (inverted
  from `discovery.py`'s TNC-scoring heuristic), the Bluetooth-GPS-is-just-
  a-serial-device confirmation, and how a live fix should feed
  `AprsBeaconer` without touching `Config.aprs.latitude`/`longitude`
  directly -- see `docs/ROADMAP.md` P4 for the full writeup. Needs real
  hardware to verify before it could ship, same as this project's other
  hardware-dependent items.
- **Two more P4 items added at the operator's request**, for after the
  beacon Settings work ships: sending object reports (with a selector
  reusing the new symbol picker) and sending APRS bulletins (the `BLNn`
  addressee convention -- not P10's BBS-style Mail/Bulletins/Files tab,
  a different feature entirely despite the name collision). Not built,
  not yet fully scoped -- flagged so the thought is not lost.

### Files
- `docs/ROADMAP.md`

## [2026-09-09] — Ctrl+Shift+B turns APRS beaconing on without opening Settings

### New Features
- **`Ctrl+Shift+B` is now context-aware by active tab**, the same dispatch
  shape `Ctrl+G` already uses for the Address-Book/Contacts slide-outs. On
  the Terminal pane it is completely unchanged: send one BTEXT beacon
  right now. On the APRS pane it instead toggles
  `Config.aprs.enabled` -- an operator no longer has to open Settings just
  to start position beaconing. Deliberately does **not** arm the transmit
  gate (AGENTS.md's transmit-gate rules name the manual beacon key
  specifically as a bare keystroke that must never do that -- this is the
  same case), and turns the plain-text (BTEXT) timer off if it was running
  when APRS beaconing is turned on this way, since an operator reaching
  for this key is very unlikely to want both running unattended at once.
  The toggle is persisted to `config.toml` immediately, same as a Settings
  save.

### Files
- `kissterm/ui/app.py`, `DESIGN.md`, `AGENTS.md`,
  `tests/pilot/test_beacon_key_dispatch.py` (new)

## [2026-09-09] — APRS Settings: a real symbol picker, WIDE presets, grid squares, Winlink notify

### New Features
- **The APRS Settings section stopped asking the operator to remember
  things.** Map symbol was a two-character text field an operator had to
  know from memory; the WIDE digipeater path was a bare string; position
  was decimal degrees only, with no help for anyone quoting their QTH as a
  grid square. All three are now real pickers:
  - **Map symbol** is a filterable dropdown (`kissterm/aprs/symbols.py`,
    the full primary+secondary APRS table, sourced from
    https://github.com/hessu/aprs-symbol-index) -- type "car", "digi",
    "fire" and the list narrows live. Each entry optionally carries a
    cosmetic emoji, shown only when `Config.ascii_safe` is False.
  - **Digipeater path** is a preset dropdown (`WIDE1-1,WIDE2-1` /
    `WIDE1-1` / `WIDE2-2` / direct) plus a **Custom...** option that
    reveals a free-text field -- a value that matches no preset (a
    hand-edited config.toml, say) still shows correctly as Custom with its
    literal text, never silently discarded.
  - **Position entry** can be typed as decimal degrees or a Maidenhead
    grid square (4/6/8 characters, `kissterm/locator.py`, new hand-rolled
    conversion verified against the well-known ARRL HQ reference point
    FN31pr) -- a mode dropdown switches between them, converting whatever
    is already entered rather than discarding it. A regression bug was
    caught and fixed here before it shipped: bulk-loading the position
    widgets from a saved config used to be able to silently overwrite an
    exact stored latitude with the center of its own grid square, because
    the Input widgets' own live-sync handlers could process their queued
    `Changed` messages after the mode had already switched underneath
    them. Fixed by using `set_reactive` (no message posted at all) for the
    bulk-load path, rather than trying to out-race Textual's async message
    queue with a timing-sensitive suppression flag.
- **"Check for Winlink messages" checkbox** (`Config.aprs.winlink_check`).
  Appends `WINLINK` to the transmitted beacon comment, reserving room for
  the token before truncation runs so a long comment never crowds it out.
  Shipped marked **UNVERIFIED**; see the entry below dated 2026-09-09 --
  the source turned up and it is documented behaviour after all.

### Files
- `kissterm/locator.py`, `kissterm/aprs/symbols.py` (both new, previous
  commit), `kissterm/config.py`, `kissterm/aprs_beacon.py`,
  `kissterm/ui/settings_schema.py`, `kissterm/ui/settings_pane.py`,
  `kissterm/ui/styles.py`, `tests/unit/test_aprs_beacon.py`,
  `tests/pilot/test_settings.py`

## [2026-09-09] — APRS beaconing actually beacons

### New Features
- **APRS position beaconing is wired up.** `Config.aprs`'s Settings section
  has said "Transmits your position on a timer" since it shipped, but
  nothing read those fields -- toggling "Enable APRS beaconing" on did
  nothing at all. `kissterm/aprs_beacon.py`'s new `AprsBeaconer` closes that
  gap: same shape as `kissterm/beacon.py`'s `Beaconer` (`start`/`stop`/
  `cancel`/`send_once`/`problem`/`build_frame`, sleep-then-send, re-checked
  at the moment of transmission, off by default) but its own timer, its own
  config table, and its own destination (`APRS`, always, per `_send_aprs_ack`/
  `_send_aprs_message`'s existing convention) -- never conflated with the
  plain-text beacon, per AGENTS.md's "a beacon is not APRS beaconing" rule.
  - `Config.aprs.latitude`/`longitude` both `0.0` (the untouched default) is
    treated as "no position set," not the Gulf of Guinea -- refused rather
    than transmitting a placeholder position under the operator's callsign.
  - The same 10-minute interval floor as the plain-text beacon, enforced in
    both `config._load_aprs` and `AprsBeaconer.interval_seconds` -- the
    Settings field's minimum was quietly 1 while the help text said 10;
    both now agree.
  - Wired into `KissTermApp` exactly like the existing beacon: constructed
    in `__init__`, (re)started from `apply_runtime_settings` on mount and
    every Settings save, cancelled on `on_unmount`, every transmission
    logged to the terminal pane, and an `APRS BEACON` status-bar marker for
    as long as it is armed -- the same "unattended transmission is always
    visible" rule as `ANSWERING`/`BEACON`.

### Files
- `kissterm/aprs_beacon.py` (new), `kissterm/config.py`, `kissterm/ui/app.py`,
  `kissterm/ui/settings_schema.py`, `tests/unit/test_aprs_beacon.py` (new),
  `tests/pilot/test_aprs_beacon_wiring.py` (new), `docs/ROADMAP.md`

## [2026-09-09] — Roadmap audit: several open items were already shipped, and two Settings fields are dead

### Improvements
- **`docs/ROADMAP.md` had drifted from the code in both directions.** Six
  items were checked off with a full paragraph of detail but never removed
  (P1's two hardware-verification bullets, P4's four APRS-pane bullets) --
  they were fully described in CHANGELOG already, so this just deletes the
  duplicated, stale copy per this file's own "ROADMAP.md only ever shows
  what's still open" rule. Three open items described work that was
  actually already shipped and were removed or corrected instead:
  - **Classic Bluetooth RFCOMM** (`kissterm/transport/bluetooth.py`,
    `kind = "bluetooth"` in config) has existed since the initial commit --
    the roadmap item referenced a `bluetooth_kiss.py` that was never the
    real filename and described the whole feature as unbuilt. `SETUP.md`
    had the identical error, telling operators the direct-RFCOMM-socket
    path "does not yet exist" when it has always worked. Only BLE (GATT)
    remains genuinely unbuilt (`BleKissTransport` still raises
    `NotImplementedError`).
  - **`scripts/generate_screenshot.py`** was listed as a P6 item ("once
    there's a UI worth screenshotting") despite being the tool this
    project's own AGENTS.md §6 tells every session to run after a layout
    change, and being referenced by name in a dozen-plus CHANGELOG entries.
  - **The command-reference modal** was still described as "the F6
    reference pane" in P8; it is `Ctrl+R` and has not been an F-key since
    before Address Book's own F5/F6 shuffle.
  - Weather/telemetry decoding (`kissterm/aprs/telemetry.py`) turned out to
    already be fully implemented and wired into `aprs.parse_packet` -- only
    the pane that would *display* a decoded `WeatherReport`/`Telemetry`
    is still missing. Reworded rather than removed, since the display half
    is real remaining work.
- **Two Settings fields do nothing, and now say so in the roadmap instead of
  only in Settings' own copy.** `Config.ascii_safe` (Settings: "ASCII-safe
  mode") and `Config.aprs.enabled`/`beacon_interval_minutes`/etc (Settings:
  "Transmits your position on a timer") both have complete config/Settings
  plumbing and neither is read anywhere outside `config.py` and
  `settings_schema.py` -- toggling either one currently changes nothing
  about what the app draws or transmits. Not fixed in this pass (that is
  real feature work, not a docs cleanup), but called out explicitly in
  `docs/ROADMAP.md` P4 and P6 so the gap between "the Settings pane says
  this happens" and "this happens" is written down somewhere a future
  session will actually read before assuming either field works.
- `kissterm/AGENTS.md`'s top-level file map was missing six real modules
  (`addressbook.py`, `aprs_contacts.py`, `aprs_conversations.py`,
  `aprs_notify.py`, `desktop_notify.py`, `transcripts.py`) and still
  described `kissterm/app.py` as containing the app's tabs/CSS/bindings,
  which moved to `kissterm/ui/app.py` on day one -- `app.py` itself already
  carries a docstring saying so; the file map just never caught up.

### Files
- `docs/ROADMAP.md`, `SETUP.md`, `AGENTS.md`

## [2026-09-09] — Width-aware Footer, and Ctrl+P as a real key reference

### New Features
- **The Footer now shows the highest-priority prefix of its key list that
  actually fits the terminal, not everything truncated.** Reported directly
  from a real session: Textual's own `Footer` is a horizontally-scrollable
  container with its scrollbar suppressed, so at an ordinary 80-column
  terminal roughly a third of kissterm's eleven action bindings were being
  pushed past the right edge, reachable only by a mouse-wheel scroll with no
  on-screen sign anything was missing. `KissTermFooter`
  (`kissterm/ui/app.py`) keeps TX, Connect, Disconnect and Contacts first --
  the cluster an operator reaches for mid-contact -- and adds the rest back
  in priority order as the terminal widens, re-fitting live on resize.
- **`Ctrl+P` is now a real, searchable key reference.** Nothing previously
  registered a Textual command-palette `Provider`, so Ctrl+P only ever
  listed Textual's own small built-in System Commands (Theme, Quit, Keys,
  Maximize, Screenshot) and typing in its search box filtered that short
  list, not kissterm's own keys. `commands.KeyBindingsProvider` walks every
  action in `KissTermApp.BINDINGS` -- including Ctrl+B/Ctrl+D's hidden
  legacy-terminal fallbacks and anything the Footer has no room for -- and
  offers them fuzzy-searchable, grouped by category (Connection, Transmit,
  Terminal, Contacts, Panes, App).
- Both read one shared table, `kissterm/ui/commands.py`'s `ACTION_META`
  (category + Footer priority per action), so a key can no longer be
  discoverable in one place and not the other. A `Binding` missing an entry
  fails `tests/pilot/test_app_mounts.py::test_every_visible_binding_action_
  has_footer_and_palette_metadata` at test time rather than silently
  dropping out of the Footer at some width.

### Files
- `kissterm/ui/app.py`, `kissterm/ui/commands.py` (new)
- `DESIGN.md`, `kissterm/ui/AGENTS.md`, `docs/ROADMAP.md`
- `tests/unit/test_commands.py` (new), `tests/pilot/test_app_mounts.py`

## [2026-09-09] — Address Book and APRS contacts become Ctrl+G slide-outs

### New Features
- **The Address Book is no longer a tab.** `F5 Address Book` is removed;
  Settings moves back to `F5` (it briefly held `F6` while Address Book had
  its own key). Dialing a station is now a `Ctrl+G` slide-out docked on the
  right of the Terminal pane, opened with the table immediately focused and
  closed with Escape or a second `Ctrl+G` -- same list, same CRUD, same
  `action_connect` flow underneath, just reached from where an operator
  actually dials rather than a separate destination.
- **The APRS pane's contacts list is the same pattern**, on the right of the
  APRS pane: hidden until `Ctrl+G`, and picking a contact closes the panel
  again so the conversation it just loaded is what's on screen next.
- **One key, dispatched per active tab.** `KissTermApp.action_toggle_contacts`
  opens whichever slide-out belongs to the current tab and is a silent
  no-op elsewhere (Monitor, Heard, Settings). Checked against every existing
  `Input`/app-level binding before landing on `Ctrl+G` -- see
  `kissterm/ui/app.py`'s `Binding` comment and `DESIGN.md`'s new "slide-out
  panels" section, which is the recipe Mail's own contacts panel is expected
  to reuse once that tab exists. No animation: the panel appears instantly,
  per `DESIGN.md`'s "no animation" rule -- "slides out" describes where it
  ends up, not a motion effect.
- `docs/ROADMAP.md` P10's F-key assignments shift up by one slot
  accordingly: Mail F6, Bulletins F7, Files F8, with F9/F10 spare.

### Files
- `kissterm/ui/app.py`, `kissterm/ui/terminal_pane.py`,
  `kissterm/ui/aprs_pane.py`, `kissterm/ui/styles.py`
- `DESIGN.md`, `docs/ROADMAP.md`, `README.md`, `SETUP.md`,
  `scripts/generate_screenshot.py`
- `tests/pilot/test_addressbook_pane.py`, `tests/pilot/test_app_mounts.py`,
  `tests/pilot/test_aprs_contacts_pane.py`, `tests/pilot/test_aprs_send.py`

## [2026-09-09] — SMS/email-over-APRS compose forms

### New Features
- **`kissterm.aprs_contacts.build_message_body`** builds the actual on-air
  message body for an SMS/email contact -- `<phone/address> <text>` by
  default -- from `Config.aprs_sms_template`/`aprs_email_template` (a
  `str.format()` template with `{detail}`/`{text}`) and the contact's
  `detail` field. A malformed hand-edited template falls back to the
  default rather than failing the send. The APRS pane's conversation log
  keeps what the operator actually typed, never the templated wire body --
  readable history, not a wire dump -- and a retry resends the exact wire
  bytes rather than re-templating the human text a second time.
- **`Config.aprs_sms_gateway`/`aprs_email_gateway`** (blank by default)
  pre-fill a new contact's callsign in `AprsContactScreen` when its
  service is switched to sms/email, only while the callsign field is
  still empty -- never overwrites one already typed or one an existing
  contact already has.
- New Settings section "APRS messaging" for all four fields.
  **UNVERIFIED, and said so in the UI**: gateway callsigns and
  message-body formats vary by region and change over time -- this
  codebase has no way to confirm one from here, so these ship as editable
  defaults, never asserted as fact.
- This closes the last of the four APRS-pane roadmap items from this
  pass (frame-fan-out subscriber/notifications, contacts CRUD, send with
  ack/retry, and this one).

### Files
- `kissterm/aprs_contacts.py` (`build_message_body`), `kissterm/config.py`,
  `kissterm/ui/aprs_pane.py`, `kissterm/ui/dialogs.py`,
  `kissterm/ui/settings_schema.py`
- `tests/unit/test_aprs_contacts.py`, `tests/pilot/test_aprs_send.py`,
  `tests/pilot/test_aprs_contacts_pane.py`

## [2026-09-09] — APRS pane: send a message, with ack and retry

### New Features
- **The APRS pane can now send.** A "To:" input (independent of the
  contacts table -- a bare callsign not in the contact list can still be
  messaged, the same way Connect and the Address Book coexist) plus a
  compose input and Send button. Sending goes through
  `KissTermApp._send_aprs_message`, a new shared primitive that encodes
  and transmits one APRS message frame through the existing transmit gate
  (never auto-armed -- this is repeatable chat traffic, not a one-shot
  confirmed action like Connect) and writes every send to the terminal
  pane, the same visibility rule the auto-ack path already follows.
- **`kissterm.aprs_conversations.PendingAcks`** -- in-memory-only tracking
  of outgoing messages awaiting an ack (never persisted, same reasoning as
  `AX25Link`'s T1/T2/T3 timers). The APRS pane runs a periodic timer that
  reconciles it against `ConversationStore.mark_acked` (flipped by
  `_on_aprs_frame`'s existing ack-matching logic on the frame fan-out) and
  resends anything still due, up to a small retry count. A retry reuses
  `_send_aprs_message` with `retry=True` so it is never recorded as a
  second history entry for the same logical message.
- This closes the roadmap item requested directly: replicate what
  KM6LYW's APRS WebChat does, in terminal form.

### Files
- `kissterm/ui/app.py` (`_send_aprs_message`), `kissterm/ui/aprs_pane.py`,
  `kissterm/aprs_conversations.py` (`PendingAcks`), `kissterm/ui/styles.py`
- `tests/pilot/test_aprs_send.py` (new), `tests/unit/test_aprs_conversations.py`

## [2026-09-09] — APRS pane: contacts list, CRUD, and read-only message history

### New Features
- **The APRS pane (F4) is real** -- `kissterm/ui/aprs_pane.py` replaces the
  placeholder with a two-column layout: an APRS messaging contacts table
  on the left (`Config.aprs_contacts`), the selected contact's message
  history on the right (read-only -- from `kissterm.aprs_conversations`,
  written by yesterday's `_on_aprs_frame` subscriber). No compose input
  yet, so nothing in this pane can transmit.
- **`AprsContactScreen`** (`kissterm/ui/dialogs.py`) -- add/edit a contact:
  name, callsign (the APRS addressee to send to), a service picker
  (station/SMS/email), and a detail field whose placeholder/label
  re-labels itself for the selected service. Insert/F2/Delete on the
  contacts table follow the exact convention `_AddressBookTable` already
  established.
- `scripts/generate_screenshot.py` now captures the APRS pane
  (`assets/screenshot-aprs.png`) with sample contacts and a sample
  exchange, per the "screenshot after any layout change" rule.

### Files
- `kissterm/ui/aprs_pane.py`, `kissterm/ui/dialogs.py`,
  `kissterm/ui/styles.py`, `scripts/generate_screenshot.py`
- `tests/pilot/test_aprs_contacts_pane.py` (new)

## [2026-09-08] — APRS decode reaches a frame subscriber: message history, auto-ack, and message/Emergency notification

### New Features
- **`aprs.parse_packet` is now called from a live frame-fan-out subscriber**
  (`KissTermApp._on_aprs_frame`, `kissterm/ui/app.py`) -- a second
  subscriber on the same fan-out the monitor pane uses, never a second
  decode path (AGENTS.md sec. 2b). This is the prerequisite roadmap item
  (docs/ROADMAP.md P4) that both the dedicated APRS pane and any
  decode-driven feature needed before either could exist; first two
  consumers ship in this same change.
- **APRS message history** (`kissterm/aprs_conversations.py`,
  `ConversationStore`) -- every incoming/outgoing message, kept per
  correspondent (callsign+SSID, unlike the SSID-stripped "addressed to me"
  check below), persisted as JSON in the state directory the same way
  `kissterm/addressbook.py` persists the station list. Pending-ack/retry
  bookkeeping is deliberately NOT persisted -- see the module docstring.
- **Auto-ack for a message addressed to the operator**
  (`Config.aprs_auto_ack`, default `true`) -- `KissTermApp._send_aprs_ack`
  sends `aprs.encode.ack` through the same transmit gate as every other
  transmission, checks the gate itself first so a closed gate can never be
  logged or recorded as a sent ack, and writes every auto-ack to the
  terminal pane, the same visibility rule a beacon or connect-script line
  follows.
- **Message-addressed-to-me and Emergency-Mic-E desktop notification**
  (`kissterm/aprs_notify.py`, pure decision logic with no I/O --
  `evaluate_packet`/`Cooldown`) -- delivered via a new
  `desktop_notify.notify_any()` (herdr first, `notify-send` as the
  cross-desktop GNOME/KDE/XFCE fallback, confirmed present here). An
  Emergency flag always bypasses the per-(source, reason) cooldown; the
  passive "MAIL FOR" notice (`_check_mail_for`) now goes through the same
  `notify_any` fallback chain rather than herdr alone.
- **`Config.aprs_contacts`** (`kissterm/aprs_contacts.py`) -- the APRS
  messaging contact list, deliberately separate from the station Address
  Book: a messaging contact (`name`/`callsign`/`service`/`detail`/`notes`,
  `service` one of station/sms/email) is a different kind of thing from a
  connect target. Storage-only in this change -- the Contacts editor
  screen and the chat view that use it are the next P4 item.
- `monitor.callsign_matches` -- the SSID-stripping match `mail_waiting_for`
  already did inline, extracted so the new "message addressed to me" check
  shares the exact same rule instead of a second copy of it.

### Files
- `kissterm/ui/app.py`, `kissterm/aprs_notify.py` (new),
  `kissterm/aprs_conversations.py` (new), `kissterm/aprs_contacts.py` (new),
  `kissterm/monitor.py`, `kissterm/desktop_notify.py`, `kissterm/config.py`,
  `kissterm/ui/settings_schema.py`
- `tests/unit/test_aprs_notify.py`, `tests/unit/test_aprs_conversations.py`,
  `tests/unit/test_aprs_contacts.py`, `tests/pilot/test_aprs_messaging.py`
  (all new), `tests/pilot/test_settings.py`

## [2026-09-08] — Mic-E verified against real traffic; found and fixed two decode bugs; added an independent cross-check to the test suite

### Bug fixes
- **`kissterm/aprs/mice.py`'s `_MICE_MESSAGES` table had every bit pattern
  inverted, causing a normal "Off Duty" Mic-E beacon to decode as
  "Emergency" and vice versa.** `(1,1,1)` was mapped to "Emergency" and
  `(0,0,0)` to "Off Duty" -- the exact opposite of the real convention.
  Caught while doing the P1 roadmap item "verify Mic-E against a real
  captured packet": a standalone receive-only sniffer script (subscribing
  to the operator's real UZ7HO SoundModem feed, never transmitting) logged
  ~30 real Mic-E frames from ~7 distinct New England stations, and the
  decoded statuses were implausible -- mostly "Emergency"/"Priority", never
  "Off Duty", the default virtually every tracker ships with and nobody
  changes. Cross-checked against `aprslib` (PyPI, an independent, mature
  APRS parsing library) -- its `MTYPE_TABLE_STD` computes the identical
  letter-vs-digit bit per destination-callsign character kissterm does, but
  maps `(1,1,1)` to "Off Duty" and `(0,0,0)` to "Emergency". Re-decoding all
  ~30 captures against the corrected table turned every implausible
  "Emergency"/"Priority" into a mundane, station-consistent "Off Duty"/
  "En Route"/"In Service".
- **N/S, the longitude-offset flag, and E/W had a second, narrower bug**,
  found immediately after while building the automated cross-check below
  rather than by a new capture: these three flags were read off the same
  generic "letter = flag set" bit the 3-bit message code uses, but the real
  flag is set by the CUSTOM-range letters (P-Y/Z) specifically -- an A-K
  letter there should read as flag-clear, same as a digit. No real capture
  exposed this (a correctly-encoding transmitter never puts an A-K letter
  in positions 4-6, so the two rules happened to agree on every real frame
  seen so far), but the parametrized cross-check below caught it
  immediately once it exercised that combination. Confirmed against both
  `aprslib` and Direwolf's `decode_aprs.c` before fixing it.
  The existing hand-built fixtures in `tests/unit/test_aprs.py` were
  regenerated to use real, correctly-encoded destination bytes (previously
  they used A-K letters for the N/S/E-W flags, which is itself not
  something a real encoder produces) and their expected text corrected; a
  new `test_mic_e_emergency_message` keeps the Emergency case under direct
  test. **Files:** `kissterm/aprs/mice.py`, `tests/unit/test_aprs.py`.

### New Features
- **`tests/unit/test_aprs_mice_cross_check.py`: an automated, independent
  cross-check for the Mic-E decoder**, added specifically because the two
  bugs above showed this file's own hand-built fixtures cannot catch a bug
  they were built to agree with. Generates Mic-E frames from first
  principles (an encoder independent of anything in `kissterm/aprs/`) across
  every message bit pattern, both codesets, and five lat/lon/hemisphere
  combinations (including the longitude +100 offset branch), and decodes
  each one through both `parse_mic_e` and `aprslib.parsing.mice.parse_mice`,
  asserting agreement. `aprslib` is GPLv2 and stays a **test-only** dev
  dependency -- never imported at runtime -- so it puts no copyleft
  obligation on kissterm (MIT) or anyone distributing it; see the `dev`
  extra's comment in `pyproject.toml`. **Files:** `pyproject.toml`,
  `tests/unit/test_aprs_mice_cross_check.py`.

### Verification
- **Mic-E position decode (lat/lon, N/S, longitude offset, E/W) is now
  independently confirmed correct against real traffic**, closing the rest
  of this P1 item. A real "Oxford County EOC" (W1OCA) Mic-E beacon decoded
  to lat 44.2207/lon -70.5188; that office's real street address (26
  Western Avenue, South Paris, ME) geocodes to 44.2211/-70.5183 -- about
  150m apart, well inside Mic-E's precision. See
  `kissterm/aprs/mice.py`'s module docstring for the full account.

## [2026-09-08] — Connected mode verified against real hardware

### Verification
- **P1's top-priority open item is closed: the AX.25 connected-mode state
  machine has now run for real, repeatedly, against real packet nodes over
  a real TNC** -- not only the software loopback. Sessions against WS1EC-15
  and CCEMA span 2026-09-05 through 2026-09-08 in
  `~/.local/state/kissterm/logs/kissterm.log` (`--log-level debug`) and a
  matching set of per-session transcripts in `logs/*_KC1JMH_*.log`. What the
  debug log actually shows, not just a successful connect:
  - **SABM/UA handshake** on every connect, both nodes.
  - **Multi-frame I-frame transfer** -- over 400 I-frames logged with
    content, modulo-8 sequence numbers wrapping correctly past S7 back to
    S0 (`ax25/window.py`'s modular arithmetic, on the air, not simulated).
  - **RR acknowledgement piggybacking** and a live poll/final exchange
    (`RR R4 P cmd` / `RR R0 F res` pairs).
  - **A real REJ recovery**, not just the loopback's injected-loss
    version: `13:53:55 TX ... KC1JMH>CCEMA REJ R2 F res` in the 2026-09-08
    session, confirming out-of-sequence detection and go-back-N recovery
    both fire against a real peer's real timing, not just
    `tests/loopback.py`'s synthetic loss.
  - **Clean DISC/UA close** in both directions (kissterm-initiated and
    peer-initiated), across multiple sessions.
  This does not close the rest of P1's verification items -- APRS Mic-E,
  the compressed-position cs-byte, and the modulo-128 fallback are each
  separate code paths and remain open; APRS specifically has not been
  exercised yet even though APRS UI frames from WS1EC-2 and WS1EC-15 are
  visible passing through the monitor in the same log. **Files:** none (a
  documentation-only update recording verification already performed);
  see `docs/ROADMAP.md` P1.

## [2026-09-08] — Passive "mail waiting" notification, with an optional herdr desktop alert

### New Features
- **kissterm now notices someone else's node beaconing "MAIL FOR
  {your callsign}" and raises a notification for it, with no connection
  needed.** Requested directly: "even if the user isn't connected to the
  node, the modem is just on frequency." Reads UI (unproto) frames off the
  existing shared frame fan-out (`AX25Station.transport.subscribe`, see
  AGENTS.md sec. 2b) the same way the monitor pane and heard list already
  do -- passive, like `_sniff_node`'s node-family detection, never a
  question asked of the channel. `monitor.mail_waiting_for` matches the
  W0RLI/FBB "MAIL FOR" convention against `Config.mycall` and
  `mycall_aliases`, on the base callsign as well as an exact match (a
  mailbox holding mail for "W1AW" and an operator running "W1AW-7" are the
  same person). Marked `# UNVERIFIED:` per this repo's rule -- the exact
  beacon wording was never checked against a real captured one, only the
  documented convention. `KissTermApp._check_mail_for` writes a line into
  the terminal log, raises kissterm's own in-app notification, and
  de-duplicates by (source callsign, matched callsign) so a beacon
  repeating on its own interval does not re-notify every time it is heard
  again. **Files:** `kissterm/monitor.py`, `kissterm/ui/app.py`,
  `tests/unit/test_monitor.py`, `tests/pilot/test_mail_waiting_notice.py`.
- **New `kissterm/desktop_notify.py`: mirrors that alert (and is available
  for future ones) through herdr's desktop notification CLI, when present.**
  A kissterm pane is easy to miss if it is not the one focused, especially
  under a terminal workspace manager holding several panes at once -- which
  is exactly the situation the mail-waiting notice above is for, since the
  whole point is finding out without kissterm in view. Detection is
  `HERDR_ENV=1` (herdr's own marker) plus the `herdr` binary on PATH, so an
  install merely present on the machine does not pop notifications into a
  session herdr is not actually showing. Confirmed interactively against a
  real herdr install: `herdr notification show <title> [--body TEXT]
  [--sound none|done|request]` returns a JSON result with `"shown": true`.
  Runs as an async subprocess with a bounded timeout, never a blocking
  call -- `AX25Link` schedules its own timers on the running loop
  (AGENTS.md sec. 3), and a synchronous wait on an external process here
  would stall them. Every failure (herdr absent, binary gone, a hang)
  degrades to "did not notify" and never raises, same rule this codebase
  applies to every other background-task failure. **Files:**
  `kissterm/desktop_notify.py`, `kissterm/ui/app.py`,
  `tests/unit/test_desktop_notify.py`.

## [2026-09-08] — A word could split across a frame boundary in the Terminal pane

### Fixes
- **Incoming text could hard-wrap mid-word ("You have 2 me" / "ssages
  waiting for you.").** Reported directly from a real session, also seen
  splitting `BULLETIN` mid-word in a message-list line. Root cause: AX.25
  delivers incoming data one frame at a time (`AX25Link.on_data`, up to
  `paclen` bytes), with no regard for where a word ends, and
  `TerminalPane.write_incoming` wrote every such chunk straight to the
  `RichLog` -- but each call to `RichLog.write` renders as its own line
  rather than continuing the previous one, so a word straddling a frame
  boundary always became a hard line break at that exact byte, with no
  relation to the pane's width or an actual wrap point. Fixed by buffering:
  `TerminalPane._flush_incoming` holds back everything after the last
  newline (`\n` or a bare `\r` -- packet nodes are CR-oriented) until either
  a newline completes it or a bounded idle timer (200 ms) fires, so a chunk
  boundary is invisible unless it happens to land on a real line break. A
  prompt with no trailing newline still appears (via the idle timer); a
  disconnect or Ctrl+L flushes or discards whatever is pending rather than
  losing or reordering it. **Files:** `kissterm/ui/terminal_pane.py`,
  `tests/pilot/test_transcript_and_color.py`.

## [2026-09-08] — The Connect dialog was too tall

### Improvements
- **The Connect dialog collapsed from an always-tall form to a quick
  "type a callsign, hit Connect" box.** The address book, previously an
  always-visible OptionList that could run to 8 rows plus its own title and
  hint line, is now a single-row "Address book" dropdown -- typing in the
  target field still narrows it, and picking a row still fills the target
  field and previews everything saved for that station in one step (it no
  longer requires arrowing in and pressing Enter to preview, since a
  `Select`'s own overlay highlight isn't something a preview can hook the
  way `OptionList.OptionHighlighted` was). Node hops and a hand-typed,
  unnamed login -- both blank on nearly every connect -- no longer get
  permanent rows either: Node hops now lives under Saved script, revealed
  by "+ Node hops (advanced)..." there (or automatically, if a picked
  address-book entry already has some); the free-text login box now lives
  under Saved credential, revealed by "+ Add new credential..." there, and
  typing a Name next to it there saves it as a new, reusable entry in
  `Config.credentials` instead of a one-off (leaving Name blank keeps it a
  one-off, exactly like before). **Files:** `kissterm/ui/dialogs.py`
  (`ConnectScreen`), `kissterm/ui/app.py` (`action_connect` persists an
  inline "+ Add new credential..." pick via the new
  `ConnectRequest.new_credential_text`), `kissterm/ui/styles.py`,
  `tests/pilot/test_app_mounts.py`, `tests/pilot/test_connect_scripts.py`.

## [2026-09-08] — A real connect never said "Connected", Enter sometimes didn't send, and scripts get their own list

Three more findings from side-by-side testing against EasyTerm on the same
node.

### Fixes
- **A fresh outgoing connect never announced itself.** `AX25Station.connect`
  only returns the link once the SABM/UA exchange is already done, which is
  AFTER the one moment the UI could have registered an `on_state` callback
  on it -- so the transition into `connected` fired to nobody, and if the
  node had nothing to say until you typed something, there was no
  confirmation on screen at all (EasyTerm's "*** Connected to station X"
  had no kissterm equivalent). `action_connect` and
  `_connect_session_transport` now print `*** Connected to <peer>`
  explicitly, right after binding the link, instead of depending on a
  callback that structurally cannot catch this one transition. **Files:**
  `kissterm/ui/app.py`, `tests/pilot/test_connect_scripts.py`.
- **Enter sometimes didn't send.** Typed text sent fine through the Send
  button but plain Enter did nothing, on a terminal (Konsole) whose
  enhanced keyboard protocol this app already depends on elsewhere (`Ctrl+
  Shift+B`/`D`) -- the same class of protocol can occasionally attach a
  modifier to a bare Enter that changes the key name Textual reports, missing
  `Input`'s own "enter"-only binding. `_SendInput` (a thin `Input` subclass)
  adds `shift+enter`/`ctrl+enter`/`alt+enter` bindings routed to the same
  `action_submit`, so the outgoing box is not dependent on getting exactly
  one specific key name back from the terminal. **Files:**
  `kissterm/ui/terminal_pane.py`, `tests/pilot/test_terminal_ux.py`.
- **The "Connected" fix above only reached the screen, not the transcript
  file.** Pulling the actual log from the WS1EC-15 report that prompted
  it showed the durable ``* connected`` line still arriving eleven seconds
  late -- timed to the next state transition (a T1 timer-recovery retry)
  rather than the real connect at 15:30:25 -- because the first fix wrote
  straight to the terminal pane instead of through `_note` (the one method
  that reaches both the pane and the transcript). Both call sites now use
  `_note`, so a transcript pulled after the fact shows the connect where it
  actually happened. **Files:** `kissterm/ui/app.py`,
  `tests/pilot/test_connect_scripts.py`,
  `tests/pilot/test_session_transport.py`.
- **Clicking Send left focus on the button, not the input.** A second
  report on the same WS1EC-15 session described needing to click Send,
  then click back into the text field, for every line -- Textual moves
  focus to whatever was clicked, and nothing in `send_line` moved it back.
  `TerminalPane.send_line` now refocuses the input on every path through
  it, so clicking Send once behaves like pressing Enter once: the field is
  ready for the next line immediately. **Files:**
  `kissterm/ui/terminal_pane.py`, `tests/pilot/test_terminal_ux.py`.

### New Features
- **Saved scripts, kept separate from saved credentials.** Requested
  directly: a credential is a login, named for the account it belongs to;
  a script is any command sequence sent after connecting (login then a
  node hop, a mailbox check, ...), named for what it does -- conflating
  them into one list was flagged as wrong even though the underlying
  mechanism (a named block of text, sent line by line) is identical.
  `Config.scripts` is a new list, same shape as `Config.credentials`
  (`{"name", "text"}`), with its own Settings tab (New/Edit/Forget, reusing
  `CredentialScreen` with `kind="script"` rather than a near-duplicate
  dialog). The Connect dialog, the Address Book editor, and
  `TransportEntryScreen`'s auto-login section each gained a second "Saved
  script" dropdown next to "Saved credential" -- three sources now, checked
  in order (credential, then saved script, then literal text) by the new
  `KissTermApp._resolve_login`, wherever an auto-login is resolved.
  `addressbook.Entry`, `ConnectRequest`, `AddressBookEdit` and `Transport`
  all gained a matching `script_name` field alongside their existing
  `script`/`credential`. **Files:** `kissterm/config.py`,
  `kissterm/addressbook.py`, `kissterm/transport/base.py`,
  `kissterm/transport/__init__.py`, `kissterm/ui/app.py`,
  `kissterm/ui/dialogs.py`, `kissterm/ui/settings_pane.py`,
  `kissterm/ui/addressbook_pane.py`, `config.toml.example`,
  `tests/pilot/test_settings.py`, `tests/unit/test_config.py`.
- **The Connect dialog can switch which same-tier transport it dials
  through.** Requested directly, for "different modems" -- a second KISS
  TNC, a second Telnet/SSH host. `ConnectScreen` gains a transport dropdown
  (frame tier), and a new `SessionTransportPickerScreen` covers the session
  tier, which previously had no dialog on `Ctrl+N` at all to put a picker
  in; both are shown ONLY when there is a real choice (2+ same-tier
  transports configured) and default to whichever is already active, so
  the overwhelming one-transport case is unchanged. Picking a different
  one calls new, shared `KissTermApp._switch_frame_transport`/
  `_switch_session_transport` before dialing -- the frame-tier one is the
  same logic `SettingsPane`'s own Active-transport switch already used
  (moved onto the app so both callers share one implementation instead of
  two that could drift). Deliberately does NOT offer switching TIERS live
  (frame KISS TNC to/from a session-tier Telnet/SSH/VARA/etc, or vice
  versa) -- monitor/heard/beacon/status-bar are all wired to whichever
  tier the app launched on, and retrofitting a live tier swap was scoped
  out as a separate, much larger and riskier change than what was asked
  for. New `transport.FRAME_TIER_KINDS`/`SESSION_TIER_KINDS` name the
  split. **Files:** `kissterm/transport/__init__.py`, `kissterm/ui/app.py`,
  `kissterm/ui/dialogs.py`, `kissterm/ui/settings_pane.py`,
  `kissterm/ui/styles.py`, `tests/unit/test_transport_factory.py`,
  `tests/pilot/test_connect_scripts.py`,
  `tests/pilot/test_session_transport.py`.
- **Past session transcripts are findable and exportable from inside the
  app, not just from a shell.** `kissterm/session_log.py` has written one
  plain-text file per connected session since P1, but the only way to find
  one again was `ls`/`grep` on the log directory. New `Ctrl+O` opens
  `TranscriptsScreen`: a searchable list of every transcript (newest
  first), a live preview pane, and an "Export" field/button that copies
  the selected one to any path the operator types, creating the
  destination directory if needed. The search box matches on
  callsign/filename first and falls back to the transcript's own text, so
  "what did we say about the net frequency" is answerable without knowing
  which callsign or date it was. Read-only over the originals -- nothing
  here can edit or delete a transcript, only copy one out. New
  `kissterm/transcripts.py` (listing/search/export, no Textual import, so
  it is testable with no running app) and `TranscriptsScreen` in
  `kissterm/ui/dialogs.py`. Also fixed the startup banner, which had
  advertised "Ctrl+H for help" since the very first commit even though no
  `Ctrl+H` binding has ever existed in this app -- it now names the two
  keys that actually do something (`Ctrl+R` commands, `Ctrl+O`
  transcripts). **Files:** `kissterm/transcripts.py`,
  `kissterm/ui/dialogs.py`, `kissterm/ui/app.py`,
  `kissterm/ui/styles.py`, `tests/unit/test_transcripts.py`,
  `tests/pilot/test_transcripts_screen.py`.
- **`Ctrl+F` finds text in the Terminal pane's scrollback.** A find bar
  above the log (Enter: next match, Shift+Enter: previous, Escape or Close
  closes it) that counts matches as you type and jumps between them,
  wrapping past the last one back to the first rather than stopping.
  Case-insensitive, and matched against `RichLog.lines` directly -- the
  same wrapped display lines already on screen, not a second copy of the
  transcript kept just for this. Read-only, like the scrollback it
  searches: nothing here can be typed into the session by accident.
  New `TerminalPane.open_find`/`action_close_find` and the `#find-row`
  it toggles; `KissTermApp.action_find_in_terminal` switches to the
  Terminal tab first, so Find never leaves the operator wondering where
  the box went from some other tab. **Files:** `kissterm/ui/terminal_pane.py`,
  `kissterm/ui/app.py`, `kissterm/ui/styles.py`,
  `tests/pilot/test_terminal_find.py`.
- **Paste protection on the send line.** A paste is sanitized before it
  reaches the box a plain Enter would transmit -- the opposite direction
  from `ansi.py`'s remote-to-local filtering, protecting the channel from
  the operator's own clipboard instead of the screen from the far end.
  `Input`'s own paste handler already keeps only the first line of a
  multi-line paste, but silently; `_SendInput._on_paste` now says so, and
  additionally strips C0/C1 control bytes (a binary clipboard, or a copied
  terminal session, could otherwise put bytes on the air that look exactly
  like something the operator typed) and caps a single line at 512
  characters, since a paclen of 256 turns one long pasted line into many I
  frames with no way to take the Enter back once it is pressed. Any of the
  three triggers a warning notification naming what changed. **Files:**
  `kissterm/ui/terminal_pane.py`, `tests/pilot/test_paste_protection.py`.
- **Configurable paclen/window per link.** `ax25.session.LinkParams` was
  already a per-link dataclass, but every link a station opened got an
  identical copy of `self.params`, built once from the global
  `Config.paclen`/`window` -- there was no way to run a slow HF link and a
  fast LAN VHF link at once with each using sane values. `AX25Station.
  connect` now takes optional `paclen`/`window` overrides that apply to
  just that one link via `dataclasses.replace` (still clamped by
  `LinkParams.__post_init__`, so an override can't corrupt sequence-number
  arithmetic any more than a config-file value could); the station's own
  `self.params` is never mutated, so every other link keeps the global
  default. `addressbook.Entry` gained matching `paclen`/`window` fields,
  set from two new optional Address Book editor fields (blank means "use
  Settings' default", same convention as everywhere else in that dialog)
  and validated the same way hops/target already are; `KissTermApp.
  action_connect` reads them off the resolved entry and passes them
  through on every dial, including a saved address-book entry, not just a
  live-typed target. Deliberately not exposed in the quick Connect dialog,
  same reasoning as `frequency`/`connection_type`: a per-station tuning
  choice belongs in the Address Book editor, set up once, not retyped on
  every dial. **Files:** `kissterm/ax25/station.py`,
  `kissterm/addressbook.py`, `kissterm/ui/dialogs.py`,
  `kissterm/ui/addressbook_pane.py`, `kissterm/ui/app.py`,
  `tests/unit/test_link_params_override.py`,
  `tests/unit/test_addressbook.py`, `tests/pilot/test_addressbook_pane.py`.
- **Hex color pickers for the Custom theme.** `Config.custom_theme`'s eleven
  fields were config-file-only since theming shipped -- editing one meant
  hand-editing `[custom_theme]` in `config.toml`. They are now eleven
  ordinary fields in the Settings pane's Appearance tab (`kind = "color"`,
  new in `settings_schema.py`), which is what makes this "small once the
  pattern for a color-swatch input exists" as the roadmap put it: `coerce()`
  validates against the same `HEX_COLOR_RE` `config.py`'s TOML loader
  already used (renamed from `_HEX_COLOR_RE` to share it, one regex so a
  value the Settings pane accepts is guaranteed to also survive
  `load_config()` on the next launch), and every other save/apply/live-theme
  mechanism the schema-driven pane already had -- `_save`'s per-field
  validation, `_apply_live`'s `app.apply_theme()` call -- needed no changes
  at all. The only genuinely new piece is the swatch: a small `Static` next
  to each hex `Input`, filled from the typed value live via `Input.Changed`
  and bordered `$error` the moment the text stops parsing as a color, so a
  typo is visible before Save is even pressed rather than only after.
  **Files:** `kissterm/config.py`, `kissterm/ui/settings_schema.py`,
  `kissterm/ui/settings_pane.py`, `kissterm/ui/styles.py`,
  `kissterm/ui/themes.py`, `config.toml.example`,
  `tests/pilot/test_settings.py`.

## [2026-09-07] — "They got it, they're just not answering" is now on screen

From a real, fully-logged case: connected to WS1EC-15 cleanly (SABM/UA),
sent a line, and the node ACKed it (an RR) within 3 seconds -- then said
nothing for 22 more, and the operator had no way to tell "they got it,
they're just slow" from "this went nowhere" without reading `--log-level
debug` output. Confirmed against the modem's own independent monitor: both
logs agreed to the millisecond, and kissterm's AX.25 layer was correct
throughout (V(A) advanced on the RR, no spurious retransmit). The gap was
entirely in what the operator could see.

### New Features
- **A note when a sent line goes unanswered.** `KissTermApp._note_if_no_
  reply`, armed by `log_sent` and cancelled the moment any data comes back
  or the link stops being plainly CONNECTED. Fires `REPLY_WAIT_SECONDS`
  (15s) after a send with nothing since, and only when the AX.25 layer has
  already acknowledged that line (`link.va == link.vs`) -- if it has NOT
  been acknowledged, T1/timer-recovery is already retrying and already
  wrote its own note, so this stays quiet rather than repeating that with
  less detail. **Files:** `kissterm/ui/app.py`,
  `tests/pilot/test_transcript_and_color.py`.

### Improvements
- **`MonitorFilter.show_supervisory` now defaults to on.** RR/RNR/REJ are
  exactly the "did they get it" evidence on an ordinary one-to-one link,
  and hiding them by default is what let the report above happen: the one
  frame that proved the node was responding never appeared. The noise
  argument for hiding them still holds on a busy multi-station link, which
  is what the pane's own "Supervisory" toggle is for -- its label now shows
  which state it's in ("Supervisory: on/off", highlighted when on) instead
  of only a toast on the press that set it, since a setting that changes
  behaviour on every future frame should be visible after the fact too.
  **Files:** `kissterm/monitor.py`, `kissterm/ui/monitor_pane.py`,
  `tests/pilot/test_monitor_sees_both_directions.py`.
- **Fixed the Monitor tab's filter row: the "Supervisory" button was
  invisible.** `Input`'s own default CSS is `width: 100%`, which inside a
  `Horizontal` claimed the entire row and pushed the button off the right
  edge with nothing on screen to suggest it existed -- confirmed against
  the committed screenshot from before this fix, so this predates
  everything else in this entry and was never about the button's label.
  **Files:** `kissterm/ui/styles.py`.

## [2026-09-06] — Add a transport by hand: Settings > Transports > New

The gap behind a report that looked like an Address Book bug: "I can't
select from multiple transports in the address book if I can't save
multiple transports in the settings." True -- "Scan for hardware" only
finds a KISS TNC or AGWPE engine it can identify by itself (see AGENTS.md's
"Discovery must only emit a config it can actually complete"); it has never
been able to add a VARA/Mercury modem, a Telnet or SSH node, or a second
entry for hardware already found, and until now neither could anything
else in the app -- that was `config.toml`-only, documented in
`config.toml.example` but with no UI path at all.

### New Features
- **Settings > Transports > New / Edit selected.** `TransportEntryScreen`
  (`kissterm/ui/dialogs.py`) is a form whose fields change with the chosen
  kind -- a serial device path, a TCP/AGWPE host and port, a VARA/Mercury
  host/callsign/ports, or a Telnet/SSH host (SSH adds username/password) --
  each matching that kind's real constructor. A Telnet/SSH/VARA/Mercury/
  kernel-AX.25 entry gets the same auto-login section the Connect dialog
  has (`script`/`credential`), since those are the session-tier kinds
  `Transport.script` actually does something for. Saving proves the entry
  by calling `transport.build_transport()` -- the one place a `Transport` is
  ever constructed from config -- and refuses to save if it raises, the
  same rule the first-run wizard already follows and for the same reason:
  a config entry that looks right and fails at `open()` is worse than
  catching it here. This is also what makes the Address Book's Connection-
  type picklist (2026-09-06, above) actually useful for anything a scan
  cannot find, which is most of what an operator would want to add second.
  **Files:** `kissterm/ui/dialogs.py`, `kissterm/ui/settings_pane.py`,
  `kissterm/ui/styles.py`, `tests/pilot/test_settings.py`.

## [2026-09-06] — Disconnect fixed while typing, and the transcript path is a header now

Two things caught from live use right after the Telnet/SSH work above.

### Fixes
- **Disconnect is now `Ctrl+Shift+D`.** Plain `Ctrl+D` is also
  `Input`/`TextArea`'s own binding for delete-character-right, and the
  outgoing-message box holds focus for nearly all of a live session -- so
  the Footer silently dropped the "Disconnect" hint the moment that box took
  focus, and the keystroke deleted a character instead of disconnecting.
  Reported directly ("^d went missing when I started to connect, but the
  keystroke still was able to cancel the attempt" -- that second half was
  luck: focus had not reached the box yet at that exact moment). Plain
  `Ctrl+D` is kept, hidden, as a fallback for whenever focus happens to be
  somewhere that does not shadow it, same pattern as `Ctrl+Shift+B`/`Ctrl+B`
  for the beacon. `Ctrl+K` (Callsign) has the identical collision and is not
  fixed here -- see the comment above its `Binding` in `kissterm/ui/app.py`.
  **Files:** `kissterm/ui/app.py`, `tests/pilot/test_transmit_gate.py`,
  `README.md`, `AGENTS.md`, `DESIGN.md`.

### Improvements
- **The transcript path is a fixed header above the scrollback, not a line
  inside it.** A session can run for hours; a line logged once and then
  scrolled past is not "shown to the operator" in any way that survives
  Ctrl+L or normal scrolling. `TerminalPane.set_transcript_note` owns it now;
  `KissTermApp._start_transcript`/`_close_transcript` set and clear it
  instead of writing a `"*** Transcript: ..."` log line. Also answers a
  direct request that the transcript note read before the "Connecting..."
  line rather than after it -- a header is always above the scrollback by
  construction, so the two can no longer land in the wrong order regardless
  of how long the connect attempt takes. **Files:** `kissterm/ui/app.py`,
  `kissterm/ui/terminal_pane.py`, `kissterm/ui/styles.py`,
  `tests/pilot/test_transcript_and_color.py`.

## [2026-09-06] — Session-transport auto-login, and an Address Book copy pass

Two follow-ups from actually looking at the Telnet/SSH work above.

### New Features
- **Auto-login for Telnet/SSH (and VARA/Mercury/kernel AX.25).** A session
  transport's config entry can carry `script` (inline text) or `credential`
  (a name from `[[credentials]]`) and it is sent, one line at a time, right
  after connecting -- the WS1EC case in full: the SSH login only reaches
  the shell account, whose own profile then runs `telnet` into the real
  BPQ node and prompts again for a packet callsign and password. A
  script's last line can be `C <node>`, so one script both logs in and
  reaches the actual service, the same as typing that hop by hand. See
  `Transport.script`'s docstring (`kissterm/transport/base.py`),
  `build_transport`'s `_named` (`kissterm/transport/__init__.py`), and the
  worked example in `config.toml.example`/SETUP.md §6a.
- **Address Book "Connection type" is now a picklist of the operator's own
  configured transports** (`kissterm/ui/dialogs.py`'s `AddressBookEntryScreen`),
  not free text -- shown as "name (kind)", e.g. "ws1ec (SSH)", from a new
  `KIND_LABELS` map in `kissterm/transport/__init__.py`. Still informational
  only (shown on `RadioReminderScreen` before connecting); it does not
  change which transport a dial actually uses. A value saved before this
  change, or naming a transport since renamed or removed, still shows up
  and round-trips as its own option rather than crashing the screen or
  silently vanishing.

### Improvements
- Reworded the Connect and Address Book dialogs: shorter placeholders
  ("Node hops, e.g. N1QFY, AB1KI-15 (optional)" instead of a parenthetical
  paragraph), the auto-login section renamed "Auto-login" with a one-line
  hint ("Pick a saved credential, or type a login below") and the
  previously blank, unlabeled script box now says what belongs in it. A
  Select's "(type your own below)" prompt referring to a sibling control
  was exactly the "puzzle, not a placeholder" DESIGN.md now warns against.
- `DESIGN.md` §8 gained two rules: a dialog is not a docstring (Settings
  copy can afford a fuller explanation; a modal mid-task cannot), and a
  placeholder must stand alone rather than pointing at another widget.
- Trimmed the Address Book tab's own persistent note to one short sentence
  -- it was explaining internal mechanism (the transmit gate, transport
  check) the operator does not need re-told every time a frequently-used
  tab opens. Audited every other modal and pane note against the same
  standard; nothing else needed changing.

## [2026-09-06] — Telnet and SSH: reaching a node over the Internet

Asked directly, with the concrete case already in hand: WS1EC (Maine Packet
Radio) accepts `ssh packet@ws1ec.mainepacketradio.org -p 4122`, where the
account's own login shell runs a local `telnet` into the real BPQ node the
moment the session opens. Neither Telnet nor SSH was supported at all --
worse, investigating turned up that the whole `SessionTransport` tier
(VARA, Mercury, kernel AX.25 too) had never been reachable from the app:
`station is None` on that tier meant `Ctrl+N` did nothing but refuse.

### New Features
- **Telnet and SSH transports** (`kind = "telnet"` / `"ssh"` in
  `config.toml` -- see `config.toml.example` and SETUP.md §6a). Neither
  carries AX.25 framing: the remote node's own telnet or SSH server accepts
  the connection and the byte stream *is* the session from the moment it
  opens, the same way SyncTERM or a plain `telnet`/`ssh` client already
  reaches this kind of node. SSH is password-auth only for now and does
  not yet verify the host key (both flagged plainly in `ssh.py`'s module
  docstring and in docs/ROADMAP.md, not silently shipped as more complete
  than they are); it needs the new optional `asyncssh` dependency
  (`pip install kissterm[ssh]`). Both verified against real local
  Telnet/SSH servers in `tests/unit/test_telnet_transport.py` and
  `tests/unit/test_ssh_transport.py` -- `asyncssh` ships a genuine SSH
  server too, so the SSH tests run a real handshake and password
  authentication over loopback, not a mock.
- **The `SessionTransport` tier is wired into the app for the first time.**
  `KissTermApp.action_connect` now branches on `session_transport` when
  there is no `AX25Station`, connects it directly (no target dialog, no hop
  chain, no address book -- a session transport has exactly one
  destination, fixed at configuration), and binds the resulting `Session`
  into the terminal pane through a new `_SessionLinkAdapter`, which
  presents `Session`'s shape as `AX25Link`'s so `_bind_link`, `action_
  disconnect` and the status bar work unchanged for either tier. This is
  what actually unblocks VARA, Mercury and kernel AX.25 too, not just the
  two transports added today -- all three existed as backend classes with
  nothing in the UI that could ever call `.connect()` on one.

### Fixes
- `transport/base.py`'s `Session.path` is now optional: VARA/Mercury/kernel
  AX.25 dial a real AX.25 callsign, but Telnet/SSH have none to give
  (`AX25Address.parse` would reject a hostname outright) -- `Session.peer`
  falls back to the transport's own detail string when there is no path.
  Added `Session.connected`, mirroring `AX25Link.connected`, for the same
  reason. Both are additive; no existing caller's shape changed.
- `docs/ROADMAP.md`'s kernel-AX25 entry said "new
  `kissterm/transport/kernel_ax25.py`" as an open TODO -- the file has
  existed and been fully implemented for a while (one `# RESEARCH:`-marked
  socket-API detail aside). Corrected to what is actually still open: real
  verification against a live `kissattach` setup, unblocked by the UI
  wiring above. SETUP.md's kernel-AX25 section had the same "not yet
  implemented" claim; fixed there too.

**Files:** `kissterm/transport/telnet.py` (new), `kissterm/transport/
ssh.py` (new), `kissterm/transport/base.py`, `kissterm/transport/
__init__.py`, `kissterm/ui/app.py`, `kissterm/__main__.py`, `pyproject.toml`,
`config.toml.example`, `SETUP.md`, `docs/ROADMAP.md`,
`tests/unit/test_telnet_transport.py` (new), `tests/unit/test_ssh_
transport.py` (new), `tests/pilot/test_session_transport.py` (new),
`tests/unit/test_transport_factory.py`

## [2026-09-06] — Address Book gets its own tab: F5, dial directly, frequency reminders

Follow-up to the same day's "a place to manage the address book" entry below,
after it turned out to be used far more often than a one-time setup screen --
closer to Terminal/Monitor in how often an operator reaches for it than to
Settings. **Breaking for muscle memory: Settings moved from F5 to F6.**

### New Features
- **Address Book is now its own main tab, at F5** (`kissterm/ui/
  addressbook_pane.py`), pulled out of Settings entirely. Settings moved to
  F6 to make room -- `Ctrl+5`/`Ctrl+6` follow. See `kissterm/ui/app.py`'s
  module docstring for the numbering rule this keeps.
- **Dial directly from the table.** Enter or the "Connect" button calls
  `KissTermApp.action_connect(prefill=entry)` -- the exact same flow as
  typing a target into Ctrl+N (transmit gate, transport check, hop chain,
  login), never a second, lighter-weight path onto the air. Recorded as an
  attempt like any other connect.
- **Frequency and connection type** on an entry (`Entry.frequency`,
  `Entry.connection_type`, set from the Address Book editor only -- purely
  informational, kissterm cannot tune a radio or start a modem). When
  either is set, connecting to that entry -- by dial or by typing its
  target into Ctrl+N -- now shows a blocking "Before connecting" checkpoint
  (`RadioReminderScreen`) before anything is armed. It exists precisely
  because a reminder seen only after the SABMs went out is worthless;
  cancelling it transmits nothing at all.

### Fixes
- **`docs/ROADMAP.md`'s F-key ceiling is now genuinely tight.** P10's three
  planned tabs (Mail, Bulletins, Files) assumed Settings would keep F5,
  leaving F6-F8. With Settings now at F6, only F7-F8 remain for three tabs.
  Flagged explicitly in that section rather than left to surprise whoever
  picks up P10 -- do not add another tab there without resolving it first
  (merging Mail/Bulletins behind one tab is the leading option).
- README, `scripts/generate_screenshot.py` and its screenshots regenerated
  for the new numbering; corrected a stale README claim that the command
  reference was `F6` (it has been `Ctrl+R` since before this session).

**Files:** `kissterm/addressbook.py`, `kissterm/ui/app.py`,
`kissterm/ui/addressbook_pane.py` (new), `kissterm/ui/dialogs.py`,
`kissterm/ui/settings_pane.py`, `kissterm/ui/styles.py`, `README.md`,
`docs/ROADMAP.md`, `scripts/generate_screenshot.py`, `assets/*`,
`tests/unit/test_addressbook.py`, `tests/pilot/test_app_mounts.py`,
`tests/pilot/test_settings.py`, `tests/pilot/test_connect_scripts.py`,
`tests/pilot/test_addressbook_pane.py` (new)

## [2026-09-06] — A place to manage the address book

Asked directly: "where do I manage, edit, etc the address book? does it have
its own modal or tab?" It did not -- the only way to touch an entry was the
Connect dialog's inline history (filter, arrow, Delete), with no way to view
the whole list, add a station in advance, or fix a typo without attempting a
live connect first.

### New Features
- **Settings > Address Book.** A table of every saved station (target, node
  hops, login, attempts, connects) with New/Edit/Forget. Saves straight to
  the address book's own JSON file, not `config.toml` -- it changes on every
  connect attempt and does not wait for the Settings "Save" button.
  Add/edit reuses the Connect dialog's hop-chain and credential/script rules
  (`AddressBookEntryScreen`, sharing `_validate_target_and_hops` and
  `_disable_while_credential_selected` with `ConnectScreen` rather than
  duplicating them) and shares one address book with the Connect dialog's
  history, so anything saved here shows up there and vice versa.
- **Insert/F2/Delete/Enter** on the table match `syncterm`'s dialing
  directory (Insert adds, F2 or Enter edits, Delete forgets) -- familiar
  muscle memory for anyone who has used a classic BBS terminal's phone book.
  Bound on the table widget itself, not the pane, so Delete still deletes a
  character out of an Input on another Settings tab rather than forgetting
  whatever row happened to be selected on a tab that was not even open.
- `AddressBook.upsert()`: create or hand-edit an entry without touching
  `attempts`/`connects` -- setting a station up in advance, or fixing a typo
  in its hop chain, is not an attempt to reach it. Handles a renamed target
  by dropping the old spelling first, since `_touch` matches whole strings
  and would otherwise leave it behind as an orphaned duplicate.

**Files:** `kissterm/addressbook.py`, `kissterm/ui/dialogs.py`,
`kissterm/ui/settings_pane.py`, `kissterm/ui/styles.py`,
`tests/unit/test_addressbook.py`, `tests/pilot/test_settings.py`

## [2026-09-05] — Node-to-node connect chains, and saved credentials

Follow-up to the same day's "per-station login scripts" entry below, after it
turned out that was answering a different question than the one asked: not a
login macro, but a Winlink/BPQ-style connect script -- reach a station that
has no digipeater path by connecting to one node at a time, waiting for each
one's own CONNECTED reply, the way `bpq-apps`' node-map crawler already does
against real BPQ nodes.

### New Features
- **Node-to-node hop chains.** An address-book entry can now carry an ordered
  list of intermediate nodes (`AddressBook.Entry.hops`). kissterm connects
  (via its own AX.25 SABM) to the first one, then sends "C <node>" over that
  one link for each remaining hop in turn -- including the actual target,
  which is just the last hop -- waiting for a CONNECTED reply before sending
  the next. An explicit BUSY/FAILED/DISCONNECTED/TIMEOUT reply stops the
  chain immediately and is reported differently from a hop that just stays
  silent past the timeout, same reasoning as a DM versus an N2 timeout one
  layer down. A stalled chain leaves the operator connected to whichever
  node was last reached rather than tearing anything down. See
  `KissTermApp._hop_through`/`_hop_to` in `kissterm/ui/app.py`.
- **Saved credentials.** Settings has a new Credentials tab: named,
  free-text login snippets (`Config.credentials`), because packet BBS logins
  do not agree on a shape -- some want a bare password, some want a name and
  a password, some want more. An address-book entry can reference one by
  name instead of storing its own copy of the text; the name is looked up
  fresh at connect time, so changing a password once in Settings updates
  every station that points at it on its next connect, with no per-entry
  re-save. The Connect dialog's script box is disabled (never cleared or
  overwritten) while a saved credential is selected, so toggling the
  dropdown back and forth can never leak one credential's text into another
  station's literal script.
- The Connect dialog gained a "Path (node hops)" field and a "Send once
  connected" credential dropdown alongside the existing script box; a
  digipeater path (`via`) and node hops are refused together, since they do
  not compose -- one repeats a single frame at the link layer, the other is
  a sequence of independent connects made minutes apart.

### Fixes
- **`Select.NULL`, not `Select.BLANK`, is this Textual version's "nothing
  selected" sentinel** -- `Select.BLANK` is a stale alias equal to the bool
  `False`. Assigning it crashes; comparing against it does not, but is
  silently always true, which is worse. Found while wiring the credentials
  dropdown, and it was already latent in `SettingsPane`: saving with no
  transport selected wrote the literal string `"Select.NULL"` into
  `config.active_transport`, and "Forget selected" with nothing chosen fell
  through instead of returning early. Fixed everywhere in `settings_pane.py`
  and guarded by two new regression tests.

**Files:** `kissterm/config.py`, `kissterm/addressbook.py`,
`kissterm/ui/app.py`, `kissterm/ui/dialogs.py`, `kissterm/ui/settings_pane.py`,
`kissterm/ui/styles.py`, `config.toml.example`, `AGENTS.md`, `docs/ROADMAP.md`,
`tests/unit/test_addressbook.py`, `tests/unit/test_config.py`,
`tests/pilot/test_app_mounts.py`, `tests/pilot/test_settings.py`,
`tests/pilot/test_connect_scripts.py` (new)

## [2026-09-05] — Per-station login scripts, and Settings stops being one long scroll

More feedback from the same on-air test session. Five separate reports, all
fixed here:

### New Features
- **Per-station auto-login scripts.** Every address-book entry can carry a
  short script -- lines sent one at a time, a little over half a second
  apart, once the connect to that station actually comes up. Arrowing
  through the Connect dialog's history previews the script saved for each
  row; whatever is in the box when Connect fires travels with the target and
  is saved back, blank or not. It rides the same armed, confirmed request the
  connect itself already got -- nothing extra to opt into -- and every line
  is echoed into the terminal log and the transcript exactly as if typed, and
  stops rather than silently drops a line if the gate closes or the link
  drops mid-script. See `AddressBook.Entry.script` and
  `KissTermApp._run_connect_script`.

### Fixes
- **Settings is a tabbed form now, not one long scrolling page.** One tab per
  section (Station, Transports, Link, ...), with Save and Reload in a bar
  below the tabs that never scrolls -- reaching Save used to mean scrolling
  past everything else first, every time, on a page that ran to several
  screens once Beacon and APRS were both on it. A validation failure now
  jumps to the first tab with a bad field and names every tab that has one,
  since the field is not necessarily on the tab currently open.
- **The Save toast is one short sentence.** Cross-check warnings used to be
  appended to the same toast notification, which then read as an unreadable
  paragraph gone before it could be read. That detail still goes somewhere
  durable -- the footer bar, which does not disappear -- just not into a
  toast with a few seconds on the clock.
- **Switching the active transport in Settings actually switches it.**
  Picking a different entry from Active and hitting Save changed
  `config.active_transport` and nothing else; the live station kept talking
  to its original transport object, so the status bar kept reporting the old
  TNC no matter how many times the operator saved. `AX25Station.
  rebind_transport` now does the other half: build the new transport, open
  it, and swap it in -- refusing if a link is still connected, since that
  would silently misroute a live conversation's frames onto unrelated
  hardware. Fixing this exposed a second bug: `kissterm/__main__.py`'s
  shutdown closed the transport it originally built rather than whatever
  `station.transport` currently was, leaking the newly-opened one (a live
  socket or serial handle) every time an operator switched transports and
  then quit. Both are fixed together.
- **A new connect clears the terminal pane.** Without this, a fresh
  connection's output scrolled in below whatever the last, unrelated station
  sent, reading as one continuous conversation when it was two.
- **The manual Clear key (Ctrl+L) is shown in the footer.** It already
  existed but was marked `show=False` under the same reasoning that hides
  the tab-switching keys (the tab bar already shows those) -- Clear has no
  such twin on screen anywhere, so hiding it just made it undiscoverable.

### Answered, no change needed
- **Connecting via a digipeater is already supported**: `CALL via DIGI1,DIGI2`
  in the Connect dialog or address book (`kissterm.ax25.parse_path`) builds
  an `AX25Path` with the repeaters in it, threaded through unchanged from
  `AX25Station._path_to` into every frame `AX25Link` sends. kissterm does not
  act as a digipeater itself (out of scope -- see AGENTS.md's scope
  boundary) and does not need to: any real digipeater on frequency does the
  repeating, the same as it would for a hardware TNC. Unverified against a
  real physical digipeater, same caveat as modulo-128 -- worth confirming on
  the next on-air test.

**Files:** `kissterm/addressbook.py`, `kissterm/ax25/station.py`,
`kissterm/ui/app.py`, `kissterm/ui/dialogs.py`, `kissterm/ui/settings_pane.py`,
`kissterm/ui/styles.py`, `kissterm/__main__.py`, `AGENTS.md`,
`docs/ROADMAP.md`, `tests/unit/test_addressbook.py`,
`tests/unit/test_station_rebind_transport.py`, `tests/pilot/test_app_mounts.py`,
`tests/pilot/test_settings.py`

## [2026-09-05] — Ctrl+D can now stop a stuck connect

From the same on-air test session, after the subnet fix below. Mistyped the
target and had to wait out the full SABM retry budget: Ctrl+D checked only
`self.link`, which is not bound until a connect *succeeds*, so it answered
"Not connected" -- true, and useless, while the radio kept keying up on its
own. Also folded in: a "Test selected" result that read like a paragraph
where the operator wanted OK or FAILED, and a connect dialog whose history
list blended into the background and whose hint text was clipped at the box
edge.

### Fixes
- **Ctrl+D cancels an in-flight connect**, not just an established one.
  `AX25Station.connect` registers the link before it awaits anything, so
  `KissTermApp._connect_target` (set for exactly the SABM/retry window) can
  find it and call `link.close(reason=...)`, which stops the retry timer at
  once and sends nothing further -- there was never a UA, so there is nothing
  for a DISC to end. The cancelled attempt is reported as "cancelled", not
  run through the "no answer" wording meant for a genuine timeout.
- **"Test selected" prints one line: OK, FAILED, or UNKNOWN**, plus the short
  reason, instead of the multi-sentence explanation written for the scan
  results list. That explanation stays where a first-time operator needs it
  (`discovery.Identity.summary`); this button's audience already asked a
  specific transport a direct question.
- **The connect dialog's history list is visibly a list.** It had no border
  and the same background as the dialog around it, so a first-time operator
  could not tell it apart from decoration. It now has a border and a "Recent
  stations" title, shown only when there is history to show.
- **The connect dialog's hint text no longer clips at the box edge.** A
  `Label`'s default width sizes to fit its content on one line; inside a
  fixed-width box that is what "cut off" looks like. Fixed with `width: 100%`
  so it wraps instead.

**Files:** `kissterm/ax25/session.py`, `kissterm/ui/app.py`,
`kissterm/ui/settings_pane.py`, `kissterm/ui/dialogs.py`,
`kissterm/ui/styles.py`, `tests/pilot/test_transmit_gate.py`,
`tests/pilot/test_settings.py`

## [2026-09-05] — The scan was only looking at a sixth of the subnet

Asked after a rescan still failed to find a known-good station: "I know the
radio room is running KISS and AGWPE at 10.6.26.128. Are we not scanning the
whole subnet?" It was not. Measured on the real network: **43 of 254
addresses, 17% of the planned probes, giving up at `.43`** -- and reporting
that as a finished scan.

### Fixes
- **The sweep now finishes.** A /24 across the well-known ports is ~1300
  attempts; it ran 64 at a time with a 0.75 s per-attempt timeout inside a
  3 s budget, which is about 21 seconds of work in a 3 second window. Now 256
  in flight at 0.5 s each with a 12 s budget: a full /24 in **6.8 seconds**,
  all 254 addresses, on the network where this was found.
- **Ports are the outer loop, hosts the inner one.** Every host is probed on
  8001 before any host is probed on 8300, so a sweep that does run short
  degrades to "all hosts, fewer ports" instead of "the first forty hosts,
  every port". The old order is why a TNC at `.128` was invisible while a web
  server at `.3` was offered as a transport.
- **A truncated sweep says so.** New `ScanCoverage` reports how many probes
  and addresses were actually reached; Settings shows it, and it is logged as
  a warning. "Nothing found" and "gave up before looking" are different
  answers and the scan used to give the first when it meant the second.
  Truncation is counted in probes rather than hosts -- with ports as the
  outer loop a badly truncated sweep still touches every address on the first
  port, so counting hosts would call it complete.
- **Identification moved out of the sweep into a second phase.** It costs up
  to a second per open port, and doing it inline let a few chatty services eat
  the budget for whole ranges of the subnet.
- **VARA's data ports are no longer swept.** 8301 and 8401 are the other half
  of a two-port modem, never a device of their own -- 508 pointless
  connections per scan.

**Files:** `kissterm/discovery.py`, `kissterm/ui/settings_pane.py`,
`kissterm/__main__.py`, `tests/unit/test_scan_coverage.py`, `README.md`,
`AGENTS.md`

## [2026-09-05] — A dead TNC socket stops looking like a dead antenna

From the first real on-air attempt. The log said four SABMs went to WS1EC-15
and the operator saw "no connection" -- so the obvious reading was a marginal
RF path. It was not. The TCP socket to the TNC had gone away mid-attempt, the
fourth SABM never left the process, and nothing anywhere said so. Probing the
configured hosts afterwards found that three of the four were web servers
that a port-number-only scan had written into `config.toml`.

### New Features
- **An address book in the connect dialog.** Every confirmed target is
  remembered; typing narrows the list, Down moves into it, Enter connects,
  Delete forgets a row. Recorded on the ATTEMPT, not on success -- the
  connect that got no answer is the one about to be retried. Attempts and
  connects are counted separately, so "five attempts, never connected" stays
  visible. Stored as `addressbook.json` in the data directory rather than in
  `config.toml`: it is history, not settings, and a file the program rewrites
  on every connect is a bad place for hand-edited configuration.

### Fixes
- **A frame the transport refused is no longer logged as transmitted.**
  `send_frame` logged `TX port 0` before calling the backend, so a frame that
  raised `TransportError: not connected` appeared in the log as one that went
  on the air. It now logs after the backend accepts it, logs `TX FAILED` with
  the reason when it does not, and does not fire `on_sent` -- so a refused
  frame never reaches the monitor pane either.
- **Losing the connection to the TNC is now in the log.** `TcpKissTransport`
  recorded the reason in `self._error` and told no one. It now logs the loss,
  each reconnect, and every failed reconnect attempt.
- **The status bar shows live transport state.** It was a string captured
  once at mount, so it happily displayed a healthy TNC address while the
  socket underneath was gone. `RECONNECTING` and `DOWN` now appear there.
- **`Ctrl+N` refuses when the TNC link is down**, and says explicitly that
  this is not an RF problem, rather than spending six SABMs on a socket that
  cannot carry them. If the link drops mid-attempt the failure message says
  that too.
- Moving into the connect history with Down now highlights the first row, so
  the next Enter or Delete acts on something instead of appearing dead.

**Files:** `kissterm/addressbook.py` (new), `kissterm/ui/dialogs.py`,
`kissterm/ui/app.py`, `kissterm/ui/styles.py`, `kissterm/transport/base.py`,
`kissterm/transport/tcp_kiss.py`, `tests/unit/test_addressbook.py`,
`tests/unit/test_transport_failure_is_visible.py`,
`tests/pilot/test_app_mounts.py`, `tests/pilot/test_transmit_gate.py`,
`README.md`, `AGENTS.md`

## [2026-09-05] — The scan can now tell a TNC from a web app

Reported after a rescan: it found AGWPE but not the KISS port on one host,
"and it also found other self-hosted apps on other IPs using those ports. Is
there a way to validate that they are in fact KISS TNC ports vs web services?"
There was not -- identification was the port number and nothing else, and
every match was written straight into `config.transports`.

### New Features
- **`discovery.identify_tcp` asks a port what it is.** For AGWPE, a DataKind
  `'R'` version query -- a question for the software, with no on-air meaning
  -- which confirms the engine outright and reports its version. For anything
  else, two bare `FEND` bytes: the same probe `probe_kiss_serial` already
  used, and a KISS frame with no type byte, so there is no command for a TNC
  to act on. VARA's ports are never spoken to at all; its command channel
  takes line commands that could start a session.
- **"Test selected" in Settings (F5).** Runs that probe against a configured
  transport and says what answered. It is deliberately not a connect attempt
  to another station: "is my TNC there, and is it what the config says" is
  the question that has to be answered first, and the one an operator
  otherwise answers by connecting to a node and misreading the silence as a
  dead RF path.
- **The sweep drops ports it has disproved.** An HTTP status line, an SSH
  banner or a hang-up is not a low confidence score, it is proof -- no KISS
  or AGWPE endpoint can produce one. Those ports are no longer offered, so
  they stop being written into the transport list.

### Improvements
- Confidence for a network find is now earned: 0.95 for a confirmed TNC, 0.5
  for open-but-unconfirmed, instead of a flat 0.7 for every open port.
- `AgwpeTransport` gained public `build_request`/`parse_header` helpers and
  uses `parse_header` in its own read loop, so the 36-byte wire format has
  exactly one definition rather than a second copy in `discovery.py`.

**Note on what the probe can and cannot prove.** The negative is strong and
the positive is weak. Proving a port is *not* a TNC takes one reply. Proving
it *is* a raw KISS TNC takes a frame off the air, and KISS has no version
query, no capability exchange and no greeting -- so an idle TNC on a quiet
channel stays "unconfirmed", and the UI must never render that as a fault.

**Files:** `kissterm/discovery.py`, `kissterm/transport/agwpe.py`,
`kissterm/ui/settings_pane.py`, `tests/unit/test_identify_tcp.py`,
`tests/pilot/test_settings.py`, `README.md`, `AGENTS.md`

## [2026-09-05] — Asking to connect is asking to transmit

Three things found while getting ready for the first on-air test.

### Improvements
- **`Ctrl+N` now opens the transmit gate instead of being refused by it.**
  Reported directly: "^n request connection, but it gives me an error that
  transmit is disabled. One would assume that if I'm asking to make a
  connection, transmit would automatically be enabled." That is right, and the
  old behaviour was a dead end -- the one thing the operator wanted was the one
  thing the message would not do. The rule now: the gate stops transmissions
  the operator did NOT initiate (a timer, an incoming call); a **confirmed,
  targeted** request arms it. `Ctrl+D` too, because a DISC we refuse to send
  leaves the far station holding a session open until its own timers give up.
  A bare keystroke with no confirmation and no target still does not arm --
  the manual beacon is unchanged. Arming is never silent: a notification, a
  line in the terminal log, and the status bar.
- **Manual beacon moves to `Ctrl+Shift+B`.** `Ctrl+B` is tmux's default
  prefix, so under a multiplexer -- how a station PC in another room is
  normally reached -- the key never reached the app. Shown in the footer as
  `^B`, the same shape as `^t`/`^n`/`^d`; plain `Ctrl+B` stays bound but
  hidden, since a terminal without the enhanced keyboard protocol sends the
  same byte for both and there is no slash command for the beacon.
- **Clicking the header no longer expands it to three lines.** Textual's
  `Header` grows on click to reveal a title and subtitle; kissterm has
  neither, so the two extra rows showed nothing while pushing the tab bar,
  the panes and the scrollback down by two -- mid-session, because a click
  landed on the top row. Suppressed with `prevent_default`, not by stopping
  the event, so the command palette icon still works (asserted in the test).

**Files:** `kissterm/ui/app.py`, `kissterm/ui/clock.py`,
`tests/pilot/test_transmit_gate.py`, `tests/pilot/test_app_mounts.py`,
`README.md`, `AGENTS.md`

## [2026-09-05] — A connect gives up sooner than a live link does

Asked directly: "How many times will the application retry a connection
attempt? EasyTerm does 10, but that seems high." It was 10 here too -- the
AX.25 2.2 default -- and applied to both cases.

### New Features
- **`connect_retries` (default 5), separate from `retries` (N2, still 10).**
  One number for both is what makes the spec default feel wrong on a connect.
  Giving up early on an ESTABLISHED link throws away a real conversation over
  what may be one car passing between two antennas, so N2=10 earns its keep
  there. Giving up early on a CONNECT costs one keystroke, while each
  unanswered SABM is another transmission on a shared channel aimed at a
  station that is evidently not listening. At the default T1 of 3 s a failed
  connect is now 6 attempts over ~18 seconds instead of 11 over ~33.
  Editable in Settings (F5) and in `config.toml`.

### Improvements
- The debug log's T1 line now names which budget it is counting against, so
  `rc=3 of 5` during a connect is not read as `rc=3 of 10`.

**Files:** `kissterm/ax25/session.py`, `kissterm/config.py`,
`kissterm/__main__.py`, `kissterm/ui/settings_schema.py`,
`config.toml.example`, `tests/unit/test_ax25_link.py`, `AGENTS.md`,
`README.md`

## [2026-09-05] — Diagnostics for a link that does not come up

Prompted by a real question before a first on-air test over a marginal path:
"is there adequate logging to determine what is successful, what frames are
sent and received?" The honest answer was no, so this closes the gap.

### New Features
- **The monitor pane shows both directions.** `FrameTransport` gained an
  `on_sent` fan-out, fired for every frame that gets past the transmit gate,
  and monitor lines now carry a `>` / `<` direction marker. Until now nothing
  kissterm transmitted appeared anywhere on screen, so "the node never
  answered" and "we never actually keyed up" looked identical.
- **The monitor is fed from the transport, not from `station.on_unhandled`.**
  `AX25Station` routes a frame belonging to an open link straight to that
  link, so the UA answering our SABM -- and every frame of a live conversation
  -- never reached the monitor. The pane went quiet at exactly the moment an
  operator most wants to watch it.
- **Every frame is logged in both directions** at DEBUG, from the two choke
  points every frame must pass through (`send_frame` and `dispatch`), so a new
  backend inherits the log rather than having to remember it. A gate-blocked
  frame is logged as `TX BLOCKED`, never as sent. `--log-level debug` now
  writes a usable on-air record to
  `~/.local/state/kissterm/logs/kissterm.log`.
- **A failed connect says why.** A DM refusal ("the node heard us and said
  no") and N2 silence ("the path did not carry") are different problems at
  different ends of the station, and both used to print `*** No connection to
  <call>`. The reason and the attempt count are now shown in the terminal
  pane and in the toast, with a pointer to the Monitor tab.

### Improvements
- **`--log-level debug` no longer uncorks asyncio and Textual.** Only the
  `kissterm` logger tree takes the requested level; the root stays at
  WARNING. Otherwise the twenty frames that matter are buried under thousands
  of lines about selector events, which is the difference between a log an
  operator will read and one they will not.
- **The log opens with a header line** naming the version, callsign and
  transport, so a file mailed in is reconstructible.
- **`AX25Link.connect`'s outer timeout is a backstop again, not a
  competitor.** It fired at exactly the same moment as N2 exhaustion, so it
  sometimes replaced the state machine's own verdict ("no answer from
  WS1EC-15 after 11 tries") with a bare "connect timed out". It now allows one
  extra T1 of slack.
- `AX25Link.last_error` records why a link failed, and
  `AX25Station.link_to()` reaches a link after a failed `connect` returned
  None -- the UI can no longer only be told that something went wrong.

**Files:** `kissterm/transport/base.py`, `kissterm/monitor.py`,
`kissterm/ui/app.py`, `kissterm/ax25/session.py`, `kissterm/ax25/station.py`,
`kissterm/__main__.py`, `tests/unit/test_frame_logging.py` (new),
`tests/pilot/test_monitor_sees_both_directions.py` (new),
`tests/unit/test_ax25_link.py`, `AGENTS.md`, `README.md`

## [2026-09-06] — Fix: the first run could not open the transport it just wrote

Reported from a real first run on 0.1.16. The wizard found the TNC, wrote a
correct-looking config, and then:

    Could not open transport '10.6.26.5:8001':
    TcpKissTransport.__init__() got an unexpected keyword argument 'name'

### Fixed
- **`build_transport` forwarded the config entry's `name` into the
  constructor.** `name` is the operator's label for the entry -- what
  `active_transport` matches on and what the status bar shows -- and no
  transport's `__init__` takes it. Every entry discovery writes carries it, so
  **no wizard-configured transport of any kind could be opened**: not serial,
  not TCP, not Bluetooth. `_ENTRY_ONLY_KEYS` now names the entry-level keys
  that get stripped; everything else is still forwarded, so a typo in a real
  setting still fails loudly rather than being silently ignored. The entry's
  `name` now also wins over the class-derived one, so the config and the
  status bar cannot disagree about which transport is in use.
- **`--doctor` had its own dispatch table, and that is why this shipped.** It
  picked constructor arguments by hand, so it exercised a path the app never
  took and reported the broken config perfectly healthy. It now delegates to
  `build_transport`. A diagnostic that does not exercise the real path is
  worse than no diagnostic, because it is believed.
- **The setup wizard now builds the transport it is about to save**, and
  refuses to print "Saved" if that fails. It is the last point where the
  operator is still sitting there to be told something is wrong.
- **Discovery reported the right service and then wrote the wrong kind.**
  Every TCP find became `kind = "tcp"`, so accepting the AGWPE entry the scan
  offered would have configured a *raw KISS* transport pointed at an AGWPE
  engine -- two framings on one socket, which decodes as garbage rather than
  failing cleanly. Port 8000 now maps to `agwpe`.
- **VARA ports are no longer offered as configurable finds.** `VaraTransport`
  needs a callsign and two ports, neither of which a port scan knows, so a
  VARA command port is reported as found with a note to configure it by hand,
  and a VARA *data* port is no longer listed as a device of its own -- it is
  the other half of the same modem, not a second thing to connect to.

### Why no test caught it
Nothing exercised `build_transport` against an entry the wizard actually
produces. `tests/unit/test_transport_factory.py` now does, for every kind,
plus a static check that walks `discovery.py` and asserts every key it writes
is either an entry-level key `build_transport` strips or a real parameter of
that kind's `__init__`. Reintroducing the original one-word bug fails 17 of
its tests.

**Files:** new `tests/unit/test_transport_factory.py`; changed
`kissterm/transport/__init__.py`, `kissterm/doctor.py`,
`kissterm/discovery.py`, `kissterm/__main__.py`, `AGENTS.md`.

---

## [2026-09-05] — A master transmit switch, and a manual beacon key

Requested: handle the "does not transmit at startup" problem the way other
amateur software does -- an Enable Tx switch like WSJT-X, and a manual beacon
button like JS8Call's heartbeat, both on control keys. That is a better answer
than the previous one, which was a rule ("the timer sleeps a full interval
first") rather than a control the operator can see and press.

### New Features

**`Ctrl+T` -- the master transmit gate** (`kissterm/tx.py`). Closed on launch:
with it closed **nothing** kissterm does can key a radio -- not a beacon, not
answering a call, not connecting, not the terminal send line. The status bar
reads `TX OFF`, with a count of what the closed gate has held, for as long as
that is true.

The part that makes it a guarantee rather than a checkbox is where it lives.
`FrameTransport.send_frame` is now **concrete** and calls a new abstract
`_send_frame`, so the gate check sits in the single place every frame passes
through, whatever produced it -- a pane, a timer, the AX.25 state machine, a
background task, or a backend nobody has written yet. `Session.send` gates the
session tier the same way, because a VARA or Mercury link never produces an
`AX25Frame` and gating only the frame tier would leave every HF modem open. A
test fails if any subclass overrides the public `send_frame`.

A blocked transmission returns normally and is counted, never raised: AX.25
retransmission runs on `call_later` callbacks with nowhere for an exception to
go, and the house rule is that a background task never dies of one. The checks
in the panes and the connect action exist only so the operator is told *why*
nothing happened -- connecting is refused up front rather than after the full
retry budget, which would look like the far station simply not being there.

`Config.tx_armed_at_start` (default false) is the opt-out for a station meant
to run unattended, where a restart quietly taking it off the air is the worse
failure.

**`Ctrl+B` -- send one beacon now.** The timed beacon still waits a full
interval before its first transmission, because launching the app is not a
request to key the radio; this is how the operator says "yes it is, right now"
without shortening the interval or waiting it out, the role JS8Call's
heartbeat button plays. It does not enable the timer and does not need the
timer to be on -- it waives exactly one check, whether the *timer* is enabled,
and nothing else. A closed gate, empty text or a bad destination still refuse.

### Fixed
- **A beacon suppressed by the gate was reported as sent.** The transport
  drops a gated frame silently, so `Beaconer.send_once` returned True and the
  terminal pane logged "Beacon sent" for a frame that never left. `problem()`
  now treats a closed gate as a reason not to beacon. Telling an operator
  something went on the air when nothing did is the one lie a transmit
  indicator must not tell.
- Enabling transmit re-arms a configured beacon, so `Ctrl+T` is enough on its
  own -- otherwise the timer sat running in front of a closed gate, deciding
  every interval to do nothing.
- An incoming call that arrives while transmit is disabled now says so in the
  terminal pane and as a notification. The UA never went out, so the caller is
  talking to nobody, and "somebody called and you could not answer" is exactly
  what an operator wants to find in the scrollback later.
- The README screenshot showed a connected session above a `TX OFF` status
  bar -- a state that cannot occur, teaching the wrong thing about the gate.
  The screenshot fixture arms transmit.

**Files:** new `kissterm/tx.py`, `tests/unit/test_tx_gate.py`,
`tests/pilot/test_transmit_gate.py`; changed `kissterm/transport/base.py`
(concrete `send_frame`, abstract `_send_frame`), `kissterm/transport/agwpe.py`,
`bluetooth.py`, `serial_kiss.py`, `tcp_kiss.py`, `tests/loopback.py` (renamed
to `_send_frame`), `kissterm/beacon.py`, `kissterm/config.py`,
`kissterm/ui/app.py`, `kissterm/ui/terminal_pane.py`,
`kissterm/ui/settings_schema.py`, `scripts/generate_screenshot.py`,
`config.toml.example`, `README.md`, `AGENTS.md`,
`kissterm/transport/AGENTS.md`, and the pilot test helpers.

**Tests:** 369 passing.

---

## [2026-09-05] — Beacons, session transcripts, and remote colour

Three roadmap items built and tested: P9's beacon text, P2's per-session
transcripts, and P2's ANSI-from-remote allowlist. Nothing here has touched a
radio -- P1's hardware verification still outranks everything.

### New Features

**Plain-text beacons (BTEXT)** -- `kissterm/beacon.py`. A short text
transmitted on a timer to an unconnected destination, the oldest convention in
packet for telling a channel you exist.

It is **not** APRS beaconing, and the code, the config and the Settings pane
all say so out loud, because conflating them would put a transmission on the
air the operator did not intend, under their own callsign. Separate
`[beacon]` table, separate section in Settings whose note begins "NOT APRS",
and a test asserting the two enable switches cannot end up sharing a label.

Everything about it follows from "this is unattended transmission":

- Off by default, and silent while `text` is empty whatever `enabled` says --
  an empty beacon is pure channel occupancy.
- **The 10-minute interval floor is enforced in code, twice**: the config
  loader clamps it with a warning, and `Beaconer.interval_seconds` clamps it
  again, because a `Config` built in code bypasses the loader and the floor
  is a courtesy to everyone else on the frequency rather than a preference of
  the operator's.
- The first transmission is one full interval after start, **never at
  startup**. An operator who opens kissterm to check something and quits must
  not have keyed the radio.
- `problem()` is re-checked at send time, not only at start, so text deleted
  under a running beaconer stops going out.
- Every beacon is written into the terminal pane, and `BEACON` sits in the
  status bar for as long as one is armed -- the same honesty rule as
  `ANSWERING`.
- Settings shows what the chosen interval actually costs: "about 2 seconds of
  channel every 10 minutes -- 0.4% of the frequency", from the existing
  airtime estimator.

**Session transcripts** -- `kissterm/session_log.py`, on by default. One
plain-text file per connection under the log directory: everything sent,
everything received, and every link-state change, timestamped, with `>`/`<`/`*`
direction markers so a bare file is readable years later without the code.
The path is printed into the terminal pane when a session starts, because a
file appearing on disk unannounced is a surprise.

A transcript is a convenience and a live link is not, so every write catches
`OSError` and degrades to a silent no-op with the reason kept in `failed`. A
pilot test connects with the log directory deliberately unusable and asserts
the link keeps working. Filenames are *constructed* -- both callsigns are
reduced to `[A-Za-z0-9-]`, capped at 12 characters, `UNKNOWN` if empty --
because `peer` is a callsign asserted by a remote station and a callsign is a
claim, not an identity. Transcripts get fully stripped text, not the coloured
form: `cat` on a log file would run whatever escapes it contained.

**Remote ANSI colour, through an allowlist** -- `kissterm/ansi.py`. A packet
BBS that has painted its menus in colour since 1988 rendered as flat grey,
because `monitor.sanitize` removes every escape sequence. It still does
everywhere text is matched, filtered or logged; the terminal pane now has a
second filter that keeps SGR and nothing else.

Written as an allowlist, not a denylist: the set of sequences a terminal
understands is large and undocumented in practice, and the set that can only
change how a glyph is painted is small enough to enumerate. So colour, bold,
dim, italic, underline, reverse, strikethrough and the 256-colour/truecolour
forms survive; cursor movement, erase, scroll regions, OSC (window title,
clipboard, and OSC 8 hyperlinks -- which are precisely a way to display one
address and open another), DCS, APC, PM, SOS, charset selection and the
terminal *query* sequences whose replies a shell later reads as keystrokes do
not. Anything unrecognised is removed by construction rather than by having
been thought of, which is the property a denylist cannot have.

Three details that are the difference between this working and looking like
it works:

- **A dropped sequence is consumed whole.** Removing the ESC and leaving
  `[2J` behind as literal text is how this class of filter usually fails.
- **An SGR whose every parameter was rejected vanishes**, rather than becoming
  `CSI m` -- which is a reset the sender never asked for.
- **Blink (5, 6) and conceal (8) are not allowlisted.** Photosensitivity is a
  real accessibility hazard and no remote station gets to impose it; text that
  renders invisible is a spoofing primitive, not a formatting choice.

`remote_color = true` by default, and turning it off changes readability, not
safety -- the dangerous sequences are removed on both paths.

### Improvements
- The status bar shows `BEACON` alongside `ANSWERING`.
- `apply_runtime_settings()` on the app is one generic hook the Settings pane
  calls after a save, so adding a setting that needs *doing* rather than
  storing stays "one entry in the schema".

### Fixed
- **`config.toml.example` silently discarded five settings.** Everything
  documented after the `[custom_theme]` header -- `show_local_time`,
  `show_utc_time`, `clock_24h`, `show_date`, `ascii_safe` -- was being parsed
  as a *custom-theme key*, because in TOML a bare key belongs to the last
  table header above it. Anyone who copied the example got a config where
  none of the clock settings applied, and `load_config` is deliberately
  forgiving so nothing said so. The table moved below the top-level scalars,
  and two tests now guard it: the example must load with zero warnings, and
  every top-level `Config` field documented in it must actually parse as
  top-level.
- **`tests/conftest.py` documented an `asyncio_mode = "auto"` that is not
  configured.** Believing it makes a whole test file report "async def
  functions are not natively supported", which reads like a missing
  dependency rather than a missing `@pytest.mark.asyncio`.
- `SessionLog.open()` called twice would leak the first handle and write a
  second header into a live transcript.

### Roadmap hygiene
- Removed the "unattended status indicator" item from P9: the `ANSWERING`
  marker shipped in `[2026-09-04]` and the entry was stale.
- P9's "MAIL FOR" item now says explicitly that the transmit half is done and
  the remaining work is the *content*, so nobody builds a second beaconer
  beside the first.

**Files:** new `kissterm/ansi.py`, `kissterm/beacon.py`,
`kissterm/session_log.py`, `tests/unit/test_ansi.py`,
`tests/unit/test_beacon.py`, `tests/unit/test_session_log.py`,
`tests/pilot/test_transcript_and_color.py`,
`tests/pilot/test_beacon_wiring.py`; changed `kissterm/config.py`,
`kissterm/ui/app.py`, `kissterm/ui/terminal_pane.py`,
`kissterm/ui/settings_pane.py`, `kissterm/ui/settings_schema.py`,
`config.toml.example`, `tests/conftest.py`, `tests/unit/test_config.py`,
`tests/pilot/test_settings.py`, `README.md`, `AGENTS.md`,
`kissterm/ui/AGENTS.md`, `docs/ROADMAP.md`.

**Tests:** 350 passing (was 216).

---

## [2026-09-05] — Roadmap: beacons, mail-for, and a served file area

Requested: beacons with beacon text and "MAIL FOR", plus a place other
stations can download from, with a warning that uploaded content is unvetted.
Roadmapped rather than built, with the parts that are easy to get wrong
written down while they are cheap to change.

### P9 — beacons
- **Beacon text (`BTEXT`) as unproto UI frames** -- the convention for telling
  a channel you exist. Explicitly **distinct from APRS beaconing (P4)**: same
  UI-frame machinery, different destination and payload, and the two must not
  be conflated in config or UI. Off by default (unattended transmission), with
  a minimum interval enforced in code and the airtime estimator used to show
  what a chosen interval costs the channel.
- **"MAIL FOR" beacons** (the W0RLI/FBB convention). Generated at send time
  from the mailbox, never cached -- a beacon advertising already-collected
  mail sends people on a pointless connect. Never beacon an empty list; cap
  the callsign list because it is real airtime at 1200 baud; and back off per
  callsign so a station that never collects is not advertised forever.

### P10 — serving files, and the sharper point under the virus warning
The requested warning is in, and so is the thing underneath it:

**A callsign in AX.25 is a claim, not an identity.** The protocol authenticates
nothing -- any station can transmit any callsign -- so "uploaded by W1AW" is
not evidence, and a per-callsign allowlist is a convenience, never a security
control. Re-serving what other stations uploaded therefore turns the station
into an unwitting distribution point under its own callsign and licence.

- The **curated** area (files the operator deliberately placed) and the
  **received** area (files that arrived over the air) are separate, and only
  the curated one is served by default. Serving uploads is an explicit
  off-by-default opt-in, and is to be built second.
- If opted in, the warning appears at every point content moves: the Files
  tab, the listing served to a remote station, and the transfer itself --
  unvetted, unauthenticated source, scan anything executable, callsign
  unverified.
- Provenance shown without implying verification (claimed callsign, time,
  size, hash).
- **Filename display must defeat spoofing** -- `readme.txt.exe`,
  right-to-left override characters, lookalike Unicode. Names are already
  sanitized on receipt; the display needs the same care.
- Never execute, never auto-open, never preview by extension alone.

### Recorded as a cross-cutting rule
`AGENTS.md` and `DESIGN.md` now carry "a callsign is a claim, not an
identity", because it already applies today -- the heard list, the monitor
pane, APRS positions and incoming connections all show asserted callsigns.
The wording rule: observations may name a callsign plainly; anything that
reads as *attribution* says "claimed".

### Also
P9's preamble still described the answer-then-silence defect that shipped
fixed in `[2026-09-04]`; corrected, and the two completed items removed.

**Files:** `docs/ROADMAP.md`, `AGENTS.md`, `DESIGN.md`.

## [2026-09-05] — Launcher fix, and diagnostics that stop crying wolf

### Fixed
- **`scripts/kissterm-dev` broke in exactly the situation it exists for.**
  It located the repo with `dirname "$BASH_SOURCE"`, which returns the
  *symlink's* directory -- so the moment it was symlinked onto PATH (the usage
  its own comments recommend) it went looking for `~/.local/.venv` and failed.
  Now follows the symlink chain by hand; `readlink -f` is GNU-only and this
  has to work on macOS and BSD too. Verified via the symlink, directly from
  the repo, and from an unrelated working directory.
- **`--doctor` told the operator to install `bleak` to "unlock Bluetooth LE
  TNC discovery and I/O".** BLE is a marked stub that raises -- following that
  advice would install a package and leave them wondering why their TNC4 still
  does not work. Now reported as `[SKIP]` with the truth, and with no remedy
  line, because there is nothing to do.
- **`--doctor` warned about a missing `pyserial-asyncio` while
  `pyserial-asyncio-fast` was installed.** They are alternatives that
  `serial_kiss.py` tries in order, not a checklist; the warning reported a
  problem that did not exist. Collapsed into one `serial async backend` check
  that is OK when either is present. A diagnostic that cries wolf gets ignored
  at the moment it matters.

**Files:** `scripts/kissterm-dev`, `kissterm/doctor.py`,
`tests/unit/test_config.py`.

## [2026-09-05] — Clock: three independent toggles, not an enum plus a flag

### Changed
Flagged directly, and correct: the clock modelled two settings of the same
kind two different ways. `clock_source` was an either/or enum ("local" /
"utc" / "both") while the date got its own boolean beside it -- so **"show
nothing" and "show only the date" were both unreachable**, and the times could
not be turned off at all.

Local time, UTC time and the date are now **three independent toggles**
(`show_local_time`, `show_utc_time`, `show_date`). Any of the eight
combinations is reachable, including none of them for an empty title bar.
**Local time defaults to on**; UTC and the date default to off.

### Fixed by the remodelling
- **The date could belong to the wrong reading.** With both clocks shown, one
  leading date silently belongs to only one of them -- and on the nights the
  local and UTC dates disagree, that is how a log entry lands on the wrong
  day. Now: one time shown gets its own date; both times on the same date
  share one; **both times across midnight each carry their own**
  (`2026-09-05 21:30 / 2026-09-06 02:30Z`). The display widens only at the
  boundary where the ambiguity actually exists.
- With no time shown at all, the date still follows the zone being shown --
  UTC if UTC is on, otherwise local.

### Migration
A `config.toml` still carrying `clock_source` is **migrated, not ignored**
(`local` -> local only, `utc` -> UTC only, `both` -> both), with a warning
naming the new keys. Silently reverting an operator's clock to defaults
because a key was renamed is exactly the surprise `load_config` exists to
avoid. New keys win if both are present; an unrecognised legacy value falls
back to the defaults with a warning.

Also recorded in `DESIGN.md`: if two settings are the same *kind* of choice
they get the same *kind* of control, and never print one value where it could
belong to two things.

**Files:** `kissterm/ui/clock.py`, `kissterm/config.py`,
`kissterm/ui/settings_schema.py`, `config.toml.example`,
`tests/unit/{test_clock,test_config}.py`, `tests/pilot/test_theming.py`,
`DESIGN.md`, `README.md`, `scripts/generate_screenshot.py`, `assets/*.png`.

## [2026-09-05] — DESIGN.md, settings layout, configurable clock

### New Features
- **`DESIGN.md`** -- the visual and interaction schema, which did not exist
  before: color tokens and what each means, the settings column grid, the
  92-column text measure, the shape language, the F-key/Ctrl split and its
  eight-tab ceiling, text and date conventions, and how to change any of it.
  Linked from `README.md`, `AGENTS.md` and `kissterm/ui/AGENTS.md`.
- **A configurable header clock** (`kissterm/ui/clock.py`): local, UTC, or
  **both side by side**; 12- or 24-hour; optional date. Textual's own
  `HeaderClock` is local-only, 24-hour, no date, and a fixed 10 columns wide
  that a date would silently truncate -- `KissTermClock` subclasses it and
  reads `Config` instead.
  - **UTC is always marked** -- `Z` on a 24-hour clock, `UTC` on a 12-hour one
    (`7:05 PM Z` reads wrong; Z is an ISO/24-hour convention). Local time is
    unmarked, the convention a paper log already uses.
  - **`both` is not a novelty**: amateur radio logs and nets run on UTC while
    the operator lives in local time, and doing that arithmetic mid-net is how
    a log ends up an hour wrong.
  - **Dates are ISO 8601**, never locale order, and the date follows the zone
    it sits beside -- around midnight the local and UTC dates differ, and a
    date belonging to the wrong reading puts a log entry on the wrong day.
    There is a test for exactly that boundary.
- **`scripts/kissterm-dev`** -- a launcher that finds the venv itself and works
  from any directory, for symlinking onto PATH without a system-wide install.

### Changed
- **Settings layout.** Station (callsign, aliases) now opens the page, with
  Transports directly beneath it -- identity first, then the radio, then
  tuning. Previously Transports came first and the callsign was below it.
- **A real column grid**: label 26 / control 46 / apply-note 20, with controls
  at a fixed width rather than `1fr` (a control that stretches with the window
  makes the third column drift and the page lose its alignment). Help text
  hangs under the control, not the label.
- **Section headings carry a rule**, body text is capped at 92 columns, and
  rows have a blank line between them. With bold accent text alone the
  sections blurred together while scrolling, and help lines ran the full width
  of a wide terminal, where the eye loses the line start on the way back.
- **Function keys are tabs; Ctrl sequences are actions and modals.** The
  command reference moved from F6 to **Ctrl+R**, freeing the whole F-row for
  the tabs still to come. The footer now shows no function key at all, and a
  test asserts that generally rather than naming one key.

### Roadmap
- **P10 — Application tabs: Mail, Bulletins, Files**, with sub-views
  (inbox/outbox/sent/deleted; downloads/received/local browse/remote listing).
  Records the **F1-F8 ceiling** up front: five tabs exist and three are
  planned, landing exactly on it, so a ninth tab needs a different navigation
  scheme rather than a ninth function key. Also flags that bulletins are
  category-addressed with a lifetime, not just mail with a different name.

**Files:** `kissterm/ui/{clock,app,styles,settings_pane,settings_schema}.py`,
`kissterm/config.py`, `scripts/kissterm-dev`, `config.toml.example`,
`tests/unit/test_clock.py`, `tests/pilot/{test_theming,test_app_mounts,test_terminal_ux}.py`,
`DESIGN.md`, `README.md`, `AGENTS.md`, `kissterm/ui/AGENTS.md`,
`docs/ROADMAP.md`, `assets/*.png`.

## [2026-09-05] — Settings is F5; the command reference moves to F6

Flagged directly, and correctly: once F1..F4 existed as tab-switching keys,
F5 read as "the fifth tab" (Settings) by the same pattern -- but F5 was bound
to the command reference instead, a modal that is not a tab at all. The
inconsistency was mine; fixed rather than defended.

Settings is now `F5 Settings`, matching `F1 Terminal` .. `F4 APRS` exactly.
The command reference -- opened over whatever tab is active, not a tab
itself -- moved to `F6`, still well inside the F1..F8 range every terminal
delivers reliably (F9+ is where that reliability drops off). `Ctrl+5` is kept
as the unlabelled fallback alias alongside the new `F5`, same as `Ctrl+1..4`
already were for the other tabs.

**Files:** `kissterm/ui/app.py`, `tests/pilot/{test_app_mounts,test_terminal_ux}.py`,
`README.md`, `AGENTS.md`, `kissterm/ui/AGENTS.md`, `docs/ROADMAP.md`, `assets/*.png`.

## [2026-09-05] — Theming: 21 built-in themes, config file and Settings UI

Requested directly: full control over the app's colors, from both a config
file (to sync with an external theme-sync tool or dotfiles) and the Settings
UI, with a curated set of popular themes and a default of Tokyo Night.

### New Features
- **`kissterm/ui/themes.py`** curates Textual's own `BUILTIN_THEMES` into
  families: Tokyo Night, Catppuccin (Latte/Frappe/Macchiato/Mocha -- Mocha is
  Catppuccin's own darkest flavor, not a separate family, and is grouped
  accordingly), Nord, Gruvbox, Dracula, Monokai, Solarized, Rose Pine, Atom
  One, Textual's own light/dark, and `ansi-dark`/`ansi-light`. Every entry is
  verified against `textual.theme.BUILTIN_THEMES` by test -- no hex value in
  the catalog was typed in from memory.
- **`ansi-dark`/`ansi-light` render using the terminal emulator's own 16-color
  palette**, not a copied one. This is the actual "sync with my terminal
  theme" feature: there is nothing to keep matched by hand, because it isn't
  a separate palette at all.
- **`theme = "custom"`** reads an exact hex palette from a new
  `[custom_theme]` table in `config.toml` (`Config.custom_theme`, one field
  per `textual.theme.Theme` color). This is the field an external theme-sync
  tool, or values copied by hand from a terminal emulator's own color-scheme
  file, writes into. Defaults to Tokyo Night's own real values, so an
  untouched `[custom_theme]` table looks identical to Tokyo Night rather than
  a jarring default. Not yet editable field-by-field in Settings (roadmap
  P6) -- eleven raw hex inputs was more than this pass wanted to ship
  half-finished.
- **Settings -> Appearance -> Theme**, a dropdown over the same catalog,
  applying live with no restart -- every color in the app was already a
  Textual theme variable (`$primary`, `$accent`, `$background`, ...), which is
  what made this possible without touching a single rule in `styles.py`.
- **The setup wizard offers the same list** after the callsign prompt, Enter
  to keep the default, from the identical catalog Settings uses -- one theme
  list in the app, not two that could drift apart.
- **Default is Tokyo Night** -- the operator's own stated preference, not an
  arbitrary pick.

### Deliberately not done
No fabricated light variant for Tokyo Night, Nord, Gruvbox, Dracula or
Monokai: none of them ship one upstream, and guessing which hexes to flip
would be presenting an invented palette as if it were the real, recognized
theme -- exactly what this project's `# UNVERIFIED:` convention exists to
prevent. `catppuccin-latte`, `rose-pine-dawn`, and `ansi-light` are pointed to
instead as honest light-mode relatives.

### Fixed
- **A stale or hand-typo'd `theme` value in `config.toml` crashed the app the
  instant the Settings tab opened.** `Config.theme` loads any string without
  validating it against the real theme registry (that would need importing
  Textual into the config layer, which stays UI-independent on purpose);
  validation happens later, when the theme is actually applied
  (`themes.resolve_theme_id`, which falls back safely). But `render_settings`
  was setting the Settings dropdown's `Select.value` directly to that
  possibly-invalid string, and Textual's `Select` raises
  `InvalidSelectValueError` for a value outside its own options -- turning a
  cosmetic typo into a crash that took the whole session down. Fixed with
  `_set_select_value`, which falls back to the first offered choice instead;
  this protects every "choice" field in the schema, not just theme.

**Files:** `kissterm/ui/{themes,app,settings_pane,settings_schema}.py`,
`kissterm/config.py`, `kissterm/__main__.py`, `config.toml.example`,
`tests/unit/test_themes.py`, `tests/pilot/test_theming.py`, `README.md`,
`AGENTS.md`, `kissterm/ui/AGENTS.md`, `docs/ROADMAP.md`, `assets/*.png`.

## [2026-09-05] — Status bar: black to match the tab row, spread across the width

### Changed
- **Background is `$background` (near-black, ~#121212), not `$panel`
  (slate-blue, ~#242F38).** Requested directly: the status readout should look
  like the same black chrome as the tab row above the panes, not the Header
  and Footer's own shade -- measured, they were two different colors.
- **Fields are laid out in a `rich.table.Table` grid instead of joined with
  `"  |  "`.** A joined string bunches everything at the left edge and leaves
  most of a wide terminal blank. `_status_row` (`ui/app.py`) gives each field
  an equal-ratio column -- the first left-anchored, the last right-anchored,
  everything between centered -- so the row fills the available width and
  re-flows on resize without being recomputed by hand. Fields are unchanged
  (`kissterm <version>`, transport, callsign, link state when connected,
  `ANSWERING` when unattended answering is on, heard count); only the layout
  changed.

### Fixed (test infrastructure)
- Two tests read `str(widget.render())` to check the status bar's text. That
  stopped working the moment the widget started holding a `Table` instead of
  a string -- `render()` returns a Textual `Visual` wrapper, not the original
  content. Fixed by reading `widget.render_lines(region)`, the actual strips
  the terminal draws, rather than reaching into a private `Visual._renderable`
  attribute that would just break again on the next Textual upgrade.

**Files:** `kissterm/ui/{app,styles}.py`, `tests/pilot/{test_app_mounts,test_settings}.py`,
`AGENTS.md`, `kissterm/ui/AGENTS.md`, `assets/*.png`.

## [2026-09-05] — Key-first tab labels, footer above status, a flat active tab

Three follow-up UI corrections, all from direct feedback on the previous
commit's screenshot.

### Fixed
- **Label order.** `Terminal (F1)` read wrong; a keyboard accelerator is named
  before the label it triggers, like a menu (`F1 Terminal`). Same for the
  other three tabs.
- **Status bar was above the shortcut-key row, not below it.** Swapping the
  `yield` order in `compose()` had no effect, because `Footer`'s own
  `DEFAULT_CSS` sets `dock: bottom` unconditionally -- it pins itself to the
  container edge no matter where it is written. Fixed with `#bottom-bar
  Footer { dock: top; }`, which was the actual lesson here: a widget's own
  default CSS can override compose order, and it is worth checking before
  assuming reordering `yield`s will move anything.
- **The active tab "looked funny".** Textual fills the focused tab strip's
  active tab with a solid "block cursor" background by default -- a heavy
  rectangle next to the flat, rounded, unfilled panels the rest of this app
  uses. It is now bold accent-colored text plus the existing underline bar,
  nothing else.

Two tests added: one drives `App.active_bindings`/tab region geometry the way
the earlier footer-duplication test did (status bar below the footer); the
other compares an active tab's resolved background against an inactive one's,
since Textual's "transparent" composites to the ambient screen color rather
than reporting zero alpha -- an alpha check would have passed even with the
bug still present, so the comparison is the only assertion that actually
proves nothing extra is being painted.

**Files:** `kissterm/ui/{app,styles}.py`, `tests/pilot/test_app_mounts.py`,
`README.md`, `AGENTS.md`, `kissterm/ui/AGENTS.md`, `assets/*.png`.

## [2026-09-05] — UI consistency: no duplicate labels, one button style

### Fixed
- **F1-F4 were named twice on screen.** The tab bar already reads `Terminal
  Monitor Heard APRS Settings`; the Footer printed `f1 Terminal f2 Monitor f3
  Heard f4 APRS` directly below it -- the same four words in two different
  corners. The F-key hint now lives IN the tab label (`Terminal (F1)`, ...);
  the `Binding`s stay registered with `show=False` so the keys still work.
  `Settings` has no F-key (F5 is the command reference, which is not a tab and
  correctly keeps its own Footer entry, since it has nothing else to
  duplicate). A test asserts f1-f4 are absent from `App.active_bindings`
  while f5 is present, and that every tab label carries its hint.
- **The Send button looked like it belonged to a different app.** Textual's
  default `Button` has a two-tone "tall" border that reads as a raised 3D
  bezel, and `variant="primary"` filled it with a bright solid block --
  visually nothing like the flat, rounded, outlined panels used everywhere
  else (`#session-log`, `#session-input`, `#connect-box`, `#ref-box`). One
  `Button` rule now applies app-wide: a flat rounded border, no fill. Variant
  classes (`-primary`/`-error`/...) still change the border and text color, so
  Save and a destructive action still read as different -- they just no
  longer become a different *kind* of widget to do it. This reaches every
  button in the app: Connect, Cancel, Save, Reload, Scan for hardware, Forget
  selected, Close, Send.

**Files:** `kissterm/ui/{app,styles}.py`, `tests/pilot/test_app_mounts.py`,
`README.md`, `AGENTS.md`, `kissterm/ui/AGENTS.md`, `assets/*.png`.

## [2026-09-04] — Shipped command references, and a read-only terminal

### New Features
- **`kissterm/nodes/` -- command references that ship with the app.** TOML data
  in `nodes/data/`, one file per family; adding a family is data, not code.
  BPQ32/LinBPQ and TNC2-class command mode are in. `F5` opens a searchable
  reference for whatever node was detected, and picking a command **fills the
  input line without sending it**.
- **Passive node identification.** The family is inferred from the banner and
  prompt that arrive anyway -- kissterm never asks the node a question to
  identify it. Confirmed against the real BPQ32 prompt shapes (`CALL:ALIAS}`
  and `de CALL>`) from a deployed node config in the sibling bpq-apps repo.
- **An airtime estimator** (`nodes.airtime_seconds` / `describe_airtime`) that
  models framing, keyup and turnaround rather than just dividing by the baud
  rate -- the overhead is what makes small transfers expensive.
- **A Send button** beside the input, so committing a line does not require the
  keyboard, and URLs in received text are clickable.

### Correction: shipped references are primary, not fallback
An earlier version of roadmap P8 said harvesting a node's own `?` output was
"a better source than any table we ship". **That was wrong.** Measured at 1200
baud half-duplex: 512 B is ~4.7 s of channel time, 2 KB is ~18.7 s, and 8 KB is
~74.9 s -- during which nobody else on the frequency can transmit. Populating
an autocomplete list that way, automatically, on every connect, would make
kissterm the rudest client on the band. Harvesting is now roadmapped as opt-in,
once per node, cached forever, and shown with its cost first. Harvested entries
supplement the shipped ones and never replace them, because local additions are
real: the WS1EC-15 node adds CALENDAR, FORMS, WALL and a dozen more to a stock
BPQ32 via `APPLICATION` lines.

Provenance is recorded per command (`verified` / `documented` / `recalled` /
`learned`) and shown in the pane. A reference that quietly mixes documented
fact with half-remembered syntax is worse than none: the operator types it, at
1200 baud, and finds out it was wrong.

### The terminal is read-only above, deliberate below
`TerminalPane` was reworked to the shape that is both expected and safe: the
scrollback is a `RichLog` -- selectable and copyable, but not typeable-into --
and **`send_line` is the single path to the air**. Enter and the Send button
both route through it, so "what can key the transmitter?" is answerable by
reading one method; a test asserts against the source that exactly one
`link.send(` call exists in that module. `suggest()` fills the input and cannot
send, which is what makes future autocomplete safe by construction.

Links are built from already-sanitized text with the target set to the matched
substring, so a remote station cannot display one address and open another.

### Fixed
- **Footer bindings collided at ordinary terminal widths.** F1-F4 are now
  hidden from the footer -- the tab bar already shows them -- so the *action*
  bindings, which are not discoverable anywhere else, stop being truncated.
- **`nodes/data/*.toml` was not declared as package data**, so the references
  would have been absent from an installed wheel while working fine in a source
  checkout.

**Files:** `kissterm/nodes/*`, `kissterm/ui/{terminal_pane,dialogs,app,styles}.py`,
`pyproject.toml`, `tests/unit/test_nodes.py`, `tests/pilot/test_terminal_ux.py`,
`docs/ROADMAP.md`, `README.md`, `AGENTS.md`, `kissterm/ui/AGENTS.md`.

## [2026-09-04] — Answering is opt-in, and a caller is no longer met with silence

### Fixed
- **kissterm answered incoming connections and then transmitted nothing.**
  `accept_incoming` defaulted to True, so a caller got a UA and then dead
  silence, with no way to tell a working link from a broken one -- worse than
  a clean refusal. It now defaults to **False** and refuses with a DM, so the
  caller stops retrying instead of burning its full N2 budget.
- **The TOML writer corrupted any config containing a control character.**
  `_toml_escape` handled only quotes and backslashes, so a value with a
  carriage return -- and `connect_banner` is CR-separated, because packet is --
  wrote a raw CR into `config.toml` and made the whole document unparseable.
  Because `load_config()` is deliberately forgiving, the next launch then
  silently reverted **every** setting to its default: callsign, transports,
  tuned timers, all of it. A write path that can corrupt the file it just
  wrote is worse than one that raises. Now escapes the full TOML basic-string
  set plus `\uXXXX` for anything else below 0x20, with a parametrized
  round-trip test that also asserts unrelated settings survive.

### New Features
- **`Config.accept_incoming` and `Config.connect_banner`**, both editable in a
  new "Unattended operation" section of the Settings tab. Answering a call is
  transmission under the operator's callsign with nobody present, so the
  setting's help text says so plainly rather than burying it, and points at
  checking what the licence allows on the band in use.
- **A connect banner** (BPQ32 calls this CTEXT) is sent to whoever connects, so
  the link opens into something rather than silence. Kept short by default:
  every byte is airtime, and at 1200 baud a long banner is several seconds of
  channel nobody else can use.
- **`ANSWERING` in the status bar** whenever the station will answer
  unattended -- the honest counterpart to the opt-in.

`_send_banner` re-checks `accept_incoming` at the moment it transmits, even
though it only runs after a connection was accepted. Anything that keys a
transmitter checks the opt-in where the transmission happens, not only where
the decision was made.

**Files:** `kissterm/config.py`, `kissterm/ui/{settings_schema,app}.py`,
`kissterm/__main__.py`, `config.toml.example`, `tests/unit/test_config.py`,
`tests/pilot/test_settings.py`, `README.md`, `AGENTS.md`.

## [2026-09-04] — Hotplug for USB TNCs; the network is still never scanned

### New Features
- **`kissterm/hotplug.py` -- serial TNCs are noticed as they are plugged in.**
  No rescan, no restart. If the transport currently *in use* is unplugged, the
  app says so immediately rather than failing opaquely on the next frame. A
  device that appears but does not look like a TNC is logged, not toasted --
  an unrecognized serial port is more often a phone than a radio.

### Why serial is polled and the network is not
An asymmetry of four orders of magnitude, measured rather than assumed:

- `list_ports.comports()` takes **0.4 ms** and reads only the local `/sys`
  tree. The 3-second poll is a ~0.01% duty cycle and touches no other machine.
- A network sweep is 254 hosts times six well-known ports -- about **1,500 TCP
  connection attempts**. On a timer that is indistinguishable from a port
  scanner, trips intrusion detection on managed networks, and is rude on a
  club or shared link.

So the network is scanned **only when a human asks**: `--discover`, the setup
wizard, or the Settings "Scan for hardware" button. A configured TCP host that
goes away does not need scanning either -- `TcpKissTransport` already
reconnects to its known address with backoff, so re-sweeping a subnet to
rediscover an address we already have would be pure waste. Bluetooth
enumerates *paired* devices only; kissterm never initiates pairing or a BT
discovery scan.

`tests/unit/test_hotplug.py::test_hotplug_never_touches_the_network` asserts
against the module source, because the failure it guards against is someone
adding a convenience rescan later -- which would look perfectly reasonable in
a diff and be antisocial on a club network.

### Fixed
- **A test that passed alone and failed in the suite.** The hotplug fixture
  patched `sys.modules["serial.tools.list_ports"]`, but
  `from serial.tools import list_ports` resolves through the *package
  attribute* once anything has imported pyserial -- so the patch only worked
  when that test ran first. Now patches `comports` directly. Recorded in
  AGENTS.md; the same trap applies to any `from package import submodule`.

**Files:** `kissterm/hotplug.py`, `kissterm/ui/{app,settings_pane}.py`,
`tests/unit/test_hotplug.py`, `tests/pilot/test_app_mounts.py`, `README.md`,
`AGENTS.md`.

## [2026-09-04] — Everything setup asks for is now editable in-app

### New Features
- **A real Settings tab.** Callsign, alternate callsigns, which TNC or modem to
  use, AX.25 timing (paclen, sequence mode, window, retries, T1/T2/T3), APRS
  beaconing, monitor filter, ASCII-safe mode and log directory -- all editable,
  validated, and persisted. Previously the wizard asked for two things
  (callsign and transport) and the Settings tab could edit neither; the
  callsign got a dialog last commit, and the transport -- the one that breaks
  when a Direwolf host changes IP -- had no UI at all.
- **Transport management in-app.** Pick the active transport, "Scan for
  hardware" to re-run discovery without leaving the app, and forget one you no
  longer use. Forgetting the active transport promotes another rather than
  leaving `active_transport` dangling at a name that no longer exists.

### How it is built
`kissterm/ui/settings_schema.py` declares every setting -- label, kind, help
text, bounds, and when the change takes effect. `settings_pane.py` is
*generated* from that list. **Adding a config option means adding one schema
entry**, with no widget, validator or save hook to write. The first, hand-built
version of this pane was out of date with `Config` on the day it shipped, so
`tests/pilot/test_settings.py` now fails if a config field has no schema entry
and no documented reason to be excluded. Themes are the only exclusion that is
a real gap, and only because there is no theme system yet (P6).

Three behaviours worth keeping:
- **Nothing saves unless everything validates.** A partial save leaves the
  operator with some new values and some old ones and no way to tell which.
- **Every field says when it applies** -- now, next connection, or restart.
- **Link parameters do not change under an established link.** paclen, window
  and the timers were negotiated when it came up; changing them mid-conversation
  corrupts it. New links pick the new values up. There is a test for this.

### Fixed
- **Any modal open for more than a second crashed the status refresh.**
  `App.query_one` resolves against the *top* of the screen stack, so with the
  connect or callsign dialog up, the periodic refresh raised `NoMatches`
  reaching for `#status-bar`. The panes are still visible behind a modal and
  still need updating, so refreshes now address the base screen explicitly
  rather than skipping. The same accessor also absorbs shutdown, where the
  stack empties and even reading `self.screen` raises `ScreenStackError`.

**Files:** `kissterm/ui/{settings_schema,settings_pane,app,styles}.py`,
`tests/pilot/test_settings.py`, `scripts/generate_screenshot.py`, `README.md`,
`AGENTS.md`, `kissterm/ui/AGENTS.md`, `assets/screenshot-settings.png`.

## [2026-09-04] — Callsign changing, screenshots, and three invisible UI bugs

### New Features
- **Change your callsign without a restart or a wizard.** `Ctrl+K` opens a
  validated dialog (`ui/dialogs.py::CallsignScreen`); `kissterm --callsign
  W1AW-9` does it from a shell and exits. Previously the only route was
  `--setup`, which re-runs the whole first-run wizard including a multi-second
  LAN sweep, to change one string. Operators change SSID constantly -- a `-1`
  mailbox, a different SSID for portable or an emergency net, a club call for
  an event -- so this is a first-class action now.
  The change reaches the **live station**, not just the config file, so it
  takes effect on the next connect rather than the next launch; a test asserts
  the new call is what actually appears in the transmitted address field. It is
  refused while a link is up: the callsign is in every frame of an established
  conversation, and swapping it mid-session would kill the link by N2 timeout
  rather than by anything the operator could diagnose.
- **`scripts/generate_screenshot.py`** — runs the real app headless against a
  loopback with fabricated traffic and writes `assets/*.svg` and `*.png`. No
  radio, no real config directory (it calls `_isolate()` first), nothing on the
  air. README now shows the terminal, monitor and heard panes.

### Fixed
Three bugs that the entire 83-test suite passed straight over, and that
generating a screenshot exposed immediately:
- **The status bar was invisible.** It and Textual's `Footer` both docked
  bottom and resolved to the *same region* -- the Footer painted over it in
  either yield order -- so link state, frame counts and retransmit count were
  never on screen. Both now live in one bottom-docked container with an
  explicit height.
- **The status bar was blank for the first second of every launch**, because
  it was only painted by a 1-second interval. It now paints on mount.
- **The heard table was empty for up to two seconds after switching to it**,
  because its refresh both ran on an interval and skipped unless the tab was
  already active -- so the status bar could read "heard 6" beside an empty
  table. Panes fed by a periodic refresh now repaint on `TabActivated`.

All three have geometry/timing regression tests in
`tests/pilot/test_app_mounts.py`, which assert on what is actually visible
rather than on state.

- **A clean quit with a live link raised.** `__main__` exits the app and *then*
  calls `station.close()`, which fires each link's state callback into a widget
  tree that no longer exists -- `query_one` raised `NoMatches` out of a
  callback nothing was catching. Link callbacks now tolerate a torn-down UI.

**Files:** `kissterm/ui/{app,dialogs,styles,settings_pane}.py`,
`kissterm/__main__.py`, `scripts/generate_screenshot.py`,
`tests/pilot/test_app_mounts.py`, `README.md`, `AGENTS.md`,
`kissterm/ui/AGENTS.md`, `assets/`.

## [2026-09-04] — P1 complete: the state machine, the app, and a modular layout

Everything P1 asked for is in and tested. 83 tests pass, all against a software
loopback — **no part of this has touched a radio yet** (see docs/ROADMAP.md P1).

**The AX.25 connected-mode state machine** (`kissterm/ax25/session.py`) — AX.25
2.2 section 6: SABM/SABME handshake with automatic modulo-8 fallback when a
peer answers DM, I/RR/RNR/REJ/SREJ handling, T1/T2/T3, timer recovery,
go-back-N retransmission, N2 link failure, and incoming-connection handling.
`ax25/station.py` demultiplexes frames from a shared transport to the right
link and answers DM to traffic for links that do not exist.

**Two concerns pulled out of the state machine so they are separately
testable** — this is where the subtle bugs live, and they now have no event
loop or peer to hide behind:
- `ax25/window.py` — V(S)/V(R)/V(A) and every piece of modular sequence
  arithmetic. Isolating it immediately surfaced that the `k < modulo`
  invariant was only enforced one layer up in `LinkParams`: with `k == modulo`
  a full window and an empty one are indistinguishable, and the link jams
  after exactly one cycle. Now enforced in both places.
- `ax25/timers.py` — T1/T2/T3 lifecycle plus the one sync-to-async bridge, so
  a raising timer handler cannot take the app down mid-contact.

**One deliberate deviation from the 2.2 SDL**, documented at the site: RC
resets on *any* forward progress, not only on leaving timer recovery. Measured
on the loopback at 40% frame loss, strict-SDL behaviour tears the link down
mid-transfer while this carries it to completion.

**The app** (`kissterm/ui/`) — Terminal, Monitor, Heard, APRS and Settings
panes, one file each, over a single shared frame fan-out (a frame is decoded
once, in `ui/app.py`, and handed to subscribers). `kissterm/app.py` is now a
thin shim so `from kissterm.app import KissTermApp` still resolves.

**`monitor.sanitize()`** — remote payload bytes are stripped of ANSI escapes
and control characters before reaching any widget. A node's output is written
by somebody else's transmitter, and a corrupt frame off a noisy channel
produces the same screen-clearing bytes as a malicious one. Proven at the pane
boundary in `tests/pilot/test_app_mounts.py`, not just in a unit test.

**CLI** (`kissterm/__main__.py`) — `--doctor`, `--discover`, `--setup`,
`--transport`, `--connect`. Discovery found live Direwolf KISS and AGWPE ports
on a real LAN on the first run.

**Modulo 128 is now configurable.** `Config.modulo` (8 or 128) reaches
`LinkParams`, and the window ceiling scales with it instead of being hard-coded
to 7 — that hard-coding would have silently capped every extended link at a
modulo-8 window, which reads as poor throughput rather than a config bug.

**Layout for smaller models.** A deliberate constraint: each file should be
changeable without reading the rest of the repo. Every package now carries its
own short `AGENTS.md` contract (file map, local rules, how to test just that
package): `kissterm/ax25/`, `kissterm/transport/`, `kissterm/aprs/`,
`kissterm/ui/`. `aprs/parse.py` (761 lines) became seven files of at most 241;
`app.py` (353) became eight of at most 232. `ax25/session.py` (~700) stays
whole on purpose — it is one state machine, and splitting its handlers creates
a two-way dependency worse than the size.

### Fixed
- `_setup_logging` treated `log_path()` (a directory) as a file, creating a
  zero-byte file named `logs` that made every later `mkdir` fail with EEXIST —
  and made `--doctor` report the log directory as unwritable, which was true
  and baffling. `--doctor` now distinguishes "exists but is a file" from a
  permissions problem, because the remedies are completely different.
- All four frame transports caught only `AX25FrameError` around
  `AX25Frame.decode`; a malformed *address* field raises the distinct
  `AX25AddressError`, which was escaping and killing read loops on ordinary RF
  line noise.
- `kissterm/__init__.py` (which holds `__version__`) was deleted during an
  earlier refactor, turning the package into an implicit namespace package and
  making `from kissterm import __version__` fail with "unknown location".

**Files:** `kissterm/ax25/{session,station,window,timers,__init__}.py`,
`kissterm/ui/*`, `kissterm/app.py`, `kissterm/monitor.py`,
`kissterm/__main__.py`, `kissterm/__init__.py`, `kissterm/config.py`,
`kissterm/doctor.py`, `kissterm/transport/*`, `config.toml.example`,
`tests/{loopback.py,unit/*,pilot/*}`, `AGENTS.md`, `README.md`,
`kissterm/*/AGENTS.md`, `docs/ROADMAP.md`.

## [2026-09-04] — Project created — AX.25 core, KISS transports, APRS rides along

Initial scaffold. kissterm's whole reason to exist is running AX.25 connected
mode in userspace instead of leaning on the Linux kernel's AF_AX25 stack (what
linpac requires), so the first code written is the protocol layer everything
else depends on:

- **`kissterm/ax25/address.py`** — the 7-byte AX.25 address field: callsign
  shift-left encoding, the SSID/command-response/has-been-repeated bits, up to
  8 digipeaters, and `parse_path()` for typing a connect target as
  `"WS1EC-7 via W1AW-1,W1XYZ"`. Round-trips to and from the wire, tolerant of
  garbled callsigns on decode (sanitizes rather than raising, since a corrupt
  frame that still passed the modem's CRC is routine on RF).
- **`kissterm/ax25/frame.py`** — I/S/U frame encode and decode in both modulo-8
  and modulo-128, including the control-field width asymmetry between them
  (U frames stay one byte in both modes). No FCS handling here by design —
  KISS TNCs add and strip the FCS themselves.
- **`kissterm/transport/kiss.py`** — the KISS codec (FEND/FESC escaping, the
  port-in-type-byte convention), with no I/O of its own, plus an incremental
  `KissDecoder` that tolerates line noise (stray FENDs, truncated frames) by
  design rather than raising.
- **`kissterm/transport/base.py`** — the frame-transport / session-transport
  split that is the load-bearing architectural decision here: `FrameTransport`
  subclasses (KISS, AGWPE raw mode) hand whole AX.25 frames to kissterm's own
  state machine; `SessionTransport` subclasses (VARA, Mercury, kernel AX.25)
  hand back an already-connected byte stream because the modem or kernel ran
  the link layer itself. Everything above this — panes, logging, file
  transfer — talks to the tier-agnostic `Session`.
- **`kissterm/transport/serial_kiss.py`** — KISS over a local serial TNC, with
  a three-way fallback (`pyserial-asyncio-fast` → `pyserial-asyncio` → a
  thread-pumped blocking `pyserial`) so the app still runs on a Raspberry Pi
  image that only has plain pyserial installed.
- **`kissterm/transport/tcp_kiss.py`** — KISS over TCP to Direwolf, UZ7HO
  SoundModem, or BPQ32's KISS port, with reconnect-with-backoff built in so a
  restarted Direwolf or a flaky LAN link doesn't require restarting kissterm.
- **`kissterm/transport/agwpe.py`** — AGWPE raw-frame mode (DataKind `'K'`)
  against Direwolf's AGW port and UZ7HO SoundModem. Deliberately does not
  touch AGWPE's own connected-mode DataKinds (`'C'`/`'D'`/`'d'`/`'X'`/`'x'`) —
  mixing those in would mean retransmission timing and link stats come from
  AGW's engine instead of kissterm's own state machine for this one transport
  only, which is exactly the inconsistency the frame/session split exists to
  avoid.

**Stubs / not yet written:** `kissterm/ax25/session.py` (the mod-8 connected-
mode state machine — T1/T2/T3, REJ, timer recovery — is the very next piece,
see ROADMAP P1), the Textual application shell (`kissterm/__main__.py`,
`kissterm/app.py`), the APRS decoder, and every transport past KISS/AGWPE
(Bluetooth, VARA, kernel AX.25). `kissterm/__init__.py` currently carries no
`__version__` — that lands with the first real release commit so
`scripts/bump_version.py` has something to bump.

**Files:** `kissterm/ax25/address.py`, `kissterm/ax25/frame.py`,
`kissterm/transport/base.py`, `kissterm/transport/kiss.py`,
`kissterm/transport/serial_kiss.py`, `kissterm/transport/tcp_kiss.py`,
`kissterm/transport/agwpe.py`, plus repo scaffolding (`pyproject.toml`,
`LICENSE`, `.gitignore`, `scripts/bump_version.py`, `hooks/pre-commit`,
`hooks/post-merge`, `docs/ROADMAP.md`, `SETUP.md`).
