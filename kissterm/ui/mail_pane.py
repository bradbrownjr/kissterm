"""The Mail, Bulletins and Files tabs: one folder tree, list and reader.

ROADMAP P2 asks for one widget with a column spec rather than three that
would drift apart, so `MessageBrowser` is all three tabs, told which part of
the store (`kissterm/mail/`) it shows:

    +-----------------+------------------------------------------+
    | All Inboxes (2) |  From     Subject                 Date   |
    | BBS             |> KC1JMH   Net tonight             09-23  |
    |   Inbox (2)     +------------------------------------------+
    |   Outbox        |  From: KC1JMH   To: WS1EC                |
    |   Sent          |  Subject: Net tonight                    |
    |   Deleted       |                                          |
    | Winlink ...     |  Hello                                   |
    +-----------------+------------------------------------------+

The folder tree replaces a sub-tab strip. Keys follow DESIGN.md section 5
rule 4, bound on the list itself so they work only while it has focus and
never while typing: Enter opens, Delete moves to Deleted, U restores from
Deleted, and on the Mail tab G gets mail from the Home BBS
(`KissTermApp.action_get_mail`). Each key is shown only where it works
(`MessageList.check_action`). Compose (Insert) and reply are added when
they exist, not before.

Message text came off the air: the reader shows it through
`monitor.sanitize` as plain `Text`, never as markup. The Files tab lists
files, not messages, and never opens or runs one.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Tree

from ..mail import MessageStore
from ..mail.store import ALL_INBOXES, DELETED, FILES, check_folder, is_deleted_folder
from ..monitor import sanitize
from . import slideouts
from .wraplog import WrapLog

#: Inbox, Outbox, Sent first and Deleted last, as every mail client orders
#: them; anything else (a bulletin category) sorts by name in between.
_RANK = {"Inbox": 0, "Outbox": 0.1, "Sent": 0.2, DELETED: 2}

#: How much of a file the Files tab previews.
_PREVIEW_BYTES = 16 * 1024


def _short_date(value: datetime | None) -> str:
    return value.astimezone().strftime("%m-%d %H:%M") if value else ""


class FolderTree(Tree):
    """The folder tree. Each node's data is a folder path or `ALL_INBOXES`.

    G works here as on the list, so it is in the Footer whichever of the
    two has focus.
    """

    BINDINGS = [
        Binding("insert", "new_message", "New"),
        Binding("g", "get_mail", "Send/Receive"),
    ]

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if action in ("get_mail", "new_message"):
            return self.query_ancestor(MessageBrowser).id == "mail-browser"
        return True

    def action_get_mail(self) -> None:
        self.app.action_get_mail()  # type: ignore[attr-defined]

    def action_new_message(self) -> None:
        self.app.action_compose_mail()  # type: ignore[attr-defined]


class MessageList(DataTable):
    """The message (or file) list, with the tab's context keys."""

    BINDINGS = [
        Binding("enter", "open_message", "Open"),
        Binding("insert", "new_message", "New"),
        Binding("r", "reply", "Reply"),
        Binding("q", "reply_quoted", "Reply quoted"),
        Binding("delete", "delete_message", "Delete"),
        Binding("u", "restore_message", "Restore"),
        Binding("g", "get_mail", "Send/Receive"),
    ]

    def _browser(self) -> "MessageBrowser":
        return self.query_ancestor(MessageBrowser)

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        browser = self._browser()
        if action == "open_message":
            return self.row_count > 0
        if action == "delete_message":
            return self.row_count > 0 and browser.can_delete()
        if action == "restore_message":
            return self.row_count > 0 and browser.can_restore()
        if action in ("get_mail", "new_message"):
            return browser.id == "mail-browser"
        if action in ("reply", "reply_quoted"):
            return self.row_count > 0 and not browser.files
        return True

    def action_new_message(self) -> None:
        self.app.action_compose_mail()  # type: ignore[attr-defined]

    def action_reply(self) -> None:
        ref = self._browser().selected_ref()
        if ref:
            self.app.action_compose_mail(ref, quoted=None)  # type: ignore[attr-defined]

    def action_reply_quoted(self) -> None:
        ref = self._browser().selected_ref()
        if ref:
            self.app.action_compose_mail(ref, quoted=True)  # type: ignore[attr-defined]

    async def _on_click(self, event: events.Click) -> None:
        """A click on a row opens it in the reader, as Enter does.

        `DataTable` only moves the cursor on the first click (it selects on
        a second click of the same row), so a message clicked once stayed
        unread in the list with the reader empty (2026-09-25). Clicking to
        read transmits nothing, so a single click is enough here; the
        Address Book, where Enter dials, keeps the two-step behaviour.
        """
        await super()._on_click(event)
        meta = event.style.meta
        if meta.get("row", -1) >= 0 and self.row_count:
            self._browser().open_selected()

    def action_open_message(self) -> None:
        self._browser().open_selected()

    def action_delete_message(self) -> None:
        self._browser().delete_selected()

    def action_restore_message(self) -> None:
        self._browser().restore_selected()

    def action_get_mail(self) -> None:
        self.app.action_get_mail()  # type: ignore[attr-defined]


