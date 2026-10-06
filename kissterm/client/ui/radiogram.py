"""The radiogram form on the phone: an ARRL radiogram for NTS, saved to
the BBS Outbox (the terminal's `ui/radiogram.py`; operator, 2026-10-06:
"New Message lacks NTS").

Chosen as the kind of a new message (NTS radiogram, or Radiogram-ICS213,
which carries HXI and a subject line). **Every rule is the station's**
(`radiogram_start`, `radiogram_check`, `radiogram_write`, on
`core.mail`'s methods and `mail/nts.py`): this page only collects the
fields and shows what the station says about them. **Saving never
transmits**: the radiogram waits in the Outbox and goes out as `ST <zip>
@ NTS<state>` on the next Send/Receive.

**The text converts as it is typed**, as at the terminal: when a word is
finished at the end of the text, the text is replaced by its radiogram
form (a period becomes X, `?` QUERY), and leaving the text converts all
of it, a final X dropped. A reply that comes back after more was typed
is not applied, so nothing typed is lost to the round trip. The check
(group count), the BBS routing and title, and the meaning of each ARL
text used follow every change.
"""

from __future__ import annotations

import flet as ft

from . import sheets


def field(label: str, *, hint: str = "", value: str = "", caps: bool = True,
          width: int | None = None, expand: bool | int | None = None,
          number: bool = False) -> ft.TextField:
    return ft.TextField(
        label=label, hint_text=hint, value=value, dense=True, width=width, expand=expand,
        capitalization=ft.TextCapitalization.CHARACTERS if caps else None,
        keyboard_type=ft.KeyboardType.NUMBER if number else None)


