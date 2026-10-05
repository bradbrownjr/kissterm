"""The core's events, notices and questions as JSON, and answers back
(docs/PROTOCOL.md sections 3, 4 and 6).

**Remote bytes are filtered here, on the station** (AGENTS.md "Untrusted
input"): `SessionData` goes out as text through the terminal's own filter
(`ansi.to_text`: the SGR allowlist, `decode_text`, C1 and bidi controls
stripped) with colour as spans, never escape codes, so a browser never
parses control bytes from the air. `raw` (base64) is there for a client
that does its own filtering, and is never to be rendered as-is. Any other
text that came off the air (a monitor line, mail) goes through
`monitor.sanitize`.

**Notices are neutral** (`core/wording.py`): no key or tab names.
"""

from __future__ import annotations

import base64
import dataclasses
from datetime import datetime
from typing import Any

from .. import ansi
from ..core import events as ev
from ..core import questions as q
from ..core import wording
from ..monitor import format_frame, sanitize

#: The protocol version this module speaks (`/v1`).
VERSION = 1


def clean(text: str) -> str:
    """Off-the-air text (a mail body, a heard path) safe for any client."""
    return sanitize(str(text).encode("utf-8", errors="replace"))


def jsonable(value: Any) -> Any:
    """`value` as plain JSON types: dataclasses as dicts, tuples as lists,
    datetimes as ISO text, anything else odd as its string."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, datetime):
        return value.isoformat()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonable(v) for v in value]
    return str(value)


def styled(data: bytes) -> dict:
    """Session bytes as filtered text plus colour spans `[start, end, style]`."""
    text = ansi.to_text(data)
    spans = [[s.start, s.end, str(s.style)] for s in text.spans if str(s.style)]
    return {"text": text.plain, "spans": spans}


def session_summary(core, key: str) -> dict:
    """What a client shows about session `key`."""
    session = core.sessions.get(key) if core.sessions is not None else None
    if session is None:
        return {"key": key, "connected": False}
    link = session.link
    family = session.reference.family
    return {
        "key": key,
        "peer": str(getattr(link, "peer", "") or ""),
        "connected": bool(link is not None and getattr(link, "connected", False)),
        "node": family.name if family is not None else "",
        "current_node": session.current_node,
        "application": session.application,
    }


def event(core, seq: int, event: ev.Event) -> dict:
    """One core event as a protocol `event` message."""
    name = type(event).__name__
    if isinstance(event, ev.SessionData):
        data = {"key": event.key, **styled(event.data),
                "raw": base64.b64encode(event.data).decode("ascii")}
    elif isinstance(event, ev.FrameSeen):
        line = format_frame(event.frame, event.port, outgoing=event.outgoing)
        data = {"port": event.port, "outgoing": event.outgoing,
                "line": clean(line.as_text(show_time=False)),
                "raw": base64.b64encode(event.frame.encode()).decode("ascii")}
    elif isinstance(event, ev.AprsPacketHeard):
        data = {"line": clean(event.line), "at": event.at}
    elif isinstance(event, ev.SessionUpdated):
        data = session_summary(core, event.key)
    elif isinstance(event, ev.LineSent):
        data = {"key": event.key, "text": event.text}
    else:
        data = jsonable(event)
    return {"type": "event", "seq": seq, "name": name, "data": data}


def notice(notice) -> dict:
    return {"type": "notice", "text": wording.neutral(notice.text),
            "severity": str(notice.severity), "title": notice.title,
            "timeout": notice.timeout}


def question(qid: str, question: q.Question) -> dict:
    data = jsonable(question)
    if isinstance(question, q.PickFiles):
        data["have"] = jsonable(question.have)
    if isinstance(question, q.ChooseSessionTransport):
        # Whole config entries, and a Telnet or SSH one can hold a
        # password: a client needs the names only (the answer is one).
        data["transports"] = [str(t.get("name", "")) if isinstance(t, dict) else str(t)
                              for t in question.transports]
    return {"type": "question", "id": qid, "name": type(question).__name__, "data": data}


class BadAnswer(ValueError):
    """An answer that does not fit its question."""


def answer(question: q.Question, value: Any) -> Any:
    """A client's answer as the Python value the core's flow expects.
    `None` is cancel. A malformed answer raises `BadAnswer`; the server
    treats that as no answer yet."""
    if value is None:
        return None
    # A setup question's "Skip" and "Go there" (`questions.SETUP_*`), as
    # words: the core's sentinels are not meant to be typed.
    if value == "skip":
        return q.SETUP_SKIP
    if value == "go":
        return q.SETUP_GO
    try:
        if isinstance(question, (q.RadioReminder, q.TrustHostKey)):
            return bool(value)
        if isinstance(question, q.WinlinkGateway):
            return q.GatewayChoice(str(value["target"]), bool(value.get("remember", False)))
        if isinstance(question, q.InternetLoginAsk):
            return q.InternetLogin(str(value["target"]), str(value.get("username", "")),
                                   str(value.get("password", "")))
        if isinstance(question, q.LoginAsk):
            if question.username is not None:
                return q.Credential(question.name, str(value["password"]),
                                    str(value.get("username", "")))
            return str(value)
        if isinstance(question, q.ChooseCategories):
            return [str(c) for c in value["categories"]], bool(value.get("all", False))
        if isinstance(question, q.PickFiles):
            return [str(name) for name in value]
        if isinstance(question, (q.HomeBbsRoute, q.CallsignAsk, q.ChooseSessionTransport)):
            return str(value)
    except (KeyError, TypeError, ValueError) as exc:
        raise BadAnswer(f"{type(question).__name__}: {exc}") from None
    raise BadAnswer(f"no answer form for {type(question).__name__}")
