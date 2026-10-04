"""The Home BBS's files: BPQMail's `FILES` listing, and what one costs.

G on the Files tab (ROADMAP P2, Files) sends `FILES`, offers what it
lists, and downloads each file ticked with `YAPP <name>` into Files >
Downloads (`collect.BbsCollector`, `yapp.receive_file`).

**From LinBPQ's `BBSUtilities.c`** (`FILES`/`LISTFILES`, read 2026-10-03;
docs/SOURCES.md): one `name size` line per file in the BBS's `Files`
folder, alphabetical, dot-files skipped, then the prompt. **Checked
against a capture** (WS1EC-2, 2026-10-03,
`tests/unit/data/bpqmail/files_ws1ec.txt`): eight files and a last line
`zType YAPP FILENAME to retrieve 0`, a sysop's empty file whose name is a
hint. A name with a space, or a size of 0, is not offered: `YAPP` reads
its argument up to the first space, and an empty file is no download. Nor
is a name BPQ would refuse (`..`, `/`, `\\`; `YAPPSendFile`'s
"Invalid filename"), or one `yapp.receive_file` would not save (letters,
digits, `.`, `_`, `-`), so a listed name is also safe to show.

**Airtime is shown before anything is asked for** (AGENTS.md, "Airtime is
the scarce resource"): the bytes at the link's speed, plus a quarter for
YAPP's headers and AX.25's framing and acknowledgements. # UNVERIFIED:
the quarter is an estimate, not a measurement; it is labelled "about".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The speed assumed when the link's is not known: 1200-baud VHF packet.
DEFAULT_BAUD = 1200
#: YAPP's packet headers and AX.25's frames and acks, on top of the bytes.
OVERHEAD = 1.25

#: What `yapp.receive_file` saves (its `_SAFE_NAME`).
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_LINE_RE = re.compile(r"^(?P<name>\S+)\s+(?P<size>\d+)\s*$")


@dataclass(frozen=True)
class BbsFile:
    name: str
    size: int


def parse_files(lines: list[str]) -> list[BbsFile]:
    """The files a `FILES` reply lists that can be downloaded (module
    docstring): one `name size` line each, other lines ignored."""
    files = []
    for line in lines:
        match = _LINE_RE.match(line.strip())
        if (match and int(match["size"]) > 0 and ".." not in match["name"]
                and _SAFE_NAME.fullmatch(match["name"])):
            files.append(BbsFile(match["name"], int(match["size"])))
    return files


def airtime_seconds(size: int, baud: int = DEFAULT_BAUD) -> float:
    """About how long `size` bytes take on the air (module docstring)."""
    return size * 8 * OVERHEAD / max(baud, 1)


def describe_airtime(size: int, baud: int = DEFAULT_BAUD) -> str:
    """"about 25 s" or "about 3 min", for the checklist."""
    seconds = airtime_seconds(size, baud)
    if seconds < 90:
        return f"about {max(1, round(seconds))} s"
    return f"about {round(seconds / 60)} min"
