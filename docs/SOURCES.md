# Sources: the software at the far end

What kissterm's knowledge of nodes, BBSes and chat servers rests on: the
command references in `kissterm/nodes/data/`, node detection, and the mail
collectors in `kissterm/mail/`. The protocols underneath (AX.25, KISS, APRS,
Winlink B2F, NTS, message forms) have their own source tables in
[PROTOCOL_GUIDE.md](PROTOCOL_GUIDE.md).

The rule (AGENTS.md section 7, "Research a protocol from its source"):
**read the far end's own source first, then confirm against a capture.** A
capture shows one sysop's settings; the source shows the rules. The node
RMS path removed in 0.1.356 is why: a day went to theories about our own
pty before `TelnetV6.c` showed the BPQ Telnet port echoes everything back.

Each command in a reference carries a provenance tier, shown in F10 > Help >
Node commands (`nodes.reference.SOURCE_TIERS`): **verified** (seen on air),
**documented** (the author's documentation or source), **recalled** (from
memory, flagged), **learned** (offered by a node, nothing more known).

## Strength of each kind of source

| Kind | Example | What it settles |
|------|---------|-----------------|
| The software's source | LinBPQ `Cmd.c` | Exact strings, matching rules, abbreviations, what is sysop-only |
| The author's documentation | G8BPQ's node commands page | Intent and meaning; less exact on wording and abbreviations |
| A capture from a real node | WS1EC-15 `?` reply | What one configured install actually sends |
| Memory | -- | Nothing until confirmed; marked `recalled` or `# UNVERIFIED:` |

## BPQ32 / LinBPQ (John Wiseman, G8BPQ)

The primary target: WS1EC-15 (node), WS1EC-2 (BPQMail), and the Chat and
APRS applications on the same install.

