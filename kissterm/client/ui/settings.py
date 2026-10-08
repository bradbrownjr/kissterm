"""Settings from the phone: the station's own schema (`settings_schema`
command), drawn as one expandable section each, saved with the same
validation the terminal's Settings uses (`Settings.save` on the station).

**One control per kind, as the terminal has one**: a switch, a dropdown
(choices, Address Book contacts, saved logins, map symbols, the theme), a
colour picker for a colour, a number field with its limits, a text field.
A "custom_choice" (the APRS path) is a dropdown with a "Custom..." entry
that opens a text field. A field with `only_when` shows only while the
other field has that value (the custom colours, while Theme is Custom);
an `advanced` field is folded under its section's "Advanced"; a
`rule_before` is a heading; and a field that does not take effect on Save
says so ("Needs a restart.").

**Only what was changed is sent**, so a phone never writes back a value
it only displayed. A secret field is always empty (the station never
sends one) and an empty secret keeps what is saved. A field the station
refuses keeps its edit and shows the station's reason under it.

What the terminal alone draws (a status-bar clock) never arrives here: the
station leaves `tui_only` fields out of the schema.
"""

from __future__ import annotations

import flet as ft

from . import colourpicker, sheets

#: Added under a field's help only where Save alone is not the whole story
#: (the terminal's `APPLY_NOTE`).
APPLY_NOTE = {"live": "", "connect": "Used from the next connection.", "restart": "Needs a restart."}

CUSTOM = "__custom__"


def display(field: dict) -> str:
    value = field.get("value")
    if field.get("kind") == "calllist":
        return ", ".join(value or [])
    if value is None:
        return ""
    return str(value)


