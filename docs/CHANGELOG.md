# CHANGELOG.md — kissterm

Format: keep newest at top. One entry per meaningful change, a few lines
long, with a **Files:** line. Entries from before 2026-09-22 (the P0
stabilization rewrite) are in `docs/CHANGELOG-archive.md`; read it only when
you need the history of a specific change.

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
