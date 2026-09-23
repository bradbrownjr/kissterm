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

**Milestone 2 -- the messaging client (P2).** kissterm's long-term shape is
OutpostPM or Winlink on Android (WoAD): the stored messages are the product,
and the terminal is one tool for getting them. Milestone 2 is reached when
Winlink and BBS mail download into their own inboxes in a folder tree, the
shipped forms can be filled in and sent, and Mail, Bulletins and Files are
the first tabs an operator sees. 1.0 stays
terminal-first so there is a stable release before that larger build starts.

Everything from P9 on comes after milestone 2.

---

## P0 — Stabilize: the product that exists, working

### P0.1 Reported bugs

Status values: `open`, `fix attempted N` (N attempts, still reported
broken), `awaiting confirmation` (fix shipped, operator has not re-tested).

- [ ] **The last line of node output, usually the prompt, never appears.**
  `awaiting confirmation` (0.1.191, 2026-09-22; five earlier attempts,
  0.1.179 through 0.1.189). Reported repeatedly ("The last line
  hides out of view, often the node prompt or the next page continue/abort
  prompt, so I'm sitting and waiting for more output from the node not
  knowing it's actually waiting on me"), and confirmed not prompt-specific:
  "Each node may present differently."
  **Cause, now measured rather than hypothesised.** The 2026-09-22 review
  guessed that every previous attempt had fixed the wrong half -- all four
  changed what happens *when a line is written* (`TerminalPane._append`), and
  nothing re-followed the bottom when the log got *shorter* after the write.
  A pilot test written before any code change confirmed it exactly: at 80x24,
  40 lines of node output ending in a prompt left `scroll_y=27` against
  `max_scroll_y=34` the moment the suggestion strip appeared -- the last seven
  lines, prompt included, below the fold with no new write left to bring them
  back. The find bar reproduces it independently (`scroll_y=27`,
  `max_scroll_y=37`), which is why the fix had to be general rather than
  written against the strip.
  **Fixed** by anchoring the scrollback (`WrapLog.on_mount` calls Textual's
  own `Widget.anchor()`): the compositor re-applies it on every arrange, so
  the resize, the strip, the find bar and the slide-out are all covered
  without any of them knowing a scrollback exists, and an operator scrolled
  back is not yanked to the bottom. Three pilot tests in
  `tests/pilot/test_terminal_ux.py` cover both directions and all three fail
  without the fix.
  **Re-tested on the air the same evening against CCEMA (WS1EC-15), and the
  symptom recurred -- from a SECOND, unrelated cause.** The anchor fix is
  sound and stays; it is simply not what produced this report. Evidence, all
  from the operator's own machine rather than a hypothesis: the session
  transcript contains the prompt (`de WS1EC>`), the debug log shows four
  I-frames of 128/128/128/53 all accepted with V(R) reaching 4, and the
  operator reports roughly thirty EMPTY rows below the last visible line. So
  every byte arrived, reached the UI layer, and the scrollback was nowhere
  near full -- nothing was below any fold, and the prompt was never written
  at all.
  **Where it actually goes.** `TerminalPane._flush_incoming` holds back
  everything after the last line terminator so a word split across a frame
  boundary does not render as a hard break mid-word. That tail is released
  only by a newline or by a 0.2s idle timer. The node's last frame ends in an
  unterminated prompt, so the prompt's entire visibility depended on that
  timer -- and the timer never ran. The screenshots prove it independently of
  the prompt: the Terminal pane shows `Emergency Communications Team` and
  `BYE<tab>- Disconnect` as single joined lines, while the Monitor shows both
  split across frames. Joined means each tail waited for the NEXT frame to
  absorb it, across a 58 second gap a 0.2s timer would have split. The one
  tail with no next frame is the prompt.
  **Confirmed by instrumentation on a second on-air run (0.1.190).** A
  diagnostic build logged every scheduling decision plus an independent
  event-loop watchdog. Result, unambiguous: `flush: Textual timer callback
  ran` appears ZERO times in the whole session, while the loop watchdog fired
  every time and reported the timer *still armed*, ending with
  `unflushed tail is b'de WS1EC>\r'`. Cause: `MessagePump.set_timer` wraps its
  callback in `call_next`, so the flush only happens if the PANE'S OWN message
  queue is drained, whereas `write_incoming` arrives by a plain method call
  from the link callback and works regardless. Nothing reproduces it under
  `run_test`, which drains those queues itself -- the real connect path
  (Ctrl+N, the Radio Reminder modal, real frames over the loopback, the
  operator's own config at their geometry) was replayed and the timer fires
  every time. That is why four earlier fixes were written against a symptom
  nobody could reproduce.
  **Fixed in two places, both measured against the real bytes.** (1) The idle
  flush is scheduled with `loop.call_later` instead of `Widget.set_timer`, so
  it no longer depends on the pane's message queue -- the event loop is the
  same one already carrying the link callback that delivered the bytes, so a
  flush cannot be starved while data is still arriving. (2) A CR that ends a
  chunk is no longer held back. It was held in case it was the first half of
  a CRLF split across two frames (a real BPQ mail-listing defect), but that
  made every CR-terminated prompt wait on the timer; the log proved the real
  tail was `b'de WS1EC>\r'`, a COMPLETE line. The line is written immediately
  now and a LF opening the next chunk is swallowed instead, which cannot
  produce a blank line or lose one. Either fix alone would have shown the
  prompt in both reported sessions; together they also cover a prompt with no
  terminator at all. Three tests in `tests/pilot/test_terminal_ux.py` replay
  the real 53-byte CCEMA frame and all fail without the fix.
  The queue problem underneath it is its own item, below.
  Files: `kissterm/ui/wraplog.py`, `kissterm/ui/terminal_pane.py`,
  `tests/pilot/test_terminal_ux.py`.
- [ ] **`TerminalPane`'s message queue does not drain on a real station.**
  `awaiting confirmation` (2026-09-23). Found 2026-09-22: a `set_timer` on
  the pane was armed repeatedly across two on-air sessions and its callback
  ran zero times. **Cause, reproduced:** the launch opens the transport
  before the app runs, so received frames were dispatched from a task with no
  active Textual app, and `Timer._tick` dies on a bare `active_app.get()`.
  `run_test` hid it because the pilot already runs inside the app's context.
  Fixed by running the frame fan-out in the app's context
  (`FrameTransport.callback_context`); `tests/pilot/test_frame_context.py`
  reproduces the real launch order. Confirm on the air with any node session.
- [ ] **The focus highlight never moves: the entry field is always orange.**
  `awaiting confirmation` (0.1.207, 2026-09-23; see CHANGELOG). Reported 2026-09-22: after clicking into the terminal's receive
  box, "the bright box border remains on the text entry field, so I type and
  wonder at first why my keystrokes aren't going into the entry field."
  Cause, read from the code: `kissterm/ui/styles.py` gives `#session-input`
  `border: round $accent` unconditionally, and `#session-log` has no focus
  rule, so the accent colour marks the widget and not the focus. **The rule,
  across the whole app, not just Terminal:** whichever pane or field has
  focus takes the `$accent` border (orange in the current theme), and
  everything else uses the standard `$primary` border. When focus leaves the
  entry field it drops back to `$primary` until it gets focus again. This
  applies to every focusable scrollback, list, table and input (the Terminal
  and APRS logs and compose boxes, the Address Book, contacts, Heard,
  Monitor and dialog fields), and keeps the ASCII-safe border variants in
  step. DESIGN.md section 2 already defines `$accent` as "the active/current
  thing", so this brings the CSS in line with the design rather than adding
  a rule. Add a pilot test that moves focus between the log and the input
  and asserts which one carries the accent border. Small.
- [ ] **Blank lines between lines of a BBS mail listing (`LM`/`LB`).**
  `awaiting confirmation`. Reported 2026-09-22 14:26, re-reported 14:44
  after the first fix; a second fix (hold a trailing CR until it is known
  whether LF follows) shipped in "Fix BBS line rendering and document
  commands". Re-test with a real `LM` of more than one page.
- [ ] **Shortcut bar keeps the previous tab's actions until the pane is
  clicked.** `awaiting confirmation`. Reported 2026-09-21 19:06 ("Going from
  Terminal to APRS keeps connect and disconnect ... until I tab or click
  within the APRS pane") and again 20:42 ("Position now wasn't shown ...
  until I clicked inside the text box"). The footer logic it broke has since
  been replaced wholesale by P0.2's registry-driven bar, which recomposes on
  tab activation and shows only what applies. Re-test.
- [ ] **"Before connecting" dialog stays on screen after Connect.**
  `awaiting confirmation`. Reported 2026-09-22 15:09 and 15:20 (Address Book
  double-click). Fixed in "Dismiss radio reminder before connecting".
- [ ] **Had to turn transmit off and on again before the radio keyed.**
  `evidence read, awaiting operator` (2026-09-23). Reported 2026-09-21 20:30
  after an app restart, the same session in which the KISS SoundModem on the
  other machine also needed a restart. **What the debug log shows:** no
  `TX BLOCKED` or `TX FAILED` all evening. After the 20:29:22 restart the
  first position report (20:29:36) was logged `TX port 0`, meaning the gate
  was open and SoundModem's socket accepted it, but it never reached APRS-IS.
  The toggle came at 20:29:46/48, and the identical frame at 20:29:51 was
  gated by WS1EC-15 two seconds later. Same pattern at 20:15:53: accepted, not
  heard; SoundModem then dropped the connection at 20:16:21 and the first
  frame after the reconnect was heard. Toggling TX cannot affect a frame the
  socket already accepted, so the evidence points downstream of kissterm
  (SoundModem, radio or RF), not at the gate. Close unless it recurs with a
  fresh log showing otherwise.
- [ ] **"Check the Monitor" hint appears when the node is simply waiting on
  the operator.** `awaiting confirmation` (2026-09-23). Reported 2026-09-22
  16:33. **Evidence (that session's transcript):** the prompt `de WS1EC>`
  arrived at 16:29:46 but was hidden by the prompt bug above, so at 16:30:19
  the operator sent an EMPTY line to prod the node; the node ACKed it and
  rightly said nothing, and the note fired 15 s later. The reply was never
  scrolled out of view -- there was none. Fixed by not arming the reply watch
  for a blank line (`log_sent`); a line with content still gets it.
- [ ] **Duplicate WXBOT replies.** `awaiting confirmation`. Reported
  2026-09-11 and again 2026-09-12 after the first fix; deduplication plus an
  extended window shipped 2026-09-12. Confirm across a few requests.
- [ ] **Toasts that report what the operator can already see.**
  `awaiting confirmation` (2026-09-23). Requested 2026-09-22 ("get rid of the
  notification pop-up that we've revealed or hidden something, we see what
  we did already"). Audited every toast that is not an error or warning:
  sixteen that confirmed a visible change are gone (saved/forgot entries in
  the Address Book, contacts and Settings lists; "Now using" a transport,
  which the status bar shows; "Cancelled connect", which the terminal log
  already says), and three now appear only when something needs acting on
  (Settings save, the transport Test button, the GPS port scan). Kept on
  purpose: every error and warning, every transmit notice (arming, beacons,
  objects -- the rules require them), events from outside (incoming
  connection, mail waiting, a new device, a watched callsign), menu toggles
  with no other visible state (APRS SSID filter, APRS beaconing), and
  results with nowhere else to show (export path, transfer complete).

### P0.2 Keyboard standard -- adopted 2026-09-22

**Shipped.** The standard is IBM CUA as Midnight Commander uses it: F1 Help,
F10 menu, every command in the menu, nine terminal-safe Ctrl keys, plain
letters only while a list has focus. It is written down in DESIGN.md section
5, generated from one table (`kissterm/ui/commands.py`'s `COMMANDS`, which
produces the bindings, the Footer, the menu, the help screen and Ctrl+P) and
enforced by `tests/unit/test_key_standard.py`. Every Ctrl+Shift, Ctrl+Alt,
Alt and Ctrl+digit binding is gone, with them the mismatched `key_display`
values, and the tabs moved to F2-F9 so Help, Menu and Settings are on their
final keys. The tab layout for milestone 2 is in DESIGN.md section 5.

Decided 2026-09-23: there is no Info tab. Monitor keeps its name; with
Mail, Bulletins and Files on F2-F4 in milestone 2, the seven tabs fit F2-F8
exactly, so nothing needs merging. README's key table is generated from the
registry (`scripts/sync_docs.py`), and `tests/unit/test_docs_keys.py` checks
every key named in README, SETUP and DESIGN.

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

- [ ] Context switch in `TerminalPane` suggestions: node, application or
  unknown, from passive prompt detection. At an unknown prompt, show nothing
  rather than guess.
- [ ] Harvest overlay semantics as described above, replacing the current
  "harvested alongside" merge.

### P0.4 The pilot suite is flaky under parallel load

- [ ] **A different test fails on each parallel run; all of them pass
  alone.** `fixed, confirming` (2026-09-23): every test listed below now
  waits on a condition (`tests/pilot/_wait.py`); remove this item after a
  few consecutive green full-suite runs. Found 2026-09-22. Observed failures so far:
  `test_a_fast_reply_does_not_wait_out_the_full_ceiling` (a real timing
  budget: "took 3.14s", asserted `< 2.0`),
  `test_bbs_helper_from_reference_reaches_compose_box_without_sending`,
  `test_footer_is_tab_and_connection_aware`,
  `test_object_scope_controls_its_rf_distribution[rf_only]`, and
  `test_tab_keys_work_while_an_input_has_focus` (`NoMatches: No nodes match
  '#heard-table'` -- a mount that had not finished). Every one passes with
  `-n0`. The common shape is a test that measures real elapsed time or reads
  a widget before its pane has mounted, running on a box with `-n auto`
  workers competing for CPU.
  **Why this is P0 and not a nuisance.** AGENTS.md already says a flake is
  the worst kind of failure because "the suite is green" stops meaning
  anything -- and this project's whole P0 exists because bugs were reported,
  "fixed" and reported again. A suite that fails somewhere different every
  run trains a reader to re-run instead of to look.
  Fix by making these tests wait on a condition rather than on wall-clock
  time (poll with a bare `asyncio.sleep` against a deadline, per AGENTS.md
  sec. 6 on `pilot.pause()` costing 100-120ms), and by awaiting the mount
  before querying. Do not "fix" it by widening the timing budgets until the
  flake hides, and do not drop `-n auto`: the parallelism is not the bug, it
  is what exposes it.

### P0.5 Documentation diet

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

## P2 — Messaging client: Mail, Bulletins, Files (milestone 2)

The model is OutpostPM and Winlink on Android (WoAD): the operator opens
kissterm to their messages, not to a prompt. The Terminal becomes one of the
tools that fills the message store, alongside Winlink and scripted BBS
sessions. Requested 2026-09-22.

Starts after P0. The BBS half depends on P0.3's per-application command
catalog, because a collection script has to know which BBS it is talking to.

### The folder tree

One on-disk store, shown as one tree in the Mail tab, with each source
getting its own branch:

```
Mail
  Winlink          Inbox  Outbox  Sent  Deleted
  BBS
    CCEMA          Inbox  Outbox  Sent  Deleted     (one per BBS account)
  Local            Inbox  Sent  Deleted             (P9's personal mailbox)
Bulletins
  CCEMA            ALL  ARES  WX  ...               (by category, with expiry)
Files
  Downloads  Attachments  Received
```

- **Plain files, one per message, in a directory tree that mirrors the UI**,
  under the platformdirs data directory. Any index is a cache rebuilt from
  the files. A mailbox only this app can read is a bad bargain for an
  emergency tool. That rule already stands in P9. Raw Winlink messages are
  kept as received (B2F) beside the parsed view, so nothing is lost to a
  parser bug.
- **Deleted is a real folder**, not destruction. A message that arrived over
  a marginal HF path may not be re-sendable.
- **Bulletins are not mail with a different header.** They are addressed to a
  category and expire, so model category and lifetime from the start.

### Items

- [ ] **Message store** (`kissterm/mail/`): folders, message files, the
  rebuildable index, move/delete/restore. No UI, no I/O beyond the data
  directory, and fully unit-tested like `ax25/`. Tests use `_isolate`.
  Medium.
- [ ] **Shared message-list widget and folder tree.** Mail, Bulletins and
  Files are the same three panes: tree, list of headers, reader. One widget
  with a column spec replaces three that would drift apart. Keys follow
  P0.2 rule 4: Enter opens the message, Insert composes, Delete moves to
  Deleted, and plain letters (R reply, F forward, S send/receive) work only
  while the list has focus. The folder tree answers the old "sub-view
  navigation" question, so there is no sub-tab strip. Medium.
- [ ] **Mail, Bulletins and Files tabs** at F2, F3 and F4, with the tab
  move from P0.2's table done in the same change. Mail becomes the launch
  tab. Large, mostly composition of the two items above.
- [ ] **Compose and Outbox.** Composing writes to the Outbox of a chosen
  account (a Winlink account or a BBS). Nothing transmits on save. Sending
  happens only when the operator starts a send/receive, which arms the gate
  through `_arm_for` exactly as Ctrl+N does. Medium.

#### Winlink

Winlink messages travel as B2F (the FBB B2 forwarding protocol: proposals,
LZHUF-compressed messages, and a challenge-response secure login) over a
byte stream. That fits the existing architecture exactly: **B2F is a
session protocol on top of whatever link is open.** It runs over an
`AX25Link` to an RMS Gateway (packet, kissterm's own state machine), a
`Session` from the VARA transport, or Telnet to the Winlink CMS, via the
same `_SessionLinkAdapter` seam the terminal uses. It needs no new transport.

Sources: Winlink's published B2F and secure-login documentation, and **Pat**
(getpat.io, github.com/la5nta/pat, with its protocol library wl2k-go). Pat
is a working open-source Winlink client and the best reference
implementation. Check its licence before porting any code, and mark
anything taken from its behaviour rather than from documentation
`# UNVERIFIED:` until a live exchange confirms it.

- [ ] **Winlink account in Settings**: callsign, and a password kept as a
  named credential (`Config.credentials`, as Address Book logins already
  are), never in plain config text if the OS keyring is available. Small.
- [ ] **B2F client** (`kissterm/winlink/`): handshake and SID exchange,
  secure login, proposal/accept, LZHUF compress and decompress, send
  Outbox, receive to Inbox, clean disconnect. Unit-tested against recorded
  exchanges. `# RESEARCH:` the exact secure-login hash and the SID flags
  from the published docs. Large.
- [ ] **CMS over Telnet first.** It is the test path that needs no radio.
  Pat's documented form is `cms.winlink.org:8772`. Confirm the host, port
  and Telnet-layer login from Winlink's own documentation. Operator-initiated
  only. Medium.
- [ ] **Packet to an RMS Gateway** using the existing Connect flow (radio
  reminder, gate arming, hop chains). Needs: a reachable RMS Gateway and a
  live session to verify. Medium.
- [ ] **VARA to an RMS Gateway**, once P3's VARA hardware verification is
  done. Small on top of the two above.
- [ ] **RMS Gateway list** for choosing where to connect, fetched from the
  Internet on request and cached, never queried over the air.
  `# RESEARCH:` whether Winlink's gateway API needs a key and on what terms.
  Medium.
- [ ] **Attachments** land in Files > Attachments, under P9's filename rules
  (sanitized, never executed, never auto-opened). Small.
- **Later:** Winlink HTML/XML forms (they meet P11's form system here),
  peer-to-peer Winlink, and scheduled send/receive. The scheduled version
  follows every unattended-transmission rule in AGENTS.md: opt-in, a status
  marker, an interval floor, and every line logged.

#### BBS mail (BPQMail first, then the other P0.3 applications)

- [ ] **BBS accounts**: an Address Book entry marked as a mail source, with
  its BBS application from the P0.3 catalog (BPQMail, FBB, JNOS mailbox),
  its hop chain and login script, and retrieval options. Small.
- [ ] **BBS send/receive**: an operator-started session that connects via
  the normal Connect flow, then runs the application's collection
  sequence from the catalog: list mine, read each new message into
  BBS/<name>/Inbox, send the Outbox, and disconnect. Every line is echoed to
  the terminal log and the transcript as it goes, as the auto-login script
  already does. It stops, and does not guess, on any reply it does not
  recognise. **Reproduce-first applies here:** the per-application
  description of where a read message starts and ends is written from
  captured real sessions (CCEMA's BPQMail first), stored as data beside the
  command catalog, and tested against those captures. Retrieval filtering
  (private, NTS or bulletins; skipping this station's own) is part of this
  item; the P11 notes below describe how Outpost does it. **Decided
  2026-09-22: messages stay on the BBS by default.** Deleting is the
  operator's choice, as it is at the node, where a message is read and
  then killed by command. Kill is an explicit per-message action (or an
  opt-in per-account setting), never a side effect of downloading.
  **Never download the same message twice:** each BBS account records
  what it has already filed, by BBS message number plus the BID/MID where
  the BBS shows one, so a later session lists new mail and reads only
  that. Winlink needs no equivalent, because the CMS delivers each
  message once. Large.
- [ ] **Bulletin collection** into Bulletins/<BBS>/<category>, using the
  same session with a category or keyword filter. Medium.

#### Forms

Decided 2026-09-22: kissterm ships every form in the sibling `bpq-apps`
repo, parity with vden's PKTNET forms (https://vden.org/pktnet/), and
Winlink's standard message forms. A filled form becomes an ordinary message
in an account's Outbox, addressed the way that form requires, and it goes
out on the next send/receive. Nothing transmits when a form is saved.

**The design is already built and in use: port it, don't re-derive it.**
`bpq-apps/apps/forms.py` and `apps/forms/*.frm` are a working forms system
on a BPQ32 BBS. A `.frm` file is one JSON document: `id`, `title`,
`version`, `description`, an optional output `format`, and `fields`. Each
field has `name`, `label`, `type`, `required` and `description`, and may
have `max_length`, `default`, `default_now` (a `strftime` pattern),
`auto_fill: "callsign"` and a `validate` rule (`callsign`, `us_zip`,
`phone`, `email`, `hhmm`, `city_state`, `hx_code`, `nts_number`). Field
types are `text`, `textarea`, `yesno`, `choice` and `strip`. Forms ship as
package data, and an operator can drop in their own `.frm` locally. **Do
not port forms.py's auto-download from GitHub on launch.** It suits a
script on someone else's BBS shell, not this project's rule that shipped
data is never fetched automatically.

| Form | Source | Output / addressing |
|---|---|---|
| ICS-213 General Message | `ics213.frm`; vden `ics213.html` | Plain text, with a linked reply half (below) |
| ICS-309 Communications Log | `ics309.frm` | Plain text |
| Net check-in | `netcheck.frm` (matches vden PACKET CHECK-IN) | `pktnet_checkin`; bulletin `SB PKTNET@USA`, subject "Name, Call, Town, State" |
| ARRL Radiogram | `radiogram.frm` + `arl_messages.json` | `nts_radiogram`; `ST <ZIP> @ NTS<STATE>` routing built from the form |
| Information strip response | `strip.frm` | Strip (`TITLE/answer1/answer2//`) |
| GYX Weather (SKYWARN) | `gyx-weather.frm` | Strip |
| Field Situation Report | `fsr.frm`; vden `fsr.html` | Plain text |
| Severe Weather Report | `severe_wx.frm`; vden `severe_wx.html` | Plain text |
| Bulletin Message | `bulletin.frm`; vden `bulletin.html` | Plain text, bulletin addressing |
| Equipment Status Report | `eqstat.frm` | Plain text |
| USGS DYFI report | `dyfi.frm` | Plain text |
| MCF720 price survey | `mcf720-price-survey.frm` | Plain text |
| Winlink standard forms | Winlink Express templates | `# RESEARCH:` below |

- [ ] **Form engine** (`kissterm/forms/`): load and validate `.frm`, the
  validators above, and the output formatters (plain, `pktnet_checkin`,
  `nts_radiogram`, strip). That includes forms.py's NTS rules: prosign
  substitution (`normalize_nts_text`), the ARRL word-count check
  (`count_nts_check`, where a pure-digit group over 5 characters counts as
  `ceil(len/5)` words), and the address-block sanitizer. **Golden-output
  tests:** the same answers through bpq-apps' forms.py and through kissterm
  must produce byte-identical messages, so two stations on one net never
  disagree about what a form looks like. Medium.
- [ ] **Form screen**: one screen generated from the schema, the same way
  the Settings pane is generated from `settings_schema.py`. It has no
  per-form code. `textarea` is a real multi-line editor here (bpq-apps'
  `/EX` terminator is a BBS-shell constraint kissterm does not have). A
  `strip` field shows the template and accepts a pasted strip. Reached from
  "New from form" in the F10 menu, and as a plain-letter key on the Mail
  list per P0.2 rule 4.
  Medium.
- [ ] **Ship every bpq-apps form** in the table above. Small once the
  engine exists: they are data.
- [ ] **vden parity check.** Compare each vden form (the local copy in the
  sibling `pktnet` directory, v1.1 from 2023-11, and the live site) field by
  field against its bpq-apps equivalent. Anything vden has that bpq-apps
  lacks is fixed in the `.frm` in both repos, not only in kissterm. Small.
- [ ] **Received forms render as forms.** A message kissterm or bpq-apps
  produced is recognised and shown in the form layout, with the raw text one
  key away. ICS-213 keeps a message and its reply in one record: the
  received half is read-only, and the reply half is editable only after the
  operator starts a reply (Outpost's `Ics213mm.exe` behaves this way).
  Medium.
- [ ] **Winlink forms.** Winlink Express's standard templates are HTML forms
  that send a readable text body plus an XML attachment
  (`RMS_Express_Form_*.xml`) that another Winlink client renders as the
  form. `# RESEARCH:` source the XML structure from Winlink's published
  Standard Templates, not from guesses. Order: first display the ones that
  arrive (the text body always works; parse the XML), then compose
  Winlink Check-In, ICS-213 and Radiogram as Winlink forms. Depends on the
  B2F client. Large.
- [ ] **PackItForms/Outpost wire compatibility**, so an Outpost or Winlink
  Express operator sees a recognised form rather than plain text. It is
  later and separate, and is sourced from PackItForms' published templates
  or a captured real message. Plain text is readable by every client and
  comes first.

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
- [ ] **Bound the remaining TCP connects.** `tcp_kiss.py` now gives up after
  `_CONNECT_TIMEOUT` (10 s) instead of waiting out the kernel's roughly
  two-minute SYN retries on a host that is down. `agwpe.py`, `telnet.py`,
  `vara.py` and `aprs_is.py` still call `asyncio.open_connection` unbounded
  and have the same blank-terminal-then-failure behaviour. Fix them the same
  way, including naming the timeout in the message (`TimeoutError`'s message
  is empty). Codeable; no hardware needed.
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

- [ ] **Collect mail when a "MAIL FOR" beacon names this station.**
      Offer (never auto-dial) to run P2's BBS send/receive against the
      advertising node. The collection itself is P2's; this item is only the
      trigger, and it must be confirmed like any other connect.
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

## P10 — Serving files to other stations

The Mail, Bulletins and Files tabs moved to P2, the messaging client. What
remains here is the server side: offering files to stations that connect to
this one. It depends on P9's drop box and on the Files tab in P2.

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

## P11 — Served-agency messaging: tactical identity, numbering, receipts

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

Forms (ICS-213, radiograms, strips, check-ins, the whole bpq-apps set,
vden and Winlink forms) moved to P2's Forms subsection, which carries
everything that was here.

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

Both notes below now feed P2's "BBS send/receive" item. Scheduled
send/receive is P2's post-milestone item; retrieval filtering belongs to
the send/receive item itself.

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

## P12 — Future idea: FSQCALL through fldigi

**Concept only, not scheduled.** Why it is here: the operator's local
emcomm team sends sitreps and small files over FSQ instead of packet,
while the ARES team they also support in the next county uses packet
and APRS. If kissterm could reach both, one operator would need only one
client for both teams.

**What FSQCALL is.** FSQ is keyboard-to-keyboard directed messaging, not a
connected mode. Every transmission starts with `sendercall:xx` (the call in
lowercase, then a CCITT CRC8 over the call and colon, as two hex digits),
followed by an addressee (a callsign, `allcall` or `cqcqcq`) and a
one-character trigger: space means chat, `?` SNR report, `$` heard list,
`#` save message/file, `;` relay, `!`/`~` repeat, `&` QTC, `@` position,
`|` alert. A header with nothing after it is a "sounding" (a beacon).
There is no link state and no ack, so it is closer to APRS messaging than
to a BBS session.

**Route.** The original FSQCALL (ZL2AFP, Windows) has no network interface.
fldigi does: XML-RPC on 7362 (`modem.set_by_name`, `text.add_tx` +
`main.tx`/`main.abort`, poll `rx.get_data`). stdlib `xmlrpc.client` is
enough, so no new dependency. fldigi's KISS port (7342) is the wrong tool:
it carries fldigi's own data frames, which an FSQCALL station cannot decode.

**Shape.** A `SessionTransport` (`transport/fldigi.py`) whose "connect" is
purely local: it picks the addressee, keys nothing, and every committed line
goes out as `<addressee> <text>` through `Session.send`, so the transmit gate
applies. Also a pure header/CRC8 parser feeding a heard list, and the
directed commands offered as fill-the-input templates that never send on
selection (the APRS service picker's rule). Manual config only: probing
XML-RPC is a real request, so it is out of bounds for discovery.

**Open questions -- settle against a running fldigi before any design work:**

- UNVERIFIED: what `rx.get_data` returns in directed mode. fldigi prints only
  traffic addressed to this station and may strip the header, which would
  make a heard list impossible from that stream. Undirected mode may give raw
  text.
- UNVERIFIED: whether text sent through `text.add_tx` gets fldigi's automatic
  `mycall:crc` header the way typed text does.
- **fldigi transmits on its own.** In directed mode it answers `?`, `$`, `@`
  etc. itself and can sound on a timer, none of which passes through
  kissterm's gate. At the least this has to be stated on screen and in
  SETUP.md, per the unattended-transmission rules.
- FSQ is slow (FSQ-3 is about 30 WPM, so 100 characters take about 20 s of
  airtime). The paste cap and any file-send UI need tighter limits than
  packet.

First step: dump `rx.get_data` and send one `text.add_tx` line against a real
fldigi in FSQ mode. Tests use a fake XML-RPC server, since fldigi cannot
decode FSQ without audio.
