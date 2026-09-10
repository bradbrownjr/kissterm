"""Command names harvested from a node's own `?`, cached forever per callsign.

`kissterm/nodes/__init__.py`'s module docstring already lays out why: asking
a node for its own help text costs real airtime (a couple of kilobytes is
~19 seconds at 1200 baud, over a minute for 8 KB), so it happens only when
the operator opts in, once, and the result must never be asked for again for
that same node. This module is the "never again" half of that promise --
the parsing itself is `nodes.reference.parse_harvested`, and the confirm
step and the actual send/capture live in `KissTermApp.harvest_commands`
(`kissterm/ui/app.py`).

Same persistence shape as `kissterm/addressbook.py` on purpose: JSON in the
data directory, atomic write via a temp file plus `os.replace`, every method
swallows and logs its own I/O errors. Losing this cache costs an operator
one repeated (opted-in, confirmed) harvest for a node they will probably
reconnect to -- an inconvenience, never a reason to take a live session down.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .config import state_path

log = logging.getLogger(__name__)


def path() -> Path:
    return state_path() / "harvested_commands.json"


class HarvestedCommands:
    """Command names learned per node callsign, keyed case-insensitively --
    same reasoning as `AddressBook`: `WS1EC-15` and `ws1ec-15` are the same
    station's cache entry, not two.
    """

    def __init__(self, file: Path | None = None) -> None:
        self.file = file or path()
        self._by_callsign: dict[str, tuple[str, ...]] = {}

    def load(self) -> None:
        """Read the file. A missing or corrupt one leaves the cache empty --
        every node is simply un-harvested yet, same as a fresh install."""
        try:
            raw = json.loads(self.file.read_text("utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            log.warning("harvested-command cache at %s is unreadable: %s", self.file, exc)
            return
        if not isinstance(raw, dict):
            log.warning("harvested-command cache at %s is not an object; ignoring", self.file)
            return
        result: dict[str, tuple[str, ...]] = {}
        for callsign, names in raw.items():
            if not isinstance(names, list):
                continue
            cleaned = tuple(str(n).strip().upper() for n in names if str(n).strip())
            if cleaned:
                result[str(callsign).strip().upper()] = cleaned
        self._by_callsign = result

    def save(self) -> None:
        """Write the file, replacing it atomically -- a program killed
        mid-write leaves the previous cache intact rather than a half-file."""
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.file.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(self._by_callsign, indent=2), "utf-8")
            os.replace(temporary, self.file)
        except OSError as exc:
            log.warning("could not save harvested-command cache to %s: %s", self.file, exc)

    def for_callsign(self, callsign: str) -> tuple[str, ...]:
        """Whatever is already cached for `callsign`, or empty -- read-only,
        used to silently pre-populate a session's reference on connect
        without spending any airtime or asking again."""
        return self._by_callsign.get(callsign.strip().upper(), ())

    def add(self, callsign: str, names: tuple[str, ...]) -> tuple[str, ...]:
        """Merge `names` into whatever is already cached for `callsign`,
        save, and return the full merged set -- the caller applies this
        directly to `CommandReference.learned` rather than just the new
        names, so a second harvest of the same node adds to the first
        instead of replacing it."""
        key = callsign.strip().upper()
        existing = list(self._by_callsign.get(key, ()))
        seen = set(existing)
        for name in names:
            cleaned = name.strip().upper()
            if cleaned and cleaned not in seen:
                existing.append(cleaned)
                seen.add(cleaned)
        merged = tuple(existing)
        self._by_callsign[key] = merged
        self.save()
        return merged
