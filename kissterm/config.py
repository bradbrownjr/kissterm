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
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import platformdirs

from .ax25.address import AX25Address, AX25AddressError

APP_NAME = "kissterm"

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
    symbol: str = "/>"
    latitude: float = 0.0
    longitude: float = 0.0
    comment: str = ""
    #: Default digipeater path. WIDE1-1,WIDE2-1 is the conventional "new
    #: N-paradigm" path that gets a beacon out one hop then two wide hops
    #: without flooding a whole region the way WIDE7-7 once did.
    path: str = "WIDE1-1,WIDE2-1"


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
    #: T1: how long to wait for an ack before retransmitting (seconds).
    t1: float = 3.0
    #: T2: how long to delay an ack in case an outgoing I-frame can piggyback
    #: it instead (seconds).
    t2: float = 3.0
    #: T3: idle-link keepalive poll interval (seconds).
    t3: float = 300.0
    #: Free-text filter applied to the monitor pane, e.g. "APRS" or a callsign.
    monitor_filter: str = ""
    #: Empty means "use log_path()" -- see that function below.
    log_dir: str = ""
    theme: str = "default"
    #: Force plain ASCII box-drawing and no emoji/Unicode glyphs, for a
    #: terminal (an old TTY, a serial console, some SSH clients) that mangles
    #: anything past code page 437.
    ascii_safe: bool = False
    aprs: AprsConfig = field(default_factory=AprsConfig)
    #: Saved connect targets: dicts with at least a "target" callsign and
    #: optionally a "path" (digipeater route) and a "transport" name.
    autoconnect: list[dict[str, Any]] = field(default_factory=list)
    #: Populated by `load_config()`; never written to the file. See the
    #: module docstring for why this exists instead of an exception.
    warnings: list[str] = field(default_factory=list, repr=False, compare=False)


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


def config_path() -> Path:
    """Where `config.toml` lives (or will be created)."""
    return _CONFIG_DIR / "config.toml"


def log_path() -> Path:
    """Where session logs go by default (overridden by `Config.log_dir`)."""
    return _STATE_DIR / "logs"


def state_path() -> Path:
    """Where other persistent-but-not-config data goes (heard lists, etc.)."""
    return _DATA_DIR


# ---------------------------------------------------------------------------
# Loading -- defensive by construction, see module docstring
# ---------------------------------------------------------------------------


def load_config(path: Path | None = None) -> Config:
    """Load `Config` from TOML at `path` (default `config_path()`).

    Never raises. A missing file yields plain defaults with no warnings (a
    first run is not an error). A present-but-broken file -- bad syntax, a
    field of the wrong type, an invalid callsign -- yields defaults for
    whatever is broken plus an entry in the returned `Config.warnings` for
    each problem, and the same problems are logged. Every field is validated
    independently, so one typo does not take the rest of a working config
    down with it.
    """
    path = path or config_path()
    warnings: list[str] = []
    raw: dict[str, Any] = {}

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

    cfg = Config()
    cfg.mycall = _load_callsign(raw.get("mycall", ""), "mycall", warnings)
    cfg.mycall_aliases = _load_callsign_list(raw.get("mycall_aliases", []), warnings)
    cfg.transports = _load_dict_list(raw.get("transports", []), "transports", warnings)
    cfg.active_transport = _load_str(raw, "active_transport", cfg.active_transport, warnings)
    cfg.paclen = _load_int(raw, "paclen", cfg.paclen, warnings)
    cfg.modulo = _load_modulo(raw.get("modulo", cfg.modulo), warnings)
    cfg.window = _load_window(raw.get("window", cfg.window), warnings, cfg.modulo)
    cfg.retries = _load_int(raw, "retries", cfg.retries, warnings)
    cfg.t1 = _load_float(raw, "t1", cfg.t1, warnings)
    cfg.t2 = _load_float(raw, "t2", cfg.t2, warnings)
    cfg.t3 = _load_float(raw, "t3", cfg.t3, warnings)
    cfg.monitor_filter = _load_str(raw, "monitor_filter", cfg.monitor_filter, warnings)
    cfg.log_dir = _load_str(raw, "log_dir", cfg.log_dir, warnings)
    cfg.theme = _load_str(raw, "theme", cfg.theme, warnings)
    cfg.ascii_safe = _load_bool(raw, "ascii_safe", cfg.ascii_safe, warnings)
    cfg.aprs = _load_aprs(raw.get("aprs", {}), warnings)
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

    return aprs


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
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = dataclasses.asdict(config)
    data.pop("warnings", None)
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


def _toml_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


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
