"""Persistent configuration -- read defensively, write atomically, never brick the app.

kissterm exists partly because linpac and EasyTerm assume a user who is
willing to hand-edit a config file before their first QSO. That assumption
has to die somewhere, and it dies here: the config file is TOML (human-
editable, unlike JSON with no comments, and available for free via the
stdlib `tomllib` reader on 3.11+) but it is treated as advisory input, not
as a contract the program is entitled to crash over.

**Why `load_config()` cannot raise.** A packet terminal is disproportionately
likely to be opened during an emergency -- a net check-in, a winlink message
that has to go out before a generator runs dry, a public-service event where
the operator is not the person who wrote the config. If a stray character
from an earlier hand-edit makes the TOML unparsable, or a future kissterm
version renames a key, the correct behaviour is to fall back to defaults for
whatever is broken, keep going, and tell the user afterward -- not to print a
traceback and exit. `load_config()` therefore repairs the config field by
field: each bad or missing value is replaced with its default and the
problem is appended to `Config.warnings` (and logged), but the function
itself never raises. A `Config` you can always get an object back from is a
prerequisite for a terminal you can always get a prompt back from.

**Why the TOML writer is hand-rolled.** `tomllib` (stdlib, read-only) covers
parsing; nothing in the stdlib writes TOML. This module ships a small writer
purpose-built for the shapes `Config` actually produces (flat scalars, one
level of subtable for `[aprs]`, and arrays of flat tables for `transports`
and `autoconnect`) rather than pulling in `tomli-w` for what is, in the end,
about sixty lines of formatting. The trade-off: **comments a user hand-adds
to their config.toml are not preserved across a save.** `save_config()` does
not round-trip the file text, it regenerates it from the `Config` object, so
any hand-written commentary is gone the next time kissterm writes its
config. `config.toml.example` at the repo root is the place for durable
commentary; the live config file is not.

**CRITICAL SAFETY RULE.** `config_path()`, `log_path()`, and `state_path()`
are backed by module-level constants computed from `platformdirs` **at
import time** -- see the bottom of this module. That means monkeypatching
`platformdirs.user_config_dir` (etc.) *after* `kissterm.config` has already
been imported does nothing; the paths are already baked in. Any headless
test, script, or REPL session that touches this module MUST call
`kissterm._isolate.isolate()` -- which patches `platformdirs` -- **before**
importing anything from `kissterm`, full stop. Never point a cleanup routine
(`shutil.rmtree`, recursive delete, `os.remove` in a loop) at whatever
`config_path()`/`state_path()` returns without first confirming, in that
process, that isolation happened before import. A sibling project of this
author's destroyed a real user's config directory twice by getting this
order backwards in a test. Do not make it three.
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import platformdirs

from .ax25.address import AX25Address, AX25AddressError

APP_NAME = "kissterm"
DEFAULT_PROFILE = "default"
_PROFILE_NAME_RE = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class AprsConfig:
    """APRS beaconing settings -- a subtable, not top-level fields.

    Grouped on its own because it is the one feature cluster a user without
    a GPS-equipped station has to fill in by hand (`latitude`/`longitude`),
    and it is entirely optional: `enabled = false` is the default so a plain
    packet-terminal user never has to look at these fields at all.
    """

    enabled: bool = False
    beacon_interval_minutes: int = 30
    #: APRS symbol table + code, e.g. "/>" for a car, "/-" for a house.
    #: Picked from kissterm.aprs.symbols.SYMBOLS in Settings, not typed
    #: from memory.
    symbol: str = "/>"
    latitude: float = 0.0
    longitude: float = 0.0
    #: Empty uses the fixed position above. A configured GPS requires a live
    #: fix rather than ever falling back to a stale saved coordinate.
    gps_device: str = ""
    #: Use a GPS fix's speed and course to shorten the beacon interval while
    #: moving and report significant turns. This is deliberately off until
    #: an operator opts in: fixed stations retain the predictable cadence
    #: above, and no setting can make an unattended beacon bypass TX gating.
    smart_beaconing: bool = False
    #: SmartBeaconing's moving and stopped rates, plus the speeds that bound
    #: the inverse-speed interpolation. Speeds are knots because NMEA RMC
    #: reports knots directly; no unit conversion should be hidden here.
    smart_fast_rate_seconds: int = 180
    smart_slow_rate_minutes: int = 30
    smart_fast_speed_knots: int = 60
    smart_slow_speed_knots: int = 5
    #: Corner pegging sends a position after a heading change above
    #: ``angle + slope / speed``, never more often than this many seconds.
    smart_turn_angle_degrees: int = 30
    smart_turn_slope: int = 255
    smart_min_turn_seconds: int = 15
    comment: str = ""
    #: Default digipeater path. WIDE1-1,WIDE2-1 is the conventional "new
    #: N-paradigm" path that gets a beacon out one hop then two wide hops
    #: without flooding a whole region the way WIDE7-7 once did.
    path: str = "WIDE1-1,WIDE2-1"
    #: The grid square Settings last showed `latitude`/`longitude` as, purely
    #: for redisplay fidelity -- empty means the operator has only ever used
    #: decimal degrees. Settings defaults to grid-square entry mode showing
    #: this string when it still matches the current lat/lon (recomputed at
    #: render time, not trusted blindly), so switching to Settings does not
    #: show a computed decimal that visually differs from what was typed.
    #: Never read by the beacon itself -- `latitude`/`longitude` remain the
    #: only fields that affect what is transmitted.
    grid_square: str = ""
    #: Append "WINLINK" to the transmitted comment when set. DOCUMENTED, not
    #: inferred: <https://winlink.org/APRSLink> states it directly -- "If you
    #: desire notification of pending Winlink email just add 'WINLINK'
    #: somewhere in your station's position comment (or status text)" -- and
    #: APRSLink then sends a daily APRS alert while mail is waiting. Shipped
    #: as an unverified guess when this field was added; the source was
    #: supplied afterwards and confirmed working on the air, so this is one
    #: of the few protocol details in this codebase that has BOTH a citation
    #: and an operator confirmation behind it. `kissterm/aprs_services/data/
    #: winlink.toml` carries the rest of APRSLink's command set.
    winlink_check: bool = False
    #: SSID to transmit APRS under, overriding the station callsign's own.
    #: Empty means "use `Config.mycall` exactly as it is".
    #:
    #: Operators conventionally separate their APRS identity from their
    #: packet one: `-9` for a car, `-7` for a handheld, `-5` for a phone,
    #: while connected-mode packet runs on the bare call or `-1`. Without
    #: this, kissterm's APRS position reports and messages went out under
    #: whatever SSID the AX.25 station was using, which is both wrong on the
    #: air (a mobile beacon claiming the base station's SSID) and
    #: unfixable without changing the callsign for connected mode too.
    #:
    #: Stored as a string rather than an int so "not set" and "-0" stay
    #: distinguishable -- `-0` is a legal, meaningful SSID (it is the bare
    #: callsign), and an int field would have to pick a sentinel that
    #: collides with it. Validated to 0-15 by the loader; anything else
    #: degrades to empty with a warning rather than putting an illegal
    #: address on the air.
    ssid: str = ""
    #: Whether an incoming APRS message must be addressed to this
    #: station's EXACT identity (base call plus `ssid` above, or one of
    #: `Config.mycall_aliases` verbatim) to count as "for me" -- deciding
    #: whether it opens a tab, gets auto-acked, or raises a notification.
    #: On by default: confirmed against a real station (see
    #: `kissterm.monitor.aprs_message_matches`'s docstring) that this is
    #: how APRS clients actually behave, and matches what most operators
    #: expect -- a message to a DIFFERENT SSID of the same base call is a
    #: different logical persona (a mobile "-9" while this session runs
    #: "-5", say), not this one. Off falls back to the SSID-agnostic
    #: leniency `callsign_matches` still uses everywhere else (MAIL FOR
    #: beacons, an operator's other stated identity checks) -- an explicit
    #: opt-out for an operator who wants every message to any SSID of
    #: their call answered from one running session.
    filter_by_ssid: bool = True

    def source_for(self, mycall: str):
        """The `AX25Address` APRS traffic should be sent from.

        Takes the base callsign from `mycall` and applies `ssid` if one is
        set. Returns the parsed `mycall` unchanged when it is not, so the
        default behaviour is exactly what it was before this field existed.

        Anything unparseable falls back to the station's own address rather
        than raising: a bad SSID in a config file must not stop the operator
        from transmitting under a callsign that is otherwise fine.
        """
        from .ax25 import AX25Address, AX25AddressError

        try:
            base = AX25Address.parse(mycall)
        except AX25AddressError:
            raise
        if not self.ssid.strip():
            return base
        try:
            return AX25Address(base.callsign, int(self.ssid.strip().lstrip("-")))
        except (ValueError, AX25AddressError):
            return base


#: Floor on the beacon interval, in minutes, enforced here and again in
#: `kissterm.beacon.Beaconer.interval_seconds`. A beacon is transmitted under
#: the operator's callsign onto a channel everyone else shares; the floor is
#: a courtesy to them, not a preference of the operator's, so it is a clamp
#: rather than a warning. Ten minutes is the conventional BTEXT interval on a
#: busy VHF channel and is not short.
MIN_BEACON_INTERVAL_MINUTES = 10


@dataclass
class BeaconConfig:
    """Plain-text beacon (BTEXT) -- a periodic unproto UI frame.

    NOT APRS beaconing, which lives in `AprsConfig` and sends a position in
    APRS format to the `APRS` destination. This sends free text to `BEACON`.
    They share the UI-frame machinery and nothing else; see
    `kissterm/beacon.py` for why conflating them would be a transmitting bug
    rather than a cosmetic one.

    `enabled = false` by default because this is unattended transmission
    under the operator's callsign, and `text = ""` by default because there
    is no sensible thing to say on somebody's behalf.
    """

    enabled: bool = False
    #: What goes on the air. Empty means nothing is transmitted, whatever
    #: `enabled` says -- an empty beacon is pure channel occupancy.
    text: str = ""
    interval_minutes: int = 30
    #: Unproto destination. BEACON is the long-standing convention; ID and CQ
    #: are the other two an operator might reasonably pick.
    destination: str = "BEACON"
    #: Digipeater path, e.g. "WIDE1-1". Empty means direct, which is the
    #: right default: a beacon that floods repeaters is the reason beacons
    #: have a bad name.
    path: str = ""
    #: KISS/AGW port for a multi-port TNC.
    port: int = 0


@dataclass
class WatchedCallsignConfig:
    """Passive local alerts for address claims heard in received frames."""

    enabled: bool = False
    callsigns: list[str] = field(default_factory=list)
    cooldown_minutes: int = 60
    hourly_cap: int = 12
    #: Local-clock hours; leave either unset to disable quiet hours.
    #: -1 disables the corresponding quiet-hours boundary (TOML has no null).
    quiet_start_hour: int = -1
    quiet_end_hour: int = -1
    #: A recent key/mouse action means the operator is already looking here.
    active_suppression_seconds: int = 60


@dataclass
class CustomThemeConfig:
    """Exact hex colors for the `"custom"` theme (`kissterm.ui.themes`).

    Field names match `textual.theme.Theme` one-for-one (see
    `kissterm.ui.themes.CUSTOM_THEME_FIELDS`) so this table can be built
    straight from a `Theme` object and read straight back into one, with no
    renaming step to keep in sync by hand.

    Defaults are Tokyo Night's OWN real values (`textual.theme.BUILTIN_THEMES
    ["tokyo-night"]`), not invented placeholders -- selecting `theme =
    "custom"` with an untouched `[custom_theme]` table looks identical to
    Tokyo Night, which is a working example to edit from rather than a blank,
    surprising theme.
    """

    primary: str = "#BB9AF7"
    secondary: str = "#7AA2F7"
    warning: str = "#E0AF68"
    error: str = "#F7768E"
    success: str = "#9ECE6A"
    accent: str = "#FF9E64"
    foreground: str = "#a9b1d6"
    background: str = "#1A1B26"
    surface: str = "#24283B"
    panel: str = "#414868"
    #: Whether Textual should treat this as a dark theme (affects default
    #: contrast choices in a few built-in widgets). Not a color.
    dark: bool = True


@dataclass
class Config:
    """The whole of kissterm's persistent state.

    `transports` and `autoconnect` are lists of plain dicts rather than
    typed dataclasses on purpose: each transport kind (serial, tcp, agwpe,
    bluetooth, kernel, vara) has its own keys, and a new transport kind
    should not require a schema migration here -- it just adds keys nothing
    else looks at. `kissterm.doctor` and the transport constructors are
    where kind-specific keys actually get interpreted.

    `warnings` is populated by `load_config()` and is deliberately *not*
    something a hand-built `Config()` needs to worry about; it exists so the
    UI can show "your config had problems" without the loader needing to
    raise to report them.
    """

    mycall: str = ""
    #: Alternate SSIDs / callsigns this station also answers to -- a personal
    #: mailbox listening on -1 while the main session sits on the bare call,
    #: for instance.
    mycall_aliases: list[str] = field(default_factory=list)
    transports: list[dict[str, Any]] = field(default_factory=list)
    #: `name` of the transport in `transports` that should be opened on
    #: startup. Empty means "ask" (or use whatever discovery finds).
    active_transport: str = ""
    #: Reusable named login snippets (`{"name": ..., "text": ...}`), managed
    #: in Settings and referenced by name from an address-book entry's
    #: `credential` field -- see `kissterm/addressbook.py`. A live reference,
    #: not a copy: change a password here once and every entry that names it
    #: picks up the change on its next connect, which is the entire point of
    #: keeping logins here instead of retyped into each station's script.
    credentials: list[dict[str, Any]] = field(default_factory=list)
    #: Reusable named command sequences (`{"name": ..., "text": ...}`), same
    #: shape and same live-lookup-by-name mechanism as `credentials` and
    #: deliberately kept as a SEPARATE list rather than folded into it: a
    #: credential is a login, one purpose, named for the account it belongs
    #: to ("Personal BBS login"); a script is any sequence of commands sent
    #: after connecting -- a login followed by a node hop, a mailbox check,
    #: whatever an operator does after every connect to some station -- and
    #: naming it for what it DOES ("Check WS1EC mail") is a different act
    #: from naming a login for who owns it. Referenced by name from an
    #: address-book entry's `script_name` field, which is checked AFTER
    #: `credential` and before that entry's own literal `script` text --
    #: see `Entry.script_name`'s docstring for the full precedence.
    scripts: list[dict[str, Any]] = field(default_factory=list)
    #: APRS messaging contacts (`{"name", "callsign", "service", "detail",
    #: "notes"}`) -- deliberately a SEPARATE list from the address book
    #: above and from `autoconnect` below: those are stations you CONNECT to,
    #: this is people/services you MESSAGE over APRS, and conflating the two
    #: would make one entry's fields mean different things depending on
    #: which feature is reading it. See `kissterm/aprs_contacts.py` for the
    #: dict shape and validation; managed from the APRS pane (F4), not
    #: Settings, the same reason the address book moved to its own tab.
    aprs_contacts: list[dict[str, Any]] = field(default_factory=list)
    #: The operator's own saved APRS messages (`{"name", "text", "gateway"}`)
    #: -- see `kissterm.aprs_contacts.CannedMessage`. `gateway` scopes one to
    #: a single shipped service (an id from `kissterm/aprs_services/`); empty
    #: means it shows for every recipient. Separate from `aprs_contacts`
    #: above for the usual reason: a contact is WHO you message, this is WHAT
    #: you say, and one operator's twenty saved lines should not have to be
    #: duplicated onto every contact they might send them to. The shipped
    #: command templates in `kissterm/aprs_services/` are the other half of
    #: the same picker and deliberately do NOT live here -- shipped data
    #: improves when kissterm updates, a copy in the operator's config file
    #: would go stale.
    aprs_templates: list[dict[str, Any]] = field(default_factory=list)
    #: Shipped gateway services the operator has hidden from the APRS pane's
    #: contact list, by directory id. The directory ships seventeen services
    #: and most operators will never use most of them; pressing Delete on a
    #: built-in row has to do SOMETHING sensible, and hiding it is the only
    #: honest option -- a built-in is not stored in `aprs_contacts` and so
    #: cannot be deleted, and refusing outright would make the key look
    #: broken. Nothing is hidden by default, and an id here that no longer
    #: exists in the directory is harmless.
    aprs_hidden_services: list[str] = field(default_factory=list)
    #: Auto-send a message ack (`kissterm.aprs.encode.ack`) when an incoming
    #: APRS message is addressed to us. Defaults to True -- unlike
    #: `accept_incoming` (an open-ended session with an unknown caller) or a
    #: beacon (arbitrary text on a timer), an ack is a single, fully
    #: deterministic reply with no content the operator did not already
    #: choose by nature of two-way APRS messaging existing at all: a message
    #: nobody acks is not "safely" delivered, it is just broken. Still fully
    #: covered by the master transmit gate (`tx_armed_at_start`/Ctrl+T) like
    #: every other transmission in this app, and every auto-ack is written
    #: to the terminal pane exactly like a beacon or a connect-script line --
    #: see `KissTermApp._on_aprs_frame`. Set False for manual-ack-only.
    aprs_auto_ack: bool = True
    #: SMS/email-over-APRS gateway defaults, pre-filled into a new contact's
    #: `callsign` when its service is set to sms/email in the APRS pane's
    #: contact editor (`AprsContactScreen`) -- see `kissterm/aprs_contacts.py`.
    #: **These were deliberately blank until 0.1.182**, on the reasoning
    #: that which gateway callsign is actually running, in what region,
    #: changes over time, and naming one here would be unearned confidence.
    #: They now default to `SMSGTE`/`EMAIL-2` because that objection stopped
    #: applying: `kissterm/aprs_services/` has shipped both since 0.1.60
    #: with their sources and command syntax, so this is a cited default,
    #: not a guess -- the same fact the contact editor's own service picker
    #: already shows.
    #:
    #: What makes naming one safe is that it is ONLY a prefill, and only
    #: into an empty field (`AprsContactScreen._prefill_gateway`): it never
    #: overwrites a callsign the operator typed, it addresses nothing on its
    #: own, and the operator still confirms the contact before anything can
    #: be sent to it. Set either to `""` to turn the prefill off entirely.
    #: A regional gateway is still a per-operator setting, not a fact about
    #: the air -- so this must stay a starting point the editor shows, never
    #: an addressee anything picks up implicitly.
    aprs_sms_gateway: str = "SMSGTE"
    aprs_email_gateway: str = "EMAIL-2"
    #: How a compose-mode message becomes the actual on-air body, as a
    #: `str.format()` template with `{detail}` (the contact's phone number
    #: or email address) and `{text}` (what the operator typed) --
    #: see `kissterm.aprs_contacts.build_message_body`. **UNVERIFIED**: the
    #: `"<phone/address> <text>"` shape is the commonly-documented
    #: convention for these gateways, not a cited spec -- confirm your own
    #: gateway's current format before relying on this operationally, and
    #: edit the template here if it differs.
    aprs_sms_template: str = "@{detail} {text}"
    aprs_email_template: str = "{detail} {text}"
    #: When running with ``--log-level debug``, keep a receive-only APRS-IS
    #: stream open for correlating RF messages with gateway replies. It has
    #: no APRS-IS publish path and never affects the transmit gate.
    aprs_is_watch_debug: bool = False
    #: Max AX.25 info-field size in bytes. 256 is the traditional default;
    #: dropping to 128 or even 64 on a noisy HF path trades throughput for a
    #: much lower chance any given frame needs a retransmit, since a shorter
    #: frame has fewer bits for QRM to hit.
    paclen: int = 256
    #: AX.25 sequence-number mode: 8 (SABM) or 128 (SABME, "extended").
    #: 8 is the default because it is what every BPQ32, KA-Node and TNC2-class
    #: station on the air actually implements. A peer that does not understand
    #: SABME answers DM, and the link falls back to modulo 8 automatically
    #: (see `ax25/session.py::_on_dm`), so setting 128 is safe to try.
    modulo: int = 8
    #: Window size k -- I frames that may be outstanding unacknowledged. Must
    #: stay strictly below `modulo`, because at k == modulo a full window and
    #: an empty one produce identical sequence state and the link jams after
    #: exactly one cycle. `load_config` clamps against whatever `modulo` is,
    #: and `SlidingWindow` enforces the same bound again where the arithmetic
    #: actually lives.
    window: int = 4
    retries: int = 10
    #: N2 for the SABM phase only, deliberately lower than `retries`. Giving up
    #: early on a connect costs one keystroke; giving up early on an
    #: established link throws away a real conversation. See
    #: `ax25/session.py::DEFAULT_CONNECT_RETRIES`.
    connect_retries: int = 5
    #: T1: how long to wait for an ack before retransmitting (seconds).
    t1: float = 3.0
    #: T2: how long to delay an ack in case an outgoing I-frame can piggyback
    #: it instead (seconds).
    t2: float = 3.0
    #: T3: idle-link keepalive poll interval (seconds).
    t3: float = 300.0
    #: Free-text filter applied to the monitor pane, e.g. "APRS" or a callsign.
    #: Open the master transmit gate at startup. FALSE by default, the way
    #: WSJT-X's "Enable Tx" resets every launch: a fresh start cannot key a
    #: radio until the operator presses Ctrl+T. Set true only for a station
    #: meant to run unattended, where a restart silently taking it off the
    #: air would be the worse failure. This is the one master switch --
    #: closed, nothing transmits, including the terminal send line. See
    #: kissterm/tx.py.
    tx_armed_at_start: bool = False
    #: Answer connections from other stations. OFF by default and deliberately
    #: so: answering is UNATTENDED TRANSMISSION under your callsign, and a
    #: fresh install must not start doing that on its own. The operator is the
    #: control operator; see docs/ROADMAP.md P9 for the regulatory note.
    accept_incoming: bool = False
    #: Sent to a station that connects to us, when `accept_incoming` is on.
    #: BPQ32 calls this CTEXT. Without it a caller gets a link that opens into
    #: silence and cannot tell a working link from a broken one.
    connect_banner: str = (
        "Welcome. This is an unattended kissterm station.\r"
        "There is no mailbox here yet. 73\r"
    )
    monitor_filter: str = ""
    #: Write a plain-text transcript of every connected session. On by
    #: default: the operator can already read the same text in the scrollback,
    #: so this changes how long it survives, not who can see it, and a station
    #: log is ordinary amateur practice. The path is shown in the terminal
    #: pane when a session starts, so it is never a surprise. Local only --
    #: nothing about this reaches the air.
    log_sessions: bool = True
    #: Empty means "use log_path()" -- see that function below.
    log_dir: str = ""
    #: A `kissterm.ui.themes.THEME_CATALOG` id, or `"custom"` to use
    #: `custom_theme` below. An unrecognised value falls back to
    #: `kissterm.ui.themes.DEFAULT_THEME` with a warning -- see
    #: `themes.resolve_theme_id`, which is the actual validation; this
    #: module does not duplicate Textual's theme registry to check against.
    theme: str = "tokyo-night"
    #: Only read when `theme == "custom"`. See `CustomThemeConfig`.
    custom_theme: CustomThemeConfig = field(default_factory=CustomThemeConfig)
    #: Header clock. Local time, UTC time and the date are three INDEPENDENT
    #: toggles, not one either/or setting with the date bolted on: an operator
    #: may want UTC only, both (amateur radio logs and nets run on UTC while
    #: the operator lives in local time), local plus the date, or -- all three
    #: off -- an empty header. See `kissterm.ui.clock.format_clock`.
    show_local_time: bool = True
    show_utc_time: bool = False
    #: 24-hour clock. True by default because amateur radio convention is
    #: 24-hour, especially for anything UTC.
    clock_24h: bool = True
    #: Show the date beside the clock, always ISO 8601 (`YYYY-MM-DD`) -- never
    #: locale order, which is ambiguous across the international audience
    #: packet actually has.
    show_date: bool = False
    #: Force plain ASCII box-drawing and no emoji/Unicode glyphs, for a
    #: terminal (an old TTY, a serial console, some SSH clients) that mangles
    #: anything past code page 437.
    ascii_safe: bool = False
    #: Let a remote station's ANSI colour through to the Terminal pane.
    #: Only SGR (colour, bold, underline) survives, and only via the
    #: allowlist in `kissterm.ansi` -- cursor movement, screen erase, window
    #: title and clipboard sequences are removed whatever this is set to.
    #: On by default because a packet BBS's menu colour is information its
    #: sysop put there on purpose; turn it off for a terminal that renders
    #: colour badly, or to see exactly the bytes a node sent.
    remote_color: bool = True
    #: Let the Terminal pane's Address Book and the APRS pane's contact list
    #: open themselves on a terminal wide enough to keep the chat or session
    #: column at 40 columns beside them -- 80 columns overall, the standard
    #: terminal width. See `kissterm/ui/slideouts.py` for the arithmetic.
    #: `Ctrl+G` still opens and closes either at any width, and doing so takes
    #: the decision away from this setting for the rest of the session.
    #: Turn it off to have both start closed however wide the terminal is.
    slideouts_auto_open: bool = True
    aprs: AprsConfig = field(default_factory=AprsConfig)
    beacon: BeaconConfig = field(default_factory=BeaconConfig)
    watched_callsigns: WatchedCallsignConfig = field(default_factory=WatchedCallsignConfig)
    #: Saved connect targets: dicts with at least a "target" callsign and
    #: optionally a "path" (digipeater route) and a "transport" name.
    autoconnect: list[dict[str, Any]] = field(default_factory=list)
    #: Populated by `load_config()`; never written to the file. See the
    #: module docstring for why this exists instead of an exception.
    warnings: list[str] = field(default_factory=list, repr=False, compare=False)
    #: Selected only before startup.  This is path-routing metadata, never a
    #: setting in the TOML payload, so a Settings save cannot switch profiles.
    profile_name: str = field(default=DEFAULT_PROFILE, repr=False, compare=False)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
#
# Computed once, at import time -- see the CRITICAL SAFETY RULE in the module
# docstring. `kissterm._isolate.isolate()` must run before this module is
# first imported in any test or script that should not touch a real user's
# files.

_CONFIG_DIR = Path(platformdirs.user_config_dir(APP_NAME))
_STATE_DIR = Path(platformdirs.user_state_dir(APP_NAME))
_DATA_DIR = Path(platformdirs.user_data_dir(APP_NAME))


def validate_profile_name(name: str) -> str:
    """Return a conservative named profile, or reject unsafe input.

    Lowercase ASCII names make path mapping one-to-one on case-insensitive
    filesystems.  ``default`` is deliberately reserved for the historical
    ``config.toml`` path rather than being a file in the profiles directory.
    """
    if not isinstance(name, str) or not _PROFILE_NAME_RE.fullmatch(name):
        raise ValueError("profile names use lowercase letters, digits, _ and - (1-32 chars)")
    return name


def _profile_directory() -> Path:
    """Return the named-profile directory only when it is a real directory.

    A profile name cannot introduce a path component, but a symlinked
    ``profiles`` directory could still redirect it onto the default config or
    another file. Named profiles refuse that indirection.
    """
    directory = _CONFIG_DIR / "profiles"
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise OSError(f"refusing unsafe profiles directory: {directory}")
    return directory


def _named_profile_path(name: str) -> Path:
    """Return a safe, unambiguous TOML path for a named profile.

    Lowercase input prevents an operator from creating two names that differ
    only by case, but an existing mixed-case file can still collide on a
    case-insensitive filesystem.  Refuse that ambiguity rather than reading
    or replacing whichever file the filesystem happens to select.
    """
    directory = _profile_directory()
    filename = f"{name}.toml"
    if directory.exists():
        for entry in directory.iterdir():
            if entry.name.casefold() == filename.casefold() and entry.name != filename:
                raise OSError(f"refusing case-colliding profile path: {entry}")
    path = directory / filename
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise OSError(f"refusing unsafe profile path: {path}")
    return path


def config_path(profile: str = DEFAULT_PROFILE) -> Path:
    """Where a selected profile lives; default preserves ``config.toml``."""
    if profile == DEFAULT_PROFILE:
        return _CONFIG_DIR / "config.toml"
    name = validate_profile_name(profile)
    return _named_profile_path(name)


def log_path() -> Path:
    """Where session logs go by default (overridden by `Config.log_dir`)."""
    return _STATE_DIR / "logs"


def state_path() -> Path:
    """Where other persistent-but-not-config data goes (heard lists, etc.)."""
    return _DATA_DIR


def mail_path() -> Path:
    """Root of the message store (`kissterm/mail/`): Mail, Bulletins, Files."""
    return _DATA_DIR / "mail"


def find_credential(config: Config, name: str) -> str:
    """The current text of the saved credential named `name`, or `""`.

    A live lookup, not a cached copy -- see `Config.credentials`'s
    docstring for why. Returns `""` for a name that no longer exists (the
    credential was deleted in Settings after an address-book entry was
    saved pointing at it) rather than raising: a connect script sending
    nothing is a much smaller problem than a connect that crashes the app.
    """
    if not name:
        return ""
    for entry in config.credentials:
        if entry.get("name") == name:
            return str(entry.get("text", ""))
    return ""


def find_script(config: Config, name: str) -> str:
    """The current text of the saved script named `name`, or `""`.

    Same live-lookup shape as `find_credential`, over the separate
    `Config.scripts` list -- see that field's docstring for why the two
    are kept apart rather than one list serving both purposes.
    """
    if not name:
        return ""
    for entry in config.scripts:
        if entry.get("name") == name:
            return str(entry.get("text", ""))
    return ""


# ---------------------------------------------------------------------------
# Loading -- defensive by construction, see module docstring
# ---------------------------------------------------------------------------


def load_config(path: Path | None = None, *, profile: str = DEFAULT_PROFILE) -> Config:
    """Load `Config` from TOML at `path` (default `config_path()`).

    Never raises. A missing file yields plain defaults with no warnings (a
    first run is not an error). A present-but-broken file -- bad syntax, a
    field of the wrong type, an invalid callsign -- yields defaults for
    whatever is broken plus an entry in the returned `Config.warnings` for
    each problem, and the same problems are logged. Every field is validated
    independently, so one typo does not take the rest of a working config
    down with it.
    """
    if path is not None and profile != DEFAULT_PROFILE:
        raise ValueError("pass either path or profile, not both")
    warnings: list[str] = []
    raw: dict[str, Any] = {}

    if path is None:
        try:
            path = config_path(profile)
        except (OSError, ValueError) as exc:
            cfg = Config(profile_name=profile)
            cfg.warnings.append(f"named profile {profile!r}: could not read safely ({exc})")
            logger.warning("config: %s", cfg.warnings[0])
            return cfg

    if path.exists():
        try:
            with path.open("rb") as fh:
                loaded = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            warnings.append(f"{path}: malformed TOML ({exc}); using defaults")
            loaded = {}
        except OSError as exc:
            warnings.append(f"{path}: could not read ({exc}); using defaults")
            loaded = {}
        if isinstance(loaded, dict):
            raw = loaded
        else:
            warnings.append(f"{path}: top level is not a table; using defaults")

    cfg = Config(profile_name=profile)
    if profile != DEFAULT_PROFILE:
        marker = raw.get("profile")
        if marker != profile:
            if path.exists():
                warnings.append(f"{path}: does not identify profile {profile!r}; using defaults")
            raw = {}
    cfg.mycall = _load_callsign(raw.get("mycall", ""), "mycall", warnings)
    cfg.mycall_aliases = _load_callsign_list(raw.get("mycall_aliases", []), warnings)
    cfg.transports = _load_dict_list(raw.get("transports", []), "transports", warnings)
    cfg.active_transport = _load_str(raw, "active_transport", cfg.active_transport, warnings)
    cfg.credentials = _load_dict_list(raw.get("credentials", []), "credentials", warnings)
    cfg.scripts = _load_dict_list(raw.get("scripts", []), "scripts", warnings)
    cfg.aprs_contacts = _load_dict_list(raw.get("aprs_contacts", []), "aprs_contacts", warnings)
    cfg.aprs_templates = _load_dict_list(raw.get("aprs_templates", []), "aprs_templates", warnings)
    cfg.aprs_hidden_services = _load_str_list(
        raw.get("aprs_hidden_services", []), "aprs_hidden_services", warnings
    )
    cfg.paclen = _load_int(raw, "paclen", cfg.paclen, warnings)
    cfg.modulo = _load_modulo(raw.get("modulo", cfg.modulo), warnings)
    cfg.window = _load_window(raw.get("window", cfg.window), warnings, cfg.modulo)
    cfg.retries = _load_int(raw, "retries", cfg.retries, warnings)
    cfg.connect_retries = _load_int(
        raw, "connect_retries", cfg.connect_retries, warnings
    )
    cfg.t1 = _load_float(raw, "t1", cfg.t1, warnings)
    cfg.t2 = _load_float(raw, "t2", cfg.t2, warnings)
    cfg.t3 = _load_float(raw, "t3", cfg.t3, warnings)
    cfg.tx_armed_at_start = _load_bool(
        raw, "tx_armed_at_start", cfg.tx_armed_at_start, warnings
    )
    cfg.accept_incoming = _load_bool(raw, "accept_incoming", cfg.accept_incoming, warnings)
    cfg.aprs_auto_ack = _load_bool(raw, "aprs_auto_ack", cfg.aprs_auto_ack, warnings)
    cfg.aprs_sms_gateway = _load_str(raw, "aprs_sms_gateway", cfg.aprs_sms_gateway, warnings)
    cfg.aprs_email_gateway = _load_str(raw, "aprs_email_gateway", cfg.aprs_email_gateway, warnings)
    cfg.aprs_sms_template = _load_str(raw, "aprs_sms_template", cfg.aprs_sms_template, warnings)
    if cfg.aprs_sms_template == "{detail} {text}":
        # The original shipped default omitted SMSGTE's required ``@``.
        # This exact value was never a documented customization, so migrate
        # it while preserving every other operator-written template.
        cfg.aprs_sms_template = "@{detail} {text}"
        warnings.append("aprs_sms_template updated to SMSGTE's @number format")
    cfg.aprs_email_template = _load_str(raw, "aprs_email_template", cfg.aprs_email_template, warnings)
    cfg.aprs_is_watch_debug = _load_bool(
        raw, "aprs_is_watch_debug", cfg.aprs_is_watch_debug, warnings
    )
    cfg.connect_banner = _load_str(raw, "connect_banner", cfg.connect_banner, warnings)
    cfg.monitor_filter = _load_str(raw, "monitor_filter", cfg.monitor_filter, warnings)
    cfg.log_sessions = _load_bool(raw, "log_sessions", cfg.log_sessions, warnings)
    cfg.log_dir = _load_str(raw, "log_dir", cfg.log_dir, warnings)
    cfg.theme = _load_str(raw, "theme", cfg.theme, warnings)
    cfg.custom_theme = _load_custom_theme(raw.get("custom_theme"), warnings)
    _load_clock(raw, cfg, warnings)
    cfg.clock_24h = _load_bool(raw, "clock_24h", cfg.clock_24h, warnings)
    cfg.show_date = _load_bool(raw, "show_date", cfg.show_date, warnings)
    cfg.ascii_safe = _load_bool(raw, "ascii_safe", cfg.ascii_safe, warnings)
    cfg.remote_color = _load_bool(raw, "remote_color", cfg.remote_color, warnings)
    cfg.slideouts_auto_open = _load_bool(
        raw, "slideouts_auto_open", cfg.slideouts_auto_open, warnings
    )
    cfg.aprs = _load_aprs(raw.get("aprs", {}), warnings)
    cfg.beacon = _load_beacon(raw.get("beacon", {}), warnings)
    cfg.watched_callsigns = _load_watched_callsigns(raw.get("watched_callsigns", {}), warnings)
    cfg.autoconnect = _load_dict_list(raw.get("autoconnect", []), "autoconnect", warnings)

    cfg.warnings = warnings
    for problem in warnings:
        logger.warning("config: %s", problem)
    return cfg


def _load_str(raw: dict[str, Any], key: str, default: str, warnings: list[str]) -> str:
    if key not in raw:
        return default
    value = raw[key]
    if not isinstance(value, str):
        warnings.append(f"{key!r} should be a string, got {value!r}; using default {default!r}")
        return default
    return value


def _load_int(raw: dict[str, Any], key: str, default: int, warnings: list[str]) -> int:
    if key not in raw:
        return default
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int):
        warnings.append(f"{key!r} should be an integer, got {value!r}; using default {default!r}")
        return default
    return value


