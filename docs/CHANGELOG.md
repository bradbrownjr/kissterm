# CHANGELOG.md — kissterm

Format: keep newest at top. One entry per meaningful change. Reference files
touched and any breaking notes.

## [2026-09-05] — Asking to connect is asking to transmit

Three things found while getting ready for the first on-air test.

### Improvements
- **`Ctrl+N` now opens the transmit gate instead of being refused by it.**
  Reported directly: "^n request connection, but it gives me an error that
  transmit is disabled. One would assume that if I'm asking to make a
  connection, transmit would automatically be enabled." That is right, and the
  old behaviour was a dead end -- the one thing the operator wanted was the one
  thing the message would not do. The rule now: the gate stops transmissions
  the operator did NOT initiate (a timer, an incoming call); a **confirmed,
  targeted** request arms it. `Ctrl+D` too, because a DISC we refuse to send
  leaves the far station holding a session open until its own timers give up.
  A bare keystroke with no confirmation and no target still does not arm --
  the manual beacon is unchanged. Arming is never silent: a notification, a
  line in the terminal log, and the status bar.
- **Manual beacon moves to `Ctrl+Shift+B`.** `Ctrl+B` is tmux's default
  prefix, so under a multiplexer -- how a station PC in another room is
  normally reached -- the key never reached the app. Shown in the footer as
  `^B`, the same shape as `^t`/`^n`/`^d`; plain `Ctrl+B` stays bound but
  hidden, since a terminal without the enhanced keyboard protocol sends the
  same byte for both and there is no slash command for the beacon.
- **Clicking the header no longer expands it to three lines.** Textual's
  `Header` grows on click to reveal a title and subtitle; kissterm has
  neither, so the two extra rows showed nothing while pushing the tab bar,
  the panes and the scrollback down by two -- mid-session, because a click
  landed on the top row. Suppressed with `prevent_default`, not by stopping
  the event, so the command palette icon still works (asserted in the test).

**Files:** `kissterm/ui/app.py`, `kissterm/ui/clock.py`,
`tests/pilot/test_transmit_gate.py`, `tests/pilot/test_app_mounts.py`,
`README.md`, `AGENTS.md`

## [2026-09-05] — A connect gives up sooner than a live link does

Asked directly: "How many times will the application retry a connection
attempt? EasyTerm does 10, but that seems high." It was 10 here too -- the
AX.25 2.2 default -- and applied to both cases.

### New Features
- **`connect_retries` (default 5), separate from `retries` (N2, still 10).**
  One number for both is what makes the spec default feel wrong on a connect.
  Giving up early on an ESTABLISHED link throws away a real conversation over
  what may be one car passing between two antennas, so N2=10 earns its keep
  there. Giving up early on a CONNECT costs one keystroke, while each
  unanswered SABM is another transmission on a shared channel aimed at a
  station that is evidently not listening. At the default T1 of 3 s a failed
  connect is now 6 attempts over ~18 seconds instead of 11 over ~33.
  Editable in Settings (F5) and in `config.toml`.

### Improvements
- The debug log's T1 line now names which budget it is counting against, so
  `rc=3 of 5` during a connect is not read as `rc=3 of 10`.

**Files:** `kissterm/ax25/session.py`, `kissterm/config.py`,
`kissterm/__main__.py`, `kissterm/ui/settings_schema.py`,
`config.toml.example`, `tests/unit/test_ax25_link.py`, `AGENTS.md`,
`README.md`

## [2026-09-05] — Diagnostics for a link that does not come up

Prompted by a real question before a first on-air test over a marginal path:
"is there adequate logging to determine what is successful, what frames are
sent and received?" The honest answer was no, so this closes the gap.

### New Features
- **The monitor pane shows both directions.** `FrameTransport` gained an
  `on_sent` fan-out, fired for every frame that gets past the transmit gate,
  and monitor lines now carry a `>` / `<` direction marker. Until now nothing
  kissterm transmitted appeared anywhere on screen, so "the node never
  answered" and "we never actually keyed up" looked identical.
- **The monitor is fed from the transport, not from `station.on_unhandled`.**
  `AX25Station` routes a frame belonging to an open link straight to that
  link, so the UA answering our SABM -- and every frame of a live conversation
  -- never reached the monitor. The pane went quiet at exactly the moment an
  operator most wants to watch it.
