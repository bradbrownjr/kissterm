"""Giving a modem program the shared `rigctld` to key through (ROADMAP P3a M5c).

A Programs entry whose `keying` is "Through kissterm's rig control" and whose
transport names a rig has exactly one keying path: kissterm's `rigctld`.
VARA asks the application for it over its command port (`core/ptt.py`);
Mercury and Direwolf key the radio themselves, so they are handed the
`rigctld` endpoint when kissterm starts them. Pure data in, arguments out;
the supervisor does the starting (`Supervisor.start`).

**Mercury** (README, "PTT control notes"): `-R model` "selects the model and
the `hamlib` PTT method" and `-A` "supplies its device or `ip:port`". Hamlib
model 2 is NET rigctl, whose device is `host:port`; Mercury's
`radio_io/radio_io.c` special-cases `RIG_MODEL_NETRIGCTL` (it sets the VFO
mode the daemon reports), so `-R 2 -A 127.0.0.1:4532` is a path the program
itself handles. Mercury built with `HAVE_HAMLIB=0` reports "HAMLIB support
not compiled in" and keys nothing; the operator sees that in its output.

**Direwolf** has no command-line PTT option and no include directive in its
configuration (`src/config.c`), only the line `PTT RIG model port`, with
"when model is 2, port would host:port like 127.0.0.1:4532", applying to the
most recent `CHANNEL`. So kissterm writes a copy of the operator's file with
`CHANNEL 0` and that line appended, into its own state folder, and starts
Direwolf on the copy with `-c`. The operator's file is never modified.
Appended last, the line overrides any earlier `PTT` for channel 0; a second
radio channel keeps whatever the operator gave it. Direwolf's Windows build
refuses `PTT RIG` ("Windows version of direwolf does not support HAMLIB")
and exits, so on Windows kissterm says so instead of starting it.

# UNVERIFIED: against a running Mercury or Direwolf (docs/ON-AIR-TESTS.md).
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

#: Hamlib's NET rigctl model: talks to a `rigctld` at host:port.
NETRIGCTL_MODEL = 2


class KeyingError(Exception):
    """The program cannot be given the shared rigctld; the message says why."""


def wants_rigctld(program: dict[str, Any] | None) -> bool:
    return bool(program and program.get("keying") == "rigctld"
                and program.get("preset") in ("mercury", "direwolf"))


def endpoint(rig: dict[str, Any]) -> str:
    from ..rig.rigctld import DEFAULT_PORT

    return f"{rig.get('host') or '127.0.0.1'}:{int(rig.get('port') or DEFAULT_PORT)}"


def mercury_args(rig: dict[str, Any]) -> list[str]:
    return ["-R", str(NETRIGCTL_MODEL), "-A", endpoint(rig)]


def _split(text: str, platform: str) -> list[str]:
    try:
        return shlex.split(text, posix=not platform.startswith("win"))
    except ValueError as exc:
        raise KeyingError(f"The arguments are not valid: {exc}") from exc


def direwolf_config_path(args: str, cwd: str, platform: str) -> Path:
    """The operator's Direwolf file: the `-c` argument, else `direwolf.conf`
    in the working folder (direwolf(1))."""
    words = _split(args, platform)
    given = ""
    for i, word in enumerate(words):
        if word == "-c" and i + 1 < len(words):
            given = words[i + 1]
        elif word.startswith("-c") and len(word) > 2:
            given = word[2:]
    path = Path(given) if given else Path("direwolf.conf")
    if not path.is_absolute() and cwd:
        path = Path(cwd) / path
    return path


def direwolf_config_text(original: str, rig: dict[str, Any]) -> str:
    tail = "" if original.endswith("\n") or not original else "\n"
    return (f"{original}{tail}\n# Added by kissterm: key through its shared rigctld.\n"
            f"CHANNEL 0\nPTT RIG {NETRIGCTL_MODEL} {endpoint(rig)}\n")


def direwolf_args(args: str, derived: Path, platform: str) -> str:
    """`args` with its `-c file` replaced by (or given) the derived file."""
    words = _split(args, platform)
    out: list[str] = []
    skip = False
    for word in words:
        if skip:
            skip = False
        elif word == "-c":
            skip = True
        elif word.startswith("-c") and len(word) > 2:
            continue
        else:
            out.append(word)
    out += ["-c", str(derived)]
    return " ".join(shlex.quote(w) if not platform.startswith("win") else
                    (f'"{w}"' if " " in w else w) for w in out)


def keyed_program(program: dict[str, Any], rig: dict[str, Any], state_dir: Path,
                  *, platform: str) -> dict[str, Any]:
    """A copy of `program` that keys through `rig`'s rigctld. Raises
    `KeyingError`. Writes the derived Direwolf file (nothing else)."""
    preset = program.get("preset")
    out = dict(program)
    if preset == "mercury":
        out["args"] = (str(program.get("args") or "") + " "
                       + " ".join(shlex.quote(a) for a in mercury_args(rig))).strip()
        return out
    if preset != "direwolf":
        return out
    if platform.startswith("win"):
        raise KeyingError(
            "Direwolf for Windows does not support Hamlib, so it cannot key through "
            "kissterm's rig control. Pick another way for it to key the radio.")
    source = direwolf_config_path(str(program.get("args") or ""),
                                  str(program.get("cwd") or ""), platform)
    try:
        original = source.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise KeyingError(
            f"Direwolf's configuration file {source} could not be read ({exc}); "
            "kissterm adds the rig control line to a copy of it.") from exc
    derived = state_dir / f"direwolf-{_safe(str(program.get('name') or 'program'))}.conf"
    try:
        derived.parent.mkdir(parents=True, exist_ok=True)
        derived.write_text(direwolf_config_text(original, rig), encoding="utf-8")
    except OSError as exc:
        raise KeyingError(f"Could not write {derived}: {exc}") from exc
    out["args"] = direwolf_args(str(program.get("args") or ""), derived, platform)
    return out


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name) or "program"
