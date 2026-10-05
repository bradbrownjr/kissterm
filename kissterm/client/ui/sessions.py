"""Sessions: the terminal, on a phone. One swipeable page per session (a
node, a BBS), the text as the station filtered it, and a line to type.

**Typing sends only on Send** (the keyboard's send key or the button),
the deliberate commit the terminal's Enter is; the line shows in the
session when the station's `LineSent` comes back, not before
(`client/state.py`). Swiping between sessions changes the page and
nothing else.

**Connect and Disconnect ask first**: a phone is easily mis-tapped, and
both put a frame on the air. A contact in the Connect sheet fills the
field (`AGENTS.md`: suggestions fill, never send).
"""

from __future__ import annotations

import flet as ft

from . import sheets
from .text import MONO, runs, split_lines

#: Lines kept on screen per session; the station keeps the transcript.
MAX_LINES = 2000


def span_style(props: dict) -> ft.TextStyle:
    return ft.TextStyle(
        color=props.get("color"), bgcolor=props.get("bgcolor"),
        weight=ft.FontWeight.BOLD if props.get("bold") else None,
        italic=props.get("italic") or None,
        decoration=ft.TextDecoration.UNDERLINE if props.get("underline") else None)


def line_control(text: str, spans: list, *, outgoing: bool = False) -> ft.Text:
    if outgoing:
        return ft.Text(text, font_family=MONO, size=13, selectable=True,
                       text_align=ft.TextAlign.LEFT,
                       color=ft.Colors.PRIMARY, weight=ft.FontWeight.BOLD)
    return ft.Text(spans=[ft.TextSpan(piece, span_style(props)) for piece, props in runs(text, spans)],
                   font_family=MONO, size=13, selectable=True, text_align=ft.TextAlign.LEFT)


