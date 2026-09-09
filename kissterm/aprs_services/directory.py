"""Loading and searching the shipped APRS gateway service directory.

Pure data handling: no radio I/O, no UI. What `kissterm/nodes/reference.py`
is to a packet node's command mode, this is to an APRS messaging gateway --
and it exists for the same reason AGENTS.md gives there. An operator who
wants Winlink mail has to know that `WLNK-1` understands `SP`, `L` and
`/EX`; one who wants an SMS has to know `SMSGTE` wants `@5551234567 text`.
None of that is discoverable from inside a terminal, and none of it should
cost airtime to find out: at 1200 baud half-duplex, asking a gateway for its
own help text is seconds of channel nobody else can use, repeated by every
operator who ever wonders. So the answers ship.

**Why this is not `kissterm/nodes/reference.py` with a different data
directory.** A `nodes.Family` carries `detect_prompt`/`detect_banner` and is
matched against a banner arriving over a connected session; a `Service` here
is matched against an APRS *addressee* and has no connection, no prompt and
no banner to sniff. The two also fail differently: a wrong node family shows
commands the operator types into a live session, a wrong service shows
commands sent as one-shot unproto messages to a callsign that may not answer
at all. They are close enough to look mergeable and different enough that
merging them would put two meanings in every field -- the same call
`kissterm/aprs_contacts.py` already made against `kissterm/addressbook.py`.
The ~40 lines of `tomllib` loader they have in common is the cheaper
duplication.

**Provenance is mandatory, not decoration.** Every service file carries a
`source` URL and every command a `confidence` from the same vocabulary
`nodes/reference.py` uses. AGENTS.md: "A reference that silently mixes
documented fact with half-remembered syntax is worse than none." That bites
harder here than it does for node commands, because several of these
services act on the message -- `APSPOT` posts a public spot, `SMSGTE` texts
a real phone -- so a guessed argument order is not a wasted keystroke, it is
a wrong thing done in the operator's name.

**This directory is a snapshot, not a liveness probe.** APRS gateways come
and go; several entries here were reported down by a third-party health
check while they were being written, and were shipped anyway because "down
this afternoon" and "gone" are different facts and this file cannot tell
them apart. Each service carries a `checked` date so the UI can say how old
the claim is instead of implying it is current.

Nothing here ever transmits, and nothing that reads it may transmit on its
own either: a chosen command fills the compose input and the operator still
commits it deliberately. See AGENTS.md's completion rule, and
`kissterm/ui/dialogs.py`'s `CommandReferenceScreen` for the same contract on
the terminal side.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

__all__ = [
    "CONFIDENCE_ORDER",
    "DATA_DIR",
    "Service",
    "ServiceCommand",
    "find",
    "load_all",
    "lookup",
    "lookup_callsign",
]

DATA_DIR = Path(__file__).parent / "data"

#: Confidence levels, weakest last -- the same vocabulary and the same
#: meanings as `kissterm.nodes.reference.CONFIDENCE_ORDER`, deliberately, so
#: an operator learns one scale rather than two. Shown in the picker next to
#: every command.
CONFIDENCE_ORDER = ("verified", "documented", "recalled", "learned")


@dataclass(frozen=True, slots=True)
class ServiceCommand:
    """One thing you can say to a gateway.

    `template` is what actually lands in the compose box, placeholders and
    all (`SP <recipient> <subject>`), because a half-filled line the operator
    completes is more useful than a name they then have to look up the
    arguments for. It is never sent from here -- see the module docstring.
    """

    name: str
    summary: str = ""
    template: str = ""
    detail: str = ""
    confidence: str = "documented"

    @property
    def insert_text(self) -> str:
        """What to put in the compose input. Falls back to the command name
        for a service whose command IS the whole message (`WHO-IS` takes a
        bare callsign and nothing else)."""
        return self.template or self.name

    def matches(self, needle: str) -> bool:
        """Case-insensitive substring match across everything a human might
        search by. Deliberately looser than `nodes.Command.matches`' prefix
        rule: an operator looking for "weather" does not know the command is
        spelled `wx`, whereas someone at a `cmd:` prompt is usually completing
        something they already started typing."""
        needle = needle.strip().lower()
        if not needle:
            return True
        return any(
            needle in haystack.lower()
            for haystack in (self.name, self.summary, self.template, self.detail)
        )


@dataclass(frozen=True, slots=True)
class Service:
    """One APRS gateway: who to address, what it does, what to say to it.

    `summary` and `note` are both required by `_parse` rather than optional
    with an empty default, because a bare callsign like `MPAD` or `WLNK-1` in
    a contact list tells an operator nothing at all -- the description IS the
    feature here, not a nicety around it. `tests/unit/test_aprs_services.py`
    fails the build for an entry missing either.
    """

    id: str
    callsign: str
    name: str
    summary: str
    note: str
    source: str
    checked: str = ""
    aliases: tuple[str, ...] = ()
    region: str = ""
    confidence: str = "documented"
    commands: tuple[ServiceCommand, ...] = ()

    @property
    def callsigns(self) -> tuple[str, ...]:
        """Every addressee this service answers on. `WHO-IS` also answers as
        `WHO-15` for clients that cannot type a non-AX.25 SSID, and a contact
        saved against either one has to resolve to this same entry."""
        return (self.callsign, *self.aliases)

    def answers_to(self, callsign: str) -> bool:
        wanted = callsign.strip().upper()
        return any(wanted == c.upper() for c in self.callsigns)

    def find(self, needle: str) -> tuple[ServiceCommand, ...]:
        """This service's commands matching `needle`; all of them for an
        empty search."""
        return tuple(c for c in self.commands if c.matches(needle))


def _parse(path: Path) -> Service:
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    svc = raw.get("service", {})

    # Required-and-non-empty, not merely present. A file with `summary = ""`
    # would load fine and then render a blank cell next to a callsign nobody
    # recognises, which is the exact failure the field exists to prevent.
    for key in ("id", "callsign", "name", "summary", "note", "source"):
        if not str(svc.get(key, "")).strip():
            raise ValueError(f"{path.name}: [service] is missing a non-empty {key!r}")

    default_confidence = str(svc.get("confidence", "documented"))
    commands = tuple(
        ServiceCommand(
            name=str(c["name"]),
            summary=str(c.get("summary", "")),
            template=str(c.get("template", "")),
            detail=str(c.get("detail", "")),
            confidence=str(c.get("confidence", default_confidence)),
        )
        for c in raw.get("commands", ())
        if str(c.get("name", "")).strip()
    )
    return Service(
        id=str(svc["id"]).strip(),
        callsign=str(svc["callsign"]).strip().upper(),
        name=str(svc["name"]).strip(),
        summary=str(svc["summary"]).strip(),
        note=str(svc["note"]).strip(),
        source=str(svc["source"]).strip(),
        checked=str(svc.get("checked", "")).strip(),
        aliases=tuple(str(a).strip().upper() for a in svc.get("aliases", ()) if str(a).strip()),
        region=str(svc.get("region", "")).strip(),
        confidence=default_confidence,
        commands=commands,
    )


@lru_cache(maxsize=None)
def load_all() -> tuple[Service, ...]:
    """Every shipped service, sorted by name. Cached.

    A malformed or unreadable file is logged and skipped, never fatal --
    same rule as `nodes.reference.load_all` and for the same reason: losing
    a reference is an inconvenience, failing to start is not. That also
    covers the installed-wheel case where `DATA_DIR` is missing entirely
    because someone forgot the `package-data` entry; the picker is then
    empty rather than the app being dead.
    """
    if not DATA_DIR.is_dir():
        log.warning("APRS service directory %s is missing", DATA_DIR)
        return ()
    services: list[Service] = []
    for path in sorted(DATA_DIR.glob("*.toml")):
        try:
            services.append(_parse(path))
        except Exception:
            log.exception("could not load APRS service %s", path)
    services.sort(key=lambda s: s.name.lower())
    return tuple(services)


def lookup(service_id: str) -> Service | None:
    """The service with this id, or None. `Contact.gateway` holds these."""
    service_id = service_id.strip()
    return next((s for s in load_all() if s.id == service_id), None)


def lookup_callsign(callsign: str) -> Service | None:
    """The service that answers on this addressee, or None for an ordinary
    station. Aliases count -- see `Service.callsigns`."""
    if not callsign.strip():
        return None
    return next((s for s in load_all() if s.answers_to(callsign)), None)


def find(needle: str) -> tuple[Service, ...]:
    """Services matching a free-text search across name, callsign, summary
    and note. Empty search returns everything."""
    needle = needle.strip().lower()
    if not needle:
        return load_all()
    return tuple(
        s
        for s in load_all()
        if needle in s.name.lower()
        or any(needle in c.lower() for c in s.callsigns)
        or needle in s.summary.lower()
        or needle in s.note.lower()
        or bool(s.find(needle))
    )