class MessageBrowser(Horizontal):
    """Tree, list and reader over one part of the message store.

    Ctrl+G slides the Address Book in on the right, as on Terminal, so a
    BBS can be picked and dialed from here (operator, 2026-09-25). Its
    `AddressBookPane` is mounted the first time it is opened, not at
    launch: the Terminal's stays the app's first, and three idle copies
    would cost a table rebuild each for nothing. It never opens by itself
    here -- the message list needs the width more than a list of stations
    nobody asked for.

    `roots` are the top-level store folders shown (`("Mail",)`); their
    children become the tree's top level. `all_inboxes` adds the combined
    view at the top. `files` switches the list to files instead of messages.
    """

    BINDINGS = [Binding("escape", "close_addressbook", "Close", show=False)]

    def __init__(
        self,
        store: MessageStore,
        roots: tuple[str, ...],
        *,
        all_inboxes: bool = False,
        files: bool = False,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id, classes="message-browser")
        self.store = store
        self.roots = roots
        self.all_inboxes = all_inboxes
        self.files = files
        #: The folder shown in the list: a store path or `ALL_INBOXES`.
        self.folder: str = ""
        #: Row key -> message ref (or file path relative to the store root).
        self._rows: list[str] = []

    def compose(self) -> ComposeResult:
        tree = FolderTree("folders", classes="mail-tree")
        tree.show_root = False
        tree.guide_depth = 2
        yield tree
        with Vertical(classes="mail-right"):
            yield MessageList(cursor_type="row", zebra_stripes=True, classes="mail-list")
            yield WrapLog(classes="mail-reader", wrap=True, markup=False, highlight=False)
        yield Vertical(classes="mail-addressbook-column")

    def on_mount(self) -> None:
        column = self.query_one(".mail-addressbook-column")
        self._slideout = slideouts.SlideOut(column, self.query_one(".mail-right"))
        column.display = False
        self.reload()

    def on_resize(self) -> None:
        # Split what is right of the folder tree, not the whole tab: the
        # tree keeps its width and the list and reader give way, down to
        # the slide-out replacing them on a narrow screen (`slideouts.split`).
        # `allowed=False`: never opens by itself on this tab (see above).
        tree = self.query_one(".mail-tree").outer_size.width
        self._slideout.resized(max(self.size.width - tree, 0), allowed=False)

    # -- the Address Book slide-out ------------------------------------------

    def toggle_addressbook(self) -> None:
        """Ctrl+G on this tab, from `KissTermApp.action_toggle_contacts`."""
        from .addressbook_pane import AddressBookPane

        column = self.query_one(".mail-addressbook-column")
        opened = self._slideout.toggle()
        if not opened:
            self.query_one(MessageList).focus()
            return
        panes = column.query(AddressBookPane)
        if panes:
            self._show_addressbook(panes.first())
        else:
            self.call_later(self._mount_addressbook, column, AddressBookPane())

    async def _mount_addressbook(self, column, pane) -> None:
        await column.mount(pane)
        self._show_addressbook(pane)

    def _show_addressbook(self, pane) -> None:
        # Stations only: the passive NET/ROM claims stay on the Terminal
        # tab, where they are used to build hops.
        pane.set_known_nodes_visible(False)
        pane.refresh_from(self.app.addressbook)  # type: ignore[attr-defined]
        pane.query_one("#addressbook-table").focus()

    def close_addressbook(self, *, refocus: bool = True) -> bool:
        """Close the slide-out if it is open; returns whether it was.

        A dial passes `refocus=False`: focus in this tab's list would pull
        the Mail tab back over Terminal (`KissTermApp.action_show_tab`).
        """
        if self._slideout.close_by_hand():
            if refocus:
                self.query_one(MessageList).focus()
            return True
        return False

    def action_close_addressbook(self) -> None:
        self.close_addressbook()

    # -- tree ---------------------------------------------------------------

    def _visible_folders(self) -> list[str]:
        """This tab's folders, parents first, mailboxes in working order."""
        folders = [
            f
            for f in self.store.folders()
            if any(f.startswith(r + "/") for r in self.roots)
        ]
        return sorted(folders, key=lambda f: [(_RANK.get(p, 1), p.casefold()) for p in f.split("/")])

    def _label(self, folder: str, name: str) -> str:
        if self.files:
            return name
        unread = (
            sum(1 for s in self.store.list_inboxes() if not s.is_read)
            if folder == ALL_INBOXES
            else self.store.unread_count(folder)
        )
        return f"{name} ({unread})" if unread else name

    def reload(self) -> None:
        """Rebuild the tree and list from the store (cheap: the index caches)."""
        self.store.refresh()
        tree = self.query_one(FolderTree)
        tree.clear()
        nodes: dict[str, object] = {}
        first = ""
        if self.all_inboxes:
            tree.root.add_leaf(self._label(ALL_INBOXES, ALL_INBOXES), data=ALL_INBOXES)
            first = ALL_INBOXES
        folders = self._visible_folders()
        children = {f.rsplit("/", 1)[0] for f in folders}
        for folder in folders:
            parent_path, name = folder.rsplit("/", 1)
            parent = nodes.get(parent_path, tree.root)
            if folder in children:
                node = parent.add(self._label(folder, name), data=folder, expand=True)
            else:
                node = parent.add_leaf(self._label(folder, name), data=folder)
            nodes[folder] = node
            if not first and folder not in children:
                first = folder
        if self.folder not in nodes and self.folder != ALL_INBOXES:
            self.folder = first
        self._select_tree_node()
        self.show_folder(self.folder)

    def _select_tree_node(self) -> None:
        tree = self.query_one(FolderTree)

        def walk(node):
            for child in node.children:
                if child.data == self.folder:
                    return child
                found = walk(child)
                if found is not None:
                    return found
            return None

        node = walk(tree.root)
        if node is not None:
            tree.move_cursor(node)

    @on(Tree.NodeHighlighted)
    def _on_folder_highlighted(self, event: Tree.NodeHighlighted) -> None:
        event.stop()
        data = event.node.data
        if data and data != self.folder:
            self.show_folder(data)

    # -- list ---------------------------------------------------------------

    def show_folder(self, folder: str) -> None:
        self.folder = folder
        table = self.query_one(MessageList)
        table.clear(columns=True)
        self._rows = []
        self.query_one(WrapLog).clear()
        if not folder:
            return
        if self.files:
            table.add_columns("Name", "Size", "Modified")
            for path in self._files_in(folder):
                stat = path.stat()
                table.add_row(
                    path.name,
                    f"{stat.st_size:,}",
                    datetime.fromtimestamp(stat.st_mtime).strftime("%m-%d %H:%M"),
                )
                self._rows.append(path.relative_to(self.store.root).as_posix())
            return
        combined = folder == ALL_INBOXES
        columns = ["", "From", "Subject", "Date"]
        if combined:
            columns.append("Via")
        table.add_columns(*columns)
        items = self.store.list_inboxes() if combined else self.store.list(folder)
        for s in items:
            mark = "" if s.is_read else "*"
            subject = Text(s.subject or "(no subject)", style="" if s.is_read else "bold")
            row = [mark, s.sender, subject, _short_date(s.date)]
            if combined:
                row.append(s.source or s.folder.split("/")[1])
            table.add_row(*row)
            self._rows.append(s.ref)
        self.refresh_bindings()

    def _files_in(self, folder: str) -> list[Path]:
        directory = self.store.root.joinpath(*check_folder(folder).split("/"))
        if not directory.is_dir():
            return []
        return sorted(
            (p for p in directory.iterdir()
             if p.is_file() and not p.is_symlink() and not p.name.startswith(".")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    def selected_ref(self) -> str:
        """The highlighted message's store ref, or "" (none, or a file)."""
        return "" if self.files else self._selected()

    def _selected(self) -> str:
        table = self.query_one(MessageList)
        if not self._rows or table.cursor_row < 0 or table.cursor_row >= len(self._rows):
            return ""
        return self._rows[table.cursor_row]

    def can_delete(self) -> bool:
        return not self.files and self.folder != "" and (
            self.folder == ALL_INBOXES or not is_deleted_folder(self.folder)
        )

    def can_restore(self) -> bool:
        return not self.files and self.folder not in ("", ALL_INBOXES) and is_deleted_folder(
            self.folder
        )

    # -- reader -------------------------------------------------------------

    def open_selected(self) -> None:
        ref = self._selected()
        if not ref:
            return
        reader = self.query_one(WrapLog)
        reader.clear()
        if self.files:
            path = self.store.root / ref
            with open(path, "rb") as handle:
                data = handle.read(_PREVIEW_BYTES + 1)
            if b"\x00" in data[:1024]:
                reader.write(Text(f"{path.name}: not a text file ({path.stat().st_size:,} bytes)."))
                return
            reader.write(Text(sanitize(data[:_PREVIEW_BYTES])))
            if len(data) > _PREVIEW_BYTES:
                reader.write(Text("[preview ends here]", style="dim"))
            return
        message = self.store.read(ref)
        head = Text()
        for label, value in (
            ("From", message.sender),
            ("To", message.to),
            ("Subject", message.subject),
            ("Date", message.date.astimezone().strftime("%Y-%m-%d %H:%M") if message.date else ""),
            ("Via", message.source),
        ):
            if value:
                head.append(f"{label}: ", style="bold")
                head.append(sanitize(value.encode("utf-8"), keep_newlines=False) + "\n")
        reader.write(head)
        reader.write(Text(sanitize(message.body.encode("utf-8"))))
        if not message.is_read:
            self.store.set_read(ref)
            self._mark_row_read()

    def delete_selected(self) -> None:
        ref = self._selected()
        if ref and self.can_delete():
            self.store.delete(ref)
            self._refresh_after_change()
            self.app.notify(f"Moved to {DELETED}. U restores it from there.", timeout=4)

    def restore_selected(self) -> None:
        ref = self._selected()
        if ref and self.can_restore():
            back = self.store.restore(ref)
            self._refresh_after_change()
            self.app.notify(f"Restored to {back.rsplit('/', 1)[0]}.", timeout=4)

    def _refresh_after_change(self) -> None:
        """Reload labels and list after a move, keeping the cursor's row."""
        table = self.query_one(MessageList)
        row = table.cursor_row
        self.reload()
        if self._rows:
            table.move_cursor(row=min(max(row, 0), len(self._rows) - 1))

    def _mark_row_read(self) -> None:
        """Show the open message as read without rebuilding the list."""
        table = self.query_one(MessageList)
        row = table.cursor_row
        table.update_cell_at(Coordinate(row, 0), "")
        subject = table.get_cell_at(Coordinate(row, 2))
        if isinstance(subject, Text):
            table.update_cell_at(Coordinate(row, 2), Text(subject.plain))
        self._relabel_tree()

    def _relabel_tree(self) -> None:
        def walk(node):
            for child in node.children:
                if child.data:
                    child.set_label(self._label(child.data, str(child.data).rsplit("/", 1)[-1]))
                walk(child)

        walk(self.query_one(FolderTree).root)


def mail_browser(store: MessageStore) -> MessageBrowser:
    return MessageBrowser(store, ("Mail",), all_inboxes=True, id="mail-browser")


def bulletins_browser(store: MessageStore) -> MessageBrowser:
    return MessageBrowser(store, ("Bulletins",), id="bulletins-browser")


def files_browser(store: MessageStore) -> MessageBrowser:
    return MessageBrowser(store, (FILES,), files=True, id="files-browser")
