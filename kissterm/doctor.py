"""`kissterm --doctor` -- one command that answers "why won't this connect."

The people who need this the most are the people least equipped to debug it
cold: a new ham whose TNC "just doesn't work," or an experienced operator on
someone else's Raspberry Pi at a public-service event with five minutes to
get on the air. Both need a single command that inspects the same things a
patient human helper would ask about in order -- Python version, optional
packages, the callsign, the config file, whether the configured transports
actually open, serial group permissions, log directory writability, terminal
capabilities -- and states plainly what is wrong and what to type next.

Every check produces a `Check` with a concrete `remedy`: a literal command
to run or file to edit, not "check your serial port settings." "Vague
advice" is what makes people give up on a diagnostic tool and start pasting
error messages into a search engine instead; a `remedy` field exists so that
never has to be the fallback.

`run_diagnostics` runs every check even if an earlier one failed -- a dead
transport should not hide a wrong callsign -- so each check function is
individually defensive: it catches its own exceptions and turns them into a
`fail` result rather than letting one bad check take the rest of the report
down, for exactly the reason `kissterm.config.load_config` never raises.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import logging
import os
import shutil
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ax25.address import AX25Address, AX25AddressError
from .config import Config, config_path, log_path

logger = logging.getLogger(__name__)

#: The set of values `Check.status` may take. "skip" is not a failure -- it
#: means the check does not apply here (a non-serial transport, a non-Linux
#: platform for the group-membership check).
_STATUS_ORDER = ("ok", "warn", "fail", "skip")


@dataclass(slots=True)
class Check:
    """One diagnostic result. `remedy` is empty exactly when there is nothing
    to do about `status` -- i.e. usually only when `status` is "ok"."""

    name: str
    status: str  # "ok" | "warn" | "fail" | "skip"
    detail: str
    remedy: str = ""


async def run_diagnostics(config: Config) -> list[Check]:
    """Run every check and return the full list, in a fixed, stable order."""
    checks: list[Check] = []
    checks.append(_check_python_version())
    checks.extend(_check_optional_deps())
    checks.append(_check_callsign(config))
    checks.append(_check_config_file())
    checks.append(_check_config_warnings(config))
    checks.extend(await _check_transports(config))
    checks.append(_check_serial_permissions())
    checks.append(_check_log_dir(config))
    checks.append(_check_terminal())
    return checks


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_python_version() -> Check:
    v = sys.version_info
    version = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) >= (3, 11):
        return Check("python version", "ok", version, "")
    return Check(
        "python version",
        "fail",
        f"{version} (kissterm needs 3.11+)",
        "install Python 3.11 or newer and run kissterm with it",
    )


#: (importable module name, what it unlocks, pip package to install)
_OPTIONAL_DEPS: tuple[tuple[str, str, str], ...] = (
    ("serial", "USB/local serial TNC support", "pyserial"),
    ("serial_asyncio_fast", "fast async serial I/O (preferred serial backend)", "pyserial-asyncio-fast"),
    ("serial_asyncio", "async serial I/O (fallback serial backend)", "pyserial-asyncio"),
    ("bleak", "Bluetooth LE TNC discovery and I/O", "bleak"),
)


def _check_optional_deps() -> list[Check]:
    out: list[Check] = []
    for module, unlocks, pip_name in _OPTIONAL_DEPS:
        try:
            present = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            present = False
        if present:
            out.append(Check(f"dependency: {module}", "ok", f"installed -- unlocks {unlocks}", ""))
        else:
            out.append(
                Check(
                    f"dependency: {module}",
                    "warn",
                    f"not installed -- {unlocks} unavailable",
                    f"pip install {pip_name}",
                )
            )
    return out


def _check_callsign(config: Config) -> Check:
    if not config.mycall:
        return Check(
            "callsign",
            "fail",
            "mycall is not set",
            'set mycall in config.toml, e.g. mycall = "W1AW-1"',
        )
    try:
        AX25Address.parse(config.mycall)
    except AX25AddressError as exc:
        return Check(
            "callsign",
            "fail",
            f"mycall {config.mycall!r} is invalid: {exc}",
            'fix mycall in config.toml, e.g. mycall = "W1AW-1"',
        )
    return Check("callsign", "ok", f"mycall = {config.mycall}", "")


def _check_config_file() -> Check:
    path = config_path()
    if not path.exists():
        return Check(
            "config file",
            "warn",
            f"no config file at {path}; running on defaults",
            f"copy config.toml.example to {path} and edit it, or let kissterm's setup wizard create one",
        )
    if not os.access(path, os.R_OK):
        return Check(
            "config file",
            "fail",
            f"{path} exists but is not readable",
            f"chmod u+r {path}",
        )
    return Check("config file", "ok", str(path), "")


def _check_config_warnings(config: Config) -> Check:
    if not config.warnings:
        return Check("config contents", "ok", "no warnings from the last load", "")
    detail = "; ".join(config.warnings)
    return Check(
        "config contents",
        "warn",
        detail,
        f"edit the fields named above in {config_path()}",
    )


async def _check_transports(config: Config) -> list[Check]:
    if not config.transports:
        return [
            Check(
                "transports",
                "warn",
                "no transports configured",
                "run discovery (kissterm --discover) or add a [[transports]] entry to config.toml",
            )
        ]
    return [await _check_one_transport(entry) for entry in config.transports]


def _build_transport(entry: dict[str, Any]) -> Any:
    """Construct a `Transport` for a doctor connectivity check, or `None`
    for a `kind` this build does not have a transport implementation for
    yet (agwpe, bluetooth, kernel, vara) -- those are reported as skipped,
    not failed, since "unimplemented" is not the same problem as "broken."
    """
    kind = entry.get("kind")
    if kind == "serial":
        from .transport.serial_kiss import SerialKissTransport

        device = entry["device"]
        return SerialKissTransport(device, baud=int(entry.get("baud", 9600)))
    if kind == "tcp":
        from .transport.tcp_kiss import TcpKissTransport

        return TcpKissTransport(entry["host"], port=int(entry.get("port", 8001)))
    return None


async def _check_one_transport(entry: dict[str, Any]) -> Check:
    name = entry.get("name") or entry.get("kind") or "?"
    kind = entry.get("kind", "?")

    try:
        transport = _build_transport(entry)
    except Exception as exc:  # noqa: BLE001 -- a malformed entry is a check result, not a crash
        return Check(
            f"transport: {name}",
            "fail",
            f"could not build {kind!r} transport from its config entry: {exc}",
            f"check the [[transports]] entry named {name!r} in config.toml",
        )

    if transport is None:
        return Check(
            f"transport: {name}",
            "skip",
            f"kind {kind!r} has no connectivity check in this build yet",
            "",
        )

    try:
        await asyncio.wait_for(transport.open(), timeout=5.0)
    except Exception as exc:  # noqa: BLE001
        return Check(
            f"transport: {name}",
            "fail",
            f"could not open {kind} transport: {exc}",
            "verify the device/host is correct, powered on, and reachable",
        )
    else:
        return Check(
            f"transport: {name}",
            "ok",
            f"{kind} ({transport.info.detail}) opened and closed cleanly",
            "",
        )
    finally:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(transport.close(), timeout=5.0)


def _check_serial_permissions() -> Check:
    if sys.platform not in ("linux", "linux2"):
        return Check(
            "serial permissions",
            "skip",
            f"group-based serial permissions do not apply on {sys.platform}",
            "",
        )
    try:
        import grp

        group_names = {grp.getgrgid(gid).gr_name for gid in os.getgroups()}
    except (ImportError, OSError, KeyError) as exc:
        return Check("serial permissions", "warn", f"could not read group membership: {exc}", "")

    needed = {"dialout", "uucp"}
    matched = group_names & needed
    if matched:
        return Check("serial permissions", "ok", f"user is in {sorted(matched)}", "")
    return Check(
        "serial permissions",
        "warn",
        "user is not in 'dialout' or 'uucp' -- opening a serial TNC will likely fail with Permission denied",
        "sudo usermod -aG dialout $USER   (then log out and back in)",
    )


def _check_log_dir(config: Config) -> Check:
    path = Path(config.log_dir) if config.log_dir else log_path()
    if path.exists() and not path.is_dir():
        # Distinguish this from a permissions problem: the remedy is to delete
        # the file, and "not writable" sends the operator chasing chmod.
        return Check(
            "log directory",
            "fail",
            f"{path} exists but is a file, not a directory",
            f"remove it: rm {path}",
        )
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".kissterm-doctor-write-test"
        probe.write_text("ok", encoding="ascii")
        probe.unlink()
    except OSError as exc:
        return Check(
            "log directory",
            "fail",
            f"{path} is not writable: {exc}",
            f"fix permissions on {path}, or set log_dir in config.toml to a writable path",
        )
    return Check("log directory", "ok", str(path), "")


def _check_terminal() -> Check:
    size = shutil.get_terminal_size(fallback=(0, 0))
    term = os.environ.get("TERM", "")
    colorterm = os.environ.get("COLORTERM", "")
    truecolor = "truecolor" in colorterm or "24bit" in colorterm
    encoding = (sys.stdout.encoding or "").upper()
    unicode_ok = "UTF" in encoding

    detail = (
        f"{size.columns}x{size.lines}, TERM={term or '?'}, "
        f"COLORTERM={colorterm or '?'}, encoding={encoding or '?'}"
    )

    if size.columns < 80 or size.lines < 24:
        return Check("terminal", "warn", f"{detail} -- smaller than the recommended 80x24", "resize the terminal window")
    if not unicode_ok:
        return Check(
            "terminal",
            "warn",
            f"{detail} -- not reporting a UTF-8 encoding",
            "set ascii_safe = true in config.toml, or switch to a UTF-8 locale",
        )
    if not truecolor:
        return Check(
            "terminal",
            "warn",
            f"{detail} -- no truecolor reported; theme colors may look approximate",
            "set COLORTERM=truecolor if your terminal emulator supports it",
        )
    return Check("terminal", "ok", detail, "")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def format_report(checks: list[Check]) -> str:
    """Render `checks` as plain ASCII text suitable for pasting into a bug
    report -- no emoji, no ANSI color codes, fixed-width alignment only."""
    if not checks:
        return "no checks were run"

    name_width = max(len(c.name) for c in checks)
    status_width = max(len(c.status) for c in checks)

    lines = ["kissterm diagnostic report", "=" * len("kissterm diagnostic report"), ""]
    for check in checks:
        lines.append(
            f"[{check.status.upper():<{status_width}}] {check.name:<{name_width}}  {check.detail}"
        )
        if check.remedy:
            pad = " " * (status_width + name_width + 4)
            lines.append(f"{pad}-> {check.remedy}")

    counts = Counter(c.status for c in checks)
    summary = ", ".join(f"{counts[s]} {s}" for s in _STATUS_ORDER if counts.get(s))
    lines.append("")
    lines.append(f"summary: {summary}")
    return "\n".join(lines)
