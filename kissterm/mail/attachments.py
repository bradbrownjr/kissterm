"""Saving a received message's attachments into Files/Attachments.

ROADMAP P2 (Winlink attachments) under P10's rules for anything that
arrived over the air. The name and the bytes come from a station nobody
has authenticated, so:

- **The name is cleaned, never trusted.** Only its last path component is
  kept (a `../../.bashrc` lands as `.bashrc`, then loses the leading dot),
  control, format and bidi characters are dropped (a right-to-left override
  is how `readme[RLO]txt.exe` displays as `readmeexe.txt`), characters that
  are illegal in a file name somewhere are replaced, and the length is
  capped keeping the real extension. Windows' reserved device names get a
  prefix. What is left is never empty.
- **Nothing is overwritten.** A name already present gets `-1`, `-2`...
  before its extension, and the file is created exclusively.
- **Nothing is opened or run.** This only writes bytes; the Files tab shows
  text through `monitor.sanitize` and anything binary as "not a text file".

The folder is flat: a folder per message would crowd the tree. Where each
file went is written into the message's Attachments line, so the sender
and date stay with it (`winlink_collect.WinlinkCollector`).
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

#: Longest name kept, in characters, extension included.
MAX_NAME = 100
_ILLEGAL = re.compile(r'[<>:"/\\|?*]')
_SPACES = re.compile(r"\s+")
_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.IGNORECASE)


def safe_filename(name: str, fallback: str = "attachment") -> str:
    """`name` as a file name that is safe to create and to display."""
    name = re.split(r"[/\\]", name)[-1]
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] not in ("C", "Z")
                   or ch == " ")
    name = _SPACES.sub(" ", _ILLEGAL.sub("_", name)).strip(" .")
    name = name.lstrip(".")
    if len(name) > MAX_NAME:
        stem, dot, extension = name.rpartition(".")
        if dot and 0 < len(extension) <= 10:
            name = stem[: MAX_NAME - len(extension) - 1].rstrip(" .") + "." + extension
        else:
            name = name[:MAX_NAME].rstrip(" .")
    if _RESERVED.match(name):
        name = "_" + name
    return name or fallback


def save_attachment(directory: Path, name: str, data: bytes) -> Path:
    """Write `data` under a cleaned, unused version of `name` in `directory`
    (created if needed); returns where it went. Raises `OSError`."""
    directory.mkdir(parents=True, exist_ok=True)
    clean = safe_filename(name)
    stem, dot, extension = clean.rpartition(".")
    if not dot or not stem:
        stem, extension = clean, ""
    suffix = f".{extension}" if extension else ""
    for index in range(10_000):
        candidate = directory / (clean if index == 0 else f"{stem}-{index}{suffix}")
        try:
            descriptor = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            continue
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        return candidate
    raise OSError(f"too many files named {clean!r}")
