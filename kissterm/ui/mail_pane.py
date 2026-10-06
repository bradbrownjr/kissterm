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
Deleted, and on the Mail tab G sends and receives: with the Home BBS on a
BBS folder, with Winlink on a Winlink folder, and with each one set up on
All Inboxes (`KissTermApp.send_receive_kind`; the Footer says which). On
the Bulletins tab G gets bulletins, I gets them over the Internet and S
chooses the categories. On the Files tab Delete moves a file to Files >
Deleted (U restores it), and S sends it by YAPP or AutoBIN over the
connected session. Each key is shown only where it works
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

from ..files_view import kind_of, zip_members
from ..mail import MessageStore, form_parse, form_xml
from ..mail.bpqmail import routes_of
from ..mail.compose import has_others
from ..mail.store import ALL_INBOXES, DELETED, FILES, check_folder, is_deleted_folder
from ..monitor import sanitize
from . import slideouts
from .form_view import form_text
from .wraplog import WrapLog

#: Inbox, Outbox, Sent first and Deleted last, as every mail client orders
#: them; anything else (a bulletin category) sorts by name in between.
_RANK = {"Inbox": 0, "Outbox": 0.1, "Sent": 0.2, DELETED: 2}

#: How much of a file the Files tab previews.
_PREVIEW_BYTES = 16 * 1024


def _short_date(value: datetime | None) -> str:
    return value.astimezone().strftime("%m-%d %H:%M") if value else ""


#: G's three Footer labels, by what it does from the folder in front
#: (`KissTermApp.send_receive_kind`): only the one that applies is shown.
_G_KIND = {"get_mail": "bbs", "get_winlink": "winlink", "get_all": "all"}

#: The Bulletins tab's own keys (ROADMAP P2, bulletin collection): G gets
#: the chosen categories from the Home BBS, I the same over the Internet,
#: S chooses the categories (`bulletin_screen.py`).
_BULLETIN_BINDINGS = (
    Binding("g", "get_bulletins", "Get bulletins"),
    Binding("i", "get_bulletins_internet", "By Internet"),
    Binding("s", "bulletin_categories", "Categories"),
)
_BULLETIN_ACTIONS = {b.action for b in _BULLETIN_BINDINGS}
#: The Files tab's G (ROADMAP P2, Files): the Home BBS's `FILES`, a pick,
#: and a YAPP download of each, by radio only (`collect.py`).
_FILES_GET = Binding("g", "get_files", "Get files")
#: While a run is going, G cancels it instead (operator, 2026-10-06: the
#: phone's turning button cancels on a tap, and "the UIs need parity").
_CANCEL_RUN = Binding("g", "cancel_run", "Cancel run")
#: What G and I start: none of them while a run is going.
_STARTS_A_RUN = {"get_mail", "get_winlink", "get_all", "get_internet", "get_bulletins",
                 "get_bulletins_internet", "get_files"}


def _run_gate(app, action: str) -> bool | None:
    """While a run is going only `cancel_run` of G and I applies; with
    none, never it. None: the caller decides."""
    running = bool(getattr(app, "_collecting", False))
    if action == "cancel_run":
        return running
    if action in _STARTS_A_RUN and running:
        return False
    return None


