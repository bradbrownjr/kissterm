"""Terminal (once called Sessions): the terminal, on a phone. One
swipeable page per session (a node, a BBS), the text as the station filtered it, and a line to type.

**Typing sends only on Send** (the keyboard's send key or the button),
the deliberate commit the terminal's Enter is; the line shows in the
session when the station's `LineSent` comes back, not before
(`client/state.py`). Swiping between sessions changes the page and
nothing else.

**Connect and Disconnect ask first**: a phone is easily mis-tapped, and
both put a frame on the air. A contact in the Connect sheet fills the
field (`AGENTS.md`: suggestions fill, never send).

**The terminal gets the height** (operator, 2026-10-06, on a phone):
there is no row above it repeating the session's name. The tab strip
names the sessions and ends in Connect; Disconnect is a chip beside the
transmit switch (`shell.py`) while the shown session is connected.

**A connect shows at once, and can be cancelled** (same day: the screen
"quietly locks" until the link is up). The connect runs in the
background (`ClientApp.start_connect`), Terminal comes to the front, and
while the station says a connect is in progress (`ConnectingChanged`)
an hourglass lies over the session with a Cancel that needs no
confirming: stopping never transmits more.
"""

from __future__ import annotations

from datetime import datetime

import flet as ft

from . import sheets
from .reference import ReferenceSheet, Suggestions
from .text import MONO, MONO_BOLD, Look, runs, split_lines

#: Lines kept on screen per session; the station keeps the transcript.
MAX_LINES = 2000


def span_style(props: dict, look: Look) -> ft.TextStyle:
    # Bold is its own family: 0xProto Bold, not a thickened Regular.
    return ft.TextStyle(
        color=look.ansi(props.get("color")), bgcolor=props.get("bgcolor"),
        font_family=MONO_BOLD if props.get("bold") else None,
        italic=props.get("italic") or None,
        decoration=ft.TextDecoration.UNDERLINE if props.get("underline") else None)


def line_control(text: str, spans: list, look: Look, *, outgoing: bool = False) -> ft.Text:
    if outgoing:
        return ft.Text(text, font_family=MONO_BOLD, size=13, selectable=True,
                       text_align=ft.TextAlign.LEFT, color=look.outgoing)
    return ft.Text(spans=[ft.TextSpan(piece, span_style(props, look)) for piece, props in runs(text, spans)],
                   font_family=MONO, size=13, selectable=True, text_align=ft.TextAlign.LEFT,
                   color=look.color)


def _state_icon(session) -> str:
    if session.connecting:
        return ft.Icons.HOURGLASS_TOP
    return ft.Icons.LINK if session.connected else ft.Icons.LINK_OFF


class Terminal:
    """One session's text, appended as it arrives, on a panel in the
    device's chosen `Look`."""

    def __init__(self, key: str, look: Look | None = None) -> None:
        self.key = key
        self.look = look or Look()
        self.list = ft.ListView(expand=True, auto_scroll=True, spacing=0,
                                padding=ft.Padding.all(10))
        self.panel = ft.Container(expand=True, content=self.list, bgcolor=self.look.bgcolor)
        #: The hourglass over the panel while a connect is in progress.
        self.waiting = ft.Container(visible=False, expand=True,
                                    bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
                                    alignment=ft.Alignment.CENTER)
        self.control = ft.Stack(expand=True, controls=[self.panel, self.waiting])
        #: Lines received before the operator cleared this view; the station
        #: keeps its transcript (Ctrl+L in the terminal clears the view only).
        self.cleared = 0
        self._reset()

    def clear(self, session) -> None:
        """Empty the view; later lines still arrive (`TerminalPane.clear`)."""
        self.cleared = session.received
        self._reset()
        self.rendered = session.received

    def show_connecting(self, session, on_cancel) -> None:
        """The hourglass and Cancel while `session` is connecting."""
        self.waiting.visible = session.connecting
        if not session.connecting:
            return
        self.waiting.content = ft.Card(content=ft.Container(
            padding=ft.Padding.all(20), content=ft.Column(
                tight=True, spacing=12, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(ft.Icons.HOURGLASS_TOP, size=40),
                    ft.Text(f"Connecting to {session.title}...",
                            theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                    ft.OutlinedButton(content="Cancel", icon=ft.Icons.CLOSE,
                                      on_click=on_cancel)])))

    def _reset(self) -> None:
        self.list.controls.clear()
        self.rendered = 0
        self._tail_text = ""
        self._tail_spans: list = []
        self._tail_outgoing = False
        self._tail_control: ft.Text | None = None

    def restyle(self, look: Look, session) -> None:
        """Draw everything again in `look` (the lines still held)."""
        self.look = look
        self.panel.bgcolor = look.bgcolor
        self._reset()
        self.rendered = max(session.received - len(session.chunks), self.cleared)
        self.sync(session)

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
            self.list.controls.append(line_control(line, line_spans, self.look, outgoing=outgoing))
        tail, tail_spans = lines[-1]
        self._tail_text, self._tail_spans, self._tail_outgoing = tail, tail_spans, outgoing
        if tail:
            self._tail_control = line_control(tail, tail_spans, self.look, outgoing=outgoing)
            self.list.controls.append(self._tail_control)

    def _close_tail(self) -> None:
        self._tail_text, self._tail_spans, self._tail_control = "", [], None


