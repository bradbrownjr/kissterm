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
        """The text Tab places in the compose box for parameter-free helpers."""
        return self.template

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


# BPQMail's commonly used interactive command shapes.  ``LM`` is intentionally
# included instead of guessing at a universal "new mail" syntax: it is the
# compact list-my-mail command the operator sees on a BPQ BBS, while other
# systems can be added as their documentation is verified. These remain
# ``recalled`` until checked against current upstream documentation or a real
# BBS capture; a wrong command shown confidently is worse than no helper.
BPQMAIL = Profile(
    id="bpqmail",
    name="BPQMail / LinBPQ BBS",
    note="Commands are put in the compose box only; check the BBS prompt before sending.",
    macros=(
        Macro("list-mine", "List my mail", "List Mine", "LM", confidence="recalled"),
        Macro("list-new", "List new mail", "List unread/new messages", "LN", confidence="recalled"),
        Macro("list-bulletins", "List bulletins", "List Bulletins", "LB", confidence="recalled"),
        Macro("bye", "Bye", "BYE — disconnect from BBS", "B", confidence="recalled", aliases=("BYE",)),
        Macro("read", "Read message", "Read one numbered message", "R {number}", ("number",), "recalled"),
        Macro("send", "Send mail", "Start a personal message to a callsign", "SP {callsign}", ("callsign",), "recalled"),
    ),
)


def profiles() -> tuple[Profile, ...]:
    """The shipped BBS dialects, in picker order."""
    return (BPQMAIL,)


def profile(profile_id: str) -> Profile | None:
    """Find a profile without making an unsupported guess."""
    return next((item for item in profiles() if item.id == profile_id), None)


def complete(prefix: str, limit: int = 8) -> tuple[Macro, ...]:
    """Parameter-free BBS commands beginning with ``prefix``.

    A Tab completion cannot safely invent a message number or recipient, so
    read/send remain in the parameterized helper picker. Listing commands are
    complete on their own and are useful alongside normal node suggestions.
    """
    needle = prefix.strip().upper()
    if not needle:
        return ()
    matches = [
        macro
        for item in profiles()
        for macro in item.macros
        if not macro.fields and macro.matches(needle)
    ]
    return tuple(matches[:limit])
