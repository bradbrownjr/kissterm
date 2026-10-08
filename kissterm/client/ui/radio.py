"""Settings > Radio, Logins and Scripts on the phone: the terminal's three
hand-built Settings sections, over `core/radio.py`.

**The station decides what is valid** (`radio_save` proves a transport with
`build_transport` before saving), and each button here is one station
command. Forgetting asks first. **Scan and Test transmit nothing** (the
station says exactly what goes out); Scan runs only when pressed, never on
a timer. A password or script text is never shown back: an empty field on an
edit keeps what is saved.
"""

from __future__ import annotations

import flet as ft

from . import sheets

NONE = "__none__"


def _dropdown(label: str, names: list[str], current: str) -> ft.Dropdown:
    options = [ft.DropdownOption(key=NONE, text="(none)")]
    options += [ft.DropdownOption(key=n, text=n) for n in names]
    if current and current not in names:
        options.append(ft.DropdownOption(key=current, text=f"{current} (not saved)"))
    return ft.Dropdown(label=label, dense=True, options=options, value=current or NONE)


def _picked(control: ft.Dropdown) -> str:
    return "" if control.value in (None, NONE) else str(control.value)


class RadioSection:
    """The radio in use, and New, Edit, Test, Forget and Scan for the list."""

    def __init__(self, app) -> None:
        self.app = app
        self.info: dict = {}
        self.picker = ft.Dropdown(label="Radio in use", dense=True, on_select=self._use)
        self.detail = ft.Text("", size=12, color=ft.Colors.OUTLINE, selectable=True)
        self.control = ft.Container(padding=ft.Padding.symmetric(horizontal=16, vertical=4),
                                    content=ft.Column(tight=True, spacing=8, controls=[
            self.picker,
            ft.Row(wrap=True, spacing=8, controls=[
                ft.OutlinedButton(content="Scan for hardware", icon=ft.Icons.RADAR,
                                  on_click=self._scan),
                ft.OutlinedButton(content="New", icon=ft.Icons.ADD, on_click=self._new),
                ft.OutlinedButton(content="Edit", icon=ft.Icons.EDIT, on_click=self._edit),
                ft.OutlinedButton(content="Test", icon=ft.Icons.NETWORK_CHECK, on_click=self._test),
                ft.OutlinedButton(content="Forget", icon=ft.Icons.DELETE_OUTLINE,
                                  on_click=self._forget)]),
            self.detail]))

    async def load(self) -> None:
        self.info = await self.app.command("radio_info") or {}
        names = [t.get("name", "") for t in self.info.get("transports", [])]
        by = {t.get("name"): t for t in self.info.get("transports", [])}
        labels = {n: f"{n}  ({by[n].get('kind', '?')})" for n in names}
        self.picker.options = [ft.DropdownOption(key=n, text=labels[n]) for n in names]
        active = self.info.get("active", "")
        self.picker.value = active if active in names else None
        self._describe()

    @property
    def current(self) -> dict | None:
        name = self.picker.value
        return next((t for t in self.info.get("transports", []) if t.get("name") == name), None)

    def _describe(self) -> None:
        entry = self.current
        if entry is None:
            self.detail.value = (
                "No transport configured. Scan for hardware looks for serial TNCs, KISS and "
                "AGWPE services on your network, and paired Bluetooth TNCs; nothing it does "
                "transmits.")
        else:
            self.detail.value = ", ".join(f"{k} = {v}" for k, v in sorted(entry.items())
                                          if k != "name") or "(no settings)"

    async def _use(self, e) -> None:
        """Open the chosen radio now, as saving the choice does in the
        terminal; it is refused while a link is connected."""
        result = await self.app.command("radio_use", name=e.control.value)
        self._describe()
        if result and result.get("errors"):
            sheets.snack(self.app.page, "; ".join(result["errors"].values()), error=True)
        elif result and not result.get("opened"):
            sheets.snack(self.app.page, "Saved, but that radio did not open. See the Monitor "
                         "and Notices; disconnect first if a link is up.", error=True)
        self.app.page.update()

    async def _scan(self, _e) -> None:
        self.detail.value = "Scanning serial ports, the local network, and paired Bluetooth..."
        self.app.page.update()
        result = await self.app.command("radio_scan")
        await self.load()
        if result:
            self.detail.value = result["summary"]
        self.app.page.update()

    async def _test(self, _e) -> None:
        entry = self.current
        if entry is None:
            self.detail.value = "Select a transport first."
        else:
            self.detail.value = f"Testing {entry.get('name')}..."
            self.app.page.update()
            result = await self.app.command("radio_test", name=entry.get("name"))
            if result:
                self.detail.value = result["line"]
        self.app.page.update()

    async def _forget(self, _e) -> None:
        entry = self.current
        if entry is None:
            return

        async def go() -> None:
            await self.app.command("radio_forget", name=entry["name"])
            await self.load()
            self.app.page.update()

        sheets.confirm(self.app.page, f"Forget {entry['name']}?",
                       "It is removed from this station's transports. The hardware is not touched.",
                       "Forget", go, danger=True)

    async def _new(self, _e) -> None:
        self._edit_sheet(None)

    async def _edit(self, _e) -> None:
        entry = self.current
        if entry is None:
            sheets.snack(self.app.page, "Select a transport first.")
            return
        self._edit_sheet(entry)

    def _edit_sheet(self, entry: dict | None) -> None:
        """The form for one kind at a time: its own fields, and for a
        session-tier kind the auto-login pickers."""
        kinds = {k["kind"]: k for k in self.info.get("kinds", [])}
        if not kinds:
            return
        entry = entry or {}
        original = entry.get("name", "")
        kind = entry.get("kind") if entry.get("kind") in kinds else next(iter(kinds))
        name = ft.TextField(label="Name", value=original, dense=True,
                            hint_text="e.g. direwolf-local or ws1ec")
        error = ft.Text("", color=ft.Colors.ERROR, visible=False)
        fields = ft.Column(tight=True, spacing=8)
        login = _dropdown("Saved login", self.info.get("logins", []), entry.get("credential", ""))
        script = _dropdown("Saved script", self.info.get("scripts", []), entry.get("script_name", ""))
        auto = ft.Column(tight=True, spacing=8, controls=[
            ft.Text("Auto-login (optional): sent right after this transport connects.",
                    size=12, color=ft.Colors.OUTLINE), login, script])
        inputs: dict[str, ft.TextField] = {}
        state = {"kind": kind}

        def draw(prefill: dict) -> None:
            spec = kinds[state["kind"]]
            inputs.clear()
            for f in spec["fields"]:
                inputs[f["key"]] = ft.TextField(
                    label=f["label"], dense=True, hint_text=f["placeholder"] or None,
                    value=str(prefill.get(f["key"], f["default"])), password=f["password"],
                    keyboard_type=ft.KeyboardType.NUMBER if f["numeric"] else None)
            fields.controls = list(inputs.values())
            auto.visible = bool(spec["session_tier"])

        async def kind_changed(e) -> None:
            state["kind"] = e.control.value
            draw({})  # a field of the previous kind is not carried over
            self.app.page.update()

        picker = ft.Dropdown(
            label="Kind", dense=True, value=kind, on_select=kind_changed,
            options=[ft.DropdownOption(
                key=k, text=v["label"] + (" (experimental)" if v["experimental"] else ""))
                for k, v in kinds.items()])
        draw(entry if entry.get("kind") == kind else {})

        async def save() -> None:
            body = {"name": name.value or "", "kind": state["kind"],
                    **{k: c.value or "" for k, c in inputs.items()}}
            if kinds[state["kind"]]["session_tier"]:
                body["credential"], body["script_name"] = _picked(login), _picked(script)
            result = await self.app.command("radio_save", entry=body, original=original)
            if result is None:
                return
            if result["error"]:
                sheets.snack(self.app.page, result["error"], error=True)
                self._edit_sheet(entry or None)  # the sheet closed with Save: show it again
                return
            await self.load()
            self.app.page.update()

        sheets.form(self.app.page, "Edit transport" if original else "New transport",
                    [name, picker, error, fields, auto], "Save", save)