class BroadcastPage:
    """The Broadcast tab: the first page, always there (the terminal's
    Broadcast tab). What the station heard to CQ, QST, ALL and the like,
    and what this station sent; a tap on a callsign fills the Connect
    sheet with it and sends nothing (`SessionsView._connect_sheet`)."""

    def __init__(self, view) -> None:
        self.view = view
        self.list = ft.ListView(expand=True, auto_scroll=True, spacing=0,
                                padding=ft.Padding.all(10))
        self.control = ft.Container(expand=True, content=self.list,
                                    bgcolor=view.app.look.bgcolor)
        #: Lines at or before this time are hidden (a view clear, as Ctrl+L
        #: on the terminal's Broadcast tab); the station keeps them.
        self.cleared_at = -1.0
        self.heard: list[dict] = []

    def clear(self) -> None:
        self.cleared_at = max((h["at"] for h in self.heard), default=self.cleared_at)
        self.paint(self.heard)

    def paint(self, heard: list[dict]) -> None:
        look = self.view.app.look
        self.control.bgcolor = look.bgcolor
        self.heard = heard
        rows = []
        for h in [h for h in heard if h["at"] > self.cleared_at][-200:]:
            stamp = datetime.fromtimestamp(h["at"]).strftime("%H:%M")
            spans = [ft.TextSpan(f"{stamp} ")]
            if h["own"]:
                spans.append(ft.TextSpan("you", ft.TextStyle(font_family=MONO_BOLD)))
            else:
                spans.append(ft.TextSpan(
                    h["source"], ft.TextStyle(decoration=ft.TextDecoration.UNDERLINE),
                    on_click=self.view.dial_filler(h["source"])))
            spans.append(ft.TextSpan(f" > {h['to']}: {h['text']}"))
            rows.append(ft.Text(spans=spans, font_family=MONO, size=13, color=look.color))
        self.list.controls = rows or [ft.Text(
            "Nothing heard yet. A line typed below goes to ALL once (CQ: or QST: first "
            "to address it elsewhere); nothing is sent until you press Send.",
            size=12, color=ft.Colors.OUTLINE)]


