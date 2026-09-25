"""A declarative description of every editable setting.

The Settings pane is generated from this list. That is the whole point: adding
a field to `kissterm.config.Config` should mean adding **one entry here**, not
writing a label, an input, a validator, a save hook and a test for each new
knob. A hand-built settings form rots the moment someone adds a config option
and forgets the UI -- which is exactly how kissterm ended up shipping a wizard
that asked for two things and a Settings tab that could edit neither.

`kind` drives both the widget and the coercion, so a value that reaches
`Config` from this pane has already been through the same validation
`load_config()` applies to the file. `apply` records when a change takes
effect, and the pane shows it, because "I changed paclen and nothing happened"
is a support question worth pre-empting:

* ``"live"``    -- takes effect immediately.
* ``"connect"`` -- affects the next connection; existing links keep their
  negotiated values, because changing them underneath an established link
  corrupts it.
* ``"restart"`` -- read only at startup.

Transports are deliberately NOT in this schema. They are a list of dicts with
kind-specific keys (a serial port has a baud rate, a TCP host has a port), and
flattening that into scalar fields would either lose the shape or hard-code
every transport kind here -- the exact coupling `config.py` avoids by keeping
them as dicts. The pane gives them their own section.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..config import HEX_COLOR_RE
from .themes import choices as _theme_choices


@dataclass(frozen=True, slots=True)
class Field:
    """One editable setting.

    `path` is dotted so a nested dataclass (`aprs.latitude`) needs no special
    case in the pane -- see `get_value`/`set_value` below.
    """

    path: str
    label: str
    # "text" | "int" | "float" | "bool" | "choice" | "callsign" | "calllist" |
    # "color" | "custom_choice" | "filtered_choice"
    kind: str
    help: str = ""
    apply: str = "connect"
    choices: tuple[tuple[str, Any], ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    placeholder: str = ""
    #: True means `SettingsPane._compose_field` builds NO widget of its own
    #: for this field -- some other, hand-written composer already built one
    #: with the matching id (`_widget_id(path)`). For a `Config` value that
    #: has more than one valid on-screen representation at once (a position
    #: as decimal degrees or a grid square, both editing the same
    #: `Config.aprs.latitude`/`longitude`), the schema's one-Field-one-widget
    #: model has no way to express that -- this is the escape hatch, the
    #: same role the hand-built Transports tab plays for dict-shaped config.
    #: `coerce`/`format_value`/`render_settings`/`_save` are untouched by
    #: this flag: they still read and write the field by its ordinary id,
    #: because the hand-written composer used that same id on purpose.
    custom_render: bool = False
    #: A heading drawn above this field, to set off the fields after it
    #: from those before (Mail's "Home BBS").
    rule_before: str = ""
    #: Folded under its section's "Advanced", shut until opened. Tuning a
    #: new operator never needs to see to get on the air; the defaults are
    #: right for 1200-baud VHF (operator, 2026-09-25: "new user
    #: approachable, not overwhelming").
    advanced: bool = False
    #: `(path, value)`: shown only while that other field is set to that
    #: value -- the custom theme colours, while Theme is Custom. Still saved
    #: while hidden, so nothing is lost by switching back and forth.
    only_when: tuple[str, Any] = ()


@dataclass(frozen=True, slots=True)
class Section:
    title: str
    note: str
    fields: tuple[Field, ...]


SETTINGS_SCHEMA: tuple[Section, ...] = (
    Section(
        'Station',
        'Who you are on the air.',
        (
            Field(
                "mycall",
                "Callsign",
                "callsign",
                "Your callsign with SSID. Also changeable any time from the F10 menu, under Session.",
                apply="connect",
                placeholder="N1ABC-1",
            ),
            Field(
                "mycall_aliases",
                "Also answer to",
                "calllist",
                "Extra callsigns this station accepts connections on, comma "
                "separated -- a personal mailbox on -1, for instance.",
                apply="live",
                placeholder="N1ABC-1, N1ABC-2",
            ),
        ),
    ),
    Section(
        'Link',
        'How your station talks AX.25 to another. The defaults suit '
        '1200-baud VHF; on HF or a poor path, try a smaller frame size.',
        (
            Field(
                "paclen",
                "Frame size (paclen)",
                "int",
                "Bytes of data per frame, 1-256. A shorter frame gives QRM and "
                "fading less to hit, so it is more likely to get through whole "
                "-- usually the right trade on HF even though it carries less.",
                minimum=1,
                maximum=256,
            ),
            Field(
                "window",
                "Window (k)",
                "int",
                "Frames outstanding unacknowledged. Must stay below the "
                "sequence mode -- so 1-7 normally. A busy or noisy channel "
                "wants a smaller window; less has to be resent when one is "
                "lost.",
                minimum=1,
                maximum=127,
            ),
            Field(
                "modulo",
                "Sequence mode",
                "choice",
                "Leave this at 8. Every BPQ32 node, KA-Node and TNC2-class "
                "station on the air speaks it. A peer that does not understand "
                "128 answers DM and kissterm falls back by itself.",
                choices=(("8 (standard)", 8), ("128 (extended)", 128)),
                advanced=True,
            ),
            Field(
                "retries",
                "Retries (N2)",
                "int",
                "How many times to retry on an ESTABLISHED link before "
                "declaring it dead. The spec default is 10, and low values "
                "drop a working session over a momentary fade.",
                minimum=1,
                maximum=100,
                advanced=True,
            ),
            Field(
                "connect_retries",
                "Connect retries",
                "int",
                "How many times to resend the connect request (SABM) before "
                "giving up. The spec default is 10: on a weak path the node "
                "often hears the request but its reply is lost, so each retry "
                "is another chance. Lower it on a busy channel.",
                minimum=1,
                maximum=100,
                advanced=True,
            ),
            Field(
                "sabm_on_poll",
                "Retry at once when polled",
                "bool",
                "While connecting, a poll from the node means it heard the "
                "request and its reply was lost. On: send the next request "
                "right away instead of waiting out T1. Off: ignore the poll, "
                "as AX.25 2.2 does.",
                advanced=True,
            ),
            Field(
                "t1",
                "T1 -- ack timeout (s)",
                "float",
                "How long to wait for an acknowledgement before resending. "
                "Must exceed the worst-case round trip or the link retransmits "
                "into its own echo: at 1200 baud a 256-byte frame is about "
                "1.8 s on the air before the reply even starts.",
                minimum=0.1,
                maximum=120.0,
                advanced=True,
            ),
            Field(
                "t2",
                "T2 -- ack delay (s)",
                "float",
                "How long to hold an acknowledgement so an outgoing frame can "
                "carry it. Setting this to zero roughly doubles the "
                "transmissions on a two-way conversation.",
                minimum=0.0,
                maximum=30.0,
                advanced=True,
            ),
            Field(
                "t3",
                "T3 -- idle check (s)",
                "float",
                "How long an idle link sits before kissterm checks the far end "
                "is still there. 0 disables it, at the cost of a dead link "
                "looking connected forever.",
                minimum=0.0,
                maximum=3600.0,
                advanced=True,
            ),
        ),
    ),
    Section(
        'Mail',
        'Writing mail, and the BBS that holds it. On the Mail tab: Insert '
        'writes, R replies, Q replies quoting, G sends and receives.',
        (
            Field(
                "reply_quote",
                "Quote in replies (R)",
                "bool",
                "On: R quotes the original under your reply, as Q does. Off: "
                "R starts empty. Quoted lines are airtime, and you can edit "
                "or delete them either way.",
                apply="live",
            ),
            Field(
                "home_bbs.route",
                "Dial",
                "text",
                "The Address Book entry that reaches the BBS, exactly as "
                "listed: WS1EC-2 direct, or a node entry whose login script "
                "sends BBS. Its frequency reminder, hops and login apply.",
                apply="live",
                placeholder="WS1EC-2",
                rule_before="Home BBS: where Send/Receive (G on the Mail tab) sends and collects your mail",
            ),
            Field(
                "home_bbs.call",
                "BBS callsign",
                "text",
                "Files mail as coming from this BBS however it was reached. "
                "Leave empty to read it from the BBS's prompt.",
                apply="live",
                placeholder="from the prompt",
            ),
            Field(
                "home_bbs.software",
                "Software",
                "choice",
                "Automatic recognises BPQMail from what it sends. Only "
                "BPQMail can be collected from so far.",
                choices=(("Automatic", "auto"), ("BPQMail", "bpqmail")),
                apply="live",
            ),
            Field(
                "home_bbs.ready_text",
                "Ready text",
                "text",
                "The text that means the BBS is ready for a command.",
                apply="live",
                rule_before="Only if the BBS software is not identified automatically",
                advanced=True,
                placeholder='e.g. de WS1EC>',
            ),
            Field(
                "home_bbs.login_prompt",
                "Login prompt",
                "text",
                "Text after which the credential below is sent. Telnet "
                "BBSes ask for a login; RF ones usually do not.",
                apply="live",
                advanced=True,
                placeholder='e.g. Password:',
            ),
            Field(
                "home_bbs.credential",
                "Credential",
                "text",
                "The name of a saved credential (Settings > Logins).",
                apply="live",
                advanced=True,
                placeholder="a saved login's name",
            ),
        ),
    ),
    Section(
        'APRS',
        'Your position and APRS messages. Nothing is sent until you turn '
        'beaconing on or send a message.',
        (
            Field(
                "aprs.enabled",
                "Enable APRS beaconing",
                "bool",
                "Transmits your position on a timer. Off by default -- "
                "kissterm never puts anything on the air you did not ask for.",
                apply="live",
            ),
            Field(
                "aprs.ssid",
                "APRS SSID",
                "str",
                "SSID to transmit APRS under, 0-15. Blank uses your station "
                "callsign as-is. Conventionally -9 for a car, -7 for a "
                "handheld, -5 for a phone, keeping your APRS identity "
                "separate from the callsign connected-mode packet uses.",
                apply="live",
                placeholder="e.g. 9",
            ),
            Field(
                "aprs.latitude",
                "Latitude",
                "float",
                "Decimal degrees, north positive.",
                minimum=-90.0,
                maximum=90.0,
                apply="live",
                custom_render=True,
            ),
            Field(
                "aprs.longitude",
                "Longitude",
                "float",
                "Decimal degrees, east positive.",
                minimum=-180.0,
                maximum=180.0,
                apply="live",
                custom_render=True,
            ),
            Field(
                "aprs.grid_square",
                "Grid square",
                "text",
                "Maidenhead locator, e.g. FN31pr. Redisplay only -- what is "
                "actually transmitted is always latitude/longitude, kept in "
                "sync with this automatically.",
                apply="live",
                custom_render=True,
            ),
            Field(
                "aprs.symbol",
                "Map symbol",
                "filtered_choice",
                "Two characters: table selector then symbol code. Type to "
                "filter by name.",
                apply="live",
            ),
            Field(
                "aprs.comment",
                "Beacon comment",
                "text",
                "Free text appended to your position report.",
                apply="live",
                placeholder='e.g. Mobile, monitoring 146.52',
            ),
            Field(
                "aprs.beacon_interval_minutes",
                "Beacon every (min)",
                "int",
                "Ten minutes is the floor and it is enforced, not "
                "suggested -- a shorter interval on a shared channel is "
                "antisocial unless you are moving. Thirty or sixty is "
                "normal for a fixed station.",
                minimum=10,
                maximum=1440,
                apply="live",
            ),
            Field(
                "aprs.path",
                "Digipeater path",
                "custom_choice",
                "WIDE1-1,WIDE2-1 is the normal path. Longer paths clog the "
                "network for everyone and are considered poor practice.",
                apply="live",
                # ARISS is a path, not a contact: the ISS digipeater answers
                # anything carrying it, so it belongs in this preset list
                # rather than kissterm/aprs_services/ (docs/ROADMAP.md P4).
                # A pass is a narrow time window at a fixed elevation, so an
                # operator picking this preset should keep messages short.
                choices=(
                    ("WIDE1-1,WIDE2-1 (recommended)", "WIDE1-1,WIDE2-1"),
                    ("WIDE1-1 (single hop)", "WIDE1-1"),
                    ("WIDE2-2 (two hop, no fill-in)", "WIDE2-2"),
                    ("ARISS (ISS digipeater, satellite pass)", "ARISS"),
                    ("Direct (no path)", ""),
                ),
                placeholder="e.g. WIDE1-1,WIDE1-1",
            ),
            Field(
                "aprs.smart_beaconing",
                "Use SmartBeaconing",
                "bool",
                "With a live GPS, shortens position-report timing while moving "
                "and reports significant turns. It never arms transmit; the "
                "normal TX gate still controls every automatic beacon.",
                apply="live",
            ),
            Field(
                "aprs.winlink_check",
                "Check for Winlink messages",
                "bool",
                "Appends WINLINK to the transmitted comment. APRSLink watches "
                "for this word in a position comment or status text and sends "
                "you a daily APRS alert when Winlink mail is waiting. "
                "Documented at winlink.org/APRSLink.",
                apply="live",
            ),
            Field(
                "aprs.filter_by_ssid",
                "Exact SSID only",
                "bool",
                "On by default, matching how most APRS apps behave: a "
                "message addressed to a different SSID of your callsign "
                "(someone else's mobile or handheld persona, say) is "
                "ignored by this session rather than answered under an "
                "identity it was never sent to. Turn off to answer a "
                "message sent to ANY SSID of your callsign -- the F10 menu's APRS > SSID filter "
                "toggles this without opening Settings.",
                apply="live",
                advanced=True,
            ),
            Field(
                "aprs.gps_device",
                "GPS serial device",
                "text",
                "Optional NMEA-0183 serial device, such as /dev/ttyUSB1 or "
                "/dev/rfcomm0. When set, beacons use only a current GPS fix; "
                "the fixed position above is left unchanged.",
                apply="live",
                placeholder="/dev/ttyUSB1",
                custom_render=True,
                advanced=True,
            ),
            Field(
                "aprs.smart_fast_rate_seconds",
                "Smart fast rate (s)",
                "int",
                "Moving at or above the fast speed uses this interval. Fifteen "
                "seconds is the enforced floor for shared-channel courtesy.",
                minimum=15,
                maximum=3600,
                apply="live",
                advanced=True,
            ),
            Field(
                "aprs.smart_slow_rate_minutes",
                "Smart slow rate (min)",
                "int",
                "At or below the slow speed, use this parked/low-speed interval.",
                minimum=1,
                maximum=1440,
                apply="live",
                advanced=True,
            ),
            Field(
                "aprs.smart_fast_speed_knots",
                "Smart fast speed (kt)",
                "int",
                "At or above this GPS speed, use the fast rate. GPS reports knots.",
                minimum=1,
                maximum=300,
                apply="live",
                advanced=True,
            ),
            Field(
                "aprs.smart_slow_speed_knots",
                "Smart slow speed (kt)",
                "int",
                "At or below this GPS speed, use the slow rate; it must be below "
                "the fast speed.",
                minimum=0,
                maximum=299,
                apply="live",
                advanced=True,
            ),
            Field(
                "aprs.smart_turn_angle_degrees",
                "Smart turn angle (deg)",
                "int",
                "Base heading change that can report a corner. The threshold grows "
                "at low speed to reject GPS course jitter.",
                minimum=1,
                maximum=180,
                apply="live",
                advanced=True,
            ),
            Field(
                "aprs.smart_turn_slope",
                "Smart turn slope",
                "int",
                "Extra turn threshold divided by speed in knots. Higher values make "
                "low-speed corner reports less sensitive.",
                minimum=0,
                maximum=720,
                apply="live",
                advanced=True,
            ),
            Field(
                "aprs.smart_min_turn_seconds",
                "Smart minimum turn (s)",
                "int",
                "Minimum time between any position report and a corner report; "
                "enforced to avoid flooding winding roads.",
                minimum=15,
                maximum=3600,
                apply="live",
                advanced=True,
            ),
            Field(
                "aprs_sms_gateway",
                "SMS gateway",
                "text",
                "Pre-fills a new SMS contact's callsign in the APRS pane's "
                "contact editor. Blank means no default -- type the "
                "gateway's callsign into each contact by hand.",
                apply="live",
                placeholder="e.g. SMSGTE",
                advanced=True,
                rule_before="SMS and email gateways (UNVERIFIED: conventions vary by region; check yours)",
            ),
            Field(
                "aprs_email_gateway",
                "Email gateway",
                "text",
                "Same idea as the SMS gateway above, for email contacts.",
                apply="live",
                placeholder="e.g. EMAIL2",
                advanced=True,
            ),
            Field(
                "aprs_sms_template",
                "SMS template",
                "text",
                "{detail} is the contact's phone number, {text} what you "
                "typed. The commonly-documented convention is phone number "
                "then message text -- edit this if your gateway differs.",
                apply="live",
                placeholder="{detail} {text}",
                advanced=True,
            ),
            Field(
                "aprs_email_template",
                "Email template",
                "text",
                "Same idea as the SMS template above, for email contacts.",
                apply="live",
                placeholder="{detail} {text}",
                advanced=True,
            ),
        ),
    ),
    Section(
        'Beacon',
        'Free text sent on a timer to say you are here. Not APRS: APRS '
        'sends your position. Off until you turn it on.',
        (
            Field(
                "beacon.enabled",
                "Beacon on a timer",
                "bool",
                "Transmits the text below every interval, unattended, under "
                "your callsign. Nothing is sent while the text is empty, "
                "whatever this is set to -- an empty beacon is pure channel "
                "occupancy. The first one goes out one full interval after "
                "you enable it, never the moment you press Save.",
                apply="live",
            ),
            Field(
                "beacon.text",
                "Beacon text",
                "text",
                "Who and where you are, and what you offer -- a node, a "
                "mailbox, a talkgroup. Use \\r for a line break. Truncated "
                "at 256 bytes: a beacon is not a bulletin.",
                apply="live",
                placeholder="W1AW Newington CT -- kissterm, mailbox on -1",
            ),
            Field(
                "beacon.interval_minutes",
                "Beacon every (min)",
                "int",
                "Ten minutes is the floor and it is enforced, not suggested: "
                "at 1200 baud your beacon is time nobody else on the "
                "frequency can transmit. Thirty or sixty is normal for a "
                "fixed station.",
                minimum=10,
                maximum=1440,
                apply="live",
            ),
            Field(
                "beacon.destination",
                "Unproto destination",
                "text",
                "Who the beacon is addressed to. BEACON is the long-standing "
                "convention; ID and CQ are the other two you will see. "
                "Nobody answers it -- the frame is unconnected.",
                apply="live",
                placeholder="BEACON",
                advanced=True,
            ),
            Field(
                "beacon.path",
                "Digipeater path",
                "text",
                "Empty means direct, which is the right answer for a fixed "
                "station that can be heard. A beacon sent through wide "
                "digipeaters is the reason beacons have a bad name.",
                apply="live",
                placeholder="(direct)",
                advanced=True,
            ),
            Field(
                "beacon.port",
                "TNC port",
                "int",
                "KISS/AGW port number, for a multi-port TNC. 0 unless you "
                "know otherwise.",
                minimum=0,
                maximum=15,
                apply="live",
                advanced=True,
            ),
        ),
    ),
    Section(
        'Answering',
        'Transmitting with nobody at the keyboard. You remain the control '
        'operator. Everything here is off until you turn it on.',
        (
            Field(
                "tx_armed_at_start",
                "Enable transmit at startup",
                "bool",
                "Off by default: kissterm starts unable to key the radio, "
                "and Ctrl+T arms it -- the same way WSJT-X's Enable Tx "
                "resets every launch. Turn this on only for a station meant "
                "to run unattended, where a restart quietly taking it off "
                "the air is the worse failure.",
                apply="restart",
            ),
            Field(
                "accept_incoming",
                "Answer incoming calls",
                "bool",
                "When off, a station calling you gets a polite refusal (DM) so "
                "it stops retrying instead of burning its whole retry budget. "
                "When on, kissterm answers and sends the banner below -- "
                "unattended, under your callsign, whether or not you are at "
                "the keyboard. Check what your licence allows for automatic "
                "control on the band you are using.",
                apply="live",
            ),
            Field(
                "connect_banner",
                "Connect banner",
                "text",
                "Sent to whoever connects. BPQ32 calls this CTEXT. Use \\r "
                "for a line break -- packet is carriage-return oriented.",
                apply="live",
            ),
            Field(
                "aprs_auto_ack",
                "Auto-ack APRS messages",
                "bool",
                "On by default: an APRS message you never ack is not safely "
                "delivered, it is just broken -- this is a single, fixed "
                "reply with no content you did not already choose by using "
                "two-way messaging at all, and it is still gated by the "
                "transmit switch above like everything else. Turn off for "
                "manual-ack-only.",
                apply="live",
            ),
        ),
    ),
    Section(
        'Alerts',
        'A local alert when a watched callsign is heard. A callsign in a '
        'frame is a claim, not proof of who sent it. Alerts never transmit.',
        (
            Field("watched_callsigns.enabled", "Watch for callsigns", "bool",
                  "Off by default. Uses the existing receive path only.", apply="live"),
            Field("watched_callsigns.callsigns", "Watch callsigns", "calllist",
                  "Comma-separated callsign claims to watch in a frame source or digipeater path.",
                  apply="live", placeholder="N1ABC, W1AW-2"),
            Field("watched_callsigns.cooldown_minutes", "Repeat cooldown (min)", "int",
                  "One alert per callsign claim during this interval.", minimum=0, maximum=1440,
                  apply="live", advanced=True),
            Field("watched_callsigns.hourly_cap", "Alerts per hour", "int",
                  "Global cap across watched callsigns; resets on the local clock hour.", minimum=0,
                  maximum=120, apply="live", advanced=True),
            Field("watched_callsigns.quiet_start_hour", "Quiet hours start", "int",
                  "Local hour 0-23; use -1 with the end hour to disable quiet hours.",
                  minimum=-1, maximum=23, apply="live", advanced=True),
            Field("watched_callsigns.quiet_end_hour", "Quiet hours end", "int",
                  "Local hour 0-23; quiet hours can cross midnight. Use -1 to disable.", minimum=-1, maximum=23,
                  apply="live", advanced=True),
            Field("watched_callsigns.active_suppression_seconds", "Suppress while active (s)", "int",
                  "After local keyboard use, skip alerts because the monitor is already visible; 0 disables.",
                  minimum=0, maximum=3600, apply="live", advanced=True),
        ),
    ),
    Section(
        'Appearance',
        'How kissterm looks. Changes show at once.',
        (
            Field(
                "start_tab",
                "Open on",
                "choice",
                "The tab kissterm shows when it starts.",
                apply="restart",
                choices=(
                    ("Mail (default)", ""),
                    ("Terminal", "terminal"),
                    ("APRS", "aprs"),
                    ("Monitor", "monitor"),
                ),
            ),
            Field(
                "theme",
                "Theme",
                "choice",
                "'Terminal ANSI' uses your terminal emulator's own 16-color "
                "palette directly, which is the closest thing to automatic "
                "syncing with an external terminal theme. 'Custom' uses the "
                "exact hex values below.",
                apply="live",
                choices=_theme_choices(),
            ),
            Field(
                "custom_theme.primary",
                "Primary",
                "color",
                "Structural borders -- pane outlines.",
                apply="live",
                rule_before="Custom theme colours",
                only_when=("theme", "custom"),
            ),
            Field(
                "custom_theme.secondary",
                "Secondary",
                "color",
                "A second accent, used sparingly alongside Primary.",
                apply="live",
                only_when=("theme", "custom"),
            ),
            Field(
                "custom_theme.accent",
                "Accent",
                "color",
                "The active/current thing: the selected tab, section "
                "headings.",
                apply="live",
                only_when=("theme", "custom"),
            ),
            Field(
                "custom_theme.foreground",
                "Foreground",
                "color",
                "Body text.",
                apply="live",
                only_when=("theme", "custom"),
            ),
            Field(
                "custom_theme.background",
                "Background",
                "color",
                "The app's own ground -- tab bar, status bar.",
                apply="live",
                only_when=("theme", "custom"),
            ),
            Field(
                "custom_theme.surface",
                "Surface",
                "color",
                "Panel interiors, dialog bodies.",
                apply="live",
                only_when=("theme", "custom"),
            ),
            Field(
                "custom_theme.panel",
                "Panel",
                "color",
                "Header and Footer chrome.",
                apply="live",
                only_when=("theme", "custom"),
            ),
            Field(
                "custom_theme.warning",
                "Warning",
                "color",
                "State, not emphasis -- something needs attention.",
                apply="live",
                only_when=("theme", "custom"),
            ),
            Field(
                "custom_theme.error",
                "Error",
                "color",
                "State, not emphasis -- something is wrong.",
                apply="live",
                only_when=("theme", "custom"),
            ),
            Field(
                "custom_theme.success",
                "Success",
                "color",
                "State, not emphasis -- something worked.",
                apply="live",
                only_when=("theme", "custom"),
            ),
            Field(
                "custom_theme.dark",
                "Dark theme",
                "bool",
                "Whether Textual should treat Custom as a dark or light "
                "palette, for the few built-in widgets that pick their own "
                "contrast from it. Not a color itself.",
                apply="live",
                only_when=("theme", "custom"),
            ),
            Field(
                "show_local_time",
                "Local time",
                "bool",
                "Shown unmarked, the same convention a paper log uses. On by "
                "default.",
                apply="live",
            ),
            Field(
                "show_utc_time",
                "UTC time",
                "bool",
                "Always marked: Z on a 24-hour clock, UTC on a 12-hour one. "
                "Turn both this and local time on to see each side by side.",
                apply="live",
            ),
            Field(
                "clock_24h",
                "24-hour clock",
                "bool",
                "On by default: 24-hour is the amateur radio convention, "
                "especially for anything logged in UTC.",
                apply="live",
            ),
            Field(
                "show_date",
                "Date",
                "bool",
                "Always ISO 8601 (2026-09-05), never locale order -- 03/04 is "
                "March 4th in the US and April 3rd almost everywhere else. "
                "With both times shown, each gets its own date on the nights "
                "they differ.",
                apply="live",
            ),
            Field(
                "ascii_safe",
                "ASCII-safe mode",
                "bool",
                "Plain ASCII instead of Unicode box-drawing, for a terminal "
                "that mangles anything past code page 437.",
                apply="restart",
            ),
            Field(
                "remote_color",
                "Allow remote colour",
                "bool",
                "Let a BBS's own ANSI colour through. Only colour, bold and "
                "underline survive -- cursor movement, screen erase, window "
                "title and clipboard sequences are removed either way, so "
                "this is a readability choice, not a safety one. Turn it off "
                "on a terminal that renders colour badly.",
                apply="live",
                advanced=True,
            ),
            Field(
                "slideouts_auto_open",
                "Open contact lists",
                "bool",
                "Let the Address Book and the APRS contact list open "
                "themselves when the terminal is at least 80 columns wide -- "
                "enough to keep the session or chat column at 40 beside them. "
                "Ctrl+G still opens and closes either at any width, and doing "
                "so takes the decision away from this setting until restart.",
                apply="restart",
                advanced=True,
            ),
        ),
    ),
    Section(
        'Logging',
        'What kissterm keeps on disk. Local only: none of this reaches the '
        'air.',
        (
            Field(
                "log_sessions",
                "Save session transcripts",
                "bool",
                "One plain-text file per connection, in the log directory "
                "below: everything sent, everything received, and every link "
                "state change. The scrollback already holds the same text -- "
                "this is what makes it survive closing the app.",
                apply="connect",
            ),
            Field(
                "log_dir",
                "Log directory",
                "text",
                "Leave empty to use the default. 'kissterm --doctor' prints "
                "where that is.",
                apply="restart",
                placeholder='the default folder',
            ),
            Field(
                "monitor_filter",
                "Monitor filter",
                "text",
                "Starting filter for the Monitor pane: a callsign, or text to "
                "match in the payload.",
                apply="live",
                placeholder='a callsign or text; empty shows all',
            ),
            Field(
                "aprs_is_watch_debug",
                "APRS-IS watch in debug log",
                "bool",
                "While kissterm runs with --log-level debug, keep a receive-only "
                "APRS-IS stream open for your packets and replies addressed to you. "
                "It never keys RF or publishes to APRS-IS. Off by default.",
                apply="live",
                advanced=True,
            ),
        ),
    ),
)


# ---------------------------------------------------------------------------
# Dotted-path access, so a nested dataclass needs no special case in the pane
# ---------------------------------------------------------------------------
def get_value(config: Any, path: str) -> Any:
    target = config
    for part in path.split("."):
        target = getattr(target, part)
    return target


def set_value(config: Any, path: str, value: Any) -> None:
    parts = path.split(".")
    target = config
    for part in parts[:-1]:
        target = getattr(target, part)
    setattr(target, parts[-1], value)


class ValidationError(ValueError):
    """A typed-in value could not be accepted. Message is shown next to it."""


def coerce(field_spec: Field, raw: Any) -> Any:
    """Turn a widget value into the type `Config` expects, or raise.

    Validation lives here rather than in the pane so the rules are stated once,
    next to the field they belong to, and so a test can exercise them without
    mounting a UI.
    """
    kind = field_spec.kind

    if kind == "bool":
        return bool(raw)

    if kind == "choice":
        for _label, value in field_spec.choices:
            if raw == value or str(raw) == str(value):
                return value
        raise ValidationError("not one of the available options")

    text = str(raw).strip()

    if kind == "callsign":
        from ..ax25.address import AX25Address, AX25AddressError

        if not text:
            raise ValidationError("a callsign is required")
        try:
            AX25Address.parse(text)
        except AX25AddressError as exc:
            raise ValidationError(str(exc)) from None
        return text.upper()

    if kind == "color":
        if not HEX_COLOR_RE.match(text):
            raise ValidationError("must be a hex color like #1A1B26")
        return text

    if kind == "calllist":
        from ..ax25.address import AX25Address, AX25AddressError

        if not text:
            return []
        out = []
        for part in text.replace(",", " ").split():
            try:
                AX25Address.parse(part)
            except AX25AddressError as exc:
                raise ValidationError(f"{part}: {exc}") from None
            out.append(part.upper())
        return out

    if kind in ("int", "float"):
        if not text:
            raise ValidationError("a number is required")
        try:
            value = int(text) if kind == "int" else float(text)
        except ValueError:
            raise ValidationError(
                "must be a whole number" if kind == "int" else "must be a number"
            ) from None
        if field_spec.minimum is not None and value < field_spec.minimum:
            raise ValidationError(f"must be at least {field_spec.minimum:g}")
        if field_spec.maximum is not None and value > field_spec.maximum:
            raise ValidationError(f"must be at most {field_spec.maximum:g}")
        return value

    return text


def format_value(field_spec: Field, value: Any) -> str:
    """Render a stored value for display in a text input."""
    if field_spec.kind == "calllist":
        return ", ".join(value or ())
    if field_spec.kind == "float":
        return f"{float(value):g}"
    return "" if value is None else str(value)


def cross_check(config: Any) -> list[str]:
    """Rules that span more than one field, checked after all are coerced.

    `window` against `modulo` is the one that matters: at k equal to the
    modulo, a full window and an empty one are indistinguishable and the link
    jams after exactly one cycle. `config.py` and `SlidingWindow` both clamp
    it, but silently -- telling the operator here is better than letting them
    save 8 and find it became 7.
    """
    problems: list[str] = []
    top = config.modulo - 1
    if config.window > top:
        problems.append(
            f"Window {config.window} is too large for sequence mode "
            f"{config.modulo}; it will be clamped to {top}."
        )
    if config.t1 <= config.t2:
        problems.append(
            "T1 should be longer than T2, or an acknowledgement is still "
            "being held when the sender gives up waiting for it."
        )
    return problems
