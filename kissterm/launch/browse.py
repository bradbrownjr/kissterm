"""Browsing the station computer's files to find a modem program.

The operator wants to pick the executable "wherever they sit", from a
paired phone as well as the terminal (ROADMAP P3a decision 1, 2026-10-09),
with the listing **filtered to what a program could be** so that the
browser is not a general file viewer:

- folders (to reach the program) and, of files, only executables: on POSIX a
  regular file with the execute bit, and a `.exe` for Wine; on Windows a
  `.exe` or `.com`. Scripts (`.bat`, `.cmd`, `.ps1`, `.vbs`, `.sh`) are not
  offered: they are how a modem path becomes a shell.
- names only: no sizes, dates, owners or contents.
- no hidden entries (a leading dot), a cap of `MAX_ENTRIES`, and nothing
  that cannot be read is an error, just absent.

This is a convenience and a smaller surface, **not** a security boundary:
the pairing (QR code or link, `serve/`) is what decides who may ask, and
`validate_path` is what keeps a saved path to an existing executable file.
"""

from __future__ import annotations

import os
import string
import sys
from dataclasses import dataclass, field

MAX_ENTRIES = 500
WINDOWS_EXTENSIONS = (".exe", ".com")
WINE_EXTENSIONS = (".exe",)


@dataclass
class Listing:
    path: str
    parent: str = ""
    folders: list[str] = field(default_factory=list)
    programs: list[str] = field(default_factory=list)
    truncated: bool = False
    error: str = ""

    def to_dict(self) -> dict:
        return {"path": self.path, "parent": self.parent, "folders": self.folders,
                "programs": self.programs, "truncated": self.truncated, "error": self.error}


def is_program(path: str, *, windows: bool | None = None) -> bool:
    """Whether `path` is a file a Programs entry could run here."""
    windows = sys.platform.startswith("win") if windows is None else windows
    if not os.path.isfile(path):
        return False
    lower = path.lower()
    if windows:
        return lower.endswith(WINDOWS_EXTENSIONS)
    return os.access(path, os.X_OK) or lower.endswith(WINE_EXTENSIONS)


def validate_path(path: str, *, windows: bool | None = None) -> str:
    """"" when `path` is an existing file a program entry may name, else why
    not (the words for the form). A bare command (`mercury.exe`) is looked
    up on PATH as the supervisor does."""
    import shutil

    text = str(path or "").strip()
    if not text:
        return "Program file is required."
    found = text if os.path.isfile(text) else shutil.which(text)
    if not found:
        return f"{text!r} is not a file on this computer."
    if not is_program(found, windows=windows):
        return f"{found!r} is not an executable program."
    return ""


def _roots() -> list[str]:
    if sys.platform.startswith("win"):
        return [f"{letter}:\\" for letter in string.ascii_uppercase
                if os.path.exists(f"{letter}:\\")]
    return ["/"]


def list_dir(path: str = "", *, windows: bool | None = None) -> Listing:
    """The folders and programs in `path` ("" is the home folder; on
    Windows "" with no home lists the drives). Never raises."""
    windows = sys.platform.startswith("win") if windows is None else windows
    start = path or os.path.expanduser("~")
    try:
        real = os.path.realpath(start)
    except (OSError, ValueError) as exc:
        return Listing(start, error=f"Cannot open {start!r}: {exc}")
    listing = Listing(real)
    parent = os.path.dirname(real.rstrip("\\/")) if real.rstrip("\\/") else ""
    listing.parent = parent if parent and parent != real else ""
    try:
        names = sorted(os.listdir(real), key=str.lower)
    except OSError as exc:
        listing.error = f"Cannot read {real!r}: {exc.strerror or exc}"
        return listing
    count = 0
    for name in names:
        if name.startswith("."):
            continue
        full = os.path.join(real, name)
        try:
            if os.path.isdir(full):
                bucket = listing.folders
            elif is_program(full, windows=windows):
                bucket = listing.programs
            else:
                continue
        except OSError:
            continue
        if count >= MAX_ENTRIES:
            listing.truncated = True
            break
        bucket.append(name)
        count += 1
    return listing


def roots() -> list[str]:
    """Where to start when the home folder is not the place: `/`, or the
    drive letters."""
    return _roots()
