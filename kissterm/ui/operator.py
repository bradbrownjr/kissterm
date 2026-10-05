"""The terminal UI's side of the core's `Operator` port
(`kissterm/core/operator.py`).

A notice becomes a toast, with the same words, severity and timeout the
app's own `notify` calls used before the flow moved into the core, so the
move is invisible to the operator. A question becomes the modal screen
registered for its type in `SCREENS`, awaited until dismissed; a
question with no screen registered is declined (None), which a core flow
treats as cancelled -- nothing transmitted.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from textual.app import App
from textual.screen import Screen

from ..core.operator import Notice, Question
from ..core.questions import RadioReminder, TrustHostKey


def _radio_reminder(question: RadioReminder) -> Screen:
    from .dialogs import RadioReminderScreen

    return RadioReminderScreen(question.frequency, question.connection_type, question.note)


def _trust_host_key(question: TrustHostKey) -> Screen:
    from .dialogs import TrustHostKeyScreen

    return TrustHostKeyScreen(question)


#: Question type -> a function building the screen that asks it. The
#: screen dismisses with the answer the question documents.
SCREENS: dict[type[Question], Callable[[Any], Screen]] = {
    RadioReminder: _radio_reminder,
    TrustHostKey: _trust_host_key,
}


class TextualOperator:
    """`Operator` for `KissTermApp`."""

    def __init__(self, app: App) -> None:
        self._app = app

    def notice(self, notice: Notice) -> None:
        self._app.notify(
            notice.text,
            title=notice.title,
            severity=str(notice.severity),  # type: ignore[arg-type]
            timeout=notice.timeout,
        )

    async def ask(self, question: Question) -> Any | None:
        """Push the question's screen and wait for it to be dismissed.

        A callback rather than `push_screen_wait`, which works only inside
        a worker: a core flow is an ordinary task. If the flow is
        cancelled while the question is up (Ctrl+D during an SSH trust
        question), the screen goes down with it.
        """
        build = SCREENS.get(type(question))
        if build is None:
            return None
        answer: asyncio.Future = asyncio.get_running_loop().create_future()
        screen = build(question)
        self._app.push_screen(
            screen, lambda result: answer.done() or answer.set_result(result))
        try:
            result = await answer
        except asyncio.CancelledError:
            if self._app.screen is screen:
                screen.dismiss(None)
            raise
        # dismiss() resolves the answer before Textual's queued screen
        # replacement paints. Yield once, so a fast nearby node cannot run
        # a whole connect while the dismissed question is still on screen.
        await asyncio.sleep(0)
        return result
