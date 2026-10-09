"""Mail: the station's message store, read from the phone, and Send/
Receive started from it.

**Three sections, as the terminal's three tabs** (`SECTIONS`): Mail,
Bulletins and Files, each with only its own folders. On the phone a
switch at the top of the page chooses; on a wide screen the shell's
rail has each as a place (`shell.RAIL`) and the switch hides (operator,
2026-10-06: "Desktop will have room for the additional section
buttons"). A section opens where it was left, else on an Inbox or its
first folder, never on Deleted.

Reading is free; **Send/Receive is a button**, the same request as the
terminal's G (and, in its sheet, By Internet: the terminal's I; on a
Bulletins folder Get bulletins, on Files Get files), and dials the Home BBS or Winlink through the station's own
connect flow (the reminder, the gate, a login question here if one is
missing).

**Writing, replying and deleting are the terminal's** (Insert, R, A, Q,
Delete, U), on the same core methods (`mail_write`, `mail_reply_start`,
`mail_delete`, `mail_restore`), and none of them transmits: Save puts a
message in its Outbox for Send/Receive. Write is a small pencil
over the Send/Receive button on a Mail folder; the reader has Reply, Reply all (when there is
anyone else), Reply with quote, and Delete, or Restore in Deleted.

**A swipe on a message deletes it** (operator, 2026-10-06), or restores
it in Deleted: nothing transmits, so unlike a station's row the swipe
acts. It takes half the row's width, and a thumb that changes its mind
slides back before letting go and nothing happens (Flutter's own
Dismissible: the decision is made where the finger lifts). After it,
**Undo** on the note puts the message back.

**A run shows it is still going** (operator, 2026-10-06: after the first
notice, nothing said it was). While the station reports one running
(`MailRunChanged`), the Send/Receive button's icon turns, and the
progress line ("Receiving 2 of 2") is followed by dots counting one to
three. **Tapping the turning button cancels the run** with no sheet:
stopping only ends the exchange (`mail_cancel`, a DISC if the link is
up), as the transmit switch turns off without asking.

**A message's routing is one small line** under the date (`Routing` and an arrow,
`routing_section`); a tap shows the `R:` lines.
"""

from __future__ import annotations

import asyncio
import base64
import math
import uuid
from datetime import datetime

import flet as ft

from . import sheets
from .toolbar import Action, Toolbar
from .text import MONO

#: A piece of a file sent up to the station, and the most it will take (it
#: refuses more: `Mail.MAX_UPLOAD`); this only spares reading a file it would refuse.
UPLOAD_PIECE = 192 * 1024
UPLOAD_MAX = 1024 * 1024

#: Seconds per step of the turning icon and the counting dots.
TICK = 0.4


def routing_section(routes: list[str]) -> list[ft.Control]:
    """One small `Routing` line under the date with an arrow icon that says
    it unfolds; a tap shows the `R:` lines themselves (operator, 2026-10-06:
    "Routing takes more space than the message ... one small tight
    small-font line under the date"; earlier the same day a recipient took
    a routing line for the sender's address, so the lines stay folded). No
    callsigns on the line (operator, 2026-10-07: "the call sign after isn't
    needed"). The arrow is a Material icon, not a text glyph: the web
    client's font has no U+25B8 and drew a box."""
    if not routes:
        return []
    lines = ft.Text("\n".join(routes), font_family=MONO, size=11, selectable=True,
                    color=ft.Colors.OUTLINE, visible=False)
    arrow = ft.Icon(ft.Icons.ARROW_RIGHT, size=18, color=ft.Colors.OUTLINE)

    def toggle(_e) -> None:
        lines.visible = not lines.visible
        arrow.icon = ft.Icons.ARROW_DROP_DOWN if lines.visible else ft.Icons.ARROW_RIGHT
        arrow.update()
        lines.update()

    return [ft.Container(on_click=toggle, content=ft.Row(
                spacing=0, tight=True, controls=[
                    ft.Text("Routing", size=12, color=ft.Colors.OUTLINE), arrow])),
            lines]


#: Message types the phone writes, as the terminal's Type list: the last
#: two open the radiogram form (`radiogram.py`); Winlink forms are the
#: terminal's for now.
RADIOGRAM, RADIOGRAM_ICS213 = "radiogram", "radiogram-ics213"
#: A form chosen as the Type is `FORM_PREFIX` + its id (the terminal's `ui/compose.py`).
FORM_PREFIX = "form:"
TYPES = (("P", "Private (BBS)"), ("B", "Bulletin (BBS)"), ("W", "Winlink"),
         (RADIOGRAM, "NTS radiogram (ST)"), (RADIOGRAM_ICS213, "Radiogram-ICS213 (ST)"))
_TO_HINT = {"P": "Callsign, e.g. W1BKW", "B": "Category, e.g. WX",
            "W": "Callsigns or email addresses, e.g. W1AW, n0call@example.com"}


