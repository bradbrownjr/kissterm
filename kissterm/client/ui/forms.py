"""Message forms on the phone: ICS-213, the Winlink check-in and the rest
(the terminal's Type > a form, `ui/form_screen.py`), laid out from the
station's description of the form (`form_start`).

**Every rule is the station's**: which fields there are, what each needs,
the text and subject a filled form makes, the derived figures and totals
(`form_check`, `mail/forms.py`), the ICS-309's mail log (`form_mail_log`),
and the Winlink XML a form carries (`form_write`). This page only collects
the values, as text or, for a table, a list of lines.

**Next** checks the form and opens the ordinary writer with its text,
subject and To filled in, to be addressed and saved to the Outbox as the
terminal's compose screen does after a form; nothing transmits until
Send/Receive. A field that sits beside another (a status and its comment)
shares its row.
"""

from __future__ import annotations

import flet as ft

from . import sheets


class FormPage:
    def __init__(self, view, start: dict, on_next) -> None:
        self.view = view
        self.app = view.app
        self.form = start["form"]
        #: What the station knows the form by: its id, or `strip:` and the
        #: strip's text, so a pasted or received strip checks and files.
        self.key = start.get("key") or self.form["id"]
        self.values: dict = dict(start["values"])
        self.on_next = on_next
        self.problems = ft.Text("", color=ft.Colors.ERROR)
        #: field id -> the control holding its text (not for `rows`).
        self.inputs: dict[str, ft.Control] = {}
        #: field id -> its lines, each {column id: control}.
        self.tables: dict[str, list[dict[str, ft.Control]]] = {}
        self.table_boxes: dict[str, ft.Column] = {}
        self.fields = {f["id"]: f for f in self.form["fields"]}
        beside = {f["beside"] for f in self.form["fields"] if f.get("beside")}
        self.body: list[ft.Control] = []
        for f in self.form["fields"]:
            if f["id"] in beside:
                continue  # drawn on its host's row
            self.body.append(self._row(f))

    # -- the fields ------------------------------------------------------
    def _row(self, f: dict) -> ft.Control:
        control = self._control(f)
        if f.get("beside") and f["beside"] in self.fields:
            return ft.Row(controls=[control, self._control(self.fields[f["beside"]])])
        return control

    def _control(self, f: dict) -> ft.Control:
        kind, value = f["kind"], self.values.get(f["id"], "")
        label = f["label"] + (" *" if f.get("required") else "")
        helper = f.get("help") or None
        if kind == "rows":
            return self._table(f)
        if kind == "check":
            box = ft.Checkbox(label=f["label"], value=bool(value),
                              on_change=self._set_check(f))
            self.inputs[f["id"]] = box
            return box
        if kind == "choice":
            box = ft.Dropdown(label=label, value=value or None, dense=True,
                              disabled=bool(f.get("readonly")), on_select=self._set(f["id"]),
                              options=[ft.DropdownOption(key=c, text=c) for c in f["choices"]])
        else:
            box = ft.TextField(
                label=label, value=value, dense=True, helper=helper,
                hint_text=f.get("placeholder") or (f.get("format") if kind in (
                    "date", "time", "datetime") else None) or None,
                multiline=kind in ("multiline", "strip"), min_lines=3 if kind == "multiline" else None,
                max_length=f.get("max_length") or None, read_only=bool(f.get("readonly")),
                expand=bool(f.get("beside")), on_change=self._set(f["id"]))
        self.inputs[f["id"]] = box
        return box

    def _set(self, field_id: str):
        async def changed(e) -> None:
            self.values[field_id] = e.control.value or ""
        return changed

    def _set_check(self, f: dict):
        async def changed(e) -> None:
            self.values[f["id"]] = f.get("on_value") or "X" if e.control.value else ""
        return changed

    # -- a table: lines of columns ---------------------------------------
    def _table(self, f: dict) -> ft.Control:
        box = ft.Column(tight=True, spacing=8)
        self.table_boxes[f["id"]] = box
        self.tables[f["id"]] = []
        for row in self.values.get(f["id"]) or []:
            self._add_line(f, row)
        column: list[ft.Control] = [
            ft.Text(f["label"], theme_style=ft.TextThemeStyle.TITLE_SMALL), box]
        if f.get("help"):
            column.insert(1, ft.Text(f["help"], size=12, color=ft.Colors.OUTLINE))
        buttons = [ft.OutlinedButton(content="Add a line", icon=ft.Icons.ADD,
                                     on_click=self._adder(f))]
        if f.get("mail_log"):
            since = ft.TextField(label="Mail since", dense=True, expand=True,
                                 hint_text="YYYY-MM-DD HH:MM", value=self._today())
            buttons = [since, ft.OutlinedButton(content="Fill from mail",
                                                on_click=self._from_mail(f, since))] + buttons
        column.append(ft.Row(wrap=True, controls=buttons))
        return ft.Column(spacing=6, controls=column)

    @staticmethod
    def _today() -> str:
        import datetime

        return datetime.date.today().isoformat()

    def _add_line(self, f: dict, row: dict | None = None) -> None:
        row = row or {}
        cells: dict[str, ft.Control] = {}
        for c in f["columns"]:
            if c.get("sum_of"):
                continue  # computed by the form, never typed
            if c.get("choices"):
                cells[c["id"]] = ft.Dropdown(
                    label=c["label"], value=row.get(c["id"]) or None, dense=True,
                    options=[ft.DropdownOption(key=x, text=x) for x in c["choices"]])
            else:
                cells[c["id"]] = ft.TextField(
                    label=c["label"], value=row.get(c["id"], ""), dense=True,
                    hint_text=c.get("placeholder") or None,
                    max_length=c.get("max_length") or None)
        self.tables[f["id"]].append(cells)
        line = ft.Container(
            padding=ft.Padding.all(8), border_radius=8, bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            content=ft.Column(tight=True, spacing=6, controls=[
                *cells.values(),
                ft.Row(alignment=ft.MainAxisAlignment.END, controls=[ft.TextButton(
                    content="Remove line", icon=ft.Icons.DELETE_OUTLINE,
                    on_click=self._remover(f, cells))])]))
        cells["_line"] = line  # type: ignore[assignment]
        self.table_boxes[f["id"]].controls.append(line)

    def _adder(self, f: dict):
        async def add(_e) -> None:
            if f.get("max_rows") and len(self.tables[f["id"]]) >= f["max_rows"]:
                sheets.snack(self.app.page, f"{f['label']} takes at most {f['max_rows']} lines.")
                return
            self._add_line(f)
            self.app.page.update()
        return add

    def _remover(self, f: dict, cells: dict):
        async def remove(_e) -> None:
            self.tables[f["id"]].remove(cells)
            self.table_boxes[f["id"]].controls.remove(cells["_line"])
            self.app.page.update()
        return remove

    def _from_mail(self, f: dict, since: ft.TextField):
        async def fill(_e) -> None:
            result = await self.app.command("form_mail_log", form=self.form["id"],
                                            field=f["id"], since=since.value or "")
            if not result:
                return
            if result.get("problem"):
                self.problems.value = result["problem"]
            else:
                existing = {tuple(self._line_values(f, cells).items())
                            for cells in self.tables[f["id"]]}
                added = 0
                for row in result["rows"]:
                    if tuple(row.items()) not in existing and (
                            not f.get("max_rows") or len(self.tables[f["id"]]) < f["max_rows"]):
                        self._add_line(f, row)
                        added += 1
                self.problems.value = (f"Added {added} line(s) from the mail." if added
                                       else "No mail since then that is not on the log already.")
            self.app.page.update()
        return fill

    @staticmethod
    def _line_values(f: dict, cells: dict) -> dict:
        return {c["id"]: (cells[c["id"]].value or "") for c in f["columns"]
                if c["id"] in cells}

    # -- the page --------------------------------------------------------
    def collect(self) -> dict:
        values = dict(self.values)
        for fid, lines in self.tables.items():
            values[fid] = [self._line_values(self.fields[fid], cells) for cells in lines]
        return values

    def control(self) -> ft.Control:
        return ft.Column(expand=True, spacing=0, controls=[
            ft.Container(padding=ft.Padding.only(right=12), content=ft.Row(controls=[
                ft.IconButton(icon=ft.Icons.CLOSE, tooltip="Close", on_click=self._close),
                ft.Text(self.form["title"], expand=True, max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                ft.FilledButton(content="Next", on_click=self._next)])),
            ft.Container(expand=True, padding=ft.Padding.symmetric(horizontal=16, vertical=8),
                         content=ft.Column(
                             expand=True, spacing=10, scroll=ft.ScrollMode.AUTO,
                             horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                             controls=[ft.Container(height=6), *self.body, self.problems]))])

    async def _next(self, _e) -> None:
        values = self.collect()
        result = await self.app.command("form_check", form=self.key, values=values)
        if not result:
            return
        if result.get("problems"):
            found = result["problems"]
            more = f"\n...and {len(found) - 3} more" if len(found) > 3 else ""
            self.problems.value = "\n".join(found[:3]) + more
            self.app.page.update()
            return
        await self.on_next(self.form, values, result, self.key)

    async def _close(self, _e) -> None:
        await self.view._back(None)
