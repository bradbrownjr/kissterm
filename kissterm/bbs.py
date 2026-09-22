"""Small, explicit helpers for packet-BBS mail commands.

Packet BBSes agree on the *jobs* (list new mail, read a numbered message,
start mail to an addressee) much more often than their prompts and complete
command languages.  This module deliberately does not parse replies or try
to drive a BBS conversation.  It supplies visible command templates for the
operator to inspect and commit through the normal terminal send path.

The data is intentionally separate from the future general Python-plugin
system: these are fixed, documented command shapes, not hooks or automation.
Adding a new dialect is a data addition here, with its provenance recorded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


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


# BPQMail's documented interactive command shapes. Their names were confirmed
# in a 2026-09-10 WS1EC BPQ BBS help capture; meanings and syntax are cross-
# checked against the saved BPQ user-command reference. Do not generalize them
# to another BBS dialect without its own capture or documentation.
BPQMAIL = Profile(
    id="bpqmail",
    name="BPQMail / LinBPQ BBS",
    note="Commands are put in the compose box only; check the BBS prompt before sending.",
    macros=(
        Macro("list-new", "List new mail", "List new messages", "L"),
        Macro("list-new-oldest", "List new, oldest first", "List new messages, oldest first", "LR"),
        Macro("list-mine", "List my mail", "List Mine", "LM"),
        Macro("list-new-status", "List new-status mail", "List messages with N status", "LN"),
        Macro("list-held", "List held mail", "List Held messages", "LH"),
        Macro("list-killed", "List killed mail", "List Killed messages", "LK"),
        Macro("list-forwarded", "List forwarded mail", "List Forwarded messages", "LF"),
        Macro("list-delivered", "List delivered mail", "List Delivered messages", "LD"),
        Macro("list-bulletins", "List bulletins", "List Bulletins", "LB"),
        Macro("list-personal", "List personal mail", "List Personal messages", "LP"),
        Macro("list-traffic", "List NTS traffic", "List Traffic (NTS messages)", "LT"),
        Macro("list-categories", "List bulletin categories", "List active bulletin TO fields", "LC"),
        Macro("list-last", "List last messages", "List the last N messages", "LL {number}", ("number",)),
        Macro("bye", "Bye", "BYE — disconnect from BBS", "B", aliases=("BYE",)),
        Macro("read", "Read message", "Read one numbered message", "R {number}", ("number",)),
        Macro("send", "Send mail", "Start a personal message to a callsign", "SP {callsign}", ("callsign",)),
    ),
)


def profiles() -> tuple[Profile, ...]:
    """The shipped BBS dialects, in picker order."""
    return (BPQMAIL,)


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
