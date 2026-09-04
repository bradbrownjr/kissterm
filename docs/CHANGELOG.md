# CHANGELOG.md — kissterm

Format: keep newest at top. One entry per meaningful change. Reference files
touched and any breaking notes.

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
