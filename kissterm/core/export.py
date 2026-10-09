"""Save as text: one mail message, one bulletin, one APRS conversation or
one Terminal session (Broadcast included) as a plain-text file (operator,
2026-10-09: "export or download individual mail, bulletins, aprs
messages, and terminal output as txt files", for an ARES report).

**One rendering for every front end.** `Exporter` (`core.export`) makes
the file's name and text; the terminal UI writes it on the station's
machine (`save`), the phone and browser ask for it over the WebSocket
(`export_text`) and hand it to the browser as a download. So a message
saved from either is the same file.

**Every file is sanitized on the way out** (`monitor.sanitize`, in
`Export`): a message body is stored as it came off the air, escape
sequences and all, so no escape sequence reaches a file someone may
`cat`, whatever the source.

**A session is what its tab shows**: what the far end sent and the lines
sent to it, never kissterm's records (DESIGN.md section 6; those are in
the transcript). It is kept in memory whether or not transcripts are on.

**File names are built, never taken from the wire**: callsigns and
subjects are reduced to `[A-Za-z0-9-]` (`_token`), as `session_log`
does for transcript names. Saving never transmits.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..monitor import sanitize

_UNSAFE_RE = re.compile(r"[^A-Za-z0-9]+")


@dataclass(frozen=True, slots=True)
class Export:
    """A file to save: its suggested name and its text, sanitized here."""

    name: str
    text: str

    def __post_init__(self) -> None:
        clean = sanitize(self.text.encode("utf-8", errors="replace"))
        object.__setattr__(self, "text", clean)


def _token(value: str, limit: int = 24) -> str:
    """`value` reduced to a short, filesystem-safe word or words."""
    return _UNSAFE_RE.sub("-", value).strip("-").lower()[:limit].strip("-")


def _name(*parts: str) -> str:
    return "-".join(p for p in parts if p) + ".txt"


def _stamp(at: float) -> str:
    return datetime.fromtimestamp(at).strftime("%Y-%m-%d %H:%M")


def _utc(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%MZ")


def _lines(text: str) -> str:
    """Newlines as LF and a final one, so the file ends cleanly."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text if text.endswith("\n") or not text else text + "\n"


def default_folder() -> Path:
    """Where the terminal UI offers to save: ~/Downloads, or home."""
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.home()


def save(export: Export, destination: Path) -> Path:
    """Write `export` to `destination` (a folder gets `export.name`),
    making its folder. Raises `OSError`: a one-shot action the front end
    turns into a notice, as `transcripts.export_transcript` does."""
    destination = Path(destination).expanduser()
    if destination.is_dir():
        destination = destination / export.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(export.text, encoding="utf-8")
    return destination


class Exporter:
    """`core.export`: each kind of thing as an `Export`."""

    def __init__(self, core) -> None:
        self.core = core

    def mail(self, ref: str) -> Export:
        """A mail message or bulletin: its headers, its `R:` routing lines
        when it came from a BBS, then its body. Raises `FileNotFoundError`
        for a message that is not in the store."""
        from ..mail.message import KIND_BULLETIN

        mail = self.core.mail
        message = mail.store.read(str(ref))
        bulletin = message.kind == KIND_BULLETIN
        heads = [("From", message.sender),
                 ("To", message.category if bulletin and message.category else message.to),
                 ("Date", _utc(message.date)),
                 ("Subject", message.subject),
                 ("Source", message.source),
                 ("Message-Id", message.message_id)]
        lines = [f"{name}: {value}" for name, value in heads if value]
        routing = mail.routing(str(ref))
        if routing:
            lines += ["", *routing]
        stamp = message.date.strftime("%Y-%m-%d") if message.date else ""
        name = _name("bulletin" if bulletin else "mail", _token(message.sender, 12), stamp,
                     _token(message.subject)) if message.sender or message.subject else ""
        return Export(name or _name("bulletin" if bulletin else "mail", _today()),
                      "\n".join(lines) + "\n\n" + _lines(message.body))

    def aprs(self, callsign: str) -> Export:
        """One APRS conversation, oldest first: time, who, text, and
        whether an outgoing message was acked. Raises `KeyError` for a
        callsign with no conversation."""
        call = str(callsign).strip().upper()
        convo = self.core.aprs.conversations.conversations.get(call)
        if convo is None:
            raise KeyError(call)
        config = self.core.config
        mycall = str(config.mycall or "")
        me = str(config.aprs.source_for(mycall)) if mycall else "me"
        lines = [f"APRS messages with {call}", ""]
        for m in convo.messages:
            who = me if m.direction == "out" else call
            mark = ""
            if m.direction == "out" and m.number is not None:
                mark = "  [acked]" if m.acked else "  [not acked]"
            lines.append(f"{_stamp(m.timestamp)}  {who}: {m.text}{mark}")
        return Export(_name("aprs", _token(call, 12), _today()), "\n".join(lines) + "\n")

    def session(self, key: str) -> Export:
        """A Terminal tab: session `key`'s text, or with `key` "" the
        Broadcast tab's lines. Raises `KeyError` for a session that is not
        open."""
        if not key:
            heard = self.core.broadcast.recent()
            lines = [f"{_stamp(h['at'])}  {h['source']} > {h['to']}: {h['text']}"
                     for h in heard]
            return Export(_name("broadcast", _today()),
                          "\n".join(lines) + "\n" if lines else "")
        session = self.core.sessions.get(str(key)) if self.core.sessions else None
        if session is None:
            raise KeyError(key)
        return Export(_name("session", _token(str(key), 12),
                            datetime.now().strftime("%Y-%m-%d-%H%M")),
                      _lines(session.screen))


def _today() -> str:
    return time.strftime("%Y-%m-%d")
