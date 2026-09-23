"""The Address Book pane: every saved station, dial straight from the list.

Pulled out of Settings into its own main tab because it turned out to be
used far more often than a one-time setup screen -- an operator picking a
station to call is a routine, frequent action, not a configuration change.
Settings is where you decide how kissterm behaves; this is where you decide
who to talk to next, which is why it sits at F5 (Settings moved to F6 to
make room) rather than buried in a settings tab.

Two things this pane is built around:

**It is one list, shared with the Connect dialog's history.** Both read and
write the same `KissTermApp.addressbook`. An entry created or fixed here
shows up in Ctrl+N's history immediately, and an attempt recorded from
Ctrl+N shows up here on the next repaint -- there is exactly one address
book, never a second copy to keep in sync.

**Dialing here still goes through the whole connect flow, unabridged.**
Pressing Enter or "Connect" calls `KissTermApp.action_connect(prefill=...)`,
which arms the transmit gate, checks the transport is actually open, and
runs the full node-hop chain and login exactly as if the operator had typed
the target into Ctrl+N -- this pane is a faster way to reach that flow, not
a second, cheaper way to transmit.
"""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Static


class _AddressBookTable(DataTable):
    """The table itself, with `syncterm`-style dialing-directory keys:
    Enter connects (its own default `select_cursor` binding, handled as
    `DataTable.RowSelected`), Insert adds, E edits, Delete forgets.
    A plain letter is safe here because it is bound on the table, which
    has no text entry; F2 would have shadowed the Terminal tab key.

    Bound on the table widget itself, not the pane -- Textual only offers a
    binding at the App or Screen level otherwise, and a Delete bound that
    broadly would also fire while an operator is typing anywhere else. This
    way the binding is only ever considered while this exact table has
    focus, the same reasoning `ConnectScreen` uses for its own Delete key.
    """

    BINDINGS = [
        Binding("enter", "select_cursor", "Connect"),
        Binding("insert", "new_entry", "New"),
        Binding("e", "edit_entry", "Edit"),
        Binding("delete", "forget_entry", "Forget"),
    ]

    def action_new_entry(self) -> None:
        self.app.query_one(AddressBookPane)._new_entry()  # type: ignore[attr-defined]

    def action_edit_entry(self) -> None:
        self.app.query_one(AddressBookPane)._edit_selected()  # type: ignore[attr-defined]

    def action_forget_entry(self) -> None:
        self.app.query_one(AddressBookPane)._forget_selected()  # type: ignore[attr-defined]


class _KnownNodesTable(DataTable):
    """Passive NET/ROM claims; selecting a row never dials it."""