class FolderTree(Tree):
    """The folder tree. Each node's data is a folder path or `ALL_INBOXES`.

    G works here as on the list, so it is in the Footer whichever of the
    two has focus.
    """

    BINDINGS = [
        Binding("insert", "new_message", "New"),
        Binding("g", "get_mail", "Send/Receive"),
        Binding("g", "get_winlink", "Send/Receive Winlink"),
        Binding("g", "get_all", "Send/Receive all"),
        Binding("i", "get_internet", "By Internet"),
        *_BULLETIN_BINDINGS,
        _FILES_GET,
        _CANCEL_RUN,
    ]

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        gate = _run_gate(self.app, action)
        if gate is not None:
            return gate
        browser = self.query_ancestor(MessageBrowser)
        if action in _BULLETIN_ACTIONS:
            return browser.id == "bulletins-browser"
        if action == "get_files":
            return browser.id == "files-browser"
        if action == "get_internet":
            return browser.id == "mail-browser"
        if action in _G_KIND:
            return browser.id == "mail-browser" and browser.g_kind() == _G_KIND[action]
        if action == "new_message":
            return browser.id == "mail-browser"
        return True

    def action_get_mail(self) -> None:
        self.app.action_get_mail()  # type: ignore[attr-defined]

    def action_cancel_run(self) -> None:
        self.app.action_cancel_mail_run()  # type: ignore[attr-defined]

    def action_get_winlink(self) -> None:
        self.app.action_get_mail()  # type: ignore[attr-defined]

    def action_get_all(self) -> None:
        self.app.action_get_mail()  # type: ignore[attr-defined]

    def action_get_internet(self) -> None:
        self.app.action_get_mail_internet()  # type: ignore[attr-defined]

    def action_new_message(self) -> None:
        self.app.action_compose_mail()  # type: ignore[attr-defined]

    def action_get_bulletins(self) -> None:
        self.app.action_get_bulletins()  # type: ignore[attr-defined]

    def action_get_bulletins_internet(self) -> None:
        self.app.action_get_bulletins_internet()  # type: ignore[attr-defined]

    def action_bulletin_categories(self) -> None:
        self.app.action_bulletin_categories()  # type: ignore[attr-defined]

    def action_get_files(self) -> None:
        self.app.action_get_files()  # type: ignore[attr-defined]


