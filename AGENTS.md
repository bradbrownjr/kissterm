# AGENTS.md — kissterm

A terminal for KISS TNCs, packet nodes, and HF modems. Python 3.11+, built with
[Textual](https://textual.textualize.io/). Package under `kissterm/`.

The rules a session needs, each with a pointer to the code or test that
enforces it. The reasons behind a rule live in that code's docstring and in
`docs/CHANGELOG.md`; the long version of this file, with each rule's history,
is in git at commit `6d81202`. Read this file top to bottom before touching
code.

Companion files: `README.md` (users), `SETUP.md` (getting on the air),
**`DESIGN.md` (how anything looks or is keyed -- read before changing
either)**, `docs/ROADMAP.md` (what is open), `docs/CHANGELOG.md` (what
changed). Each package has its own short `AGENTS.md` (`kissterm/ax25/`,
`transport/`, `aprs/`, `ui/`, `mail/`).

---

## Before picking up any work

Read the top of `docs/ROADMAP.md` ("How to work this file"). In short: P0
(reported bugs, stabilizing) comes before any new feature; a live bug is
reproduced from real evidence before it is fixed and is closed only by the
operator; no key binding changes outside DESIGN.md section 5.

## Always / Never memory protocol

- When the user says **"always"**, **"never"**, **"remember"** or **"don't"**,
  add it to section 7 as a rule immediately.
- A rule not written here will be forgotten next session.
- Update or remove a rule that turns out wrong rather than stacking another.
- A rule is a sentence or two plus a pointer. History goes to CHANGELOG.

---

## 1. What kissterm is, and what it is not

A **terminal**: connect to a packet BBS, NET/ROM node or BPQ32/LinBPQ node and
type at it; also monitor the channel, keep a heard list, decode and send APRS.

**What makes it different** is `kissterm/ax25/session.py`: AX.25 connected
mode implemented in userspace over KISS. That is why it runs unprivileged and
cross-platform against a TNC on serial, Bluetooth or a TCP socket on another
machine (linpac needs the kernel AX.25 stack; BPQTerminal and EasyTerm are
Windows GUIs tied to one install). **A change that delegates the link layer
back to the kernel deletes the reason this project exists.**

Scope: a client terminal, not a node, BBS or igate. It may answer incoming
connections (keyboard chat, a future personal mailbox) but never routes,
digipeats or gates to the internet (ROADMAP P4).

## 2. Architecture

### 2a. The two transport tiers

`kissterm/transport/base.py`. Every backend is exactly one of:

- **Frame transports** (`FrameTransport`) move AX.25 frames: KISS over serial,
  TCP, Bluetooth; AGWPE raw. Frames go into kissterm's own state machine.
- **Session transports** (`SessionTransport`) hand back an already-connected
  byte stream: VARA, Mercury, kernel AX.25, Telnet, SSH. **Never run
  kissterm's state machine on top of one** -- two AX.25 implementations on
  one link corrupt it.

They return different objects: `AX25Station.connect()` gives an `AX25Link`,
`SessionTransport.connect()` a `Session`. `KissTermApp._SessionLinkAdapter`
(`ui/app.py`) wraps a `Session` in `AX25Link`'s shape at bind time. **Add UI
logic that must work on both tiers by extending the adapter, never by
reshaping `Session`** (that ripples into vara/mercury/kernel_ax25 and
`tests/unit/test_tx_gate.py`).

### 2b. One shared frame fan-out

`FrameTransport.subscribe()` fans each frame out once to the station, monitor,
heard table and APRS decoder. **A new consumer is a subscriber, never a second
decode path.** `AX25Station` (`ax25/station.py`) demultiplexes: existing link,
new incoming link, or `on_unhandled` (the APRS input). The monitor subscribes
to the transport, not to `on_unhandled`, or it goes quiet during a live
conversation. `FrameTransport.on_sent` is the transmit-side fan-out.

Nothing in `ax25/` does I/O; every byte goes through a transport object, which
is what makes the stack testable on a loopback (section 6).

## 3. The AX.25 stack

`kissterm/ax25/session.py` implements AX.25 2.2 section 6; its module
docstring is long on purpose. The points that cost time if forgotten:

- **`TIMER_RECOVERY` is not an error.** Never show it as a failure or tear the
  link down over it.
- **T1** drives retransmission, **T2** delays acks so they piggyback (T2=0
  doubles frames on air), **T3** probes an idle link so a vanished peer does
  not stay "connected".
- **All sequence arithmetic is modular** (`ax25/window.py`). `while va < nr`
  jams the window after the first wrap ("stalls after exactly 8 frames").
- **One REJ, not one per out-of-sequence frame** (`reject_sent`).
- **Deliberate deviation:** `_ack_upto` resets RC on any forward progress.
  Revert only with a test showing a link clinging to a dead peer.
- **Modulo 128 works but SABM/mod 8 is the default**; `_on_dm` falls back
  from SABME to SABM once. `Config.modulo` selects it; k < modulo.
- **Answer DM to traffic for a link you do not have**; silence costs the
  caller N2 retries.
- **Connect retries (5) and N2 (10) are separate budgets on purpose.**
- **Single-threaded per link, no locks.** Never call into a link from a thread.
- New logic that fits `window.py` or `timers.py` goes there, not into
  `session.py` (the one deliberately large file).

## 4. File map

```
kissterm/
  __init__.py  __main__.py  config.py  _isolate.py  tx.py (TRANSMIT GATE)
  monitor.py (sanitize)  ansi.py (SGR allowlist, decode_text)
  discovery.py  hotplug.py  doctor.py
  beacon.py (BTEXT)  aprs_beacon.py (APRS)  aprs_*.py  desktop_notify.py
  session_log.py  transcripts.py  heard.py  locator.py
  addressbook.py  harvested.py  bbs.py  glossary.py  guides.py
  nodes/ aprs_services/   SHIPPED references (data/*.toml)
  ax25/  aprs/  transport/  ui/  mail/   each with its own AGENTS.md
         ui/commands.py is the key table; ui/settings_schema.py drives Settings
tests/  loopback.py  unit/ (test_ax25_link.py matters most)  pilot/ (_wait.py)
```

**Each file should be changeable without reading the rest of the repo.** That
is why each package has its own `AGENTS.md`, and why modular arithmetic and
timers live apart from the state machine.

## 5. Running and versioning

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/kissterm            # --doctor, --discover, --setup
git config core.hooksPath hooks
```

`__version__` in `kissterm/__init__.py` is the source of truth;
`hooks/pre-commit` bumps the patch version on every commit and keeps
`pyproject.toml` in step. `hooks/post-merge` reinstalls when `pyproject.toml`
changes.

## 6. Testing without a TTY or a radio

- **Call `kissterm._isolate.isolate()` before the first `kissterm` import** in
  any test or script. `config.py` resolves the real `~/.config/kissterm` at
  import time. **Never `shutil.rmtree()` a `platformdirs` path.**
- **Run only the tests for what you changed.** Requested repeatedly by the
  operator (CPU, power, tokens). The full suite (`-n auto`, several minutes on
  every core) is for cross-cutting changes -- transport, the AX.25 state
  machine, shared config, dependency upgrades -- run once, with
  `-o faulthandler_timeout=180` so a hang prints its stack. `-n0` for
  un-interleaved output.
- **The loopback** (`tests/loopback.py`) re-encodes every frame; keep it that
  way. `tests/unit/test_ax25_link.py` is the conformance suite.
- **Wait on conditions, not wall-clock time** (`tests/pilot/_wait.py`). Drain a
  lossy link by byte count (`_drain(link, expect=N)`). At 40% loss a transfer
  takes ~5 s; 25% is the stable test point.
- **`pilot.pause()` costs ~100-120 ms.** Poll asyncio-level conditions with
  `asyncio.sleep()`; pause once before reading a widget.
- **Pause before pressing a button on a just-pushed screen.** A lost press
  leaves the screen open and `run_test` then never returns -- a hang, not a
  failure.
- **`run_test` runs inside the app's context; the real launch does not.**
  Frame-driven Textual timers need `FrameTransport.callback_context`; see
  `tests/pilot/test_frame_context.py`.
- `LinkParams` is `slots=True`: copy with `dataclasses.replace()`.
- Patch `serial.tools.list_ports.comports` itself, never `sys.modules`.
- **Generate a screenshot after any layout change**
  (`scripts/generate_screenshot.py` -> `assets/`) and look at it; write a
  geometry test (`tests/pilot/test_app_mounts.py`) for what it shows.
- Two bottom-docked widgets overlap; put them in one docked container.
- A pane fed by a periodic refresh needs a `TabActivated` hook.
- `KissTermApp` takes `config` and `station` as arguments so tests can mount
  it on a loopback. Keep it that way.

## 7. ALWAYS / NEVER rules

### Workflow
- **Commit and push every tested increment**; commits and pushes are
  pre-approved. One CHANGELOG entry per commit where the hunks allow it.
- **Never add `Co-Authored-By: Claude` trailers.** AI attestation is in the
  README.
- **System-wide read-only commands are pre-approved**; ask before system-wide
  writes, installs or service changes.
- **Update CHANGELOG and ROADMAP when something ships**: a dated section with
  a `**Files:**` line; delete the roadmap item the same day. New capabilities
  go under "New Features", improvements to existing ones under
  "Improvements". Keep entries to a few lines.
- **Module docstrings explain why** the design is what it is and what breaks
  otherwise. That is where a rule's history belongs.
- **No emoji** in source, output or docs. Sole exception:
  `kissterm/aprs/symbols.py`'s `Symbol.emoji`, UI-only, operator-requested.
- **Never write a doubled curly brace in Markdown** (Jekyll/Liquid breaks the
  author's GitHub Pages builds).
- **Mark inferred protocol details `# UNVERIFIED:` or `# RESEARCH:`.** Never
  present a guessed wire format as fact.

### Airtime is the scarce resource
- **Never spend channel time to populate the UI.** Command references ship in
  `kissterm/nodes/data/`; asking a node for its `?` list is opt-in, once per
  node, cached, and shows the cost first (`nodes.reference.describe_airtime`).
- **Node identification is passive** (`_sniff_node`): read the banner and
  prompt, never ask.
- **A wrong family shown confidently is worse than "unknown"**; detection
  patterns must be specific.
- **Record provenance per command** (verified / documented / recalled /
  learned) and show it (`nodes.reference.SOURCE_TIERS`).

### One visual language, one place for each fact
- **The keyboard is one table**: `kissterm/ui/commands.py`'s `COMMANDS`
  generates the bindings, Footer, F10 menu, Help Keys page, palette and the
  README key table (`scripts/sync_docs.py`). Never hand-write an App
  `Binding`. The standard is DESIGN.md section 5, enforced by
  `tests/unit/test_key_standard.py` and `test_docs_keys.py`. **Never bind
  Ctrl+Shift, Ctrl+Alt or Alt anything.**
- **Never turn Textual's Kitty keyboard protocol back on**
  (`kissterm/__init__.py`, `tests/unit/test_keyboard_protocol.py`). When a key
  "does nothing", run `scripts/keycheck.py` before guessing.
- **A tab's key is in its label (`F2 Terminal`), never also in the Footer.**
- **One flat, rounded `Button` style** (`styles.py`); variants change colour
  only.
- **Active tab = bold accent text plus underline**, not a filled block.
- **`Footer` docks itself**; compose order does not place it. Check a widget's
  `DEFAULT_CSS` before assuming yield order controls layout.
- **Status bar**: `$background`, fields in a `Table.grid` (`_status_row`).
- **A focused widget's `BINDINGS` with `show=True` are the context bar.** No
  hint lines under buttons; a modal screen yields its own `Footer()`.

### The terminal transmits only on a deliberate commit
- **`TerminalPane.send_line` is the single transmit path** out of the terminal
  pane (`tests/pilot/test_terminal_ux.py` counts `link.send(` in the source).
- **Suggestions and completions fill the input; they never send.** Use
  `TerminalPane.suggest`; never complete-on-enter.
- **The APRS template picker never transmits on selection**
  (`AprsServiceScreen`). Both guarding tests in `test_aprs_templates.py` stay.
- The scrollback is a read-only `RichLog`/`WrapLog`.
- Links are built from sanitized text, never parsed from remote markup.

### The transmit gate
- **`kissterm/tx.py` is the master switch, CLOSED on launch.** `Ctrl+T`
  toggles it; `Config.tx_armed_at_start` defaults false.
- **A confirmed, operator-named request arms the gate** through
  `KissTermApp._arm_for` only: connect (Ctrl+N dialog, Address Book dial,
  Ctrl+R Reconnect), disconnect, `TerminalPane.send_line` while connected,
  `AprsPane._send_compose`, APRS > Send position. **An unattended resend never
  arms** (`AprsPane._retry_worker`, beacon timers).
- **Arming is never silent**: `_arm_for` writes a terminal line, a toast and
  the status bar.
- **Enforced at the transport, not the UI.** `FrameTransport.send_frame` is
  concrete; backends implement `_send_frame` and **never override
  `send_frame`** (`tests/unit/test_tx_gate.py`). `Session.send` gates the
  session tier.
- A blocked send returns normally and is counted, logged `TX BLOCKED`, and
  never fires `on_sent`.
- A bare `Transport` (tests, scripts) has an open gate; `KissTermApp.__init__`
  installs the closed one (`tests/pilot/test_transmit_gate.py`).
- **Log a frame as transmitted only after the backend accepted it**; `TX
  FAILED` otherwise.
- **Show a transport that is not carrying frames** (`_transport_status`:
  `RECONNECTING`, `DOWN`), and refuse to connect over it with a message that
  says it is not an RF problem.
- **Never report a suppressed transmission as sent** (`Beaconer.problem()`).
- Send beacon (menu) waives only the timer-enabled check, not the gate, empty
  text or a bad destination.

### Unattended transmission
- **Answering calls and beaconing are the only unattended transmitters.** Both
  off by default, both shown in the status bar (`ANSWERING`, `BEACON`) while
  armed, both log every transmission to the terminal pane.
- **A login script or hop chain rides the connect the operator confirmed**
  (`_run_connect_script`, `_hop_through`): each line echoed, stops if the
  gate closes or the link drops, and the login runs only if the whole chain
  came up.
- **`RadioReminderScreen` comes before the gate arms**; cancelling transmits
  nothing (`test_connect_scripts.py`). Address Book dials and Reconnect go
  through it too.
- **BTEXT (`beacon.py`) is not APRS beaconing (`aprs/`)**: separate config,
  Settings sections and labels (`tests/pilot/test_settings.py`). Turning APRS
  beaconing on from the menu turns BTEXT off (`_toggle_aprs_beacon_quick`);
  Settings does not cross-disable. Keep both as they are.
- **Beacon interval floor: 10 minutes**, clamped in `config.py` and in
  `Beaconer.interval_seconds`.
- **Nothing transmits at startup**; the beacon waits a full interval.
- **Never send an empty beacon.**
- **Re-check at the moment of transmission**, not only where the decision was
  made (`Beaconer.send_once`, `_send_banner`).
- **Answering is off by default and stays that way**; a refusal is a DM, never
  silence.

### One way to build a transport
- **`transport.build_transport()` is the only constructor from config** (app,
  wizard, `--doctor`). `_ENTRY_ONLY_KEYS` strips config-only keys like `name`;
  everything else is forwarded so a typo fails loudly
  (`tests/unit/test_transport_factory.py`).
- **Discovery emits only a config it can complete**; the port decides the kind.
- **The wizard builds what it saves** and never prints "Saved" on failure.
- **Switch transports with `AX25Station.rebind_transport`**, never by
  assignment; it refuses while a link is connected. At shutdown, close
  `station.transport`, not the variable that first built it.

### Discovery and scanning
- **A sweep covers the subnet or says it did not** (`ScanCoverage`); ports are
  the outer loop, truncation counted in probes.
- **Never scan the network on a timer** -- only `--discover`, the wizard, or
  Settings' "Scan for hardware" (`test_hotplug_never_touches_the_network`).
- **Do poll local serial ports** (`hotplug.py`, ~0.4 ms per poll).
- A configured TCP host that goes away is reconnected, not rescanned.
- **Never initiate Bluetooth pairing or discovery**; enumerate paired devices.

### Radio and protocol
- **Never send anything to a transport the operator did not ask for.**
- **Never transmit during discovery.** A probe may write two bare FENDs or one
  AGWPE `'R'` query, nothing else; **VARA's ports are never touched**
  (`tests/unit/test_identify_tcp.py`).
- **A silent probe is inconclusive** ("open, identity unconfirmed"). A protocol
  reply (HTTP, SSH banner, hang-up) is conclusive: `"not-a-tnc"`, dropped.
- **Always answer a poll with F=1**, even when busy.
- **Keep `paclen` and window configurable per link.**

### A callsign is a claim, not an identity
- AX.25 has no authentication. **Never present a callsign as proof**, in
  wording ("claimed W1AW") or behaviour; a per-callsign allowlist is a
  convenience, never a security control (ROADMAP P10).

### A failure the operator cannot diagnose is a bug
- **Both directions of every frame are logged** at DEBUG in `send_frame` and
  `dispatch`; never add a send path that bypasses `send_frame`.
- `--log-level debug` raises only the `kissterm` logger tree.
- **Never report two different failures with the same words** (DM refusal vs.
  N2 silence; a closed-gate auto-ack is announced, not just withheld).

### Untrusted input
- **Every remote byte goes through a filter before a widget or log.**
  `monitor.sanitize()` everywhere; `ansi.to_text()` only in the terminal pane.
- **`kissterm/ansi.py` is an allowlist and stays one**: dropped sequences
  vanish whole, an emptied SGR vanishes rather than becoming a reset, blink
  and conceal are not allowed (`tests/unit/test_ansi.py`).
- **Transcripts get fully stripped text**, never colour codes.
- **A paste is sanitized before the send line** (`_SendInput._on_paste`);
  never call `super()._on_paste` there.
- **A log that cannot be written never disturbs a live link**
  (`session_log.py` catches `OSError`).
- **Decode payload with `ansi.decode_text`**: UTF-8 when valid, else latin-1
  (operator's decision, 2026-09-23). Never a bare `.decode("utf-8")`. C1 and
  bidi controls are stripped from the decoded text, never as bytes.
- **Never let a decode error, dropped socket or missing optional dependency
  raise out of a background task.** Count it and continue.

### Textual traps (all verified against 8.2.8)
- **`Select.NULL`, never `Select.BLANK`**, for "nothing selected".
- **Pin the current value into any `Select.set_options` list, and never set
  an empty list** (`tests/pilot/test_settings.py`).
- **Use `WrapLog`, never a bare `RichLog`**, in a resizable column
  (`kissterm/ui/wraplog.py`).
- **Tab ids need a prefix** (`convo-`, since `2E0ABC` is a callsign);
  `add_tab` on an empty strip activates it; `Tabs.TabActivated` and
  `TabbedContent.TabActivated` are unrelated.
- **A message used with `@on(..., "#id")` needs a `control` property**
  (`kissterm/ui/tabclose.py`).

## 7a. Theming

`kissterm/ui/themes.py` curates Textual's `BUILTIN_THEMES` plus a `"custom"`
theme from `Config.custom_theme`; `KissTermApp.apply_theme()` applies it.

- **Never invent a palette** for a family with no upstream light variant; point
  at `SUGGESTED_LIGHT_ALTERNATIVES`.
- **A bad theme name never crashes or unstyles the app**
  (`themes.resolve_theme_id`, default `tokyo-night`).
- **`ansi-dark`/`ansi-light` are "match my terminal"** -- mention them first.
- Add a family as a `ThemeFamily` in `THEME_CATALOG`, verified by test.

## 8. Known caveats

- **Mic-E is decoded but not validated against off-air traffic** (fixtures come
  from our own encoder). Run a real captured packet through it before
  trusting it -- the highest-value open verification.
- The compressed-position cs byte is treated as radio range; weather fields
  are regex-extracted. Check against a live feed.
- **Modulo 128, VARA, Mercury, kernel AX.25 and BLE are unverified on
  hardware** (ROADMAP P3). Do not "finish" VARA or Mercury by guessing;
  `mercury.py` is an honest skeleton.
- The session-tier UI wiring is proven against local Telnet/SSH servers only.
- **Every top-level setting in `config.toml.example` stays above the first
  `[table]` header** (`tests/unit/test_config.py`).
- **Answering has no mailbox behind it yet** (ROADMAP P9; read its regulatory
  note first).
- APRS: a station list/map view is still open (P4). The Monitor pane shows raw
  frames by design.
- **APRS specifics, each documented in `ui/app.py`'s `_on_aprs_frame` and
  `aprs_*` modules:** third-party-wrapped messages are unwrapped for
  ack-matching; conversation tabs are restored at launch but the retry queue
  never is; Ctrl+L on "All" deletes every conversation, and a new pane in
  `action_clear_log` needs its own case; acks go out under
  `Config.aprs.source_for` and never another identity (LinBPQ requires an
  exact SSID match -- fix addressing, never spoof); a closed-gate auto-ack is
  announced; duplicates are shown once but acked every time;
  `filter_by_ssid` (default on) decides "addressed to me" in one place,
  `monitor.aprs_message_matches`.
- **YAPP is viable here**, unlike under BPQ32's stdio in the sibling
  `bpq-apps` repo (ROADMAP P5).

## 9. Common tasks

- **Add a transport:** subclass `FrameTransport` or `SessionTransport`
  (tier = "does it connect on its own?"), add a lazily-imported branch to
  `build_transport()`, an example in `config.toml.example`, and a discovery
  heuristic if findable. Implement `_send_frame`, never `send_frame`.
- **Add a pane:** a `TabPane` in `compose()`, a `Command` in
  `ui/commands.py`, and a fan-out subscriber if it needs frames.
- **Add a setting:** a `Config` field with a loader entry, then one
  `SETTINGS_SCHEMA` entry (`test_every_config_field_is_editable_or_deliberately_excluded`).
- **Change link behaviour:** add a loopback test in `test_ax25_link.py` first.
- **"The link stalls":** check `_ack_upto`'s modular walk, then `_pump()`
  reachability, then `peer_busy`; `--log-level debug` shows V(S)/V(R)/V(A)/rc.
- **"Nothing in the monitor":** the transport's decode-error counter, then
  `MonitorFilter`, then the debug log.
- **"Acked but no reply":** `_note_if_no_reply` -- the far application is
  slow, not the link.
- **"The connect failed":** `link.last_error` and the Monitor. DM = refused
  (configuration); N2 silence = path (antenna, power, propagation).
- **A key "does nothing":** `scripts/keycheck.py`.