def when(iso: str | None) -> str:
    """A message's date as the terminal's reader shows it: local time,
    to the minute. Anything unreadable is shown as it came."""
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(iso)


#: One checkbox row in a sheet, for sizing a list that scrolls in its own box.
CHECKBOX_ROW = 48


def size_text(m: dict) -> str:
    """A file's size under Files ("" for a message)."""
    return f"{m['size']:,} bytes" if m.get("file") and isinstance(m.get("size"), int) else ""


#: The three kinds of folder, as the terminal's Mail, Bulletins and Files
#: tabs: (top folder, title, icon, selected icon).
SECTIONS = (
    ("Mail", "BBS Mail", ft.Icons.MAIL_OUTLINE, ft.Icons.MAIL),
    ("Bulletins", "Bulletins", ft.Icons.FEED_OUTLINED, ft.Icons.FEED),
    ("Files", "Files", ft.Icons.FOLDER_OUTLINED, ft.Icons.FOLDER),
)


#: The terminal's combined view of every Inbox under Mail: a name
#: `mail_list` takes, not a folder anything is filed in. Mail opens on
#: it, as the terminal's Mail tab does.
ALL_INBOXES = "All Inboxes"


def in_section(folder: str, section: str) -> bool:
    if folder == ALL_INBOXES:
        return section == "Mail"
    return folder == section or folder.startswith(section + "/")


def section_folders(folders: list[str], section: str) -> list[str]:
    """The section's folders a message can be in: its own top folder only
    when nothing is under it (Files), never a bare parent (Mail, Mail/BBS)."""
    mine = [f for f in folders if in_section(f, section)]
    leaves = [f for f in mine if not any(o.startswith(f + "/") for o in mine)]
    leaves = sorted(leaves, key=in_deleted)  # Deleted last, the rest as they came
    return [ALL_INBOXES, *leaves] if section == "Mail" else leaves


def default_folder(folders: list[str], section: str) -> str:
    """Where a section opens: All Inboxes or an Inbox, else its first
    folder that is not Deleted (a section never opens on what was thrown
    away)."""
    if ALL_INBOXES in folders:
        return ALL_INBOXES
    return next((f for f in folders if f.endswith("Inbox")),
                next((f for f in folders if not in_deleted(f)),
                     folders[0] if folders else section))


def folder_label(folder: str, section: str) -> str:
    return folder.removeprefix(section + "/") if folder != section else section


def folder_tree(folders: list[str], section: str) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """`section_folders` as the picker's tree: (label, folder, children).
    A folder two levels under the section (`Mail/BBS/Inbox`) goes under its
    service (`BBS`: no folder of its own, children `Inbox`), in the order the
    services first appear; a one-level folder (All Inboxes, `Bulletins/WX`,
    Files) stands alone. Pure, so the shape is tested without a page."""
    out: list[tuple[str, str, list[tuple[str, str]]]] = []
    groups: dict[str, list[tuple[str, str]]] = {}
    for folder in folders:
        rel = folder_label(folder, section) if folder != ALL_INBOXES else folder
        group, _, leaf = rel.partition("/")
        if not leaf:
            out.append((rel, folder, []))
        elif group in groups:
            groups[group].append((leaf, folder))
        else:
            groups[group] = [(leaf, folder)]
            out.append((group, "", groups[group]))
    return out


def in_deleted(folder: str) -> bool:
    return folder.rsplit("/", 1)[-1] == "Deleted"


def swipe_background(restore: bool, end: bool) -> ft.Control:
    """What shows under a message while it is dragged: Delete (or Restore
    in Deleted), on the side the thumb is uncovering."""
    label, icon, colour = (("Restore", ft.Icons.RESTORE_FROM_TRASH, ft.Colors.PRIMARY_CONTAINER)
                           if restore else
                           ("Delete", ft.Icons.DELETE_OUTLINE, ft.Colors.ERROR_CONTAINER))
    parts = [ft.Icon(icon), ft.Text(label)]
    return ft.Container(
        bgcolor=colour, padding=ft.Padding.symmetric(horizontal=20),
        alignment=ft.Alignment.CENTER_RIGHT if end else ft.Alignment.CENTER_LEFT,
        content=ft.Row(tight=True, controls=parts[::-1] if end else parts))




