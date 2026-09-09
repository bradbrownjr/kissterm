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

from .. import aprs_services
from ..aprs_contacts import Contact, build_message_body, canned_messages_for
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
                # Ctrl+R does the same thing. The button exists because the
                # whole point of the directory is discoverability, and a
                # feature reachable only by a key nobody has been told about
                # is not discoverable.
                yield Button("Templates", id="aprs-templates-button")
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
        """Repaint the table from `Config.aprs_contacts`, then append the
        shipped gateway services.

        Safe to call repeatedly -- same rule as
        `AddressBookPane.refresh_from`: correct the instant this pane becomes
        visible, not on the next tab switch.

        **The built-in rows are rendered from `kissterm/aprs_services/` and
        are never written into `Config.aprs_contacts`.** Copying them into
        the operator's config would freeze them at whatever this version
        shipped and make a corrected callsign or a new command permanent
        until they noticed and re-added it by hand. Keeping them out means
        they improve when kissterm updates and can never masquerade as
        something the operator typed.

        They sort after the saved contacts because seventeen services would
        otherwise bury the two or three people an operator actually messages.
        Anything in `Config.aprs_hidden_services` is skipped entirely; that
        is what Delete on a built-in row does.
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
        hidden = set(getattr(self.app.config, "aprs_hidden_services", ()))  # type: ignore[attr-defined]
        for service in aprs_services.load_all():
            if service.id in hidden:
                continue
            table.add_row(
                service.name,
                service.callsign,
                "built-in",
                "",
                # The description is the reason a built-in row is worth
                # having at all -- "MPAD" next to a blank cell would tell an
                # operator nothing they did not already not know.
                service.summary,
                key=f"service:{service.id}",
            )

    def _contacts(self) -> list[dict]:
        return self.app.config.aprs_contacts  # type: ignore[attr-defined]

    def _selected_key(self) -> str | None:
        table = self.query_one("#aprs-contact-table", DataTable)
        if table.row_count == 0 or table.cursor_coordinate is None:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:
            return None
        return None if row_key.value is None else str(row_key.value)

    def _selected_index(self) -> int | None:
        """The `Config.aprs_contacts` index under the cursor, or None.

        None also covers a built-in service row, whose key is `service:<id>`
        rather than a number -- built-ins are not stored in that list at all,
        so there is no index to give. Callers that care about the difference
        use `_selected_service_id` as well.
        """
        key = self._selected_key()
        if key is None or key.startswith("service:"):
            return None
        try:
            return int(key)
        except ValueError:
            return None

    def _selected_service_id(self) -> str | None:
        """The shipped-directory id under the cursor, or None for a saved
        contact."""
        key = self._selected_key()
        if key is None or not key.startswith("service:"):
            return None
        return key.split(":", 1)[1]

    @on(DataTable.RowSelected, "#aprs-contact-table")
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        key = None if event.row_key.value is None else str(event.row_key.value)
        if key is None:
            return
        if key.startswith("service:"):
            # A built-in behaves exactly like picking a contact: address it
            # and show whatever history exists. It is a real callsign you can
            # really message; the only thing it is not is editable.
            service = aprs_services.lookup(key.split(":", 1)[1])
            if service is None:
                return
            self.query_one("#aprs-to-input", Input).value = service.callsign
            self._show_conversation_for(
                service.callsign, f"{service.name} ({service.callsign})"
            )
            self.action_close_contacts()
            return
        try:
            index = int(key)
        except ValueError:
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
        service_id = self._selected_service_id()
        if service_id is not None:
            # A built-in cannot be edited in place -- it is shipped data, not
            # the operator's. Offering to save a copy is the useful move
            # instead of an error: the reason to "edit" SMSGTE is to attach
            # your own phone number to it, which is a new contact.
            self._copy_service_to_contact(service_id)
            return
        index = self._selected_index()
        if index is None:
            self.app.notify("Select a contact first.", severity="warning")  # type: ignore[attr-defined]
            return
        self._edit_contact(index)

    @work
    async def _copy_service_to_contact(self, service_id: str) -> None:
        """Open the contact editor prefilled from a shipped service, as a NEW
        contact. Never touches the built-in row itself."""
        from .dialogs import AprsContactScreen

        service = aprs_services.lookup(service_id)
        if service is None:
            return
        self.app.notify(  # type: ignore[attr-defined]
            f"{service.callsign} is built in and cannot be edited. "
            "Saving your own copy instead."
        )
        result = await self.app.push_screen_wait(  # type: ignore[attr-defined]
            AprsContactScreen(
                name=service.name,
                callsign=service.callsign,
                gateway=service.id,
                sms_gateway=getattr(self.app.config, "aprs_sms_gateway", ""),  # type: ignore[attr-defined]
                email_gateway=getattr(self.app.config, "aprs_email_gateway", ""),  # type: ignore[attr-defined]
            )
        )
        if result is None:
            return
        raw_contacts = self._contacts()
        raw_contacts.append(result.to_dict())
        self.app._save_config()  # type: ignore[attr-defined]
        self.refresh_from(raw_contacts)
        self.app.notify(f"Saved {result.name!r}.")  # type: ignore[attr-defined]

    @on(Button.Pressed, "#aprs-contact-edit")
    def _edit_pressed(self) -> None:
        self._edit_selected()

    def _forget_selected(self) -> None:
        service_id = self._selected_service_id()
        if service_id is not None:
            self._hide_service(service_id)
            return
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

    def _hide_service(self, service_id: str) -> None:
        """Delete on a built-in row hides it (`Config.aprs_hidden_services`).

        A built-in is not stored in `Config.aprs_contacts`, so there is
        nothing to delete; refusing outright would make the key look broken,
        and most operators will never use most of seventeen services. Hiding
        is the honest middle -- reversible by hand in `config.toml`, and the
        notification says so rather than leaving the row's disappearance
        looking permanent.
        """
        service = aprs_services.lookup(service_id)
        hidden = self.app.config.aprs_hidden_services  # type: ignore[attr-defined]
        if service_id not in hidden:
            hidden.append(service_id)
        self.app._save_config()  # type: ignore[attr-defined]
        self.refresh_from(self._contacts())
        name = service.name if service is not None else service_id
        self.app.notify(  # type: ignore[attr-defined]
            f"Hid {name}. Remove it from aprs_hidden_services in config.toml "
            "to get it back."
        )

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

    # -- templates -----------------------------------------------------------
    @on(Button.Pressed, "#aprs-templates-button")
    def _templates_pressed(self) -> None:
        self.show_templates()

    @work
    async def show_templates(self) -> None:
        """What to say to whoever is in "To:". `Ctrl+R`'s target on this pane.

        Scoped to the current addressee rather than showing all seventeen
        services at once: an operator composing to `WLNK-1` wants Winlink's
        commands, and making them pick the service again -- having already
        picked the contact -- is a step that exists only because the code
        found it convenient.

        **The result fills the compose box and is never sent.** See
        `AprsServiceScreen`'s docstring and AGENTS.md's completion rule. The
        text lands in the input exactly as `CommandReferenceScreen`'s pick
        lands in the terminal's send line, and goes out only when the
        operator commits it.
        """
        from .dialogs import AprsServiceScreen

        addressee = self.query_one("#aprs-to-input", Input).value.strip()
        contact = self._contact_for(addressee)
        # The contact's own `gateway` wins over a callsign match: an operator
        # who deliberately saved "this contact is WXBOT" is more
        # authoritative than the directory, and it also covers a gateway
        # reachable at a callsign the shipped table does not know.
        service = None
        if contact is not None and contact.gateway:
            service = aprs_services.lookup(contact.gateway)
        if service is None:
            service = aprs_services.lookup_callsign(addressee)
        saved = canned_messages_for(
            self.app.config.aprs_templates,  # type: ignore[attr-defined]
            service.id if service is not None else "",
        )
        chosen = await self.app.push_screen_wait(  # type: ignore[attr-defined]
            AprsServiceScreen(service, saved, addressee=addressee)
        )
        if not chosen:
            return
        field = self.query_one("#aprs-compose-input", Input)
        field.value = chosen
        field.focus()
        field.action_end()

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