- **Every frame is logged in both directions** at DEBUG, from the two choke
  points every frame must pass through (`send_frame` and `dispatch`), so a new
  backend inherits the log rather than having to remember it. A gate-blocked
  frame is logged as `TX BLOCKED`, never as sent. `--log-level debug` now
  writes a usable on-air record to
  `~/.local/state/kissterm/logs/kissterm.log`.
- **A failed connect says why.** A DM refusal ("the node heard us and said
  no") and N2 silence ("the path did not carry") are different problems at
  different ends of the station, and both used to print `*** No connection to
  <call>`. The reason and the attempt count are now shown in the terminal
  pane and in the toast, with a pointer to the Monitor tab.

### Improvements
- **`--log-level debug` no longer uncorks asyncio and Textual.** Only the
  `kissterm` logger tree takes the requested level; the root stays at
  WARNING. Otherwise the twenty frames that matter are buried under thousands
  of lines about selector events, which is the difference between a log an
  operator will read and one they will not.
- **The log opens with a header line** naming the version, callsign and
  transport, so a file mailed in is reconstructible.
- **`AX25Link.connect`'s outer timeout is a backstop again, not a
  competitor.** It fired at exactly the same moment as N2 exhaustion, so it
  sometimes replaced the state machine's own verdict ("no answer from
  WS1EC-15 after 11 tries") with a bare "connect timed out". It now allows one
  extra T1 of slack.
- `AX25Link.last_error` records why a link failed, and
  `AX25Station.link_to()` reaches a link after a failed `connect` returned
  None -- the UI can no longer only be told that something went wrong.

**Files:** `kissterm/transport/base.py`, `kissterm/monitor.py`,
`kissterm/ui/app.py`, `kissterm/ax25/session.py`, `kissterm/ax25/station.py`,
`kissterm/__main__.py`, `tests/unit/test_frame_logging.py` (new),
`tests/pilot/test_monitor_sees_both_directions.py` (new),
`tests/unit/test_ax25_link.py`, `AGENTS.md`, `README.md`

## [2026-09-06] — Fix: the first run could not open the transport it just wrote

Reported from a real first run on 0.1.16. The wizard found the TNC, wrote a
correct-looking config, and then:

    Could not open transport '10.6.26.5:8001':
    TcpKissTransport.__init__() got an unexpected keyword argument 'name'

### Fixed
- **`build_transport` forwarded the config entry's `name` into the
  constructor.** `name` is the operator's label for the entry -- what
  `active_transport` matches on and what the status bar shows -- and no
  transport's `__init__` takes it. Every entry discovery writes carries it, so
  **no wizard-configured transport of any kind could be opened**: not serial,
  not TCP, not Bluetooth. `_ENTRY_ONLY_KEYS` now names the entry-level keys
  that get stripped; everything else is still forwarded, so a typo in a real
  setting still fails loudly rather than being silently ignored. The entry's
  `name` now also wins over the class-derived one, so the config and the
  status bar cannot disagree about which transport is in use.
- **`--doctor` had its own dispatch table, and that is why this shipped.** It
  picked constructor arguments by hand, so it exercised a path the app never
  took and reported the broken config perfectly healthy. It now delegates to
  `build_transport`. A diagnostic that does not exercise the real path is
  worse than no diagnostic, because it is believed.
- **The setup wizard now builds the transport it is about to save**, and
  refuses to print "Saved" if that fails. It is the last point where the
  operator is still sitting there to be told something is wrong.
- **Discovery reported the right service and then wrote the wrong kind.**
  Every TCP find became `kind = "tcp"`, so accepting the AGWPE entry the scan
  offered would have configured a *raw KISS* transport pointed at an AGWPE
  engine -- two framings on one socket, which decodes as garbage rather than
  failing cleanly. Port 8000 now maps to `agwpe`.
- **VARA ports are no longer offered as configurable finds.** `VaraTransport`
  needs a callsign and two ports, neither of which a port scan knows, so a
  VARA command port is reported as found with a note to configure it by hand,
  and a VARA *data* port is no longer listed as a device of its own -- it is
  the other half of the same modem, not a second thing to connect to.

### Why no test caught it
Nothing exercised `build_transport` against an entry the wizard actually
produces. `tests/unit/test_transport_factory.py` now does, for every kind,
plus a static check that walks `discovery.py` and asserts every key it writes
is either an entry-level key `build_transport` strips or a real parameter of
that kind's `__init__`. Reintroducing the original one-word bug fails 17 of
its tests.

**Files:** new `tests/unit/test_transport_factory.py`; changed
`kissterm/transport/__init__.py`, `kissterm/doctor.py`,
`kissterm/discovery.py`, `kissterm/__main__.py`, `AGENTS.md`.

---

## [2026-09-05] — A master transmit switch, and a manual beacon key

Requested: handle the "does not transmit at startup" problem the way other
amateur software does -- an Enable Tx switch like WSJT-X, and a manual beacon
button like JS8Call's heartbeat, both on control keys. That is a better answer
than the previous one, which was a rule ("the timer sleeps a full interval
first") rather than a control the operator can see and press.

### New Features

**`Ctrl+T` -- the master transmit gate** (`kissterm/tx.py`). Closed on launch:
with it closed **nothing** kissterm does can key a radio -- not a beacon, not
answering a call, not connecting, not the terminal send line. The status bar
reads `TX OFF`, with a count of what the closed gate has held, for as long as
that is true.

The part that makes it a guarantee rather than a checkbox is where it lives.
`FrameTransport.send_frame` is now **concrete** and calls a new abstract
`_send_frame`, so the gate check sits in the single place every frame passes
through, whatever produced it -- a pane, a timer, the AX.25 state machine, a
background task, or a backend nobody has written yet. `Session.send` gates the
session tier the same way, because a VARA or Mercury link never produces an
`AX25Frame` and gating only the frame tier would leave every HF modem open. A
test fails if any subclass overrides the public `send_frame`.

A blocked transmission returns normally and is counted, never raised: AX.25
retransmission runs on `call_later` callbacks with nowhere for an exception to
go, and the house rule is that a background task never dies of one. The checks
in the panes and the connect action exist only so the operator is told *why*
nothing happened -- connecting is refused up front rather than after the full
retry budget, which would look like the far station simply not being there.

`Config.tx_armed_at_start` (default false) is the opt-out for a station meant
to run unattended, where a restart quietly taking it off the air is the worse
failure.

**`Ctrl+B` -- send one beacon now.** The timed beacon still waits a full
interval before its first transmission, because launching the app is not a
request to key the radio; this is how the operator says "yes it is, right now"
without shortening the interval or waiting it out, the role JS8Call's
heartbeat button plays. It does not enable the timer and does not need the
timer to be on -- it waives exactly one check, whether the *timer* is enabled,
and nothing else. A closed gate, empty text or a bad destination still refuse.

### Fixed
- **A beacon suppressed by the gate was reported as sent.** The transport
  drops a gated frame silently, so `Beaconer.send_once` returned True and the
  terminal pane logged "Beacon sent" for a frame that never left. `problem()`
  now treats a closed gate as a reason not to beacon. Telling an operator
  something went on the air when nothing did is the one lie a transmit
  indicator must not tell.
- Enabling transmit re-arms a configured beacon, so `Ctrl+T` is enough on its
  own -- otherwise the timer sat running in front of a closed gate, deciding
  every interval to do nothing.
- An incoming call that arrives while transmit is disabled now says so in the
  terminal pane and as a notification. The UA never went out, so the caller is
  talking to nobody, and "somebody called and you could not answer" is exactly
  what an operator wants to find in the scrollback later.
- The README screenshot showed a connected session above a `TX OFF` status
  bar -- a state that cannot occur, teaching the wrong thing about the gate.
  The screenshot fixture arms transmit.

**Files:** new `kissterm/tx.py`, `tests/unit/test_tx_gate.py`,
`tests/pilot/test_transmit_gate.py`; changed `kissterm/transport/base.py`
(concrete `send_frame`, abstract `_send_frame`), `kissterm/transport/agwpe.py`,
`bluetooth.py`, `serial_kiss.py`, `tcp_kiss.py`, `tests/loopback.py` (renamed
to `_send_frame`), `kissterm/beacon.py`, `kissterm/config.py`,
`kissterm/ui/app.py`, `kissterm/ui/terminal_pane.py`,
`kissterm/ui/settings_schema.py`, `scripts/generate_screenshot.py`,
`config.toml.example`, `README.md`, `AGENTS.md`,
`kissterm/transport/AGENTS.md`, and the pilot test helpers.

**Tests:** 369 passing.

---

## [2026-09-05] — Beacons, session transcripts, and remote colour

Three roadmap items built and tested: P9's beacon text, P2's per-session
transcripts, and P2's ANSI-from-remote allowlist. Nothing here has touched a
radio -- P1's hardware verification still outranks everything.

### New Features

**Plain-text beacons (BTEXT)** -- `kissterm/beacon.py`. A short text
transmitted on a timer to an unconnected destination, the oldest convention in
packet for telling a channel you exist.

It is **not** APRS beaconing, and the code, the config and the Settings pane
all say so out loud, because conflating them would put a transmission on the
air the operator did not intend, under their own callsign. Separate
`[beacon]` table, separate section in Settings whose note begins "NOT APRS",
and a test asserting the two enable switches cannot end up sharing a label.

Everything about it follows from "this is unattended transmission":

- Off by default, and silent while `text` is empty whatever `enabled` says --
  an empty beacon is pure channel occupancy.
- **The 10-minute interval floor is enforced in code, twice**: the config
  loader clamps it with a warning, and `Beaconer.interval_seconds` clamps it
  again, because a `Config` built in code bypasses the loader and the floor
  is a courtesy to everyone else on the frequency rather than a preference of
  the operator's.
- The first transmission is one full interval after start, **never at
  startup**. An operator who opens kissterm to check something and quits must
  not have keyed the radio.
- `problem()` is re-checked at send time, not only at start, so text deleted
  under a running beaconer stops going out.
- Every beacon is written into the terminal pane, and `BEACON` sits in the
  status bar for as long as one is armed -- the same honesty rule as
  `ANSWERING`.
- Settings shows what the chosen interval actually costs: "about 2 seconds of
  channel every 10 minutes -- 0.4% of the frequency", from the existing
  airtime estimator.

**Session transcripts** -- `kissterm/session_log.py`, on by default. One
plain-text file per connection under the log directory: everything sent,
everything received, and every link-state change, timestamped, with `>`/`<`/`*`
direction markers so a bare file is readable years later without the code.
The path is printed into the terminal pane when a session starts, because a
file appearing on disk unannounced is a surprise.

A transcript is a convenience and a live link is not, so every write catches
`OSError` and degrades to a silent no-op with the reason kept in `failed`. A
pilot test connects with the log directory deliberately unusable and asserts
the link keeps working. Filenames are *constructed* -- both callsigns are
reduced to `[A-Za-z0-9-]`, capped at 12 characters, `UNKNOWN` if empty --
because `peer` is a callsign asserted by a remote station and a callsign is a
claim, not an identity. Transcripts get fully stripped text, not the coloured
form: `cat` on a log file would run whatever escapes it contained.

**Remote ANSI colour, through an allowlist** -- `kissterm/ansi.py`. A packet
BBS that has painted its menus in colour since 1988 rendered as flat grey,
because `monitor.sanitize` removes every escape sequence. It still does
everywhere text is matched, filtered or logged; the terminal pane now has a
second filter that keeps SGR and nothing else.

Written as an allowlist, not a denylist: the set of sequences a terminal
understands is large and undocumented in practice, and the set that can only
change how a glyph is painted is small enough to enumerate. So colour, bold,
dim, italic, underline, reverse, strikethrough and the 256-colour/truecolour
forms survive; cursor movement, erase, scroll regions, OSC (window title,
clipboard, and OSC 8 hyperlinks -- which are precisely a way to display one
address and open another), DCS, APC, PM, SOS, charset selection and the
terminal *query* sequences whose replies a shell later reads as keystrokes do
not. Anything unrecognised is removed by construction rather than by having
been thought of, which is the property a denylist cannot have.

Three details that are the difference between this working and looking like
it works:

- **A dropped sequence is consumed whole.** Removing the ESC and leaving
  `[2J` behind as literal text is how this class of filter usually fails.
- **An SGR whose every parameter was rejected vanishes**, rather than becoming
  `CSI m` -- which is a reset the sender never asked for.
- **Blink (5, 6) and conceal (8) are not allowlisted.** Photosensitivity is a
  real accessibility hazard and no remote station gets to impose it; text that
  renders invisible is a spoofing primitive, not a formatting choice.

`remote_color = true` by default, and turning it off changes readability, not
safety -- the dangerous sequences are removed on both paths.

### Improvements
- The status bar shows `BEACON` alongside `ANSWERING`.
- `apply_runtime_settings()` on the app is one generic hook the Settings pane
  calls after a save, so adding a setting that needs *doing* rather than
  storing stays "one entry in the schema".

### Fixed
- **`config.toml.example` silently discarded five settings.** Everything
  documented after the `[custom_theme]` header -- `show_local_time`,
  `show_utc_time`, `clock_24h`, `show_date`, `ascii_safe` -- was being parsed
  as a *custom-theme key*, because in TOML a bare key belongs to the last
  table header above it. Anyone who copied the example got a config where
  none of the clock settings applied, and `load_config` is deliberately
  forgiving so nothing said so. The table moved below the top-level scalars,
  and two tests now guard it: the example must load with zero warnings, and
  every top-level `Config` field documented in it must actually parse as
  top-level.
- **`tests/conftest.py` documented an `asyncio_mode = "auto"` that is not
  configured.** Believing it makes a whole test file report "async def
  functions are not natively supported", which reads like a missing
  dependency rather than a missing `@pytest.mark.asyncio`.
- `SessionLog.open()` called twice would leak the first handle and write a
  second header into a live transcript.

### Roadmap hygiene
- Removed the "unattended status indicator" item from P9: the `ANSWERING`
  marker shipped in `[2026-09-04]` and the entry was stale.
- P9's "MAIL FOR" item now says explicitly that the transmit half is done and
  the remaining work is the *content*, so nobody builds a second beaconer
  beside the first.

**Files:** new `kissterm/ansi.py`, `kissterm/beacon.py`,
`kissterm/session_log.py`, `tests/unit/test_ansi.py`,
`tests/unit/test_beacon.py`, `tests/unit/test_session_log.py`,
`tests/pilot/test_transcript_and_color.py`,
`tests/pilot/test_beacon_wiring.py`; changed `kissterm/config.py`,
`kissterm/ui/app.py`, `kissterm/ui/terminal_pane.py`,
`kissterm/ui/settings_pane.py`, `kissterm/ui/settings_schema.py`,
`config.toml.example`, `tests/conftest.py`, `tests/unit/test_config.py`,
`tests/pilot/test_settings.py`, `README.md`, `AGENTS.md`,
`kissterm/ui/AGENTS.md`, `docs/ROADMAP.md`.

**Tests:** 350 passing (was 216).

---

## [2026-09-05] — Roadmap: beacons, mail-for, and a served file area

Requested: beacons with beacon text and "MAIL FOR", plus a place other
stations can download from, with a warning that uploaded content is unvetted.
Roadmapped rather than built, with the parts that are easy to get wrong
written down while they are cheap to change.

### P9 — beacons
- **Beacon text (`BTEXT`) as unproto UI frames** -- the convention for telling
  a channel you exist. Explicitly **distinct from APRS beaconing (P4)**: same
  UI-frame machinery, different destination and payload, and the two must not
  be conflated in config or UI. Off by default (unattended transmission), with
  a minimum interval enforced in code and the airtime estimator used to show
  what a chosen interval costs the channel.
- **"MAIL FOR" beacons** (the W0RLI/FBB convention). Generated at send time
  from the mailbox, never cached -- a beacon advertising already-collected
  mail sends people on a pointless connect. Never beacon an empty list; cap
  the callsign list because it is real airtime at 1200 baud; and back off per
  callsign so a station that never collects is not advertised forever.

### P10 — serving files, and the sharper point under the virus warning
The requested warning is in, and so is the thing underneath it:

**A callsign in AX.25 is a claim, not an identity.** The protocol authenticates
nothing -- any station can transmit any callsign -- so "uploaded by W1AW" is
not evidence, and a per-callsign allowlist is a convenience, never a security
control. Re-serving what other stations uploaded therefore turns the station
into an unwitting distribution point under its own callsign and licence.

- The **curated** area (files the operator deliberately placed) and the
  **received** area (files that arrived over the air) are separate, and only
  the curated one is served by default. Serving uploads is an explicit
  off-by-default opt-in, and is to be built second.
- If opted in, the warning appears at every point content moves: the Files
  tab, the listing served to a remote station, and the transfer itself --
  unvetted, unauthenticated source, scan anything executable, callsign
  unverified.
- Provenance shown without implying verification (claimed callsign, time,
  size, hash).
- **Filename display must defeat spoofing** -- `readme.txt.exe`,
  right-to-left override characters, lookalike Unicode. Names are already
  sanitized on receipt; the display needs the same care.
- Never execute, never auto-open, never preview by extension alone.

### Recorded as a cross-cutting rule
`AGENTS.md` and `DESIGN.md` now carry "a callsign is a claim, not an
identity", because it already applies today -- the heard list, the monitor
pane, APRS positions and incoming connections all show asserted callsigns.
The wording rule: observations may name a callsign plainly; anything that
reads as *attribution* says "claimed".

### Also
P9's preamble still described the answer-then-silence defect that shipped
fixed in `[2026-09-04]`; corrected, and the two completed items removed.

**Files:** `docs/ROADMAP.md`, `AGENTS.md`, `DESIGN.md`.

## [2026-09-05] — Launcher fix, and diagnostics that stop crying wolf

### Fixed
- **`scripts/kissterm-dev` broke in exactly the situation it exists for.**
  It located the repo with `dirname "$BASH_SOURCE"`, which returns the
  *symlink's* directory -- so the moment it was symlinked onto PATH (the usage
  its own comments recommend) it went looking for `~/.local/.venv` and failed.
  Now follows the symlink chain by hand; `readlink -f` is GNU-only and this
  has to work on macOS and BSD too. Verified via the symlink, directly from
  the repo, and from an unrelated working directory.
- **`--doctor` told the operator to install `bleak` to "unlock Bluetooth LE
  TNC discovery and I/O".** BLE is a marked stub that raises -- following that
  advice would install a package and leave them wondering why their TNC4 still
  does not work. Now reported as `[SKIP]` with the truth, and with no remedy
  line, because there is nothing to do.
- **`--doctor` warned about a missing `pyserial-asyncio` while
  `pyserial-asyncio-fast` was installed.** They are alternatives that
  `serial_kiss.py` tries in order, not a checklist; the warning reported a
  problem that did not exist. Collapsed into one `serial async backend` check
  that is OK when either is present. A diagnostic that cries wolf gets ignored
  at the moment it matters.

**Files:** `scripts/kissterm-dev`, `kissterm/doctor.py`,
`tests/unit/test_config.py`.

## [2026-09-05] — Clock: three independent toggles, not an enum plus a flag

### Changed
Flagged directly, and correct: the clock modelled two settings of the same
kind two different ways. `clock_source` was an either/or enum ("local" /
"utc" / "both") while the date got its own boolean beside it -- so **"show
nothing" and "show only the date" were both unreachable**, and the times could
not be turned off at all.

Local time, UTC time and the date are now **three independent toggles**
(`show_local_time`, `show_utc_time`, `show_date`). Any of the eight
combinations is reachable, including none of them for an empty title bar.
**Local time defaults to on**; UTC and the date default to off.

### Fixed by the remodelling
- **The date could belong to the wrong reading.** With both clocks shown, one
  leading date silently belongs to only one of them -- and on the nights the
  local and UTC dates disagree, that is how a log entry lands on the wrong
  day. Now: one time shown gets its own date; both times on the same date
  share one; **both times across midnight each carry their own**
  (`2026-09-05 21:30 / 2026-09-06 02:30Z`). The display widens only at the
  boundary where the ambiguity actually exists.
- With no time shown at all, the date still follows the zone being shown --
  UTC if UTC is on, otherwise local.

### Migration
A `config.toml` still carrying `clock_source` is **migrated, not ignored**
(`local` -> local only, `utc` -> UTC only, `both` -> both), with a warning
naming the new keys. Silently reverting an operator's clock to defaults
because a key was renamed is exactly the surprise `load_config` exists to
avoid. New keys win if both are present; an unrecognised legacy value falls
back to the defaults with a warning.

Also recorded in `DESIGN.md`: if two settings are the same *kind* of choice
they get the same *kind* of control, and never print one value where it could
belong to two things.

**Files:** `kissterm/ui/clock.py`, `kissterm/config.py`,
`kissterm/ui/settings_schema.py`, `config.toml.example`,
`tests/unit/{test_clock,test_config}.py`, `tests/pilot/test_theming.py`,
`DESIGN.md`, `README.md`, `scripts/generate_screenshot.py`, `assets/*.png`.

## [2026-09-05] — DESIGN.md, settings layout, configurable clock

### New Features
- **`DESIGN.md`** -- the visual and interaction schema, which did not exist
  before: color tokens and what each means, the settings column grid, the
  92-column text measure, the shape language, the F-key/Ctrl split and its
  eight-tab ceiling, text and date conventions, and how to change any of it.
  Linked from `README.md`, `AGENTS.md` and `kissterm/ui/AGENTS.md`.
- **A configurable header clock** (`kissterm/ui/clock.py`): local, UTC, or
  **both side by side**; 12- or 24-hour; optional date. Textual's own
  `HeaderClock` is local-only, 24-hour, no date, and a fixed 10 columns wide
  that a date would silently truncate -- `KissTermClock` subclasses it and
  reads `Config` instead.
  - **UTC is always marked** -- `Z` on a 24-hour clock, `UTC` on a 12-hour one
    (`7:05 PM Z` reads wrong; Z is an ISO/24-hour convention). Local time is
    unmarked, the convention a paper log already uses.
  - **`both` is not a novelty**: amateur radio logs and nets run on UTC while
    the operator lives in local time, and doing that arithmetic mid-net is how
    a log ends up an hour wrong.
  - **Dates are ISO 8601**, never locale order, and the date follows the zone
    it sits beside -- around midnight the local and UTC dates differ, and a
    date belonging to the wrong reading puts a log entry on the wrong day.
    There is a test for exactly that boundary.
- **`scripts/kissterm-dev`** -- a launcher that finds the venv itself and works
  from any directory, for symlinking onto PATH without a system-wide install.

### Changed
- **Settings layout.** Station (callsign, aliases) now opens the page, with
  Transports directly beneath it -- identity first, then the radio, then
  tuning. Previously Transports came first and the callsign was below it.
- **A real column grid**: label 26 / control 46 / apply-note 20, with controls
  at a fixed width rather than `1fr` (a control that stretches with the window
  makes the third column drift and the page lose its alignment). Help text
  hangs under the control, not the label.
- **Section headings carry a rule**, body text is capped at 92 columns, and
  rows have a blank line between them. With bold accent text alone the
  sections blurred together while scrolling, and help lines ran the full width
  of a wide terminal, where the eye loses the line start on the way back.
- **Function keys are tabs; Ctrl sequences are actions and modals.** The
  command reference moved from F6 to **Ctrl+R**, freeing the whole F-row for
  the tabs still to come. The footer now shows no function key at all, and a
  test asserts that generally rather than naming one key.

### Roadmap
- **P10 — Application tabs: Mail, Bulletins, Files**, with sub-views
  (inbox/outbox/sent/deleted; downloads/received/local browse/remote listing).
  Records the **F1-F8 ceiling** up front: five tabs exist and three are
  planned, landing exactly on it, so a ninth tab needs a different navigation
  scheme rather than a ninth function key. Also flags that bulletins are
  category-addressed with a lifetime, not just mail with a different name.

**Files:** `kissterm/ui/{clock,app,styles,settings_pane,settings_schema}.py`,
`kissterm/config.py`, `scripts/kissterm-dev`, `config.toml.example`,
`tests/unit/test_clock.py`, `tests/pilot/{test_theming,test_app_mounts,test_terminal_ux}.py`,
`DESIGN.md`, `README.md`, `AGENTS.md`, `kissterm/ui/AGENTS.md`,
`docs/ROADMAP.md`, `assets/*.png`.

## [2026-09-05] — Settings is F5; the command reference moves to F6

Flagged directly, and correctly: once F1..F4 existed as tab-switching keys,
F5 read as "the fifth tab" (Settings) by the same pattern -- but F5 was bound
to the command reference instead, a modal that is not a tab at all. The
inconsistency was mine; fixed rather than defended.

Settings is now `F5 Settings`, matching `F1 Terminal` .. `F4 APRS` exactly.
The command reference -- opened over whatever tab is active, not a tab
itself -- moved to `F6`, still well inside the F1..F8 range every terminal
delivers reliably (F9+ is where that reliability drops off). `Ctrl+5` is kept
as the unlabelled fallback alias alongside the new `F5`, same as `Ctrl+1..4`
already were for the other tabs.

**Files:** `kissterm/ui/app.py`, `tests/pilot/{test_app_mounts,test_terminal_ux}.py`,
`README.md`, `AGENTS.md`, `kissterm/ui/AGENTS.md`, `docs/ROADMAP.md`, `assets/*.png`.

## [2026-09-05] — Theming: 21 built-in themes, config file and Settings UI

Requested directly: full control over the app's colors, from both a config
file (to sync with an external theme-sync tool or dotfiles) and the Settings
UI, with a curated set of popular themes and a default of Tokyo Night.

### New Features
- **`kissterm/ui/themes.py`** curates Textual's own `BUILTIN_THEMES` into
  families: Tokyo Night, Catppuccin (Latte/Frappe/Macchiato/Mocha -- Mocha is
  Catppuccin's own darkest flavor, not a separate family, and is grouped
  accordingly), Nord, Gruvbox, Dracula, Monokai, Solarized, Rose Pine, Atom
  One, Textual's own light/dark, and `ansi-dark`/`ansi-light`. Every entry is
  verified against `textual.theme.BUILTIN_THEMES` by test -- no hex value in
  the catalog was typed in from memory.
- **`ansi-dark`/`ansi-light` render using the terminal emulator's own 16-color
  palette**, not a copied one. This is the actual "sync with my terminal
  theme" feature: there is nothing to keep matched by hand, because it isn't
  a separate palette at all.
- **`theme = "custom"`** reads an exact hex palette from a new
  `[custom_theme]` table in `config.toml` (`Config.custom_theme`, one field
  per `textual.theme.Theme` color). This is the field an external theme-sync
  tool, or values copied by hand from a terminal emulator's own color-scheme
  file, writes into. Defaults to Tokyo Night's own real values, so an
  untouched `[custom_theme]` table looks identical to Tokyo Night rather than
  a jarring default. Not yet editable field-by-field in Settings (roadmap
  P6) -- eleven raw hex inputs was more than this pass wanted to ship
  half-finished.
- **Settings -> Appearance -> Theme**, a dropdown over the same catalog,
  applying live with no restart -- every color in the app was already a
  Textual theme variable (`$primary`, `$accent`, `$background`, ...), which is
  what made this possible without touching a single rule in `styles.py`.
- **The setup wizard offers the same list** after the callsign prompt, Enter
  to keep the default, from the identical catalog Settings uses -- one theme
  list in the app, not two that could drift apart.
- **Default is Tokyo Night** -- the operator's own stated preference, not an
  arbitrary pick.

### Deliberately not done
No fabricated light variant for Tokyo Night, Nord, Gruvbox, Dracula or
Monokai: none of them ship one upstream, and guessing which hexes to flip
would be presenting an invented palette as if it were the real, recognized
theme -- exactly what this project's `# UNVERIFIED:` convention exists to
prevent. `catppuccin-latte`, `rose-pine-dawn`, and `ansi-light` are pointed to
instead as honest light-mode relatives.

### Fixed
- **A stale or hand-typo'd `theme` value in `config.toml` crashed the app the
  instant the Settings tab opened.** `Config.theme` loads any string without
  validating it against the real theme registry (that would need importing
  Textual into the config layer, which stays UI-independent on purpose);
  validation happens later, when the theme is actually applied
  (`themes.resolve_theme_id`, which falls back safely). But `render_settings`
  was setting the Settings dropdown's `Select.value` directly to that
  possibly-invalid string, and Textual's `Select` raises
  `InvalidSelectValueError` for a value outside its own options -- turning a
  cosmetic typo into a crash that took the whole session down. Fixed with
  `_set_select_value`, which falls back to the first offered choice instead;
  this protects every "choice" field in the schema, not just theme.

**Files:** `kissterm/ui/{themes,app,settings_pane,settings_schema}.py`,
`kissterm/config.py`, `kissterm/__main__.py`, `config.toml.example`,
`tests/unit/test_themes.py`, `tests/pilot/test_theming.py`, `README.md`,
`AGENTS.md`, `kissterm/ui/AGENTS.md`, `docs/ROADMAP.md`, `assets/*.png`.

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
