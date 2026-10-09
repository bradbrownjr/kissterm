# ROADMAP.md — kissterm

What is still open, in the order it should be done. Shipped work moves to
`CHANGELOG.md` (dated section) and is deleted from this file the same day;
nothing here is ever checked off and left in place.


Waiting on the radio: `docs/ON-AIR-TESTS.md` lists what the operator
still has to try on the air.

**Blockers outside the code:**

- **Winlink CMS does not know kissterm** (2026-09-28). The production CMS
  turns away a client program it does not know, by the name in its SID:
  "Unknown client types are not allowed on production servers -- use
  cms-z.winlink.org" (operator's first Internet session,
  `[kissterm-0.1.325-B2FHM$]`). The published B2F specification
  (winlink.org/B2F) names no developer registry, so how a program
  becomes known is still to be learned; the operator is researching it,
  and it can go in the same request to the Winlink Development Team as
  the API key below. kissterm never borrows another program's SID name.
  **The test server accepts kissterm** (2026-10-02, transcript
  `20261002-134724_KC1JMH_WL2K.log`): cms-z.winlink.org took the same
  SID, `[kissterm-0.1.349-B2FHM$]`, answered the `;PQ:` challenge with
  `CMS>`, and did not refuse after `FF`. The production server had
  refused at that point (`20260928-103900_KC1JMH_WL2K.log`). So the
  refusal is the client-name check alone, not the login or the protocol.
  The same session received real mail: cms-z offered one message (`FC EM
  ED1VSIAJZVYF`, "Weekly Winlink Message Number 453" from KB1TCE) and
  kissterm filed it. So the test server reads the operator's real mailbox,
  at least for incoming mail; it offered one message where APRSLink had
  reported five pending on 2026-09-21.
  # UNVERIFIED: whether an RMS gateway over the radio passes the same
  check to the CMS; whether mail sent through cms-z reaches the Internet;
  and why one message, not five (already collected elsewhere, or the
  test server holds only some). A second I at 14:30 the same day was
  offered nothing, so cms-z had no more for the account.
  **Through the node** (0.1.354-0.1.355, removed in 0.1.356): I logged
  in to WS1EC by SSH and sent `RMS`; the node reached the production CMS
  (`CMS via WS1EC >`, `20261002-161514_KC1JMH_WS1ECSSH.log`), but BPQ's
  Telnet user port echoes every byte and treats 0x08/0x7F as erase
  (LinBPQ `TelnetV6.c`, `InnerProcessData`), so B2F cannot run over it.
  BPQ's binary-clean relay port (`RELAYAPPL`) would need a firewall
  change, and would reach the same CMS that refuses kissterm's SID, so
  the operator chose to get kissterm authorized instead (2026-10-02).

- **Winlink API access key** (2026-09-27). The RMS Gateway list (P2) needs
  a key issued to kissterm by a Winlink administrator. The operator will
  request it once kissterm is polished enough to share its repository or
  site with the request. Everything else is built (2026-09-27, F10 >
  Session > RMS gateways). When the key arrives: set
  `ACCESS_KEY` in `kissterm/winlink/gateways.py`, press Refresh once to
  check the request against the live API, and add that reply's shape to
  the tests.

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
6. **No key binding is added or changed except under the keyboard standard**
   (DESIGN.md section 5), enforced by `tests/unit/test_key_standard.py`.
7. **Keep documentation proportionate.** A CHANGELOG entry is a few lines. A
   new AGENTS.md rule is added when the operator states one, not to narrate a
   fix. Explanations belong in the code's docstrings.

## Finish line: what 1.0 means

1.0 is a packet terminal an unfamiliar operator can install, set up, connect
to a node or BBS with, and read mail on, without hitting a known bug or a key
that does not work in their terminal. Concretely:

- P0 is empty, with every live bug confirmed fixed by the operator.
- The keyboard follows DESIGN.md section 5's standard, enforced by test. Met
  2026-09-23.
