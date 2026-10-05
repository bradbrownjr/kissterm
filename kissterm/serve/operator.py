"""The `Operator` port (`core/operator.py`) answered by remote clients.

**`RemoteOperator`** sends every notice and question to every connected
client (docs/PROTOCOL.md 3.3, 3.4). **The first answer wins**; the other
clients are told the question closed. Headless (`kissterm --serve`), a
question asked with nobody connected, or left open when the last client
goes, is cancelled -- an answer of None, and a cancelled flow transmits
nothing. Nobody to ask is never a yes.

**`FanOutOperator`** is the terminal UI and the remote clients together
(the server running inside the terminal UI): a notice goes to both, a
question is put to both and the first to answer wins, the other's
question taken down. There the terminal is always present to answer, so
the remote side waits instead of cancelling when no client is connected.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
from typing import Any

from ..core.operator import Notice
from ..core.questions import Question
from . import wire

log = logging.getLogger(__name__)


class RemoteOperator:
    """Notices and questions for every client of `server` (`RemoteServer`).

    `standalone`: no other front end answers, so a question nobody can
    answer is cancelled (headless). False inside the terminal UI.
    """

    def __init__(self, server, *, standalone: bool = True) -> None:
        self.server = server
        self.standalone = standalone
        #: Open questions: id -> (question, future), in the order asked.
        self.pending: dict[str, tuple[Question, asyncio.Future]] = {}
        self._ids = itertools.count(1)

    def notice(self, notice: Notice) -> None:
        log.info("notice: %s", wire.notice(notice)["text"])
        self.server.broadcast(wire.notice(notice))

    async def ask(self, question: Question) -> Any | None:
        if self.standalone and not self.server.has_clients():
            log.info("%s cancelled: no client connected", type(question).__name__)
            return None
        qid = f"q{next(self._ids)}"
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self.pending[qid] = (question, future)
        self.server.broadcast(wire.question(qid, question))
        try:
            return await future
        finally:
            self.pending.pop(qid, None)
            # Answered here, cancelled, or won by the terminal: every client
            # takes its copy down.
            self.server.broadcast({"type": "question_closed", "id": qid})

    def open_questions(self) -> list[dict]:
        """The questions still waiting, for a client that just connected."""
        return [wire.question(qid, question) for qid, (question, _f) in self.pending.items()]

    def answer(self, qid: str, value: Any) -> None:
        """A client's answer. An unknown or already-answered id is ignored
        (another client won); a malformed one raises `wire.BadAnswer` and
        leaves the question open."""
        entry = self.pending.get(qid)
        if entry is None:
            return
        question, future = entry
        result = wire.answer(question, value)
        if not future.done():
            future.set_result(result)

    def cancel_all(self) -> None:
        """Cancel every open question (headless: the last client left)."""
        for _question, future in list(self.pending.values()):
            if not future.done():
                future.set_result(None)


class FanOutOperator:
    """The terminal UI (`local`) and the remote clients (`remote`) as one
    operator. See the module docstring."""

    def __init__(self, local: Operator, remote: RemoteOperator) -> None:
        self.local = local
        self.remote = remote

    def notice(self, notice: Notice) -> None:
        self.local.notice(notice)
        self.remote.notice(notice)

    async def ask(self, question: Question) -> Any | None:
        tasks = [asyncio.ensure_future(self.local.ask(question)),
                 asyncio.ensure_future(self.remote.ask(question))]
        try:
            done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        return next(iter(done)).result()
