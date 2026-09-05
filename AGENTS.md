# AGENTS.md — kissterm

A terminal for KISS TNCs, packet nodes, and HF modems. Python 3.11+, built with
[Textual](https://textual.textualize.io/). Package under `kissterm/`.

This file is the single source of truth for a future session continuing work
WITHOUT prior chat context. Read it top to bottom before touching code.

Companion files: `README.md` (users), `SETUP.md` (operators getting on the air),
**`DESIGN.md` (the visual and interaction schema -- read before changing how
anything looks)**, `docs/ROADMAP.md` (what is still open), `docs/CHANGELOG.md`
(what changed and why).

---

## Always / Never Memory Protocol

- If the user says **"always"**, **"never"**, **"remember"**, or **"don't"**,
  treat it as a permanent rule and add it to §7 immediately.
- If a rule is not written down here, assume it will be forgotten next session.
- Remove or update rules that turn out to be wrong rather than letting them stack.

---

## 1. What kissterm is, and what it is not

kissterm is a **terminal**. You connect to a packet BBS, a NET/ROM node, or a
BPQ32/LinBPQ node and type at it. It also monitors the channel, keeps a heard
list, and decodes APRS.

**The thing that makes it different from every comparable project** is in
`kissterm/ax25/session.py`: kissterm implements AX.25 connected mode *itself*,
in userspace, over KISS.

| Project | Why it does not cover this niche |
|---|---|
| linpac | Requires the Linux kernel AX.25 stack (`AF_AX25`, `axports`, root to set up). Cannot talk to a KISS TNC on another machine's TCP port at all. |
| BPQTerminal / bpqterm32 | Windows GUI, tied to a BPQ32 install. |
| UZ7HO EasyTerm | Windows GUI, tied to that author's soundmodem. |

Owning the state machine is why kissterm runs unprivileged, cross-platform,
against a TNC on a serial cable, a Bluetooth link, or a TCP socket on a
Raspberry Pi in the garage. **If a future change proposes delegating the link
layer back to the kernel, it is deleting the reason this project exists.**

Scope boundary: kissterm is a *client terminal*, not a node, a BBS, or an
igate. It answers incoming connections (that is how keyboard-to-keyboard chat
and a personal mailbox work) but it does not route, digipeat, or gate to the
internet. See `docs/ROADMAP.md` P4 for why igating is explicitly out of scope.

## 2. Architecture

### 2a. The two transport tiers — the central design decision

`kissterm/transport/base.py`. Every backend is one of two things, and
conflating them is how a packet terminal accretes special cases:

**Frame transports** (`FrameTransport`) move AX.25 *frames* and know nothing
about connections. KISS over serial (`serial_kiss.py`), KISS over TCP
(`tcp_kiss.py`), KISS over Bluetooth (`bluetooth.py`), AGWPE raw mode
(`agwpe.py`). Their frames go into kissterm's own state machine.

**Session transports** (`SessionTransport`) hand back an *already-connected
byte stream*. VARA HF/FM (`vara.py`), Mercury (`mercury.py`), the Linux kernel
AX.25 stack (`kernel_ax25.py`). The modem or kernel already ran the link layer.
**Running kissterm's state machine on top of one of these puts two AX.25
implementations on one link and corrupts it.** That is what the tier split
exists to prevent.

Both tiers produce a `Session`. Everything above — panes, logging, file
transfer — talks only to `Session` and never learns which tier it is on. That
is the seam that lets a VARA link and a KISS link render in the same pane.

### 2b. One shared frame fan-out

`FrameTransport.subscribe()` is a fan-out. The station, the monitor pane, the
heard table and the APRS decoder are all subscribers; a frame is decoded once
no matter how many things care about it. **Adding a second decode path for a
new pane is the wrong instinct — add a subscriber.**

`AX25Station` (`ax25/station.py`) is the demultiplexer: it decides whether an
inbound frame belongs to an existing link, starts a new one (incoming SABM),
or belongs to nobody and goes to `on_unhandled` — which is the input to APRS.

**The monitor pane subscribes to the transport, not to `station.on_unhandled`.**
A frame belonging to an open link is routed straight to that link and never
reaches `on_unhandled`, so a monitor fed from there cannot show the UA that
answers your SABM, nor any traffic of a live conversation — it goes quiet at
the one moment worth watching. `FrameTransport.on_sent` is the matching
fan-out for the transmit side; without it "the node never answered" and "we
never actually keyed up" look identical on screen.

### 2c. Layering

```
        app.py  (Textual: tabs, panes, bindings)
           |
      Session  <-------------------------------+
           |                                    |
   ax25/station.py  (demux, incoming links)      |
           |                                    |
   ax25/session.py  (AX25Link: the state machine)|
           |                                    |
   ax25/frame.py + ax25/address.py  (wire format)|
           |                                    |
   FrameTransport                        SessionTransport
   (kiss.py codec + serial/tcp/bt/agwpe)  (vara, mercury, kernel)
```

Nothing in `ax25/` does I/O. Every byte goes through a transport object. That
is what makes the whole stack testable against a loopback with no radio — see
§6.

## 3. The AX.25 stack — what a future session needs to know

`kissterm/ax25/session.py` implements AX.25 2.2 section 6. Read its module
docstring; it is long on purpose. The points that cost time if forgotten:

- **`TIMER_RECOVERY` is not an error state.** It is the link asking "are you
  still there, and what have you received?" after T1 expired. A busy 1200-baud
  channel or a marginal HF path spends real time there and recovers fine.
  Showing the operator a failure, or tearing the link down, is wrong.
- **Three timers, three jobs.** T1 = "I sent something and have not been
  acknowledged" (drives all retransmission). T2 = "wait before acknowledging",
  so an outgoing I frame can piggyback the ack — on a half-duplex radio channel
  every avoided transmission is avoided airtime and avoided collisions; setting
  T2 to zero roughly doubles the frames on the air. T3 = "the link has been
  idle, is it alive?" — without it a link whose far end vanished stays
  "connected" in the UI forever.
- **All sequence arithmetic is modular.** `_ack_upto` walks V(A) forward
  modulo N rather than comparing integers. Writing `while self.va < nr` instead
  silently stops acknowledging after the first wrap and the window jams shut.
  The symptom is "the link stalls after exactly 8 frames".
- **One REJ, not one per out-of-sequence frame.** The peer is already sending
  the rest of its window; every extra REJ is airtime spent asking for something
  already on its way. `reject_sent` guards this.
- **DELIBERATE DEVIATION from the 2.2 SDL**: `_ack_upto` resets RC on *any*
  forward progress, not only on leaving timer recovery. Measured on the
  loopback at 40% frame loss, strict-SDL behaviour tears the link down
  mid-transfer while this carries it to completion. Revert only with a test
  showing it makes a link cling to a genuinely dead peer.
- **Modulo 128 is implemented and tested** (`test_modulo_128_link`), but SABM /
  modulo 8 is the default because it is what every BPQ32, KA-Node and
  TNC2-class station on the air actually implements. A station that does not
  understand SABME answers DM; `_on_dm` falls back to SABM once before giving
  up, which is what makes the non-default safe to turn on. `Config.modulo`
  selects it and the window ceiling scales with it (k < modulo).
- **Answer DM to traffic for a link you do not have.** A silent drop makes the
  caller retry N2 times and waste a minute of channel time.
- **Connect retries and N2 are separate budgets, on purpose.**
  `LinkParams.connect_retries` (default 5) bounds the SABM phase;
  `retries` (default 10, the spec value) bounds an established link. They are
  different trades: giving up early on a connect costs one keystroke, while
  giving up early on a live session throws away a real conversation over what
  may be one car passing between two antennas. Collapsing them back into one
  number makes one of the two wrong whichever value is picked.
- **Single-threaded per link, no locks.** `AX25Link` schedules `call_later`
  timers on the running loop. Calling into one from a thread destroys the
  invariant the whole state machine rests on.

## 4. File map

```
kissterm/
├── pyproject.toml           # package metadata + console_scripts entry
├── README.md                # users
├── AGENTS.md                # THIS file
├── SETUP.md                 # getting a radio on the air
├── DESIGN.md                # visual + interaction schema (colors, grid, keys)
├── LICENSE                  # MIT
├── config.toml.example      # documented config template (never auto-copied)
├── docs/
│   ├── ROADMAP.md           # what is open; completed items move to CHANGELOG
│   └── CHANGELOG.md         # newest at top, dated sections, **Files:** line
├── hooks/{pre-commit,post-merge}   # version bump + dep resync (see §5)
├── scripts/bump_version.py
├── kissterm/
│   ├── __init__.py          # __version__ -- source of truth
│   ├── __main__.py          # CLI: --doctor, --setup, --discover, wizard, launch
│   ├── app.py               # Textual app: tabs, panes, CSS, bindings
│   ├── config.py            # Config dataclass <-> config.toml (never raises)
│   ├── _isolate.py          # platformdirs monkeypatch for tests -- see §6
│   ├── discovery.py         # serial / LAN / Bluetooth autodiscovery (MANUAL)
│   ├── hotplug.py           # serial-only hotplug watch (never the network)
│   ├── doctor.py            # `--doctor` diagnostics
│   ├── monitor.py           # frame -> monitor line, and sanitize()
│   ├── tx.py                # MASTER TRANSMIT GATE -- closed on launch
│   ├── ansi.py              # SGR ALLOWLIST for the terminal pane only
│   ├── beacon.py            # BTEXT: unproto UI frames on a timer (NOT APRS)
│   ├── session_log.py       # per-session plain-text transcript
│   ├── heard.py             # MHEARD table
│   ├── nodes/               # SHIPPED command references (data/*.toml)
│   ├── ax25/            # + its own AGENTS.md (local contract)
│   │   ├── address.py       # callsign/SSID encode+decode, AX25Path
│   │   ├── frame.py         # I/S/U frames, modulo 8 and 128
│   │   ├── window.py        # V(S)/V(R)/V(A) -- ALL modular arithmetic
│   │   ├── timers.py        # T1/T2/T3 + the sync-to-async bridge
│   │   ├── session.py       # AX25Link -- THE STATE MACHINE
│   │   └── station.py       # AX25Station -- demux, incoming links
│   ├── aprs/                # UI-frame payload decode + encode (+ AGENTS.md)
│   ├── ui/                  # Textual panes, one file each (+ AGENTS.md)
│   │   ├── settings_schema.py  # DECLARATIVE settings; add a field here only
│   │   └── settings_pane.py    # generated from the schema, edits nothing else
│   └── transport/           # + its own AGENTS.md (local contract)
│       ├── base.py          # the two tiers, Session
│       ├── kiss.py          # KISS codec, no I/O
│       ├── serial_kiss.py   tcp_kiss.py   agwpe.py      (frame tier)
│       └── bluetooth.py     kernel_ax25.py  vara.py  mercury.py
└── tests/
    ├── loopback.py          # two frame transports wired together, with loss
    ├── unit/                # pytest; test_ax25_link.py is the important one
    └── pilot/               # headless Textual run_test() scenarios
```

### Keeping files editable by a smaller model

A deliberate constraint: **each file should be changeable without reading the
rest of the repo.** That is why every package carries its own short
`AGENTS.md` contract (file map, local rules, how to test just that package) and
why the two riskiest concerns -- modular sequence arithmetic and timer
lifecycle -- were pulled out of the state machine into `window.py` and
`timers.py`, where they can be tested with no event loop and no peer.

`ax25/session.py` (~700 lines) is the one deliberately large file: it is a
single state machine, and splitting its handlers apart creates a two-way
dependency worse than the size. New logic that fits in `window.py` or
`timers.py` belongs there instead of growing it further.

## 5. How to run, and versioning

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/kissterm              # or: .venv/bin/python -m kissterm
.venv/bin/kissterm --doctor     # diagnostics, plain stdout, no TUI
.venv/bin/kissterm --discover   # scan for TNCs and exit
.venv/bin/kissterm --setup      # re-run the first-run wizard
```

`__version__` in `kissterm/__init__.py` is the source of truth; `pyproject.toml`
is kept in lockstep. The patch version bumps on every commit — `hooks/pre-commit`
runs `scripts/bump_version.py` and stages both files. Activate once per clone:

```bash
git config core.hooksPath hooks
```

`hooks/post-merge` re-runs `pip install -e .` when a pull touches
`pyproject.toml`, so a new dependency does not produce a `ModuleNotFoundError`
on the next launch.

## 6. Testing without a TTY and without a radio

> **Isolate config/state paths before importing anything from `kissterm` in ANY
> headless test or script.** `config.py` computes `_CONFIG_DIR`/`_STATE_DIR`/
> `_DATA_DIR` from `platformdirs` at **import time**, using the same `"kissterm"`
> app name the real installed app uses — on a dev machine those are the
> developer's actual `~/.config/kissterm`. Call `kissterm._isolate.isolate()`
> **before** the first `kissterm` import; patching afterwards is too late.
> **Never `shutil.rmtree()` a `platformdirs.user_*_dir()` result.** A sibling
> project of this author destroyed a real user's settings twice doing exactly
> that, and there is no `ignore_errors=True` that makes it safe — the path being
> real in the first place is the bug.

**The stack needs no radio.** `tests/loopback.py` wires two `FrameTransport`s
to each other, with injectable `loss` and `delay`, so two real `AX25Station`s
hold a full conversation — SABM, I frames, acknowledgements, retransmission,
DISC — inside one event loop. `tests/unit/test_ax25_link.py` is the suite that
matters most in this project; it is the only conformance check short of putting
the code on the air.

Gotchas that already cost time:

- **The loopback re-encodes and re-decodes** rather than passing the same
  `AX25Frame` object across. A test that hands one instance to both ends
  silently skips the wire format, where half the real bugs live. Keep it.
- **Do not drain a lossy link with a "went quiet" heuristic.** On a lossy
  channel the gap between chunks is a whole T1 recovery cycle, so a quiet-period
  read returns partial data and blames the state machine for a harness bug —
  this produced exactly one false failure already. `_drain(link, expect=N)`
  waits for a byte count against a hard deadline instead.
- **At 40% frame loss the transfer completes in about 5 s**, not instantly:
  go-back-N with a 4-frame window collapses under that much loss. That is
  correct behaviour, not a stall. 25% is the stable test point.
- **`LinkParams` is `slots=True`** — `vars()` does not work on it. Use
  `dataclasses.replace()` to copy per-link params.
- **Patch `serial.tools.list_ports.comports` itself, not `sys.modules`.**
  `from serial.tools import list_ports` resolves through the package attribute
  once anything has imported it, so a `monkeypatch.setitem(sys.modules, ...)`
  works only when the test happens to run first. That produced tests that
  passed alone and failed in the suite — the worst kind, because it looks like
  a real regression. Same trap for any `from package import submodule`.
- Textual needs a real terminal, so UI tests use `app.run_test()` with a pilot,
  same pattern as the sibling `google-tui` project. `app.save_screenshot(path)`
  inside `run_test` exports an SVG of the current render.
- **Generate a screenshot after any layout change.**
  `.venv/bin/python scripts/generate_screenshot.py` runs the real app headless
  against a loopback and writes `assets/*.png`. This is not just for the
  README: two invisible layout bugs -- a status bar the Footer painted over,
  and a heard table that stayed empty until an interval ticked -- passed the
  whole test suite and were caught only by looking at the picture. Both now
  have geometry regression tests in `tests/pilot/test_app_mounts.py`; write one
  like them when the picture shows something the assertions did not.
- **Two bottom-docked widgets land in the same region.** Textual's `Footer`
  docks bottom; anything else docked bottom is painted over, in either yield
  order. Put them in one docked container with an explicit height instead.
- **A pane fed by a periodic refresh needs a `TabActivated` hook**, or it shows
  empty or stale content for up to one interval every time the operator
  switches to it. See `_on_tab_activated`.
- `KissTermApp` takes `config` and `station` as constructor arguments
  specifically so a test can mount it against a loopback with no hardware and
  no real config dir. Do not make it construct them internally.

## 7. ALWAYS / NEVER rules

### Airtime is the scarce resource
- **Never spend channel time to populate the UI.** At 1200 baud half-duplex,
  2 KB is ~19 seconds and 8 KB is over a minute during which nobody else on the
  frequency can transmit. Command references therefore **ship** as data in
  `kissterm/nodes/data/`; asking a node for its own `?` output is opt-in, once
  per node, cached forever, and shows the operator the cost first
  (`nodes.reference.describe_airtime`). An earlier version of the roadmap had
  this backwards.
- **Node identification is passive.** `_sniff_node` reads the banner and prompt
  that arrive anyway. It must never ask a question to identify a node.
- **A wrong family shown confidently is worse than "unknown node"**, because
  the operator types its commands. Detection patterns must be specific.
- **Record provenance per command** (`confidence`: verified / documented /
  recalled / learned) and show it. A reference that silently mixes documented
  fact with half-remembered syntax is worse than none.

### One visual language, one place for each fact
- **A tab-switching key is shown in the tab label, never in the footer too.**
  `F1 Terminal` (key first, like a menu accelerator), not `Terminal (F1)`.
  Textual's `Footer` would otherwise print the same word the tab bar already
  shows, in a different corner of the screen -- exactly the duplication a user
  flagged from a real screenshot. The `Binding`s stay registered with
  `show=False`; only the on-screen label moved.
- **Every `Button` shares one flat, rounded style** (`styles.py`). Textual's
  default is a two-tone "tall" border reading as a raised 3D bezel; a `Send`
  button styled with `variant="primary"` and everything else left default
  looked like it belonged to a different app. Variant classes change color
  only, never the shape.
- **The active tab is bold accent text plus the underline bar, not a filled
  block.** Textual fills the focused tab strip's active tab with a solid
  "block cursor" background by default -- flagged as "looks funny" next to the
  flat outlined panels everywhere else.
- **Footer docks itself; yield order does not decide its position.**
  `Footer`'s own `DEFAULT_CSS` sets `dock: bottom` unconditionally, so writing
  it second in `compose()` does not put it below a sibling -- it pins to the
  container edge regardless. Getting the status bar to sit below it needed
  `#bottom-bar Footer { dock: top; }`, not a reordered `yield`. Check a
  widget's own default CSS before assuming compose order controls layout.
- **Status bar background is `$background` (near-black, matches the tab
  row), not `$panel`** (the slate-blue Header/Footer use). Requested directly:
  the readout should look like the chrome above the panes, not the Header.
- **Status fields are laid out in a `Table.grid`, not joined with `"  |  "`.**
  A joined string bunches at the left and leaves most of a wide terminal
  blank; equal-ratio columns spread across the full width and re-flow on
  resize. See `_status_row` in `ui/app.py`.

### The terminal transmits only on a deliberate commit
- **`TerminalPane.send_line` is the single transmit path** out of the terminal
  pane. Enter and the Send button both route through it, so "what can key the
  transmitter?" is answerable by reading one method.
  `tests/pilot/test_terminal_ux.py` asserts against the source that there is
  exactly one `link.send(` call in that module.
- **Suggestions and completions fill the input; they never send.** Use
  `TerminalPane.suggest`. A completion that transmits on its own is a defect on
  a shared channel. Never complete-on-enter.
- **The scrollback is a `RichLog`, not an editable widget** -- selectable and
  copyable, but it cannot be typed into by accident.
- **Links are constructed from sanitized text, never parsed from remote
  markup.** The link target is the matched substring itself, so displayed text
  and destination cannot differ.

### The transmit gate -- read this before touching any send path
- **`kissterm/tx.py` is the master switch, and it is CLOSED on launch.**
  `Ctrl+T` opens it; `Config.tx_armed_at_start` (default false) decides where
  it starts. Modelled on WSJT-X's "Enable Tx" because that is the convention
  an operator already knows. With it closed, nothing keys the radio -- not a
  beacon, not answering, not connecting, not the terminal send line.
- **A confirmed, targeted request ARMS the gate; it is not refused by it.**
  `KissTermApp._arm_for` is the only way this happens, and `Ctrl+N` (after
  the operator names a station and confirms the dialog) and `Ctrl+D` are its
  only callers. The gate exists to stop transmissions the operator did not
  initiate -- a timer, an incoming call -- and it was never meant to veto one
  they just asked for by name. Refusing a connect with "transmit is disabled"
  is a dead end: the only thing the operator wanted is the only thing the
  message will not do, and on a marginal path it reads like the far station
  is missing. `Ctrl+D` matters for the channel too -- a DISC we refuse to
  send leaves the far station holding a session open until its own timers
  give up.
- **A bare keystroke never arms it.** The manual beacon (`Ctrl+Shift+B`) has
  no confirmation step and no target, which is exactly the shape of an
  accidental transmission; it still reports the closed gate and sends
  nothing. The rule is *confirmed and targeted*, not *the operator pressed
  something*.
- **Arming is never silent.** `_arm_for` writes a line into the terminal log,
  raises a notification, and refreshes the status bar. "Did this thing start
  transmitting behind my back?" has to stay answerable from the screen, or
  the auto-arm is not defensible at all.
- **It is enforced at the transport, not in the UI.**
  `FrameTransport.send_frame` is CONCRETE and calls the abstract
  `_send_frame`; `Session.send` gates the session tier so VARA and Mercury are
  covered too. A new backend implements `_send_frame` and **must never
  override `send_frame`** -- that would route around the interlock, and
  `tests/unit/test_tx_gate.py` fails if one does. The checks in the panes are
  a courtesy so the operator learns *why* nothing happened; the transport
  check is the guarantee.
- **A blocked send returns normally and is counted, never raised.** AX.25
  retransmission runs on `call_later` callbacks with nowhere for an exception
  to go, and the house rule is that a background task never dies of one.
- **A bare `Transport` has an OPEN gate.** A transport built by a test, a
  script or a probe has no operator to throw the switch, and a safety
  interlock nobody can reach is just a broken program. `KissTermApp.__init__`
  installs the closed one, and `tests/pilot/test_transmit_gate.py` asserts a
  freshly mounted app cannot transmit.
- **Never report a suppressed transmission as a sent one.**
  `Beaconer.problem()` treats a closed gate as a reason not to beacon
  precisely so `send_once` cannot log "Beacon sent" for a frame the gate
  dropped. Telling an operator something went on the air when nothing did is
  the one lie a transmit indicator must not tell.
- **`Ctrl+Shift+B` is a manual beacon and waives exactly one check** -- whether the
  *timer* is enabled, because a manual beacon is not the timer. It does not
  waive the gate, empty text, or a bad destination. It is `Ctrl+Shift+B`, not
  `Ctrl+B`, because `Ctrl+B` is tmux's prefix and a station PC in another room
  is usually reached through a multiplexer -- a transmit key the operator
  cannot press is not a transmit key. Plain `Ctrl+B` stays bound but hidden,
  for terminals whose keyboard protocol collapses the two into one byte.

### Unattended transmission
- **Two things can transmit with nobody present: answering a call, and
  beaconing.** Both are off by default, both show a status-bar marker
  (`ANSWERING`, `BEACON`) for as long as they are armed, and both write every
  transmission into the terminal pane. A station that transmits without the
  operator being able to see that it did is what the opt-in exists to prevent.
- **A beacon is not APRS beaconing, and the code must keep saying so.**
  `kissterm/beacon.py` sends free text to `BEACON`; `kissterm/aprs/` sends a
  position in APRS format to `APRS`. Separate config tables, separate Settings
  sections, separate intervals. An operator who enables one expecting the
  other is transmitting something they did not intend, under their own
  callsign -- so this is a transmitting bug, not a cosmetic one, and
  `tests/pilot/test_settings.py` guards the labelling.
- **The beacon interval floor is a clamp, not advice.** Ten minutes, enforced
  in `config.py`'s loader AND again in `Beaconer.interval_seconds`, because a
  `Config` built in code bypasses the loader. It is a courtesy to everyone
  else on the frequency, not a preference of the operator's to be talked out
  of.
- **Nothing transmits at startup.** The beacon sleeps a full interval first.
  Opening the app is not a request to key the radio.
- **Never send an empty beacon.** No text, no transmission, whatever
  `enabled` says. `MAIL FOR:` with nothing after it is pure channel occupancy.
- **Re-check at the moment of transmission, not only where the decision was
  made.** `Beaconer.send_once` re-runs `problem()`; the failure mode of not
  doing so is transmitting text the operator already deleted.
- **Answering incoming calls is OFF by default and must stay that way.** It is
  unattended transmission under the operator's callsign. Anything that
  transmits checks the opt-in at the moment it transmits, not only where the
  decision was made -- `_send_banner` re-checks `accept_incoming` even though
  it only runs after a connection was accepted.
- **A refusal is a DM, never silence.** A silently dropped call makes the
  caller retry its full N2 budget and waste a minute of channel time.
- **If the station will answer unattended, say so on screen** for as long as
  that is true. The status bar's `ANSWERING` marker is the honest counterpart
  to the opt-in.

### One way to build a transport
- **`transport.build_transport()` is the ONLY way a `Transport` is constructed
  from config.** The app, the setup wizard and `--doctor` all go through it. A
  second dispatch table looks harmless and is not: `--doctor` had one, picked
  constructor arguments by hand, and so reported every transport healthy while
  the app could not open a single one. A diagnostic that does not exercise the
  real path is worse than no diagnostic, because it is believed.
- **Config-entry keys are not constructor arguments.** `name` is the
  operator's label -- what `active_transport` matches on and what the status
  bar shows -- and no transport's `__init__` takes it. `_ENTRY_ONLY_KEYS` is
  the list that gets stripped; everything else is still forwarded, so a typo
  in a real setting still fails loudly instead of being silently dropped.
  Forwarding `name` blindly is what made 0.1.16's first run write a
  valid-looking config and then fail to open it, for every transport kind.
- **Discovery must only emit a config it can actually complete.** A probe
  cannot know a VARA modem's callsign or that it needs two ports, so those
  entries carry no `kind` and the wizard says so rather than writing a wrong
  one. And the port decides the *kind*, not just the label: an AGWPE engine
  spoken to as raw KISS decodes as garbage instead of failing cleanly.
- **The wizard builds what it is about to save**, and refuses to print
  "Saved" if that fails. It is the last moment the operator is still present
  to be told something is wrong.
- `tests/unit/test_transport_factory.py` guards all of the above, including a
  static check that every key discovery writes is either stripped or accepted
  by that kind's `__init__`.

### Discovery and scanning
- **NEVER scan the network on a timer.** A sweep is 254 hosts times six
  ports -- about **1,500 TCP connection attempts**. Automatic, that is
  indistinguishable from a port scanner, trips intrusion detection on managed
  networks, and is rude on a club link. It happens only when a human asks:
  `--discover`, the setup wizard, or the Settings "Scan for hardware" button.
  `tests/unit/test_hotplug.py::test_hotplug_never_touches_the_network` fails if
  someone adds a convenience rescan later.
- **DO poll local serial ports.** `list_ports.comports()` costs about **0.4 ms**
  and reads only the local `/sys` tree, so the 3-second poll in
  `kissterm/hotplug.py` is a ~0.01% duty cycle touching no other machine. The
  asymmetry between this rule and the one above is measured, not aesthetic.
- **A configured host that goes away does not need a scan.**
  `TcpKissTransport` already reconnects to its known address with backoff.
  Re-scanning a subnet to rediscover an address you already have is waste.
- **NEVER initiate Bluetooth pairing or a discovery scan.** Enumerate *paired*
  devices only; pairing is a system-level action the operator takes deliberately.

### Radio and protocol
- **NEVER** send anything to a transport that the operator did not ask for.
  Every transmission is on a shared channel, keys a transmitter, and is
  attributable to a licensed callsign.
- **NEVER** transmit during discovery or probing. `probe_kiss_serial` listens;
  the network sweep reads banners passively. Nothing in discovery may key a rig.
- **ALWAYS** treat a negative probe as inconclusive. A silent KISS TNC is
  indistinguishable from a wrong serial port until a frame arrives off the air.
  The UI says "no traffic seen yet", **never** "not a TNC".
- **ALWAYS** answer a poll (`P` bit) with a response carrying `F=1`, even when
  busy. A peer waiting on a poll is blocked.
- **ALWAYS** keep `paclen` and window configurable per link. HF wants short
  frames; a fast local link wants the opposite.

### A callsign is a claim, not an identity
- **AX.25 has no authentication of any kind.** Any station can transmit any
  callsign. Everything kissterm displays -- the heard list, the monitor pane,
  APRS positions, an incoming connection's source, and eventually a file's
  uploader or a message's sender -- is a callsign the sender *asserted*, and
  nothing more.
- **Never present a callsign as proof.** Not in wording ("uploaded by W1AW"
  implies verification that does not exist -- "claimed W1AW" does not), and
  not in behaviour: a per-callsign allowlist is a convenience for the
  operator, never a security control, and must never be the only thing
  standing between a remote station and a destructive action.
- This is why serving back files that arrived over the air is opt-in and
  loudly labelled (docs/ROADMAP.md P10), and why any future auto-action keyed
  on "who" is suspect by construction.

### A failure the operator cannot diagnose is a bug
- **Both directions of every frame are recorded.** `send_frame` and `dispatch`
  are the two points every frame passes through, and both log at DEBUG, so a
  new backend inherits the record instead of having to remember it. Never add
  a send path that bypasses `send_frame`.
- **A gate-blocked frame is logged as `TX BLOCKED`, never as sent**, and does
  not fire `on_sent`. Same rule as the beacon: never report a suppressed
  transmission as a sent one.
- **`--log-level debug` raises the level of the `kissterm` tree only.** The
  root stays at WARNING. Letting it also uncork asyncio and Textual buries the
  twenty frames that matter under thousands of lines about selector events.
- **Never report two different failures with the same words.** "No connection"
  covering both a DM refusal and N2 silence sends the operator to check the
  wrong end of their station.

### Untrusted input
- **ALWAYS** put remote-supplied bytes through one of the two filters before
  they reach a widget or a log. `monitor.sanitize()` removes every escape
  sequence and is the default everywhere -- matching, filtering, logging,
  transcripts. `ansi.to_text()` additionally keeps allowlisted SGR, and is
  used in exactly one place, the terminal pane, where a BBS's colour is the
  point. Every byte in an information field was put there by someone else's
  transmitter; a corrupt frame off a noisy channel produces the same bytes by
  accident.
- **`kissterm/ansi.py` is an ALLOWLIST and must stay one.** The set of escape
  sequences a terminal understands is large and undocumented in practice; the
  set that can only recolour a glyph is enumerable. Anything unrecognised is
  removed *by construction* rather than by having been thought of, which is
  the property a denylist cannot have. Three invariants there are load-
  bearing, each with a test: a dropped sequence is consumed **whole** (leaving
  `[2J` behind as text is how this filter usually fails); an SGR with nothing
  allowlisted left **vanishes** rather than becoming `CSI m`, which is a reset
  the sender never asked for; and blink (5, 6) and conceal (8) are **not**
  allowlisted -- photosensitivity is an accessibility hazard and invisible
  text is a spoofing primitive.
- **A transcript gets fully stripped text, never the coloured form.** `cat` on
  a log file runs whatever escapes it contains.
- **A log that cannot be written must never disturb a live link.**
  `session_log.py` catches `OSError` everywhere and degrades to a no-op. A
  full disk taking a station off the air mid-net is a regression an operator
  will not forgive.
- **ALWAYS** decode payload text as `latin-1`, never UTF-8. Packet is a
  byte-oriented, mostly-ASCII medium; a decoder that raises or inserts
  replacement characters on a corrupt frame loses the readable part with the
  noise. latin-1 is total.
- **NEVER** let a decode error, a dropped socket, or a missing optional
  dependency raise out of a background task. Count it and continue. Line noise
  is normal on RF; taking the app down for it is not.

### Code
- **ALWAYS** write module docstrings that explain *why* the design is what it
  is and what breaks otherwise. This codebase's docstrings are load-bearing
  documentation, not decoration. Shallow "This module implements X" docstrings
  do not match the house style.
- **NEVER** put emoji in source, output, or docs.
- **NEVER** write a doubled curly brace in a Markdown file — Jekyll parses it
  as a Liquid variable and breaks this author's GitHub Pages builds. This rule
  cannot state the sequence literally for the same reason.
- **NEVER** add `Co-Authored-By: Claude` trailers to commits. AI attestations
  go in the repo README.
- **ALWAYS** mark inferred protocol details with `# UNVERIFIED:` or
  `# RESEARCH:` rather than presenting a guess as fact. An honest stub beats an
  invented wire format.
- **ALWAYS** update `docs/CHANGELOG.md` and `docs/ROADMAP.md` when something
  ships. New capabilities go under "New Features"; "Improvements" is only for
  making existing things better. Remove a roadmap item the moment it ships.

## 7a. Theming

`kissterm/ui/themes.py` curates a set of Textual's own `BUILTIN_THEMES`
(Tokyo Night, Catppuccin's four flavors, Nord, Gruvbox, Dracula, Monokai,
Solarized, Rose Pine, Atom One, Textual's own, `ansi-dark`/`ansi-light`) plus
a `"custom"` escape hatch built from `Config.custom_theme`'s hex fields.
`KissTermApp.apply_theme()` resolves `Config.theme` and sets `self.theme`;
called from `__init__` (so the first frame paints correctly, no flash) and
again after a Settings save or a config reload.

- **Never invent a palette for a family that does not have one upstream.**
  Tokyo Night, Nord, Gruvbox, Dracula and Monokai ship dark-only; there is no
  real "Tokyo Night Light" to point at, and guessing hex values to fake one
  would be presenting a fabricated palette as the real thing. Point at
  `SUGGESTED_LIGHT_ALTERNATIVES` instead.
- **A bad theme name must never crash the app or leave it unstyled.**
  `themes.resolve_theme_id` always returns something valid; `DEFAULT_THEME`
  ("tokyo-night") is the fallback. This bit twice in testing: once because a
  `Select` widget raises if set to a value outside its own options (fixed in
  `settings_pane._set_select_value`), and once in the config loader's hex
  validation (`_load_hex_color`), which degrades one bad `[custom_theme]`
  field at a time rather than discarding the whole table.
- **`ansi-dark`/`ansi-light` are the actual "sync with my terminal" feature.**
  They render using the terminal emulator's own ANSI palette, not a copied
  one -- nothing to keep in sync by hand. Mention these first when anyone asks
  how to match kissterm to their terminal theme.
- Add a new theme family by adding a `ThemeFamily` to `THEME_CATALOG` --
  verified by test against `textual.theme.BUILTIN_THEMES`, never by typing
  hex values in by hand.

## 8. Known caveats / open items

- **APRS Mic-E is decoded but not validated against real off-air traffic.**
  The Mic-E test fixtures were generated by this codebase's own inverse
  encoder, so they prove the decoder is self-consistent, not that it is
  correct. The destination-callsign polarity for N/S, the longitude offset,
  E/W, and the 3-bit message-code table were reconstructed rather than cited.
  **Run a real captured Mic-E packet through it before trusting it
  operationally.** Mic-E is the most common position format on 2 m and the
  most commonly botched decoder, so this is the highest-value verification
  task open in the project.
- **Compressed-position `{` cs-byte**: implemented as a pre-calculated radio
  range (`Position.precalc_range_mi`), not as altitude. Worth checking against
  a live feed. Weather-report field widths are regex-extracted rather than
  fixed-column, because real trackers are not uniform.

- **Modulo 128 is configurable but has never run against real hardware.**
  `Config.modulo` (8 or 128) reaches `LinkParams` and the window clamp now
  scales with it (k < modulo, enforced in both `config.py` and
  `SlidingWindow`). It is covered by `test_modulo_128_link` on the loopback
  only. Almost nothing on the air speaks SABME, so the fallback path in
  `_on_dm` (DM answering SABME retries once as SABM) is the part most likely
  to matter and the part least likely to have been exercised.
- **VARA and Mercury are unverified against hardware.** `vara.py`'s command set
  is written from documentation and is marked `# UNVERIFIED:` where behaviour
  is inferred. `mercury.py` is an honest skeleton that raises from `open()`;
  its wire protocol needs reading out of the upstream source before it can
  work. Do not "finish" either one by guessing.
- **BLE TNCs are not supported.** Mobilinkd TNC4-class devices need GATT
  characteristic handling and a `bleak` dependency. `BleKissTransport` is a
  marked stub.
- **`config.toml.example` had five settings silently discarded** because they
  were documented after the `[custom_theme]` header and TOML puts a bare key
  under the last table above it. Fixed, and guarded by two tests in
  `tests/unit/test_config.py`. **Every top-level setting must stay above the
  first `[table]` header in that file.**
- **Answering is opt-in and there is still no mailbox behind it.**
  `Config.accept_incoming` defaults to False; a caller gets a DM refusal.
  Turned on, kissterm answers, sends `Config.connect_banner`, and shows
  `ANSWERING` in the status bar -- but the session then has nothing to say and
  no commands. That is roadmap P9. **Read P9's regulatory note before building
  a mailbox**: unattended answering and third-party traffic are both regulated
  and vary by country and band.
- **The APRS pane is a placeholder.** Decoding is wired into the frame fan-out
  and APRS traffic shows in the Monitor tab, but the dedicated pane
  (positions, messaging with ack/retry, beaconing) is roadmap P4.
- **YAPP is viable here, unlike in the sibling `bpq-apps` repo.** That project
  documents YAPP as a dead end because BPQ32's terminal emulation filters the
  control characters it needs — that limitation applies to apps running *under*
  BPQ32's stdio, not to a terminal holding a genuinely binary-transparent AX.25
  link. Do not let a future reader conflate the two cases. Roadmap P5.

## 9. Common tasks a future session might do

- **Add a transport:** subclass `FrameTransport` or `SessionTransport` in
  `kissterm/transport/`, add a branch to `build_transport()` in
  `transport/__init__.py` (import it lazily there so a missing optional
  dependency never breaks `import kissterm`), add a worked example to
  `config.toml.example`, and add a `discovery.py` heuristic if it is findable.
  Pick the tier by asking one question: *does this thing connect on its own?*
- **Add a transport backend:** implement `_send_frame`, never `send_frame`.
  See the transmit-gate rules above.
- **Add a pane:** add a `TabPane` in `app.py`'s `compose()`, a `Binding` for
  `ctrl+N`/`fN`, and — if it needs frames — a subscriber on the existing
  fan-out, never a second decode path.
- **Add a setting:** add the field to `Config` in `config.py` (with a loader
  entry so a bad value degrades to the default), then add ONE entry to
  `SETTINGS_SCHEMA` in `kissterm/ui/settings_schema.py`. The Settings pane is
  generated from that list — no widget, validator or save hook to write. A
  config field with no schema entry fails
  `tests/pilot/test_settings.py::test_every_config_field_is_editable_or_deliberately_excluded`,
  which is there precisely because the first, hand-built Settings pane was out
  of date with `Config` on the day it shipped.
- **Change link behaviour:** it is all in `ax25/session.py`. Add a loopback
  test in `tests/unit/test_ax25_link.py` first; that file is the safety net.
- **Debug "the link stalls":** check the modular arithmetic in `_ack_upto`
  first, then whether `_pump()` is reachable from the path you changed, then
  whether `peer_busy` got stuck. Turn on `--log-level debug` and read
  `V(S)/V(R)/V(A)/rc` — `AX25Link.__repr__` prints all four.
- **Debug "nothing in the monitor pane":** the frame never reached
  `Transport.dispatch`. Check the transport's decode-error counter first, then
  `MonitorFilter` (supervisory frames are hidden by default). Run with
  `--log-level debug`: every frame is logged in both directions from
  `send_frame` and `dispatch`, so the log settles whether the frame arrived at
  all before you go looking in the UI.
- **Debug "the connect failed":** read `link.last_error` via
  `AX25Station.link_to()`, and the Monitor tab. A DM means the far end heard
  us and refused — a configuration problem. N2 silence means the path did not
  carry — an antenna, power or propagation problem. These need opposite
  actions from the operator and must never be reported with the same words.
- **Ship something:** update `docs/CHANGELOG.md` with a dated section and a
  `**Files:**` line, and delete the item from `docs/ROADMAP.md`.
