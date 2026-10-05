"""Settings from the phone: the station's own schema (`settings_schema`
command), drawn as one expandable section each, saved with the same
validation the terminal's Settings uses (`Settings.save` on the station).

**Only what was changed is sent**, so a phone never writes back a value
it only displayed. A secret field is always empty (the station never
sends one) and an empty secret keeps what is saved. A field the station
refuses keeps its edit and shows the station's reason under it.
"""

from __future__ import annotations

import flet as ft

from . import sheets

CHOICE_KINDS = ("choice",)


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
        self.inputs: dict[str, ft.Control] = {}
        self.column = ft.Column(spacing=0)
        self.save_button = ft.FilledButton(content="Save", icon=ft.Icons.SAVE,
                                           on_click=self._save, disabled=True)

    async def load(self) -> None:
        schema = await self.app.command("settings_schema") or []
        self.draft.clear()
        self.inputs.clear()
        self.column.controls = [ft.ExpansionTile(
            title=ft.Text(section["title"]),
            controls=[self._field(f) for f in section["fields"]],
            controls_padding=ft.Padding.symmetric(horizontal=16, vertical=4))
            for section in schema]
        self.save_button.disabled = True

    def _changed(self, path: str, value) -> None:
        self.draft[path] = value
        self.save_button.disabled = False
        control = self.inputs.get(path)
        if isinstance(control, ft.TextField):
            control.error = None
        self.app.page.update()

    def _field(self, field: dict) -> ft.Control:
        path, kind, label = field["path"], field.get("kind", "text"), field["label"]
        help_text = field.get("help", "")

        if kind == "bool":
            async def toggled(e, path=path) -> None:
                self._changed(path, bool(e.control.value))
            control = ft.Switch(label=label, value=bool(field.get("value")), on_change=toggled)
        elif kind in CHOICE_KINDS and field.get("choices"):
            choices = [(str(text), value) for text, value in field["choices"]]

            async def picked(e, path=path, choices=choices) -> None:
                index = int(e.control.value)
                self._changed(path, choices[index][1])
            current = next((str(i) for i, (_t, v) in enumerate(choices)
                            if v == field.get("value")), None)
            control = ft.Dropdown(label=label, value=current, on_select=picked, dense=True,
                                  options=[ft.DropdownOption(key=str(i), text=t)
                                           for i, (t, _v) in enumerate(choices)])
        else:
            async def typed(e, path=path) -> None:
                self._changed(path, e.control.value or "")
            secret = kind == "secret"
            control = ft.TextField(
                label=label, value="" if secret else display(field), dense=True,
                password=secret, can_reveal_password=secret, on_change=typed,
                hint_text="(unchanged)" if secret else field.get("placeholder") or None,
                keyboard_type=ft.KeyboardType.NUMBER if kind in ("int", "float") else None)
        self.inputs[path] = control
        return ft.Container(padding=ft.Padding.symmetric(vertical=6), content=ft.Column(
            tight=True, spacing=2, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[control] + (
                [ft.Text(help_text, size=12, color=ft.Colors.OUTLINE)] if help_text else [])))

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
            if isinstance(control, ft.TextField):
                control.error = message
        if errors:
            sheets.snack(self.app.page, "Nothing saved: " + "; ".join(
                f"{p}: {m}" for p, m in errors.items()), error=True)
        else:
            self.draft.clear()
            self.save_button.disabled = True
            where = "Saved." if result.get("saved") else "Applied for this session only."
            notes = " ".join(result.get("notes") or [])
            sheets.snack(self.app.page, f"{where} {notes}".strip())
        self.app.page.update()