class Terminal:
    """One session's text, appended as it arrives."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.list = ft.ListView(expand=True, auto_scroll=True, spacing=0,
                                padding=ft.Padding.all(8))
        self.rendered = 0
        self._tail_text = ""
        self._tail_spans: list = []
        self._tail_outgoing = False
        self._tail_control: ft.Text | None = None

    def sync(self, session) -> None:
        new = session.received - self.rendered
        if new <= 0:
            return
        chunks = list(session.chunks)[-min(new, len(session.chunks)):]
        for chunk in chunks:
            self._append(chunk.text, chunk.spans, chunk.outgoing)
        self.rendered = session.received
        excess = len(self.list.controls) - MAX_LINES
        if excess > 0:
            del self.list.controls[:excess]

    def _append(self, text: str, spans: list, outgoing: bool) -> None:
        if outgoing != self._tail_outgoing and self._tail_text:
            self._close_tail()
        offset = len(self._tail_text)
        text = self._tail_text + text
        spans = self._tail_spans + [[a + offset, b + offset, s] for a, b, s in spans]
        lines = split_lines(text, spans)
        if self._tail_control is not None:
            self.list.controls.remove(self._tail_control)
            self._tail_control = None
        for line, line_spans in lines[:-1]:
            self.list.controls.append(line_control(line, line_spans, outgoing=outgoing))
        tail, tail_spans = lines[-1]
        self._tail_text, self._tail_spans, self._tail_outgoing = tail, tail_spans, outgoing
        if tail:
            self._tail_control = line_control(tail, tail_spans, outgoing=outgoing)
            self.list.controls.append(self._tail_control)

    def _close_tail(self) -> None:
        self._tail_text, self._tail_spans, self._tail_control = "", [], None


class SessionsView:
    def __init__(self, app) -> None:
        self.app = app
        self.terminals: dict[str, Terminal] = {}
        self.keys: list[str] = []
        self.selected = 0
        self.input = ft.TextField(
            expand=True, hint_text="Type to the station", dense=True,
            autocorrect=False, enable_suggestions=False,
            text_style=ft.TextStyle(font_family=MONO),
            capitalization=ft.TextCapitalization.NONE, on_submit=self._send)
        self.pages = ft.Container(expand=True)
        self.header = ft.Row(spacing=0)
        self.send_row = ft.Container(padding=ft.Padding.all(8), content=ft.Row(controls=[
            self.input,
            ft.IconButton(icon=ft.Icons.SEND, tooltip="Send", on_click=self._send)]))
        self.control = ft.Column(expand=True, spacing=0, controls=[
            self.header, self.pages, self.send_row])
        self._rebuild()

    def fab(self):
        # Connect lives in the session header: a floating button would sit
        # on the Send button, where a thumb already is.
        return None

    async def shown(self) -> None:
        pass

    @property
    def current(self) -> str | None:
        return self.keys[self.selected] if self.keys and self.selected < len(self.keys) else None

    # ------------------------------------------------------------------
    def on_state(self, kind: str, data) -> None:
        if kind == "session":
            if data.key not in self.terminals:
                self._rebuild()
            self.terminals[data.key].sync(data)
            self._paint_header()
        elif kind in ("session_closed", "station"):
            self._rebuild()

    def _rebuild(self) -> None:
        sessions = self.app.state.sessions
        current = self.current
        self.keys = list(sessions)
        for key in self.keys:
            terminal = self.terminals.setdefault(key, Terminal(key))
            terminal.sync(sessions[key])
        for key in [k for k in self.terminals if k not in sessions]:
            del self.terminals[key]
        self.selected = self.keys.index(current) if current in self.keys else max(0, len(self.keys) - 1)
        if not self.keys:
            self.pages.content = ft.Container(
                alignment=ft.Alignment.CENTER, padding=ft.Padding.all(24),
                content=ft.Column(tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                  controls=[
                    ft.Icon(ft.Icons.TERMINAL, size=48, color=ft.Colors.OUTLINE),
                    ft.Text("No session. Connect to a node or BBS.", text_align=ft.TextAlign.CENTER),
                    ft.FilledButton(content="Connect", icon=ft.Icons.ADD_LINK,
                                    on_click=self._connect_sheet)]))
        else:
            sessions_by_key = self.app.state.sessions
            self.pages.content = ft.Tabs(
                length=len(self.keys), selected_index=self.selected, expand=True,
                on_change=self._tab_changed,
                content=ft.Column(expand=True, spacing=0, controls=[
                    ft.TabBar(scrollable=True, tabs=[
                        ft.Tab(label=sessions_by_key[k].title) for k in self.keys]),
                    ft.TabBarView(expand=True, controls=[
                        self.terminals[k].list for k in self.keys])]))
        self._paint_header()

    def _paint_header(self) -> None:
        key = self.current
        session = self.app.state.sessions.get(key) if key is not None else None
        self.send_row.visible = session is not None
        if session is None:
            self.header.controls = []
            return
        state = session.state or ("connected" if session.connected else "")
        where = " > ".join(p for p in (session.node, session.application) if p)
        self.header.controls = [
            ft.Container(expand=True, padding=ft.Padding.only(left=16, top=4), content=ft.Text(
                f"{session.title}  {state}  {where}".strip(), size=12, color=ft.Colors.OUTLINE)),
            ft.IconButton(icon=ft.Icons.ADD_LINK, tooltip="Connect",
                          on_click=self._connect_sheet),
            ft.IconButton(icon=ft.Icons.LINK_OFF, tooltip="Disconnect",
                          on_click=self._disconnect)]

    async def _tab_changed(self, e) -> None:
        self.selected = int(e.control.selected_index)
        self._paint_header()
        self.app.page.update()

    # ------------------------------------------------------------------
    async def _send(self, _e) -> None:
        key = self.current
        text = self.input.value or ""
        if key is None:
            sheets.snack(self.app.page, "No session to send to. Connect first.")
            return
        if await self.app.command("send_line", key=key, text=text):
            self.input.value = ""
        self.app.page.update()

    async def _disconnect(self, _e) -> None:
        key = self.current
        if key is None:
            return

        async def go() -> None:
            await self.app.command("disconnect", key=key)

        sheets.confirm(self.app.page, f"Disconnect from {key or 'the session'}?",
                       "Sends a disconnect to the far station.", "Disconnect", go)

    async def _connect_sheet(self, _e) -> None:
        contacts = await self.app.command("addressbook") or []
        target = ft.TextField(label="Station, node or BBS", hint_text="e.g. W1AW-7",
                              capitalization=ft.TextCapitalization.CHARACTERS,
                              autocorrect=False, enable_suggestions=False, autofocus=True)
        by_target = {c.get("target", "").upper(): c for c in contacts if c.get("target")}

        def fill(name: str):
            async def handler(_e) -> None:
                target.value = name
                self.app.page.update()
            return handler

        chips = ft.Row(wrap=True, spacing=6, run_spacing=6, controls=[
            ft.Chip(label=name, on_click=fill(name)) for name in list(by_target)[:12]])

        async def go() -> None:
            name = (target.value or "").strip().upper()
            if not name:
                return
            if name in by_target:
                await self.app.command("connect", entry=by_target[name]["target"])
            else:
                await self.app.command("connect", target=name)

        sheets.form(self.app.page, "Connect", [target, chips] if contacts else [target],
                    "Connect", go, detail="The station asks first if a contact has a reminder.")
