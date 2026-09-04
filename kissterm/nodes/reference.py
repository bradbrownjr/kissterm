"""Loading and searching the shipped command references.

Pure data handling: no I/O to a radio, no UI. `CommandReference` is what the
help pane and the autocomplete source both read, so there is one notion of
"what commands exist here" rather than two that can disagree.
"""

from __future__ import annotations

import logging
import re
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"

#: Confidence levels, weakest last. Shown in the UI so an operator knows
#: whether to trust a syntax line before spending airtime on it.
CONFIDENCE_ORDER = ("verified", "documented", "recalled", "learned")


@dataclass(frozen=True, slots=True)
class Command:
    name: str
    summary: str = ""
    usage: str = ""
    detail: str = ""
    aliases: tuple[str, ...] = ()
    confidence: str = "documented"

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)

    def matches(self, prefix: str) -> bool:
        """Case-insensitive prefix match on the command or any alias."""
        p = prefix.upper()
        return any(n.upper().startswith(p) for n in self.names)


@dataclass(slots=True)
class Family:
    id: str
    name: str
    confidence: str = "documented"
    note: str = ""
    detect_prompt: tuple[str, ...] = ()
    detect_banner: tuple[str, ...] = ()
    commands: tuple[Command, ...] = ()

    def identify(self, text: str) -> bool:
        """Does this text look like it came from this family?

        Deliberately conservative. A wrong family shown confidently is worse
        than "unknown node", because the operator will type its commands.
        """
        for pattern in self.detect_prompt:
            try:
                if re.search(pattern, text, re.MULTILINE):
                    return True
            except re.error:
                log.warning("bad detect_prompt regex in family %s", self.id)
        upper = text.upper()
        return any(marker.upper() in upper for marker in self.detect_banner)


def _parse(path: Path) -> Family:
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    fam = raw.get("family", {})
    commands = tuple(
        Command(
            name=str(c["name"]),
            summary=str(c.get("summary", "")),
            usage=str(c.get("usage", "")),
            detail=str(c.get("detail", "")),
            aliases=tuple(str(a) for a in c.get("aliases", ())),
            confidence=str(c.get("confidence", fam.get("confidence", "documented"))),
        )
        for c in raw.get("commands", ())
        if c.get("name")
    )
    return Family(
        id=str(fam.get("id", path.stem)),
        name=str(fam.get("name", path.stem)),
        confidence=str(fam.get("confidence", "documented")),
        note=str(fam.get("note", "")).strip(),
        detect_prompt=tuple(fam.get("detect_prompt", ())),
        detect_banner=tuple(fam.get("detect_banner", ())),
        commands=commands,
    )


@lru_cache(maxsize=None)
def load_all() -> tuple[Family, ...]:
    """Every shipped reference. Cached; a bad file is skipped, never fatal."""
    families = []
    if not DATA_DIR.is_dir():
        return ()
    for path in sorted(DATA_DIR.glob("*.toml")):
        try:
            families.append(_parse(path))
        except Exception:
            # A malformed reference must not stop the app from working as a
            # terminal. Losing help is an inconvenience; not connecting is not.
            log.exception("could not load command reference %s", path)
    return tuple(families)


def available_families() -> tuple[str, ...]:
    return tuple(f.id for f in load_all())


def load_family(family_id: str) -> Family | None:
    return next((f for f in load_all() if f.id == family_id), None)


def identify_family(text: str) -> Family | None:
    """Guess the family from a banner or prompt. None when unsure."""
    for family in load_all():
        if family.identify(text):
            return family
    return None


@dataclass(slots=True)
class CommandReference:
    """The command set in effect for one session: shipped plus learned.

    Learned commands are kept separate from shipped ones so the UI can show
    where each came from, and so re-learning replaces only the learned half.
    """

    family: Family | None = None
    learned: tuple[Command, ...] = ()

    @property
    def commands(self) -> tuple[Command, ...]:
        """Shipped commands, plus learned ones not already covered.

        Shipped entries win on a name collision: they carry usage and detail
        text, while a harvested line is usually just a name.
        """
        shipped = self.family.commands if self.family else ()
        known = {n.upper() for c in shipped for n in c.names}
        extra = tuple(c for c in self.learned if c.name.upper() not in known)
        return shipped + extra

    def complete(self, prefix: str, limit: int = 8) -> tuple[Command, ...]:
        """Candidates for a partly-typed command.

        An empty prefix returns nothing rather than everything: suggesting the
        whole command set the moment the operator focuses an empty input is
        noise, not help.
        """
        if not prefix.strip():
            return ()
        matches = [c for c in self.commands if c.matches(prefix.strip())]
        matches.sort(key=lambda c: (len(c.name), c.name))
        return tuple(matches[:limit])

    def find(self, text: str) -> tuple[Command, ...]:
        """Free-text search across names, summaries and detail."""
        needle = text.strip().lower()
        if not needle:
            return self.commands
        return tuple(
            c
            for c in self.commands
            if needle in c.name.lower()
            or any(needle in a.lower() for a in c.aliases)
            or needle in c.summary.lower()
            or needle in c.detail.lower()
        )


# ---------------------------------------------------------------------------
# Airtime
# ---------------------------------------------------------------------------
def airtime_seconds(
    byte_count: int,
    baud: int = 1200,
    paclen: int = 256,
    txdelay_ms: int = 300,
    turnaround_ms: int = 200,
) -> float:
    """Roughly how long `byte_count` takes on a half-duplex channel.

    Deliberately includes per-frame overhead, keyup and turnaround rather than
    just dividing by the baud rate: those dominate at small frame sizes and are
    exactly what makes "just download the help text" expensive. Used to warn
    the operator *before* they spend the channel, which is the only time the
    number is useful.

    An estimate, not a measurement -- real timing depends on the TNC's
    parameters and on how busy the channel is.
    """
    if byte_count <= 0:
        return 0.0
    frames = max(1, -(-byte_count // max(1, paclen)))
    overhead_bytes = frames * 20  # address, control, PID, FCS, flags
    data_seconds = (byte_count + overhead_bytes) * 8 / max(1, baud)
    switching = frames * (txdelay_ms + turnaround_ms) / 1000
    return data_seconds + switching


def describe_airtime(byte_count: int, baud: int = 1200) -> str:
    """A short human phrase for a transfer cost, for a confirm prompt."""
    seconds = airtime_seconds(byte_count, baud=baud)
    if seconds < 1:
        return "under a second"
    if seconds < 90:
        return f"about {seconds:.0f} seconds"
    return f"about {seconds / 60:.1f} minutes"