class SettingsEditor:
    def __init__(self, app) -> None:
        self.app = app
        self.draft: dict = {}
        self.fields: dict[str, dict] = {}
        self.inputs: dict[str, ft.Control] = {}
        #: A field's whole row (control, help), shown or hidden by `only_when`.
        self.rows: dict[str, ft.Control] = {}
        self.column = ft.Column(spacing=0)
        self.save_button = ft.FilledButton(content="Save", icon=ft.Icons.SAVE,
                                           on_click=self._save, disabled=True)

    async def load(self) -> None:
        schema = await self.app.command("settings_schema") or []
        self.draft.clear()
        self.inputs.clear()
        self.rows.clear()
        self.fields = {f["path"]: f for section in schema for f in section["fields"]}
        self.column.controls = [self._section(section) for section in schema]
        self._show_conditional()
        self.save_button.disabled = True

    def _section(self, section: dict) -> ft.Control:
        plain: list[ft.Control] = []
        advanced: list[ft.Control] = []
        for field in section["fields"]:
            row = self._field(field)
            if field.get("rule_before"):
                heading = ft.Text(field["rule_before"], weight=ft.FontWeight.BOLD,
                                  theme_style=ft.TextThemeStyle.TITLE_SMALL)
                row = ft.Column(tight=True, spacing=0, controls=[heading, row])
                self.rows[field["path"]] = row
            (advanced if field.get("advanced") else plain).append(row)
        if advanced:
            plain.append(ft.ExpansionTile(
                title=ft.Text("Advanced"), subtitle=ft.Text(
                    "Tuning the defaults already suit most stations", size=12),
                controls=advanced, dense=True,
                controls_padding=ft.Padding.symmetric(horizontal=8)))
        return ft.ExpansionTile(
            title=ft.Text(section["title"]), controls=plain,
            controls_padding=ft.Padding.symmetric(horizontal=16, vertical=4))

    # ------------------------------------------------------------------
    def value_of(self, path: str):
        """What a field holds now: the edit, else what the station has."""
        return self.draft[path] if path in self.draft else self.fields.get(path, {}).get("value")

    def _show_conditional(self) -> None:
        for path, field in self.fields.items():
            when = field.get("only_when")
            if when and path in self.rows:
                self.rows[path].visible = self.value_of(when[0]) == when[1]

    def _changed(self, path: str, value) -> None:
        self.draft[path] = value
        self.save_button.disabled = False
        control = self.inputs.get(path)
        if isinstance(control, (ft.TextField, ft.Dropdown)):
            control.error = None
        self._show_conditional()
        self.app.page.update()

    def _field(self, field: dict) -> ft.Control:
        path, kind, label = field["path"], field.get("kind", "text"), field["label"]
        extra: list[ft.Control] = []

        if kind == "bool":
            async def toggled(e, path=path) -> None:
                self._changed(path, bool(e.control.value))
            control = ft.Switch(label=label, value=bool(field.get("value")), on_change=toggled)
        elif kind == "color":
            control, entry = self._colour(field)
        elif kind == "custom_choice":
            control, extra = self._custom_choice(field)
        elif kind in ("choice", "contact", "login", "filtered_choice"):
            control = self._dropdown(field)
        else:
            async def typed(e, path=path) -> None:
                self._changed(path, e.control.value or "")
            secret = kind == "secret"
            numeric = kind in ("int", "float")
            control = ft.TextField(
                label=label, value="" if secret else display(field), dense=True,
                password=secret, can_reveal_password=secret, on_change=typed,
                hint_text="(unchanged)" if secret else field.get("placeholder") or None,
                helper=self._limits(field) if numeric else None,
                keyboard_type=ft.KeyboardType.NUMBER if numeric else None,
                capitalization=ft.TextCapitalization.CHARACTERS if kind in (
                    "callsign", "calllist") else None)
        self.inputs[path] = entry if kind == "color" else control
        notes = [field.get("help", ""), APPLY_NOTE.get(field.get("apply", ""), "")]
        row = ft.Container(padding=ft.Padding.symmetric(vertical=6), content=ft.Column(
            tight=True, spacing=2, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[control, *extra] + [ft.Text(n, size=12, color=ft.Colors.OUTLINE)
                                          for n in notes if n]))
        self.rows[path] = row
        return row

    @staticmethod
    def _limits(field: dict) -> str | None:
        low, high = field.get("minimum"), field.get("maximum")
        if low is not None and high is not None:
            return f"{low:g} to {high:g}"
        if low is not None:
            return f"at least {low:g}"
        if high is not None:
            return f"at most {high:g}"
        return None

    # -- dropdowns -----------------------------------------------------
    def _pairs(self, field: dict) -> list[tuple[str, object]]:
        raw = field.get("options") if field.get("options") is not None else field.get("choices")
        return [(str(text), value) for text, value in raw or []]

    def _dropdown(self, field: dict) -> ft.Dropdown:
        """Options are keyed by position: a value may be an int or "", and a
        key is text. A long list (the map symbols) filters as you type."""
        path = field["path"]
        pairs = self._pairs(field)
        current = field.get("value")
        index = next((str(i) for i, (_t, v) in enumerate(pairs) if v == current), None)

        async def picked(e, path=path, pairs=pairs) -> None:
            self._changed(path, pairs[int(e.control.value)][1])
        return ft.Dropdown(
            label=field["label"], value=index, on_select=picked, dense=True,
            enable_filter=len(pairs) > 12, editable=len(pairs) > 12,
            options=[ft.DropdownOption(key=str(i), text=t) for i, (t, _v) in enumerate(pairs)])

    def _custom_choice(self, field: dict) -> tuple[ft.Control, list[ft.Control]]:
        """A dropdown of presets ending "Custom...", which shows a text field
        (the terminal's `aprs.path`)."""
        path = field["path"]
        pairs = self._pairs(field)
        current = field.get("value")
        known = {v for _t, v in pairs}
        custom = ft.TextField(label=f"{field['label']} (custom)", dense=True,
                              value="" if current in known else str(current or ""),
                              hint_text=field.get("placeholder") or None,
                              visible=current not in known)

        async def typed(e) -> None:
            self._changed(path, e.control.value or "")
        custom.on_change = typed

        async def picked(e) -> None:
            if e.control.value == CUSTOM:
                custom.visible = True
                self._changed(path, custom.value or "")
            else:
                custom.visible = False
                self._changed(path, pairs[int(e.control.value)][1])
        options = [ft.DropdownOption(key=str(i), text=t) for i, (t, _v) in enumerate(pairs)]
        options.append(ft.DropdownOption(key=CUSTOM, text="Custom..."))
        index = next((str(i) for i, (_t, v) in enumerate(pairs) if v == current), CUSTOM)
        return ft.Dropdown(label=field["label"], value=index, on_select=picked, dense=True,
                           options=options), [custom]

    # -- colours -------------------------------------------------------
    def _colour(self, field: dict) -> tuple[ft.Control, ft.TextField]:
        """A swatch and the hex, and a tap opens the picker; the hex can
        still be typed or pasted."""
        path, label = field["path"], field["label"]
        box = ft.Container(width=36, height=36)
        hex_field = ft.TextField(label=label, value=display(field), dense=True, expand=True,
                                 hint_text=field.get("placeholder") or "#1A1B26")

        def paint() -> None:
            rgb = colourpicker.parse(hex_field.value or "")
            box.bgcolor = colourpicker.to_hex(*rgb) if rgb else ft.Colors.SURFACE_CONTAINER_HIGHEST
            box.border = ft.Border.all(1, ft.Colors.OUTLINE)
            box.border_radius = 8

        async def typed(e) -> None:
            paint()
            self._changed(path, e.control.value or "")

        async def used(value: str) -> None:
            hex_field.value = value
            paint()
            self._changed(path, value)

        async def open_picker(_e) -> None:
            colourpicker.pick(self.app.page, label, hex_field.value or "", used)

        hex_field.on_change = typed
        box.on_click = open_picker
        box.tooltip = "Pick a colour"
        paint()
        return ft.Row(controls=[box, hex_field],
                      vertical_alignment=ft.CrossAxisAlignment.CENTER), hex_field

    async def _save(self, _e) -> None:
        draft = {k: v for k, v in self.draft.items()
                 if not (isinstance(self.inputs.get(k), ft.TextField)
                         and self.inputs[k].password and not v)}
        result = await self.app.command("settings_save", draft=draft)
        if result is None:
            return
        errors = result.get("errors") or {}
        for path, message in errors.items():
            control = self.inputs.get(path)
            if isinstance(control, (ft.TextField, ft.Dropdown)):
                control.error = message
        if errors:
            sheets.snack(self.app.page, "Nothing saved: " + "; ".join(
                f"{p}: {m}" for p, m in errors.items()), error=True)
        else:
            for path, value in self.draft.items():
                if path in self.fields:
                    self.fields[path]["value"] = value
            self.draft.clear()
            self.save_button.disabled = True
            where = "Saved." if result.get("saved") else "Applied for this session only."
            notes = " ".join(result.get("notes") or [])
            sheets.snack(self.app.page, f"{where} {notes}".strip())
        self.app.page.update()
