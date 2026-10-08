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
