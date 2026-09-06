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

from dataclasses import dataclass

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Select, TextArea
from textual.widgets.option_list import Option

from ..addressbook import AddressBook
from ..ax25 import parse_path


@dataclass(frozen=True)
class ConnectRequest:
    """What the Connect dialog hands back: where to connect, and what to
    do once there.

    `hops` is a comma-separated chain of intermediate nodes to reach
    `target` node-to-node, for when no digipeater path does the job --
    almost always empty. `script`/`credential` are the two mutually
    exclusive ways to say what to send once the FULL chain (or the plain
    direct connect, if `hops` is empty) comes up: literal text, or the name
    of a saved credential looked up fresh at send time. See
    `KissTermApp.action_connect` and `_run_connect_script`.
    """

    target: str
    script: str = ""
    hops: str = ""
    credential: str = ""


def _validate_target_and_hops(text: str, hops: str) -> tuple[object | None, str]:
    """Parse `text` as a connect target, refusing to combine it with node
    hops. Returns `(path, "")` on success or `(None, message)` on failure --
    shared by `ConnectScreen` and `AddressBookEntryScreen`, which both offer
    the same two addressing mechanisms and must refuse the same conflict:
    a digipeater path repeats ONE frame at the link layer, node hops are a
    sequence of independent connects made minutes apart, and the two do not
    compose.
    """
    try:
        path = parse_path(text)
    except Exception as exc:
        return None, str(exc)
    if hops and path.repeaters:
        return None, "Can't combine a digipeater path (via ...) with node hops -- pick one."
    return path, ""


def _disable_while_credential_selected(select: Select, area: TextArea) -> None:
    """Disable, but never touch the text of, a login script box while a
    saved credential is selected next to it.

    Shared by `ConnectScreen` and `AddressBookEntryScreen`. Deliberately
    does not clear or overwrite `.text`: doing so on every dropdown change
    is how a credential's password ends up copied into the box and then
    silently saved as another station's "custom" script the next time the
    dropdown is reset to blank. Leaving the text alone and merely disabling
    the box means the two mechanisms cannot contaminate each other -- each
    screen's submit handler reads the box only when no credential is
    selected.
    """
    area.disabled = bool(select.value) and select.value is not Select.NULL


