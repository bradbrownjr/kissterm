"""Commands: what to say to the node or BBS this session is talking to, and
the packet glossary (the terminal's command reference, `CommandReferenceScreen`,
and its suggestion strip), over the Terminal's message box.

The station supplies everything (`session_reference`, `session_suggest`,
`glossary`, `session_harvest`, `session_forget_learned`), so what a command
is called, whether it needs the sysop and how far to trust the line
("published", "recalled, unverified") are the terminal's answers.

**A pick or a suggestion fills the message box and never sends**
(AGENTS.md); Send is the commitment. **Asking the node for its list is
opt-in and shows its airtime first** ("Airtime is the scarce resource"):
only the Ask button in the confirmation sends anything.
"""

from __future__ import annotations

import flet as ft

from . import sheets
from .text import MONO

#: Suggestions shown over the message box (the terminal's strip lists 20).
SUGGESTIONS_SHOWN = 5


def _matches(needle: str, command: dict) -> bool:
    needle = needle.strip().lower()
    if not needle:
        return True
    return any(needle in str(part).lower() for part in (
        command["name"], *command["aliases"], command["summary"], command["detail"]))


class ReferenceSheet:
    def __init__(self, view, key: str, data: dict) -> None:
        self.view = view
        self.key = key
        self.data = data
        self.mode = "commands"
        self.needle = ""
        self.rows = ft.Column(tight=True, spacing=0)
        self.search = ft.TextField(label="Search", dense=True, on_change=self._search)
        self.title = ft.Text("", theme_style=ft.TextThemeStyle.TITLE_MEDIUM)
        self.note = ft.Text("", size=12, color=ft.Colors.OUTLINE)
        self.modes = ft.SegmentedButton(
            selected=["commands"], on_change=self._mode_changed,
            segments=[ft.Segment(value="commands", label="Commands"),
                      ft.Segment(value="glossary", label="Glossary")])
        self.buttons = ft.Row(alignment=ft.MainAxisAlignment.END, wrap=True)
        self.status = ft.Text("", size=12)

    @property
    def page(self):
        return self.view.app.page

    async def show(self) -> None:
        await self._paint()
        self.page.show_dialog(sheets.sheet([
            self.title, self.note, self.modes, self.search, self.rows, self.status,
            ft.Text("Choosing one puts it in the message box. Nothing is sent until you "
                    "press Send.", size=12), self.buttons], scrollable=True))

    def _button_row(self) -> list[ft.Control]:
        buttons: list[ft.Control] = [ft.TextButton(content="Close", on_click=self._close)]
        if self.mode == "commands":
            buttons.append(ft.OutlinedButton(content="BBS mail", on_click=self._bbs))
            buttons.append(ft.OutlinedButton(content="Receive file", on_click=self._receive))
            if self.data.get("learned"):
                buttons.append(ft.OutlinedButton(content="Forget learned", on_click=self._forget))
            if self.data.get("can_harvest"):
                buttons.append(ft.OutlinedButton(content="Learn from node", on_click=self._learn))
        return buttons

    async def _paint(self) -> None:
        sections = self.data.get("sections") or []
        first = sections[0] if sections else {"title": "unknown node", "note": ""}
        if self.mode == "glossary":
            self.title.value = "Glossary: packet radio terms"
            self.note.value = "Aimed at an operator who knows radio but not packet."
            terms = await self.view.app.command("glossary", needle=self.needle) or []
            self.rows.controls = [ft.ListTile(
                title=ft.Text(t["name"], weight=ft.FontWeight.BOLD),
                subtitle=ft.Text(t["definition"])) for t in terms] or [
                ft.Text("Nothing matches.", color=ft.Colors.OUTLINE)]
        else:
            self.title.value = f"Commands: {first['title']}"
            self.note.value = first["note"]
            rows: list[ft.Control] = []
            for index, section in enumerate(sections):
                found = [c for c in section["commands"] if _matches(self.needle, c)]
                if index and found:
                    rows.append(ft.Text(section["title"], weight=ft.FontWeight.BOLD))
                rows += [self._row(c) for c in found]
            self.rows.controls = rows or [ft.Text("Nothing matches.", color=ft.Colors.OUTLINE)]
        self.buttons.controls = self._button_row()

    def _row(self, command: dict) -> ft.Control:
        names = " / ".join([command["name"], *command["aliases"]])
        context = {"node": "Node", "bbs": "BBS"}.get(command["context"], command["context"])
        if command["sysop"]:
            context += ", sysop"
        return ft.ListTile(
            title=ft.Text(names),
            subtitle=ft.Text(f"{command['usage']}\n{command['summary']}".strip(),
                             font_family=MONO, size=11),
            trailing=ft.Text(f"{context}\n{command['source']}", size=10,
                             color=ft.Colors.OUTLINE, text_align=ft.TextAlign.RIGHT),
            on_click=self._picker(command["name"]))

    def _picker(self, text: str):
        async def pick(_e) -> None:
            self.page.pop_dialog()
            self.view.input.value = text
            self.page.update()
        return pick

    async def _search(self, e) -> None:
        self.needle = e.control.value or ""
        await self._paint()
        self.page.update()

    async def _mode_changed(self, e) -> None:
        selected = list(e.control.selected or [])
        if selected and selected[0] != self.mode:
            self.mode = selected[0]
            self.needle = self.search.value = ""
            self.search.label = "Search glossary" if self.mode == "glossary" else "Search"
            await self._paint()
            self.page.update()

    async def _bbs(self, _e) -> None:
        """The terminal's BBS mail helper: a documented BBS command with
        its message number or callsign filled in, put in the message box
        and not sent."""
        self.page.pop_dialog()
        await BbsHelper(self.view).show()

    async def _receive(self, _e) -> None:
        """The terminal's File transfer dialog, in download mode
        (`transfer.py`): asks first."""
        from . import transfer

        self.page.pop_dialog()
        transfer.ask(self.view.app, current=self.key)

    async def _close(self, _e=None) -> None:
        self.page.pop_dialog()

    async def _refresh(self) -> None:
        self.data = await self.view.app.command("session_reference", key=self.key) or self.data
        await self._paint()
        self.page.update()

    # -- opt-in airtime --------------------------------------------------
    async def _learn(self, _e) -> None:
        """Ask the node for its list: never without this confirmation, which
        says what it costs; the choice of context is the operator's (the
        station's guess from the prompt is only the default)."""
        low, high = self.data.get("airtime") or ("", "")
        context = ft.Dropdown(
            label="Which list", value=self.data.get("context") or "node", dense=True,
            options=[ft.DropdownOption(key="node", text="Node commands"),
                     ft.DropdownOption(key="bbs", text="BBS commands"),
                     ft.DropdownOption(key="application", text="Other application commands")])

        async def ask() -> None:
            self.status.value = "Asking the node..."
            self.page.update()
            result = await self.view.app.command(
                "session_harvest", key=self.key, context=context.value or "node")
            await self._reopen(
                f"Captured {result['captured']} byte(s); learned {len(result['learned'])} "
                "command(s)." if result and result.get("captured")
                else "No reply was captured from the node.")

        sheets.form(
            self.page, f"Ask {self.data.get('peer') or 'the node'} for its command list?",
            [context], "Ask", ask,
            detail=f"This is real airtime on a shared channel: anywhere from {low} to {high}, "
                   "during which nobody else on the frequency can transmit. A marginal link "
                   "can take longer. The result is kept, so this is asked at most once per "
                   "node.")

    async def _forget(self, _e) -> None:
        count = self.data.get("learned", 0)
        node = self.data.get("learned_node", "")

        async def go() -> None:
            await self.view.app.command("session_forget_learned", key=self.key)
            await self._reopen(f"Forgot the commands learned from {node}.")

        sheets.confirm(
            self.page, f"Forget {count} learned command(s) for {node}?",
            "The shipped reference stays. Learning them again means asking the node, which "
            "is airtime on a shared channel.", "Forget", go, danger=True)

    async def _reopen(self, status: str) -> None:
        self.data = await self.view.app.command("session_reference", key=self.key) or self.data
        self.status.value = status
        await self.show()


