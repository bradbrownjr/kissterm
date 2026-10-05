"""The decisions the core asks the operator for (`operator.Question`).

Each is plain data a client can draw natively: the terminal UI maps it to a
modal screen (`ui/operator.SCREENS`); a phone would show a sheet. The
answer type is in each docstring; None always means cancelled.
"""

from __future__ import annotations

from dataclasses import dataclass

from .operator import Question


@dataclass(frozen=True, slots=True)
class RadioReminder(Question):
    """Before connecting to a contact with a frequency, connection type or
    note on file: show it, before anything is armed or transmitted, and
    go on only if the operator says so. Answer: bool (True = connect)."""

    frequency: str = ""
    connection_type: str = ""
    note: str = ""


@dataclass(frozen=True, slots=True)
class TrustHostKey(Question):
    """First contact with an SSH server: trust the key it offered?
    (`transport/ssh.py`.) Answer: bool (True = trust and save it)."""

    host: str
    port: int
    key_type: str
    fingerprint: str
    #: The known_hosts file trusting it writes to.
    path: str