class MessageList(DataTable):
    """The message (or file) list, with the tab's context keys."""

    BINDINGS = [
        Binding("enter", "open_message", "Open"),
        Binding("insert", "new_message", "New"),
        Binding("r", "reply", "Reply"),
        Binding("q", "reply_quoted", "Reply quoted"),
        Binding("a", "reply_all", "Reply all"),
        Binding("delete", "delete_message", "Delete"),
        Binding("u", "restore_message", "Restore"),
        Binding("g", "get_mail", "Send/Receive"),
        Binding("g", "get_winlink", "Send/Receive Winlink"),
        Binding("g", "get_all", "Send/Receive all"),
        Binding("i", "get_internet", "By Internet"),
        Binding("v", "toggle_form", "Form/text"),
        Binding("t", "toggle_routing", "Routing"),
        *_BULLETIN_BINDINGS,
        _FILES_GET,
        _CANCEL_RUN,
        Binding("s", "send_file", "Send"),
    ]

    def _browser(self) -> "MessageBrowser":
        return self.query_ancestor(MessageBrowser)

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        gate = _run_gate(self.app, action)
        if gate is not None:
            return gate
        browser = self._browser()
        if action in _BULLETIN_ACTIONS:
            return browser.id == "bulletins-browser"
        if action == "get_files":
            return browser.id == "files-browser"
        if action == "send_file":
            return (browser.files and self.row_count > 0
                    and not is_deleted_folder(browser.folder or "Files")
                    and self.app.can_send_file())  # type: ignore[attr-defined]
        if action == "open_message":
            return self.row_count > 0
        if action == "delete_message":
            return self.row_count > 0 and browser.can_delete()
        if action == "restore_message":
            return self.row_count > 0 and browser.can_restore()
        if action in _G_KIND:
            return browser.id == "mail-browser" and browser.g_kind() == _G_KIND[action]
        if action in ("new_message", "get_internet"):
            return browser.id == "mail-browser"
        if action in ("reply", "reply_quoted"):
            return self.row_count > 0 and not browser.files
        if action == "reply_all":
            return self.row_count > 0 and not browser.files and browser.showing_reply_all_message()
        if action == "toggle_form":
            return browser.showing_form_message()
        if action == "toggle_routing":
            return browser.showing_routed_message()
        return True

    def action_toggle_form(self) -> None:
        self._browser().toggle_form_view()

    def action_cancel_run(self) -> None:
        self.app.action_cancel_mail_run()  # type: ignore[attr-defined]

    def action_toggle_routing(self) -> None:
        self._browser().toggle_routing()

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

    def action_reply_all(self) -> None:
        ref = self._browser().selected_ref()
        if ref:
            self.app.action_compose_mail(ref, quoted=None, everyone=True)  # type: ignore[attr-defined]

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
        """Enter: a message opens in the reader; a file opens full screen
        in the viewer (`file_viewer.py`), a click still previewing it."""
        browser = self._browser()
        path = browser.selected_file()
        if path is None:
            browser.open_selected()
            return
        from .file_viewer import FileViewerScreen, read_for_viewer

        try:
            data = read_for_viewer(path)
        except OSError as exc:
            self.app.notify(f"Can't read {path.name}: {exc}", severity="warning")
            return
        self.app.push_screen(FileViewerScreen(path.name, data))

    def action_delete_message(self) -> None:
        self._browser().delete_selected()

    def action_restore_message(self) -> None:
        self._browser().restore_selected()

    def action_get_mail(self) -> None:
        self.app.action_get_mail()  # type: ignore[attr-defined]

    def action_get_winlink(self) -> None:
        self.app.action_get_mail()  # type: ignore[attr-defined]

    def action_get_all(self) -> None:
        self.app.action_get_mail()  # type: ignore[attr-defined]

    def action_get_internet(self) -> None:
        self.app.action_get_mail_internet()  # type: ignore[attr-defined]

    def action_get_bulletins(self) -> None:
        self.app.action_get_bulletins()  # type: ignore[attr-defined]

    def action_get_bulletins_internet(self) -> None:
        self.app.action_get_bulletins_internet()  # type: ignore[attr-defined]

    def action_bulletin_categories(self) -> None:
        self.app.action_bulletin_categories()  # type: ignore[attr-defined]

    def action_get_files(self) -> None:
        self.app.action_get_files()  # type: ignore[attr-defined]

    def action_send_file(self) -> None:
        path = self._browser().selected_file()
        if path is not None:
            self.app.action_file_transfer(path)  # type: ignore[attr-defined]


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
        #: The message in the reader, whether it reads as a form, and
        #: whether V has switched it to its text (`form_view.py`).
        self._open_ref = ""
        self._open_form = None
        self._as_text = False
        #: Its `R:` routing lines, and whether T has unfolded them: folded
        #: by default, as the phone's reader has them (operator,
        #: 2026-10-06: "the UIs need parity in functionality").
        self._open_routes: list[str] = []
        self._show_routes = False
        #: Whether A (Reply all) would reach anyone besides the sender.
        self._open_reply_all = False

    def compose(self) -> ComposeResult:
        tree = FolderTree("folders", classes="mail-tree")
        tree.show_root = False
        tree.guide_depth = 2
        yield tree
        with Vertical(classes="mail-right"):
            yield MessageList(cursor_type="row", zebra_stripes=True, classes="mail-list")
            yield WrapLog(classes="mail-reader", wrap=True, markup=False, highlight=False,
                          follow=False)
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
            self.refresh_bindings()
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

    def selected_file(self) -> Path | None:
        """The highlighted file on the Files tab, or None."""
        ref = self._selected() if self.files else ""
        return self.store.root / ref if ref else None

    def _selected(self) -> str:
        table = self.query_one(MessageList)
        if not self._rows or table.cursor_row < 0 or table.cursor_row >= len(self._rows):
            return ""
        return self._rows[table.cursor_row]

    def g_kind(self) -> str:
        """What G does from this folder: "bbs", "winlink" or "all"."""
        return self.app.send_receive_kind(self.folder)  # type: ignore[attr-defined]

    def can_delete(self) -> bool:
        if self.files:
            return self.folder != "" and not is_deleted_folder(self.folder)
        return self.folder != "" and (
            self.folder == ALL_INBOXES or not is_deleted_folder(self.folder)
        )

    def can_restore(self) -> bool:
        return self.folder not in ("", ALL_INBOXES) and is_deleted_folder(self.folder)

    # -- reader -------------------------------------------------------------

    def open_selected(self) -> None:
        ref = self._selected()
        if not ref:
            return
        reader = self.query_one(WrapLog)
        reader.clear()
        reader.scroll_home(animate=False)
        if self.files:
            path = self.store.root / ref
            with open(path, "rb") as handle:
                data = handle.read(_PREVIEW_BYTES + 1)
            kind = kind_of(path.name, data)
            if kind == "zip":
                try:
                    members = zip_members(path.read_bytes())
                except (OSError, ValueError) as exc:
                    reader.write(Text(f"{path.name}: {exc}"))
                    return
                listing = "\n".join(f"{size:>10,}  {name}" for name, size in members)
                reader.write(Text(sanitize(listing.encode()) or "(empty zip)"))
                reader.write(Text("Enter opens the zip to read its files.", style="dim"))
                return
            if kind == "binary":
                reader.write(Text(f"{path.name}: not a text file ({path.stat().st_size:,} bytes)."))
                return
            reader.write(Text(sanitize(data[:_PREVIEW_BYTES])))
            if len(data) > _PREVIEW_BYTES:
                reader.write(Text("[preview ends here]", style="dim"))
            if kind in ("markdown", "html"):
                reader.write(Text("Enter shows it formatted.", style="dim"))
            return
        message = self.store.read(ref)
        if ref != self._open_ref:
            self._open_ref, self._as_text = ref, False
            self._open_routes, self._show_routes = routes_of(self.store, ref), False
            self._open_reply_all = has_others(message, str(self.app.config.mycall or ""))  # type: ignore[attr-defined]
            # A Winlink form's XML is exactly what was filled in; the text
            # is read against the template only when there is none.
            found = form_xml.from_raw(self.store.raw_files(ref))
            self._open_form = form_xml.read(found) if found is not None else form_parse.recognize(
                message.subject, message.body, form_id=message.extra.get("Form", ""))
            self.query_one(MessageList).refresh_bindings()  # V and T, in the Footer
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
        if self._open_routes:
            count = len(self._open_routes)
            noun = "BBS" if count == 1 else "BBSes"
            if self._show_routes:
                routing = Text(f"Routing ({count} {noun}), the latest first; "
                               "not the sender's address:\n", style="dim")
                for line in self._open_routes:
                    routing.append(sanitize(line.encode("utf-8"), keep_newlines=False) + "\n",
                                   style="dim")
            else:
                routing = Text(f"Routing: {count} {noun} (T shows it)", style="dim")
            reader.write(routing)
        if self._open_form is not None and not self._as_text:
            reader.write(form_text(self._open_form))
        else:
            reader.write(Text(sanitize(message.body.encode("utf-8"))))
        if not message.is_read:
            self.store.set_read(ref)
            self._mark_row_read()

    def showing_form_message(self) -> bool:
        """The reader holds a message that reads as a form (V applies)."""
        return self._open_form is not None and self._open_ref == self._selected()

    def showing_reply_all_message(self) -> bool:
        """The reader holds a message with other recipients (A applies)."""
        return self._open_reply_all and self._open_ref == self._selected()

    def showing_routed_message(self) -> bool:
        """The reader holds a message with routing lines (T applies)."""
        return bool(self._open_routes) and self._open_ref == self._selected()

    def toggle_routing(self) -> None:
        if self.showing_routed_message():
            self._show_routes = not self._show_routes
            self.open_selected()

    def toggle_form_view(self) -> None:
        if self.showing_form_message():
            self._as_text = not self._as_text
            self.open_selected()
            self.query_one(MessageList).refresh_bindings()

    def delete_selected(self) -> None:
        ref = self._selected()
        if ref and self.can_delete():
            self.app.core.mail.delete(ref)  # type: ignore[attr-defined]
            self._refresh_after_change()
            if self.files:
                self.app.notify(f"Moved to Files > {DELETED}. U restores it from there.")
                return
            self.app.notify(f"Moved to {DELETED}. U restores it from there.")

    def restore_selected(self) -> None:
        ref = self._selected()
        if ref and self.can_restore():
            back = self.app.core.mail.restore(ref)  # type: ignore[attr-defined]
            self._refresh_after_change()
            if self.files:
                self.app.notify(f"Restored to {back.rsplit('/', 1)[0].replace('/', ' > ')}.")
                return
            self.app.notify(f"Restored to {back.rsplit('/', 1)[0]}.")

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
