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

Both hardware verification and the remaining protocol checks are complete.
See CHANGELOG's 2026-09-13 verification entry for the authoritative
compressed-range reference and the recorded on-air modulo-128 fallback test.


## P3 — Transports

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
- [ ] **Mercury HF verification against real hardware.** Mercury v2's
  documented VARA-compatible TCP TNC interface is implemented and covered by
  a local control/data socket integration test. Verify an actual ARQ contact
  before treating it as field-ready; this validates radio/audio/PTT setup and
  the modem's live status behavior, which a loopback cannot exercise.
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

Operator feedback on the terminal pane and glossary rendering, from a real
session, not yet acted on:

- [ ] **`LM`/`LB` (and likely any multi-line node reply) render with a
      spurious blank line between every pair of real lines.** Reported
      directly from a real BBS session. The likely cause is in
      `TerminalPane._flush_incoming` (`kissterm/ui/terminal_pane.py`):
      `split = max(buf.rfind(b"\n"), buf.rfind(b"\r"))` treats `\r` and `\n`
      as independent line terminators, so a `\r\n` pair arriving (or
      splitting) across two flushes can be counted as two line ends instead
      of one, rendering an empty line between every real one. Needs a real
      capture of the actual bytes a BBS list command sends (`--log-level
      debug` logs both directions) to confirm before changing the split
      logic -- guess-fixing CR/LF handling here risks reintroducing the
      mid-word split bug this same method's docstring describes fixing.
      Small once the actual byte sequence is captured.
- [ ] **A pager prompt (`<A>bort, <CR> Continue...`) can go missing off the
      bottom of the log until Enter is pressed**, reported directly as the
      last row of output appearing twice and the pager prompt itself
      invisible until a keystroke -- read by the operator as the connection
      having died. Likely related to the same `_flush_incoming`/CR-handling
      area above (a no-trailing-newline prompt sits in the pending buffer
      until the 0.2 s idle timer or `final=True` flush fires) rather than
      `RichLog` auto-scroll, which is already on
      (`auto_scroll=True` in `terminal_pane.py`'s compose). Needs the same
      real byte capture as the item above before attempting a fix --
      likely the same root cause, not two bugs. Small-medium once diagnosed.
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
- [ ] **Named, switchable config profiles.** Outpost stores its settings as
  named "Profiles" (e.g. `Outpost`, `Personal`, `Winlink`) switchable from a
  dropdown on the main toolbar, with a per-switch save policy (always /
  prompt / never) so a shared EOC-station install does not clobber another
  operator's setup by accident. kissterm currently has exactly one
  `config.toml`. Useful for the same reason it is in Outpost: a station PC
  shared across operators or between a home setup and a tactical/EOC setup.
  Lower priority than the items above — a real request would sharpen the
  shape (multiple files vs. named sections in one file, whether Address
  Book/transports are per-profile or shared). Medium.

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

- [ ] **More families.** FBB, KA-Node, DXSpider, Winlink RMS.
      One TOML file each in `kissterm/nodes/data/` -- data, not code. Each needs
      a `detect_prompt`/`detect_banner` that is specific enough not to false-
      match; a wrong family shown confidently is worse than "unknown node",
      because the operator types its commands. Small per family. **JNOS
      shipped `[2026-09-10]`** (see CHANGELOG): banner-only detection (no
      `detect_prompt` -- JNOS's stock prompt can collide with tnc2.toml's
      `cmd:` pattern), all commands `confidence = "recalled"` pending a real
      session -- next candidate for the "verify against live nodes" item
      below, reachable via a BPQ->JNOS hop. **TheNet/X1J shipped
      `[2026-09-18]`** (see CHANGELOG): documented release-4 user commands,
      intentionally with no detection patterns because the available source
      does not establish a safe discriminator; live-node verification remains
      open below.
- [ ] **Verify the shipped references against live nodes.** Entries carrying
      `confidence = "recalled"` in `bpq32.toml` and `tnc2.toml` were written
      from memory, are flagged as such in the UI, and should be corrected from
      a real session -- kissterm will already be logging those (P2). The
      documented entries deserve a check too. **Partially done for
      `bpq32.toml`**: a real `[2026-09-10]` session against WS1EC-15/CCEMA
      promoted `?`/`B`/`C`/`I`/`N`/`P`/`R`/`U`/`MH` to `confidence =
      "verified"` (see CHANGELOG) -- `STATS`/`PING`/`CQ`/`T` stayed
      `"recalled"` (absent from that one node's `?` output, which proves
      nothing either way about other nodes), `BBS`/`CHAT` stayed at the
      family's `"documented"` default (application names, not node commands),
      and `tnc2.toml` is completely untouched. **Needs an operator with a
      real node to connect to** -- not something a coding session can do on
      its own. Cross-checked `[2026-09-10]` against the sibling `bpq-apps`
      repo's own node-map crawl (`utilities/nodemap.json`, 15 real captured
      "?" replies): independently confirmed the same 8 core commands on 12 of
      15 nodes, and added `RMS` at `confidence = "documented"` (60% of those
      nodes list it as a configured application -- common enough across
      independently-run nodes to be worth naming). See `bpq32.toml`'s own
      provenance comment for the full breakdown.
- [ ] **Candidate PBBS/AEA-TNC-mailbox family, not yet shipped.** 3 of the 15
      nodes in that same `nodemap.json` crawl (W1KRP-1, WD1F-1, W1ZE-1) are
      tagged `"type": "BPQ"` by the crawl's own heuristic but returned
      single-letter-with-parenthetical-long-form command sets (`B(ye)`,
      `J(heard)`, `[AEA PK-232M]`) that do not match `bpq32.toml`'s
      `detect_prompt`/`detect_banner` at all -- they read as a PBBS-style
      mailbox and an AEA PK-232 TNC mailbox, respectively. Worth a real family
      of its own eventually, but 2-3 samples from one crawl is not enough to
      write a confident `detect_prompt` yet -- a wrong family shown
      confidently is worse than "unknown node". Needs more captured examples
      before it ships.

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
