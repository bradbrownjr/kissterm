"""Stations you have connected to, remembered so you do not retype them.

Packet callsigns are exactly the kind of thing a person should not have to
hold in their head: `WS1EC-15` and `WS1EC-7` are different services on the
same machine, `W1AW-1 via W1XYZ` is a path you worked out once and will want
again, and getting one character wrong produces a connect that fails for a
reason indistinguishable from a bad RF path. Every terminal program the
operators of this mode already use -- BPQTerminal, EasyTerm, the old DOS
packages -- keeps a list like this, and doing without it was the single most
obvious gap in the connect dialog.

**Why this is not in `config.toml`.** It is history, not configuration. It
changes on its own every time you connect, and a file the program rewrites
underneath the operator is a bad place for settings they hand-edit -- one
careless write and their carefully commented TOML is reformatted. So this
lives in the data directory as JSON, and a corrupt or unreadable file costs
you your history and nothing else.

**Recorded on the attempt, not on success.** A connect that failed is
precisely the one you are about to try again -- which is what happened the
first time this was needed -- so waiting for a UA to record the target would
withhold the entry at the moment it is most wanted. The entry carries
`attempts` and `connects` separately, so "I have tried this ten times and
never got in" stays visible rather than being flattened into a bare list.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import state_path

log = logging.getLogger(__name__)

#: Entries kept. A station list is a convenience, not an archive: past a
#: screenful the older rows are noise, and an unbounded file that every
#: connect rewrites is a slow leak on a Raspberry Pi's SD card.
MAX_ENTRIES = 100


@dataclass(slots=True)
class Entry:
    """One remembered connect target.

    `target` is the raw text the operator typed, digipeater path and all
    (``"WS1EC-7 via W1AW-1"``), not a parsed structure -- what goes back into
    the dialog has to be exactly what worked, and re-rendering a parsed path
    is a chance to render it differently from how it was entered.
    """

    target: str
    last_used: float = field(default_factory=time.time)
    attempts: int = 0
    connects: int = 0
    note: str = ""
    #: An auto-login script for this station: lines sent, one at a time,
    #: right after the connection comes up (see `KissTermApp._run_connect_
    #: script`). Empty means "connect only, send nothing automatically",
    #: which is the default for every entry -- a script only exists here
    #: because an operator typed one into the Connect dialog for this exact
    #: station and it got saved alongside the target, the same way a typed
    #: digipeater path does. Ignored when `credential` names a saved one
    #: instead -- see that field.
    script: str = ""
    #: Comma-separated node callsigns to hop through BEFORE `target`, in
    #: order, for stations reached only node-to-node -- no digipeater path
    #: exists, so kissterm connects to the first node directly and then
    #: sends "C <next node>" over that link, waiting for its own CONNECTED
    #: reply, once per remaining hop, `target` included as the last one.
    #: Empty (the default, and what almost every entry has) means a normal
    #: direct connect to `target` -- nothing about existing entries changes.
    #: See `KissTermApp.action_connect`'s hop-chain handling.
    hops: str = ""
    #: The NAME of a saved credential (`Config.credentials`) to send instead
    #: of `script`, looked up fresh at connect time -- see that field's
    #: docstring for why this is a name, not a copy. Empty means "use
    #: `script` literally", which is what every entry has until an operator
    #: picks a saved credential from the Connect dialog's dropdown.
    credential: str = ""

    @property
    def summary(self) -> str:
        """The right-hand column of the dialog: what happened last time."""
        if self.connects:
            return f"connected {self.connects}x"
        if self.attempts:
            return f"{self.attempts} attempt(s), never connected"
        return ""


def path() -> Path:
    return state_path() / "addressbook.json"


class AddressBook:
    """A most-recently-used list of connect targets, persisted as JSON.

    Every method that touches the disk swallows its own errors and logs
    them. A station list is a convenience: failing to save one must never
    take down the connect that is happening at that moment, and failing to
    load one must never stop the app from starting.
    """

    def __init__(self, file: Path | None = None) -> None:
        self.file = file or path()
        self.entries: list[Entry] = []

    # -- persistence ------------------------------------------------------
    def load(self) -> None:
        """Read the file. A missing or corrupt one leaves an empty book."""
        try:
            raw = json.loads(self.file.read_text("utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            log.warning("address book at %s is unreadable: %s", self.file, exc)
            return
        if not isinstance(raw, list):
            log.warning("address book at %s is not a list; ignoring", self.file)
            return

        entries: list[Entry] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            target = str(item.get("target", "")).strip()
            if not target:
                continue
            entries.append(
                Entry(
                    target=target,
                    last_used=float(item.get("last_used", 0.0) or 0.0),
                    attempts=int(item.get("attempts", 0) or 0),
                    connects=int(item.get("connects", 0) or 0),
                    note=str(item.get("note", "")),
                    script=str(item.get("script", "")),
                    hops=str(item.get("hops", "")),
                    credential=str(item.get("credential", "")),
                )
            )
        self.entries = entries[:MAX_ENTRIES]

    def save(self) -> None:
        """Write the file, replacing it atomically.

        Via a temporary file and `os.replace` because this is rewritten on
        every connect: a program killed mid-write leaves the old list intact
        rather than a half-file that the next `load` discards entirely.
        """
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.file.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps([asdict(e) for e in self.entries], indent=2), "utf-8"
            )
            os.replace(temporary, self.file)
        except OSError as exc:
            log.warning("could not save address book to %s: %s", self.file, exc)

    # -- the list ---------------------------------------------------------
    def record_attempt(
        self, target: str, script: str = "", hops: str = "", credential: str = ""
    ) -> Entry:
        """Note that the operator asked to connect to `target`, and save.

        `script`, `hops` and `credential` are whatever the Connect dialog's
        matching fields held at submit time, including empty -- those fields
        are the one place each can be entered or cleared, so what they held
        is written back unconditionally rather than only when non-empty. A
        deliberate blank removes a script/hop-chain/credential the operator
        no longer wants, exactly the same way typing over the target field
        changes it.
        """
        entry = self._touch(target)
        entry.attempts += 1
        entry.script = script
        entry.hops = hops
        entry.credential = credential
        self.save()
        return entry

    def record_connect(self, target: str) -> Entry:
        """Note that a connect to `target` actually came up, and save."""
        entry = self._touch(target)
        entry.connects += 1
        self.save()
        return entry

    def forget(self, target: str) -> bool:
        """Drop `target`. Returns whether anything was removed."""
        before = len(self.entries)
        self.entries = [e for e in self.entries if e.target != target]
        if len(self.entries) != before:
            self.save()
            return True
        return False

    def _touch(self, target: str) -> Entry:
        """The entry for `target`, moved to the front, created if new.

        Matching is case-insensitive on the whole typed string: callsigns are
        conventionally upper case and `ws1ec-7` is the same station as
        `WS1EC-7`, so treating them as two entries would fill the list with
        duplicates of one node.
        """
        target = target.strip()
        key = target.upper()
        for entry in self.entries:
            if entry.target.upper() == key:
                self.entries.remove(entry)
                entry.last_used = time.time()
                # Keep the newer spelling: it is what the operator just typed
                # and is about to see in the list.
                entry.target = target
                self.entries.insert(0, entry)
                return entry
        entry = Entry(target=target)
        self.entries.insert(0, entry)
        del self.entries[MAX_ENTRIES:]
        return entry
