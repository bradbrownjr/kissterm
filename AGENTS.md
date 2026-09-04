# AGENTS.md — kissterm

A terminal for KISS TNCs, packet nodes, and HF modems. Python 3.11+, built with
[Textual](https://textual.textualize.io/). Package under `kissterm/`.

This file is the single source of truth for a future session continuing work
WITHOUT prior chat context. Read it top to bottom before touching code.

Companion files: `README.md` (users), `SETUP.md` (operators getting on the air),
`docs/ROADMAP.md` (what is still open), `docs/CHANGELOG.md` (what changed and why).

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
or belongs to nobody and goes to `on_unhandled` — which is the entire input to
the monitor pane, the heard list, and APRS.

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
│   ├── discovery.py         # serial / LAN / Bluetooth autodiscovery
│   ├── doctor.py            # `--doctor` diagnostics
│   ├── monitor.py           # frame -> monitor line, and sanitize()
│   ├── heard.py             # MHEARD table
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

### Untrusted input
- **ALWAYS** put remote-supplied bytes through `monitor.sanitize()` before they
  reach a widget or a log. Every byte in an information field was put there by
  someone else's transmitter and can carry ANSI escapes that repaint the screen,
  set the window title, or inject a terminal response. A corrupt frame off a
  noisy channel produces the same bytes by accident.
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
- **Themes are the one setting with no UI**, because there is no theme system
  yet (roadmap P6). `Config.theme` is read and written but does nothing.
  Everything else in `Config` is editable in the Settings tab; the coverage
  test in `tests/pilot/test_settings.py` fails if a new config field is added
  without one, so that gap cannot silently reopen.
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
  `on_unhandled`. Check the transport's decode-error counter, then whether the
  frame was addressed to us and consumed by a link instead.
- **Ship something:** update `docs/CHANGELOG.md` with a dated section and a
  `**Files:**` line, and delete the item from `docs/ROADMAP.md`.