**Source:** [g8bpq/linbpq](https://github.com/g8bpq/linbpq), master at
`4b7a47b` (version 6.0.25.41, 2026-09-23), read 2026-10-01 and 2026-10-02.
Several files have CRLF line endings and are ISO-8859; normalise them before
grepping.

| File | What was read there | Used by |
|------|---------------------|---------|
| `Cmd.c` | `COMMANDS[]` (about line 4777): the node command table, minimum lengths, first-match order; `CMDLIST` (the `?` reply's fixed part); `DecodeNodeName`, `SetupNodeHeader` (the `ALIAS:CALL} ` prefix, or `CALL} ` with no alias); "Connected to %s"; `NC` (XID first); `NRPING` | `nodes/data/bpq32.toml` |
| `cMain.c` | `HEADERCHAR` fixed at `}`; application slots must be typed in full | `bpq32.toml` |
| `L4Code.c` | "Returned to Node %s" | `bpq32.toml` `return_pattern` |
| `TelnetV6.c` | Login prompts (`user:`, `password:`, relay `Callsign :`/`Password :`); the server sends IAC WILL ECHO and echoes every byte but the password; BS/DEL erase, LF becomes CR | `mail/collect.py`; why the node RMS path was removed |
| `BBSUtilities.c` | `ListMessage` (four listing shapes); the read's end marker `[End of Message #N from ...]`; the `de CALL>` prompt; the help text; `Output aborted`; the default welcome; prefix-matched commands; `Bye` (sign-off, a second's pause, disconnect) and the disconnect handler saving `lastmsg` either way | `mail/bpqmail.py`, `mail/collect.py` (`sign_off`), `nodes/data/bpqmail.toml` |
| `lzhuf32.c` | The `@winlink.org` suffix on end markers for Winlink-sourced mail | `mail/bpqmail.py` |
| `BBSUtilities.c` | `YAPPSendFile`, `YAPPSendData`, `ProcessYAPPMessage`: `FILES` and `YAPP <name>`; control packets are two bytes (`ENQ 1`, `ACK 1`-`5`, `ETX 1`, `EOT 1`), only `SOH`/`STX`/`NAK`/`CAN` carry a length; data packets `paclen - 2` bytes, a length of 0 meaning none; an upload is taken at the prompt from an `ENQ 1` alone; a `CAN` is answered `ACK 5` and "File Rejected", leaving YAPP mode with no prompt | `yapp.py` |
| `BBSUtilities.c`, `NNTPRoutines.c` | `ListCategories` (`LC`, `%-6s %-3d` nine to a line) and `BuildNNTPList` (bulletins neither killed nor held, by "to"); the list loop's `>` selector and number range; `ProcessSuspendedListCommand` (`A` at a listing page prompt returns to the prompt) | `mail/bulletins.py`, `mail/collect.py` |
| `HanksRT.c` | BPQChat: the long `/` commands and their minimum lengths; `rt_cmd()`'s one-letter commands; the `/H` help text | `nodes/data/bpqchat.toml` |
| `APRSCode.c` | The node's `APRS` command: `?`, `STATUS`, `MSGS`, `SENT`; sysop-only `SEND`, `BEACON`, `ENABLEIGATE`, `DISABLEIGATE`, `RECONFIG` | `bpq32.toml` `APRS` entry |

**Documentation** (www.cantab.net/users/john.wiseman/Documents/):

| Page | Used by |
|------|---------|
| [NodeCommands.html](https://www.cantab.net/users/john.wiseman/Documents/NodeCommands.html) (updated July 2023) | `bpq32.toml` meanings |
| [Commands.htm](https://www.cantab.net/users/john.wiseman/Documents/Commands.htm) (older node commands page) | `bpq32.toml`; its abbreviation rule is superseded by `Cmd.c` |
| [BBSUserCommands.html](https://www.cantab.net/users/john.wiseman/Documents/BBSUserCommands.html) (updated December 2020) | `bpqmail.toml` |
| [ChatServer.html](https://www.cantab.net/users/john.wiseman/Documents/ChatServer.html) | `bpqchat.toml` |
| PATSupport.html, LinBPQ_RMSGateway.html | The removed node RMS path (0.1.354-0.1.355); kept for the ROADMAP Winlink entry |

**Where source and documentation disagreed** (source wins):

- Abbreviations. The documentation capitalises a prefix (`PAClen`); the
  table's first-match order decides. `NR` is NRR, `AP` is APRS, PASSWORD has
  no short form.
- `T`/`TALK` is in neither the table nor the documentation; it was recalled
  and has been removed.
- BPQMail's LH and LK are sysop-only on the web page but were offered to an
  ordinary user on WS1EC-2; kept as user commands.

## JNOS 2.0 (Maiko Langelaar, VE4KLM)

The second target: KC1UIX's node, reachable over AXIP/UDP through WS1EC
port 8.

**Source:** [DigitalHERMES/jnos2](https://github.com/DigitalHERMES/jnos2),
a mirror at `5555864` (2022-06-21), `JNOS_VERSION` "2.0m.5Gz". The official
site, langelaar.net/jnos2, refused connections during the audit
(2026-10-02). **This is older than current JNOS releases**: compare the
version in KC1UIX's greeting, and re-read the official source when it is
reachable.

| File | What was read there | Used by |
|------|---------------------|---------|
| `mailbox.c` | `Mbcmds[]` (the mailbox command table a caller gets); `mbx_parse()` (two-letter forms, digits alone read a message); `putprompt()`, `Mbmenu`, `MbCurrent` (the prompt); `Mbwelcome`, `Mbbanner` (the greeting); `dombexpert()` (XM, XA, XP) | `nodes/data/jnos.toml` |
| `cmdparse.c` | `cmdparse()`: first table entry the typed word is a prefix of | `jnos.toml` abbreviations |
| `bmutil.c` | List, kill and read subtypes (LM, LL, L>, L<, LB, LT, LH; KM, KU; RM, RH) | `jnos.toml` |
| `mboxmail.c` | `dosend()`: SP, SB, ST, SC, SR; the end-of-text rule | `jnos.toml` |
| `mboxcmd.c` | `Mbnrid`: the `ALIAS:CALL ` prefix a NET/ROM caller sees | `jnos.toml` prompt pattern |
| `version.c` | The SID `[JNOS-<version>-B2FHIM$]` and its variants | `jnos.toml` banner pattern |
| `lzhuf.c` | LZHUF compression | `winlink/lzhuf.py` (see PROTOCOL_GUIDE) |

Before this audit `jnos.toml` listed JNOS *console* commands from memory
(`ftp`, `route`, `who`). A caller never sees the console.

## Other references

| Reference | Source | Status |
|-----------|--------|--------|
| TheNet X-1J | G8KBB's [User Guide for TheNet X-1J release 4](https://datenfunk.org/X1J4/userguid.htm), consulted 2026-09-18 | Documented only; deliberately not auto-detected |
| TNC2 command mode | The long-standing TAPR TNC2 command set as cloned by Kantronics, MFJ, PacComm, Timewave | Mostly recalled; no source document cited yet |
| APRS services (`aprs_services/data/`) | Each file cites its service's own page | See each file |
| Raspberry Pi UARTs (SETUP.md section 2) | Raspberry Pi [Configuration > Configure UARTs](https://www.raspberrypi.com/documentation/computers/configuration.html): which UART `/dev/serial0` names per model, `disable-bt`/`miniuart-bt`, `hciuart`, raspi-config's Serial Port; read 2026-10-06 | Documented; not yet tried with a HAT |
| The offline map (`geo/data/`, `scripts/build_basemap.py`) | [Natural Earth](https://www.naturalearthdata.com/) vector data, public domain, the GeoJSON in [nvkelso/natural-earth-vector](https://github.com/nvkelso/natural-earth-vector) `geojson/`: 1:50m coastline, country and state lines, lakes (scalerank 2 or less); 1:10m coastline, US counties, roads (Major and Secondary Highway, Beltway, Bypass), rivers, lakes; fetched 2026-10-06 | Source; simplified (Douglas-Peucker), so a shore is within a few hundred metres zoomed in |
| Midnight Commander theme (`ui/themes.py`) | [mc](https://github.com/MidnightCommander/mc) `misc/skins/default.ini` and `lib/tty/color-internal.c` (colour names to ANSI numbers), commit 23a260a; Linux `drivers/tty/vt/vt.c` `default_red/grn/blu` for the colours; read 2026-10-02 | Source |

## Captures

Sessions from real nodes, kept in the operator's transcripts
(`~/.local/state/kissterm/logs/`) and quoted in the files that rely on them:

| Capture | What it confirmed |
|---------|-------------------|
| WS1EC-15 (alias CCEMA), `?` reply, 2026-09-10 | The node's application list and the eight core commands |
| WS1EC-2 (BPQMail 6.0.23.1) `?` reply, 2026-09-10 | The BBS user command list (`bpqmail.toml`) |
| WS1EC-2 (BPQMail 6.0.23.1) `LC`, `LB> WX` and `R 3104`, over WS1EC's SSH login, 2026-10-02 | Bulletin categories and listing (`mail/bulletins.py`; `tests/unit/data/bpqmail/`) |
| WS1EC-2 (BPQMail 6.0.23.1) bulletin windows `LB> WX 3112-3211`, over WS1EC's SSH login, 2026-10-06 | The window form and the date stop of a first collection (`mail/bulletins.py`, `mail/collect.py`) |
| WS1EC-2 `L` listings, 2026-09-23 to 09-25 | Listing layout, split lines, the read end marker |
| WS1EC-15, 2026-09-13 | The FRMR-to-SABM fallback (`ax25/session.py`) |
| WS1EC-15 session, 2026-09-22 | The node's prompt arriving last, unterminated (`test_terminal_ux.py` replays it) |
| WS1EC-2, 2026-09-24 and 09-25 | A SABM whose UA was lost; message 2801 read back (`test_ax25_link.py`, `test_session_log.py`) |
| bpq-apps repo, `utilities/nodemap.json`, 2026-08-25 | `?` replies from 15 crawled nodes: the core commands on 12, RMS on 9 |

**Still to capture** (each a checkbox in [ON-AIR-TESTS.md](ON-AIR-TESTS.md)
or a ROADMAP item): a JNOS mailbox session (KC1UIX), a BPQChat session, and
the node's APRS command.

## Outpost receipts (2026-10-07)

- Outpost Packet Message Manager 3.7 Users Guide, "Basics", sections 6.8
  (requesting receipts) and 8.5 (receipt settings):
  outpostpm.org/docs/OutpostUserBasics.pdf.
- github.com/rothskeller/packet (branch v4), a client built to interoperate
  with Outpost: `message/payload/outpost.go` (the `!RDR!`, `!RRR!`, `!URG!`,
  `!B64!` flags), `message/receipt/delivrcpt.go` and `readrcpt.go` (the
  `DELIVERED:` and `READ:` titles and bodies), and
  `wppsvr/analyze/testdata/invalid/delivrcpt.yaml` (a sample message). Used
  by `kissterm/mail/receipts.py`. No capture from Outpost itself.

## Modem programs (2026-10-09)

- Mercury README (github.com/rhizomatica/mercury): `mercury` options `-p`
  (ARQ base port, default 8300, data on base+1), `-R`/`-A`/`-P` (Hamlib
  model, rigctl endpoint, PTT method), install at `/usr/bin/mercury` (Debian
  package) or `/usr/local/bin/mercury` (`make install`), `mercury.exe` on
  Windows. Used by `kissterm/launch/presets.py`.
- Hamlib `rigctld(1)` and `rigctl(1)` man pages
  (github.com/Hamlib/Hamlib, `doc/man1/`): the Extended Response Protocol
  (a leading `+`; the echoed command, `Key: value` records, a final
  `RPRT n`), `f`/`F`, `m`/`M`, `t`/`T` (0 RX, 1 TX), `l SWR`, `U TUNER`,
  `G TUNE`, `\chk_vfo`, and `rigctld`'s `-m -r -s -P -p -T -t`. `-T` sets
  the listen address (default ANY): `rigctld_command` always passes it.
  Used by `kissterm/rig/rigctld.py`. Checked against the source, below; no
  capture from a running `rigctld` yet (ON-AIR-TESTS).
- Python `subprocess` documentation: `CREATE_NEW_PROCESS_GROUP` is needed to
  send `CTRL_C_EVENT`/`CTRL_BREAK_EVENT` on Windows; `start_new_session`
  calls `setsid()` on POSIX. Used by `kissterm/launch/supervisor.py`.
  UNVERIFIED: that a Windows GUI modem (VARA) reacts to CTRL_BREAK; the
  supervisor falls back to `kill()` after `STOP_WAIT` either way.
- Direwolf `man/direwolf.1` and `src/config.c` (github.com/wb2osz/direwolf):
  `-c file` ("rather than the default locations"; default `direwolf.conf`
  in the working folder) and `-t n` (text colours, 0 disabled). Its binary
  path is not documented (a package puts it in `/usr/bin`, `make install` in
  `/usr/local/bin`; the Windows folder is a guess). Used by `launch/presets.py`.
- QtSoundModem (github.com/g8bpq/QtSoundModem, `QtSoundModem.cpp`):
  settings are read through `QSettings("QtSoundModem.ini", IniFormat)`, a
  path relative to the working folder, hence `cwd_is_program_folder`. No
  install path or command-line options were found; its path stays a guess.
- VARA HF and VARA FM: the default install folders `C:\VARA\VARA.exe` and
  `C:\VARA FM\VaraFM.exe` from the Winlink and club setup guides found by
  search (winlink.org/sites/default/files/RMSE_FORMS/vara_fm_for_winlink_with_signalink_on_windows_v4_0.pdf,
  vccomm.org VARA FM quick setup guide); EA5HVK's own documentation was not
  read. UZ7HO SoundModem's path is still a guess.
- Hamlib `include/hamlib/rig.h` (`enum rig_errcode_e`, RIG_OK to
  RIG_EACCESS = 22; `RIG_LEVEL_SWR` "arg float [0.0 ... infinite]",
  read-only) and `tests/rigctl_parse.c` (`print_model_list`'s format;
  `chk_vfo` sends no header and no `RPRT` under `+`; `rig_strstatus` in
  `src/misc.c`), read 2026-10-09.
