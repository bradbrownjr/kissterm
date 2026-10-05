"""The terminal UI's side of the core's `Operator` port
(`kissterm/core/operator.py`).

A notice becomes a toast, with the same words, severity and timeout the
app's own `notify` calls used before the flow moved into the core, so the
move is invisible to the operator. A question becomes the modal screen
registered for its type in `SCREENS`, awaited with `push_screen_wait`; a
question with no screen registered is declined (None), which a core flow
treats as cancelled -- nothing transmitted.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textual.app import App
from textual.screen import Screen

from ..core.operator import Notice, Question

#: Question type -> a function building the screen that asks it. The
#: screen dismisses with the answer the question documents.
SCREENS: dict[type[Question], Callable[[Question], Screen]] = {}


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
        build = SCREENS.get(type(question))
        if build is None:
            return None
        return await self._app.push_screen_wait(build(question))
