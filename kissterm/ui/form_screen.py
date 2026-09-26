"""The form screen: fill in one message form (`kissterm/mail/forms.py`).

Opened by choosing a form as the Type in the compose screen (Mail tab,
Insert). It shows any form file the same way -- one row per field, compact
controls, the help for the focused field on one line at the bottom, as in
Settings -- so a new form is a data file, not new UI.

**Continue returns the rendered text to the compose screen**, where the
operator addresses it and saves it to the Outbox: To, @, the title checks
and the /EX guard are the compose screen's, not repeated here, and the
text can be read in full before it is saved. Nothing here transmits.

A `rows` field (the 213RR order lines) starts with one line; "Add line"
adds another, up to the form's limit. Its columns are laid out on as many
rows as they need to fit 80 columns, each input labelled by its
placeholder.
"""

from __future__ import annotations

from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Footer, Input, Label, Select, Static, TextArea

from ..mail.compose import MAX_TITLE, Draft
from ..mail.forms import Column, Field, FormDef, Values, defaults, problems, render

#: Width budget for one line of a `rows` field: what an 80-column screen
#: leaves beside the row label. A column of 40 or more characters takes
#: what is left (`1fr`) and counts as `_WIDE`; each cell has a 1-column gap.
_ROW_BUDGET = 54
_WIDE = 20


def _column_width(column: Column) -> int:
    if column.max_length >= 40:
        return _WIDE
    return max(6, min(column.max_length + 2, 18), len(column.label) + 2)


def _column_lines(columns: tuple[Column, ...]) -> list[list[Column]]:
    """Columns grouped greedily into lines that fit the budget."""
    lines: list[list[Column]] = [[]]
    used = 0
    for column in columns:
        width = _column_width(column) + 1
        if lines[-1] and used + width > _ROW_BUDGET:
            lines.append([])
            used = 0
        lines[-1].append(column)
        used += width
    return lines


