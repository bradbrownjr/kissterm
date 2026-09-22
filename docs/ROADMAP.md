# ROADMAP.md — kissterm

What is still open, in the order it should be done. Shipped work moves to
`CHANGELOG.md` (dated section) and is deleted from this file the same day;
nothing here is ever checked off and left in place.

## How to work this file -- read before picking anything up

These rules exist because of a failure mode found in the 2026-09-22 review
of the Codex sessions and git history: over eleven days roughly twenty new features shipped
while the same handful of terminal bugs were reported, "fixed", and reported
again. "What's next on the roadmap?" kept resolving to a new feature because
the bugs were never on the roadmap -- they lived only in chat.

1. **P0 goes first, top to bottom.** No item whose CHANGELOG entry would sit
   under "New Features" starts while P0 has an open item, unless the operator
   explicitly asks for that specific feature.
2. **A bug the operator reports from a live session goes into P0.1 the moment
   it is reported**, with the date and their words. Chat is not a tracker.
3. **Reproduce before fixing.** A fix starts with a failing test built from
   the real evidence -- bytes from the `--log-level debug` log or a saved
   transcript, or a pilot test that reproduces the geometry -- not from a
   theory about it. No reproduction, no fix: say what evidence is missing and
   ask for it.
4. **Only the operator closes a live bug.** A passing test moves it to
   `awaiting confirmation`, not to CHANGELOG. It leaves P0 when the operator
   confirms it on a real session.
5. **Two failed attempts means stop patching.** After the second "still
   broken", write a root-cause note in the item (what was assumed, what the
   evidence showed) before touching code a third time. Adding and then
   removing UI to work around a symptom is the pattern this rule stops.
6. **No key binding is added or changed except under P0.2's standard.** Once
   P0.2 lands, its allowlist test is the enforcement.
7. **Keep documentation proportionate.** A CHANGELOG entry is a few lines. A
   new AGENTS.md rule is added when the operator states one, not to narrate a
   fix. Explanations belong in the code's docstrings.

## Finish line: what 1.0 means

1.0 is a packet terminal an unfamiliar operator can install, set up, connect
to a node or BBS with, and read mail on, without hitting a known bug or a key
that does not work in their terminal. Concretely:

- P0 is empty, with every live bug confirmed fixed by the operator.
- The keyboard follows P0.2's standard, enforced by test.
- The command catalog (P0.3) covers BPQ32/LinBPQ node, BPQMail and BPQChat
  fully from published documentation, plus JNOS, TheNet/X1J and TNC2 at
  their current level.
- P7's PyPI, pipx/uv and Raspberry Pi items are done.
- Transports never verified against hardware (kernel AX.25, VARA, Mercury,
  BLE) are labelled **experimental** in Settings, `--doctor` and SETUP.md
  rather than blocking the release.

Everything from P9 on is post-1.0.

---

## P0 — Stabilize: the product that exists, working

### P0.1 Reported bugs

Status values: `open`, `fix attempted N` (N attempts, still reported
broken), `awaiting confirmation` (fix shipped, operator has not re-tested).

