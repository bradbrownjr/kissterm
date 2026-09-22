"""The F10 menu bar and the F1 help screen.

The menu is the CUA pull-down menu (Turbo Vision, Midnight Commander): a bar
of headings across the top row, one open at a time, each listing its
commands with their keys. It exists so that a command does not need a key of
its own to be reachable -- which is what let the key budget shrink to the
terminal-safe set in `commands.py`. It is generated from `commands.COMMANDS`,
so nothing can be in the menu under one name and in the Footer under another.

Keys inside the menu: Left/Right change heading, Up/Down move, Enter runs,
the highlighted letter runs that entry directly, Esc or F10 closes. Letters
are handled in `on_key`, not as `BINDINGS`, because a plain-letter binding is
exactly what the key standard forbids outside a focused list.

A command that cannot run right now (Disconnect with nothing connected) is
listed dimmed with the reason in place of its key, rather than hidden: the
menu is also where an operator learns what exists.

Neither screen transmits or changes anything itself. The menu returns the
chosen `Command`; `KissTermApp.run_command` runs it exactly as its key would.
"""

from __future__ import annotations

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, OptionList, Static
from textual.widgets.option_list import Option

from .commands import Command, key_label

#: (command, reason it cannot run now, or "" if it can)
MenuEntry = tuple[Command, str]


class _MenuTitle(Static):
    """One heading in the menu bar; a click opens it."""

    def __init__(self, index: int, title: str) -> None:
        super().__init__(title, classes="menu-title")
        self.index = index

    def on_click(self) -> None:
        self.screen.open_group(self.index)  # type: ignore[attr-defined]


def _entry_text(command: Command, reason: str, width: int) -> Text:
    label = Text(command.label)
    pos = command.label.upper().find(command.mnemonic)
    right = reason or key_label(command.key, short=False)
    if reason:
        label.stylize("dim")
    elif pos >= 0:
        label.stylize("bold underline", pos, pos + 1)
    pad = max(width - len(command.label) - len(right), 2)
    text = Text.assemble(label, " " * pad, Text(right, style="dim" if not reason else "dim italic"))
    return text


class MenuScreen(ModalScreen[Command | None]):
    DEFAULT_CSS = """
    MenuScreen {
        align: left top;
        background: $background 40%;
    }
    MenuScreen #menu-bar {
        height: 1;
        width: 100%;
        background: $panel;
    }
    MenuScreen .menu-title {
        width: auto;
        padding: 0 1;
    }
    MenuScreen .menu-title.-open {
        background: $accent;
        color: $background;
        text-style: bold;
    }
    MenuScreen #menu-drop {
        width: auto;
        height: auto;
        border: round $accent;
        background: $surface;
    }
    MenuScreen #menu-items {
        border: none;
        height: auto;
        max-height: 20;
        background: $surface;
        padding: 0;
    }
    MenuScreen #menu-hint {
        color: $text-muted;
        height: auto;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss(None)", "Close"),
        Binding("f10", "dismiss(None)", "Close"),
        Binding("left", "step(-1)", "Previous", show=False),
        Binding("right", "step(1)", "Next", show=False),
    ]

    def __init__(self, groups: list[tuple[str, list[MenuEntry]]], start: int = 0) -> None:
        super().__init__()
        self.groups = groups
        self.current = start

    def compose(self) -> ComposeResult:
        with Horizontal(id="menu-bar"):
            for i, (title, _entries) in enumerate(self.groups):
                yield _MenuTitle(i, title)
        with Vertical(id="menu-drop"):
            yield OptionList(id="menu-items")
            yield Static(id="menu-hint")
        yield Footer()

    def on_mount(self) -> None:
        self.open_group(self.current)

    def _entries(self) -> list[MenuEntry]:
        return self.groups[self.current][1]

    def open_group(self, index: int) -> None:
        self.current = index % len(self.groups)
        for title in self.query(_MenuTitle):
            title.set_class(title.index == self.current, "-open")
        entries = self._entries()
        width = max(
            (
                len(c.label) + len(reason or key_label(c.key, short=False)) + 4
                for c, reason in entries
            ),
            default=20,
        )
        items = self.query_one("#menu-items", OptionList)
        items.clear_options()
        items.add_options(
            Option(_entry_text(c, reason, width), id=str(i), disabled=bool(reason))
            for i, (c, reason) in enumerate(entries)
        )
        items.styles.width = width + 2
        self.query_one("#menu-hint", Static).styles.width = width + 2
        first = next((i for i, (_c, reason) in enumerate(entries) if not reason), None)
        items.highlighted = first
        items.focus()
        self._show_hint(first)
        self.call_after_refresh(self._place_drop)

    def _place_drop(self) -> None:
        """Hang the list under its heading, as a pull-down menu does."""
        for title in self.query(_MenuTitle):
            if title.index == self.current:
                self.query_one("#menu-drop").styles.offset = (title.region.x, 0)

    def _show_hint(self, index: int | None) -> None:
        hint = self._entries()[index][0].help if index is not None else ""
        self.query_one("#menu-hint", Static).update(Text(hint, overflow="fold"))

    def action_step(self, delta: int) -> None:
        self.open_group(self.current + delta)

    @on(OptionList.OptionHighlighted)
    def _highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self._show_hint(event.option_index)

    @on(OptionList.OptionSelected)
    def _selected(self, event: OptionList.OptionSelected) -> None:
        command, reason = self._entries()[event.option_index]
        if not reason:
            self.dismiss(command)

    def on_key(self, event: events.Key) -> None:
        char = event.character or ""
        if len(char) != 1 or not char.isalpha():
            return
        for command, reason in self._entries():
            if command.mnemonic == char.upper():
                event.stop()
                if reason:
                    self.app.bell()
                else:
                    self.dismiss(command)
                return


class HelpScreen(ModalScreen[None]):
    """F1: what this tab is for and every key that works on it."""

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
        background: $background 60%;
    }
    HelpScreen #help-body {
        width: 90;
        max-width: 100%;
        height: auto;
        max-height: 90%;
        border: round $accent;
        border-title-color: $accent;
        background: $surface;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss(None)", "Close"),
        Binding("f1", "dismiss(None)", "Close"),
    ]

    def __init__(self, body) -> None:
        super().__init__()
        self.body = body

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-body") as scroll:
            scroll.border_title = "Help"
            yield Static(self.body)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#help-body").focus()