def _load_float(raw: dict[str, Any], key: str, default: float, warnings: list[str]) -> float:
    if key not in raw:
        return default
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        warnings.append(f"{key!r} should be a number, got {value!r}; using default {default!r}")
        return default
    return float(value)


def _load_bool(raw: dict[str, Any], key: str, default: bool, warnings: list[str]) -> bool:
    if key not in raw:
        return default
    value = raw[key]
    if not isinstance(value, bool):
        warnings.append(f"{key!r} should be true/false, got {value!r}; using default {default!r}")
        return default
    return value


def _load_modulo(value: Any, warnings: list[str]) -> int:
    """Only 8 and 128 exist. Anything else is a typo, not a tunable."""
    if value in (8, 128) and not isinstance(value, bool):
        return int(value)
    warnings.append(f"'modulo' must be 8 or 128, got {value!r}; using 8")
    return 8


#: Old `clock_source` values -> the (show_local_time, show_utc_time) pair
#: that replaced them. Kept so a config written by an earlier build keeps
#: working instead of silently reverting to defaults.
_LEGACY_CLOCK_SOURCE = {
    "local": (True, False),
    "utc": (False, True),
    "both": (True, True),
}


def _load_clock(raw: dict[str, Any], cfg: "Config", warnings: list[str]) -> None:
    """Load the two clock toggles, migrating the old `clock_source` enum.

    `clock_source = "local"|"utc"|"both"` was the first cut, and it was the
    wrong shape: it modelled the two times as one either/or choice while the
    date got an independent flag, so "show me nothing" and "show me only the
    date" were both unreachable. The explicit toggles replace it.

    A config file still carrying `clock_source` is migrated rather than
    ignored -- silently reverting someone's clock to defaults because a key
    was renamed is exactly the kind of surprise `load_config` exists to avoid.
    The new keys win if both are present.
    """
    legacy = raw.get("clock_source")
    if legacy is not None and "show_local_time" not in raw and "show_utc_time" not in raw:
        pair = _LEGACY_CLOCK_SOURCE.get(legacy)
        if pair is None:
            warnings.append(
                f"'clock_source' (no longer used) was {legacy!r}, which is not one of "
                f"{', '.join(_LEGACY_CLOCK_SOURCE)}; using the defaults instead"
            )
        else:
            cfg.show_local_time, cfg.show_utc_time = pair
            warnings.append(
                f"'clock_source = {legacy!r}' is obsolete; migrated to "
                f"show_local_time = {str(cfg.show_local_time).lower()}, "
                f"show_utc_time = {str(cfg.show_utc_time).lower()}. "
                f"Save from Settings to rewrite config.toml without it."
            )
        return

    cfg.show_local_time = _load_bool(raw, "show_local_time", cfg.show_local_time, warnings)
    cfg.show_utc_time = _load_bool(raw, "show_utc_time", cfg.show_utc_time, warnings)