- The command catalog covers BPQ32/LinBPQ node, BPQMail and
  BPQChat fully from published documentation, plus JNOS, TheNet/X1J and TNC2
  at their current level. Met 2026-09-23; context-following suggestions
  confirmed by the operator on a live session the same day.
- P7's PyPI, pipx/uv and Raspberry Pi items are done.
- Transports never verified against hardware (serial, Bluetooth, kernel
  AX.25, VARA, Mercury, BLE) are labelled **experimental** in Settings, `--doctor` and SETUP.md
  rather than blocking the release. Met 2026-09-27
  (`transport.EXPERIMENTAL_KINDS`).

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

A live bug the operator reports goes here first, under rule 2 above, with
the date and their words. A bug reported and fixed the same day goes to
CHANGELOG only. As of 2026-10-09: one item open, outside the code
(Winlink's client list); the operator closed the rest.

### P0.1 Reported bugs

Status values: `open`, `fix attempted N` (N attempts, still reported
broken), `awaiting confirmation` (fix shipped, operator has not re-tested).

- **Winlink over the Internet: "unknown client"** (2026-09-28, `open`,
  outside the code): "tested, unknown client." The CMS answered "Unknown
  client types are not allowed on production servers -- use
  cms-z.winlink.org": it does not know kissterm's SID name (Blockers).
  kissterm now says so in plain words. The same session's log held the `;PR:` answer beside the `;PQ:`
  challenge; the answer is no longer logged.

---

## P2 — Messaging client: Mail, Bulletins, Files (milestone 2)

The model is OutpostPM and Winlink on Android (WoAD): the operator opens
kissterm to their messages, not to a prompt. The Terminal becomes one of the
tools that fills the message store, alongside Winlink and scripted BBS
sessions. Requested 2026-09-22.

Starts after P0. The BBS half depends on the per-application command
catalog (`kissterm/nodes/data/`, application families), because a collection script has to know which BBS it is talking to.

### The folder tree

One on-disk store, shown as one tree in the Mail tab. **Folders separate
kinds of mail, never sources** (decided 2026-09-23): an operator has one
home BBS, reachable several ways (WS1EC-15 then BBS, the CCEMA alias,
WS1EC-2 direct, the CCEBBS alias), and Outpost and Winlink Express file all
of it in one place. A message's origin is its `Source:` header, by the
BBS's own callsign, never the route.

```
Mail
  All Inboxes                                       (a view over every Inbox)
  BBS              Inbox  Outbox  Sent  Deleted
  Winlink          Inbox  Outbox  Sent  Deleted
  Local            Inbox  Sent  Deleted             (P9's mailbox; hidden until it ships)
Bulletins          ALL  ARES  WX  ...  Deleted      (by category, with expiry)
Files
  Downloads  Attachments  Received  Deleted
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

The message store (`kissterm/mail/`), the shared folder-tree/list/reader
widget and the Mail, Bulletins and Files tabs shipped 2026-09-23.

#### Winlink

Winlink messages travel as B2F (the FBB B2 forwarding protocol: proposals,
LZHUF-compressed messages, and a challenge-response secure login) over a
byte stream. That fits the existing architecture exactly: **B2F is a
session protocol on top of whatever link is open.** It runs over an
`AX25Link` to an RMS Gateway (packet, kissterm's own state machine), a
`Session` from the VARA transport, or Telnet to the Winlink CMS, via the
same `SessionLinkAdapter` seam the terminal uses. It needs no new transport.

Sources: Winlink's published B2F and secure-login documentation, and **Pat**
(getpat.io, github.com/la5nta/pat, with its protocol library wl2k-go). Pat
is a working open-source Winlink client and the best reference
implementation; wl2k-go is MIT, and its secure login and LZHUF are ported
(2026-09-26, credited in the README). Mark anything taken from its
behaviour rather than from documentation `# UNVERIFIED:` until a live
exchange confirms it.

- [ ] **CMS over Telnet: the first real session.** Built 2026-09-26
  (I on the Mail tab, Send/Receive by Internet; host, port and
  `CMSTelnet` from wl2k-go). The Home BBS by Telnet or SSH came with it. Waiting on the operator's first run (docs/ON-AIR-TESTS.md);
  its transcript becomes `tests/unit/data/winlink/` fixture and settles
  the `# UNVERIFIED:` notes in `winlink/b2f.py` and `winlink_collect.py`.
- [ ] **VARA to an RMS Gateway**, once P3's VARA hardware verification is
  done. Small on top of the two above.
- [ ] **RMS Gateway list: the live fetch.** Built 2026-09-27 except for a
  request against the real API, which needs an access key issued to
  kissterm (Blockers at the top; Pat's key is issued to Pat). Small once
  the key exists.
- **Later:** peer-to-peer Winlink, and scheduled send/receive. The scheduled version
  follows every unattended-transmission rule in AGENTS.md: opt-in, a status
  marker, an interval floor, and every line logged.

#### BBS mail (BPQMail first, then the applications P8 adds)

- **On hold until the operator's Yagi is up** (2026-09-26): retrieval
  filters below need listings from WS1EC-2 (WS1EC's SSH login reaches the
  same BBS, as the 2026-10-02 bulletin capture did).
- [ ] **Retrieval filters beyond `LM`** (NTS traffic for your area,
  bulletins); the P11 notes below describe Outpost's. Medium.
#### Forms

Decided 2026-09-26 (operator approved the plan, and confirmed that the
newer published standards win over bpq-apps' forms), replacing the 2026-09-22
decision to port bpq-apps' `.frm` files with byte-identical output: **each
form copies the published layout its readers expect** -- the Winlink
standard template's text body, with the owning agency's numbering (FEMA
for ICS) -- because several bpq-apps forms are home-made field sets (its
ICS-213 lacks blocks 5, 6 and 8a; its ICS-309 holds one entry) that a
receiving station would not recognise. bpq-apps' strip engine, GYX
WEATHER, MCF720 and PKTNET check-in do match their published formats and
are ported as they are.

A form is a TOML file in `kissterm/mail/data/forms/` rendered by
`kissterm/mail/forms.py` (template syntax is Winlink's `<var name>`, so a
template's `Msg:` text can be pasted in) and shown by one generic
`FormScreen`. It is chosen as the Type in the compose screen; Continue
returns the text to the compose screen to address and save. Nothing
transmits on save. Forms ship as package data; **never fetch forms
automatically** (the Winlink bundle is read by a developer, cited, and
transcribed).

Phases, each shipped and tested on its own. Phases A (the engine,
ICS-213 and ICS-213RR), B (Winlink and PKTNET check-ins) and C (Field
Situation Report, Severe WX, Damage Assessment, Incident Status) and D
(information strips: GYX WEATHER, MCF720, paste any strip, Answer strip
on a reply), E (ICS-309, ICS-214, ICS-205) and F (Radiogram-ICS213, on
the radiogram form rather than as a form file) shipped 2026-09-26.
ROSTER is not shipped: it is bpq-apps' README example, not a form any
net publishes; paste it.

- Decided 2026-10-07: **no PackItForms/PacFORMS wire compatibility**
  (operator: the team uses the standard ARRL, RRI and SKYWARN forms; the
  PacFORMS ICS-213 is a Santa Clara County form, not a standard). Dropped,
  not deferred. The format notes are in git history at the commit that
  added them (`0b31a4a`) if an Outpost-using partner ever asks.

---

## P3 — Transports

Not blocking 1.0 (see the finish line): each is labelled experimental until
verified. Each needs an operator with the hardware or peer; none can be
closed by a coding session.

- [ ] **Serial KISS against a real TNC** (USB-serial, a KPC-3 or TNC2 in
  KISS mode, a NinoTNC). Built and loopback-tested; labelled experimental
  2026-09-29 because no operator has reported one working.
- [ ] **Bluetooth Classic KISS against a real TNC** (Mobilinkd TNC2/TNC3),
  both routes: `rfcomm bind` to the serial transport, and kissterm's own
  RFCOMM socket. Labelled experimental 2026-09-29, as above.

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

## P3a — Beside the radio: starting the modem, and rig control (planned 2026-10-09)

**Why.** Today kissterm runs on one machine and reaches a modem on another
(the operator's Debian LXC to KC1JMH-RR's TNC software over the LAN). Once it
runs on the shack computer itself, it should do what Winlink Express does:
start the modem program when its transport opens (VARA HF/FM, UZ7HO
SoundModem, QtSoundModem, Direwolf, Mercury), and drive the rig over CAT
through Hamlib (key PTT for VARA, set the dial frequency for a contact or an
RMS gateway, show frequency, mode and PTT). This is a "New Features" item:
under rule 1 it starts after P0 is clear, or when the operator asks for a
milestone by name. Approve each milestone before it starts (as P7a).

**Who builds what.** Each milestone is labelled with the model that should
write it:

- **[Sonnet]** -- follows a pattern that already exists in the repo
  (the transport list in `core/radio.py`, `transport/forms.py`, the
  Settings list rows, the phone's sheets) or is a small protocol client
  written against a published spec. Hand Sonnet the milestone text, the
  files it names, and the package `AGENTS.md`.
- **[Opus]** -- anything on the transmit path (PTT is a transmission),
  process lifetime across three operating systems, `core/restart.py`, or
  a security boundary. Opus writes the module and its docstring; Sonnet
  may then fill the UI around it.
- **[Operator]** -- needs the radio, Windows or a Mac; goes to
  `docs/ON-AIR-TESTS.md` the day the code ships.

### The design in one place (read before any milestone)

**No new Settings section.** All of it lives in the existing
**Settings > Radio**, which already holds "Radio in use" and the transport
list. Radio gains two more lists built exactly like the transport list
(New / Edit / Forget, a form per entry, saved through `core/radio.py`):

```
Settings > Radio
  Radio in use        [ vara-hf          v ]
  Transports          vara-hf, direwolf-local, ...     New  Edit  Forget
  Programs            VARA HF, Direwolf                New  Edit  Forget
  Rigs                IC-7300                          New  Edit  Forget
```

A transport's form gains two optional choices, folded under "On this
computer" and shown only for kinds that reach a local program (`tcp`,
`agwpe`, `vara`, `varafm`, `mercury`): **Start program** (a Programs entry,
or none) and **Rig** (a Rigs entry, or none). A transport with neither
behaves exactly as today. Nothing goes into `SETTINGS_SCHEMA`: like
transports these are lists of dicts (`settings_schema`'s docstring says why).

Config shape (`config.toml.example`, all below the top-level settings):

```toml
[[programs]]
name = "VARA HF"
preset = "vara-hf"          # fills path/args defaults per platform
path = 'C:\VARA\VARA.exe'   # this computer's path; ~ and $VAR/%VAR% expanded
args = []                   # a list, never a shell string
cwd = ""                    # empty = the program's own folder
wine = false                # POSIX only: run a Windows .exe under Wine
stop_on_exit = true         # stop it when kissterm closes, only if kissterm started it
keying = "rig_control"      # own_port | rig_control | cat_port (see below)

[[rigs]]
name = "IC-7300"
model = 3073                # Hamlib model number (rigctl -l)
device = "/dev/ttyUSB0"     # or COM4
baud = 19200
ptt = "cat"                 # cat | rts | dtr | none (VOX, or the modem keys)
ptt_device = ""             # RTS/DTR on a different port (a DigiRig, say)
ptt_timeout = 60            # seconds; the watchdog unkeys after this
swr_warn = 2.0              # warn above this during a transmission (if the rig reports SWR)
swr_trip = 3.0              # unkey and close the transmit gate above this; 0 = off
tune_before_connect = false # a carrier: opt-in, gated (see below)
# or, to use a rigctld something else already runs:
# rigctld = "127.0.0.1:4532"

[[transports]]
name = "vara-hf"
kind = "vara"
host = "127.0.0.1"
cmd_port = 8300
data_port = 8301
program = "VARA HF"
rig = "IC-7300"
frequency = ""              # optional home channel set when it opens, e.g. "145.050 FM"
```

**Paths are the station computer's.** One config file belongs to one
machine, so a program entry stores one path. "POSIX and Windows" is handled
by the **presets** (`kissterm/launch/presets.py`): each knows its default
install path and arguments per platform (`win32`, `darwin`, `linux`/BSD),
including VARA under Wine on Linux/macOS, and the form pre-fills them for
the platform kissterm is running on. A phone editing the station's
Settings is editing the *station's* paths, and the form says so.

**One owner per serial port.** Two programs cannot open the same COM port,
and tuning matters even when the modem keys the radio itself (Direwolf,
SoundModem): kissterm still has to put the rig on the channel. Each Rigs
entry starts one `rigctld` (or attaches to one already running) on the
rig's CAT port, and a program entry says how that program keys the radio,
one choice, three answers, in order of preference:

1. **"Its own port"** -- a separate PTT port, VOX, or the sound
   interface's own PTT (CM108, a SignaLink). Nothing is shared, nothing
   to coordinate. The FT-991A works this way over one USB cable: Yaesu's
   driver gives an "Enhanced" COM port for CAT and a "Standard" one whose
   RTS/DTR keys the rig, so `rigctld` takes the first and Direwolf or
   SoundModem the second. This is not universal: an IC-7300 has one COM
   port carrying both, and an FT-817ND has one CAT port on its ACC jack,
   with PTT on the DATA jack keyed by whatever interface is plugged in (a
   second COM port there belongs to the interface cable, not the radio).
   RESEARCH each named rig against its manual before the form says so.
2. **"Through kissterm's rig control"** -- the program talks to the shared
   `rigctld`: Mercury (`-R 2 -A 127.0.0.1:4532`, Hamlib's NET rigctl model;
   Mercury README, branch `mercuryv2`), Direwolf (`PTT RIG 2
   127.0.0.1:4532`), QtSoundModem and UZ7HO SoundModem if they support it
   (RESEARCH, not assumed). For VARA, which has no Hamlib, kissterm keys
   the rig itself from VARA's `PTT ON`/`PTT OFF` notifications (already
   parsed in `transport/vara.py`, `self.ptt`).
3. **"The rig's CAT port itself"** -- the program must own the only port
   (VARA set to key by CAT, SoundModem's RTS on an IC-7300's single port).
   Then kissterm **hands the port off**: with no session up, it stops the
   program, starts `rigctld`, tunes, stops `rigctld`, starts the program
   again and reopens the transport. Only for a program kissterm started
   (it cannot stop one it does not own; it says so instead); the program
   is restarted on every path, failure included. It costs the program's
   startup time (VARA takes seconds) on every channel change, which is why
   it is the last choice and SETUP.md says how to reach 1 or 2 instead.

Talking to `rigctld` instead of linking Hamlib's Python bindings avoids a
dependency that pip cannot install: `rigctld` is a separate binary on every
platform (`apt install libhamlib-utils`, `brew install hamlib`, the
hamlib-w64 installer), found on PATH or at a path in the rig's Advanced
fold, and reported by `--doctor`.

**The antenna tuner and SWR.** Hamlib exposes both (`U TUNER 1` turns a
built-in ATU on, `G TUNE` starts a tuning cycle, `l SWR` reads SWR), but
only some rigs support them (the FT-991A has an internal ATU on HF and
6 m; the FT-817ND has none), so the controls appear only when the rig
reports the capability. **A tuning cycle and most SWR readings are
transmissions**: the rig keys a carrier, on a channel a gateway may be
using. So, by cost:

- **ATU on** after tuning: no RF. Most internal ATUs then recall the match
  stored for that frequency. The default.
- **SWR watched during real transmissions**: read `l SWR` while the modem
  already has the rig keyed, warn when it is above a limit set on the
  rig. Free in airtime. The default. Above a second, higher limit it
  **trips** (next section).
- **Tune before connect**: off by default, a per-rig choice; runs only
  as part of a connect the operator confirmed, with the gate open,
  re-checked when it keys, shown in `RadioReminderScreen` ("Tunes the ATU:
  a few seconds of carrier on 7.101.500"), logged and in the Monitor like
  any transmission. Never automatic on an SWR warning.

**The SWR trip: stop transmitting into a broken antenna.** A wire antenna
that comes down in a storm should not be fed for the rest of an unattended
mail session. When SWR read during a transmission passes `swr_trip`,
kissterm:

1. unkeys the rig (`T 0`) when it is the one keying it (VARA, or a modem
   in case 2), and otherwise stops the modem program if kissterm started
   it (stopping Direwolf or SoundModem drops its RTS); a modem kissterm
   cannot stop is named in the notice as still able to key;
2. **closes the transmit gate** (`tx.py`), so nothing of kissterm's
   transmits again, unattended transmitters included (beacon, answering,
   the tactical ID), and tells a VARA or Mercury modem `ABORT` (a local
   command, no RF) so it stops retrying;
3. **latches**: the status bar shows `SWR TRIP` (with the reading,
   frequency and time) in the error colour until the operator re-arms with
   Ctrl+T, which first asks "SWR tripped at 4.8:1 on 7.101.500 at 14:02.
   Check the antenna. Transmit anyway?" A restart does not clear it
   silently either; the trip is saved to state and shown at the next
   launch.
4. raises a notice, a desktop notification and an Alerts entry, and
   records it in the session transcript and kissterm.log.

Honest limits, stated in GUIDE.md and the setting's help: it is **not
hardware protection**. It reacts at the polling rate (a few readings a
second over CAT, so roughly half a second), most modern rigs already fold
back power at high SWR on their own, and it works only on rigs whose
Hamlib backend reads SWR while transmitting. What it adds is that the
*station stops trying*, which a rig's foldback does not. To avoid false
trips: ignore readings for a moment after key-up and during an ATU cycle,
and trip only on several consecutive readings over the limit. Knowing the
rig is keyed when the modem keys it on its own port (case 1) means polling
`t`; whether a rig reports PTT it did not key over CAT is a RESEARCH item
per rig, and where it does not, the trip covers only transmissions kissterm
keys. Because no other packet or Winlink client is known to do this, it is
a candidate headline for README.md, **once proven on the air**; until then
it is "experimental" there, as AGENTS.md requires.

**Launch timing.** A program starts when its transport is opened (made
"Radio in use", or at launch if it is the active transport and the program
entry says so), never on a timer and never during discovery. Order: try the
transport's own connect; if refused, start the program and retry the
connect with backoff until `start_timeout`; if something else is already
listening, use it and leave it alone at exit (only a process kissterm
started is ever stopped). That is the transport's normal connect, not a
probe, so "VARA's ports are never touched" by discovery still holds.

**What does not change.** kissterm stays a terminal (section 1). Every
transmission still passes the gate: kissterm keys PTT only while the gate
is open and a modem it is talking to asked for it. A modem that transmits
by itself (Direwolf's own beacons, VARA answering while `LISTEN ON`) is
outside the gate and the form says so, as P12 says of fldigi.

### Milestones

- [ ] **M5 [Opus] PTT for VARA, through the gate.** `transport/vara.py`'s
  `PTT ON`/`PTT OFF` drive `T 1`/`T 0` on the transport's rig. Keys only
  while the gate is open, re-checked at the moment of keying (AGENTS.md
  "Re-check at the moment of transmission"); a refused key is logged `TX
  BLOCKED` and announced. Unkey on every exit path: `PTT OFF`, the modem
  socket closing, the transport closing, the gate closing mid-transmission,
  `ptt_timeout` (watchdog), Restart, Shut down, a crash (`atexit` and
  signal handlers). Status bar `PTT` while keyed (both front ends). Mercury
  and Direwolf entries pass the shared `rigctld` on their command line
  instead (M2's preset arguments), so only one keying path exists per
  modem. RESEARCH before writing: VARA's documented PTT setting (whether
  `PTT ON` is sent only when VARA's own PTT is set to the TCP client) from
  EA5HVK's VARA TNC command document; mark what stays inferred
  `# UNVERIFIED:`. Tests on the loopback with a fake VARA and a fake
  rigctld, including the watchdog and gate-closes-while-keyed cases.
  AGENTS.md's unattended-transmission rules gain one line for it.
- [ ] **M5b [Opus] The SWR watch and trip.** Needs M4 and M5. SWR and
  warning read during any PTT kissterm knows of; the trip sequence above;
  the latched `SWR TRIP` state in `tx.py` or beside it (a closed gate with
  a reason, so every existing gate check honours it unchanged); the re-arm
  question, through the `Operator` port so the phone asks it too; the
  status bar field in both front ends, placed under DESIGN.md's status-bar
  rules. RESEARCH first: Hamlib's `RIG_LEVEL_SWR` (which backends
  implement it, whether the value is a ratio or a raw meter reading; the
  FT-991A's `RM6` meter read), and `T 0`'s effect on a rig keyed by RTS on
  another port. Tests with a fake `rigctld` that reports a rising SWR: a
  spike right after key-up does not trip, a sustained one does, the gate
  closes, a beacon timer then sends nothing, Ctrl+T asks before re-arming,
  the latch survives a restart. AGENTS.md gains the rule ("an SWR trip
  closes the gate and only the operator re-arms it").
- [ ] **M6b [Opus] Port hand-off and the tuner.** The case 3 sequence
  (stop program, `rigctld`, tune, stop `rigctld`, restart program, reopen
  transport) as one core method with a `finally` that always restarts the
  program, refused while any session is up, and its progress shown as
  notices. The ATU: capability from `rigctld`'s `\dump_caps`/`U ?`,
  ATU-on after every tune (no SWR watch here: that is M5b), and the
  opt-in tune-before-connect cycle through the gate as described above.
  Tests with the fake modem script from M2 and a fake `rigctld`, including
  a `rigctld` that fails mid-tune (the program must still come back).
- [ ] **M7 [Operator] On the air at KC1JMH-RR.** ON-AIR-TESTS entries, one
  per milestone as it ships: VARA HF started by kissterm on Windows; VARA
  under Wine on Linux; Direwolf and QtSoundModem started on Linux; Mercury
  with the shared `rigctld`; PTT keyed and released on a VARA connect;
  tuning the FT-991A over its Enhanced port while Direwolf keys over the
  Standard port; a port hand-off on a single-port rig; ATU on and SWR
  read during a VARA transmission; an SWR trip, tested safely at low power
  by setting `swr_trip` just under the antenna's normal SWR (never by
  transmitting into an open or shorted feedline); the
  watchdog unkeys a held PTT; frequency set from a contact.

**Decisions of 2026-10-09** (operator):

1. Program paths: **a paired phone may browse the station's files and set
   the path too** (operator, 2026-10-09: "Phone too, understanding that the
   user must use a QR code or hashed link to essentially authenticate that
   they are the owner and have direct access to the station. If we can
   intelligently filter the browse for the expected executables, that may
   help some of the security concerns."). The pairing (QR code or link,
   `serve/`) is the authentication; the browse is filtered to what a program
   could be (executables, per platform, plus the folders to reach them);
   the saved path must be an existing executable file. **Full parity**
   (operator, 2026-10-09: "I don't want to give the user unnecessary
   barriers or they won't use the product"): the phone and web client set
   everything the terminal does, `args` and working folder included, with no
   extra confirmation at the station. The web UI may run on the station
   itself, and the hashed pairing link already proves the user is at it.
2. A modem starts when its transport opens. The operator adds that this
   "should probably change how the application starts and tries to find
   the transport modem": launch tries the transport, starts the program if
   refused, and discovery stays passive (it never starts anything).
3. Hamlib through `rigctld`: `rigctld` is Hamlib's own daemon, so this is
   the widest radio support there is; flrig is not added.
4. SWR trip on by default at 3.0:1 (done in M1's defaults).
5. Tune-before-connect available, off by default, **chosen per band** (a
   rig's `tune_bands`; 20 m and 40 m usually fine, 40 m sometimes wants it,
   80 m best without). M6b reads it per band.

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
- **Out of scope:** igate and digipeater operation. A separate tool if ever.

## P6 — UX (post-1.0)

- [ ] **Python plugin hooks** (on connect, line received, line typed) --
  instead of a macro DSL. Needs a security design before any plugin can
  transmit or touch files. Distinct from the shipped per-station auto-login
  and hop chains.

## P7 — Packaging (1.0)

- [ ] **PyPI release.** Needs: owner account and a version decision.
  Every release, from the first: README, docs/GUIDE.md and SETUP.md read
  true for the version going out, the screenshots are regenerated
  (`scripts/generate_screenshot.py`), and the install section names the
  real install command.
- [ ] **`pipx` / `uv tool install`** verified against the published package
  and documented.
- [ ] **Standalone binaries** -- post-1.0: Windows, macOS and Linux, each
  on x86-64 and ARM64, so an operator installs one file with no Python.
  Built per platform on CI runners (Nuitka or PyInstaller cannot
  cross-compile), with serial, Bluetooth (`bleak`) and the optional
  transports checked on each. **Not a speed fix**: startup time is
  Textual building and styling widgets (2026-09-27, local disk: 0.85 s
  import, 2.4 s to the first screen with about 300 widgets, after the
  Settings form went from 434 widgets to 97), and compiling Python does
  not change that work. A one-file PyInstaller
  build starts slower, since it unpacks itself first. Startup is fixed in
  the code, not by packaging.
- [ ] **Debian package** -- post-1.0.

## P7a — One back end, three front ends (post-milestone 2)

Meet operators where they are: the terminal UI for those at home in one,
a desktop GUI for those who are not, and a browser version for a shelter
laptop, a tablet or a station run from another room. All three drive one
back end, so a protocol fix or a new transport lands everywhere at once.

- Decided 2026-10-07: the web client in a browser (Chrome) is the
  desktop front end; no native desktop GUI and no separate binaries of it.
- [ ] **Parity gaps left in Settings (2026-10-08):** the terminal's Settings
  pane still edits `config.transports`, `credentials` and `scripts` itself;
  move it onto `core.radio` so the two cannot drift. On the phone: the APRS symbol is a searchable dropdown and not the terminal's
  picker, Test cannot probe a serial or Bluetooth TNC (the terminal cannot
  either).

## P8 — Node references (beyond the 1.0 set)

Why references ship as data instead of being harvested: measured at 1200
baud half-duplex, a node's help costs 4.7 s (512 B) to 75 s (8 KB) of
channel time during which nobody else can transmit. See
`kissterm/nodes/reference.py` and AGENTS.md "Airtime is the scarce
resource".

- [ ] **More families:** FBB, KA-Node, DXSpider, Winlink RMS. One data file each, with a detection pattern specific enough never
  to false-match. An application family (`kind = "application"`) also needs
  `entered_by`, and its node family needs the `enter_pattern` /
  `return_pattern` lines that hand the session over (see `bpq32.toml`).
- [ ] **BPQChat and the application hand-off are documented, not seen.**
  `bpqchat.toml` has no captured chat session behind it, and "Returned to
  Node" is from G8BPQ's documentation only. Capture both on a real node.
- [ ] **Verify against live nodes.** `recalled` entries in `bpq32.toml` and
  all of `tnc2.toml`; JNOS (now the mailbox, from its source) and
  TheNet/X1J are unverified. Needs: sessions on real nodes (JNOS: KC1UIX,
  through WS1EC port 8, in `docs/ON-AIR-TESTS.md`).
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


**P11's three items shipped:** message-ID numbering and delivery/read
receipts 2026-10-07, the tactical call with its automatic identification
2026-10-08 (CHANGELOG). This section stays for the Outpost research the
notes below rest on.

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