class AddressBookPane(Vertical):
    """Every station in `KissTermApp.addressbook`: dial, add, edit, forget."""

    _known_nodes_visible = True

    def compose(self) -> ComposeResult:
        # No note line above the table and no key-hint line below the
        # buttons: `_AddressBookTable.BINDINGS` are already registered with
        # `show=False` and Textual's own Footer is the context-aware
        # shortcut bar for them (AGENTS.md: "A widget's own BINDINGS with
        # show=True ARE the context-aware shortcut bar" -- a second, static
        # copy of the same keys here is the duplication that rule already
        # argues against). Dropping both Statics also puts this pane's
        # button row at the same vertical position as the Terminal pane's
        # input-and-Send row, requested directly for visual symmetry
        # between the two side-by-side panes.
        yield _AddressBookTable(id="addressbook-table", cursor_type="row", zebra_stripes=True)
        with Horizontal(classes="addressbook-actions"):
            yield Button("Connect", variant="primary", id="addressbook-connect")
            yield Button("New", id="addressbook-new")
            yield Button("Edit", id="addressbook-edit")
            yield Button("Forget", id="addressbook-forget")
        yield Static("Known NET/ROM nodes — unverified received claims", id="known-nodes-note")
        yield _KnownNodesTable(id="known-nodes-table", cursor_type="row", zebra_stripes=True)
        with Horizontal(classes="addressbook-actions"):
            yield Button("Use node", id="known-nodes-use")

    def on_mount(self) -> None:
        self.refresh_from(self.app.addressbook)  # type: ignore[attr-defined]
        self.refresh_known_nodes(self.app.known_nodes)  # type: ignore[attr-defined]

    def refresh_known_nodes(self, known_nodes) -> None:
        table = self.query_one("#known-nodes-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Claimed node", "Alias", "Via", "Quality", "Broadcast by")
        for node in known_nodes.entries():
            table.add_row(node.callsign, node.alias, node.via, str(node.quality), node.broadcaster, key=node.callsign)

    def set_known_nodes_visible(self, visible: bool) -> bool:
        """Set visibility of the passive NET/ROM-claim section.

        The address book is the deliberate dialing directory; received
        NET/ROM claims are useful supporting context but can take too much
        vertical room on a short terminal.  Keep their visibility independent
        of the Address Book slide-out so Ctrl+G always means just that.

        Returns the resulting visibility so the caller can report it.
        """
        self._known_nodes_visible = visible
        for widget_id in (
            "#known-nodes-note",
            "#known-nodes-table",
            "#known-nodes-use",
        ):
            self.query_one(widget_id).display = self._known_nodes_visible
        if not self._known_nodes_visible:
            # Do not leave focus in a hidden table; keyboard navigation should
            # return to the permanent directory immediately.
            self.query_one("#addressbook-table", DataTable).focus()
        return self._known_nodes_visible

    def toggle_known_nodes(self) -> bool:
        """Invert the NET/ROM-claim section's current visibility."""
        return self.set_known_nodes_visible(not self._known_nodes_visible)

    def _use_claimed_node(self) -> None:
        table = self.query_one("#known-nodes-table", DataTable)
        if table.row_count == 0 or table.cursor_coordinate is None:
            self.app.notify("Select a claimed node first.", severity="warning")  # type: ignore[attr-defined]
            return
        row_key, _column_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        # A received callsign is an untrusted claim, so offer it only in the
        # existing deliberate Connect dialog. It must never land in a live
        # session's send line, where a later Enter could transmit it as text.
        self.app.action_connect(target=str(row_key.value))  # type: ignore[attr-defined]

    @on(Button.Pressed, "#known-nodes-use")
    def _use_claimed_node_pressed(self) -> None:
        self._use_claimed_node()

    def refresh_from(self, book) -> None:
        """Repaint the table from `book`. Safe to call repeatedly -- the
        same rule as `HeardPane.refresh_from` and `SettingsPane.render_
        settings`: a pane must be correct the instant it becomes visible,
        not on the next unrelated event."""
        table = self.query_one("#addressbook-table", DataTable)
        table.clear(columns=True)
        table.add_columns(
            "Target", "Hops", "Frequency", "Connection", "Paclen", "Window", "Login",
            "Attempts", "Connects",
        )
        for entry in book.entries:
            if entry.credential:
                login = f"credential: {entry.credential}"
            elif entry.script_name:
                login = f"script: {entry.script_name}"
            elif entry.script:
                first_line = entry.script.splitlines()[0]
                login = first_line + ("..." if "\n" in entry.script else "")
            else:
                login = ""
            table.add_row(
                entry.target,
                entry.hops,
                entry.frequency,
                entry.connection_type,
                entry.paclen,
                entry.window,
                login,
                str(entry.attempts),
                str(entry.connects),
                key=entry.target,
            )

    # ------------------------------------------------------------------
    def _selected_target(self) -> str | None:
        table = self.query_one("#addressbook-table", DataTable)
        if table.row_count == 0 or table.cursor_coordinate is None:
            return None
        try:
            row_key, _column_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:
            return None
        return str(row_key.value) if row_key.value is not None else None

    def _selected_entry(self):
        target = self._selected_target()
        if target is None:
            return None
        return self.app.addressbook.find(target)  # type: ignore[attr-defined]

    # -- dial --------------------------------------------------------------
    def _connect_selected(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            self.app.notify("Select a station first.", severity="warning")  # type: ignore[attr-defined]
            return
        self.app.action_connect(prefill=entry)  # type: ignore[attr-defined]

    @on(Button.Pressed, "#addressbook-connect")
    def _connect_pressed(self) -> None:
        self._connect_selected()

    @on(DataTable.RowSelected, "#addressbook-table")
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        # Enter on a row -- DataTable's own default binding fires this.
        target = str(event.row_key.value) if event.row_key.value is not None else None
        if target is None:
            return
        entry = self.app.addressbook.find(target)  # type: ignore[attr-defined]
        if entry is not None:
            self.app.action_connect(prefill=entry)  # type: ignore[attr-defined]

    # -- new / edit / forget -------------------------------------------------
    def _new_entry(self) -> None:
        self._edit_entry(None)

    @on(Button.Pressed, "#addressbook-new")
    def _new_pressed(self) -> None:
        self._new_entry()

    def _edit_selected(self) -> None:
        target = self._selected_target()
        if target is None:
            self.app.notify("Select a station first.", severity="warning")  # type: ignore[attr-defined]
            return
        self._edit_entry(target)

    @on(Button.Pressed, "#addressbook-edit")
    def _edit_pressed(self) -> None:
        self._edit_selected()

    def _forget_selected(self) -> None:
        target = self._selected_target()
        if target is None:
            return
        book = self.app.addressbook  # type: ignore[attr-defined]
        if book.forget(target):
            self.refresh_from(book)

    @on(Button.Pressed, "#addressbook-forget")
    def _forget_pressed(self) -> None:
        self._forget_selected()

    @work
    async def _edit_entry(self, target: str | None) -> None:
        from .dialogs import AddressBookEntryScreen

        book = self.app.addressbook  # type: ignore[attr-defined]
        entry = book.find(target) if target else None
        config = self.app.config  # type: ignore[attr-defined]
        result = await self.app.push_screen_wait(  # type: ignore[attr-defined]
            AddressBookEntryScreen(
                target=entry.target if entry else "",
                script=entry.script if entry else "",
                hops=entry.hops if entry else "",
                credential=entry.credential if entry else "",
                script_name=entry.script_name if entry else "",
                frequency=entry.frequency if entry else "",
                connection_type=entry.connection_type if entry else "",
                paclen=entry.paclen if entry else "",
                window=entry.window if entry else "",
                note=entry.note if entry else "",
                credentials=config.credentials,
                scripts=config.scripts,
                transports=config.transports,
            )
        )
        if result is None:
            return
        book.upsert(
            result.target,
            script=result.script,
            hops=result.hops,
            credential=result.credential,
            script_name=result.script_name,
            frequency=result.frequency,
            connection_type=result.connection_type,
            paclen=result.paclen,
            window=result.window,
            note=result.note,
            original_target=target or "",
        )
        self.refresh_from(book)
