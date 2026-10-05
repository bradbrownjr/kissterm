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
import contextlib
from collections.abc import Callable
from typing import Any

from textual.app import App, ScreenStackError
from textual.screen import Screen

from ..core.operator import Notice, Question
from ..core.questions import (
    CallsignAsk,
    ChooseCategories,
    ChooseSessionTransport,
    HomeBbsRoute,
    InternetLoginAsk,
    LoginAsk,
    PickFiles,
    RadioReminder,
    TrustHostKey,
    WinlinkGateway,
)


def _radio_reminder(question: RadioReminder) -> Screen:
    from .dialogs import RadioReminderScreen

    return RadioReminderScreen(question.frequency, question.connection_type, question.note)


def _trust_host_key(question: TrustHostKey) -> Screen:
    from .dialogs import TrustHostKeyScreen

    return TrustHostKeyScreen(question)


def _home_bbs_route(q: HomeBbsRoute) -> Screen:
    from .dialogs import HomeBbsSetupScreen

    return HomeBbsSetupScreen(list(q.targets), missing=q.missing, all_note=q.all_note,
                              skip=q.skip)


def _winlink_gateway(q: WinlinkGateway) -> Screen:
    from .dialogs import WinlinkGatewayScreen

    return WinlinkGatewayScreen(list(q.contacts), q.favourite, gateway_list=q.gateway_list,
                                all_note=q.all_note, skip=q.skip)


def _login_ask(q: LoginAsk) -> Screen:
    from .dialogs import LoginAskScreen

    return LoginAskScreen(q.title, q.detail, q.name, secret=q.secret, all_note=q.all_note,
                          skip=q.skip, go_label=q.go_label, username=q.username,
                          where=q.where)


def _internet_login(q: InternetLoginAsk) -> Screen:
    from .dialogs import InternetLoginScreen

    return InternetLoginScreen(list(q.targets), q.current, missing=q.missing,
                               username=q.username, saved=q.saved, where=q.where,
                               all_note=q.all_note, skip=q.skip)


def _choose_categories(q: ChooseCategories) -> Screen:
    from .bulletin_screen import BulletinCategoriesScreen

    return BulletinCategoriesScreen(q.bbs, dict(q.counts), new_only=q.new_only)


def _pick_files(q: PickFiles) -> Screen:
    from .bbs_files_screen import BbsFilesScreen

    return BbsFilesScreen(q.bbs, list(q.files), have=dict(q.have))


def _callsign(q: CallsignAsk) -> Screen:
    from .dialogs import CallsignScreen

    return CallsignScreen(q.current)


def _session_transport(q: ChooseSessionTransport) -> Screen:
    from .dialogs import SessionTransportPickerScreen

    return SessionTransportPickerScreen(list(q.transports), q.active)


#: Question type -> a function building the screen that asks it. The
#: screen dismisses with the answer the question documents.
SCREENS: dict[type[Question], Callable[[Any], Screen]] = {
    RadioReminder: _radio_reminder,
    TrustHostKey: _trust_host_key,
    HomeBbsRoute: _home_bbs_route,
    WinlinkGateway: _winlink_gateway,
    LoginAsk: _login_ask,
    InternetLoginAsk: _internet_login,
    ChooseCategories: _choose_categories,
    PickFiles: _pick_files,
    CallsignAsk: _callsign,
    ChooseSessionTransport: _session_transport,
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
            # At shutdown the screen stack may already be gone; there is
            # then nothing left to take down.
            with contextlib.suppress(ScreenStackError):
                if self._app.screen is screen:
                    screen.dismiss(None)
            raise
        # dismiss() resolves the answer before Textual's queued screen
        # replacement paints. Yield once, so a fast nearby node cannot run
        # a whole connect while the dismissed question is still on screen.
        await asyncio.sleep(0)
        return result
