"""What each radio transport kind needs to be set up: the form a client
draws for Settings > Radio (the terminal's `TransportEntryScreen`, the
phone's sheet), with no UI in it.

One table, so the two cannot disagree on which kinds there are or what
each asks for. `kissterm/core/radio.py` validates an entry against it and
`transport.build_transport` is the only constructor (AGENTS.md "One way to
build a transport").
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TransportField:
    """One kind-specific input. `key` is exactly the config key it fills --
    the same name `build_transport` forwards to that kind's constructor."""

    key: str
    label: str
    placeholder: str = ""
    default: str = ""
    numeric: bool = False
    password: bool = False
    optional: bool = False


#: Which fields each kind needs, and whether it is a session transport --
#: that decides whether the auto-login section applies at all (`Transport.
#: script`/`credential` are meaningful only to a `SessionTransport`; see
#: that field's docstring in `transport/base.py`). This is each kind's
#: REQUIRED constructor arguments, not its full parameter list -- an
#: advanced knob like serial's `kiss_params` or vara's `bandwidth` stays
#: something only `config.toml.example` documents, same as before this
#: dialog existed. Editing an entry that already has one of those set
#: preserves it rather than dropping it -- see `Radio.save_transport`.
TRANSPORT_FORMS: dict[str, tuple[bool, tuple[TransportField, ...]]] = {
    "tcp": (False, (
        TransportField("host", "Host", "e.g. 192.168.1.50"),
        TransportField("port", "Port", default="8001", numeric=True),
    )),
    "agwpe": (False, (
        TransportField("host", "Host", "e.g. 192.168.1.50"),
        TransportField("port", "Port", default="8000", numeric=True),
    )),
    "serial": (False, (
        TransportField("device", "Serial device", "e.g. /dev/ttyUSB0 or COM3"),
        TransportField("baud", "Baud rate", default="9600", numeric=True),
    )),
    "bluetooth": (False, (
        TransportField("address", "Bluetooth address", "e.g. 00:11:22:33:44:55"),
        TransportField("channel", "RFCOMM channel", default="1", numeric=True),
    )),
    "ble": (False, (
        TransportField("address", "Bluetooth address", "e.g. 00:11:22:33:44:55"),
    )),
    "kernel": (True, (
        TransportField("ax25_port", "AX.25 port", "e.g. radio0, from /etc/ax25/axports"),
        TransportField("mycall", "Callsign for this port", "e.g. N1ABC-1"),
    )),
    "vara": (True, (
        TransportField("host", "Host", "e.g. 127.0.0.1"),
        TransportField("mycall", "Callsign", "e.g. N1ABC-1"),
        TransportField("cmd_port", "Command port", default="8300", numeric=True),
        TransportField("data_port", "Data port", default="8301", numeric=True),
    )),
    "varafm": (True, (
        TransportField("host", "Host", "e.g. 127.0.0.1"),
        TransportField("mycall", "Callsign", "e.g. N1ABC-1"),
        TransportField("cmd_port", "Command port", default="8300", numeric=True),
        TransportField("data_port", "Data port", default="8301", numeric=True),
    )),
    "mercury": (True, (
        TransportField("host", "Host", "e.g. 127.0.0.1"),
        TransportField("port", "Port", default="8300", numeric=True),
        TransportField("mycall", "Callsign", "e.g. N1ABC-1"),
    )),
    # No Telnet or SSH: those are Address Book contacts, By Telnet or SSH
    # (ROADMAP P2, every contact in the Address Book), dialed beside the
    # radio rather than in its place.
}


@dataclass(frozen=True)
class EntryField:
    """One input of a Programs or Rigs entry. `kind` is "text", "number",
    "decimal", "bool", "choice" or "bands"; `key` is the config key."""

    key: str
    label: str
    kind: str = "text"
    placeholder: str = ""
    default: str = ""
    optional: bool = False
    advanced: bool = False
    choices: tuple[str, ...] = ()


#: Amateur bands a rig can be told to tune before a connect on (ROADMAP P3a
#: decision 5: tune-before-connect is per band, off everywhere by default --
#: the operator's 20 m and 80 m work best without the tuner, 40 m sometimes
#: needs it).
BANDS = ("160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m", "12m", "10m",
         "6m", "2m", "70cm")

#: A Programs entry. `path`, `args` and `cwd` decide what runs on the
#: station computer, so M2 decides who may edit them remotely.
PROGRAM_FORM: tuple[EntryField, ...] = (
    EntryField("preset", "Program", "choice"),
    EntryField("path", "Program file", placeholder="browse to the executable"),
    EntryField("args", "Arguments", optional=True),
    EntryField("wine", "Run under Wine", "bool", default="false", optional=True),
    EntryField("cwd", "Working folder", optional=True, advanced=True),
    EntryField("start_timeout", "Seconds to wait for it", "number", default="30",
               advanced=True),
    EntryField("stop_on_exit", "Stop it when kissterm exits", "bool", default="true",
               advanced=True),
)

#: A Rigs entry: a radio reached through Hamlib's `rigctld`.
RIG_FORM: tuple[EntryField, ...] = (
    EntryField("model", "Radio model (Hamlib number)", "number"),
    EntryField("device", "CAT serial device", placeholder="e.g. /dev/ttyUSB0 or COM3",
               optional=True),
    EntryField("speed", "CAT baud rate", "number", optional=True),
    EntryField("host", "rigctld host", default="127.0.0.1", advanced=True),
    EntryField("port", "rigctld port", "number", default="4532", advanced=True),
    EntryField("rigctld_path", "rigctld program", optional=True, advanced=True),
    EntryField("swr_trip", "Stop transmitting above SWR", "decimal", default="3.0"),
    EntryField("ptt_timeout", "Unkey after (seconds)", "number", default="120",
               advanced=True),
    EntryField("tune_bands", "Tune the ATU before connecting on", "bands", optional=True),
)
