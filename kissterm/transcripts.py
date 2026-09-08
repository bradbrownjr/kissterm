"""Finding, searching and exporting past session transcripts.

`kissterm/session_log.py` already writes one plain-text file per connected
session, but until now the only way to find one again was a shell and
`ls`/`grep` on the log directory -- a real gap for an operator who wants to
know what was actually said to a station months ago and would rather not
leave the app to look. This module is the read side of that gap: list what
is on disk, filter it by peer/callsign or by what is actually inside a file,
and copy one out to wherever the operator wants it kept.

Deliberately read-only (aside from `export_transcript`'s copy) and free of
any Textual import, so it can be tested head-on with `tmp_path` and no
running app -- the same pattern `session_log.py` and `heard.py` already use.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

#: Matches the shape `session_log.transcript_name()` produces:
#: YYYYMMDD-HHMMSS_MYCALL_PEER.log. A `.log` file that does not match this --
#: an operator's own note dropped into the log directory, say, or a name from
#: some earlier version of this app -- is still listed by `list_transcripts`,
#: just without a parsed call/peer/date to show or filter on.
_NAME_RE = re.compile(
    r"^(?P<stamp>\d{8}-\d{6})_(?P<mycall>[A-Za-z0-9-]+)_(?P<peer>[A-Za-z0-9-]+)\.log$"
)


@dataclass
class TranscriptInfo:
    """One transcript file, with whatever its filename encodes.

    `started`/`mycall`/`peer` are empty strings when the filename did not
    match the expected shape -- callers show `path.name` in that case rather
    than blank columns.
    """

    path: Path
    started: str
    mycall: str
    peer: str
    size: int


def list_transcripts(directory: Path) -> list[TranscriptInfo]:
    """Every `.log` file in `directory`, newest session first.

    A directory that does not exist yet -- no session has ever connected --
    is not an error; there is simply nothing to list.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []
    out: list[TranscriptInfo] = []
    for path in directory.glob("*.log"):
        try:
            size = path.stat().st_size
        except OSError:
            # Gone between the glob and the stat (rotated out from under us,
            # say). Skip it rather than raising out of a listing.
            continue
        match = _NAME_RE.match(path.name)
        if match:
            stamp = match.group("stamp")
            started = (
                f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]} "
                f"{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}"
            )
            mycall, peer = match.group("mycall"), match.group("peer")
        else:
            started, mycall, peer = "", "", ""
        out.append(TranscriptInfo(path, started, mycall, peer, size))
    # Filenames are timestamp-first (see transcript_name's docstring), so a
    # plain reverse name sort is already newest-first with no date parsing.
    out.sort(key=lambda info: info.path.name, reverse=True)
    return out


def search_transcripts(directory: Path, needle: str) -> list[TranscriptInfo]:
    """Transcripts whose peer, callsign or filename match `needle` -- or,
    failing that, whose CONTENT does.

    The content fallback only runs for files the cheap filename check did
    not already match, and only reads what it needs to: real transcripts are
    per-session plain text, realistically a few kilobytes, so scanning the
    handful left after the filename pass costs nothing worth indexing for.
    A file that fails to read (permissions, or a very old session log left
    mid-write by a crash) is skipped rather than raised -- the same "a log
    problem must never surface as a crash" rule `session_log.py` follows.
    """
    needle = needle.strip()
    transcripts = list_transcripts(directory)
    if not needle:
        return transcripts
    lowered = needle.lower()
    out = []
    for info in transcripts:
        if (
            lowered in info.peer.lower()
            or lowered in info.mycall.lower()
            or lowered in info.path.name.lower()
        ):
            out.append(info)
            continue
        try:
            text = info.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if lowered in text.lower():
            out.append(info)
    return out


def export_transcript(info: TranscriptInfo, destination: Path) -> None:
    """Copy a transcript to `destination`.

    Raises `OSError` on failure rather than swallowing it -- unlike
    `SessionLog`, this runs from a one-shot UI action with no live link to
    protect, so the caller can and should turn a failure straight into a
    notification instead of it disappearing silently.

    Creates the destination's parent directory if needed, the same courtesy
    `SessionLog.open()` extends to the log directory itself -- an operator
    typing `~/packet-logs/ws1ec.log` should not also have to `mkdir` first.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(info.path, destination)
