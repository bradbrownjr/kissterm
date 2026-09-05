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

from .themes import choices as _theme_choices


@dataclass(frozen=True, slots=True)
class Field:
    """One editable setting.

    `path` is dotted so a nested dataclass (`aprs.latitude`) needs no special
    case in the pane -- see `get_value`/`set_value` below.
    """

    path: str
    label: str
    kind: str  # "text" | "int" | "float" | "bool" | "choice" | "callsign" | "calllist"
    help: str = ""
    apply: str = "connect"
    choices: tuple[tuple[str, Any], ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    placeholder: str = ""


@dataclass(frozen=True, slots=True)
class Section:
    title: str
    note: str
    fields: tuple[Field, ...]


SETTINGS_SCHEMA: tuple[Section, ...] = (
    Section(
        "Station",
        "Who you are on the air.",
        (
            Field(
                "mycall",
                "Callsign",
                "callsign",
                "Your callsign with SSID. Also changeable any time with Ctrl+K.",
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
        "Link",
        "AX.25 timing and framing. The defaults suit 1200-baud VHF; HF wants "
        "shorter frames and longer timers.",
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
                "modulo",
                "Sequence mode",
                "choice",
                "Leave this at 8. Every BPQ32 node, KA-Node and TNC2-class "
                "station on the air speaks it. A peer that does not understand "
                "128 answers DM and kissterm falls back by itself.",
                choices=(("8 (standard)", 8), ("128 (extended)", 128)),
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
                "retries",
                "Retries (N2)",
                "int",
                "How many times to retry before declaring the link dead.",
                minimum=1,
                maximum=100,
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
            ),
        ),
    ),
    Section(
        "APRS",
        "APRS rides on the same AX.25 UI frames the monitor already decodes.",
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
                "aprs.beacon_interval_minutes",
                "Beacon every (min)",
                "int",
                "Beaconing more often than every 10 minutes on a shared "
                "channel is antisocial unless you are moving.",
                minimum=1,
                maximum=1440,
                apply="live",
            ),
            Field(
                "aprs.latitude",
                "Latitude",
                "float",
                "Decimal degrees, north positive.",
                minimum=-90.0,
                maximum=90.0,
                apply="live",
            ),
            Field(
                "aprs.longitude",
                "Longitude",
                "float",
                "Decimal degrees, east positive.",
                minimum=-180.0,
                maximum=180.0,
                apply="live",
            ),
            Field(
                "aprs.symbol",
                "Map symbol",
                "text",
                "Two characters: table selector then symbol code. '/>' is a "
                "car, '/-' a house, '/y' a house with an antenna.",
                apply="live",
                placeholder="/>",
            ),
            Field(
                "aprs.path",
                "Digipeater path",
                "text",
                "WIDE1-1,WIDE2-1 is the normal path. Longer paths clog the "
                "network for everyone and are considered poor practice.",
                apply="live",
                placeholder="WIDE1-1,WIDE2-1",
            ),
            Field(
                "aprs.comment",
                "Beacon comment",
                "text",
                "Free text appended to your position report.",
                apply="live",
            ),
        ),
    ),
    Section(
        "Unattended operation",
        "Answering a call transmits under your callsign with nobody present. "
        "You remain the control operator. Off unless you turn it on.",
        (
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
        ),
    ),
    Section(
        "Appearance",
        "Every color in kissterm is a theme variable, so switching here "
        "repaints instantly -- nothing to restart.",
        (
            Field(
                "theme",
                "Theme",
                "choice",
                "'Terminal ANSI' uses your terminal emulator's own 16-color "
                "palette directly, which is the closest thing to automatic "
                "syncing with an external terminal theme. 'Custom' reads "
                "exact hex values from config.toml's [custom_theme] table -- "
                "not yet editable here, see docs/ROADMAP.md.",
                apply="live",
                choices=_theme_choices(),
            ),
        ),
    ),
    Section(
        "Display and logging",
        "Local only -- none of this reaches the air.",
        (
            Field(
                "monitor_filter",
                "Monitor filter",
                "text",
                "Starting filter for the Monitor pane: a callsign, or text to "
                "match in the payload.",
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
                "log_dir",
                "Log directory",
                "text",
                "Leave empty to use the default. 'kissterm --doctor' prints "
                "where that is.",
                apply="restart",
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