class ConnectScreen(ModalScreen[ConnectRequest | None]):
    """Ask for a connect target. Accepts ``CALL-SSID [via DIGI,DIGI]``.

    Carries an address book of stations already tried, because `WS1EC-15` and
    `WS1EC-7` are different services on one machine and a mistyped SSID fails
    in a way that looks exactly like a bad RF path. Typing filters the list;
    Down moves into it; Enter on a row connects; Delete forgets the row. The
    book is loaded here rather than passed in so the dialog works in a test
    with no app around it, and it is optional: pass `book=AddressBook(path)`
    to point it somewhere else.

    Also carries an optional per-station node-hop chain and login (a literal
    script or a saved credential) -- arrowing through the history previews
    everything saved for that entry, and whatever the fields hold when
    Connect fires travels back with the target and gets saved, blank or not.
    `credentials` is the raw `Config.credentials` list of `{"name", "text"}`
    dicts, for the "send once connected" dropdown; defaults to none, so the
    dialog still works in a test or a script with no config around it.
    """

    BINDINGS = [
        Binding("escape", "dismiss(None)", "Cancel"),
        Binding("down", "into_list", "History", show=False),
        Binding("delete", "forget", "Forget", show=False),
    ]

    def __init__(
        self,
        book: AddressBook | None = None,
        credentials: list[dict] | None = None,
    ) -> None:
        super().__init__()
        if book is None:
            book = AddressBook()
            book.load()
        self.book = book
        self.credentials = credentials or []

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-box"):
            yield Label("Connect to station", id="connect-title")
            yield Input(
                placeholder="WS1EC-7  or  WS1EC-7 via W1AW-1",
                id="connect-target",
            )
            yield Input(
                placeholder="N1QFY, AB1KI-15 (optional -- node hops, when no digipeater reaches it)",
                id="connect-hops",
            )
            yield Label("", id="connect-error")
            yield Label("Recent stations", id="connect-history-title")
            yield OptionList(id="connect-history")
            yield Label(
                "Down for previous stations - Enter connects - Delete forgets",
                id="connect-hint",
            )
            yield Label(
                "Send once connected (optional)",
                id="connect-script-title",
            )
            yield Select(
                [],
                id="connect-credential",
                allow_blank=True,
                prompt="(type your own below)",
            )
            yield TextArea(id="connect-script", tab_behavior="focus")
            with Horizontal(id="connect-buttons"):
                yield Button("Connect", variant="primary", id="connect-go")
                yield Button("Cancel", id="connect-cancel")

    def on_mount(self) -> None:
        self._render_history()
        self._render_credentials()
        self.query_one("#connect-target", Input).focus()

    def _render_credentials(self) -> None:
        select = self.query_one("#connect-credential", Select)
        select.set_options(
            (name, name)
            for c in self.credentials
            if (name := c.get("name"))
        )

    def _credential_text(self, name: str) -> str:
        for c in self.credentials:
            if c.get("name") == name:
                return str(c.get("text", ""))
        return ""

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
                f"{e.target}"
                f"{'  --  ' + e.summary if e.summary else ''}"
                f"{'  [via nodes]' if e.hops else ''}",
                id=e.target,
            )
            for e in matches
        ]
        history = self.query_one("#connect-history", OptionList)
        history.clear_options()
        history.add_options(options)
        history.display = bool(options)
        self.query_one("#connect-hint", Label).display = bool(options)
        self.query_one("#connect-history-title", Label).display = bool(options)

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

    @on(OptionList.OptionHighlighted, "#connect-history")
    def _preview_entry(self, event: OptionList.OptionHighlighted) -> None:
        """Arrowing through history previews everything saved for that
        station -- its node-hop chain and its login, script or credential.

        So picking a station also picks up how to reach it and what to say
        once there, without having to remember any of it separately. Still
        editable before Connect.
        """
        entry = None
        if event.option.id:
            entry = next(
                (e for e in self.book.entries if e.target == event.option.id), None
            )
        self.query_one("#connect-hops", Input).value = entry.hops if entry else ""
        self.query_one("#connect-script", TextArea).text = entry.script if entry else ""
        valid = {c.get("name") for c in self.credentials}
        credential = entry.credential if entry and entry.credential in valid else ""
        self.query_one("#connect-credential", Select).value = credential or Select.NULL
        self._apply_credential_state()

    @on(Select.Changed, "#connect-credential")
    def _credential_changed(self) -> None:
        self._apply_credential_state()

    def _apply_credential_state(self) -> None:
        _disable_while_credential_selected(
            self.query_one("#connect-credential", Select),
            self.query_one("#connect-script", TextArea),
        )

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
        hops = self.query_one("#connect-hops", Input).value.strip()
        _path, error = _validate_target_and_hops(text, hops)
        if error:
            self.query_one("#connect-error", Label).update(f"[red]{error}[/red]")
            return
        select_value = self.query_one("#connect-credential", Select).value
        credential = (
            str(select_value) if select_value and select_value is not Select.NULL else ""
        )
        # A credential, once selected, is authoritative -- the box next to
        # it is disabled (see `_apply_credential_state`) specifically so
        # its leftover text is never read here.
        script = "" if credential else self.query_one("#connect-script", TextArea).text
        # Recorded on the ATTEMPT, not on success: a connect that failed is
        # the one about to be retried, and withholding it until a UA arrives
        # would keep it out of the list at exactly the moment it is wanted.
        # Everything else travels the same way, blank or not -- a deliberate
        # blank clears a script/hop-chain/credential the operator no longer
        # wants.
        self.book.record_attempt(text, script, hops, credential)
        self.dismiss(ConnectRequest(text, script, hops, credential))