class FormScreen(ModalScreen["Draft | None"]):
    """Fill in one form. Returns a `Draft` for the compose screen, or None."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, form: FormDef, *, mycall: str = "", remembered: Values | None = None) -> None:
        super().__init__()
        self.form = form
        self._values = defaults(form, mycall=mycall, remembered=remembered)
        self._start = dict(self._values)
        self._confirm_discard = False
        self._row_counts = {f.id: 0 for f in form.fields if f.kind == "rows"}

    # -- layout ----------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical(id="form-box"):
            yield Label(self.form.title, id="form-heading")
            with VerticalScroll(id="form-body"):
                for f in self.form.fields:
                    yield from self._field_widgets(f)
            yield Static("", id="form-help")
            with Horizontal(id="form-foot"):
                yield Label("", id="form-error")
                yield Button("Continue", variant="primary", compact=True, id="form-continue")
                yield Button("Cancel", compact=True, id="form-cancel")
        yield Footer()

    def _field_widgets(self, f: Field) -> ComposeResult:
        wid = f"form-{f.id}"
        value = self._values.get(f.id, "")
        if f.kind == "rows":
            with Vertical(id=wid, classes="form-rows"):
                yield Label(f.label, classes="form-label form-rows-label")
            yield Button("Add line", compact=True, id=f"{wid}-add", classes="form-add")
            return
        if f.kind == "multiline":
            yield Label(f.label, classes="form-label form-label-alone")
            yield TextArea(value, id=wid, tab_behavior="focus", soft_wrap=True, classes="form-multiline")
            return
        with Horizontal(classes="form-row"):
            yield Label(f.label, classes="form-label")
            if f.kind == "choice":
                yield Select([(c, c) for c in f.choices], value=value or f.choices[0],
                             allow_blank=False, compact=True, id=wid)
            elif f.kind == "check":
                # Labelled on/off as in Settings: an empty compact label
                # renders as "X..." (Textual 8.2.8).
                yield Checkbox("on" if value else "off", bool(value), compact=True, id=wid)
            else:
                yield Input(value, id=wid, placeholder=f.placeholder, compact=True,
                            max_length=f.max_length or 0)

    async def on_mount(self) -> None:
        for field_id in self._row_counts:
            await self._add_row(self.form.field(field_id))
        first = next((w for w in self.query("#form-body Input, #form-body TextArea")), None)
        if first is not None:
            first.focus()

    async def _add_row(self, f: Field) -> None:
        count = self._row_counts[f.id]
        if count >= f.max_rows:
            return
        container = self.query_one(f"#form-{f.id}", Vertical)
        number = count + 1
        widgets: list[Widget] = []
        for index, line in enumerate(_column_lines(f.columns)):
            label = Label(f"Line {number}" if index == 0 else "", classes="form-label")
            inputs = [
                Input(id=f"form-{f.id}-{number}-{c.id}", placeholder=c.label, compact=True,
                      max_length=c.max_length or 0,
                      classes="form-cell form-cell-wide" if c.max_length >= 40 else "form-cell")
                for c in line
            ]
            for cell, column in zip(inputs, line):
                if column.max_length < 40:
                    cell.styles.width = _column_width(column)
            widgets.append(Horizontal(label, *inputs, classes="form-row"))
        self._row_counts[f.id] = number
        await container.mount(*widgets)
        if number >= f.max_rows:
            self.query_one(f"#form-{f.id}-add", Button).disabled = True

    @on(Button.Pressed, ".form-add")
    async def _add_pressed(self, event: Button.Pressed) -> None:
        field_id = (event.button.id or "").removeprefix("form-").removesuffix("-add")
        await self._add_row(self.form.field(field_id))
        number = self._row_counts[field_id]
        first = self.form.field(field_id).columns[0].id
        self.query_one(f"#form-{field_id}-{number}-{first}", Input).focus()

    # -- values ----------------------------------------------------------------

    def values(self) -> Values:
        values: Values = {}
        for f in self.form.fields:
            wid = f"#form-{f.id}"
            if f.kind == "rows":
                values[f.id] = [
                    {c.id: self.query_one(f"#form-{f.id}-{n}-{c.id}", Input).value for c in f.columns}
                    for n in range(1, self._row_counts[f.id] + 1)
                ]
            elif f.kind == "multiline":
                values[f.id] = self.query_one(wid, TextArea).text
            elif f.kind == "choice":
                chosen = self.query_one(wid, Select).value
                values[f.id] = chosen if isinstance(chosen, str) else ""
            elif f.kind == "check":
                values[f.id] = "1" if self.query_one(wid, Checkbox).value else ""
            else:
                values[f.id] = self.query_one(wid, Input).value
        return values

    def _typed(self) -> bool:
        values = self.values()
        for f in self.form.fields:
            if f.kind == "rows":
                if any(v.strip() for row in values[f.id] for v in row.values()):
                    return True
            elif values[f.id] != self._start.get(f.id, ""):
                return True
        return False

    # -- help, errors ----------------------------------------------------------

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        wid = event.widget.id or ""
        field_id = wid.removeprefix("form-").split("-")[0]
        try:
            f = self.form.field(field_id)
        except StopIteration:
            return
        limit = f" At most {f.max_length} characters." if f.max_length else ""
        needed = " Needed." if f.required else ""
        self.query_one("#form-help", Static).update(f"{f.help}{needed}{limit}".strip())

    @on(Checkbox.Changed)
    def _say_on_or_off(self, event: Checkbox.Changed) -> None:
        event.checkbox.label = "on" if event.value else "off"

    @on(Input.Changed)
    @on(TextArea.Changed)
    @on(Checkbox.Changed)
    @on(Select.Changed)
    def _edited(self) -> None:
        if self._confirm_discard:
            self._confirm_discard = False
            self.query_one("#form-error", Label).update("")

    # -- continue and cancel ---------------------------------------------------

    @on(Button.Pressed, "#form-continue")
    def _continue(self) -> None:
        values = self.values()
        found = problems(self.form, values)
        if found:
            more = f"\n...and {len(found) - 2} more" if len(found) > 2 else ""
            self.query_one("#form-error", Label).update("\n".join(found[:2]) + more)
            return
        subject, body = render(self.form, values)
        # BPQMail cuts a title at 60; cut it here so the operator sees it.
        self.dismiss(Draft(to=self.form.to, at=self.form.at, title=subject[:MAX_TITLE], body=body,
                           send_type=self.form.send_type, form_id=self.form.id,
                           form_values=values))

    def action_cancel(self) -> None:
        if self._typed() and not self._confirm_discard:
            self._confirm_discard = True
            self.query_one("#form-error", Label).update(
                "Discard this form? Esc again to discard, or keep typing."
            )
            return
        self.dismiss(None)

    @on(Button.Pressed, "#form-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)