class MailView:
    def __init__(self, app) -> None:
        self.app = app
        self.folder = ALL_INBOXES
        #: Mail, Bulletins or Files (`SECTIONS`), and the folder last shown
        #: in each, so going back to one finds it where it was.
        self.section = "Mail"
        self._last: dict[str, str] = {}
        #: The phone's way between the sections; on a wide screen the rail
        #: has each as its own place and this is hidden.
        self.switch = ft.Tabs(
            length=len(SECTIONS), selected_index=0, on_change=self._switched,
            content=ft.TabBar(tabs=[ft.Tab(label=value) for value, *_ in SECTIONS]))
        #: The folder picker (operator, 2026-10-07: "more of a tree folder
        #: view", the inline panel): a row showing the folder, `Mail / BBS /
        #: Inbox`, that opens a tree under it as wide as the section switch.
        #: Services (BBS, Winlink) fold; a leaf picks and closes. Folded
        #: arrows are Material icons, the web font has no text triangle.
        self.folder_list: list[str] = []
        self._picking = False
        self._expanded: set[str] = set()
        self._folder_text = ft.Text(expand=True, no_wrap=True,
                                    overflow=ft.TextOverflow.ELLIPSIS)
        self._folder_arrow = ft.Icon(ft.Icons.ARROW_DROP_DOWN, color=ft.Colors.OUTLINE)
        self.folders = ft.Container(
            expand=True, on_click=self._toggle_picker, ink=True,
            padding=ft.Padding.symmetric(horizontal=14, vertical=12),
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT), border_radius=6,
            content=ft.Row(controls=[self._folder_text, self._folder_arrow]))
        self.tree = ft.Column(spacing=0, tight=True)
        self.panel = ft.Container(
            visible=False, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH, border_radius=12,
            padding=ft.Padding.symmetric(horizontal=8, vertical=6),
            margin=ft.Margin.symmetric(horizontal=12), content=self.tree)
        self._picker: ft.FilePicker | None = None
        self._writing: dict | None = None
        self._reloading = False
        self._reload_again = False
        self.list = ft.ListView(expand=True)
        self.reader: ft.Control | None = None
        self.control = ft.Container(expand=True)
        self.activity = ft.Text("", color=ft.Colors.PRIMARY)
        self.sync_icon = ft.Icon(ft.Icons.SYNC, rotate=0,
                                 animate_rotation=ft.Animation(int(TICK * 1000), ft.AnimationCurve.LINEAR))
        #: The one toolbar (`toolbar.py`): the section tabs on a phone, then
        #: what this folder offers, and Write last on Mail. Send/Receive (Get
        #: bulletins, Get files) is the icon that turns while a run is going,
        #: the same plain icon on all three tabs.
        self.actions = {
            "sync": Action(self.sync_icon, "Send/Receive", self._send_receive),
            "categories": Action(ft.Icons.CHECKLIST, "Categories", self._categories,
                                 visible=False),
            "add_file": Action(ft.Icons.UPLOAD_FILE, "Add file", self._add_file, visible=False),
            "write": Action(ft.Icons.EDIT, "Write", self._write_new, primary=True),
        }
        self.toolbar = Toolbar(app)
        self._ticking = False
        self._dots = 0
        self._paint_button()
        self._show_list()

    def _paint_button(self) -> None:
        running = self.app.state.mail_running
        what = ("Get files" if self.folder.startswith("Files")
                else "Get bulletins" if self.folder.startswith("Bulletins") else "Send/Receive")
        sync = self.actions["sync"]
        sync.label = what
        sync.tooltip = "Running: tap to cancel" if running else what
        self.toolbar.set(list(self.actions.values()))

    async def shown(self) -> None:
        await self.reload()

    def on_state(self, kind: str, data) -> None:
        if kind == "stale" and data == "mail":
            # Only while in front; `shown` reloads when it comes back. Under
            # Flet 1.0.3 a list rebuilt off screen was drawn with a row
            # twice once it came back (reproduced 2026-10-06).
            from .shell import MAIL

            if self.app.index == MAIL:
                self.app.page.run_task(self.reload)
        elif kind == "activity" and self.reader is None and self._writing is None:
            self._show_list()
        elif kind in ("mail_running", "station"):  # "station": a (re)join mid-run
            self._paint_button()
            if self.app.state.mail_running and not self._ticking:
                self._ticking = True
                self.app.page.run_task(self._tick)

    async def _tick(self) -> None:
        """Turn the icon and count the dots while a run is going."""
        try:
            while self.app.state.mail_running:
                self.sync_icon.rotate = (self.sync_icon.rotate or 0) + math.pi / 2
                self._dots = self._dots % 3 + 1
                self._paint_activity()
                self.app.page.update()
                await asyncio.sleep(TICK)
        finally:
            self._ticking = False
            self._dots = 0
            self._paint_activity()
            self.app.page.update()

    def _paint_activity(self) -> None:
        text = self.app.state.activity
        dots = "." * self._dots if self.app.state.mail_running else ""
        # The dots in a fixed width, so the line does not shuffle as they count.
        self.activity.value = f"{text}{dots:<3}" if text else ""

    def _show_list(self) -> None:
        self.reader = None
        self._paint_activity()
        self._paint_toolbar()
        self.paint_switch()
        self.toolbar.show(True)
        self.control.content = ft.Column(
            expand=True, spacing=0, controls=[
                ft.Container(padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                             content=self.toolbar.row),
                ft.Container(padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                             content=ft.Row(controls=[self.folders])),
                self.panel,
                *([ft.Container(padding=ft.Padding.symmetric(horizontal=16, vertical=4),
                                content=self.activity)] if self.app.state.activity else []),
                self.list])

    async def reload(self) -> None:
        """Load the folder list and the folder shown. One at a time: the
        connection coming up, a mail change and a tap can all ask at once,
        and overlapping rebuilds of the keyed rows drew a message twice
        (2026-10-06). A request during a load runs once more after it."""
        if self._reloading:
            self._reload_again = True
            return
        self._reloading = True
        try:
            while True:
                self._reload_again = False
                await self._reload_once()
                if not self._reload_again:
                    break
        finally:
            self._reloading = False

    async def _reload_once(self) -> None:
        folders = section_folders(await self.app.command("mail_folders") or [], self.section)
        if not in_section(self.folder, self.section) or (folders and self.folder not in folders):
            self.folder = default_folder(folders, self.section)
        self.folder_list = folders
        self._paint_button()
        self._paint_folders()
        messages = await self.app.command("mail_list", folder=self.folder) or []
        self.list.controls = [self._row(m) for m in messages] or [ft.Container(
                padding=ft.Padding.all(24),
                content=ft.Text("Nothing in this folder.", color=ft.Colors.OUTLINE))]
        if self.reader is None and self._writing is None:
            self._paint_toolbar()
        self.app.page.update()

    def _paint_folders(self) -> None:
        """The picker row and its tree for the folder shown. The service
        holding the folder shown is open; the others stay as left."""
        self._folder_text.value = (self.folder if self.folder == ALL_INBOXES else
                                   folder_label(self.folder, self.section)).replace("/", " / ")
        self._folder_arrow.icon = (ft.Icons.ARROW_DROP_UP if self._picking
                                   else ft.Icons.ARROW_DROP_DOWN)
        self.panel.visible = self._picking
        rows: list[ft.Control] = []
        for label, key, kids in folder_tree(self.folder_list or [self.folder], self.section):
            if not kids:
                rows.append(self._leaf(label, key, 0))
                continue
            opened = label in self._expanded
            rows.append(self._tree_row(
                ft.Icons.ARROW_DROP_DOWN if opened else ft.Icons.ARROW_RIGHT,
                ft.Icons.FOLDER_OPEN if opened else ft.Icons.FOLDER, label, False,
                self._group_toggler(label), 0))
            if opened:
                rows += [self._leaf(name, k, 1) for name, k in kids]
        self.tree.controls = rows

    def _leaf(self, label: str, key: str, depth: int) -> ft.Control:
        return self._tree_row(None, ft.Icons.ALL_INBOX if key == ALL_INBOXES else ft.Icons.INBOX
                              if label == "Inbox" else ft.Icons.FOLDER_OUTLINED, label,
                              key == self.folder, self._folder_picker(key), depth)

    @staticmethod
    def _tree_row(arrow, icon, label: str, selected: bool, on_click, depth: int) -> ft.Control:
        return ft.Container(
            on_click=on_click, ink=True, border_radius=8,
            bgcolor=ft.Colors.SECONDARY_CONTAINER if selected else None,
            padding=ft.Padding.only(left=8 + 28 * depth, right=8, top=10, bottom=10),
            content=ft.Row(spacing=8, controls=[
                ft.Icon(arrow, color=ft.Colors.OUTLINE) if arrow else ft.Container(width=0),
                ft.Icon(icon, size=20, color=ft.Colors.PRIMARY if selected else ft.Colors.OUTLINE),
                ft.Text(label)]))

    def _group_toggler(self, label: str):
        def handler(_e) -> None:
            self._expanded.symmetric_difference_update({label})
            self._paint_folders()
            self.app.page.update()
        return handler

    def _folder_picker(self, key: str):
        async def handler(_e) -> None:
            self.folder = key
            self._picking = False
            self._paint_button()
            await self.reload()
        return handler

    def _toggle_picker(self, _e) -> None:
        self._picking = not self._picking
        if self._picking:  # open on the service holding the folder shown
            self._expanded.update(g for g, _k, kids in folder_tree(self.folder_list, self.section)
                                  if any(k == self.folder for _n, k in kids))
        self._paint_folders()
        self.app.page.update()

    def _paint_toolbar(self) -> None:
        mail = in_section(self.folder, "Mail")
        self.actions["write"].visible = mail
        self.actions["categories"].visible = in_section(self.folder, "Bulletins")
        self.actions["add_file"].visible = in_section(self.folder, "Files")
        # The run is the same plain icon on all three tabs (operator,
        # 2026-10-09: "three tabs, different connect buttons"); the primary is
        # the tab's own making action: Write, or Add file.
        self.actions["add_file"].primary = True
        self.toolbar.paint()

    async def _add_file(self, _e) -> None:
        """Pick a file on this device and send it up to Files > Uploads
        (`file_upload`, in pieces); the terminal reaches any file on its own
        disk, a phone cannot. It is only kept there: sending it over the
        radio is Send over the radio on the file, which asks first."""
        if self._picker is None:
            self._picker = ft.FilePicker()
            self.app.page.services.append(self._picker)
        picked = await self._picker.pick_files(dialog_title="Add a file to Files",
                                               with_data=True)
        if not picked:
            return
        name, data = picked[0].name, picked[0].bytes
        if not data:
            sheets.snack(self.app.page, "That file could not be read.", error=True)
            return
        if len(data) > UPLOAD_MAX:
            sheets.snack(self.app.page, "That file is over 1 MiB, more than is worth sending "
                                        "by packet.", error=True)
            return
        upload = uuid.uuid4().hex
        sent, ref = 0, ""
        while True:
            piece = data[sent:sent + UPLOAD_PIECE]
            done = sent + len(piece) >= len(data)
            result = await self.app.command(
                "file_upload", id=upload, filename=name, offset=sent,
                data=base64.b64encode(piece).decode("ascii"), done=done)
            if not result:
                return
            sent += len(piece)
            if done:
                ref = result["ref"]
                break
        sheets.snack(self.app.page, "Added to Files > Uploads. Open it and press Send over "
                                    "the radio to send it.")
        self.folder = ref.rsplit("/", 1)[0] or self.folder
        await self.reload()

    async def _categories(self, _e) -> None:
        """Which bulletin categories are collected, from those the Home BBS
        listed last; changed here, offline, and saved by the station."""
        choice = await self.app.command("bulletin_categories")
        if not choice:
            sheets.snack(self.app.page, "No categories yet: Get bulletins asks the BBS "
                                        "for its list on the first collection.")
            return
        chosen = {c.upper() for c in choice.get("chosen", [])}
        every = ft.Switch(label="Every category, now and later", value=bool(choice.get("all")))
        boxes = [ft.Checkbox(label=f"{name}  ({count})", value=name.upper() in chosen, data=name)
                 for name, count in (choice.get("seen") or {}).items()]

        def every_changed(_e) -> None:
            for box in boxes:
                box.disabled = bool(every.value)
            self.app.page.update()

        every.on_change = every_changed
        every_changed(None)

        async def save() -> None:
            await self.app.command("bulletin_categories_save",
                                   picked=[b.data for b in boxes if b.value],
                                   all=bool(every.value))

        sheets.form(self.app.page, f"Bulletins from {choice.get('bbs', 'the Home BBS')}",
                    # The list scrolls in its own box, so Save stays on screen:
                    # WS1EC's 14 categories ran past the phone's bottom edge
                    # with nothing to scroll (operator, 2026-10-07).
                    [every, ft.Column(tight=True, spacing=0, scroll=ft.ScrollMode.AUTO,
                                      height=min(CHECKBOX_ROW * len(boxes), 320),
                                      controls=boxes)],
                    "Save", save,
                    detail="Ticked categories are collected by Get bulletins. Nothing is "
                           "asked of the BBS to change this.")

    def _row(self, m: dict) -> ft.Control:
        ref = m.get("ref", "")
        restore = in_deleted(self.folder)
        return ft.Dismissible(
            key=f"msg-{ref}", data=ref,
            background=swipe_background(restore, end=False),
            secondary_background=swipe_background(restore, end=True),
            dismiss_direction=ft.DismissDirection.HORIZONTAL,
            # Half the row: a short, accidental drag springs back.
            dismiss_thresholds={ft.DismissDirection.START_TO_END: 0.5,
                                ft.DismissDirection.END_TO_START: 0.5},
            on_dismiss=self._swiped,
            content=ft.ListTile(
                title=ft.Text(m.get("subject", "") or "(no subject)", max_lines=1,
                              overflow=ft.TextOverflow.ELLIPSIS),
                subtitle=ft.Text("  ".join(part for part in (
                    m.get("sender") or "", size_text(m), when(m.get("date")), self._via(m))
                    if part), size=12),
                on_click=self._opener(ref)))

    def _via(self, m: dict) -> str:
        """On All Inboxes, which service a message came by (the terminal's
        Via column): its source, else its folder's service."""
        if self.folder != ALL_INBOXES:
            return ""
        parts = (m.get("folder") or "").split("/")
        return m.get("source") or (parts[1] if len(parts) > 1 else "")

    async def _swiped(self, e) -> None:
        """The swipe went all the way: the row is gone, so is the message
        (to Deleted), with Undo."""
        if e.control in self.list.controls:
            self.list.controls.remove(e.control)
        self.app.page.update()
        await self.discard(e.control.data)

    async def discard(self, ref: str) -> None:
        """Delete `ref`, or restore it in Deleted, and offer Undo."""
        restoring = in_deleted(self.folder)
        moved = await self.app.command("mail_restore" if restoring else "mail_delete", ref=ref)
        if not moved:
            await self.reload()
            return

        async def undo() -> None:
            await self.app.command("mail_delete" if restoring else "mail_restore", ref=moved)

        where = moved.rsplit("/", 1)[0].removeprefix("Mail/")
        sheets.snack(self.app.page, f"Restored to {where}." if restoring else "Moved to Deleted.",
                     action="Undo", on_action=undo)

    def title(self) -> str:
        return next(title for value, title, *_ in SECTIONS if value == self.section)

    def relayout(self) -> None:
        """The screen crossed `shell.WIDE`: the switch shows or goes."""
        if self.reader is None and self._writing is None:
            self._show_list()

    def paint_switch(self) -> None:
        """The section tabs lead the toolbar on a phone; a wide screen has a
        rail place for each, so they go."""
        self.switch.selected_index = [v for v, *_ in SECTIONS].index(self.section)
        self.toolbar.tabs = None if getattr(self.app, "wide", False) else self.switch
        self.toolbar.paint()

    def set_section(self, section: str) -> None:
        """Show Mail, Bulletins or Files, at the folder last shown there."""
        if section == self.section:
            return
        self._last[self.section] = self.folder
        self._picking = False
        self.section = section
        self.folder = self._last.get(section, "")
        if self.reader is None and self._writing is None:
            self._show_list()

    async def _switched(self, e) -> None:
        picked = SECTIONS[int(e.control.selected_index)][0]
        if picked == self.section:  # a tap on the tab already shown: stay
            return
        self.set_section(picked)
        self.app.section_changed()
        await self.reload()

    def _opener(self, ref: str):
        async def handler(_e) -> None:
            await self.open(ref)
        return handler

    async def open(self, ref: str) -> None:
        message = await self.app.command("mail_read", ref=ref)
        if not message:
            return
        head = [f"{name}: {value}" for name, value in
                (("From", message.get("sender")), ("To", message.get("to")),
                 ("Size", size_text(message)), ("Date", when(message.get("date")))) if value]
        self.reader = ft.Column(expand=True, spacing=0, controls=[
            ft.Row(controls=[ft.IconButton(icon=ft.Icons.ARROW_BACK, tooltip="Back to the list",
                                           on_click=self._back),
                             ft.Text(message.get("subject", ""), expand=True, max_lines=2,
                                     theme_style=ft.TextThemeStyle.TITLE_MEDIUM)]),
            ft.Container(padding=ft.Padding.symmetric(horizontal=8), content=self._reader_toolbar(
                self.reader_actions(ref, message))),
            ft.Container(expand=True, padding=ft.Padding.all(16), content=ft.Column(
                scroll=ft.ScrollMode.AUTO, controls=[
                    ft.Column(spacing=2, tight=True, controls=[
                        ft.Text("\n".join(head), color=ft.Colors.OUTLINE, selectable=True),
                        *routing_section(message.get("routing") or [])]),
                    ft.Divider(),
                    ft.Text(message.get("body", ""), selectable=True)]))])
        self.toolbar.show(False)
        self.control.content = self.reader
        self.app.page.update()

    async def open_viewer(self, ref: str) -> None:
        from .files import FileViewer

        async def close() -> None:
            self.toolbar.show(False)
            self.control.content = self.reader
            self.app.page.update()

        viewer = FileViewer(self, ref, close)
        await viewer.show()
        self.toolbar.show(False)
        self.control.content = viewer.control
        self.app.page.update()

    def _reader_toolbar(self, actions: list[Action]) -> ft.Control:
        """The reader's one row of actions (`toolbar.py`): the primary last."""
        bar = Toolbar(self.app, register=False, gate=False)
        bar.set(actions)
        return bar.inline()

    def reader_actions(self, ref: str, message: dict) -> list[Action]:
        """Reply (the primary), Reply all, Reply with quote, Delete or Restore:
        the terminal's R, A, Q, Delete and U; on a file, Open and Send over
        the radio."""
        def reply(quoted: bool | None, everyone: bool = False):
            async def go(_e) -> None:
                await self.reply(ref, quoted=quoted, everyone=everyone)
            return go

        async def discard(_e) -> None:
            await self.discard(ref)
            await self._back(None)

        actions: list[Action] = []
        in_files = bool(message.get("file")) or self.folder.startswith("Files")
        if message.get("file") and message.get("kind") != "binary":
            # The terminal's Enter on a file: a zip's members, Markdown and
            # HTML formatted (`files.py`).
            async def open_file(_e) -> None:
                await self.open_viewer(ref)

            actions.append(Action(
                ft.Icons.OPEN_IN_FULL,
                "Open as a list" if message.get("kind") == "zip" else "Open formatted",
                open_file, primary=True))
        if message.get("file"):
            # The terminal's S on the Files tab: over a connected session, asked first.
            async def send_file(_e) -> None:
                from . import transfer
                from .shell import TERMINAL

                transfer.ask(self.app, ref=ref, name=message.get("subject", ""),
                             current=self.app.views[TERMINAL].current)

            actions.append(Action(ft.Icons.UPLOAD_FILE, "Send over the radio", send_file))
        if not self.folder.startswith("Files"):
            actions.append(Action(ft.Icons.REPLY, "Reply", reply(None), primary=True))
            if message.get("reply_all"):
                actions.append(Action(ft.Icons.REPLY_ALL, "Reply all", reply(None, everyone=True)))
            actions.append(Action(ft.Icons.FORMAT_QUOTE, "Reply with quote", reply(True)))
            on = message.get("reply_on") or {}

            def answer(form_id: str):
                async def go(_e) -> None:
                    await self.show_form(form_id, reply_to=ref)
                return go

            if on.get("form"):
                # The terminal's Reply on form: the ICS-213 reply, the original's blocks read-only.
                actions.append(Action(ft.Icons.ASSIGNMENT_RETURN, "Reply on form", answer("")))
            if on.get("strip"):
                # The terminal's Answer strip: the request strip as a form.
                actions.append(Action(ft.Icons.FACT_CHECK, "Answer strip", answer(on["strip"])))
        if in_deleted(self.folder):
            actions.append(Action(ft.Icons.RESTORE_FROM_TRASH, "Restore", discard,
                                  primary=not in_files and not any(a.primary for a in actions)))
        else:
            actions.append(Action(ft.Icons.DELETE_OUTLINE, "Delete", discard))
        return actions

    async def _back(self, _e) -> None:
        self._writing = None
        self._show_list()
        await self.reload()

    # -- writing ---------------------------------------------------------
    async def _write_new(self, _e) -> None:
        send_type = "W" if self.folder.startswith("Mail/Winlink") else "P"
        self.show_writer({"to": "", "title": "", "body": "", "send_type": send_type,
                          "heading": "New message", "by_number": False, "note": ""}, "")

    async def reply(self, ref: str, *, quoted: bool | None, everyone: bool = False) -> None:
        start = await self.app.command("mail_reply_start", ref=ref, quoted=quoted, all=everyone)
        if start:
            self.show_writer(start, ref)

    def show_writer(self, start: dict, reply_to: str) -> None:
        """The message being written, full screen: Save files it in its
        Outbox and sends nothing; the close button asks before throwing
        away what was typed."""
        new = not reply_to
        send_type = start.get("send_type", "P")
        kind = ft.Dropdown(dense=True, label="Type", value=send_type, visible=new,
                           options=[ft.DropdownOption(key=k, text=t) for k, t in TYPES])
        to = ft.TextField(label="To", value=start.get("to", ""), dense=True,
                          hint_text=_TO_HINT.get(send_type, ""),
                          disabled=bool(start.get("by_number")),
                          capitalization=ft.TextCapitalization.CHARACTERS)
        at = ft.TextField(label="@ (optional: the BBS adds it)", dense=True,
                          visible=send_type != "W", disabled=bool(start.get("by_number")),
                          capitalization=ft.TextCapitalization.CHARACTERS)
        title = ft.TextField(label="Title", value=start.get("title", ""), dense=True,
                             disabled=bool(start.get("by_number")))
        body = ft.TextField(label="Message", value=start.get("body", ""), multiline=True,
                            min_lines=8, expand=True)
        problems = ft.Text("", color=ft.Colors.ERROR)
        written_on = start.get("form")  # {"id", "values"} when a form made this text

        async def add_forms() -> None:
            """The station's forms, after the radiograms in Type."""
            found = await self.app.command("forms") or []
            kind.options += [ft.DropdownOption(key=FORM_PREFIX + f["id"], text=f"{f['title']} (form)")
                             for f in found]
            self.app.page.update()

        if new and not written_on:
            self.app.page.run_task(add_forms)

        def kind_changed(_e) -> None:
            if str(kind.value).startswith(FORM_PREFIX):
                self.app.page.run_task(self.show_form, kind.value.removeprefix(FORM_PREFIX))
                return
            if kind.value in (RADIOGRAM, RADIOGRAM_ICS213):
                self.app.page.run_task(self.show_radiogram, kind.value == RADIOGRAM_ICS213)
                return
            to.hint_text = _TO_HINT.get(kind.value, "")
            at.visible = kind.value != "W"
            at.label = "@ distribution, e.g. USA" if kind.value == "B" else \
                "@ (optional: the BBS adds it)"
            self.app.page.update()

        kind.on_select = kind_changed

        async def save(_e) -> None:
            args = dict(to=to.value or "", at=at.value or "", title=title.value or "",
                        body=body.value or "", send_type=kind.value or send_type)
            if written_on:
                # A form's message: its XML goes with it for Winlink (`Mail.write_form`).
                result = await self.app.command("form_write", form=written_on["id"],
                                                values=written_on["values"],
                                                reply_to=written_on.get("reply_to", ""), **args)
            else:
                result = await self.app.command("mail_write", reply_to=reply_to, **args)
            if not result:
                return
            if result.get("problems"):
                problems.value = "\n".join(result["problems"])
                self.app.page.update()
                return
            where = result["folder"].removeprefix("Mail/").replace("/", " ")
            sheets.snack(self.app.page, f"Saved to {where}. Send/Receive sends it."
                         + (f" {result['note']}" if result.get("note") else ""))
            await self._back(None)

        async def close(_e) -> None:
            if (body.value or "") != start.get("body", "") and (body.value or "").strip():
                sheets.confirm(self.app.page, "Discard this message?",
                               "What you wrote is not saved anywhere.", "Discard",
                               lambda: self._back(None), danger=True)
                return
            await self._back(None)

        self._writing = {"to": to, "at": at, "title": title, "body": body, "kind": kind,
                         "problems": problems, "save": save, "close": close}
        self.reader = None
        self.toolbar.show(False)
        self.control.content = ft.Column(expand=True, spacing=0, controls=[
            ft.Container(padding=ft.Padding.only(right=12), content=ft.Row(controls=[
                ft.IconButton(icon=ft.Icons.CLOSE, tooltip="Close", on_click=close),
                ft.Text(start.get("heading", ""), expand=True, max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                ft.FilledButton(content="Save to Outbox", on_click=save)])),
            ft.Container(expand=True, padding=ft.Padding.symmetric(horizontal=16, vertical=8),
                         content=ft.Column(expand=True, spacing=10,
                                           horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                                           controls=[
                             *([ft.Text(start["note"], color=ft.Colors.OUTLINE, size=12)]
                               if start.get("note") else []),
                             kind, to, at, title, body, problems]))])
        self.app.page.update()

    async def fill_in(self, form: str) -> None:
        """The form a PKTNET page is (`file_open`'s `form`), on its own page."""
        if form == RADIOGRAM:
            await self.show_radiogram(False)
        else:
            await self.show_form(form)

    async def show_form(self, form_id: str, reply_to: str = "") -> None:
        """A form, in the writer's place (`forms.py`); Next opens the writer
        with what it made. `form_id` may be `strip:` and a strip's text.
        With `reply_to`, that message's reply form (the ICS-213 reply) or
        its strip answered: Next opens the writer as a reply to it."""
        from .forms import FormPage

        start = await self.app.command("form_start", form=form_id,
                                       reply_to=reply_to if not form_id.startswith("strip:")
                                       else "")
        if start is None:
            return

        async def next_(form: dict, values: dict, made: dict, key: str) -> None:
            if made.get("next_form"):
                # A pasted strip is two forms: the paste, then its questions.
                await self.show_form(made["next_form"])
                return
            start = {
                "to": made["to"], "at": made["at"], "title": made["title"],
                "body": made["body"], "send_type": made["send_type"],
                "heading": form["title"], "by_number": False, "note": "",
                "form": {"id": key, "values": values, "reply_to": reply_to}}
            if reply_to:
                # Addressed and titled as any reply (SR to a BBS message number).
                reply = await self.app.command("mail_reply_start", ref=reply_to,
                                               quoted=False, all=False)
                if reply:
                    start.update(to=reply["to"], title=reply["title"], send_type=reply["send_type"],
                                 by_number=reply["by_number"], note=reply["note"],
                                 heading=reply["heading"])
            self.show_writer(start, reply_to)

        page = FormPage(self, start, next_)
        self._writing = {"form": page}
        self.reader = None
        self.toolbar.show(False)
        self.control.content = page.control()
        self.app.page.update()

    async def show_radiogram(self, ics213: bool = False) -> None:
        """The radiogram form, in the writer's place (`radiogram.py`)."""
        from .radiogram import RadiogramForm

        start = await self.app.command("radiogram_start", ics213=ics213)
        if start is None:
            return
        form = RadiogramForm(self, start, ics213)
        self._writing = {"radiogram": form}
        self.reader = None
        self.toolbar.show(False)
        self.control.content = form.control()
        self.app.page.update()

    async def _send_receive(self, _e) -> None:
        if self.app.state.mail_running:
            # Stopping never asks (module docstring).
            if await self.app.command("mail_cancel"):
                sheets.snack(self.app.page, "Cancelling Send/Receive...")
            return
        folder = self.folder
        app = self.app

        def run(name: str, **args):
            async def go() -> None:
                await app.command(name, **args)
            return go

        # What G and I do on the terminal's Mail, Bulletins and Files tabs.
        if folder.startswith("Files"):
            sheets.confirm(app.page, "Get files from the Home BBS?",
                           "The station connects by radio, lists the BBS's files, and "
                           "asks here which to download.", "Get files", run("get_files"))
        elif folder.startswith("Bulletins"):
            sheets.choose(app.page, "Get bulletins?",
                          "The station gets new bulletins in the categories you chose "
                          "from the Home BBS.",
                          [("By Internet", run("get_bulletins", internet=True)),
                           ("By radio", run("get_bulletins"))])
        else:
            sheets.choose(app.page, "Send and receive mail?",
                          "The station sends the Outbox and reads new mail: by radio, "
                          "or over the Internet with no transmitting.",
                          [("By Internet", run("send_receive", folder=folder, internet=True)),
                           ("By radio", run("send_receive", folder=folder))])
