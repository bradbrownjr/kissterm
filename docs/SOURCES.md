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
| `BBSUtilities.c` | `ListMessage` (four listing shapes); the read's end marker `[End of Message #N from ...]`; the `de CALL>` prompt; the help text; `Output aborted`; the default welcome; prefix-matched commands | `mail/bpqmail.py`, `nodes/data/bpqmail.toml` |
| `lzhuf32.c` | The `@winlink.org` suffix on end markers for Winlink-sourced mail | `mail/bpqmail.py` |
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
| Midnight Commander theme (`ui/themes.py`) | [mc](https://github.com/MidnightCommander/mc) `misc/skins/default.ini` and `lib/tty/color-internal.c` (colour names to ANSI numbers), commit 23a260a; Linux `drivers/tty/vt/vt.c` `default_red/grn/blu` for the colours; read 2026-10-02 | Source |

## Captures

Sessions from real nodes, kept in the operator's transcripts
(`~/.local/state/kissterm/logs/`) and quoted in the files that rely on them:

| Capture | What it confirmed |
|---------|-------------------|
| WS1EC-15 (alias CCEMA), `?` reply, 2026-09-10 | The node's application list and the eight core commands |
| WS1EC-2 (BPQMail 6.0.23.1) `?` reply, 2026-09-10 | The BBS user command list (`bpqmail.toml`) |
| WS1EC-2 (BPQMail 6.0.23.1) `LC`, `LB> WX` and `R 3104`, over WS1EC's SSH login, 2026-10-02 | Bulletin categories and listing (`mail/bulletins.py`; `tests/unit/data/bpqmail/`) |
| WS1EC-2 `L` listings, 2026-09-23 to 09-25 | Listing layout, split lines, the read end marker |
| WS1EC-15, 2026-09-13 | The FRMR-to-SABM fallback (`ax25/session.py`) |
| WS1EC-15 session, 2026-09-22 | The node's prompt arriving last, unterminated (`test_terminal_ux.py` replays it) |
| WS1EC-2, 2026-09-24 and 09-25 | A SABM whose UA was lost; message 2801 read back (`test_ax25_link.py`, `test_session_log.py`) |
| bpq-apps repo, `utilities/nodemap.json`, 2026-08-25 | `?` replies from 15 crawled nodes: the core commands on 12, RMS on 9 |

**Still to capture** (each a checkbox in [ON-AIR-TESTS.md](ON-AIR-TESTS.md)
or a ROADMAP item): a JNOS mailbox session (KC1UIX), a BPQChat session, and
the node's APRS command.
