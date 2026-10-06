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


# ----------------------------------------------------------------------
# Send/Receive's setup questions (`mail.py`), asked before anything is
# dialed so a missing setting never costs a connect's airtime.
# ----------------------------------------------------------------------
#: A setup question's two answers besides a value and None (cancel
#: everything): leave this service out of an All Inboxes run, or take the
#: operator to the place the question is about (operator, 2026-09-27: "if
#: it wants the user to go someplace, include a button to go directly
#: there"). On SETUP_GO the core cancels the run and publishes
#: `events.SetupRequested`; the client goes there.
SETUP_SKIP = "\x00skip"
SETUP_GO = "\x00go"


@dataclass(frozen=True)
class Credential:
    """One saved login or script, as a client hands it back. For a login
    `text` is the password, "" to keep the saved one when editing; for a
    script it is the script."""

    name: str
    text: str
    username: str = ""


@dataclass
class GatewayChoice:
    """`WinlinkGateway`'s answer: where to connect this time."""

    target: str
    #: Make it the favourite gateway (Settings > Mail > Gateway contact).
    remember: bool
    #: When it came from the RMS gateway list: its frequency and modes,
    #: for the Address Book contact it becomes.
    channel: object | None = None


@dataclass
class InternetLogin:
    """`InternetLoginAsk`'s answer: the contact and the login for it."""

    target: str
    username: str
    #: "" keeps the password already saved.
    password: str


@dataclass(frozen=True)
class HomeBbsRoute(Question):
    """Which Address Book contact is the Home BBS (G), when none is set or
    the one set is gone. Answer: the contact's target, SETUP_GO or
    SETUP_SKIP. `all_note`/`skip`: on All Inboxes, why this is asked and
    the Skip button's label (both "" otherwise)."""

    targets: tuple[str, ...]
    missing: str = ""
    all_note: str = ""
    skip: str = ""


@dataclass(frozen=True)
class WinlinkGateway(Question):
    """Which Winlink gateway to connect to, with no favourite or the
    favourite gone from the Address Book. Answer: `GatewayChoice` or
    SETUP_SKIP."""

    contacts: tuple[str, ...]
    favourite: str = ""
    #: Whether the RMS gateway list can be offered.
    gateway_list: bool = False
    all_note: str = ""
    skip: str = ""


@dataclass(frozen=True)
class LoginAsk(Question):
    """A login Send/Receive needs and does not have, saved under `name`.
    Answer: the password (str), or with `username` (a BBS login: its
    starting text) a `Credential`; SETUP_SKIP on All Inboxes. `where`:
    "keyring" or "config", where the password will be kept, if said."""

    title: str
    detail: str
    name: str
    secret: bool = True
    all_note: str = ""
    skip: str = ""
    go_label: str = "Send/Receive"
    username: str | None = None
    where: str = ""


@dataclass(frozen=True)
class InternetLoginAsk(Question):
    """I's setup question: the Home BBS's Telnet/SSH contact and its login,
    saved together. Answer: `InternetLogin` or SETUP_SKIP."""

    targets: tuple[str, ...]
    current: str = ""
    missing: str = ""
    username: str = ""
    #: A password is saved already: an empty answer keeps it.
    saved: bool = False
    where: str = "keyring"
    all_note: str = ""
    skip: str = ""


@dataclass(frozen=True)
class ChooseCategories(Question):
    """Mid-run: which bulletin categories to collect from `bbs`, of those
    offered with their message counts (`new_only`: only categories not
    seen before are offered). Answer: (chosen categories, all)."""

    bbs: str
    counts: dict
    new_only: bool = False


@dataclass(frozen=True)
class HowManyBulletins(Question):
    """Mid-run, more than `newest` new bulletins listed (`count`, in
    `categories`; `radio`: over the air): read them all, only the newest
    `newest`, or none. Answer: the number to read (`count`, `newest`);
    None or 0 reads none."""

    bbs: str
    count: int
    categories: tuple
    newest: int
    radio: bool = False


@dataclass(frozen=True)
class PickFiles(Question):
    """Mid-run: which of the BBS's listed files to download (`files`:
    `mail.collect` file entries; `have`: name -> size already in
    Downloads). Answer: a list of file names."""

    bbs: str
    files: tuple
    have: dict


@dataclass(frozen=True)
class CallsignAsk(Question):
    """The station callsign, needed and not set (Winlink's account
    defaults to it). Answer: the new callsign."""

    current: str = ""


@dataclass(frozen=True)
class ChooseSessionTransport(Question):
    """More than one session-tier transport is configured: which to
    connect over. Answer: its name."""

    transports: tuple
    active: str = ""
