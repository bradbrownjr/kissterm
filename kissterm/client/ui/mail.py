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

**A message's routing is one small line** under the date (`Routed W1BKW
> WS1EC`, `routing_section`); a tap shows the `R:` lines.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime

import flet as ft

from . import sheets
from .text import MONO

#: Seconds per step of the turning icon and the counting dots.
TICK = 0.4


def routing_section(routes: list[str], bbses: list[str]) -> list[ft.Control]:
    """One small line under the date, `Routed W1BKW > WS1EC` (`bbses`,
    the station's `route_bbses`); a tap shows
    the `R:` lines themselves (operator, 2026-10-06: "Routing takes more
    space than the message ... one small tight small-font line under the
    date"; earlier the same day a recipient took a routing line for the
    sender's address, so the lines stay folded)."""
    if not routes:
        return []
    lines = ft.Text("\n".join(routes), font_family=MONO, size=11, selectable=True,
                    color=ft.Colors.OUTLINE, visible=False)
    bbses = bbses or [f"{len(routes)} BBS"]

    def toggle(_e) -> None:
        lines.visible = not lines.visible
        lines.update()

    return [ft.Container(on_click=toggle,
                         content=ft.Text("Routed " + " > ".join(bbses), size=12,
                                         color=ft.Colors.OUTLINE)),
            lines]


#: Message types the phone writes, as the terminal's Type list: the last
#: two open the radiogram form (`radiogram.py`); Winlink forms are the
#: terminal's for now.
RADIOGRAM, RADIOGRAM_ICS213 = "radiogram", "radiogram-ics213"
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


# The page's button sits 16 px in from the body's corner and is 56 px
# across; the mini (40 px) Write rides above it, its right edge on the
# same line, both hugging the screen's edge (operator, 2026-10-06: "align
# it right to have the buttons hug the edge of the screen").
WRITE_RIGHT = 16
WRITE_BOTTOM = 16 + 56 + 16


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
        self.switch = ft.SegmentedButton(
            selected=["Mail"], show_selected_icon=False, on_change=self._switched,
            segments=[ft.Segment(value=value, label=ft.Text(value), icon=ft.Icon(icon))
                      for value, _title, icon, _sel in SECTIONS])
        self.folders = ft.Dropdown(dense=True, expand=True, on_select=self._folder_changed,
                                   options=[])
        #: Write: the terminal's Insert, on a Mail folder. A small pencil
        #: stacked over Send/Receive, no label (operator, 2026-10-06).
        self.write_button = ft.FloatingActionButton(
            icon=ft.Icons.EDIT, tooltip="Write", mini=True, on_click=self._write_new,
            right=WRITE_RIGHT, bottom=WRITE_BOTTOM)
        #: Categories: the terminal's S on Bulletins, on a Bulletins folder.
        self.categories_button = ft.FilledTonalButton(
            content="Categories", icon=ft.Icons.CHECKLIST, on_click=self._categories)
        self._writing: dict | None = None
        self.list = ft.ListView(expand=True)
        self.reader: ft.Control | None = None
        self.control = ft.Container(expand=True)
        self.activity = ft.Text("", color=ft.Colors.PRIMARY)
        self.sync_icon = ft.Icon(ft.Icons.SYNC, rotate=0,
                                 animate_rotation=ft.Animation(int(TICK * 1000), ft.AnimationCurve.LINEAR))
        self.button = ft.FloatingActionButton(content=self.sync_icon, on_click=self._send_receive)
        self._ticking = False
        self._dots = 0
        self._paint_button()
        self._show_list()

    def fab(self):
        if self.reader is not None or self._writing is not None:
            return None
        return self.button

    def _paint_button(self) -> None:
        running = self.app.state.mail_running
        what = ("Get files" if self.folder.startswith("Files")
                else "Get bulletins" if self.folder.startswith("Bulletins") else "Send/Receive")
        self.button.tooltip = "Running: tap to cancel" if running else what

    async def shown(self) -> None:
        await self.reload()

    def on_state(self, kind: str, data) -> None:
        if kind == "stale" and data == "mail":
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
        self.control.content = ft.Stack(expand=True, controls=[ft.Column(
            expand=True, spacing=0, controls=[
                ft.Container(padding=ft.Padding.only(left=12, right=12, top=6),
                             content=ft.Row(controls=[self.switch],
                                            alignment=ft.MainAxisAlignment.CENTER),
                             visible=self.switch.visible),
                ft.Container(padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                             content=ft.Row(controls=[self.folders, self.categories_button])),
                *([ft.Container(padding=ft.Padding.symmetric(horizontal=16, vertical=4),
                                content=self.activity)] if self.app.state.activity else []),
                self.list]), self.write_button])

    async def reload(self) -> None:
        folders = section_folders(await self.app.command("mail_folders") or [], self.section)
        if not in_section(self.folder, self.section) or (folders and self.folder not in folders):
            self.folder = default_folder(folders, self.section)
        self.folders.options = [ft.DropdownOption(key=f, text=folder_label(f, self.section))
                                for f in folders] or [
            ft.DropdownOption(key=self.folder, text=folder_label(self.folder, self.section))]
        self._paint_button()
        self.folders.value = self.folder
        messages = await self.app.command("mail_list", folder=self.folder) or []
        self.list.controls = [self._row(m) for m in messages] or [ft.Container(
                padding=ft.Padding.all(24),
                content=ft.Text("Nothing in this folder.", color=ft.Colors.OUTLINE))]
        if self.reader is None and self._writing is None:
            self._paint_toolbar()
        self.app.page.update()

    def _paint_toolbar(self) -> None:
        self.write_button.visible = in_section(self.folder, "Mail")
        self.categories_button.visible = in_section(self.folder, "Bulletins")

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
                    [every, ft.Column(tight=True, spacing=0, controls=boxes)],
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
                    m.get("sender") or "", when(m.get("date")), self._via(m)) if part), size=12),
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
        self.switch.visible = not getattr(self.app, "wide", False)
        self.switch.selected = [self.section]

    def set_section(self, section: str) -> None:
        """Show Mail, Bulletins or Files, at the folder last shown there."""
        if section == self.section:
            return
        self._last[self.section] = self.folder
        self.section = section
        self.folder = self._last.get(section, "")
        if self.reader is None and self._writing is None:
            self._show_list()

    async def _switched(self, e) -> None:
        picked = list(e.control.selected or [])
        if not picked:  # a tap on the selected segment: stay
            self.paint_switch()
            self.app.page.update()
            return
        self.set_section(picked[0])
        self.app.section_changed()
        await self.reload()

    async def _folder_changed(self, e) -> None:
        self.folder = e.control.value
        self._paint_button()
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
                 ("Date", when(message.get("date")))) if value]
        self.reader = ft.Column(expand=True, spacing=0, controls=[
            ft.Row(controls=[ft.IconButton(icon=ft.Icons.ARROW_BACK, tooltip="Back to the list",
                                           on_click=self._back),
                             ft.Text(message.get("subject", ""), expand=True, max_lines=2,
                                     theme_style=ft.TextThemeStyle.TITLE_MEDIUM)]),
            ft.Row(spacing=0, alignment=ft.MainAxisAlignment.END,
                   controls=self.reader_actions(ref, message)),
            ft.Container(expand=True, padding=ft.Padding.all(16), content=ft.Column(
                scroll=ft.ScrollMode.AUTO, controls=[
                    ft.Column(spacing=2, tight=True, controls=[
                        ft.Text("\n".join(head), color=ft.Colors.OUTLINE, selectable=True),
                        *routing_section(message.get("routing") or [],
                                         message.get("routed") or [])]),
                    ft.Divider(),
                    ft.Text(message.get("body", ""), selectable=True)]))])
        self.control.content = self.reader
        self.app.page.floating_action_button = None
        self.app.page.update()

    def reader_actions(self, ref: str, message: dict) -> list[ft.Control]:
        """Reply, Reply all, Reply with quote, Delete or Restore: the
        terminal's R, A, Q, Delete and U."""
        def reply(quoted: bool | None, everyone: bool = False):
            async def go(_e) -> None:
                await self.reply(ref, quoted=quoted, everyone=everyone)
            return go

        async def discard(_e) -> None:
            await self.discard(ref)
            await self._back(None)

        actions: list[ft.Control] = []
        if not self.folder.startswith("Files"):
            actions.append(ft.IconButton(icon=ft.Icons.REPLY, tooltip="Reply",
                                         on_click=reply(None)))
            if message.get("reply_all"):
                actions.append(ft.IconButton(icon=ft.Icons.REPLY_ALL, tooltip="Reply all",
                                             on_click=reply(None, everyone=True)))
            actions.append(ft.IconButton(icon=ft.Icons.FORMAT_QUOTE, tooltip="Reply with quote",
                                         on_click=reply(True)))
        if in_deleted(self.folder):
            actions.append(ft.IconButton(icon=ft.Icons.RESTORE_FROM_TRASH, tooltip="Restore",
                                         on_click=discard))
        else:
            actions.append(ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip="Delete",
                                         on_click=discard))
        return actions

    async def _back(self, _e) -> None:
        self._writing = None
        self._show_list()
        self.app.page.floating_action_button = self.fab()
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

        def kind_changed(_e) -> None:
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
            result = await self.app.command(
                "mail_write", to=to.value or "", at=at.value or "", title=title.value or "",
                body=body.value or "", send_type=kind.value or send_type, reply_to=reply_to)
            if not result:
                return
            if result.get("problems"):
                problems.value = "\n".join(result["problems"])
                self.app.page.update()
                return
            where = result["folder"].removeprefix("Mail/").replace("/", " ")
            sheets.snack(self.app.page, f"Saved to {where}. Send/Receive sends it.")
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
        self.app.page.floating_action_button = None
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
        self.control.content = form.control()
        self.app.page.floating_action_button = None
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