class RadiogramForm:
    """One radiogram being filled in, as a page of `MailView`."""

    def __init__(self, view, start: dict, ics213: bool) -> None:
        self.view = view
        self.app = view.app
        self.ics213 = ics213
        self._asked = 0
        precedences = start.get("precedences") or [["R", "Routine"]]
        self.fields: dict[str, ft.Control] = {
            "number": field("Number", value=start.get("number", ""), width=96, number=True),
            "precedence": ft.Dropdown(
                dense=True, label="Precedence", value=start.get("precedence", "R"), expand=True,
                options=[ft.DropdownOption(key=v, text=label) for v, label in precedences]),
            "handling": field("HX", hint="e.g. HXG", value=start.get("handling", ""), width=96),
            "test": ft.Switch(label="Test (an exercise message)", value=False),
            "origin": field("From station", value=start.get("origin", ""), width=130),
            "place": field("Place", hint="sender's city ST, e.g. WATERBORO ME",
                           value=start.get("place", ""), expand=True),
            "time_filed": field("Time filed", hint="e.g. 1830Z", width=130),
            "to_name": field("Name", hint="as in the phone book", expand=True),
            "to_call": field("Call", hint="if a ham", width=120),
            "to_street": field("Street", hint="e.g. 164 EAST SIXTH AVE"),
            "to_city": field("City", hint="e.g. RIVER CITY", expand=True),
            "to_state": field("State", hint="MD", width=76),
            "to_zip": field("ZIP", hint="00789", width=96, number=True),
            "to_phone": field("Phone", hint="e.g. 301 555 3470", caps=False,
                              number=True),
            "to_email": field("Email", hint="optional", caps=False),
            "to_op_note": field("Op note", hint="optional, for the delivering operator"),
            "text": ft.TextField(label="Text", multiline=True, min_lines=4, dense=True,
                                 capitalization=ft.TextCapitalization.CHARACTERS),
            "signature": field("Signature", hint=(
                "name and position, e.g. JANE DOE SHELTER MANAGER" if ics213
                else "who it is from")),
            "ics_subject": field("Subject", hint="the ICS-213 subject, e.g. SHELTER STATUS 1400",
                                 value="") if ics213 else None,
            "sig_op_note": field("Op note", hint="optional, e.g. REPLY VIA KC1JMH AT WS1EC"),
        }
        self.fields = {k: v for k, v in self.fields.items() if v is not None}
        for name, control in self.fields.items():
            control.on_change = self._changed
            if name == "text":
                control.on_blur = self._text_left
        self.arl = ft.Dropdown(
            dense=True, label="Insert an ARL numbered text", on_select=self._insert_arl,
            options=[ft.DropdownOption(key=t["groups"], text=f"{t['number']} {t['text']}")
                     for t in start.get("arl") or []])
        self.check = ft.Text(f"Date {start.get('date', '')}   Check 0", size=12,
                             color=ft.Colors.OUTLINE)
        self.meanings = ft.Text("", size=12, color=ft.Colors.OUTLINE, visible=False)
        self.status = ft.Text("", size=12, color=ft.Colors.OUTLINE)
        self.problems = ft.Text("", color=ft.Colors.ERROR)
        self._date = start.get("date", "")

    # -- the page ----------------------------------------------------------
    def control(self) -> ft.Control:
        f = self.fields
        heading = "Radiogram-ICS213" if self.ics213 else "NTS radiogram"

        def label(text: str) -> ft.Control:
            return ft.Text(text, theme_style=ft.TextThemeStyle.TITLE_SMALL)

        return ft.Column(expand=True, spacing=0, controls=[
            ft.Container(padding=ft.Padding.only(right=12), content=ft.Row(controls=[
                ft.IconButton(icon=ft.Icons.CLOSE, tooltip="Close", on_click=self.close),
                ft.Text(heading, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                        theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                ft.FilledButton(content="Save to Outbox", on_click=self.save)])),
            ft.Container(expand=True, padding=ft.Padding.symmetric(horizontal=16, vertical=8),
                         content=ft.Column(
                             expand=True, spacing=10, scroll=ft.ScrollMode.AUTO,
                             horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=[
                                 # Room for the first row's floating labels,
                                 # which the scroll would otherwise clip.
                                 ft.Container(height=6),
                                 ft.Row(controls=[f["number"], f["precedence"], f["handling"]]),
                                 f["test"],
                                 ft.Row(controls=[f["origin"], f["place"]]),
                                 ft.Row(vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        controls=[f["time_filed"], self.check]),
                                 label("To"),
                                 ft.Row(controls=[f["to_name"], f["to_call"]]),
                                 f["to_street"],
                                 ft.Row(controls=[f["to_city"], f["to_state"], f["to_zip"]]),
                                 f["to_phone"], f["to_email"], f["to_op_note"],
                                 label("Text"),
                                 self.arl, f["text"], self.meanings,
                                 f["signature"],
                                 *([f["ics_subject"]] if self.ics213 else []),
                                 f["sig_op_note"],
                                 self.status, self.problems]))])

    # -- what the station says about it -------------------------------------
    def values(self) -> dict:
        out = {}
        for name, control in self.fields.items():
            out[name] = bool(control.value) if name == "test" else (control.value or "")
        return out

    async def _changed(self, _e) -> None:
        await self.refresh(live=True)

    async def _text_left(self, _e) -> None:
        await self.refresh(final=True)

    async def refresh(self, *, live: bool = False, final: bool = False) -> None:
        self._asked += 1
        asked = self._asked
        sent = self.values()
        result = await self.app.command("radiogram_check", fields=sent, ics213=self.ics213)
        if not result or asked != self._asked:
            return  # a newer change is on its way: its answer wins
        text = self.fields["text"]
        typed = sent["text"]
        if final and result.get("text") is not None and result["text"] != typed:
            text.value = result["text"]
        elif live and typed[-1:].isspace() and result.get("live") not in (None, typed):
            text.value = result["live"]
        self.check.value = f"Date {self._date}   Check {result.get('check', '0')}"
        used = result.get("arl_used") or []
        self.meanings.value, self.meanings.visible = "\n".join(used), bool(used)
        self.status.value = "\n".join(
            [f"{result.get('route', '')}   {result.get('subject', '')}".strip(),
             *(result.get("warnings") or [])])
        self.app.page.update()

    async def _insert_arl(self, e) -> None:
        groups = e.control.value
        if not groups:
            return
        text = self.fields["text"]
        current = text.value or ""
        text.value = f"{current}{'' if not current or current.endswith(' ') else ' '}{groups} "
        self.arl.value = None
        await self.refresh()

    # -- save and close ------------------------------------------------------
    async def save(self, _e) -> None:
        result = await self.app.command("radiogram_write", fields=self.values(),
                                        ics213=self.ics213)
        if not result:
            return
        if result.get("problems"):
            self.problems.value = "\n".join(result["problems"])
            self.app.page.update()
            return
        sheets.snack(self.app.page, "Radiogram saved to the BBS Outbox. "
                                    "Send/Receive sends it.")
        await self.view._back(None)

    async def close(self, _e) -> None:
        values = self.values()
        if (values["text"] or values["to_name"]).strip():
            sheets.confirm(self.app.page, "Discard this radiogram?",
                           "What you wrote is not saved anywhere.", "Discard",
                           lambda: self.view._back(None), danger=True)
            return
        await self.view._back(None)
