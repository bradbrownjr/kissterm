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
    #: Where this command is meaningful.  Shipped references are node-level
    #: by default; a command learned while the operator is inside a BBS keeps
    #: that distinct context all the way to the command picker.
    context: str = "node"
    #: The shortest form the software accepts, where its documentation says
    #: ("PAC" for PACLEN). Empty when the source does not say.
    abbrev: str = ""
    #: Where this entry's description came from: the family's source URL
    #: unless the entry names its own. Shown so an operator can check it.
    source: str = ""
    #: Needs sysop status. Listed so an operator knows it exists, never
    #: offered as a completion to someone who is not the sysop.
    sysop: bool = False
    #: An application the sysop configured (BBS, CHAT): typed in full, and
    #: entering it hands the session to a different command language.
    application: bool = False
    #: The BBS helper (Ctrl+R) offers this command when it has a helper id.
    #: `template` fills `fields` ("R {number}"); empty means the bare name.
    helper_id: str = ""
    helper_label: str = ""
    template: str = ""
    fields: tuple[str, ...] = ()

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
    #: "node" (NET/ROM node, TNC command mode, JNOS) or "application" (a
    #: BBS or chat server reached FROM a node). An application's commands
    #: mean nothing at the node prompt and vice versa -- "L" lists mail in
    #: BPQMail and links on the node -- so which one is in effect decides
    #: what the send line may suggest.
    kind: str = "node"
    source: str = ""
    #: The context a harvested `?` reply is filed under while this family
    #: is in effect (kissterm.harvested's node / bbs / application).
    harvest_context: str = "node"
    #: Application only: the names a node's "Connected to <NAME>" uses for
    #: it (BPQ32 says "Connected to BBS").
    entered_by: tuple[str, ...] = ()
    #: Node only: a line saying the node handed the session to an
    #: application; group 1 is the application's name.
    enter_pattern: str = ""
    #: Node only: a line saying an application handed the session back.
    return_pattern: str = ""

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
    source = str(fam.get("source", ""))
    context = str(fam.get("harvest_context", "node"))
    commands = tuple(
        Command(
            name=str(c["name"]),
            summary=str(c.get("summary", "")),
            usage=str(c.get("usage", "")),
            detail=str(c.get("detail", "")),
            aliases=tuple(str(a) for a in c.get("aliases", ())),
            confidence=str(c.get("confidence", fam.get("confidence", "documented"))),
            context=context,
            abbrev=str(c.get("abbrev", "")),
            source=str(c.get("source", source)),
            sysop=bool(c.get("sysop", False)),
            application=bool(c.get("application", False)),
            helper_id=str(c.get("helper_id", "")),
            helper_label=str(c.get("helper_label", "")),
            template=str(c.get("template", "")),
            fields=tuple(str(f) for f in c.get("fields", ())),
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
        kind=str(fam.get("kind", "node")),
        source=source,
        harvest_context=context,
        entered_by=tuple(str(n).upper() for n in fam.get("entered_by", ())),
        enter_pattern=str(fam.get("enter_pattern", "")),
        return_pattern=str(fam.get("return_pattern", "")),
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
    """Guess the family from a banner or prompt. None when unsure.

    Applications are tried first: a BBS is reached through a node, so text
    from inside one often still carries the node's marks (a BPQMail greeting
    follows the node's "CCEMA:WS1EC-15} Connected to BBS"), while a node's
    own text never carries a BBS's SID.
    """
    families = load_all()
    for family in sorted(families, key=lambda f: f.kind != "application"):
        if family.identify(text):
            return family
    return None


def application_named(name: str) -> Family | None:
    """The application family a node's "Connected to NAME" refers to.

    None for an application kissterm ships no reference for (a sysop's own
    CALENDAR or GOPHER): its commands are unknown, and saying so beats
    offering the node's.
    """
    wanted = name.strip().upper()
    return next(
        (f for f in load_all() if f.kind == "application" and wanted in f.entered_by),
        None,
    )


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

        Sysop commands are left out: they are listed in the reference screen
        so an operator knows they exist, but offering PASSWORD or KH to
        someone typing at a public node is offering a command that will be
        refused, on the air.
        """
        if not prefix.strip():
            return ()
        needle = prefix.strip().upper()
        matches = [c for c in self.commands if not c.sysop and c.matches(needle)]
        # Shortest first, and within one length the reference file's own
        # order, which puts the everyday commands (L, LR, LM) ahead of the
        # rarer ones (L$) rather than sorting punctuation to the top.
        matches.sort(key=lambda c: (c.name.upper() != needle, len(c.name)))
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


# ---------------------------------------------------------------------------
# Harvesting -- turning a node's own '?' reply into candidate command names
# ---------------------------------------------------------------------------

#: Ordinary English words a node's banner, prompt or help prose is likely to
#: contain, filtered out so they never get treated as command names. Not
#: exhaustive by design -- see `parse_harvested`'s docstring for why this is
#: a best-effort guess, not a parser, and why that is an acceptable trade.
_HARVEST_STOPWORDS = frozenset(
    """
    THE AND FOR YOU ARE NOT ALL CAN HAS WAS WITH FROM THIS THAT YOUR WILL
    HAVE PLEASE ENTER TYPE USE TO OF IS IN ON AT BE OR IT AN AS BY IF NO DO
    SEE GET OUT TRY NODE PORT LINK USER LOGIN NAME CALL CALLSIGN WELCOME
    HELLO EACH CONTINUE THEN THAN WHEN WHAT WHERE WHICH THERE THEIR THEY
    THEM SOME MORE MOST LIST VALID COMMAND COMMANDS
    """.split()
)

_HARVEST_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]{1,9}")

#: Candidate names kept from one harvest, regardless of how much text came
#: back -- a node that replies with paragraphs of prose instead of a command
#: list must not turn into a reference with hundreds of bogus "commands".
HARVEST_MAX_NAMES = 60


def parse_harvested(text: str) -> tuple[str, ...]:
    """A best-effort guess at command names out of a node's raw `?` reply.

    Deliberately crude: node help text has no common format across BPQ32,
    TNC2, FBB and everything else this might ever talk to, so this looks for
    word-shaped tokens (2-10 letters/digits, starting with a letter) rather
    than parsing any specific layout -- the same reasoning
    `CommandReference.commands`'s docstring already gives for why a harvested
    entry is "usually just a name". Callers mark the result
    `confidence = "learned"`, the weakest tier in `CONFIDENCE_ORDER`,
    precisely because this is a guess, not a parse.

    **Deliberately excludes single-letter tokens**, even though `C`, `B`,
    `D` and the like are exactly the commands a real BPQ32/TNC2 node uses
    (see `data/bpq32.toml`). Allowing them would match ordinary prose
    constantly ("a", "I", "u" abbreviations) for no gain, because those
    single-letter commands are already the ones the shipped references
    already cover -- what harvesting actually needs to catch is a node's
    own longer, non-standard additions (the roadmap's own example: a stock
    BPQ32 with CALENDAR, FORMS, WALL, GOPHER, PREDICT bolted on via
    `APPLICATION` lines), which this catches fine.
    """
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in _HARVEST_TOKEN.findall(text):
        token = raw.upper()
        if token in _HARVEST_STOPWORDS or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
        if len(tokens) >= HARVEST_MAX_NAMES:
            break
    return tuple(tokens)
