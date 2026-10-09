"""Sessions: every live link's record, node identification and reply watch,
for every front end (ROADMAP P7a M3).

**What a session is.** One conversation with one far station (a Terminal
tab in the terminal UI), keyed by `connect.session_key`. The core keeps
its link, its transcript, what kind of node is at the far end and which of
its applications the operator is in, and the commands learned from it. A
client draws it from events: `SessionOpened`, `SessionData` (raw bytes,
for the client to filter), `LineSent`, `SessionStateChanged`,
`SessionUpdated` and `SessionClosed` (`events.py`).

**`send_line` is the one path for a typed line to the air**
(`tests/pilot/test_terminal_ux.py` checks that no other method in this
module and nothing in the terminal pane sends one).

**Identification is passive.** The banner and prompt arrive anyway; asking
a node for its command list costs real airtime and is opt-in, once, cached
forever (`harvest_commands`; AGENTS.md "Airtime is the scarce resource").
A wrong family shown confidently is worse than "unknown".

**Records never go to the Terminal.** A note about a session goes to its
transcript (or kissterm.log); the Terminal holds only what the far end sent
and what was sent to it (DESIGN.md section 6).

Single-threaded, one loop: every callback here runs on the station's loop,
and the reply watch is an event-loop timer, not a UI one.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..harvested import HarvestedCommands
from ..monitor import sanitize
from ..nodes import Command, CommandReference
from ..nodes.reference import (
    UNPUBLISHED,
    application_named,
    applications_of,
    describe_airtime,
    identify_family,
    parse_harvested,
)
from ..session_log import SessionLog
from ..transport.base import SessionState
from .connect import session_key
from .events import (
    ActivityChanged,
    LineSent,
    SessionClosed,
    SessionData,
    SessionOpened,
    SessionStateChanged,
    SessionUpdated,
)
from .hops import HOP_COMMAND_WORDS, HopConfirmation
from .links import SessionLinkAdapter
from .operator import Notice, Severity
from .wording import TRANSMIT_DISABLED

log = logging.getLogger(__name__)

#: How long after sending a line, with nothing back, before saying so
#: (`Sessions.note_if_no_reply`). From a real report: WS1EC-15
#: acknowledged a line at the AX.25 layer (an RR came back within 3
#: seconds) and then said nothing for 22 seconds before the operator gave
#: up and disconnected, having no way to tell "they got it, they are just
#: slow" from "this went nowhere" without reading the Monitor tab and
#: knowing to look for a hidden-by-default supervisory frame. Long enough
#: that an ordinary node's response time does not trip it on every line.
REPLY_WAIT_SECONDS = 15.0


#: `Sessions.harvest_commands` NEVER waits longer than this, no matter
#: what. From a real report: a fixed 5-second window (this constant's first
#: value) closed a harvest 12 seconds before WS1EC-15/CCEMA's reply even
#: started arriving -- its "?" needed three T1 retry/REJ recovery cycles
#: before the actual text came through, ~18.8 seconds after the request went
#: out, for a reply of all of two lines. That delay is real AX.25 behaviour
#: on a lossy link (AGENTS.md: "TIMER_RECOVERY is not an error state"), not
#: a hang, so the ceiling has to tolerate it -- 90s roughly matches
#: `describe_airtime(8192)`'s documented worst case plus headroom for
#: exactly this kind of retry overhead, which `describe_airtime` does not
#: model at all (it only prices wire time, not link-layer recovery).
HARVEST_MAX_WAIT_SECONDS = 90.0

#: Once a harvest has received AT LEAST ONE byte, this much silence after
#: the last one is treated as "the node is done sending" and the capture
#: ends early -- most replies are short, and nobody should have to wait out
#: the full 90-second ceiling for a two-line answer. This is deliberately
#: NOT the same heuristic AGENTS.md's testing section warns against ("do not
#: drain a lossy link with a went-quiet heuristic"): that warning is about
#: mistaking a mid-transfer T1 recovery gap for the end of an ongoing,
#: segmented transfer with no ceiling at all. This is a one-shot
#: request/reply exchange with a hard ceiling as the backstop, so a quiet
#: gap AFTER real content has already started arriving is a reasonable
#: signal, not a guess with no fallback.
HARVEST_QUIET_SECONDS = 3.0

#: How often `harvest_commands` checks the buffer while waiting. Small
#: enough that the quiet-exit above doesn't overshoot by much, cheap enough
#: that polling for up to 90 seconds costs nothing measurable.
HARVEST_POLL_INTERVAL = 0.5

#: Hard cap on how much text one harvest capture keeps, regardless of how
#: much the node actually sends. A chatty or verbose node must not turn one
#: opt-in harvest into unbounded memory growth for a session that stays open
#: for hours.
HARVEST_CAPTURE_LIMIT = 4096

#: Most characters of a session's text kept for Save as text
#: (`LiveSession.screen`, `core/export.py`); the oldest go first.
SCREEN_LIMIT = 1024 * 1024


@dataclass
class LiveSession:
    """Everything the core tracks for one session (a Terminal tab).

    Keyed in `Sessions.by_key` by `connect.session_key` (a peer's callsign,
    plus port if not 0). `link` is `None` only for the permanent `""` entry
    -- the pre-connection view, which has no link at all. A fresh instance
    IS the reset a reconnect to the same peer needs (a new node's banner
    must not be read against the last one's command reference) -- see
    `Sessions.bind`, which replaces rather than mutates.
    """

    link: object = None
    reference: "CommandReference" = field(default_factory=CommandReference)
    detect_buffer: str = ""
    transcript: SessionLog | None = None
    #: The reply watch (`Sessions.note_if_no_reply`), an event-loop timer.
    reply_timer: asyncio.TimerHandle | None = None
    #: Who the operator is currently, logically, talking to -- starts as
    #: `str(link.peer)` (the real AX.25 remote station, set in `_bind_link`
    #: since a dataclass default cannot read another field) and only changes
    #: once a hop to a different node is CONFIRMED to have succeeded (see
    #: `Sessions.commit_hop`). Distinct from `link.peer`, which never
    #: changes for the life of a connection even when the operator hops
    #: through intermediate nodes at the far node's application layer --
    #: conflating the two is what made `harvest_commands` cache a hopped-to
    #: node's command list under the FIRST node's callsign, silently
    #: corrupting that node's real entry in `harvested.py`'s store.
    current_node: str = ""
    #: The background watch started by `log_sent` for a hand-typed hop, so
    #: it can be cancelled -- a second hop sent before the first resolves
    #: must not leave two watchers racing on the same `link.on_data`. Kept
    #: as a plain `asyncio.Task` with a manual stop/clear, mirroring
    #: `reply_timer` above rather than introducing a worker-group pattern
    #: this file uses nowhere else.
    hop_watch_task: "asyncio.Task | None" = None
    #: `None` means "not harvesting right now" -- the common case. Set to an
    #: (initially empty) string by `Sessions.harvest_commands` for the
    #: duration of its capture window; `_capture_harvest` appends into it.
    #: See `HARVEST_CAPTURE_LIMIT` for why it cannot grow without bound.
    harvest_buffer: str | None = None
    #: Sanitized text from the most recent completed harvest on this live
    #: session. The Node commands screen shows it after parsing so the operator can
    #: judge what the node actually said, rather than trusting a terse list
    #: of names extracted from an opaque exchange. It is deliberately
    #: per-session and in-memory: it is diagnostic context, not a second
    #: command cache or a new persistence promise.
    last_harvest_text: str = ""
    #: The last state `_on_link_state` was actually called with -- set on
    #: EVERY call, including a suppressed TIMER_RECOVERY one, never only on
    #: a call that wrote a note. See that method's docstring for why a
    #: "last state we wrote a note for" version of this field does not work.
    last_state: "SessionState | None" = None
    #: The application the node said it handed this session to ("BBS",
    #: "CHAT", a sysop's "CALENDAR"), upper-cased; "" while at the node.
    #: See `Sessions.track_application`.
    application: str = ""
    #: The node's own command set, put aside while an application's is in
    #: effect and restored when the node says the session came back.
    node_reference: "CommandReference | None" = None
    #: The unterminated tail of the last chunk received, so a line split
    #: across two frames is still matched whole.
    line_buffer: str = ""
    #: Until when (`time.monotonic()`) a YAPP send init on this session is
    #: the download the operator asked for; 0 when none was asked.
    download_until: float = 0.0
    #: The session as its Terminal tab shows it, as plain text: what the
    #: far end sent (sanitized) and each line sent to it, never a record
    #: (DESIGN.md section 6). Kept whether or not transcripts are on, for
    #: Save as text (`core/export.py`); at most `SCREEN_LIMIT` characters.
    screen: str = ""


class Sessions:
    """Every live session: what it is bound to, what it has said, and what
    kissterm has learned about the far end. Owned by `Core` as
    `core.sessions`; a client follows it through events (module docstring).
    """

    def __init__(self, core) -> None:
        self.core = core
        #: Per-session state keyed by `connect.session_key`. The permanent
        #: `""` entry is the pre-connection view (and the session tier's one
        #: session), so "nothing on screen" still has an entry to read.
        self.by_key: dict[str, LiveSession] = {"": LiveSession()}
        #: Command names harvested from a node's own `?`, cached forever per
        #: callsign so the opt-in airtime is never spent twice for the same
        #: node -- see `kissterm/harvested.py` and `harvest_commands`.
        self.harvested = HarvestedCommands()
        self.harvested.load()
        #: Callsigns already explained by `on_stray_poll` this launch.
        self.stray_noted: set[str] = set()
        #: `(key, data) -> bool`: True takes the bytes away from the session
        #: (a file transfer reading them). Until file transfers move into
        #: the core (milestone 5), the terminal UI registers its own here.
        self.data_interceptors: list[Callable[[str, bytes], bool]] = []
        #: `(key, text, session)` after a line is logged as sent; the
        #: terminal UI's YAPP download watch, until milestone 5.
        self.sent_hooks: list[Callable[[str, str, LiveSession], None]] = []
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    @property
    def config(self):
        return self.core.config

    def _publish(self, event) -> None:
        self.core.events.publish(event)

    def _notice(self, text: str, severity: Severity = Severity.INFORMATION) -> None:
        self.core.operator.notice(Notice(text, severity))

    def get(self, key: str) -> LiveSession | None:
        return self.by_key.get(key)

    def link(self, key: str):
        session = self.by_key.get(key)
        return session.link if session is not None else None

    # ------------------------------------------------------------------
    # Binding a link
    # ------------------------------------------------------------------
    def bind(self, link, key: str | None = None, *, activate: bool = True,
             incoming: bool = False) -> str:
        """Wire a connected link into its session: transcript, node
        reference, reply watch, and a `SessionOpened` for the clients.

        `key` is computed from `link.peer`/`link.port` when not given --
        every caller except the connect flow needs exactly that, since that
        one must know the key before the link exists. A fresh
        `LiveSession()` is what resets the node reference and detect buffer
        for a new conversation; any reply timer, hop watch or transcript
        left from a PRIOR binding of this key (a reconnect to a peer whose
        tab is still open) is torn down first.

        The one thing NOT reset: commands harvested from this exact peer
        are re-applied at once, so a reconnect never re-asks and never
        re-spends the airtime (`HarvestedCommands.for_callsign`).
        """
        key = key if key is not None else session_key(link.peer, link.port)
        self.cancel_reply_timer(key)
        self.cancel_hop_watch(key)
        self.close_transcript(key)
        previous = self.by_key.get(key)
        session = LiveSession(link=link)
        # A reconnect keeps its tab and what the tab shows.
        session.screen = previous.screen if previous is not None else ""
        # A fresh connection is talking to the link's own peer; any logical
        # peer a previous hop chain established belonged to the session that
        # just ended (`LiveSession.current_node`, `commit_hop`).
        session.current_node = str(link.peer)
        session.reference = CommandReference(learned=self.learned(str(link.peer), "node"))
        self.by_key[key] = session
        self._publish(SessionOpened(key, str(link.peer), activate, incoming))
        self.start_transcript(key, link)
        link.on_data.append(lambda data: self.on_link_data(key, data))
        link.on_state.append(lambda state: self.on_link_state(key, state))
        link.on_error.append(lambda why: self.link_error(key, why))
        return key

    def on_incoming_link(self, link) -> None:
        """A station called us and the station accepted (`accept_incoming`)."""
        key = self.bind(link, activate=True, incoming=True)
        self.record(key, f"Incoming connection from {link.peer}")
        if not self.core.gate.enabled:
            # The UA never went out, so the caller is talking to nobody. Say
            # so: "somebody called and you could not answer" is exactly what
            # an operator wants to find later.
            self.record(key, f"Could not answer {link.peer} -- transmit is disabled")
            self._notice(f"{link.peer} called, but transmit is disabled.", Severity.WARNING)
        self._spawn(self.send_banner(link))
        self._notice(f"Connection from {link.peer}")

    def on_stray_poll(self, peer, port: int) -> None:
        """A station polled a link we do not hold; the station answered DM.

        Typical after a relaunch or a crash mid-connection: the node still
        thinks it is connected and polls until its N2 runs out. Said once per
        peer per launch (a node polls about every 7 s), and it says what the
        DM means, so a caller with no matching session is not a mystery.
        """
        call = str(peer)
        if call in self.stray_noted:
            return
        self.stray_noted.add(call)
        if self.core.gate.enabled:
            what = "answered DM (no connection here) so it stops polling"
        else:
            what = "would answer DM, but transmit is disabled ({key:toggle_transmit})"
        self._notice(
            f"{call} is polling a connection kissterm does not have "
            f"(left open when it last closed?); {what}."
        )

    async def send_banner(self, link) -> None:
        """Greet a caller, so the link does not open into silence (BPQ32's
        CTEXT; short, because every byte is airtime). Checked against
        `accept_incoming` at the moment it transmits, not only where the
        connection was accepted."""
        banner = (getattr(self.config, "connect_banner", "") or "").strip()
        if not banner or not getattr(self.config, "accept_incoming", False):
            return
        try:
            await link.send(banner.encode("latin-1", "replace") + b"\r")
        except Exception:  # noqa: BLE001 - a greeting must not break the link
            log.exception("could not send connect banner to %s", link.peer)

    def close(self, key: str) -> None:
        """Forget session `key` (its tab closed). Timers and the hop watch
        are cancelled BEFORE the entry goes: `cancel_hop_watch` finds the
        task through `by_key`."""
        self.cancel_reply_timer(key)
        self.cancel_hop_watch(key)
        self.by_key.pop(key, None)
        self._publish(SessionClosed(key))

    def shutdown(self) -> None:
        """Close every transcript and stop every timer and watch."""
        for key in list(self.by_key):
            self.close_transcript(key)
            self.cancel_reply_timer(key)
            self.cancel_hop_watch(key)
        for task in list(self._tasks):
            task.cancel()

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # ------------------------------------------------------------------
    # The record: transcripts and notes
    # ------------------------------------------------------------------
    def transcript_directory(self) -> Path:
        """Where transcripts are written and read back from -- one method,
        so the two can never drift onto different directories."""
        from ..config import log_path

        return Path(self.config.log_dir) if self.config.log_dir else log_path()

    def transcripts(self, needle: str = "") -> list:
        """Past transcripts, newest first, filtered by callsign or by what
        is in them (`transcripts.search_transcripts`): the terminal's
        Transcripts screen and the phone's both read this directory."""
        from ..transcripts import search_transcripts

        return search_transcripts(self.transcript_directory(), needle)

    def read_transcript(self, name: str, limit: int = 256 * 1024) -> str:
        """One transcript's text by its file name, the last `limit` bytes
        of a long one. Only a name `transcripts` lists is read, never a
        path: a client cannot reach outside the directory."""
        from ..ansi import decode_text
        from ..transcripts import list_transcripts

        for info in list_transcripts(self.transcript_directory()):
            if info.path.name == name:
                with open(info.path, "rb") as handle:
                    if info.size > limit:
                        handle.seek(info.size - limit)
                    return decode_text(handle.read())
        raise FileNotFoundError(name)

    def start_transcript(self, key: str, link) -> None:
        """Open a transcript for `key`, if recording is enabled."""
        self.close_transcript(key)
        if not getattr(self.config, "log_sessions", True):
            return
        station = self.core.station
        # No station on the session tier, but the operator's own callsign is
        # still `config.mycall`.
        mycall = str(station.mycall) if station is not None else str(
            getattr(self.config, "mycall", "") or "")
        transcript = SessionLog(self.transcript_directory(), mycall, str(link.peer))
        if not transcript.open():
            self._notice(f"No transcript for {link.peer}: {transcript.failed}", Severity.WARNING)
            return
        session = self.by_key.get(key)
        if session is not None:
            session.transcript = transcript
        self._publish(SessionUpdated(key))

    def close_transcript(self, key: str) -> None:
        session = self.by_key.get(key)
        if session is not None and session.transcript is not None:
            session.transcript.close()
            session.transcript = None
            self._publish(SessionUpdated(key))

    def record(self, key: str, text: str) -> None:
        """Something kissterm did or saw about a session, for the record:
        its transcript, or kissterm.log when it has none (a connect that
        never came up). Never the Terminal, which holds only what the far
        end sent and what was sent to it (operator, 2026-10-02: "I again
        don't want anything in there that didn't come from the node")."""
        text = text.strip().lstrip("* ")
        session = self.by_key.get(key)
        if session is not None and session.transcript is not None:
            session.transcript.note(text)
        else:
            log.info("%s: %s", key or "session", text)

    def note(self, key: str, text: str) -> None:
        """A note about one session: to its transcript, never its screen."""
        self.record(key, text)

    def link_error(self, key: str, why: str) -> None:
        """A link failed under a session: recorded, and one notice."""
        self.record(key, why)
        self._notice(f"{key or 'Session'}: {why}", Severity.WARNING)

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------
    async def send_line(self, key: str, text: str, *,
                        refuse: Callable[[str], bool] | None = None,
                        before_send: Callable[[], None] | None = None) -> bool:
        """The one path for a line the operator typed to the air.

        A line committed with Enter or Send, to a station already connected,
        is the "confirmed, targeted" request that arms the gate
        (`Connector.arm_for`); a closed gate on a session with nothing to
        send to arms nothing, since the link is checked first. An Internet
        contact's session cannot key a radio, so it never arms. `refuse` is
        the client's chance to keep a line the link cannot carry
        (file-transfer commands over SSH); `before_send` runs once the line
        is certain to go (the terminal clears its input). True if sent.
        """
        if not key:
            # No session: the Terminal's Broadcast tab. A line typed there
            # is an unproto broadcast, sent once (`core/broadcast.py`).
            return await self.core.broadcast.send_line(text, before_send)
        link = self.link(key)
        if link is None or not link.connected:
            self._notice("Not connected.", Severity.WARNING)
            return False
        if refuse is not None and refuse(text):
            return False
        if not self.core.gate.enabled and not getattr(link, "internet", False):
            self.core.connector.arm_for(f"sending to {key}")
        if before_send is not None:
            before_send()
        # latin-1, not UTF-8: packet is byte-oriented, and a pasted character
        # must not fail to encode mid-session. CR, not LF: LF makes a BPQ32
        # node echo a spurious blank line after every command.
        await link.send(text.encode("latin-1", "replace") + b"\r")
        self.echo_sent(key, text, text)
        return True

    def echo_sent(self, key: str, shown: str, sent: str, *, watch_hop: bool = True) -> None:
        """Show `shown` as sent on `key` and log `sent` as the line that
        went (a password is shown masked, logged masked too)."""
        self._publish(LineSent(key, shown))
        session = self.by_key.get(key)
        if session is not None:
            # On a line of its own, as the Terminal shows it.
            lead = "\n" if session.screen and not session.screen.endswith("\n") else ""
            self.keep_screen(session, f"{lead}{shown}\n")
        self.log_sent(key, sent, watch_hop=watch_hop)

    @staticmethod
    def keep_screen(session: LiveSession, text: str) -> None:
        """Add to `session.screen`, dropping the oldest past `SCREEN_LIMIT`."""
        session.screen += text
        if len(session.screen) > SCREEN_LIMIT:
            session.screen = session.screen[-SCREEN_LIMIT:]

    def log_sent(self, key: str, text: str, *, watch_hop: bool = True) -> None:
        """Record a line transmitted on `key`, and (re)arm its reply watch:
        the LAST line sent starts the clock.

        Also where a HAND-TYPED hop to another node is noticed. Node
        identification locks onto the first family it sees and never looks
        again, so ordinary text cannot trigger a false match; but a "C
        <node>" typed through a BPQ node changes who the operator is talking
        to without the AX.25 link changing at all. **The reset waits for the
        hop to be CONFIRMED** (`watch_typed_hop` -> `commit_hop`): a hop that
        answers BUSY or nothing leaves the operator on the node they were
        correctly identified against, and blanking that turned working
        suggestions into "unknown node" in live testing against BPQ32.

        `watch_hop=False` is for the scripted hop chain alone, which
        confirms its own hop; a second watcher would race it on the same
        bytes.
        """
        session = self.by_key.get(key)
        if session is None:
            return
        # A node's prompt has no line end ("CCEMA:WS1EC-15} "); the line the
        # operator typed ends it, or the reply reads as its continuation and
        # "Connected to BBS" never matches.
        session.line_buffer = ""
        if session.transcript is not None:
            session.transcript.sent(self.core.connector.masked(text))
        if watch_hop:
            self.watch_typed_hop(key, text)
        for hook in list(self.sent_hooks):
            hook(key, text, session)
        self.cancel_reply_timer(key)
        # Not for a blank line: that is a nudge, and a node owes it no reply
        # (CCEMA, 2026-09-22: the note blamed the far end while the node was
        # waiting on the operator).
        if text.strip() and session.link is not None and session.link.connected:
            session.reply_timer = asyncio.get_running_loop().call_later(
                REPLY_WAIT_SECONDS, self.note_if_no_reply, key)

    # ------------------------------------------------------------------
    # Hopping onward through a node, at the far end's application layer
    # ------------------------------------------------------------------
    def watch_typed_hop(self, key: str, text: str) -> None:
        """If `text` is a connect-onward command with a target, start (or
        restart) the watch that commits the hop if it comes up.

        The target is the LAST word: bpq32.toml documents "C <call>" and
        "C <port> <call>", and taking the first word would read "C 2
        JNOSNODE" as a hop to a node named "2". A bare "C" names nothing.
        """
        parts = text.strip().split(None, 1)
        if len(parts) < 2 or parts[0].upper() not in HOP_COMMAND_WORDS:
            return
        args = parts[1].strip().split()
        target = args[-1] if args else ""
        if not target:
            return
        session = self.by_key.get(key)
        if session is None or session.link is None:
            return
        # A second hop typed before the first resolved replaces it; the old
        # watcher would otherwise match the NEW hop's traffic.
        self.cancel_hop_watch(key)
        # Subscribed HERE, synchronously: a task does not run until the loop
        # next gets a turn, and a reply in that window would be missed. The
        # link is captured now, so a reconnect on this key cannot move it.
        link = session.link
        watch = HopConfirmation(link, target)
        connector = self.core.connector

        async def _run() -> None:
            try:
                ok, _detail = await connector.await_hop_confirmation(link, target, watch=watch)
                if ok:
                    self.commit_hop(key, target)
            finally:
                current = self.by_key.get(key)
                if current is not None and current.hop_watch_task is task:
                    current.hop_watch_task = None

        task = asyncio.get_event_loop().create_task(_run(), name=f"hop-watch:{key}:{target}")
        # Unsubscribe on EVERY ending, including a task cancelled before it
        # ever ran, whose `finally` never fires. `stop` is idempotent.
        task.add_done_callback(lambda _task: watch.stop())
        session.hop_watch_task = task

    def cancel_hop_watch(self, key: str) -> None:
        session = self.by_key.get(key)
        if session is not None and session.hop_watch_task is not None:
            session.hop_watch_task.cancel()
            session.hop_watch_task = None

    def commit_hop(self, key: str, node: str) -> None:
        """Apply a CONFIRMED hop to `node`: from here on this session is
        logically talking to a different station than its link's peer.

        The ONLY place a hop's success is applied (scripted chain and typed
        hop alike). Re-arms node detection so the new node's banner gets a
        clean read, and re-applies anything already harvested from `node`.
        Never call it for a hop that refused or timed out.
        """
        session = self.by_key.get(key)
        if session is None:
            return
        session.current_node = node
        session.reference = CommandReference(learned=self.learned(node, "node"))
        session.detect_buffer = ""
        session.application = ""
        session.node_reference = None
        session.line_buffer = ""
        self._publish(SessionUpdated(key))

    # ------------------------------------------------------------------
    # Receiving
    # ------------------------------------------------------------------
    def on_link_data(self, key: str, data: bytes) -> None:
        for intercept in list(self.data_interceptors):
            if intercept(key, data):
                return
        # Any data back answers the "did they get it" question the reply
        # watch exists for.
        self.cancel_reply_timer(key)
        self._publish(SessionData(key, data))
        session = self.by_key.get(key)
        if session is not None:
            self.keep_screen(session, sanitize(data))
        if session is not None and session.transcript is not None:
            # Sanitized, never raw: `cat` on a transcript would run the
            # escape sequences the terminal's filter removes.
            session.transcript.received_stream(data, sanitize)
        self.sniff_node(key, data)
        self.capture_harvest(key, data)

    def sniff_node(self, key: str, data: bytes) -> None:
        """Identify the node family from what it already sent -- passive on
        purpose: asking with `?` costs twenty seconds to a minute of a
        1200-baud channel, and the banner and prompt arrive anyway.

        Only the first couple of kilobytes are examined; a node identifies
        itself in its greeting or not at all, and scanning forever would let
        message text trigger a false match. Once known, `track_application`
        follows the family's own enter/return lines.
        """
        session = self.by_key.get(key)
        if session is None:
            return
        text = sanitize(data)
        if (
            session.reference.family is None
            and not session.application
            and len(session.detect_buffer) <= 2048
        ):
            session.detect_buffer += text
            family = identify_family(session.detect_buffer)
            if family is not None:
                # In place: replacing the whole reference would drop the
                # learned commands `bind` pre-populated.
                session.reference.family = family
                if family.kind == "application":
                    # Connected straight to a BBS: its harvested names, not
                    # the node-context ones `bind` assumed.
                    session.reference.learned = self.learned(
                        session.current_node, family.harvest_context)
                self._publish(SessionUpdated(key))
        self.track_application(key, session, text)

    def track_application(self, key: str, session: LiveSession, text: str) -> None:
        """Follow the session into and out of a node's applications.

        A BPQ32 node says "Connected to BBS" when it hands the session to
        its BBS and "Returned to Node" when one hands it back; between the
        two, BPQMail's commands are in effect ("L" lists mail there and
        links at the node). Both lines come from the family's data
        (`enter_pattern`, `return_pattern`), so nothing here is
        BPQ-specific. An application kissterm ships no reference for gets an
        empty command set. The node uses the same words for a hop to
        another node, so while a typed hop is watched an unknown name is
        left to `commit_hop`.
        """
        node = (
            session.node_reference.family
            if session.node_reference is not None
            else session.reference.family
        )
        if node is None or node.kind != "node" or not (node.enter_pattern or node.return_pattern):
            return
        pending = session.line_buffer + text
        *lines, tail = re.split(r"\r\n|\r|\n", pending)
        session.line_buffer = tail[-512:]
        try:
            if session.application:
                # The return line is followed by the node's prompt with no
                # line end, so the unterminated tail counts too.
                if node.return_pattern and any(
                    re.search(node.return_pattern, line) for line in (*lines, tail)
                ):
                    session.reference = session.node_reference or CommandReference()
                    session.node_reference = None
                    session.application = ""
                    session.line_buffer = ""
                    self._publish(SessionUpdated(key))
                return
            if not node.enter_pattern:
                return
            for line in lines:
                match = re.search(node.enter_pattern, line)
                if match is None:
                    continue
                name = match.group(1).upper()
                family = application_named(name)
                if family is None and session.hop_watch_task is not None:
                    continue
                session.node_reference = session.reference
                session.application = name
                context = family.harvest_context if family is not None else "application"
                session.reference = CommandReference(
                    family=family, learned=self.learned(session.current_node, context))
                self._publish(SessionUpdated(key))
                return
        except re.error:
            log.warning("bad enter/return pattern in family %s", node.id)

    def on_link_state(self, key: str, state: SessionState) -> None:
        """Record a state change -- except a TIMER_RECOVERY excursion and
        its own return to CONNECTED, which a lossy channel produces several
        times per reply and which is not an error (AGENTS.md section 3).
        `last_state` is recorded on EVERY call, or the return could never
        be recognised as one (that shipped once, caught only live)."""
        session = self.by_key.get(key)
        previous = session.last_state if session is not None else None
        recovering = state is SessionState.TIMER_RECOVERY
        recovered = state is SessionState.CONNECTED and previous is SessionState.TIMER_RECOVERY
        if not recovering and not recovered:
            self.note(key, state.value)
        if session is not None:
            session.last_state = state
        if state is not SessionState.CONNECTED:
            # Nothing to ask "did they get it" about any more.
            self.cancel_reply_timer(key)
        if state is SessionState.DISCONNECTED:
            # Only here, never on TIMER_RECOVERY: a hop over a marginal path
            # spends real time in recovery and comes back.
            self.cancel_hop_watch(key)
            self.close_transcript(key)
        self._publish(SessionStateChanged(key, state.value))

    # ------------------------------------------------------------------
    # The reply watch -- "they got it, are they just not answering?"
    # ------------------------------------------------------------------
    def cancel_reply_timer(self, key: str) -> None:
        session = self.by_key.get(key)
        if session is not None and session.reply_timer is not None:
            session.reply_timer.cancel()
            session.reply_timer = None

    def note_if_no_reply(self, key: str) -> None:
        """`REPLY_WAIT_SECONDS` after a send with nothing back, on `key`
        (bound when the timer was armed, so a tab switch cannot misreport).

        Only when the AX.25 layer has nothing outstanding (`va == vs`): the
        far end acknowledged the line. Unacknowledged, T1 is already
        retrying. From a real report: WS1EC-15 ACKed in 3 s and then said
        nothing for 22, and the only sign of the ACK was a hidden RR frame.
        """
        session = self.by_key.get(key)
        if session is None:
            return
        session.reply_timer = None
        link = session.link
        # A session-tier link has no V(A)/V(S) (operator, 2026-10-03: this
        # timer crashed the app 25 s after a line typed over SSH).
        if link is None or not link.connected or isinstance(link, SessionLinkAdapter):
            return
        if link.va != link.vs:
            return
        self._notice(
            f"{link.peer} acknowledged that -- no reply yet. The {{view:monitor}} "
            "shows what has come back since."
        )

    # ------------------------------------------------------------------
    # Command references, learned and harvested
    # ------------------------------------------------------------------
    def learned(self, node: str, context: str) -> tuple[Command, ...]:
        """Names harvested from `node` in one context, as `Command`s --
        "L" at the BBS and "L" at the node are different commands."""
        return tuple(
            Command(name=command.name, confidence="learned", context=command.context)
            for command in self.harvested.records_for_callsign(node)
            if command.context == context
        )

    @staticmethod
    def context_of(session: LiveSession) -> str:
        """The harvest context (node / bbs / application) in effect."""
        family = session.reference.family
        if family is not None and family.kind == "application":
            return family.harvest_context
        return "application" if session.application else "node"

    def learned_node(self, key: str) -> tuple[str, int]:
        """The node this session's learned commands are filed under, and
        how many there are."""
        session = self.by_key.get(key)
        if session is None or session.link is None:
            return ("", 0)
        node = session.current_node or str(session.link.peer)
        return (node, len(self.harvested.records_for_callsign(node)))

    def forget_learned(self, key: str) -> int:
        """Drop everything learned from this session's node, from the cache
        and the live references. Sends nothing."""
        node, _count = self.learned_node(key)
        if not node:
            return 0
        dropped = self.harvested.forget(node)
        session = self.by_key[key]
        session.reference.learned = ()
        if session.node_reference is not None:
            session.node_reference.learned = ()
        self._notice(f"Forgot {dropped} learned command(s) for {node}.")
        return dropped

    def reference_sections(self, key: str) -> tuple[CommandReference, ...]:
        """The command sets reachable from where this session is, other
        than the one in effect: the node's while inside its BBS, and the
        node's applications either way -- so a BBS command can be looked up
        before spending the airtime to enter the BBS."""
        session = self.by_key.get(key)
        if session is None:
            return ()
        current = session.reference
        node_reference = session.node_reference if session.application else current
        sections: list[CommandReference] = []
        if session.application and node_reference is not None:
            sections.append(node_reference)
        node_family = node_reference.family if node_reference is not None else None
        if node_family is not None and node_family.kind == "node":
            for family in applications_of(node_family):
                if family is current.family:
                    continue
                sections.append(CommandReference(
                    family=family,
                    learned=self.learned(session.current_node, family.harvest_context),
                ))
        return tuple(sections)

    def reference_view(self, key: str) -> dict:
        """What the terminal's command reference (`CommandReferenceScreen`)
        shows for this session, as plain data for a client: the command set
        in effect and the others reachable from here, each command with its
        source ("published", "recalled, unverified", ...), and what the
        Learn from node button needs (whether the link is up, who would be
        asked, the airtime range, the context in effect). Nothing is sent."""
        session = self.by_key.get(key)
        if session is None:
            return {}
        link = session.link
        peer = session.current_node or (str(link.peer) if link is not None else "")
        node, learned = self.learned_node(key)

        def section(reference: CommandReference) -> dict:
            family = reference.family
            note = ""
            if family is None:
                note = ("The node has not been identified from its banner or prompt, so "
                        "this list may not apply. Nothing has been asked of the node -- "
                        "that would cost airtime.")
            else:
                note = " ".join(family.note.split())
                if family.confidence == "recalled":
                    note += " This reference is unverified; check a command before spending airtime on it."
            return {
                "title": family.name if family else "unknown node",
                "note": note.strip(),
                "commands": [{
                    "name": c.name, "aliases": list(c.aliases), "usage": c.usage or c.name,
                    "summary": c.summary or (UNPUBLISHED if c.confidence == "learned" else ""),
                    "detail": c.detail, "context": c.context, "sysop": c.sysop,
                    "source": reference.tier(c)} for c in reference.commands],
            }

        return {
            "sections": [section(session.reference),
                         *(section(r) for r in self.reference_sections(key))],
            "can_harvest": link is not None and link.connected,
            "peer": peer,
            "context": self.context_of(session),
            "learned": learned,
            "learned_node": node,
            "airtime": [describe_airtime(512), describe_airtime(8192)],
        }

    def bbs_helpers(self) -> list[dict]:
        """The BBS mail helper's dialects and their commands (the terminal's
        `BbsHelperScreen`): each macro's `fields` (a message number, a
        callsign) say what it needs. Nothing is sent."""
        from .. import bbs

        return [{"id": p.id, "name": p.name, "note": p.note, "macros": [
            {"id": m.id, "label": m.label, "summary": m.summary, "fields": list(m.fields),
             "confidence": m.confidence} for m in p.macros]} for p in bbs.profiles()]

    def bbs_render(self, profile_id: str, macro_id: str, values: dict) -> dict:
        """The one-line command a macro makes from `values`: `text`, or
        `error` saying what is missing or not allowed (a number is digits,
        no control characters). Fills a client's message box at most; never
        sends."""
        from .. import bbs

        found = bbs.profile(profile_id)
        macro = next((m for m in found.macros if m.id == macro_id), None) if found else None
        if macro is None:
            return {"text": "", "error": "Unknown BBS command."}
        try:
            return {"text": macro.render(**{k: str(v) for k, v in values.items()}), "error": ""}
        except ValueError as exc:
            return {"text": "", "error": str(exc)}

    def suggest(self, key: str, text: str, limit: int = 20) -> list[dict]:
        """Candidates for the partly-typed command `text` against the
        context this session is in (the terminal's suggestion strip). Fills
        a client's input at most; never sends."""
        session = self.by_key.get(key)
        if session is None:
            return []
        return [{"name": c.name, "summary": c.summary or (UNPUBLISHED if c.confidence == "learned" else ""),
                 "usage": c.usage or c.name}
                for c in session.reference.complete(text, limit=limit)]

    def harvest_context(self, key: str) -> str:
        """What a `?` asked now would be answered by."""
        session = self.by_key.get(key)
        return self.context_of(session) if session is not None else "node"

    def capture_harvest(self, key: str, data: bytes) -> None:
        """Feed one session's harvest capture window, when one is open;
        bounded by `HARVEST_CAPTURE_LIMIT`."""
        session = self.by_key.get(key)
        if session is None or session.harvest_buffer is None:
            return
        session.harvest_buffer += sanitize(data)
        if len(session.harvest_buffer) > HARVEST_CAPTURE_LIMIT:
            session.harvest_buffer = session.harvest_buffer[:HARVEST_CAPTURE_LIMIT]

    async def harvest_commands(self, key: str, *, context: str = "node") -> tuple[str, ...]:
        """Ask the node's own `?` for its command list, once, and cache what
        comes back forever under its callsign (AGENTS.md "Airtime is the
        scarce resource": the client confirms the cost first, and `bind`
        re-applies the cache on every later connect).

        Sends through `link.send`, the gated path, and is echoed and logged
        like any other automated line. Waits `HARVEST_MAX_WAIT_SECONDS` at
        most, but ends `HARVEST_QUIET_SECONDS` after the reply stops
        growing. Returns the NEWLY learned names.
        """
        session = self.by_key.get(key)
        if session is None or session.link is None or not session.link.connected:
            return ()
        if not self.core.gate.enabled:
            self._notice(TRANSMIT_DISABLED, Severity.WARNING)
            return ()
        link = session.link
        # A second, unanswered harvest must not show the previous reply as
        # though it were current.
        session.last_harvest_text = ""
        session.harvest_buffer = ""
        try:
            await link.send(b"?\r")
        except Exception:  # noqa: BLE001 - reported in the log, nothing learned
            log.exception("could not send harvest request to %s", link.peer)
            session.harvest_buffer = None
            return ()
        self.echo_sent(key, "?", "?")
        self.record(key, "Asked the node for its command list")
        self._publish(ActivityChanged("Reading the command list"))
        waited = 0.0
        quiet = 0.0
        last_length = 0
        while waited < HARVEST_MAX_WAIT_SECONDS:
            await asyncio.sleep(HARVEST_POLL_INTERVAL)
            waited += HARVEST_POLL_INTERVAL
            buffer = session.harvest_buffer or ""
            if len(buffer) > last_length:
                # Still arriving: only a buffer that stopped GROWING counts
                # toward the quiet exit.
                last_length = len(buffer)
                quiet = 0.0
            elif buffer:
                quiet += HARVEST_POLL_INTERVAL
                if quiet >= HARVEST_QUIET_SECONDS:
                    break
        text = session.harvest_buffer or ""
        session.harvest_buffer = None
        session.last_harvest_text = text
        names = parse_harvested(text)
        if not names:
            self._publish(ActivityChanged(""))
            self._notice("No commands recognised in the node's reply.", Severity.WARNING)
            return ()
        # Keyed on the LOGICAL peer: after a confirmed hop the `?` was
        # answered by the node hopped to, not the link's peer.
        node = session.current_node or str(link.peer)
        self.harvested.add(node, names, context=context)
        session.reference.learned = self.learned(node, self.context_of(session))
        self._publish(ActivityChanged(""))
        self.record(key, f"Learned {len(names)} command(s) from {node}: {', '.join(names)}")
        self._notice(f"Learned {len(names)} command(s) from {node}.")
        return names

    def last_harvest_text(self, key: str) -> str:
        """The sanitized reply captured by this session's latest harvest."""
        session = self.by_key.get(key)
        return session.last_harvest_text if session is not None else ""