def _load_window(value: Any, warnings: list[str], modulo: int = 8) -> int:
    """Clamp k to 1..modulo-1.

    The upper bound depends on `modulo` and is not a constant: 7 under modulo
    8, 127 under modulo 128. Hard-coding 7 here silently capped every extended
    link at a modulo-8 window, which looks like poor throughput rather than a
    config bug.
    """
    default = 4
    top = modulo - 1
    if isinstance(value, bool) or not isinstance(value, int):
        warnings.append(
            f"'window' should be an integer 1-{top}, got {value!r}; using default {default}"
        )
        return default
    if not 1 <= value <= top:
        clamped = max(1, min(top, value))
        warnings.append(
            f"'window' {value} is out of range 1-{top} "
            f"(modulo-{modulo} AX.25 caps k at {top}); clamped to {clamped}"
        )
        return clamped
    return value


def _load_callsign(value: Any, field_name: str, warnings: list[str]) -> str:
    """Validate one callsign via `AX25Address.parse` -- reused, not reimplemented.

    An empty string is not a warning (unset is the honest default for a
    first run); anything non-empty that fails to parse is.
    """
    if value in ("", None):
        return ""
    if not isinstance(value, str):
        warnings.append(f"{field_name!r} should be a string, got {value!r}; leaving unset")
        return ""
    try:
        AX25Address.parse(value)
    except AX25AddressError as exc:
        warnings.append(f"{field_name} {value!r} is not a valid callsign ({exc}); leaving unset")
        return ""
    return value.strip().upper()


