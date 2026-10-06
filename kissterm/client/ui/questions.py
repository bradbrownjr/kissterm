"""The station's questions (`core/questions.py`) as bottom sheets, with
the answer forms docs/PROTOCOL.md section 3.4 lists.

**Dismissing a sheet is Cancel**, and a cancelled flow transmits nothing.
**The first answer anywhere wins**: when the station closes a question
(answered on another screen, or the flow ended), its sheet here closes
without answering.
"""

from __future__ import annotations

import flet as ft

from . import sheets
from .text import MONO

#: A setup question's words for "leave this service out" and "go there".
SKIP, GO = "skip", "go"


class QuestionSheets:
    def __init__(self, app) -> None:
        self.app = app
        #: qid -> its open sheet.
        self.open: dict[str, ft.BottomSheet] = {}
        self.answered: set[str] = set()

    # ------------------------------------------------------------------
    def show(self, question) -> None:
        build = getattr(self, f"_{question.name}", None)
        title, body, buttons = build(question) if build else self._unknown(question)
        qid = question.qid

        async def dismissed(_e) -> None:
            self.open.pop(qid, None)
            if qid not in self.answered:
                self.answered.add(qid)
                await self.app.conn.answer(qid, None)

        sheet = sheets.sheet([
            ft.Text(title, theme_style=ft.TextThemeStyle.TITLE_MEDIUM), *body,
            ft.Row(alignment=ft.MainAxisAlignment.END, wrap=True, controls=buttons)],
            scrollable=True, on_dismiss=dismissed)
        self.open[qid] = sheet
        self.app.page.show_dialog(sheet)
        self.app.page.run_task(self.app.haptic)

    def closed(self, qid: str) -> None:
        """The station closed `qid`: take its sheet down, answering nothing."""
        self.answered.add(qid)
        sheet = self.open.pop(qid, None)
        if sheet is not None:
            sheet.open = False
            self.app.page.update()

    def answer(self, qid: str, value_of):
        """A button handler: answer `qid` with `value_of()` and close."""
        async def handler(_e) -> None:
            if qid in self.answered:
                return
            self.answered.add(qid)
            value = value_of() if callable(value_of) else value_of
            sheet = self.open.pop(qid, None)
            if sheet is not None:
                sheet.open = False
                self.app.page.update()
            await self.app.conn.answer(qid, value)
            if value == GO:
                from .shell import MORE

                self.app.go(MORE)
        return handler

    def _buttons(self, question, go_label: str, value_of, *, cancel: str = "Cancel",
                 cancel_value=None) -> list[ft.Control]:
        data = question.data
        buttons: list[ft.Control] = [ft.TextButton(
            content=cancel, on_click=self.answer(question.qid, cancel_value))]
        if data.get("skip"):
            buttons.append(ft.TextButton(content=data["skip"],
                                         on_click=self.answer(question.qid, SKIP)))
        buttons.append(ft.FilledButton(content=go_label,
                                       on_click=self.answer(question.qid, value_of)))
        return buttons

    @staticmethod
    def _note(data: dict) -> list[ft.Control]:
        return [ft.Text(data["all_note"], color=ft.Colors.OUTLINE)] if data.get("all_note") else []

    # ------------------------------------------------------------------
    # One builder per question: (title, body controls, buttons)
    # ------------------------------------------------------------------
    def _RadioReminder(self, q):
        d = q.data
        lines = [t for t in (d.get("frequency") and f"Frequency: {d['frequency']}",
                             d.get("connection_type") and f"Connection: {d['connection_type']}",
                             d.get("note")) if t]
        return ("Check the radio before connecting",
                [ft.Text("\n".join(lines), size=16)],
                self._buttons(q, "Connect", True, cancel_value=False))

    def _TrustHostKey(self, q):
        d = q.data
        return (f"Trust {d.get('host', '')}?",
                [ft.Text(f"First connection to {d.get('host')}:{d.get('port')}. "
                         "Check its key fingerprint with the server's owner."),
                 ft.Text(f"{d.get('key_type', '')} {d.get('fingerprint', '')}",
                         selectable=True, font_family=MONO)],
                self._buttons(q, "Trust and save", True, cancel_value=False))

    def _pick(self, label: str, options: list[str], current: str = "") -> ft.Dropdown:
        return ft.Dropdown(label=label, value=current if current in options else None,
                           options=[ft.DropdownOption(key=o, text=o) for o in options])

    def _HomeBbsRoute(self, q):
        d = q.data
        pick = self._pick("Home BBS contact", list(d.get("targets") or []))
        body = self._note(d) + ([ft.Text(d["missing"])] if d.get("missing") else []) + [pick]
        buttons = self._buttons(q, "Use it", lambda: pick.value or None)
        buttons.insert(-1, ft.TextButton(content="Settings", on_click=self.answer(q.qid, GO)))
        return ("Which contact is your Home BBS?", body, buttons)

    def _WinlinkGateway(self, q):
        d = q.data
        pick = self._pick("Gateway", list(d.get("contacts") or []), d.get("favourite", ""))
        remember = ft.Checkbox(label="Make it the favourite", value=False)
        return ("Which Winlink gateway?", self._note(d) + [pick, remember],
                self._buttons(q, "Connect", lambda: {"target": pick.value, "remember": remember.value}
                              if pick.value else None))

    def _LoginAsk(self, q):
        d = q.data
        password = ft.TextField(label="Password" if d.get("secret", True) else d.get("name", ""),
                                password=d.get("secret", True), can_reveal_password=True,
                                autofocus=True)
        fields: list[ft.Control] = []
        username = None
        if d.get("username") is not None:
            username = ft.TextField(label="Username", value=d.get("username") or "")
            fields.append(username)
        fields.append(password)

        def value():
            if username is not None:
                return {"username": username.value or "", "password": password.value or ""}
            return password.value or ""

        where = {"keyring": "Saved in the station's keyring.",
                 "config": "Saved in the station's config file."}.get(d.get("where", ""), "")
        body = self._note(d) + [ft.Text(d.get("detail", ""))] + fields + (
            [ft.Text(where, size=12, color=ft.Colors.OUTLINE)] if where else [])
        return (d.get("title") or "Login needed", body,
                self._buttons(q, d.get("go_label") or "Continue", value))

    def _InternetLoginAsk(self, q):
        d = q.data
        pick = self._pick("Telnet/SSH contact", list(d.get("targets") or []), d.get("current", ""))
        username = ft.TextField(label="Username", value=d.get("username", ""))
        password = ft.TextField(label="Password", password=True, can_reveal_password=True,
                                hint_text="(unchanged)" if d.get("saved") else None)
        return ("Home BBS by Internet", self._note(d) + [pick, username, password],
                self._buttons(q, "Continue", lambda: {
                    "target": pick.value or "", "username": username.value or "",
                    "password": password.value or ""} if pick.value else None))

    def _ChooseCategories(self, q):
        d = q.data
        boxes = [ft.Checkbox(label=f"{name} ({count})", data=name, value=False)
                 for name, count in sorted((d.get("counts") or {}).items())]
        every = ft.Checkbox(label="All of them, every time", value=False)
        return (f"Bulletins from {d.get('bbs', '')}",
                [ft.Column(tight=True, scroll=ft.ScrollMode.AUTO, height=300, controls=boxes), every],
                self._buttons(q, "Collect", lambda: {
                    "categories": [b.data for b in boxes if b.value], "all": every.value}))

    def _HowManyBulletins(self, q):
        d = q.data
        count, newest = int(d.get("count", 0)), int(d.get("newest", 0))
        where = "over the air" if d.get("radio") else "over the Internet"
        detail = (f"{count} new bulletins in {', '.join(d.get('categories') or [])}, read "
                  f"one by one {where}. The newest {newest} leaves the older ones; the "
                  "next run starts after the newest read.")
        # The usual answer last and filled, as every sheet (DESIGN.md 8a).
        return (f"{count} new bulletins on {d.get('bbs', '')}",
                [ft.Text(detail)],
                [ft.TextButton(content="None", on_click=self.answer(q.qid, None)),
                 ft.TextButton(content=f"All {count}", on_click=self.answer(q.qid, count)),
                 ft.FilledButton(content=f"Newest {newest}",
                                 on_click=self.answer(q.qid, newest))])

    def _PickFiles(self, q):
        d = q.data
        have = d.get("have") or {}
        boxes = []
        for item in d.get("files") or []:
            name = item.get("name") if isinstance(item, dict) else str(item)
            size = item.get("size") if isinstance(item, dict) else None
            label = name + (f"  {size} bytes" if size else "") + ("  (have it)" if name in have else "")
            boxes.append(ft.Checkbox(label=label, data=name, value=False))
        return (f"Files on {d.get('bbs', '')}",
                [ft.Column(tight=True, scroll=ft.ScrollMode.AUTO, height=300, controls=boxes)],
                self._buttons(q, "Download", lambda: [b.data for b in boxes if b.value]))

    def _CallsignAsk(self, q):
        field = ft.TextField(label="Callsign with SSID", value=q.data.get("current", ""),
                             capitalization=ft.TextCapitalization.CHARACTERS, autofocus=True)
        return ("Station callsign", [field],
                self._buttons(q, "Save", lambda: (field.value or "").strip().upper() or None))

    def _ChooseSessionTransport(self, q):
        pick = self._pick("Connect over", list(q.data.get("transports") or []),
                          q.data.get("active", ""))
        return ("Which connection?", [pick], self._buttons(q, "Connect", lambda: pick.value))

    def _unknown(self, q):
        return (q.name, [ft.Text("This question needs the station's own screen.")],
                [ft.TextButton(content="Cancel", on_click=self.answer(q.qid, None))])