class SessionsView:
    def __init__(self, app) -> None:
        self.app = app
        self.terminals: dict[str, Terminal] = {}
        self.broadcast = BroadcastPage(self)
        #: False until the operator picks a tab: until then a session that
        #: appears (a late join's replay, an incoming call) comes forward.
        self._chose = False
        self.keys: list[str] = []
        self.selected = 0
        self.input = ft.TextField(
            expand=True, hint_text="Type to the station", dense=True,
            autocorrect=False, enable_suggestions=False,
            text_style=ft.TextStyle(font_family=MONO),
            capitalization=ft.TextCapitalization.NONE, on_submit=self._send,
            on_change=self._typed)
        self.suggestions = Suggestions(self)
        self.pages = ft.Container(expand=True)
        self.send_row = ft.Container(padding=ft.Padding.all(8), content=ft.Row(controls=[
            # The terminal's command reference (F1): what to say to this node.
            ft.IconButton(icon=ft.Icons.MENU_BOOK, tooltip="Commands",
                          on_click=self._commands),
            self.input,
            ft.IconButton(icon=ft.Icons.SEND, tooltip="Send", on_click=self._send)]))
        self.control = ft.Column(expand=True, spacing=0, controls=[
            self.pages, self.suggestions.column, self.send_row])
        self._rebuild()

    def fab(self):
        # Connect ends the tab strip: a floating button would sit on the
        # Send button, where a thumb already is.
        return None

    async def shown(self) -> None:
        await self.refresh_broadcast()

    async def refresh_broadcast(self) -> None:
        info = await self.app.command("broadcast_info", text="")
        if info:
            self.broadcast.paint(info["heard"])
            self.app.page.update()

    def dial_filler(self, call: str):
        async def handler(_e) -> None:
            await self._connect_sheet(None, target=call)
        return handler

    def restyle(self) -> None:
        """Every session again in the app's current `Look`."""
        sessions = self.app.state.sessions
        for key, terminal in self.terminals.items():
            if key in sessions:
                terminal.restyle(self.app.look, sessions[key])

    @property
    def current(self) -> str | None:
        """The shown page's key; "" is the Broadcast tab."""
        return self.keys[self.selected] if self.keys and self.selected < len(self.keys) else None

    @property
    def current_session(self):
        key = self.current
        return self.app.state.sessions.get(key) if key is not None else None

    # ------------------------------------------------------------------
    def on_state(self, kind: str, data) -> None:
        if kind == "session":
            follow = self.app.follow_next_session and (
                data.key not in self.terminals or data.connecting)
            if follow:
                # The session this client just asked for comes to the front.
                self.app.follow_next_session = False
            if data.key not in self.terminals or follow:
                forward = follow or (data.key not in self.terminals and not self._chose)
                self._rebuild(select=data.key if forward else None)
            self.terminals[data.key].sync(data)
            self.terminals[data.key].show_connecting(data, self._canceller(data.key))
            self._paint_tabs()
        elif kind in ("session_closed", "station"):
            self._rebuild()
        elif kind == "stale" and data == "broadcast":
            self.app.page.run_task(self.refresh_broadcast)

    def _rebuild(self, select: str | None = None) -> None:
        sessions = self.app.state.sessions
        current = select if select is not None else self.current
        #: Broadcast ("") is always the first page; sessions follow it.
        self.keys = [""] + list(sessions)
        for key in sessions:
            terminal = self.terminals.setdefault(key, Terminal(key, self.app.look))
            terminal.sync(sessions[key])
            terminal.show_connecting(sessions[key], self._canceller(key))
        for key in [k for k in self.terminals if k not in sessions]:
            del self.terminals[key]
        self.selected = self.keys.index(current) if current in self.keys else len(self.keys) - 1
        self.send_row.visible = True
        self.tab_bar = ft.TabBar(scrollable=True, tabs=[], expand=True,
                                 tab_alignment=ft.TabAlignment.START)
        self.pages.content = ft.Tabs(
            length=len(self.keys), selected_index=self.selected, expand=True,
            on_change=self._tab_changed,
            content=ft.Column(expand=True, spacing=0, controls=[
                ft.Row(spacing=0, controls=[
                    self.tab_bar,
                    ft.IconButton(icon=ft.Icons.RSS_FEED, tooltip="Send beacon",
                                  on_click=self._send_beacon),
                    ft.IconButton(icon=ft.Icons.CLEAR_ALL, tooltip="Clear",
                                  on_click=self._clear),
                    ft.IconButton(icon=ft.Icons.ADD_LINK, tooltip="Connect",
                                  on_click=self._connect_sheet)]),
                ft.TabBarView(expand=True, controls=[
                    self.broadcast.control if k == "" else self.terminals[k].control
                    for k in self.keys])]))
        self._paint_tabs()
        self.app.paint_actions()

    def _paint_tabs(self) -> None:
        """Each tab: the session's name, and an icon for its state."""
        if getattr(self, "tab_bar", None) is None:
            return
        sessions = self.app.state.sessions
        # The icon beside the name, not above it: a taller strip is the
        # height the terminal was given back.
        self.tab_bar.tabs = [ft.Tab(label=ft.Row(tight=True, spacing=6, controls=[
            ft.Icon(ft.Icons.CAMPAIGN if k == "" else _state_icon(sessions[k]), size=16),
            ft.Text("Broadcast" if k == "" else sessions[k].title)]))
            for k in self.keys]
        self.app.paint_actions()

    async def _tab_changed(self, e) -> None:
        self._chose = True
        self.selected = int(e.control.selected_index)
        self.app.paint_actions()
        self.app.page.update()

    async def _send_beacon(self, _e) -> None:
        """Which beacon: the packet beacon text (the terminal's Session >
        Send beacon) or an APRS position (APRS > Send position); each its
        own button, asked first (operator, 2026-10-06: "Beacon ... should ask Packet or APRS"; on
        Terminal, not More, since 2026-10-08)."""
        async def packet() -> None:
            await self.app.command("beacon_now")

        async def aprs() -> None:
            await self.app.command("aprs_position")

        sheets.choose(self.app.page, "Send a beacon now?",
                      "Packet sends the station's beacon text once, and only while "
                      "transmit is on. APRS sends one position report. Neither "
                      "changes a beacon timer.",
                      [("APRS position", aprs), ("Packet beacon", packet)])

    async def _clear(self, _e) -> None:
        """Clear what this tab shows (the terminal's Ctrl+L): the view only."""
        key = self.current
        if key == "":
            self.broadcast.clear()
        elif key in self.terminals and key in self.app.state.sessions:
            self.terminals[key].clear(self.app.state.sessions[key])
        self.app.page.update()

    def _canceller(self, key: str):
        async def cancel(_e) -> None:
            # No confirmation: cancelling sends no more SABMs, never one more.
            await self.app.command("disconnect", key=key)
        return cancel

    # ------------------------------------------------------------------
    async def _typed(self, e) -> None:
        if not self.current:
            # Broadcast has no node command list to suggest from.
            self.suggestions.column.visible = False
            self.app.page.update()
            return
        await self.suggestions.typed(e.control.value or "")

    async def _commands(self, _e) -> None:
        key = self.current
        if not key:
            sheets.snack(self.app.page, "Broadcast has no command list. Connect to a node first.")
            return
        data = await self.app.command("session_reference", key=key)
        if data:
            await ReferenceSheet(self, key, data).show()

    async def _send(self, _e) -> None:
        key = self.current
        text = self.input.value or ""
        if key is None:
            return
        if key == "":
            # Broadcast: the station reads a QST:/ALL: prefix; Send is the commitment.
            result = await self.app.command("broadcast_send", to="", text=text)
            if result and result.get("error"):
                sheets.snack(self.app.page, result["error"], error=True)
            elif result:
                self.input.value = ""
            self.app.page.update()
            return
        if await self.app.command("send_line", key=key, text=text):
            self.input.value = ""
            self.suggestions.column.visible = False
        self.app.page.update()

    async def disconnect(self, _e=None) -> None:
        """The Disconnect chip beside the transmit switch (`shell.py`)."""
        key = self.current
        if not key:
            return

        async def go() -> None:
            await self.app.command("disconnect", key=key)

        sheets.confirm(self.app.page, f"Disconnect from {key or 'the session'}?",
                       "Sends a disconnect to the far station.", "Disconnect", go)

    async def reconnect(self, _e=None) -> None:
        """The Reconnect chip, on a session that has dropped (Ctrl+R in
        the terminal): its own last request again, through the station's
        reminder and gate, asked first like every connect here."""
        key = self.current
        if not key:
            return

        async def go() -> None:
            await self.app.command("reconnect", key=key)

        sheets.confirm(self.app.page, f"Reconnect to {key}?",
                       "The station dials it again the same way: route, port and login.",
                       "Reconnect", go)

    async def _connect_sheet(self, _e, target: str = "") -> None:
        contacts = await self.app.command("addressbook") or []
        field = ft.TextField(label="Station, node or BBS", hint_text="e.g. W1AW-7", value=target,
                             capitalization=ft.TextCapitalization.CHARACTERS,
                             autocorrect=False, enable_suggestions=False, autofocus=True)
        by_target = {c.get("target", "").upper(): c for c in contacts if c.get("target")}

        def fill(name: str):
            async def handler(_e) -> None:
                field.value = name
                self.app.page.update()
            return handler

        chips = ft.Row(wrap=True, spacing=6, run_spacing=6, controls=[
            ft.Chip(label=name, on_click=fill(name)) for name in list(by_target)[:12]])

        async def go() -> None:
            name = (field.value or "").strip().upper()
            if not name:
                return
            if name in by_target:
                self.app.start_connect(entry=by_target[name]["target"])
            else:
                self.app.start_connect(target=name)

        sheets.form(self.app.page, "Connect", [field, chips] if contacts else [field],
                    "Connect", go, detail="The station asks first if a contact has a reminder.")
