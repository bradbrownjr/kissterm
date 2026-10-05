"""YAPP and AutoBIN file transfers over a live session, for every front
end (ROADMAP P7a M5).

**A transfer's bytes are its own, not the session's.** While one runs on
a session (`active`), `intercept` (a `Sessions.data_interceptors` entry)
keeps its bytes out of the session's data events and transcript; a client
showing the session would otherwise print binary.

**A download starts by itself only when the operator asked for it.**
`YAPP <name>` sent on a session (`yapp_requested`, a `Sessions.sent_hooks`
entry) opens a `DOWNLOAD_WAIT_SECONDS` window in which a YAPP send-init is
taken as that file. A sender that turns up unasked is never answered: that
is the unattended mailbox (ROADMAP P9). BPQ sends its `ENQ 1` alone and
waits for the answer (`yapp.py`), so nothing arrives before the receiver
subscribes. Until 2026-10-03 a download had to be armed first from a menu;
the operator: "this is the only application that requires me to start a
file download session".

**An explicit transfer (`start`) is operator-committed** and arms the gate
for itself, as a typed line does. Over SSH a server's telnet holds YAPP's
replies, so a link that cannot carry binary (`carries_binary`) is refused
with that reason.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

from ..autobin import AutoBinError
from ..autobin import receive_file as receive_autobin
from ..autobin import send_file as send_autobin
from ..yapp import YappError, receive_file, send_file, starts_download
from .events import MailChanged
from .operator import Notice, Severity

log = logging.getLogger(__name__)

#: How long after the operator sends `YAPP <name>` a YAPP send-init is
#: taken as the file they asked for (`watch_for_download`). WS1EC-2
#: answered in 3 s over the air (2026-10-03); a minute covers a slow path
#: without leaving a stale request armed.
DOWNLOAD_WAIT_SECONDS = 60.0
#: BPQMail's download command (`YAPP <name>`; LinBPQ `BBSUtilities.c`
#: matches its first four letters, any case).
YAPP_REQUEST = re.compile(r"^\s*YAPP\s+\S", re.IGNORECASE)
#: Why a link that cannot carry binary refuses a transfer.
NO_BINARY = ("File transfers are not supported over SSH: the server's telnet "
             "holds YAPP's replies.")


class Transfers:
    """File transfers on the core's sessions. Owned by `Core` as
    `core.transfers`."""

    def __init__(self, core) -> None:
        self.core = core
        #: Session keys a transfer (or a mail run's protocol exchange) is
        #: reading the bytes of.
        self.active: set[str] = set()
        self._tasks: set[asyncio.Task] = set()

    def _notice(self, text: str, severity: Severity = Severity.INFORMATION) -> None:
        self.core.operator.notice(Notice(text, severity))

    # ------------------------------------------------------------------
    # Session hooks
    # ------------------------------------------------------------------
    def intercept(self, key: str, data: bytes) -> bool:
        """`Sessions.data_interceptors`: True if `data` belongs to a
        transfer -- one running, or a requested download starting now."""
        if key in self.active:
            return True
        return self.watch_for_download(key, data)

    def yapp_requested(self, key: str, text: str, session) -> None:
        """`Sessions.sent_hooks`: `YAPP <name>` sent opens the download
        window -- not while a files run fetches it itself
        (`collect.BbsCollector._get_file`)."""
        if YAPP_REQUEST.match(text) and key not in self.active:
            session.download_until = time.monotonic() + DOWNLOAD_WAIT_SECONDS

    def watch_for_download(self, key: str, data: bytes) -> bool:
        """Start a requested YAPP download when its first bytes arrive:
        True if `data` began one."""
        session = self.core.sessions.get(key)
        if session is None or not session.download_until:
            return False
        if time.monotonic() > session.download_until:
            session.download_until = 0.0
            return False
        if not starts_download(data):
            return False
        session.download_until = 0.0
        self.active.add(key)
        task = asyncio.get_running_loop().create_task(self._receive_requested(key, bytes(data)))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def _receive_requested(self, key: str, initial: bytes) -> None:
        session = self.core.sessions.get(key)
        if session is None or session.link is None:
            self.active.discard(key)
            return

        def progress(name: str, done: int, size: int) -> None:
            self.core.set_activity(f"YAPP {name} {done}/{size}")

        await self.run(key, "YAPP", "download", receive_file(
            session.link, self.core.mail.downloads_dir(), initial=initial, progress=progress,
        ))

    # ------------------------------------------------------------------
    # Running one
    # ------------------------------------------------------------------
    async def run(self, key: str, protocol: str, mode: str, transfer) -> None:
        """Await one transfer on session `key` (already in `active`), then
        say how it went: a note in the transcript and one notice."""
        sessions = self.core.sessions
        sessions.note(key, f"{protocol} {mode} starting")
        self.core.set_activity(f"{protocol} {mode}")
        try:
            result = await transfer
        except (OSError, ValueError, YappError, AutoBinError) as exc:
            sessions.note(key, f"{protocol} {mode} failed: {exc}")
            self._notice(f"{protocol} {mode} failed: {exc}", Severity.WARNING)
        else:
            sessions.note(key, f"{protocol} {mode} complete: {result.path.name} ({result.size} bytes)")
            if mode == "upload":
                self._notice(f"{protocol} upload complete: {result.path.name}")
            else:
                self._notice(f"{protocol} download complete: {result.path.name}, "
                             "in {view:downloads}.")
                self.core.events.publish(MailChanged())
        finally:
            self.active.discard(key)
            self.core.set_activity("")

    def can_send(self, key: str) -> bool:
        """Whether session `key` can carry a transfer now: connected, able
        to carry binary, and not running one already."""
        session = self.core.sessions.get(key)
        return (session is not None and session.link is not None and session.link.connected
                and getattr(session.link, "carries_binary", True)
                and key not in self.active)

    def refusal(self, key: str) -> str:
        """Why session `key` cannot start a transfer, or "" if it can be
        asked to (connected, carries binary)."""
        session = self.core.sessions.get(key)
        if session is None or session.link is None or not session.link.connected:
            return "Connect before starting a file transfer."
        if not getattr(session.link, "carries_binary", True):
            return NO_BINARY + " Connect by radio to send a file."
        return ""

    async def start(self, key: str, protocol: str, mode: str, path) -> None:
        """One explicit transfer the operator chose: `protocol` "yapp" or
        "autobin", `mode` "upload" (of `path`) or "download". Arms the gate
        as a committed send."""
        session = self.core.sessions.get(key)
        if session is None or session.link is None:
            return
        if not self.core.gate.enabled:
            self.core.connector.arm_for(f"{protocol.upper()} {mode}")
        self.active.add(key)
        if protocol == "yapp":
            sender, receiver = send_file, receive_file
        else:
            sender, receiver = send_autobin, receive_autobin
        if mode == "upload":
            transfer = sender(session.link, path)
        else:
            transfer = receiver(session.link, self.core.mail.downloads_dir())
        await self.run(key, protocol.upper(), mode, transfer)

    def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
