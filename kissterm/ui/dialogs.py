"""Modal screens layered on top of the app.

`ConnectScreen` is the only one that exists today, but it is pulled out into
its own module rather than left inline in `app.py` because it will not stay
the only one -- a "confirm disconnect", a transport picker, or a settings
editor (roadmap P6) are all `ModalScreen`s, and each one is a small, mostly
self-contained unit that a future editor should be able to add or change
without touching `app.py`'s bindings or fan-out wiring at all. Add new
modals here.
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList
from textual.widgets.option_list import Option

from ..addressbook import AddressBook
from ..ax25 import parse_path


class ConnectScreen(ModalScreen[str | None]):
    """Ask for a connect target. Accepts ``CALL-SSID [via DIGI,DIGI]``.

    Carries an address book of stations already tried, because `WS1EC-15` and
    `WS1EC-7` are different services on one machine and a mistyped SSID fails
    in a way that looks exactly like a bad RF path. Typing filters the list;
    Down moves into it; Enter on a row connects; Delete forgets the row. The
    book is loaded here rather than passed in so the dialog works in a test
    with no app around it, and it is optional: pass `book=AddressBook(path)`
    to point it somewhere else.
    """

    BINDINGS = [
        Binding("escape", "dismiss(None)", "Cancel"),
        Binding("down", "into_list", "History", show=False),
        Binding("delete", "forget", "Forget", show=False),
    ]

    def __init__(self, book: AddressBook | None = None) -> None:
        super().__init__()
        if book is None:
            book = AddressBook()
            book.load()
        self.book = book

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-box"):
            yield Label("Connect to station", id="connect-title")
            yield Input(
                placeholder="WS1EC-7  or  WS1EC-7 via W1AW-1",
                id="connect-target",
            )
            yield Label("", id="connect-error")
            yield OptionList(id="connect-history")
            yield Label(
                "Down for previous stations - Enter connects - Delete forgets",
                id="connect-hint",
            )
            with Horizontal(id="connect-buttons"):
                yield Button("Connect", variant="primary", id="connect-go")
                yield Button("Cancel", id="connect-cancel")

    def on_mount(self) -> None:
        self._render_history()
        self.query_one("#connect-target", Input).focus()

    # -- the address book -------------------------------------------------
    def _render_history(self, filter_text: str = "") -> None:
        """Repaint the list, narrowed to entries matching `filter_text`.

        The filter is a plain case-insensitive substring on the whole typed
        target, so "ws1" narrows to one machine's services and "via" finds
        the paths that need a digipeater.
        """
        needle = filter_text.strip().upper()
        matches = [e for e in self.book.entries if needle in e.target.upper()]
        options = [
            Option(
                f"{e.target}{'  --  ' + e.summary if e.summary else ''}",
                id=e.target,
            )
            for e in matches
        ]
        history = self.query_one("#connect-history", OptionList)
        history.clear_options()
        history.add_options(options)
        history.display = bool(options)
        self.query_one("#connect-hint", Label).display = bool(options)

    def action_into_list(self) -> None:
        history = self.query_one("#connect-history", OptionList)
        if not (history.display and history.option_count):
            return
        history.focus()
        if history.highlighted is None:
            # Focus alone leaves nothing highlighted, so the first Delete or
            # Enter after arrowing down would do nothing at all -- the key
            # appears dead rather than doing something the operator can see.
            history.highlighted = 0

    def action_forget(self) -> None:
        """Delete the highlighted row. Only meaningful with the list focused,
        so a Delete keypress while editing the target text still edits text."""
        history = self.query_one("#connect-history", OptionList)
        if not history.has_focus or history.highlighted is None:
            return
        option = history.get_option_at_index(history.highlighted)
        if option.id and self.book.forget(option.id):
            self._render_history(self.query_one("#connect-target", Input).value)
            if not self.book.entries:
                self.query_one("#connect-target", Input).focus()

    @on(OptionList.OptionSelected, "#connect-history")
    def _pick(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self._submit(event.option.id)

    @on(Input.Changed, "#connect-target")
    def _filter(self, event: Input.Changed) -> None:
        self._render_history(event.value)

    # -- connect / cancel -------------------------------------------------
    @on(Button.Pressed, "#connect-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#connect-go")
    @on(Input.Submitted, "#connect-target")
    def _go(self) -> None:
        self._submit(self.query_one("#connect-target", Input).value)

    def _submit(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        try:
            parse_path(text)
        except Exception as exc:
            self.query_one("#connect-error", Label).update(f"[red]{exc}[/red]")
            return
        # Recorded on the ATTEMPT, not on success: a connect that failed is
        # the one about to be retried, and withholding it until a UA arrives
        # would keep it out of the list at exactly the moment it is wanted.
        self.book.record_attempt(text)
        self.dismiss(text)


class CallsignScreen(ModalScreen[str | None]):
    """Change the station callsign without leaving the app.

    This exists because operators change callsign far more often than the
    "set it once at install time" model assumes: a `-1` SSID for a personal
    mailbox, a different SSID for portable or emergency-net operation, a club
    call for an event, a fresh SSID after someone else claimed the one you were
    using on the same channel. Before this dialog the only route was
    `kissterm --setup`, which re-runs the whole first-run wizard -- including a
    multi-second LAN sweep and transport re-selection -- to change one string.

    Validation is `AX25Address.parse`, the same function the wire encoder uses,
    so anything this dialog accepts is guaranteed encodable into an address
    field. Rejecting here is much better than discovering it at SABM time.
    """

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, current: str = "") -> None:
        super().__init__()
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-box"):
            yield Label("Station callsign", id="connect-title")
            yield Input(
                value=self._current,
                placeholder="N1ABC-1",
                id="callsign-value",
            )
            yield Label(
                "Saved to config.toml and used for the next connection.",
                id="callsign-hint",
            )
            yield Label("", id="callsign-error")
            with Horizontal(id="connect-buttons"):
                yield Button("Save", variant="primary", id="callsign-save")
                yield Button("Cancel", id="callsign-cancel")

    def on_mount(self) -> None:
        field = self.query_one("#callsign-value", Input)
        field.focus()
        # Cursor to the end, so backspacing an SSID off the current call is
        # one keystroke away -- the most common edit by far is N1ABC-1 to
        # N1ABC-9, not typing a whole new callsign.
        field.action_end()

    @on(Button.Pressed, "#callsign-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#callsign-save")
    @on(Input.Submitted, "#callsign-value")
    def _save(self) -> None:
        text = self.query_one("#callsign-value", Input).value.strip().upper()
        if not text:
            return
        from ..ax25 import AX25Address

        try:
            AX25Address.parse(text)
        except Exception as exc:
            self.query_one("#callsign-error", Label).update(f"[red]{exc}[/red]")
            return
        self.dismiss(text)


class CommandReferenceScreen(ModalScreen[str | None]):
    """The shipped command reference for the node we are talking to.

    Exists because asking the node itself is expensive: at 1200 baud
    half-duplex, a couple of kilobytes of help text is roughly twenty seconds
    during which nobody else on the frequency can transmit, and eight kilobytes
    is over a minute. A reference that ships with the app costs nothing and is
    available before the first byte is exchanged.

    Selecting a command **fills the input line and does not send it**. The
    operator still commits deliberately -- see `TerminalPane.send_line`, which
    is the only path to the air.
    """

    BINDINGS = [Binding("escape", "dismiss(None)", "Close")]

    def __init__(self, reference, detected: str = "") -> None:
        super().__init__()
        self._reference = reference
        self._detected = detected

    def compose(self) -> ComposeResult:
        from textual.widgets import DataTable, Static

        with Vertical(id="ref-box"):
            yield Label(self._title(), id="ref-title")
            yield Static(self._note(), id="ref-note")
            yield Input(placeholder="search commands", id="ref-search")
            yield DataTable(id="ref-table", cursor_type="row", zebra_stripes=True)
            yield Static(
                "Enter puts a command in the input line. It is not sent until "
                "you press Enter there or click Send.",
                id="ref-help",
            )
            with Horizontal(id="connect-buttons"):
                yield Button("Close", id="ref-close")

    def _title(self) -> str:
        family = self._reference.family
        return f"Commands -- {family.name}" if family else "Commands -- unknown node"

    def _note(self) -> str:
        family = self._reference.family
        if family is None:
            return (
                "The node has not been identified from its banner or prompt, so "
                "this list may not apply. Nothing has been asked of the node -- "
                "that would cost airtime."
            )
        parts = [family.note.replace("\n", " ").strip()]
        if family.confidence == "recalled":
            parts.append(
                "This reference is unverified; check a command before spending "
                "airtime on it."
            )
        return " ".join(p for p in parts if p)

    def on_mount(self) -> None:
        from textual.widgets import DataTable

        table = self.query_one("#ref-table", DataTable)
        table.add_columns("Command", "Usage", "What it does", "Source")
        self._populate("")
        self.query_one("#ref-search", Input).focus()

    def _populate(self, needle: str) -> None:
        from textual.widgets import DataTable

        table = self.query_one("#ref-table", DataTable)
        table.clear()
        for command in self._reference.find(needle):
            names = command.name
            if command.aliases:
                names += " / " + " / ".join(command.aliases)
            table.add_row(
                names,
                command.usage or command.name,
                command.summary,
                # Say where each line came from. A reference that silently
                # mixes documented fact with half-remembered syntax is worse
                # than none: the operator types it, at 1200 baud, and finds out.
                command.confidence,
                key=command.name,
            )

    @on(Input.Changed, "#ref-search")
    def _search(self, event: Input.Changed) -> None:
        self._populate(event.value)

    @on(Button.Pressed, "#ref-close")
    def _close(self) -> None:
        self.dismiss(None)

    def on_data_table_row_selected(self, event) -> None:
        """Hand the command back to the app, which fills the input line."""
        self.dismiss(str(event.row_key.value or ""))