class AddressBookEntryScreen(ModalScreen[ConnectRequest | None]):
    """Add or hand-edit one address-book entry directly (Settings > Address
    Book), without attempting a live connect.

    Same fields and the same via/hops and credential/script rules as the
    lower half of `ConnectScreen` -- a station reached node-to-node, or one
    with a saved login, should be set up correctly once from Settings
    rather than the operator having to attempt (and possibly fail) a real
    connect just to create the entry. No history browsing here: the whole
    point of this screen is that a caller already knows which entry it is
    editing, or that it is a new one.
    """

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(
        self,
        target: str = "",
        script: str = "",
        hops: str = "",
        credential: str = "",
        credentials: list[dict] | None = None,
    ) -> None:
        super().__init__()
        self._target = target
        self._script = script
        self._hops = hops
        self._credential = credential
        self.credentials = credentials or []

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-box"):
            yield Label("Address book entry", id="connect-title")
            yield Input(
                value=self._target,
                placeholder="WS1EC-7  or  WS1EC-7 via W1AW-1",
                id="connect-target",
            )
            yield Input(
                value=self._hops,
                placeholder="N1QFY, AB1KI-15 (optional -- node hops, when no digipeater reaches it)",
                id="connect-hops",
            )
            yield Label("", id="connect-error")
            yield Label("Send once connected (optional)", id="connect-script-title")
            yield Select(
                [],
                id="connect-credential",
                allow_blank=True,
                prompt="(type your own below)",
            )
            yield TextArea(self._script, id="connect-script", tab_behavior="focus")
            with Horizontal(id="connect-buttons"):
                yield Button("Save", variant="primary", id="connect-go")
                yield Button("Cancel", id="connect-cancel")

    def on_mount(self) -> None:
        select = self.query_one("#connect-credential", Select)
        select.set_options((name, name) for c in self.credentials if (name := c.get("name")))
        valid = {c.get("name") for c in self.credentials}
        select.value = self._credential if self._credential in valid else Select.NULL
        self._apply_credential_state()
        field = self.query_one("#connect-target", Input)
        field.focus()
        field.action_end()

    @on(Select.Changed, "#connect-credential")
    def _credential_changed(self) -> None:
        self._apply_credential_state()

    def _apply_credential_state(self) -> None:
        _disable_while_credential_selected(
            self.query_one("#connect-credential", Select),
            self.query_one("#connect-script", TextArea),
        )

    @on(Button.Pressed, "#connect-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#connect-go")
    @on(Input.Submitted, "#connect-target")
    def _save(self) -> None:
        text = self.query_one("#connect-target", Input).value.strip()
        if not text:
            return
        hops = self.query_one("#connect-hops", Input).value.strip()
        _path, error = _validate_target_and_hops(text, hops)
        if error:
            self.query_one("#connect-error", Label).update(f"[red]{error}[/red]")
            return
        select_value = self.query_one("#connect-credential", Select).value
        credential = (
            str(select_value) if select_value and select_value is not Select.NULL else ""
        )
        script = "" if credential else self.query_one("#connect-script", TextArea).text
        self.dismiss(ConnectRequest(text, script, hops, credential))


@dataclass(frozen=True)
class Credential:
    """One saved login, as `CredentialScreen` hands it back."""

    name: str
    text: str


class CredentialScreen(ModalScreen[Credential | None]):
    """Add or edit one saved credential (Settings > Credentials).

    Kept deliberately simple -- a name and a block of text, nothing
    structured -- because packet BBS logins do not agree on a shape: some
    want a bare password, some want a real name and a password, some want a
    CBBS-style multi-field login. A named block of text sent one line at a
    time covers all of them without guessing a schema that will not fit the
    next BBS someone connects to.

    Saving here does not touch `config.toml` itself -- the caller
    (`SettingsPane`) folds the result into `Config.credentials` and saves
    the whole config, same as every other Settings field.
    """

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, name: str = "", text: str = "") -> None:
        super().__init__()
        self._name = name
        self._text = text

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-box"):
            yield Label("Saved credential", id="connect-title")
            yield Input(
                value=self._name,
                placeholder="Personal BBS login",
                id="credential-name",
            )
            yield Label("", id="credential-error")
            yield Label(
                "Text -- one or more lines, sent in order once referenced by a station",
                id="connect-script-title",
            )
            yield TextArea(self._text, id="credential-text", tab_behavior="focus")
            with Horizontal(id="connect-buttons"):
                yield Button("Save", variant="primary", id="credential-save")
                yield Button("Cancel", id="credential-cancel")

    def on_mount(self) -> None:
        field = self.query_one("#credential-name", Input)
        field.focus()
        field.action_end()

    @on(Button.Pressed, "#credential-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#credential-save")
    @on(Input.Submitted, "#credential-name")
    def _save(self) -> None:
        name = self.query_one("#credential-name", Input).value.strip()
        if not name:
            self.query_one("#credential-error", Label).update(
                "[red]Name this credential something -- it is how a station's "
                "Connect entry will find it.[/red]"
            )
            return
        text = self.query_one("#credential-text", TextArea).text
        self.dismiss(Credential(name, text))


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
