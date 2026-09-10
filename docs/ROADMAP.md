# ROADMAP.md — kissterm

Prioritized future work. Each item notes status and the file(s) it touches.
Update this file as items are completed — move the completed item's entry
into CHANGELOG.md under a new dated section (`## [YYYY-MM-DD]`) instead of
just checking it off here, so ROADMAP.md only ever shows what's still open.

Phase numbers are labels, not a strict work order. The one real ordering
constraint is that **P1's remaining verification-against-hardware items outrank
everything else** -- the whole stack is proven only against a software loopback
so far, and a bug found on the air could invalidate work built on top of it.

## P1 — Core terminal — DONE (2026-09-04)

Everything P1 called for shipped: the AX.25 connected-mode state machine, KISS
over serial and TCP, the Textual app shell with a connected session, the
monitor pane, the heard list, the first-run wizard with autodiscovery, and
`--doctor`. See docs/CHANGELOG.md `[2026-09-04]` for what was built and how it
was verified.

Both hardware verification and the Mic-E real-capture check called out in
the original version of this section are done -- see CHANGELOG's
`[2026-09-08]` entries ("Connected mode verified against real hardware" and
"Mic-E verified against real traffic..."). What is still open:

- [ ] **Verify the compressed-position `{` cs-byte** (implemented as a
      pre-calculated range in `Position.precalc_range_mi`, not as altitude)
      against a live APRS-IS feed. `kissterm/aprs/position.py`. Small.
- [ ] **Exercise the modulo-128 fallback path on the air.** `Config.modulo`
      accepts 128 and the window ceiling scales with it, covered by
      `test_modulo_128_link` on the loopback. Almost nothing on the air speaks
      SABME, so the DM-answering-SABME fallback in `ax25/session.py::_on_dm`
      is the part most likely to matter and least likely to have been
      exercised. Small.

## P3 — Transports

- [ ] **AGWPE completion — `kissterm/transport/agwpe.py`.** Raw-frame mode
  (DataKind `'K'`) against Direwolf and UZ7HO SoundModem already works. What's
  missing relative to `tcp_kiss.py`: reconnect-with-backoff on a dropped
  socket (today a lost AGWPE connection just goes to `ERROR` and stays
  there), and actually parsing the port-info reply (`'G'`) instead of
  discarding it, so a multi-port AGW engine's port count and descriptions
  reach the setup wizard. Small-to-medium.