def _load_callsign_list(value: Any, warnings: list[str]) -> list[str]:
    if not isinstance(value, list):
        warnings.append(f"'mycall_aliases' should be a list, got {value!r}; using empty list")
        return []
    out: list[str] = []
    for item in value:
        call = _load_callsign(item, "mycall_aliases entry", warnings)
        if call:
            out.append(call)
    return out


def _load_aprs_ssid(raw: dict[str, Any], warnings: list[str]) -> str:
    """`aprs.ssid` as a canonical "" or "0".."15".

    Accepts an int (TOML `ssid = 9`) or a string, with or without a leading
    dash, because all three are what an operator would naturally write.
    Anything out of range degrades to empty with a warning: transmitting
    under the station's own SSID is a defensible fallback, putting an
    illegal address on the air is not.
    """
    value = raw.get("ssid", "")
    if value in (None, ""):
        return ""
    text = str(value).strip().lstrip("-")
    try:
        number = int(text)
    except ValueError:
        warnings.append(f"aprs.ssid {value!r} is not a number; ignoring it")
        return ""
    if not 0 <= number <= 15:
        warnings.append(f"aprs.ssid {value!r} is outside 0-15; ignoring it")
        return ""
    return str(number)


def _load_str_list(value: Any, field_name: str, warnings: list[str]) -> list[str]:
    """A list of plain strings, dropping anything that is not one.

    `_load_callsign_list` above is the same shape but validates each entry as
    a callsign and is hard-wired to `mycall_aliases`' warning text; this is
    the un-validated sibling for lists whose entries are just identifiers.
    Blanks are dropped rather than kept -- an empty id matches no service and
    would only ever be noise.
    """
    if not isinstance(value, list):
        warnings.append(f"{field_name!r} should be a list, got {value!r}; using empty list")
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif not isinstance(item, str):
            warnings.append(f"{field_name}: entry {item!r} is not a string; dropped")
    return out