class LoginsSection:
    """Saved logins and scripts: what a contact or transport can name."""

    def __init__(self, app) -> None:
        self.app = app
        self.logins = ft.Column(tight=True, spacing=0)
        self.scripts = ft.Column(tight=True, spacing=0)
        self.control = ft.Container(padding=ft.Padding.symmetric(horizontal=16, vertical=4),
                                    content=ft.Column(tight=True, spacing=8, controls=[
            ft.Text("Logins", theme_style=ft.TextThemeStyle.TITLE_SMALL),
            ft.Text("A saved login: a username and password, sent after connecting. A "
                    "contact or transport can pick one by name.", size=12,
                    color=ft.Colors.OUTLINE),
            self.logins,
            ft.OutlinedButton(content="New login", icon=ft.Icons.ADD,
                              on_click=self._new_login),
            ft.Text("Scripts", theme_style=ft.TextThemeStyle.TITLE_SMALL),
            ft.Text("Commands sent one line at a time after connecting, after any login: a "
                    "node hop, a mailbox check. The text stays on the station.", size=12,
                    color=ft.Colors.OUTLINE),
            self.scripts,
            ft.OutlinedButton(content="New script", icon=ft.Icons.ADD,
                              on_click=self._new_script)]))

    async def load(self) -> None:
        logins = await self.app.command("logins") or []
        scripts = await self.app.command("scripts") or []
        self.logins.controls = [self._row(
            l["name"], f"{'Username ' + l['username'] if l['username'] else 'No username'}; "
            f"{'password saved in ' + ('the system keyring' if l['where'] == 'keyring' else 'config.toml') if l['has_password'] else 'no password'}.",
            self._edit_login(l), self._forget("login_forget", l["name"], "login"))
            for l in logins] or [ft.Text("No logins saved yet.", size=12)]
        self.scripts.controls = [self._row(
            s["name"], f"{s['lines']} line(s) saved." if s["lines"] else "(empty)",
            self._edit_script(s), self._forget("script_forget", s["name"], "script"))
            for s in scripts] or [ft.Text("No scripts saved yet.", size=12)]

    def _row(self, title: str, subtitle: str, edit, forget) -> ft.Control:
        return ft.ListTile(
            title=ft.Text(title), subtitle=ft.Text(subtitle, size=12), dense=True,
            trailing=ft.Row(tight=True, spacing=0, controls=[
                ft.IconButton(icon=ft.Icons.EDIT, tooltip=f"Edit {title}", on_click=edit),
                ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip=f"Forget {title}",
                              on_click=forget)]))

    def _forget(self, command: str, name: str, noun: str):
        async def ask(_e) -> None:
            async def go() -> None:
                await self.app.command(command, name=name)
                await self.load()
                self.app.page.update()
            sheets.confirm(self.app.page, f"Forget the {noun} {name}?",
                           "A contact or transport that names it will have nothing to send.",
                           "Forget", go, danger=True)
        return ask

    async def _new_login(self, _e) -> None:
        self._login_sheet({})

    def _edit_login(self, login: dict):
        async def open_sheet(_e) -> None:
            self._login_sheet(login)
        return open_sheet

    def _login_sheet(self, login: dict) -> None:
        original = login.get("name", "")
        name = ft.TextField(label="Name", value=original, dense=True)
        user = ft.TextField(label="Username", value=login.get("username", ""), dense=True,
                            autocorrect=False, enable_suggestions=False)
        password = ft.TextField(label="Password", dense=True, password=True,
                                can_reveal_password=True,
                                hint_text="(unchanged)" if login.get("has_password") else None)

        async def save() -> None:
            result = await self.app.command(
                "login_save", name=name.value or "", username=user.value or "",
                password=password.value or "", original=original)
            if result and result["error"]:
                sheets.snack(self.app.page, result["error"], error=True)
                return
            await self.load()
            self.app.page.update()

        sheets.form(self.app.page, "Edit login" if original else "New login",
                    [name, user, password], "Save", save)

    async def _new_script(self, _e) -> None:
        self._script_sheet({})

    def _edit_script(self, script: dict):
        async def open_sheet(_e) -> None:
            self._script_sheet(script)
        return open_sheet

    def _script_sheet(self, script: dict) -> None:
        original = script.get("name", "")
        name = ft.TextField(label="Name", value=original, dense=True,
                            hint_text="e.g. Check WS1EC mail")
        text = ft.TextField(label="Commands, one per line", multiline=True, min_lines=4,
                            max_lines=10, autocorrect=False, enable_suggestions=False,
                            text_style=ft.TextStyle(font_family="monospace"),
                            hint_text="(unchanged)" if script.get("lines") else None)

        async def save() -> None:
            result = await self.app.command("script_save", name=name.value or "",
                                            text=text.value or "", original=original)
            if result and result["error"]:
                sheets.snack(self.app.page, result["error"], error=True)
                return
            await self.load()
            self.app.page.update()

        sheets.form(self.app.page, "Edit script" if original else "New script",
                    [name, text], "Save", save)