- [ ] **The last line of node output, usually the prompt, sits below the
  visible area.** `fix attempted 4` (0.1.179 through 0.1.182, all
  2026-09-22). First reported earlier, re-reported 2026-09-22 ("The last line
  hides out of view, often the node prompt or the next page continue/abort
  prompt, so I'm sitting and waiting for more output from the node not
  knowing it's actually waiting on me"), still present in 0.1.179, and
  confirmed not prompt-specific: "Each node may present differently."
  **Root-cause note (2026-09-22 review):** every attempt so far changed what
  happens *when a line is written* (`TerminalPane._append`: refresh the
  layout, then `scroll_end`). Nothing re-follows the bottom when the log gets
  *shorter* after the write. `WrapLog.on_resize` only updates `min_width`,
  and `RichLog.auto_scroll` acts only on `write`. Several things take rows
  from the log after output has arrived: the stacked suggestion list shipped
  the same day (`#suggestion-strip`, `height: auto`), the find bar, the
  "Last remote" and transcript-path rows that were added and then removed,
  and closing the slide-out, which changes wrap width. Any of these puts the
  last lines below the fold with no new write to bring them back. That fits
  the report exactly: it looks like waiting on the node, and pressing Enter
  "fixes" it. **Unverified hypothesis:** confirm it with a pilot test (write
  lines ending in a prompt with no newline, then show the suggestion strip,
  then assert the last line is inside the log's visible region) before
  changing code. The likely fix is general: when the log was at the bottom
  before a resize, keep it at the bottom after. Also replay a real captured
  session from the debug log to rule out a receive-side cause.
  Files: `kissterm/ui/terminal_pane.py`, `kissterm/ui/wraplog.py`.
- [ ] **Blank lines between lines of a BBS mail listing (`LM`/`LB`).**
  `awaiting confirmation`. Reported 2026-09-22 14:26, re-reported 14:44
  after the first fix; a second fix (hold a trailing CR until it is known
  whether LF follows) shipped in "Fix BBS line rendering and document
  commands". Re-test with a real `LM` of more than one page.
- [ ] **Shortcut bar keeps the previous tab's actions until the pane is
  clicked.** `awaiting confirmation`. Reported 2026-09-21 19:06 ("Going from
  Terminal to APRS keeps connect and disconnect ... until I tab or click
  within the APRS pane") and again 20:42 ("Position now wasn't shown ...
  until I clicked inside the text box"). Fixed in "Refresh APRS shortcuts on
  tab activation". P0.2 replaces this footer logic; re-test after that.
- [ ] **"Before connecting" dialog stays on screen after Connect.**
  `awaiting confirmation`. Reported 2026-09-22 15:09 and 15:20 (Address Book
  double-click). Fixed in "Dismiss radio reminder before connecting".
- [ ] **Had to turn transmit off and on again before the radio keyed.**
  `open`, not investigated. Reported 2026-09-21 20:30 after an app restart,
  the same session in which the KISS SoundModem on the other machine also
  needed a restart. The cause may be the modem, but nobody has read the
  debug log for that session to find out. Check whether `TX BLOCKED` or
  `TX FAILED` appears before the toggle.
- [ ] **"Check the Monitor" hint appears when the node is simply waiting on
  the operator.** `open`. Reported 2026-09-22 16:33. `_note_if_no_reply`
  (`kissterm/ui/app.py`) fires when a sent line gets no reply in time. If the
  reply actually arrived and was only scrolled out of view (the first bug
  above), the hint is blaming the RF path for a display bug. Re-test once the
  first item is fixed. If it still fires, decide whether it may fire at all
  while unread output exists.
- [ ] **Duplicate WXBOT replies.** `awaiting confirmation`. Reported
  2026-09-11 and again 2026-09-12 after the first fix; deduplication plus an
  extended window shipped 2026-09-12. Confirm across a few requests.
- [ ] **Toasts that report what the operator can already see.** `open`.
  Requested 2026-09-22 ("get rid of the notification pop-up that we've
  revealed or hidden something, we see what we did already"). The UI has
  107 `notify()` calls, and many of them either confirm a visible change or
  say "Open APRS to ..." for a key pressed on the wrong tab. DESIGN.md
  section 1 already says "no toast for anything that is not actionable".
  Audit every call: keep errors and transmit-related notices (the rules
  require those), remove confirmations, and make wrong-tab actions
  unavailable (P0.2) instead of explaining them after the fact.

### P0.2 Keyboard standard -- adopt one, then conform to it

**Problem.** Keys were chosen one at a time, each against the collisions
known at that moment. The NET/ROM toggle alone moved five times in one day
(Alt+G, Ctrl+Shift+G, Ctrl+Alt+G, Ctrl+Alt+G again, Ctrl+PageDown), and
each move was a new collision found by the operator on their own desktop.
Worse, the footer advertises keys that do something else in an ordinary
terminal:

| Footer shows | Actual binding | What an ordinary terminal (no kitty keyboard protocol) delivers |
|---|---|---|
| `^O` Object | Ctrl+Shift+O | Ctrl+O, which is **Transcripts** |
| `^F` SSID Filter | Ctrl+Shift+F | Ctrl+F, which is **Find** |
| `^I` Watch IS | Ctrl+Shift+I | Ctrl+I, which **is the Tab key** |
| `^Y` Files | Ctrl+Shift+Y | Ctrl+Y, which nothing is bound to |
| `^D` Disconnect | Ctrl+Shift+D | Ctrl+D, which the focused input consumes as delete-right |
| `^B` Beacon | Ctrl+Shift+B | Ctrl+B, the tmux prefix |
| (hidden) Heard tab | Ctrl+3 | Escape (xterm encodes Ctrl+3 as ESC) |
| `Ctrl+PgDn` NET/ROM | Ctrl+PageDown | Switches tabs in GNOME Terminal and xfce4-terminal |
| Position now | Ctrl+Alt+B | Commonly taken by the desktop (Ctrl+Alt+G was, per the report) |

"The terminal doesn't seem to differentiate between upper and lowercase"
(operator, 2026-09-22) was a correct diagnosis of the table above, not a
local quirk: Ctrl+Shift+letter and Ctrl+letter are the same byte unless the
terminal and every layer in between (tmux, ssh) support an enhanced keyboard
protocol.

**The standard: IBM CUA (Common User Access), as adapted to character
terminals by Turbo Vision and Midnight Commander.** It is the published
convention for keyboard-driven text UIs, and it is what an operator who has
used `mc`, a DOS-era program or a BIOS setup screen already knows. It fits
this app because its central idea is that **every command is reachable from
a menu, and shortcuts are accelerators, not the only way in**. That removes
the pressure to give every action its own chord.

The rules, in the form that goes into DESIGN.md section 5:

1. **F1 is Help** -- context help for the current tab, including its keys.
   **F10 is the menu** -- every command, grouped (Connection, Transmit,
   APRS, View, Tools), with its key shown beside it. Inside the menu, plain
   letters are the mnemonics, so no Alt chord is needed.
2. **Only terminal-safe keys may be bound.** Allowed: F1-F10, Enter, Esc,
   Tab/Shift+Tab, arrows, Home/End, PgUp/PgDn, Insert, Delete, plain
   Ctrl+letter from the budget in rule 3, and plain letters while a list
   (not a text input) has focus. **Never bound:** Ctrl+Shift+anything,
   Ctrl+digit, Ctrl+Alt+anything, Alt+anything outside the menu, Ctrl+PgUp,
   Ctrl+PgDn, Ctrl+Tab, F11, F12. Ctrl+I, M, H, [ and J are Tab, Enter,
   Backspace, Escape and LF. Ctrl+C, Z and \ are signals, Ctrl+S is
   flow control, Ctrl+B and Ctrl+A are the tmux and screen prefixes, and
   Ctrl+A, E, K, U and W are line editing in the input.
3. **At most nine global Ctrl keys**, each with a mnemonic that holds in
   other software: `Ctrl+Q` Quit, `Ctrl+N` New connection, `Ctrl+D`
   Disconnect (end-of-session in every Unix shell; bound with priority over
   the input's delete-right, which the Delete key already provides), `Ctrl+T`
   Transmit on/off, `Ctrl+F` Find, `Ctrl+L` Clear, `Ctrl+G` Side panel,
   `Ctrl+R` Command reference, `Ctrl+P` Command palette. Everything else
   (beacon now, position now, object, bulletin, gateway form, Watch IS, SSID
   filter, file transfer, NET/ROM panel, callsign, transcripts) lives in the
   F10 menu and Ctrl+P, plus a context key where rule 4 allows one.
4. **Context keys are plain keys on focused lists.** In a table or list:
   Enter is the default action, Insert is New, Delete is Delete, and any
   other action is one letter shown in the footer. In a text input, typing
   is typing: no plain-letter bindings.
5. **The footer shows only what works right now.** An action that does not
   apply on this tab or in this state is absent from the footer and disabled
   in the menu. It is not shown and then answered with a toast. Tab switches
   refresh the footer; this is the rule the stale-footer bug above breaks.
6. **What the footer prints is exactly what to press.** No `key_display`
   that names a different chord from the one bound.

**Decision needed from the operator before implementation -- the tab keys.**
CUA reserves F1 for Help, and F1 is currently the Terminal tab.
Recommended: shift the tabs up by one and fold in the reserved P10 tabs, so
the row reads the way Midnight Commander's does: `F1 Help  F2 Terminal
F3 APRS  F4 Heard  F5 Monitor  F6 Mail  F7 Bulletins  F8 Files  F9 Settings
F10 Menu`. This fits every planned tab inside the F10 ceiling. The
alternative keeps F1-F5 as they are and puts Help only on F10 > Help, which
costs CUA conformance on its most widely known key.

Work items, in order:

- [ ] Operator decides the tab-key question above; the rules go into
  DESIGN.md section 5, replacing the per-key history there.
- [ ] `tests/unit/test_key_standard.py`: walks every `BINDINGS` list in
  `kissterm/ui/` and fails on any key outside the rule 2 allowlist, any
  `key_display` that differs from the bound key, or more than nine global
  Ctrl bindings. It will fail on the current tree; that is the point.
- [ ] F10 action menu: one modal listing every action with its key, driven
  from `commands.ACTION_META` so the menu, the Ctrl+P palette and the footer
  read one registry. Disabled entries are shown dimmed with the reason.
- [ ] F1 context help screen generated from the same registry.
- [ ] Rebind to the standard: remove every Ctrl+Shift, Ctrl+Alt, Ctrl+digit
  and Alt binding and the hidden legacy fallbacks that existed only to
  paper over them; route those actions through the menu.
- [ ] Update README's key table and SETUP.md from the registry, not by hand.

### P0.3 Command knowledge: one catalog, layered by source and context

**Problem.** Command suggestions currently merge three sources that were
built at different times: node references as data
(`kissterm/nodes/data/*.toml`, 16 BPQ node commands), BBS mail helpers as
Python (`kissterm/bbs.py`, a handful of BPQMail macros), and names harvested
from a node's `?` output (`kissterm/harvested.py`, names without meanings).
They are shown together whether the operator is at a node prompt or inside
the BBS. This produces the reports "I type L and see LB, LM ... but no
explanation", "BYE is missing", "What about LD, LF, LH, LK, LL", and the
operator's rule for how to fix it: "we shouldn't rely solely on learned info
from the node, these are standard node operating systems that should be well
documented. There's no reason not to include published information in our
help and auto-complete."

**Model.**

- **Two kinds of reference, both data files with per-command provenance:**
  *node* families (BPQ32/LinBPQ, JNOS, TheNet/X1J, KA-Node, TNC2 command
  mode) and *applications* reached through a node (BPQMail, BPQChat, FBB,
  JNOS mailbox, Winlink RMS, DXSpider). Each command carries name, minimum
  abbreviation, syntax, one-line description, `source` (URL or document and
  section) and `confidence`.
- **Context is detected passively**, as family detection already is: the
  node prompt, the BBS prompt (`de CALL>`), the chat prompt. Suggestions show
  the current context's commands only. The reference screen (Ctrl+R) shows
  all of them, grouped by context.
- **Harvested names are an overlay, never a source of meaning.** A harvested
  name that matches a published command marks it "offered by this node". An
  unmatched name is listed as "offered by this node, not in the published
  reference". It never gets an invented description.
- **Every row shows its source tier** (published / verified on air /
  harvested only), so a guess can never pass for documentation.

Work items:

- [ ] Move `kissterm/bbs.py`'s macros into data
  (`kissterm/nodes/data/bpqmail.toml`) using the same schema as node
  families, with an `application` kind and its own prompt detection.
- [ ] Complete BPQMail from its published documentation -- every user
  command it documents, with minimum abbreviations, not a sample. At least
  the ones operators have already hit without a description: `LD`, `LF`,
  `LH`, `LK`, `LL`, and `B`/`BYE`. Cite the section for each; anything not
  found in the documentation is marked `recalled`, never written from
  memory as `documented`.
- [ ] Complete the BPQ32 node file the same way (currently 16 commands), and
  add BPQChat.
- [ ] Context switch in `TerminalPane` suggestions: node, application or
  unknown, from passive prompt detection. At an unknown prompt, show nothing
  rather than guess.
- [ ] Harvest overlay semantics as described above, replacing the current
  "harvested alongside" merge.

### P0.4 Documentation diet

The files agents are told to read are now too long to hold in mind, which is
how rules already written down get broken again. AGENTS.md is about 1,200
lines, CHANGELOG.md about 4,350, and this file was about 680 before this
rewrite.

- [ ] Cut AGENTS.md to rules and pointers, under about 400 lines: each rule
  stated in a sentence or two with a pointer to the code or test that
  enforces it. The history behind a rule moves to the enforcing module's
  docstring or to CHANGELOG, where it already mostly lives.
- [ ] Archive CHANGELOG sections older than the last release into
  `docs/CHANGELOG-archive.md` once 1.0 is tagged.
- [ ] DESIGN.md section 5 replaced by P0.2's standard, not added to.

---

## P3 — Transports

Not blocking 1.0 (see the finish line): each is labelled experimental until
verified. All four need an operator with the hardware or peer; none can be
closed by a coding session.

- [ ] **Linux kernel AF_AX25 against real hardware.** Needs: a
  `kissattach`/`axports` station and an authorized peer. One socket detail
  in `kissterm/transport/kernel_ax25.py` is marked `# RESEARCH:` (the
  bind/connect address tuple shape).
- [ ] **VARA HF/FM against real hardware.** Needs: a licensed VARA modem,
  radio, and peer. Command set in `vara.py` is `# UNVERIFIED:` where
  inferred.
- [ ] **Mercury HF against real hardware.** Needs: Mercury v2, radio, peer.
  Local control/data socket test passes; an ARQ contact has not been made.
- [ ] **BLE KISS (Mobilinkd-class) against real hardware.** Needs: a BLE
  TNC. Shipped 2026-09-17 against mocks only.
- [ ] **AX/IP** -- post-1.0, and only with a named use case (a node reachable
  only over AX/IP) and BPQ32's own wire-format documentation. Node-to-node
  backbone linking is not a terminal's job.

## P4 — APRS

- [ ] **GPS against physical receivers** (USB and Bluetooth `rfcomm`).
  Needs: a GPS puck. Covers fix, loss of fix, live beacon position and
  SmartBeaconing intervals.
- [ ] **Object reports heard by a real digipeater/igate.** Operator saw
  WS1EC-15 list the station but not TESTOBJ on 2026-09-21; the investigation
  (path, LinBPQ object handling, local-only delivery option) is in that
  session's CHANGELOG entries. Confirm an object appears on aprs.fi.
- [ ] **Service directory currency** -- periodic manual re-check of each
  `kissterm/aprs_services/` entry against its `source` URL. No liveness
  probe, by design.
- [ ] **Station list/map view** -- the remaining half of the original P4:
  bearing and distance per heard station, from the existing decode
  subscriber. Post-1.0.
- **Out of scope:** igate and digipeater operation. A separate tool if ever.

## P6 — UX (post-1.0)

- [ ] **Python plugin hooks** (on connect, line received, line typed) --
  instead of a macro DSL. Needs a security design before any plugin can
  transmit or touch files. Distinct from the shipped per-station auto-login
  and hop chains.
- [ ] **`textual serve` remote access** -- confirm nothing assumes a local
  TTY. Small.

## P7 — Packaging (1.0)

- [ ] **PyPI release.** Needs: owner account and a version decision.
- [ ] **`pipx` / `uv tool install`** verified against the published package
  and documented.
- [ ] **Raspberry Pi note** in SETUP.md: serial backend fallback, `dialout`
  group, GPIO UART.
- [ ] **Debian package** -- post-1.0.
- [ ] **Self-update check** against PyPI metadata, never blocking startup --
  post-1.0.

## P8 — Node references (beyond P0.3's 1.0 set)

Why references ship as data instead of being harvested: measured at 1200
baud half-duplex, a node's help costs 4.7 s (512 B) to 75 s (8 KB) of
channel time during which nobody else can transmit. See
`kissterm/nodes/reference.py` and AGENTS.md "Airtime is the scarce
resource".

- [ ] **More families:** FBB, KA-Node, DXSpider, Winlink RMS. One data file
  each, with a detection pattern specific enough never to false-match.
- [ ] **Verify against live nodes.** `recalled` entries in `bpq32.toml` and
  all of `tnc2.toml`; JNOS and TheNet/X1J are unverified. Needs: sessions
  on real nodes (JNOS reachable via a BPQ hop).
- [ ] **PBBS / AEA PK-232 mailbox family** -- three samples in the
  `bpq-apps` node-map crawl (W1KRP-1, WD1F-1, W1ZE-1). Needs more captured
  examples before a detection pattern can be trusted.

## P9 — Unattended operation: mailbox, file drop, and alerts

The answering half of this phase shipped in `[2026-09-04]` (see CHANGELOG):
`Config.accept_incoming` is opt-in and off by default, a refused call gets a
DM rather than silence, an accepted one gets a configurable connect banner,
and the status bar shows `ANSWERING` whenever the station will transmit with
nobody present. What is still open is everything the caller would *do* once
connected -- a mailbox, a file area. Plain beacons shipped in `[2026-09-05]`;
the beacon that says there is *mail waiting* still needs a mailbox behind it.

### Regulatory constraint -- read before building any of this
Auto-answering means **transmitting unattended under the operator's callsign**,
and a mailbox that accepts messages for onward delivery means **handling
third-party traffic**. Both are regulated, and the rules differ by country and
by band -- automatic control is broadly permissive above 29.5 MHz in the US but
restricted on HF, and third-party traffic depends on international agreements
with the other station's country. **These specifics need checking against the
current rules by someone qualified; do not treat this paragraph as authority.**
What follows from it for the design is not in doubt, though:

- Unattended answering is **off by default** and requires an explicit opt-in.
- The UI must make it obvious when the station will transmit unattended.
- The operator is the control operator; kissterm states that plainly in the
  setting's help text rather than burying it.
- Anything that would relay a message from one third party to another is out
  of scope for v1. A drop box that holds mail *for its own operator* is a much
  smaller regulatory question than a forwarding BBS.

### Items
Beacon text (`BTEXT`) shipped in `[2026-09-05]` -- see CHANGELOG. What remains
of the beacon work is the half that needs a mailbox behind it:

- [ ] **"MAIL FOR" beacons** -- the W0RLI/FBB convention: a station with mail
      waiting beacons the list of callsigns it is holding for, so users know
      there is a reason to connect. Content is **generated at send time from
      the mailbox**, never cached -- a beacon advertising mail that was
      already collected wastes airtime and sends people on a pointless
      connect.
      The parts that are easy to get wrong and expensive on a shared channel:
      - **Never beacon an empty list.** "MAIL FOR:" with nothing after it is
        pure channel occupancy. No mail, no beacon.
      - **Cap the list.** A long callsign list is real airtime at 1200 baud;
        truncate with a count ("...and 6 more") rather than transmitting the
        lot.
      - **Back off per callsign.** A station that never collects should not
        have its callsign beaconed every interval forever. Decay the
        repetition, and stop after some age.
      - Depends on the mailbox below existing first. The transmit side is
        already done: `kissterm/beacon.py` owns the timer, the enforced
        interval floor, the never-send-empty rule and the airtime estimate.
        This item is the *content* -- generating the callsign list, capping
        it, and the per-callsign back-off -- not another beacon. **Do not
        build a second beaconer beside the first.** Mid.

- [ ] **Auto-collect mail once a mailbox exists.** Depends on the mailbox
      item below shipping first -- once kissterm can hold mail *for its own
      operator*, it should also be able to go get mail (and bulletins)
      *from someone else's*: on hearing (or being told about) a "MAIL FOR"
      match via the passive notice above, offer to dial the advertising
      node, log in, run its list/read/download command sequence for the
      node family in question (`kissterm/nodes/` already has per-family
      command references -- see P8), and file the results locally, all
      without the operator typing the session by hand. This is a
      **connection the operator has to confirm**, same as every other
      unattended-looking action in this codebase (AGENTS.md's "Unattended
      transmission" rules) -- never auto-dial on a bare notification with no
      confirmation step, that is exactly the "bare keystroke never arms the
      gate" case applied to a whole session instead of one transmission.
      Medium-large: needs a per-family "collect" script (list, read each,
      mark read/kill, disconnect) layered on the BBS session helpers item
      above (P5), not a new parsing approach.
- [ ] **A personal mailbox on an alternate SSID** -- the `-1` convention, which
      `Config.mycall_aliases` and `AX25Station.aliases` already support at the
      protocol level. Minimal command set in the EasyTerm//W0RLI tradition:
      `H`/`?` help, `L` list, `R n` read, `S` send, `K n` kill, `B` bye. New
      `kissterm/mailbox/` package. Messages stored as plain files, because a
      mailbox whose contents can only be read by the app that wrote them is a
      bad bargain for an emergency tool. Large effort.
- [ ] **File upload and download to a drop box.** This is where the security
      work is, and it must not be hand-waved -- an unattended station accepting
      files is writing attacker-controlled bytes to disk from an unauthenticated
      RF link:
      - a single jail directory, with every path resolved and confirmed inside
        it (`Path.resolve().is_relative_to`), never string-prefix checks;
      - filenames sanitized to a strict allowlist, never trusted from the wire
        -- no separators, no `..`, no leading dots, length capped;
      - a total-size quota and a per-callsign quota, both enforced *during*
        transfer, not after, or the quota is decorative;
      - a per-callsign rate limit, so one station cannot occupy the channel;
      - **never execute, never auto-open** anything received.
      YAPP is the right transfer protocol here, and it *is* viable for kissterm
      even though the sibling `bpq-apps` repo documents it as a dead end -- that
      limitation is BPQ32's stdio terminal filter eating control characters,
      which does not apply to a native binary-transparent AX.25 link. See P5.
      Large effort.
- [ ] **Notify on incoming connection and on new mail**, same rate-limiting
      machinery. Small once the above exists.

## P10 — Application tabs: Mail, Bulletins, Files

The three tabs that turn kissterm from a terminal into a station. Each is a
front-end over machinery P9 builds (the mailbox and the file drop); this phase
is the operator-facing half, and it is worth designing the navigation before
any of it is written.

### The F-key ceiling -- raised to F10, but still finite

**Superseded pending P0.2's tab-key decision.** If the recommended CUA
layout is adopted, these tabs land on F6 Mail, F7 Bulletins, F8 Files with
F1 Help, F9 Settings and F10 Menu; the reasoning below about the F10
ceiling and F11 still holds.
Function keys are tabs; Ctrl sequences are actions and modals (see
`kissterm/ui/app.py`'s module docstring). The ceiling was originally set at
F8 (some terminals were assumed unreliable past it), but confirmed working
in practice through F10 on the terminals actually in use here, matching
Midnight Commander's long-standing F1-F10 convention. **F1..F10 is the
working ceiling; ten tabs the practical maximum.** F11 stays off-limits --
"toggle fullscreen" in enough terminal emulators and window managers that it
rarely reaches the application at all.

Five tabs exist now (F1 Terminal, F2 APRS, F3 Heard, F4 Monitor, F5
Settings), ordered by how often an operator visits them rather than by the
order they were built. Address Book briefly had its own F5 slot (bumping Settings to F6)
before it shipped as a collapsible slide-out on the Terminal pane instead --
`Ctrl+G`, see `kissterm/ui/app.py`'s module docstring and `DESIGN.md`'s
"slide-out panels" section -- which returned Settings to F5 and freed the
slot back up. The three below take **F6 Mail, F7 Bulletins, F8 Files**,
landing with **F9 and F10 spare** for whatever needs a tab next -- do not put
something on either of those that would rather be a command-palette entry or
a modal. Mail's own contact list is expected to reuse the Address-Book/APRS
slide-out recipe rather than becoming a seventh tab or a fourth copy of
"contacts".

- [ ] **Mail tab (F6)** -- personal message store, sub-views for Inbox,
      Outbox, Sent and Deleted. Reads the mailbox P9 builds; the tab is the
      view layer, not a second copy of the storage. Deleted should be a real
      recoverable folder rather than immediate destruction -- an operator who
      fat-fingers a delete on a message that arrived over a marginal HF path
      may have no way to get it re-sent. Large.
- [ ] **Bulletins tab (F7)** -- same four sub-views, but bulletins are
      broadcast-addressed rather than person-addressed, and that difference is
      not cosmetic: a bulletin is addressed to a category (`ALL`, `ARES`,
      `WX`) and typically carries a lifetime after which it should stop being
      shown or forwarded. Model the category and expiry from the start rather
      than reusing the mail schema unchanged. Large.
### Serving files to other stations -- read before building the download area

A public download area is the natural companion to the drop box, and it is
the feature with the sharpest edge in this whole roadmap.

**A callsign in AX.25 is a claim, not an identity.** There is no
authentication anywhere in the protocol: any station can transmit any
callsign. So "uploaded by W1AW" is not evidence that W1AW uploaded it, and a
per-callsign allowlist is a convenience, never a security control. Nothing in
the design may treat a callsign as proof of anything.

It follows that **re-serving what other stations uploaded turns this station
into an unwitting distribution point** for content nobody vetted, under the
operator's own callsign and licence. So:

- **The curated area and the received area are separate, and only the curated
  one is served by default.** Files the operator deliberately placed there are
  a different category from files that arrived over the air, and collapsing
  the two is the mistake to avoid. Serving the received area at all is an
  explicit, off-by-default opt-in.
- **If the operator does opt in, say so at every point content moves**: in
  the Files tab, in the listing served to a remote station, and again at
  transfer. The wording should be plain -- these files arrived from an
  unauthenticated source, nobody has checked them, scan anything executable
  before running it, and the callsign attached is unverified.
- **Show provenance without implying it is verified**: heard callsign, time,
  size, and a hash so a file can at least be compared against a copy from
  elsewhere. Label the callsign as claimed.
- **Filename display must defeat spoofing.** `readme.txt.exe`, right-to-left
  override characters, and lookalike Unicode all exist to make a file look
  like something it is not. The names are already sanitized on receipt (P9);
  the *display* needs the same care, and should show the real extension.
- **Never execute, never auto-open, never preview by extension alone.**

- [ ] **A curated public download area** the operator puts files into
      deliberately -- net documents, forms, a club roster. Served read-only.
      This is the safe default and should be built first, on its own. Mid.
- [ ] **Optionally serving the received/uploads area**, off by default, with
      the warnings above wired into the listing, the tab, and the transfer.
      Do not build this before the curated area works. Mid.
- [ ] **A hash and a claimed-source line per file**, shown locally and in the
      remote listing. Small once the areas exist.

- [ ] **Files tab (F8)** -- sub-views for Downloads (files this station
      fetched), Received (files other stations sent us, which is the P9 drop
      box and carries all of its security requirements: a resolved jail
      directory, allowlisted filenames, quotas enforced during transfer, never
      execute or auto-open), a local browser for choosing something to upload,
      and -- where the far end supports it -- a remote directory listing.
      Large.
- [ ] **Sub-view navigation within a tab.** Four sub-views per tab across
      three tabs means the F-row cannot address them; they need their own
      consistent scheme (left/right arrows, or a sub-tab strip like the
      Calendar tab in the sibling google-tui project). Pick ONE pattern and
      use it in all three, decided before the first of them is built rather
      than three times independently. Small, but blocking.
- [ ] **A shared message-list widget.** Mail and Bulletins are the same list
      of headers over different stores; Files is a list too. One widget with
      a column spec beats three that drift apart -- the same argument that
      made `settings_schema.py` worth having. Mid.

## P11 — Served-agency messaging: forms, traffic, tactical identity

Researched from Outpost Packet Message Manager (`outpostpm.org`), the
Windows application ARES/RACES/MARS teams already standardize on for
exactly this niche -- source documents: `Ics213320UG.pdf` (ICS-213
messaging), `OutpostQuickStart.pdf` (v3.7.0), and the site's own feature
list. This phase is not "catch up to Outpost" for its own sake: served
agencies (county OES, Red Cross, hospitals) expect specific, recognizable
artifacts -- a filled ICS-213, a numbered radiogram -- out of whatever
software a volunteer operator is running, and a net mixing kissterm and
Outpost stations is a real scenario this project should not make harder.
Producing a message an Outpost operator can read as the form it claims to
be (and reading one Outpost sends the same way) is the actual goal, not
merely having "a form feature" of kissterm's own invention.

**Correction to an earlier version of this section**, which claimed no
product named "PMX" existed. It does:
**OutpostPMX** (`outpostpm.org/outpostx/indexopx.php`) is the successor
suite, in public beta (`v2026.09.2-beta` as of this research) as two
programs -- **OutpostX** (messaging, functionally the replacement for
classic Outpost PM) and **OptermX** (a unified terminal covering Serial,
Telnet, and AGWPE -- the same three-transport spread kissterm's own frame
tier already covers). Written in modern Python and Qt, shipped as
stand-alone executables needing no separate Python install, storing
messages in SQLite, and -- unlike classic Outpost PM -- natively
cross-platform: Windows 10/11, Linux x86-64, Linux ARM64 (Raspberry Pi
OS), and macOS (Intel and ARM). Tested against JNOS, BPQMailChat, Winlink
CMS packet gateways, and the Kantronics PBBS family. **Forms/ICS-213
support is explicitly NOT yet in OutpostPMX either -- "ICS 213 Message
Maker" is on its own planned-additions list, same as it is here.** That
makes the forms work below a genuine opportunity, not just catch-up: a
kissterm operator on a mixed net may have working forms before an
OutpostPMX one does, not after.

- [ ] **A form template system, modeled directly on the sibling `bpq-apps`
      repo's `apps/forms.py` and `apps/forms/*.frm` -- port the design, not
      just the idea.** That app is a *working, in-use* fillable-forms system
      for a BPQ32 BBS: a `.frm` file is one JSON document (`id`, `title`,
      `version`, `description`, `fields: [...]`), each field a `name` /
      `label` / `type` / `required` / `description`, optionally
      `max_length`, `default`, `default_now` (a `strftime` pattern for
      auto-filled dates), `auto_fill: "callsign"`, and a `validate` rule
      (`callsign`, `us_zip`, `phone`, `email`, `hhmm`, `city_state`,
      `hx_code`, `nts_number` are all already implemented). Field types:
      `text`, `textarea` (terminated by typing `/EX`, matching this
      codebase's own YAPP/autobin-adjacent packet conventions), `yesno`
      (Y/N/NA), and `choice` (a numbered pick-list). This is the same
      "data, not code" pattern `kissterm/nodes/` and
      `kissterm/aprs_services/` already use in this codebase for exactly
      the same reason -- ship the form set as data, add one file per form,
      never hand-write a screen per form. `kissterm/nodes/data/ics213.frm`
      and `.../forms/ics309.frm` already exist in `bpq-apps` as a starting
      field list (ICS-309 is a communications log, not covered anywhere in
      this file before now) -- copy and adapt them rather than re-deriving
      the ICS-213 field list from Outpost's PDF guide a second time. **Do
      not port `forms.py`'s GitHub auto-download-on-every-launch
      behaviour** -- that fits a script running on someone else's BBS shell
      account with no local persistence story; it does not fit this
      project's "ship it, cache it, never fetch it automatically" rule
      already established for `nodes/` and `aprs_services/`. Ship the forms
      as static package data and let an operator drop in a custom `.frm`
      file locally, the same way a custom node reference would work.
      Depends on the P10 Mail tab existing as somewhere to compose from and
      land replies. Large.
- [ ] **ICS-213 as the first shipped form**, using the field list above:
      Incident Name, To/Position, From/Position, Subject, Message
      (free-text), Priority, and (matching Outpost's own `Ics213mm.exe`
      more closely than `bpq-apps`' flatter version) a linked Reply half
      with its own Signature/Position/Date -- one message and its reply
      share a single record, not two independent messages, and only the
      half the local operator is producing is ever editable: a received
      message's Message area is read-only, and the Reply area is editable
      only after the operator explicitly starts a reply. Medium, once the
      template system above exists.
- [ ] **Strip-mode forms (MARS/SHARES convention) -- a capability Outpost
      itself does not have, worth keeping.** `bpq-apps`' `strip.frm` and
      `fill_strip_form` handle a different shape entirely: a
      slash-separated "information request strip" (`ROSTER/CALL/NAME/
      LOCATION//`) that the operator either pastes verbatim or picks from a
      form's own built-in `template` field, then answers field-by-field,
      producing a matching `TITLE/answer1/answer2//` response strip. Worth
      its own field `type: "strip"` in the template schema (the roadmap
      item above scopes `text`/`textarea`/`yesno`/`choice`; add this as a
      fifth) rather than skipping it because Outpost has no equivalent --
      it is real, still-used net-check traffic in MARS/SHARES circles.
      Small once the template system exists.
- [ ] **Plain-text output now; PackItForms/Winlink-Express wire compatibility
      is a separate, later, lower-priority question.** `bpq-apps`'
      `format_as_bpq_message` does not attempt to match Outpost's or
      Winlink Express's PackItForms tagged-block encoding -- it renders a
      filled form as an ordinary, human-readable text message body (field:
      value pairs, or -- for NTS -- the standard radiogram layout below),
      which is readable by *any* BBS mail client, PackItForms-aware or not.
      That is the right first target here too: it is what was actually
      asked for (a forms feature in kissterm's own BBS mail client, in the
      same spirit as the never-transmit-on-selection APRS service-template
      picker already shipped -- `AprsServiceScreen`, `kissterm/ui/
      dialogs.py`), and it needs no reverse-engineering of a format neither
      this project nor `bpq-apps` has ever captured a real sample of.
      **If bit-for-bit PackItForms compatibility is wanted later** (so an
      Outpost or Winlink Express operator's client renders the message as
      a recognized form rather than plain text), that is its own future
      item and this repo's usual rule still applies: source the actual
      field-tag/delimiter format from PackItForms' own published templates
      or a captured real message before writing an encoder, and mark
      anything unconfirmed `# UNVERIFIED:`. Do not block the item above on
      it.
- [ ] **NTS / ARRL Radiogram format -- a working reference implementation
      already exists in `bpq-apps`, port it rather than re-deriving it.**
      `apps/forms.py`'s `format_nts_radiogram`, `normalize_nts_text`
      (ARRL/Winlink prosign substitution: `,`/`!`/`;` -> `X`, `?` -> `INT`,
      `&` -> `AND`, decimal points between digits -> `R`, hyphens between
      words -> `X`), `count_nts_check` (the word-count check, including the
      ARRL rule that a pure-digit group over 5 characters counts as
      `ceil(len/5)` words), and the address-block sanitizer (`#` -> `NR`,
      hyphens -> `DASH`, per NTS punctuation rules) are a complete,
      already-in-use encoder for the numbered radiogram (station of
      origin, check, place of origin, time filed, date, precedence, `BT`
      breaks, 5-word-per-line body) plus its own ARL canned-message
      catalog (`forms/arl_messages.json`, browsable by group) for the
      common boilerplate messages. This is a different, older, and
      equally-live standard from ICS-213 -- rigid fixed fields with a
      word-count integrity check, vs. free text -- and Outpost's own
      Message Settings treats it as a distinct message type for exactly
      that reason (its own "skip NTS messages that I sent" BBS retrieval
      filter). Porting working, already-field-tested Python beats
      re-deriving the ARRL rules from documentation a second time; still
      worth a real-traffic sanity check before calling it done, same as
      every other unverified-on-the-air item in this file. Medium,
      independent of the ICS-213 work above -- and with most of the actual
      research risk already retired by the existing implementation.
- [ ] **Tactical call / assignment identity.** Outpost's "Setups for
      Tactical Operations" is a distinct, well-established ARES/RACES
      convention worth its own item, not a variant of the P9 mailbox
      alt-SSID idea: an operator logs into the BBS and addresses traffic
      under an assignment name (`CUPEOC`, `K6SJC-1`) rather than their
      personal callsign, so the *assignment* keeps a stable identity across
      shift changes without every operator re-teaching the net their own
      call. This is a real station-identification question, not a cosmetic
      label: the TNC's MYCALL is set to the tactical call for BBS
      interaction, and the *actual* licensed callsign still has to be
      legally identified on the air periodically -- Outpost does this with
      a scheduled unproto transmission of the real call. **Read this
      project's own P9 regulatory-constraint note before building this** --
      the same "needs checking against current rules by someone qualified"
      caveat applies, and the periodic legal-ID transmission has to follow
      every rule this file already has for unattended transmission
      (opt-in, visible status marker, never silent, re-checked at send time
      -- `kissterm/beacon.py` is the existing pattern to copy, not
      reinvent). `Config.mycall_aliases`/`AX25Station.aliases`, already
      used for P9's alt-SSID mailbox, is the wrong precedent to reach for
      here -- that is a second *reachable* identity on the same station,
      while a tactical call is what the *primary* connect and
      mail-addressing identity resolves to until the operator changes it,
      layered on top of (not replacing) the real MYCALL the state machine
      still identifies with. Needs scoping against `ax25/session.py`'s
      handling of `mycall` before estimating size. Medium-large.
- [ ] **Message-ID numbering convention.** Outpost tags every outbound
      subject line with a short prefix (3 characters, defaulting to the
      last 3 of the callsign, or a tactical-call-derived prefix when one is
      active), a sequence number, and an optional type-suffix letter (e.g.
      `P` for Private), e.g. `6PE-2032P: Stevens Creek Dam Status` -- purely
      a subject-line convention for human traceability across relays and
      BBS forwarding, not a protocol field. Belongs in the P9/P10 mailbox
      work as a formatting rule on outgoing mail (forms and radiograms
      above need their own numbering fields regardless, per their own
      standards) rather than a new subsystem. Small once the mailbox
      exists.
- [ ] **Delivery and read receipts.** Outpost can request, and
      auto-answer, a Delivery Receipt (message was retrieved) and a Read
      Receipt (message was opened) between two Outpost stations. A useful
      mailbox feature independent of forms -- a net controller wants to
      know traffic actually reached someone, not just that it left the
      BBS. Fold into the P9/P10 mailbox item as an outgoing-message option
      and an auto-reply rule, following the same "never silently suppress,
      log what was sent" discipline as every other auto-transmission in
      this file. Small-medium once the mailbox exists.

### Adjacent nuance for the existing BBS/mailbox items above

- **Scheduled, unattended send/receive.** Outpost's most-used feature in
  practice is not manual Send/Receive -- it is a timer that connects to a
  configured BBS every N minutes (or at fixed minutes past the hour),
  sends queued outgoing mail, collects incoming mail per the retrieval
  filters below, and disconnects, entirely without the operator present.
  This is P9's existing "Auto-collect mail once a mailbox exists" item,
  specifically automated on a timer rather than triggered only by a
  "MAIL FOR" notice -- both should probably share one
  connect-and-run-the-mail-script code path. Treat it exactly like the
  beacon and answering-incoming features already in this file: **opt-in,
  an enforced minimum interval (Outpost's own floor is 1 minute, but this
  project's airtime rules argue for something closer to the beacon's
  10-minute floor for anything that holds a connected-mode session, not
  just an unproto frame), a visible status-bar marker for as long as it is
  armed, and every line of the session logged as it happens** -- an
  unattended SABM the operator did not witness is exactly the case
  AGENTS.md's "Unattended transmission" section already exists to cover;
  extend that section's rules to this case rather than writing new ones.
  Depends on P5's BBS session helpers. Medium.
- **BBS retrieval filtering, more specifically than P5 currently scopes
  it.** Outpost's per-BBS retrieval setup separates Private / NTS /
  Bulletin retrieval, can skip bulletins or NTS traffic the station itself
  originated (so a station does not re-download its own outgoing mail),
  offers three bulletin-retrieval modes (all new, a filtered keyword list
  against the BBS's `List Filtered` command, or raw custom list commands
  for BBS software -- JNOS named specifically -- whose listing commands do
  not match the common convention), and defaults to *deleting* retrieved
  private messages from the BBS (a documented real-world surprise for an
  operator who expected the BBS to double as shared storage -- keeping
  messages on the BBS after retrieval is an explicit opt-out, not the
  default). Worth folding into P5's "BBS session helpers" item as the
  concrete filter shape once that item is scoped, including which way
  kissterm's own default should go, rather than building one
  undifferentiated "get everything" collector.