class Suggestions:
    """The few commands matching what is being typed, over the message box
    (the terminal's suggestion strip); a tap fills the box. Never sends."""

    def __init__(self, view) -> None:
        self.view = view
        self.column = ft.Column(tight=True, spacing=0, visible=False)

    async def typed(self, text: str) -> None:
        key = self.view.current
        found = []
        if key and text.strip():
            found = await self.view.app.command("session_suggest", key=key, text=text) or []
        if (self.view.input.value or "") != text:
            return  # typing moved on while the station answered
        self.column.controls = [ft.ListTile(
            dense=True, title=ft.Text(c["name"], font_family=MONO, size=13),
            subtitle=ft.Text(c["summary"], size=11, max_lines=1,
                             overflow=ft.TextOverflow.ELLIPSIS) if c["summary"] else None,
            on_click=self._filler(c["name"])) for c in found[:SUGGESTIONS_SHOWN]]
        self.column.visible = bool(self.column.controls)
        self.view.app.page.update()

    def _filler(self, name: str):
        async def fill(_e) -> None:
            self.view.input.value = name
            self.column.visible = False
            self.view.app.page.update()
        return fill


class BbsHelper:
    """One documented BBS mail command with its arguments (`bbs_helpers`,
    `bbs_render`): the preview is the station's; Put in message box fills
    the box and sends nothing."""

    def __init__(self, view) -> None:
        self.view = view
        self.profiles: list[dict] = []
        self.macro: dict = {}
        self.pick = ft.Dropdown(label="Command", dense=True, on_select=self._picked)
        self.number = ft.TextField(label="Message number", dense=True,
                                   keyboard_type=ft.KeyboardType.NUMBER, on_change=self._edited)
        self.callsign = ft.TextField(label="Recipient callsign", dense=True,
                                     capitalization=ft.TextCapitalization.CHARACTERS,
                                     on_change=self._edited)
        self.preview = ft.Text("", font_family=MONO, size=12)
        self.note = ft.Text("", size=12, color=ft.Colors.OUTLINE)
        self.text = ""

    @property
    def page(self):
        return self.view.app.page

    async def show(self) -> None:
        self.profiles = await self.view.app.command("bbs_helpers") or []
        macros = [(p["id"], m) for p in self.profiles for m in p["macros"]]
        if not macros:
            sheets.snack(self.page, "No BBS commands are shipped.", error=True)
            return
        self.pick.options = [ft.DropdownOption(key=f"{pid}/{m['id']}", text=m["label"])
                             for pid, m in macros]
        first_profile, self.macro = macros[0]
        self.profile_id = first_profile
        self.pick.value = f"{first_profile}/{self.macro['id']}"
        await self._sync()
        self.page.show_dialog(sheets.sheet([
            ft.Text("BBS mail", theme_style=ft.TextThemeStyle.TITLE_MEDIUM), self.note,
            self.pick, self.number, self.callsign, self.preview,
            ft.Text("Putting it in the message box does not send it. Review it, then press "
                    "Send.", size=12),
            ft.Row(alignment=ft.MainAxisAlignment.END, controls=[
                ft.TextButton(content="Cancel", on_click=self._close),
                ft.FilledButton(content="Put in message box", on_click=self._use)])],
            scrollable=True))

    async def _picked(self, e) -> None:
        pid, mid = (e.control.value or "/").split("/", 1)
        self.profile_id = pid
        profile = next(p for p in self.profiles if p["id"] == pid)
        self.macro = next(m for m in profile["macros"] if m["id"] == mid)
        await self._sync()
        self.page.update()

    async def _edited(self, _e) -> None:
        await self._render()
        self.page.update()

    async def _sync(self) -> None:
        profile = next(p for p in self.profiles if p["id"] == self.profile_id)
        self.note.value = (f"{profile['name']}: {self.macro['summary']} "
                           f"({self.macro['confidence']}). {profile['note']}")
        self.number.visible = "number" in self.macro["fields"]
        self.callsign.visible = "callsign" in self.macro["fields"]
        await self._render()

    async def _render(self) -> None:
        result = await self.view.app.command(
            "bbs_render", profile=self.profile_id, macro=self.macro["id"],
            values={"number": self.number.value or "", "callsign": self.callsign.value or ""})
        self.text = (result or {}).get("text", "")
        error = (result or {}).get("error", "")
        self.preview.value = f"Will put in the message box: {self.text}" if self.text else error
        self.preview.color = None if self.text else ft.Colors.ERROR

    async def _use(self, _e) -> None:
        if not self.text:
            return
        self.page.pop_dialog()
        self.view.input.value = self.text
        self.page.update()

    async def _close(self, _e) -> None:
        self.page.pop_dialog()
