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
from .radio import LoginsSection, ProgramsSection, RadioSection, RigsSection

#: Added under a field's help only where Save alone is not the whole story
#: (the terminal's `APPLY_NOTE`).
APPLY_NOTE = {"live": "", "connect": "Used from the next connection.", "restart": "Needs a restart."}

CUSTOM = "__custom__"
NEW = "__new__"


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
        #: A contact field's "Edit contact" button, by path.
        self.contact_edit: dict[str, ft.Control] = {}
        self.column = ft.Column(spacing=0)
        #: The terminal's two hand-built sections (`radio.py`): the radio
        #: comes straight after Station, logins and scripts last.
        self.radio = RadioSection(app)
        self.programs = ProgramsSection(app)
        self.rigs = RigsSection(app)
        self.logins = LoginsSection(app)
        #: Sections left open, so a reload (the station saved something, in
        #: Radio say) does not fold them shut under the operator.
        self.open: set[str] = set()
        self.save_button = ft.FilledButton(content="Save", icon=ft.Icons.SAVE,
                                           on_click=self._save, disabled=True)

    async def load(self) -> None:
        schema = await self.app.command("settings_schema") or []
        self.draft.clear()
        self.inputs.clear()
        self.rows.clear()
        self.fields = {f["path"]: f for section in schema for f in section["fields"]}
        await self.radio.load()
        self.programs.load(self.radio.info)
        self.rigs.load(self.radio.info)
        await self.logins.load()
        tiles = [self._section(section) for section in schema]
        radio = self._tile("Radio", [self.radio.control, self.programs.control, self.rigs.control])
        logins = self._tile("Logins", [self.logins.control])
        after = next((i for i, sec in enumerate(schema) if sec["title"] == "Station"), -1)
        tiles.insert(after + 1, radio)
        self.column.controls = tiles + [logins]
        self._show_conditional()
        self.save_button.disabled = True

    async def refresh(self) -> None:
        """The station's settings changed (a save here or on another screen):
        draw them again, unless something here is typed and not saved, which
        a reload would throw away."""
        if not self.draft:
            await self.load()

    def _tile(self, title: str, controls: list, key: str = "", **more) -> ft.ExpansionTile:
        key = key or title

        async def toggled(e) -> None:
            (self.open.add if e.control.expanded else self.open.discard)(key)
        return ft.ExpansionTile(title=ft.Text(title), controls=controls,
                                expanded=key in self.open, on_change=toggled, **more)

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
            plain.append(self._tile(
                "Advanced", advanced, key=f"{section['title']}/Advanced", dense=True,
                subtitle=ft.Text("Tuning the defaults already suit most stations", size=12),
                controls_padding=ft.Padding.symmetric(horizontal=8)))
        return self._tile(section["title"], plain,
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
            if path in self.contact_edit:
                extra = [ft.Row(controls=[self.contact_edit[path]])]
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
        if path == "aprs.gps_device":
            extra = self._gps_scan(control)
        self.inputs[path] = entry if kind == "color" else control
        notes = [field.get("help", ""), APPLY_NOTE.get(field.get("apply", ""), "")]
        row = ft.Container(padding=ft.Padding.symmetric(vertical=6), content=ft.Column(
            tight=True, spacing=2, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[control, *extra] + [ft.Text(n, size=12, color=ft.Colors.OUTLINE)
                                          for n in notes if n]))
        self.rows[path] = row
        return row

    def _gps_scan(self, entry: ft.TextField) -> list[ft.Control]:
        """The terminal's "Scan" beside the GPS device: list the station's
        local serial ports and put the pick in the field."""
        picker = ft.Dropdown(label="Serial ports found", dense=True, visible=False)
        note = ft.Text("", size=12, color=ft.Colors.OUTLINE)

        async def picked(e) -> None:
            entry.value = e.control.value
            self._changed("aprs.gps_device", entry.value)

        picker.on_select = picked

        async def scan(_e) -> None:
            found = await self.app.command("gps_scan") or []
            picker.options = [ft.DropdownOption(key=d["label"], text=f"{d['label']} -- {d['detail']}")
                              for d in found]
            picker.visible = bool(found)
            note.value = "" if found else "No local serial ports found"
            self.app.page.update()

        return [ft.Row(controls=[ft.OutlinedButton(content="Scan", icon=ft.Icons.SEARCH,
                                                   on_click=scan), note]), picker]

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

        kind = field.get("kind")
        options = [ft.DropdownOption(key=str(i), text=t) for i, (t, _v) in enumerate(pairs)]
        if kind in ("contact", "login"):
            # The terminal's lists end "New contact..." / "New login...": a
            # station with none yet can make one without leaving Settings.
            options.append(ft.DropdownOption(
                key=NEW, text="New contact..." if kind == "contact" else "New login..."))
        dropdown = ft.Dropdown(
            label=field["label"], value=index, dense=True,
            enable_filter=len(pairs) > 12, editable=len(pairs) > 12, options=options)

        chosen = [index]

        def added(name: str) -> None:
            """The new entry joins the list, is picked, and is the edit."""
            pairs.append((name, name))
            dropdown.options.insert(len(pairs) - 1, ft.DropdownOption(
                key=str(len(pairs) - 1), text=name))
            dropdown.value = chosen[0] = str(len(pairs) - 1)
            self._changed(path, name)

        async def picked(e, path=path, pairs=pairs) -> None:
            if e.control.value == NEW:
                e.control.value = chosen[0]  # until a save: cancelling leaves it as it was
                if kind == "contact":
                    self._new_contact(field.get("contacts") == "internet", added)
                else:
                    self._new_login(added)
                self.app.page.update()
                return
            chosen[0] = e.control.value
            self._changed(path, pairs[int(e.control.value)][1])
        dropdown.on_select = picked
        if kind == "contact":
            internet = field.get("contacts") == "internet"

            async def edit(_e) -> None:
                value = pairs[int(chosen[0])][1] if chosen[0] is not None else ""
                if value:
                    await self._edit_contact(value, internet, renamed)
            self.contact_edit[path] = ft.TextButton(content="Edit contact", icon=ft.Icons.EDIT,
                                                    on_click=edit)

        def renamed(name: str) -> None:
            """An edit that renamed the contact: the list and the field follow."""
            old = pairs[int(chosen[0])]
            pairs[int(chosen[0])] = (name, name)
            dropdown.options[int(chosen[0])].text = name
            self._changed(path, name)
        return dropdown

    def _new_contact(self, internet: bool, done) -> None:
        self._contact_sheet({}, internet, done)

    async def _edit_contact(self, target: str, internet: bool, done) -> None:
        """The selected contact's own form (the Address Book's editor)."""
        book = await self.app.command("addressbook") or []
        entry = next((e for e in book if e.get("target") == target), None)
        if entry is None:
            sheets.snack(self.app.page, f"{target} is not in the Address Book.", error=True)
            return
        self._contact_sheet(entry, internet, done)

    def _contact_sheet(self, entry: dict, internet: bool, done) -> None:
        """Make or edit a contact: the radio kind is a station (frequency,
        hops, note), the Internet kind a host (Telnet or SSH)."""
        original = entry.get("target", "")
        name = ft.TextField(label="Name" if internet else "Station", value=original,
                            autofocus=not original,
                            capitalization=None if internet else ft.TextCapitalization.CHARACTERS)
        fields: list[ft.Control] = [name]
        kind = host = port = frequency = hops = note = None
        if internet:
            kind = ft.Dropdown(label="Connect by", value=entry.get("connect_by") or "telnet",
                               options=[ft.DropdownOption(key="telnet", text="Telnet"),
                                        ft.DropdownOption(key="ssh", text="SSH")])
            host = ft.TextField(label="Host", value=entry.get("host", ""),
                                hint_text="e.g. bbs.example.org")
            port = ft.TextField(label="Port", value=str(entry.get("port", "") or ""),
                                hint_text="23 for Telnet, 22 for SSH",
                                keyboard_type=ft.KeyboardType.NUMBER)
            fields += [kind, host, port]
        else:
            frequency = ft.TextField(label="Frequency", value=entry.get("frequency", ""))
            hops = ft.TextField(label="Node hops", value=entry.get("hops", ""),
                                hint_text="e.g. N1QFY, AB1KI-15")
            note = ft.TextField(label="Note", value=entry.get("note", ""))
            fields += [frequency, hops, note]

        async def go() -> None:
            target = (name.value or "").strip()
            target = target if internet else target.upper()
            if not target or (internet and not (host.value or "").strip()):
                sheets.snack(self.app.page, "Fill in the name" + (" and host." if internet else "."),
                             error=True)
                return
            data = {"target": target, "original_target": original}
            if internet:
                data.update(connect_by=kind.value, host=host.value.strip(), port=port.value or "")
            else:
                data.update(frequency=frequency.value or "", hops=hops.value or "",
                            note=note.value or "")
            if not original:
                data.pop("original_target")
            if await self.app.command("addressbook_save", entry=data):
                done(target)

        sheets.form(self.app.page, "Edit contact" if original else "New contact", fields,
                    "Save", go)

    def _new_login(self, done) -> None:
        name = ft.TextField(label="Name", autofocus=True)
        user = ft.TextField(label="Username", autocorrect=False, enable_suggestions=False)
        password = ft.TextField(label="Password", password=True, can_reveal_password=True)

        async def go() -> None:
            result = await self.app.command(
                "login_save", name=name.value or "", username=user.value or "",
                password=password.value or "", original="")
            if result and result["error"]:
                sheets.snack(self.app.page, result["error"], error=True)
                return
            if result:
                done((name.value or "").strip())
                await self.logins.load()

        sheets.form(self.app.page, "New login", [name, user, password], "Save", go)

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
