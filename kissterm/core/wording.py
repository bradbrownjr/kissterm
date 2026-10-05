"""Client-neutral words for the controls and places the core's notices
name (ROADMAP P7a M7).

A notice that says "press Ctrl+T" is wrong on a phone, and one that says
"the Transmit switch" reads oddly in the terminal, where the key is the
thing to know. So the core writes a token where a key or a view goes, and
each client renders it:

* ``{key:ACTION}`` -- a command, by its action name (`ui/commands.py`
  for the terminal). The terminal shows its key ("Ctrl+T"), or for a
  menu-only command its menu path ("F10 > Session > RMS gateways"); a
  client without either shows `KEYS[ACTION]` ("the Transmit switch").
* ``{view:NAME}`` -- a place. ``monitor``, ``downloads``, and
  ``settings/<Section>``. The terminal shows where it is and its key
  ("Monitor tab (F8)", "Settings (F9) > Radio"); otherwise `neutral`.

`neutral` is what any client without its own renderer -- the WebSocket
server, the log, a transcript -- uses. Write the text so it reads with
either rendering: "Press {key:toggle_transmit} to turn Transmit on."
"""

from __future__ import annotations

import re
from collections.abc import Callable

#: A key or view token in a notice's text.
TOKEN = re.compile(r"\{(key|view):([A-Za-z_/]+)\}")

#: What comes before a token that opens a sentence.
SENTENCE_START = re.compile(r"(?:^|[.!?]\s+)$")

#: A command, named for a client that has no key for it.
KEYS: dict[str, str] = {
    "toggle_transmit": "the Transmit switch",
    "get_mail": "Send/Receive",
    "set_callsign": "My callsign",
    "check_updates": "Check for updates",
    "rms_gateways": "RMS gateways",
    "toggle_aprs_ssid_filter": "the SSID filter switch",
    "toggle_contacts": "the Address Book",
    "remote_pairing": "Remote pairing",
}

#: A place, named for a client that does not show where it is.
VIEWS: dict[str, str] = {
    "monitor": "Monitor",
    "downloads": "Files > Downloads",
}

#: The one sentence for "the gate is closed" (was `tx.DISABLED_MESSAGE`).
TRANSMIT_DISABLED = "Transmit is disabled -- press {key:toggle_transmit} to enable it."


def neutral_view(name: str) -> str:
    if name.startswith("settings/"):
        return "Settings > " + name.split("/", 1)[1]
    return VIEWS.get(name, name)


def render(text: str, *, key: Callable[[str], str | None] | None = None,
           view: Callable[[str], str | None] | None = None) -> str:
    """`text` with every token replaced: by `key(action)` / `view(name)`
    when the client gives one and it returns a name, else neutrally."""

    def one(match: re.Match) -> str:
        kind, name = match.group(1), match.group(2)
        if kind == "key":
            word = (key(name) if key else None) or KEYS.get(name, name)
        else:
            word = (view(name) if view else None) or neutral_view(name)
        # "the Transmit switch" opening a sentence: "The Transmit switch".
        if SENTENCE_START.search(text[:match.start()]):
            word = word[:1].upper() + word[1:]
        return word

    return TOKEN.sub(one, text)


def neutral(text: str) -> str:
    """`text` for a client with no keys and no tabs of its own."""
    return render(text)
