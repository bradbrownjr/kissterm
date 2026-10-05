"""What a remote client knows about the station, built from the protocol
messages alone (docs/PROTOCOL.md), with no UI.

**Separate from the widgets so it can be tested without Flutter**, and so
the phone, desktop and browser layouts read one model. `apply` takes every
message in order; listeners (`subscribe`) hear `(kind, data)` for what
changed: "station", "gate", "transport", "activity", "session",
"session_closed", "notice", "question", "question_closed", "monitor",
"alert", "setup", or "stale" with what to re-read ("mail", "aprs",
"heard", "addressbook", "config", "nodes").

**Text arrives filtered by the station** (`serve/wire.py`): session text
is plain with colour spans, never escape codes. Nothing here parses
anything from the air.

**Only what the station said is shown**: a line the operator types is
not added to its session until the station's `LineSent` comes back, so a
line that was refused never looks sent.
"""

from __future__ import annotations

import collections
from collections.abc import Callable
from dataclasses import dataclass, field

#: Text chunks kept per session (the station keeps the rest in its
#: transcript).
SESSION_CHUNKS = 4000
MONITOR_LINES = 500
NOTICES = 50

#: Link states that are a live link (`transport.base.SessionState`).
CONNECTED_STATES = ("connected", "timer-recovery")

#: Event -> what a client must re-read when it arrives.
STALE = {
    "MailChanged": "mail",
    "AprsMessage": "aprs",
    "AprsAcked": "aprs",
    "AprsRetried": "aprs",
    "AprsBulletinHeard": "aprs",
    "AddressBookChanged": "addressbook",
    "ConfigChanged": "config",
    "KnownNodesChanged": "nodes",
}


@dataclass(slots=True)
class Chunk:
    """Session text: `spans` are `[start, end, style]` in `text`;
    `outgoing` for a line this station sent."""

    text: str
    spans: list = field(default_factory=list)
    outgoing: bool = False


@dataclass(slots=True)
class Session:
    key: str
    peer: str = ""
    connected: bool = False
    state: str = ""
    node: str = ""
    current_node: str = ""
    application: str = ""
    chunks: collections.deque = field(
        default_factory=lambda: collections.deque(maxlen=SESSION_CHUNKS))
    #: Chunks ever received, so a view can append only what is new.
    received: int = 0

    def add(self, chunk: "Chunk") -> None:
        self.chunks.append(chunk)
        self.received += 1

    @property
    def title(self) -> str:
        return self.current_node or self.peer or self.key or "Session"

    def text(self) -> str:
        return "".join(chunk.text for chunk in self.chunks)


@dataclass(slots=True)
class Question:
    qid: str
    name: str
    data: dict


class StationState:
    def __init__(self) -> None:
        self.callsign = ""
        self.version = ""
        self.gate = False
        self.transport: dict = {}
        self.activity = ""
        self.sessions: dict[str, Session] = {}
        self.questions: dict[str, Question] = {}
        self.notices: collections.deque = collections.deque(maxlen=NOTICES)
        self.monitor: collections.deque = collections.deque(maxlen=MONITOR_LINES)
        #: Correspondents with an APRS message to me not yet looked at.
        self.unread_aprs: set[str] = set()
        self._listeners: list[Callable[[str, object], None]] = []

    def subscribe(self, listener: Callable[[str, object], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    def _tell(self, kind: str, data: object = None) -> None:
        for listener in list(self._listeners):
            listener(kind, data)

    def session(self, key: str) -> Session:
        if key not in self.sessions:
            self.sessions[key] = Session(key)
        return self.sessions[key]

    # ------------------------------------------------------------------
    def apply(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "welcome":
            self._welcome(message)
        elif kind == "event":
            self._event(message.get("name", ""), message.get("data") or {})
        elif kind == "notice":
            self.notices.append(message)
            self._tell("notice", message)
        elif kind == "error":
            notice = {"type": "notice", "text": message.get("error", ""),
                      "severity": "error", "title": "", "timeout": None}
            self.notices.append(notice)
            self._tell("notice", notice)
        elif kind == "question":
            question = Question(message["id"], message.get("name", ""), message.get("data") or {})
            self.questions[question.qid] = question
            self._tell("question", question)
        elif kind == "question_closed":
            if self.questions.pop(message.get("id"), None) is not None:
                self._tell("question_closed", message.get("id"))

    def _welcome(self, message: dict) -> None:
        station = message.get("station") or {}
        snapshot = message.get("snapshot") or {}
        self.callsign = station.get("callsign", "")
        self.version = station.get("kissterm", "")
        self.gate = bool(snapshot.get("gate"))
        self.transport = snapshot.get("transport") or {}
        self.activity = snapshot.get("activity", "")
        # Questions are sent again after every welcome: start clean.
        self.questions.clear()
        live = set()
        for summary in snapshot.get("sessions") or []:
            live.add(summary.get("key", ""))
            self._summary(summary)
        for key in [k for k in self.sessions if k not in live and not self.sessions[k].chunks]:
            del self.sessions[key]
        self._tell("station")

    def _summary(self, data: dict) -> None:
        session = self.session(data.get("key", ""))
        for name in ("peer", "connected", "node", "current_node", "application"):
            if name in data:
                setattr(session, name, data[name])
        self._tell("session", session)

    def _event(self, name: str, data: dict) -> None:
        if name == "GateChanged":
            self.gate = bool(data.get("enabled"))
            self._tell("gate", self.gate)
        elif name == "TransportChanged":
            self.transport = data
            self._tell("transport", data)
        elif name == "ActivityChanged":
            self.activity = data.get("text", "")
            self._tell("activity", self.activity)
        elif name == "SessionOpened":
            session = self.session(data.get("key", ""))
            session.peer = data.get("peer", session.peer)
            self._tell("session", session)
        elif name == "SessionData":
            session = self.session(data.get("key", ""))
            session.add(Chunk(data.get("text", ""), data.get("spans") or []))
            self._tell("session", session)
        elif name == "LineSent":
            session = self.session(data.get("key", ""))
            session.add(Chunk(data.get("text", "") + "\n", outgoing=True))
            self._tell("session", session)
        elif name == "SessionStateChanged":
            session = self.session(data.get("key", ""))
            session.state = data.get("state", "")
            # TIMER_RECOVERY is a healthy link probing its peer, never a
            # failure (AGENTS.md section 3).
            session.connected = session.state in CONNECTED_STATES
            self._tell("session", session)
        elif name == "SessionUpdated":
            self._summary(data)
        elif name == "SessionClosed":
            key = data.get("key", "")
            if self.sessions.pop(key, None) is not None:
                self._tell("session_closed", key)
        elif name == "FrameSeen":
            self.monitor.append(data.get("line", ""))
            self._tell("monitor", data)
            self._tell("stale", "heard")
        elif name == "AprsPacketHeard":
            self._tell("stale", "heard")
        elif name == "Alert":
            self._tell("alert", data)
        elif name == "SetupRequested":
            self._tell("setup", data.get("place", ""))
        elif name in STALE:
            if name == "AprsMessage" and data.get("to_me"):
                self.unread_aprs.add(data.get("correspondent", ""))
            self._tell("stale", STALE[name])
