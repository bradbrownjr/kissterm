"""Small, explicit helpers for packet-BBS mail commands.

Packet BBSes agree on the *jobs* (list new mail, read a numbered message,
start mail to an addressee) much more often than their prompts and complete
command languages.  This module deliberately does not parse replies or try
to drive a BBS conversation.  It supplies visible command templates for the
operator to inspect and commit through the normal terminal send path.

The data is intentionally separate from the future general Python-plugin
system: these are fixed, documented command shapes, not hooks or automation.
The commands themselves live in the shipped reference files
(`kissterm/nodes/data/*.toml`, `helper_id` entries), so the helper, the send
line's suggestions and the Help tab describe a command in the same words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .nodes.reference import load_family


@dataclass(frozen=True, slots=True)
class Macro:
    """One command the BBS helper can put in the terminal compose box."""

    id: str
    label: str
    summary: str
    template: str
    fields: tuple[str, ...] = ()
    confidence: str = "documented"
    aliases: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        """The command word, separate from any helper-only parameters."""
        return self.template.split(maxsplit=1)[0]

    def matches(self, prefix: str) -> bool:
        """Whether the short command or a documented long spelling matches."""
        needle = prefix.upper()
        return any(name.upper().startswith(needle) for name in (self.name, *self.aliases))

    def render(self, **values: str) -> str:
        """Fill the template, rejecting control characters before they can
        turn a one-line helper into several commands.

        The returned text still has no transmission path.  It is only the
        value eventually offered to :meth:`TerminalPane.suggest`.
        """
        clean: dict[str, str] = {}
        for field in self.fields:
            value = values.get(field, "").strip()
            if not value:
                raise ValueError(f"{field.replace('_', ' ')} is required")
            if any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise ValueError(f"{field.replace('_', ' ')} cannot contain control characters")
            clean[field] = value
        if "number" in clean and not re.fullmatch(r"[0-9]+", clean["number"]):
            raise ValueError("message number must contain digits only")
        return self.template.format(**clean)


@dataclass(frozen=True, slots=True)
class Profile:
    """A named BBS command dialect, with only its safe common operations."""

    id: str
    name: str
    note: str
    macros: tuple[Macro, ...]


def _from_family(family_id: str, note: str) -> Profile | None:
    """A helper profile built from a shipped reference's helper entries.

    The helper used to carry its own copy of BPQMail's commands, and the
    two copies described the same commands in different words. Now the
    reference file (`kissterm/nodes/data/bpqmail.toml`) is the one place a
    BBS command is described; an entry with a `helper_id` is also offered
    here, with the same summary and the same provenance.
    """
    family = load_family(family_id)
    if family is None:
        return None
    macros = tuple(
        Macro(
            id=c.helper_id,
            label=c.helper_label or c.name,
            summary=c.summary,
            template=c.template or c.name,
            fields=c.fields,
            confidence=c.confidence,
            aliases=c.aliases,
        )
        for c in family.commands
        if c.helper_id
    )
    if not macros:
        return None
    return Profile(id=family.id, name=family.name, note=note, macros=macros)


@lru_cache(maxsize=None)
def profiles() -> tuple[Profile, ...]:
    """The shipped BBS dialects, in picker order."""
    bpqmail = _from_family(
        "bpqmail",
        "Commands are put in the compose box only; check the BBS prompt before sending.",
    )
    return (bpqmail,) if bpqmail is not None else ()


def profile(profile_id: str) -> Profile | None:
    """Find a profile without making an unsupported guess."""
    return next((item for item in profiles() if item.id == profile_id), None)


def complete(
    prefix: str, limit: int = 16, *, include_parameterized: bool = True
) -> tuple[Macro, ...]:
    """BBS commands beginning with ``prefix``.

    The complete published reference is available to callers by default,
    including commands with a message number or callsign argument. Filling
    one still only puts its short command into the compose box; it never
    transmits or invents its required argument.
    """
    needle = prefix.strip().upper()
    if not needle:
        return ()
    matches = [
        macro
        for item in profiles()
        for macro in item.macros
        if (include_parameterized or not macro.fields) and macro.matches(needle)
    ]
    return tuple(matches[:limit])