def _load_dict_list(value: Any, field_name: str, warnings: list[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        warnings.append(f"{field_name!r} should be a list of tables, got {value!r}; using empty list")
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            out.append(item)
        else:
            warnings.append(f"{field_name}: entry {item!r} is not a table; dropped")
    return out


def _load_aprs(value: Any, warnings: list[str]) -> AprsConfig:
    default = AprsConfig()
    if not isinstance(value, dict):
        if value not in ({}, None):
            warnings.append(f"'aprs' should be a table, got {value!r}; using defaults")
        return default

    aprs = AprsConfig()
    aprs.enabled = _load_bool(value, "enabled", default.enabled, warnings)
    aprs.beacon_interval_minutes = _load_int(
        value, "beacon_interval_minutes", default.beacon_interval_minutes, warnings
    )
    if aprs.beacon_interval_minutes < MIN_BEACON_INTERVAL_MINUTES:
        warnings.append(
            f"aprs.beacon_interval_minutes {aprs.beacon_interval_minutes} is below "
            f"the {MIN_BEACON_INTERVAL_MINUTES}-minute minimum; using "
            f"{MIN_BEACON_INTERVAL_MINUTES}. A beacon occupies a channel "
            f"everyone else shares."
        )
        aprs.beacon_interval_minutes = MIN_BEACON_INTERVAL_MINUTES
    aprs.symbol = _load_str(value, "symbol", default.symbol, warnings)
    aprs.comment = _load_str(value, "comment", default.comment, warnings)
    aprs.path = _load_str(value, "path", default.path, warnings)

    aprs.latitude = _load_float(value, "latitude", default.latitude, warnings)
    if not -90.0 <= aprs.latitude <= 90.0:
        clamped = max(-90.0, min(90.0, aprs.latitude))
        warnings.append(f"aprs.latitude {aprs.latitude} out of range -90..90; clamped to {clamped}")
        aprs.latitude = clamped

    aprs.longitude = _load_float(value, "longitude", default.longitude, warnings)
    if not -180.0 <= aprs.longitude <= 180.0:
        clamped = max(-180.0, min(180.0, aprs.longitude))
        warnings.append(f"aprs.longitude {aprs.longitude} out of range -180..180; clamped to {clamped}")
        aprs.longitude = clamped

    aprs.gps_device = _load_str(value, "gps_device", default.gps_device, warnings).strip()
    aprs.smart_beaconing = _load_bool(value, "smart_beaconing", default.smart_beaconing, warnings)
    for key, minimum, maximum in (
        ("smart_fast_rate_seconds", 15, 3600),
        ("smart_slow_rate_minutes", 1, 1440),
        ("smart_fast_speed_knots", 1, 300),
        ("smart_slow_speed_knots", 0, 299),
        ("smart_turn_angle_degrees", 1, 180),
        ("smart_turn_slope", 0, 720),
        ("smart_min_turn_seconds", 15, 3600),
    ):
        loaded = _load_int(value, key, getattr(default, key), warnings)
        clamped = max(minimum, min(maximum, loaded))
        if clamped != loaded:
            warnings.append(f"aprs.{key} {loaded} out of range {minimum}..{maximum}; using {clamped}")
        setattr(aprs, key, clamped)
    if aprs.smart_slow_speed_knots >= aprs.smart_fast_speed_knots:
        corrected = max(0, aprs.smart_fast_speed_knots - 1)
        warnings.append(
            "aprs.smart_slow_speed_knots must be below smart_fast_speed_knots; "
            f"using {corrected}"
        )
        aprs.smart_slow_speed_knots = corrected

    aprs.grid_square = _load_str(value, "grid_square", default.grid_square, warnings)
    aprs.winlink_check = _load_bool(value, "winlink_check", default.winlink_check, warnings)
    aprs.ssid = _load_aprs_ssid(value, warnings)
    aprs.filter_by_ssid = _load_bool(value, "filter_by_ssid", default.filter_by_ssid, warnings)

    return aprs


def _load_beacon(value: Any, warnings: list[str]) -> BeaconConfig:
    """Load `[beacon]`, clamping the interval up to the floor.

    The clamp is the point of this function existing rather than a generic
    table loader: `interval_minutes = 1` in a hand-edited config would
    otherwise put the operator's callsign on the channel sixty times an hour.
    It is corrected with a warning rather than refused, because refusing
    would mean falling back to `enabled` with some other interval, and the
    operator asked to beacon -- just not that often.
    """
    default = BeaconConfig()
    if not isinstance(value, dict):
        if value not in ({}, None):
            warnings.append(f"'beacon' should be a table, got {value!r}; using defaults")
        return default

    beacon = BeaconConfig()
    beacon.enabled = _load_bool(value, "enabled", default.enabled, warnings)
    beacon.text = _load_str(value, "text", default.text, warnings)
    beacon.destination = _load_str(value, "destination", default.destination, warnings)
    beacon.path = _load_str(value, "path", default.path, warnings)
    beacon.port = _load_int(value, "port", default.port, warnings)
    beacon.interval_minutes = _load_int(
        value, "interval_minutes", default.interval_minutes, warnings
    )
    if beacon.interval_minutes < MIN_BEACON_INTERVAL_MINUTES:
        warnings.append(
            f"beacon.interval_minutes {beacon.interval_minutes} is below the "
            f"{MIN_BEACON_INTERVAL_MINUTES}-minute minimum; using "
            f"{MIN_BEACON_INTERVAL_MINUTES}. A beacon occupies a channel "
            f"everyone else shares."
        )
        beacon.interval_minutes = MIN_BEACON_INTERVAL_MINUTES

    if beacon.enabled and not beacon.text.strip():
        warnings.append(
            "beacon.enabled is true but beacon.text is empty; nothing will be "
            "transmitted. An empty beacon is pure channel occupancy."
        )
    return beacon


def _load_watched_callsigns(value: Any, warnings: list[str]) -> WatchedCallsignConfig:
    """Load the passive watchlist, discarding unsafe or malformed controls."""
    default = WatchedCallsignConfig()
    if not isinstance(value, dict):
        if value not in ({}, None):
            warnings.append(f"'watched_callsigns' should be a table, got {value!r}; using defaults")
        return default
    watched = WatchedCallsignConfig()
    watched.enabled = _load_bool(value, "enabled", default.enabled, warnings)
    watched.callsigns = _load_callsign_list(value.get("callsigns", []), warnings)
    watched.cooldown_minutes = _load_int(
        value, "cooldown_minutes", default.cooldown_minutes, warnings
    )
    watched.hourly_cap = _load_int(value, "hourly_cap", default.hourly_cap, warnings)
    watched.active_suppression_seconds = _load_int(
        value, "active_suppression_seconds", default.active_suppression_seconds, warnings
    )
    for attr in ("cooldown_minutes", "hourly_cap", "active_suppression_seconds"):
        if getattr(watched, attr) < 0:
            warnings.append(f"watched_callsigns.{attr} must not be negative; using default")
            setattr(watched, attr, getattr(default, attr))
    for attr in ("quiet_start_hour", "quiet_end_hour"):
        raw = value.get(attr)
        if raw is None or raw == -1:
            setattr(watched, attr, -1)
        elif isinstance(raw, int) and not isinstance(raw, bool) and 0 <= raw <= 23:
            setattr(watched, attr, raw)
        else:
            warnings.append(f"watched_callsigns.{attr} must be an hour from 0 to 23; disabled")
            setattr(watched, attr, -1)
    return watched


#: A Textual-acceptable hex color: 6 or 3 hex digits, always `#`-prefixed.
#: Public (not `_`-prefixed) because `kissterm.ui.settings_schema` validates
#: a Settings-pane color field against this exact pattern -- one regex, so a
#: value the Settings pane accepts is guaranteed to also survive
#: `load_config()` on the next launch.
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{3}(?:[0-9A-Fa-f]{3})?$")


def _load_hex_color(raw: dict[str, Any], key: str, default: str, warnings: list[str]) -> str:
    """Validate one `[custom_theme]` field.

    Permissive by the same rule as everything else in this module: a typo in
    one hex value degrades to that one field's default rather than discarding
    the whole custom theme, so an operator fixing a single color does not
    silently lose the other nine.
    """
    value = raw.get(key, default)
    if not isinstance(value, str) or not HEX_COLOR_RE.match(value):
        warnings.append(
            f"custom_theme.{key} should be a hex color like '#1A1B26', got {value!r}; "
            f"using default {default!r}"
        )
        return default
    return value


def _load_custom_theme(value: Any, warnings: list[str]) -> "CustomThemeConfig":
    default = CustomThemeConfig()
    if not isinstance(value, dict):
        if value not in ({}, None):
            warnings.append(f"'custom_theme' should be a table, got {value!r}; using defaults")
        return default

    custom = CustomThemeConfig()
    for attr in (
        "primary", "secondary", "warning", "error", "success",
        "accent", "foreground", "background", "surface", "panel",
    ):
        setattr(custom, attr, _load_hex_color(value, attr, getattr(default, attr), warnings))
    custom.dark = _load_bool(value, "dark", default.dark, warnings)
    return custom


# ---------------------------------------------------------------------------
# Saving -- atomic by construction
# ---------------------------------------------------------------------------


def save_config(config: Config, path: Path | None = None) -> None:
    """Write `config` to TOML at `path` (default `config_path()`), atomically.

    "Atomically" means: render the whole file in memory, write it to a temp
    file in the same directory (so the final `os.replace` is a same-
    filesystem rename, not a copy), flush and fsync it, then swap it into
    place. A crash, power loss, or SIGKILL at any point before the replace
    leaves the previous config file exactly as it was; a crash after leaves
    the new one intact. There is no window in which `config.toml` exists but
    is half-written -- which is the scenario that would otherwise turn a
    single interrupted save into the exact "config file is broken" case
    `load_config()` has to recover from.
    """
    profile = config.profile_name
    if path is not None and profile != DEFAULT_PROFILE:
        raise ValueError("an explicit path cannot save a selected profile")
    path = path or config_path(profile)
    if profile != DEFAULT_PROFILE:
        _profile_directory()
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise OSError(f"refusing to replace unsafe profile path: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)

    data = dataclasses.asdict(config)
    data.pop("warnings", None)
    data.pop("profile_name", None)
    if profile != DEFAULT_PROFILE:
        data["profile"] = profile
    text = _dump_toml(data)

    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".config-", suffix=".toml.tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp_name)
        raise


#: TOML basic-string escapes. Order matters only in that backslash is handled
#: first by `_toml_escape` itself, before anything else can introduce one.
_TOML_ESCAPES = {
    '"': '\\"',
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def _toml_escape(text: str) -> str:
    """Escape a string for a TOML basic string.

    Control characters MUST be escaped, not just quotes and backslashes. An
    earlier version escaped only those two, so any value containing a carriage
    return -- `connect_banner` is CR-separated, because packet is -- wrote a
    raw CR into the file. That makes the whole document unparseable, and
    because `load_config()` is deliberately forgiving it then falls back to
    *every* default silently: an operator's tuned timers, callsign and
    transports would all quietly revert on the next launch. A write path that
    can corrupt the file it just wrote is worse than one that raises.
    """
    out = text.replace("\\", "\\\\")
    for char, escape in _TOML_ESCAPES.items():
        out = out.replace(char, escape)
    # Anything else below 0x20, plus DEL, has no short escape.
    return "".join(
        c if (c >= " " and c != "\x7f") else f"\\u{ord(c):04X}" for c in out
    )


def _toml_scalar(value: Any) -> str:
    """Render one TOML scalar. Handles exactly what `Config` can hold --
    str, int, float, bool, and flat lists of those -- not general TOML."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return f'"{_toml_escape(value)}"'
    if isinstance(value, list):
        return "[" + ", ".join(_toml_scalar(v) for v in value) + "]"
    raise TypeError(f"unsupported TOML scalar type: {type(value)!r}")


def _dump_toml(data: dict[str, Any]) -> str:
    """Render `data` as TOML text.

    Not a general-purpose TOML writer: it knows exactly three shapes,
    because that is all `Config` ever produces -- top-level scalars/inline
    arrays, one flat subtable (`[aprs]`), and arrays of flat tables
    (`[[transports]]`, `[[autoconnect]]`). See the module docstring for why
    this exists instead of a dependency, and why it does not attempt to
    preserve a hand-edited file's comments.
    """
    scalar_lines: list[str] = []
    tables: list[tuple[str, dict[str, Any]]] = []
    array_tables: list[tuple[str, list[dict[str, Any]]]] = []

    for key, value in data.items():
        if isinstance(value, dict):
            tables.append((key, value))
        elif isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            array_tables.append((key, value))
        else:
            scalar_lines.append(f"{key} = {_toml_scalar(value)}")

    lines = list(scalar_lines)

    for key, table in tables:
        lines.append("")
        lines.append(f"[{key}]")
        for k, v in table.items():
            lines.append(f"{k} = {_toml_scalar(v)}")

    for key, entries in array_tables:
        for entry in entries:
            lines.append("")
            lines.append(f"[[{key}]]")
            for k, v in entry.items():
                lines.append(f"{k} = {_toml_scalar(v)}")

    return "\n".join(lines) + "\n"
