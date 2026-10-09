"""The one toolbar every place on the phone and browser uses (DESIGN.md 8a).

**The title row carries the buttons, the tabs get the row under it** (operator,
2026-10-09: "move all the icons into the same row as the section title to give
the tabs more space"). **One set per place, no floating buttons** (operator, 2026-10-08: "3 or 4
competing interface designs ... we really need to settle on a design
scheme"). On the left, the place's tabs if it has any; on the right its
secondary actions, then its **primary action last**, always a filled button
with a word on it ("Connect", "Write", "New").

**Width decides the labels** (operator, 2026-10-08): from `shell.WIDE` up
(a desktop browser) every action carries its word, so someone new to packet
radio is never left guessing at an icon; on a phone in portrait **none does**
(operator, 2026-10-09: words crowded the tabs, "difficult to navigate between
tabs"): icons only, the primary filled, each with a tooltip. The tooltip is also the
action's accessible name, so a test or a screen reader reaches it the same
way at either width.

**The transmit chip ends every row** (operator, 2026-10-08: it pushed the
whole page down in the top bar): a place's primary action sits just before
it, and the chip is always in the same corner.

**A page over the list takes the title bar** with a `Toolbar` of its own,
swapped into `appbar.actions` (`MailView._use`), as an open mail message
does: Delete, Save as text, the replies, Reply last; the list's goes back
when it closes. Swapped, not repainted in place: repainting the list's own
buttons with the reader's was never drawn by the page.

An action is data (`Action`); the buttons are drawn from it by `paint`, which
the shell calls again when the width crosses `WIDE`. Hide one by setting
`visible` and painting. Nothing here sends anything: an action only calls
the handler it was given, and a handler that transmits asks first.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import flet as ft


@dataclass
class Action:
    """One thing a place can do. `icon` is an icon name, or an `ft.Icon` the
    owner animates (Mail's turning sync). `tooltip` defaults to `label`."""

    icon: object
    label: str
    on_click: Callable[..., Awaitable[None]]
    primary: bool = False
    visible: bool = True
    tooltip: str = ""


class Toolbar:
    def __init__(self, app, *, tabs: ft.Control | None = None, register: bool = True,
                 gate: bool = True) -> None:
        self.app = app
        #: The transmit chip, last in the row (a reader's page has none).
        make = getattr(app, "gate_chip", None)
        self.gate = make() if gate and make else None
        self.actions: list[Action] = []
        #: The place's tab bar, given the room the buttons leave.
        self.tabs = tabs
        #: Only the place's tabs, under the title; the buttons are in the app
        #: bar beside it (`bar`, `ClientApp.go`).
        self.row = ft.Row(spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.buttons = ft.Row(spacing=4, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        #: A place's toolbar lives as long as the app and is repainted at a
        #: width change; one made per page (a reader) is not kept, since
        #: nothing would ever drop it again.
        registry = getattr(app, "toolbars", None)
        if register and registry is not None:
            registry.append(self)
        #: What the app bar carries at the right of the title: the actions,
        #: then the transmit chip (which stays when a page hides the actions).
        self.bar = [self.buttons] + ([self.gate] if self.gate else [])
        self.paint()

    def close(self) -> None:
        """Forget a toolbar made for one page (an open message): its
        repaints and its transmit chip, which the app would paint forever."""
        registry = getattr(self.app, "toolbars", None)
        if registry is not None and self in registry:
            registry.remove(self)
        chips = getattr(self.app, "gate_chips", None)
        if chips is not None and self.gate is not None:
            chips[:] = [c for c in chips if c is not self.gate]

    def show(self, on: bool) -> None:
        """Hide the actions while a page over the place's list (a message
        being read, a thread) has its own; the transmit chip stays."""
        self.buttons.visible = on

    def set(self, actions: list[Action]) -> None:
        self.actions = actions
        self.paint()

    @property
    def wide(self) -> bool:
        return bool(getattr(self.app, "wide", False))

    def paint(self) -> None:
        shown = [a for a in self.actions if a.visible]
        # The primary is last whatever order it was given in.
        shown.sort(key=lambda a: a.primary)
        self.buttons.controls = [self._button(a) for a in shown]
        if self.tabs is not None:
            self.tabs.expand = True
        self.row.controls = [self.tabs] if self.tabs is not None else []

    def _button(self, action: Action) -> ft.Control:
        tip = action.tooltip or action.label
        if self.wide:
            if action.primary:
                return ft.FilledButton(content=action.label, icon=action.icon, tooltip=tip,
                                       on_click=action.on_click)
            return ft.TextButton(content=action.label, icon=action.icon, tooltip=tip,
                                 on_click=action.on_click)
        # Named on a wrapper: beside other icon buttons Flutter's own tooltip
        # label was left out of the page's accessibility tree, so a screen
        # reader (and the screenshot script) found nothing to call it by.
        # The app bar tints its actions' icons; the primary names its colours.
        look = dict(bgcolor=ft.Colors.PRIMARY, icon_color=ft.Colors.ON_PRIMARY) \
            if action.primary else {}
        button = ft.FilledIconButton if action.primary else ft.IconButton
        return ft.Semantics(label=tip, container=True, content=button(
            icon=action.icon, tooltip=tip, on_click=action.on_click, **look))
