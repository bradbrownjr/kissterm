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
`self.app.aprs_conversations`; the actual encode-and-transmit step is
`KissTermApp._send_aprs_message` -- the shared primitive a fresh send and a
retry both call, so "what does it mean to send an APRS message" has exactly
one answer, gated by the same transmit switch as everything else in this app.

**Sending, ack, and retry.** `self._pending` (`aprs_conversations.
PendingAcks`) tracks outgoing messages awaiting an ack, in memory only --
see that module's docstring for why. A periodic timer
(`_check_retries`) reconciles it against `self.app.aprs_conversations`
(an ack arriving is `_on_aprs_frame`'s job, over on the frame fan-out; this
pane only notices the flag it leaves behind) and resends anything still due.
The "To:" field is independent of the contacts table on purpose: typing a
bare callsign there sends to someone not in the contact list at all, the
same way the Connect dialog and the Address Book coexist -- a contact is a
convenience, not a requirement, for messaging someone.

**The contacts table is a Ctrl+G slide-out, docked on the right, not a
permanent column.** The conversation view is what an operator is actually
looking at while messaging someone; the contact list is a lookup, summoned
with `KissTermApp.action_toggle_contacts` (dispatched here to
`toggle_contacts`) the same way the Terminal pane's Address Book is -- see
`DESIGN.md`'s "slide-out panels" section for the shared recipe. Picking a
row closes the panel again (`_row_selected`), since choosing a contact and
then still having the list covering the screen is not what "select a
contact" was for.
"""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, RichLog, Static

from ..aprs_contacts import Contact, build_message_body
from ..aprs_conversations import PendingAcks

#: How often the retry timer checks for a due, un-acked message. Independent
#: of `PendingAcks.retry_seconds` (how long a single message waits before
#: its own first/next retry) -- this is just the polling granularity.
_RETRY_CHECK_INTERVAL = 10.0


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
    """The conversation view, plus a Ctrl+G contacts slide-out on the right."""

    BINDINGS = [
        Binding("escape", "close_contacts", show=False),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._pending = PendingAcks()
        #: Wraps well inside the spec's 1-5 alphanumeric characters; a
        #: fresh number each send, reused by nothing until it wraps.
        self._next_msg_number = 1

    def compose(self) -> ComposeResult:
        # Conversation first -- this is the main, always-visible column.
        # Contacts is the slide-out, hidden by default; see `toggle_contacts`.
        with Vertical(id="aprs-conversation-column"):
            yield Static("Select a contact to see its message history.", id="aprs-conversation-title")
            yield RichLog(id="aprs-conversation-log", wrap=True, markup=False)
            with Horizontal(id="aprs-compose-row"):
                yield Input(placeholder="To (callsign)", id="aprs-to-input")
                yield Input(placeholder="Message", id="aprs-compose-input")
                yield Button("Send", variant="primary", id="aprs-send-button")
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

    def on_mount(self) -> None:
        self.refresh_from(self.app.config.aprs_contacts)  # type: ignore[attr-defined]
        self.query_one("#aprs-contacts-column").display = False
        self.set_interval(_RETRY_CHECK_INTERVAL, self._check_retries)

    # -- contacts slide-out ---------------------------------------------------
    def toggle_contacts(self) -> None:
        """Show or hide the contacts column. `Ctrl+G`'s target on this pane,
        dispatched from `KissTermApp.action_toggle_contacts`. Opening
        repaints from `Config.aprs_contacts` (same "correct the instant it
        becomes visible" reasoning as `TerminalPane.toggle_addressbook` --
        this column stays composed-but-hidden rather than being torn down
        and rebuilt, so nothing else repaints it once the pane has mounted)
        and focuses the table; closing (here or via Escape) returns focus to
        the compose field.
        """
        column = self.query_one("#aprs-contacts-column")
        column.display = not column.display
        if column.display:
            self.refresh_from(self.app.config.aprs_contacts)  # type: ignore[attr-defined]
            self.query_one("#aprs-contact-table", DataTable).focus()
        else:
            self.query_one("#aprs-compose-input", Input).focus()

    def action_close_contacts(self) -> None:
        """Escape. A no-op if the column is already hidden, so binding it at
        the pane level never disturbs a plain Escape typed for some other
        reason (e.g. inside a modal opened over this pane)."""
        column = self.query_one("#aprs-contacts-column")
        if column.display:
            column.display = False
            self.query_one("#aprs-compose-input", Input).focus()

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
        raw_contacts = self._contacts()
        if index < 0 or index >= len(raw_contacts):
            return
        contact = Contact.from_dict(raw_contacts[index])
        self.query_one("#aprs-to-input", Input).value = contact.callsign
        self._show_conversation(index)
        # Picking a contact closes the panel -- the conversation just loaded
        # is what the operator wants to look at next, not a panel still
        # covering part of the screen.
        self.action_close_contacts()

    def _show_conversation(self, index: int) -> None:
        raw_contacts = self._contacts()
        if index < 0 or index >= len(raw_contacts):
            return
        contact = Contact.from_dict(raw_contacts[index])
        self._show_conversation_for(contact.callsign, f"{contact.name} ({contact.callsign})")

    def _show_conversation_for(self, callsign: str, title: str) -> None:
        """Repaint the conversation log for `callsign` -- the shared render
        step for a contact-row selection AND a bare "To:" callsign that
        matches no saved contact at all."""
        callsign = callsign.strip().upper()
        self.query_one("#aprs-conversation-title", Static).update(title)
        log = self.query_one("#aprs-conversation-log", RichLog)
        log.clear()
        store = self.app.aprs_conversations  # type: ignore[attr-defined]
        convo = store.conversations.get(callsign)
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
                gateway=existing.gateway if existing else "",
                sms_gateway=getattr(self.app.config, "aprs_sms_gateway", ""),  # type: ignore[attr-defined]
                email_gateway=getattr(self.app.config, "aprs_email_gateway", ""),  # type: ignore[attr-defined]
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

    # -- sending, ack, retry -------------------------------------------------
    def _next_number(self) -> str:
        number = str(self._next_msg_number)
        self._next_msg_number = self._next_msg_number % 99999 + 1
        return number

    def _contact_for(self, callsign: str) -> Contact | None:
        """The saved contact whose `callsign` matches, or `None` for a bare
        "To:" target that matches no saved contact at all -- messaging
        someone not in the contact list always behaves like "station"
        service (plain text, no template), the only thing that makes sense
        for a contact this pane knows nothing else about."""
        callsign = callsign.strip().upper()
        for raw in self._contacts():
            if str(raw.get("callsign", "")).strip().upper() == callsign:
                return Contact.from_dict(raw)
        return None

    @on(Button.Pressed, "#aprs-send-button")
    @on(Input.Submitted, "#aprs-compose-input")
    def _send_pressed(self) -> None:
        self._send_compose()

    @work
    async def _send_compose(self) -> None:
        addressee = self.query_one("#aprs-to-input", Input).value.strip()
        text_field = self.query_one("#aprs-compose-input", Input)
        text = text_field.value.strip()
        if not addressee:
            self.app.notify("Type a callsign to send to.", severity="warning")  # type: ignore[attr-defined]
            return
        if not text:
            return
        contact = self._contact_for(addressee)
        service = contact.service if contact else "station"
        detail = contact.detail if contact else ""
        config = self.app.config  # type: ignore[attr-defined]
        wire_text = build_message_body(
            service,
            detail,
            text,
            sms_template=getattr(config, "aprs_sms_template", ""),
            email_template=getattr(config, "aprs_email_template", ""),
        )
        number = self._next_number()
        ok = await self.app._send_aprs_message(addressee, wire_text, number)  # type: ignore[attr-defined]
        if not ok:
            self.app.notify(  # type: ignore[attr-defined]
                "Message not sent -- transmit is disabled (Ctrl+T).", severity="warning"
            )
            return
        # The conversation log keeps what the operator actually typed, not
        # the templated wire body -- readable history, not a wire dump.
        # A retry, though, must resend the exact bytes that went out the
        # first time, so `_pending` tracks `wire_text`, not `text`.
        self.app.aprs_conversations.record_outgoing(  # type: ignore[attr-defined]
            addressee, text, number=number, service=service
        )
        self._pending.add(addressee, number, wire_text)
        text_field.value = ""
        self._show_conversation_for(addressee, addressee)

    def _check_retries(self) -> None:
        self._retry_worker()

    @work
    async def _retry_worker(self) -> None:
        store = self.app.aprs_conversations  # type: ignore[attr-defined]
        self._pending.discard_acked(store)
        for callsign, number, text in self._pending.due():
            await self.app._send_aprs_message(  # type: ignore[attr-defined]
                callsign, text, number, retry=True
            )