- [ ] **BLE (GATT) — new `kissterm/transport/ble_kiss.py`.** The Mobilinkd
  TNC4's BLE mode does not go through `/dev/rfcomm*` — it needs `bleak`
  (already an optional dependency, see `pyproject.toml`'s `ble` extra) and
  real GATT characteristic discovery/subscription work, since KISS bytes
  arrive as BLE notifications rather than a byte stream. Medium-large; no
  reference implementation to lean on yet.
- [ ] **Linux kernel AF_AX25 verification against real hardware.**
  `kissterm/transport/kernel_ax25.py` is implemented (`SessionTransport`,
  for users who already run `ax25d`/`kissattach` and want kissterm as a
  terminal on top of the kernel's own link layer -- see SETUP.md's "kernel
  AX.25 as an alternative" section for when that's the right call) and, as
  of the same session that added Telnet/SSH, actually reachable from the
  app (`KissTermApp.action_connect` via `_SessionLinkAdapter` -- before
  that, `station is None` on this tier meant Ctrl+N did nothing at all,
  for VARA and Mercury too). What is still open is real verification: one
  socket-API detail is marked `# RESEARCH:` in that file (the exact
  bind/connect address tuple shape for `AF_AX25`, which has shifted across
  Python versions), and nothing here has been exercised against a live
  `kissattach` setup. Linux-only, small once someone with that setup can
  test it.
- [ ] **VARA HF/FM verification against real hardware.** The two-TCP-port
  protocol (control + data, see SETUP.md) is documented and a
  `SessionTransport` implementation is planned, but nothing has been tested
  against an actual VARA modem and radio yet — treat any implementation as
  unverified until it has. Effort unknown until that testing happens.
- [ ] **Mercury protocol research.** Mercury (the newer HF soundcard modem
  from the VARA author) has no public protocol documentation as thorough as
  VARA's; this item is "go find out what's actually on the wire" before any
  implementation work can be scoped.
- [ ] **Multi-port TNC handling.** `FrameTransport.ports` already models one
  transport exposing several KISS/AGW ports (Direwolf's `CHANNEL 0`/`CHANNEL
  1`); what's missing is UI to pick which port a new connection or the
  monitor pane uses when more than one is configured. Small, blocked on the
  app shell (P1) existing.
- [ ] **SSH key-based authentication.** `kissterm/transport/ssh.py` supports
  password auth only (shipped -- see docs/CHANGELOG.md). Some hosts require
  a key; needs deciding where a key path and passphrase live in config
  before building it, not guessing a default silently.
- [ ] **SSH host-key verification.** Currently off (`known_hosts=None` --
  see `ssh.py`'s module docstring for why that is a real gap, not an
  oversight). Needs either a trust-on-first-use prompt or a config field to
  pin the expected key.
- [ ] **Cancelling a hung session-transport connect.** The FrameTransport
  path has `_connect_target`/Ctrl+D cancellation for a stuck SABM retry
  loop; `KissTermApp._connect_session_transport` (Telnet, SSH, VARA,
  Mercury, kernel AX.25) has no equivalent yet -- a slow or unreachable
  host has to time out or fail on its own. Small once someone wants it.
- [ ] **AX/IP — a different, lower-priority ask.** Carries actual AX.25
  *frames* over UDP (BPQ32's convention for linking nodes to each other
  over the Internet), so architecturally it is a `FrameTransport` like
  `tcp_kiss.py`, not a `SessionTransport` like Telnet/SSH above -- kissterm
  would run its own state machine over it exactly as it does over KISS.
  Its real use is node-to-node backbone linking, not operator dial-in, so
  it is unlikely to be what an operator actually wants kissterm itself to
  speak; confirm there is a real use case (reaching a specific node whose
  only path in is AX/IP, say) before building it. Medium, and needs the
  wire format sourced from BPQ32's own documentation rather than guessed
  -- mark anything inferred `# UNVERIFIED:` per this repo's rule.

## P4 — APRS

APRS rides on the same AX.25 UI (`UType.UI`) frames every other unproto
traffic uses — decoding it is a payload-format problem sitting on top of
transports and framing that already exist, not a new transport.

The four items originally listed here -- the frame-fan-out subscriber with
message-history/auto-ack/notification, the contacts-list CRUD pane, sending
with ack/retry, and SMS/email compose forms -- all shipped 2026-09-08 and
2026-09-09, as did the shipped gateway-service directory
(`kissterm/aprs_services/`, 17 services as built-in contacts with a
never-transmits template picker on `Ctrl+R`); see CHANGELOG for the dated
entries. What's still open:

- [ ] **Keeping the service directory current.** It ships with a `checked`
  date per service and is explicitly a snapshot, not a liveness probe --
  several entries were reported down by a third-party health check the day
  they were written. There is no mechanism to notice a service that has
  gone away for good, and there deliberately is not one that phones home.
  A periodic manual re-check against each entry's `source` URL is the
  honest answer; a "last checked" column in the picker already tells an
  operator how stale the claim is. Revisit if entries start rotting.

- [ ] **A heard-stations position/map view.** The bearing/distance-list v1
  shipped `[2026-09-09]` (see CHANGELOG: `kissterm/geo.py`, the Heard pane's
  Distance/Bearing columns, sortable by header click) and was extended
  `[2026-09-10]` to cover a plain packet node's grid square in its own
  beacon text, not just APRS positions (`kissterm.locator.find_grid_in_text`)
  -- what's still open is the map itself, see the "text-mode map" item below,
  now narrowed to just that.
- [ ] **GPS integration.** Everything shipped `[2026-09-09]` (see
  CHANGELOG) covers a *fixed* station: static decimal-degree or
  Maidenhead-grid-square position entry in Settings, with a real
  symbol/WIDE-path/Winlink-notify picker around it. A mobile or portable
  operator with a GPS puck has nothing to plug into yet -- this item is
  that missing half, scoped but not built (needs real hardware to verify
  before it could be marked done, same as every other hardware-dependent
  item in this file).
  - **Shape**: a new `kissterm/gps.py`, modeled on `kissterm/hotplug.py`'s
    `SerialPortWatcher` -- `subscribe`/`start`/`stop`, never raises out of
    its own read loop, cheap enough to run continuously. Differs from that
    class in what it does with the port once found: it *opens* it and
    parses a continuous NMEA-0183 sentence stream (GGA for a fix plus
    altitude, RMC for the same fix plus speed/course) rather than just
    enumerating and diffing. This is explicitly NOT a `FrameTransport` --
    no KISS framing involved, a different kind of background reader
    entirely, closer in shape to `serial_kiss.py`'s own read loop than to
    anything in `kissterm/transport/`.
  - **Config**: one new field for the GPS device path (empty means off,
    today's static-position behaviour unchanged). The device picker
    should reuse `discover_serial()`/`list_ports.comports()` -- the same
    enumeration TNC discovery already does -- rather than inventing a
    second one, but with the INVERSE heuristic from `discovery.py`'s
    `_UNLIKELY_SUBSTRINGS`: that list currently down-scores a port
    description containing "gps receiver" *because* it is scoring
    candidate TNCs, so a GPS device picker wants to score those same
    descriptions *up*.
  - **Bluetooth GPS pucks need no new code at all.** Exactly the same
    "pair once with `bluetoothctl`, `rfcomm bind`, then it is an ordinary
    serial device" story SETUP.md already documents for Bluetooth TNCs
    applies unchanged -- confirmed while scoping this, not assumed.
  - **Feed `AprsBeaconer` a live position at send time, never write one
    into `Config.aprs.latitude`/`longitude`.** `AprsBeaconer.build_frame`
    already re-checks everything at the moment of transmission rather
    than trusting state from when it was started (see
    `kissterm/aprs_beacon.py`) -- a GPS fix should plug into that same
    discipline as an optional live-position source the beaconer asks for
    at send time, not by mutating the config fields a Settings save could
    clobber out from under it.
  - **Status bar**: a `GPS FIX` / `GPS NO FIX` marker for as long as the
    reader is running, matching the existing `ANSWERING`/`BEACON`
    convention -- this station is doing something semi-autonomous
    (trusting a hardware fix over what Settings says), so say so on
    screen the whole time it's true.
  - Unblocks the "Smart beaconing" item below, which needs exactly this
    as its position/speed/course source. Large effort; no reference
    implementation in this codebase to lean on.
- [ ] **Smart beaconing.** Speed/heading-aware beacon interval adjustment
  (the SmartBeaconing algorithm most APRS trackers use) — needs the GPS
  integration item above as its position/speed source first. Medium once
  that exists.
- [ ] **A text-mode map.** The realistic v1 -- a sorted bearing/distance-from-me
  list of heard stations -- shipped `[2026-09-09]` as Heard-pane columns; what
  remains is a full map rendering, or a crude ASCII-art radar-style view as a
  lighter stretch goal than a real map. Medium.
- [ ] **Weather and telemetry display.** Decoding is already done --
  `kissterm/aprs/telemetry.py`'s `parse_weather`/`parse_telemetry` and
  `aprs.parse_packet`'s `"weather"`/`"telemetry"` `kind`s -- what's missing
  is a pane that renders a `WeatherReport`/`Telemetry` value at all; nothing
  in `kissterm/ui/` references either type today. Medium.
- [ ] **Sending object reports, with an object selector.** Requested
  directly, for after the beacon Settings work `[2026-09-09]` ships.
  Decoding already exists (`kissterm/aprs/messages.py::parse_object` ->
  `ObjectReport`) but `kissterm/aprs/encode.py` has no matching encoder,
  and there is no UI for picking which of the ~184 symbols in
  `kissterm/aprs/symbols.py` an object should use -- the new filterable
  symbol picker built for the beacon Settings section (`kissterm/ui/
  settings_pane.py`) is the natural widget to reuse rather than building
  a second one. Not scoped further yet -- where in the APRS pane this
  lives, and how an object's own position (not necessarily the operator's
  own) gets entered, are still open questions. Medium-large.
- [ ] **Sending APRS bulletins.** Also requested for after the beacon
  Settings work ships. **Do not confuse this with P10's Mail/Bulletins/
  Files "Bulletins tab"** -- that is BBS-style store-and-forward mail
  reached over an AX.25 connected-mode session; this is the APRS
  convention of a message addressed to `BLNn`/`ANn` (n = 0-9) instead of a
  callsign, sent unproto the same way a position beacon is.
  `kissterm/aprs/messages.py`'s own docstring already notes decode needs
  no special-casing for this ("a message whose addressee happens to be
  BLNn"); `encode.py`'s `message()` likely already produces a valid
  bulletin frame if given a `BLNn`-shaped addressee, unverified. What's
  missing is entirely UI: composing one, and a place to read ones heard
  from other stations that is not just raw APRS-messaging conversation
  history. Small-medium once scoped.
- [ ] **Igate-adjacent features are explicitly out of scope.** kissterm is a
  terminal for a human operator, not an unattended relay — running it as an
  RF-to-APRS-IS igate or a digipeater is a different problem (unattended
  operation, message deduplication, digipeat path handling) with different
  reliability requirements than an interactive TUI is built for. If that need
  arises, it belongs in a separate tool, not bolted onto kissterm.

## P5 — Node and BBS workflow

- [ ] **NET/ROM awareness.** Recognize and display NET/ROM routing broadcasts
  and node lists (`PID_NETROM` in `kissterm/ax25/frame.py` already exists)
  so the UI can offer a "known nodes" picker instead of requiring every
  destination to be typed by hand. Would pair naturally with the node-hop
  chain that already shipped (`AddressBook.Entry.hops`) -- this is what
  would let an operator pick hops from a discovered list instead of typing
  callsigns they already know. Medium.
- [ ] **BBS session helpers** — mail read/send macros for the common
  packet-BBS command dialects (read commands, list-new, send-to-callsign),
  as scriptable macros (see P6) rather than hardcoded parsing, since BBS
  software varies enough that a rigid parser would break constantly. Medium.
- [ ] **YAPP and autobin binary file transfer.** Note for whoever picks this
  up: the sibling `bpq-apps` repo's docs describe YAPP as a dead end
  *specifically for apps running under BPQ32's stdio terminal filter*, where
  the filter's own line-oriented text handling gets in the way of anything
  binary. That constraint does not apply here — kissterm holds a genuinely
  binary-transparent AX.25 connected-mode link of its own, with no terminal
  filter sitting in between, so YAPP (and the simpler autobin) are both
  viable transfer protocols in kissterm even though they were ruled out for
  bpq-apps. Do not let that bpq-apps finding get cited against implementing
  this here — they are not the same situation. Medium-large effort.

## P6 — UX

- [ ] **ASCII-safe mode.** `Config.ascii_safe` and its Settings toggle
  already exist, and `doctor.py` already suggests turning it on for a
  non-UTF-8 locale -- but no code anywhere reads `config.ascii_safe` to
  actually change what gets drawn. The real work -- swapping kissterm's own
  Unicode box-drawing/symbols for 7-bit ASCII when it's set -- is still
  entirely unbuilt; the config plumbing is a shell around nothing yet. Does
  not affect what a remote station sends (see P2's ANSI sanitization, a
  different concern). Small-medium.
- [ ] **Macro/scripting system — Python plugins.** Deliberately not
  linpac's Lisp-ish macro language: a documented plugin API (hook points for
  "on connect", "on line received", "on line typed") that lets a user write
  a normal `.py` file instead of learning a bespoke macro DSL. Medium-large,
  needs a real security think-through before plugins can touch anything
  sensitive. Not to be confused with what already shipped: a per-station
  auto-login (`AddressBook.Entry.script`/`.credential`, sent by
  `KissTermApp._run_connect_script`) and a node-to-node hop chain
  (`AddressBook.Entry.hops`, walked by `_hop_through`/`_hop_to`) -- both
  fixed, no-logic sequences triggered only by "on connect", not a scripting
  language. This item is the general-purpose, arbitrary-hook version of the
  same idea (conditionals, reacting to arbitrary text, running on other
  events besides connect).
- [ ] **`textual serve` remote access.** Let kissterm be reached over a
  browser via `textual serve`, useful for operating a home-station TNC from
  elsewhere. Small — mostly confirming nothing in the transport layer assumes
  a local TTY.

## P7 — Packaging

- [ ] **PyPI release.** Register `kissterm` on PyPI, wire up a release build
  (the `pyproject.toml` here is already shaped for it). Small once P1 is
  solid enough to tag a 0.1.0.
- [ ] **`uv tool install` / `pipx` install paths.** Both should already work
  once published (`[project.scripts]` is set up for it) — this item is
  verifying and documenting them, not building anything new. Small.
- [ ] **Raspberry Pi install note.** Document the ARM-specific serial
  backend fallback (see `kissterm/transport/serial_kiss.py`'s docstring) and
  any Pi-specific `dialout` group / GPIO-UART quirks in SETUP.md. Small,
  mostly documentation — some of it already exists in SETUP.md's Raspberry Pi
  callouts.
- [ ] **Debian packaging.** A `.deb` for users who won't touch pip/pipx at
  all — likely useful for club/EOC-maintained machines that standardize on
  apt-installed software. Medium, unfamiliar territory (packaging tooling,
  not kissterm code).
- [ ] **Self-update check modeled on google-tui's `updater.py`.** Same
  strictness rules as that implementation: never touch uncommitted work,
  fast-forward only, and never block startup on the check (fail silently and
  let the app come up if the check itself fails or is slow). For a
  PyPI-distributed tool this likely means checking PyPI's version metadata
  rather than git, unlike google-tui's git-based updater — needs a decision
  on which distribution channel is authoritative once P7's PyPI item lands.
  Medium.

## P8 — Terminal assistance: know what to type at the node you reached

Packet's usability problem is not the protocol, it is that every node family
has its own command set and a new operator faces a bare `}` prompt with no idea
what is legal.

**Correction to an earlier version of this section**, which said harvesting a
node's own `?` output was "a better source than any table we ship". That was
wrong, on airtime grounds. Measured with `kissterm.nodes.airtime_seconds` at
1200 baud half-duplex, including framing, keyup and turnaround:

| help text | channel time |
|---|---|
| 512 B | ~4.7 s |
| 2 KB | ~18.7 s |
| 8 KB | ~74.9 s |

A verbose node's help is a minute or more during which **nobody else on the
frequency can transmit**. Doing that automatically on every connect, to
populate an autocomplete list, would make kissterm the rudest client on the
band. Shipped references are therefore the **primary** source; harvesting is
opt-in, once per node, and cached forever.

Shipped in `[2026-09-04]` (see CHANGELOG): the `kissterm/nodes/` package with
TOML references for BPQ32/LinBPQ and TNC2-class command mode, passive family
detection from the banner and prompt, the command-reference modal (`Ctrl+R`
today -- it moved off the F-row before Address Book's own F5/F6 shuffle, see
`kissterm/ui/AGENTS.md` rule 16), and the airtime estimator. Still open:

- [ ] **More families.** FBB, JNOS, TheNet/X1J, KA-Node, DXSpider, Winlink RMS.
      One TOML file each in `kissterm/nodes/data/` -- data, not code. Each needs
      a `detect_prompt`/`detect_banner` that is specific enough not to false-
      match; a wrong family shown confidently is worse than "unknown node",
      because the operator types its commands. Small per family.
- [ ] **Verify the shipped references against live nodes.** Entries carrying
      `confidence = "recalled"` in `bpq32.toml` and `tnc2.toml` were written
      from memory, are flagged as such in the UI, and should be corrected from
      a real session -- kissterm will already be logging those (P2). The
      documented entries deserve a check too. Small, and the highest-value item
      here. **Needs an operator with a real node to connect to** -- not
      something a coding session can do on its own.

Shipped in `[2026-09-10]` (see CHANGELOG, three entries): opt-in harvesting
from a connected node (`kissterm/harvested.py`, `HarvestConfirmScreen`), a
packet-terminology glossary sharing the Ctrl+R pane (`kissterm/glossary.py`),
and per-node notes in the Address Book, shown on connect.

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
- [ ] **Notify when a watched callsign is heard.** Hangs off the existing frame
      fan-out and `HeardTable` -- no new decode path. A watchlist in config,
      matched on any frame's source, digipeater path included.
      Rate limiting is the substance of this item, not an afterthought: a
      friend running APRS beacons every minute would otherwise generate a
      notification every minute, and the operator will disable the whole
      feature rather than tune it. Needs, at minimum:
      - a per-callsign cooldown (default on the order of an hour), so "heard
        again" is only reported once per visit rather than once per beacon;
      - a global cap on notifications per hour, so a band opening does not
        produce a wall of toasts;
      - optional quiet hours;
      - suppression while the operator is actively using the app, since a toast
        for a station already visible in the monitor pane is noise.
      Delivery via the existing in-app notification plus optional OS
      notification (`notify-send` / `terminal-notifier`), degrading silently
      where no notifier exists. Mid effort.
- [ ] **Notify on incoming connection and on new mail**, same rate-limiting
      machinery. Small once the above exists.

## P10 — Application tabs: Mail, Bulletins, Files

The three tabs that turn kissterm from a terminal into a station. Each is a
front-end over machinery P9 builds (the mailbox and the file drop); this phase
is the operator-facing half, and it is worth designing the navigation before
any of it is written.

### The F-key ceiling -- raised to F10, but still finite
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
