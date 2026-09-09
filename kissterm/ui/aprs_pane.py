"""The APRS pane: a contact list and a chat-style conversation view.

Requested directly: replicate, in a terminal, what KM6LYW's APRS WebChat does
in a browser -- a contact list separate from the station Address Book (an
APRS messaging contact is a person or gateway you message, not a node you
connect to -- see `kissterm/aprs_contacts.py`) and a conversation view per
contact.

APRS decoding itself does not live here -- it is wired into the shared frame
fan-out in `ui/app.py`'s `_on_aprs_frame`, the same way the monitor pane and
heard list are (AGENTS.md sec. 2b: never a second decode path). This module
only ever reads `self.app.config.aprs_contacts` and
`self.app.aprs_conversations`, and sends through `self.app.station.transport
.send_frame` -- the same transmit gate as everything else in this app.

**Contacts CRUD lands first, the conversation view and sending land next**
(this file is built in the same two-commit sequence the roadmap item was
scoped in): until then, selecting a contact shows its message history
read-only. No compose input exists yet, so nothing here can transmit.
"""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, RichLog, Static

from ..aprs_contacts import Contact


class _AprsContactTable(DataTable):
    """Insert/F2/Delete on the contacts table, same convention as
    `_AddressBookTable` -- bound on the table itself so Delete does not also
    fire while the operator is typing somewhere else in this pane.
    """

    BINDINGS = [
        Binding("insert", "new_contact", "New", show=False),
        Binding("f2", "edit_contact", "Edit", show=False),
        Binding("delete", "forget_contact", "Forget", show=False),
    ]

    def action_new_contact(self) -> None:
        self.app.query_one(AprsPane)._new_contact()  # type: ignore[attr-defined]

    def action_edit_contact(self) -> None:
        self.app.query_one(AprsPane)._edit_selected()  # type: ignore[attr-defined]

    def action_forget_contact(self) -> None:
        self.app.query_one(AprsPane)._forget_selected()  # type: ignore[attr-defined]


class AprsPane(Horizontal):
    """Contacts on the left, the selected contact's conversation on the right."""

    def compose(self) -> ComposeResult:
        with Vertical(id="aprs-contacts-column"):
            yield Static("APRS messaging contacts.", classes="addressbook-note")
            yield _AprsContactTable(id="aprs-contact-table", cursor_type="row", zebra_stripes=True)
            with Horizontal(classes="addressbook-actions"):
                yield Button("New", id="aprs-contact-new")
                yield Button("Edit selected", id="aprs-contact-edit")
                yield Button("Forget selected", id="aprs-contact-forget")
            yield Static(
                "Insert: new -- F2: edit selected -- Delete: forget selected",
                classes="addressbook-hint",
            )
        with Vertical(id="aprs-conversation-column"):
            yield Static("Select a contact to see its message history.", id="aprs-conversation-title")
            yield RichLog(id="aprs-conversation-log", wrap=True, markup=False)

    def on_mount(self) -> None:
        self.refresh_from(self.app.config.aprs_contacts)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    def refresh_from(self, raw_contacts: list[dict]) -> None:
        """Repaint the table from `Config.aprs_contacts`. Safe to call
        repeatedly -- same rule as `AddressBookPane.refresh_from`: correct
        the instant this pane becomes visible, not on the next tab switch.
        """
        table = self.query_one("#aprs-contact-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Name", "Callsign", "Service", "Detail", "Notes")
        for index, raw in enumerate(raw_contacts):
            contact = Contact.from_dict(raw)
            table.add_row(
                contact.name,
                contact.callsign,
                contact.service,
                contact.detail,
                contact.notes,
                key=str(index),
            )

    def _contacts(self) -> list[dict]:
        return self.app.config.aprs_contacts  # type: ignore[attr-defined]

    def _selected_index(self) -> int | None:
        table = self.query_one("#aprs-contact-table", DataTable)
        if table.row_count == 0 or table.cursor_coordinate is None:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:
            return None
        return int(row_key.value) if row_key.value is not None else None

    @on(DataTable.RowSelected, "#aprs-contact-table")
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        index = int(event.row_key.value) if event.row_key.value is not None else None
        if index is None:
            return
        self._show_conversation(index)

    def _show_conversation(self, index: int) -> None:
        raw_contacts = self._contacts()
        if index < 0 or index >= len(raw_contacts):
            return
        contact = Contact.from_dict(raw_contacts[index])
        self.query_one("#aprs-conversation-title", Static).update(
            f"{contact.name} ({contact.callsign})"
        )
        log = self.query_one("#aprs-conversation-log", RichLog)
        log.clear()
        store = self.app.aprs_conversations  # type: ignore[attr-defined]
        convo = store.conversations.get(contact.callsign)
        if convo is None or not convo.messages:
            log.write("(no messages yet)")
            return
        for entry in convo.messages:
            arrow = "<" if entry.direction == "in" else ">"
            ack = " (acked)" if entry.direction == "out" and entry.acked else ""
            log.write(f"{arrow} {entry.text}{ack}")

    # -- new / edit / forget -------------------------------------------------
    def _new_contact(self) -> None:
        self._edit_contact(None)

    @on(Button.Pressed, "#aprs-contact-new")
    def _new_pressed(self) -> None:
        self._new_contact()

    def _edit_selected(self) -> None:
        index = self._selected_index()
        if index is None:
            self.app.notify("Select a contact first.", severity="warning")  # type: ignore[attr-defined]
            return
        self._edit_contact(index)

    @on(Button.Pressed, "#aprs-contact-edit")
    def _edit_pressed(self) -> None:
        self._edit_selected()

    def _forget_selected(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        raw_contacts = self._contacts()
        if index < 0 or index >= len(raw_contacts):
            return
        removed = raw_contacts.pop(index)
        self.app._save_config()  # type: ignore[attr-defined]
        self.refresh_from(raw_contacts)
        self.app.notify(f"Forgot {removed.get('name', '(unnamed)')!r}.")  # type: ignore[attr-defined]

    @on(Button.Pressed, "#aprs-contact-forget")
    def _forget_pressed(self) -> None:
        self._forget_selected()

    @work
    async def _edit_contact(self, index: int | None) -> None:
        from .dialogs import AprsContactScreen

        raw_contacts = self._contacts()
        existing = Contact.from_dict(raw_contacts[index]) if index is not None else None
        result = await self.app.push_screen_wait(  # type: ignore[attr-defined]
            AprsContactScreen(
                name=existing.name if existing else "",
                callsign=existing.callsign if existing else "",
                service=existing.service if existing else "station",
                detail=existing.detail if existing else "",
                notes=existing.notes if existing else "",
            )
        )
        if result is None:
            return
        if index is not None:
            raw_contacts[index] = result.to_dict()
        else:
            raw_contacts.append(result.to_dict())
        self.app._save_config()  # type: ignore[attr-defined]
        self.refresh_from(raw_contacts)
        self.app.notify(f"Saved {result.name!r}.")  # type: ignore[attr-defined]
