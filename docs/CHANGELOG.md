# CHANGELOG.md — kissterm

Format: keep newest at top. One entry per meaningful change. Reference files
touched and any breaking notes.

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
