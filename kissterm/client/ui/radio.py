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
        programs = [p["name"] for p in self.info.get("programs", [])]
        rigs = [r["name"] for r in self.info.get("rigs", [])]
        program = _dropdown("Start this program when it opens", programs, entry.get("program", ""))
        rig = _dropdown("Radio read through Hamlib", rigs, entry.get("rig", ""))
        local = ft.Column(tight=True, spacing=8, visible=bool(programs or rigs or entry.get("program")
                                                              or entry.get("rig")),
                          controls=[ft.Text("On this computer (optional)", size=12,
                                            color=ft.Colors.OUTLINE), program, rig])

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
            if local.visible:
                body["program"], body["rig"] = _picked(program), _picked(rig)
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
                    [name, picker, error, fields, auto, local], "Save", save)


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



class ProgramsSection:
    """Modem programs kissterm starts beside a transport: list, New, Edit,
    Start, Stop, Forget, and a browser over the STATION's files. Every
    field is editable from here, as at the terminal."""

    def __init__(self, app) -> None:
        self.app = app
        self.info: dict = {}
        self.rows = ft.Column(tight=True, spacing=0)
        self.control = ft.Container(padding=ft.Padding.symmetric(horizontal=16, vertical=4),
                                    content=ft.Column(tight=True, spacing=8, controls=[
            ft.Text("Modem programs", theme_style=ft.TextThemeStyle.TITLE_SMALL),
            ft.Text("A program kissterm starts when a transport that names it opens (Mercury, "
                    "Direwolf, VARA...), and stops when kissterm exits. It runs on the station.",
                    size=12, color=ft.Colors.OUTLINE),
            self.rows,
            ft.OutlinedButton(content="New program", icon=ft.Icons.ADD, on_click=self._new)]))

    def load(self, info: dict) -> None:
        self.info = info
        programs = info.get("programs", [])
        self.rows.controls = [self._row(p) for p in programs] or [
            ft.Text("No programs saved yet.", size=12)]

    def _row(self, p: dict) -> ft.Control:
        state = ("running" if p.get("running")
                 else f"exited with code {p['exit_code']}" if p.get("started_by_kissterm")
                 else "not started by kissterm")
        used = [t["name"] for t in self.info.get("transports", []) if t.get("program") == p["name"]]
        return ft.ListTile(
            title=ft.Text(p["name"]), dense=True,
            subtitle=ft.Text(f"{p.get('path', '')} {p.get('args', '')}".strip() + f"  --  {state}"
                             + (f"; used by {', '.join(used)}" if used else ""), size=12),
            trailing=ft.Row(tight=True, spacing=0, controls=[
                ft.IconButton(icon=ft.Icons.STOP if p.get("running") else ft.Icons.PLAY_ARROW,
                              tooltip=("Stop " if p.get("running") else "Start ") + p["name"],
                              on_click=self._run(p)),
                ft.IconButton(icon=ft.Icons.EDIT, tooltip=f"Edit {p['name']}",
                              on_click=self._edit(p)),
                ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip=f"Forget {p['name']}",
                              on_click=self._forget(p))]))

    async def _reload(self) -> None:
        self.load(await self.app.command("radio_info") or {})
        self.app.page.update()

    def _run(self, p: dict):
        async def go(_e) -> None:
            command = "program_stop" if p.get("running") else "program_start"
            result = await self.app.command(command, name=p["name"])
            if result and result["error"]:
                sheets.snack(self.app.page, result["error"], error=True)
            await self._reload()
        return go

    def _forget(self, p: dict):
        async def ask(_e) -> None:
            async def go() -> None:
                result = await self.app.command("program_forget", name=p["name"])
                if result and result["error"]:
                    sheets.snack(self.app.page, result["error"], error=True)
                await self._reload()
            sheets.confirm(self.app.page, f"Forget {p['name']}?",
                           "The program file is not touched.", "Forget", go, danger=True)
        return ask

    async def _new(self, _e) -> None:
        self._sheet({})

    def _edit(self, p: dict):
        async def open_sheet(_e) -> None:
            self._sheet(p)
        return open_sheet

    def _sheet(self, entry: dict) -> None:
        form = self.info.get("program_form", {})
        presets = {p["key"]: p for p in form.get("presets", [])}
        original = entry.get("name", "")
        preset = ft.Dropdown(label="Program", dense=True, value=entry.get("preset") or "custom",
                             options=[ft.DropdownOption(key=k, text=v["label"])
                                      for k, v in presets.items()])
        name = ft.TextField(label="Name", value=original, dense=True,
                            hint_text="e.g. mercury, vara-hf")
        path = ft.TextField(label="Program file (on the station)", value=entry.get("path", ""),
                            dense=True, autocorrect=False, enable_suggestions=False)
        args = ft.TextField(label="Arguments", value=entry.get("args", ""), dense=True,
                            autocorrect=False, enable_suggestions=False)
        wine = ft.Checkbox(label="Run under Wine", value=bool(entry.get("wine")))
        cwd = ft.TextField(label="Working folder", value=entry.get("cwd", ""), dense=True,
                           hint_text="its own folder")
        timeout = ft.TextField(label="Seconds to wait", dense=True,
                               value=str(entry.get("start_timeout", 30)),
                               keyboard_type=ft.KeyboardType.NUMBER)
        stop = ft.Checkbox(label="Stop it when kissterm exits", value=bool(entry.get("stop_on_exit", True)))
        note = ft.Text("", size=12, color=ft.Colors.OUTLINE)

        def show_note() -> None:
            p = presets.get(preset.value)
            note.value = f"{p['note']} (path: {p['source']})" if p and p.get("note") else ""

        async def changed(_e) -> None:
            show_note()
            self.app.page.update()

        preset.on_select = changed
        show_note()

        async def browse(_e) -> None:
            await self._browse(path)

        async def save() -> None:
            body = {"name": name.value or "", "preset": preset.value or "custom",
                    "path": path.value or "", "args": args.value or "", "wine": bool(wine.value),
                    "cwd": cwd.value or "", "start_timeout": timeout.value or "",
                    "stop_on_exit": bool(stop.value)}
            result = await self.app.command("program_save", entry=body, original=original)
            if result is None:
                return
            if result["error"]:
                sheets.snack(self.app.page, result["error"], error=True)
                self._sheet({**entry, **body})  # the sheet closed with Save: show it again
                return
            await self._reload()

        sheets.form(self.app.page, "Edit program" if original else "New program",
                    [name, preset, note, path,
                     ft.OutlinedButton(content="Browse the station's files", icon=ft.Icons.FOLDER_OPEN,
                                       on_click=browse),
                     args, wine, cwd, timeout, stop], "Save", save)

    async def _browse(self, target: ft.TextField) -> None:
        """Walk the station's folders (executables only) and put the chosen
        file in `target`. Names only; the station filters the listing."""
        import os

        start = os.path.dirname(target.value) if target.value and os.path.isabs(target.value) else ""
        listing = await self.app.command("program_browse", path=start) or {}
        heading = ft.Text(listing.get("path", ""), size=12, selectable=True)
        column = ft.Column(tight=True, spacing=0, scroll=ft.ScrollMode.AUTO, height=320)

        async def show(path: str) -> None:
            nonlocal listing
            listing = await self.app.command("program_browse", path=path) or {}
            heading.value = listing.get("error") or listing.get("path", "")
            rows: list[ft.Control] = []
            if listing.get("parent"):
                rows.append(self._entry_tile("..", ft.Icons.ARROW_UPWARD, show, listing["parent"]))
            else:
                rows += [self._entry_tile(r, ft.Icons.FOLDER, show, r) for r in listing.get("roots", [])
                         if r != listing.get("path")]
            join = lambda n: os.path.join(listing["path"], n)  # noqa: E731
            rows += [self._entry_tile(n + "/", ft.Icons.FOLDER, show, join(n))
                     for n in listing.get("folders", [])]

            async def choose(full: str) -> None:
                target.value = full
                self.app.page.pop_dialog()
                self.app.page.update()

            rows += [self._entry_tile(n, ft.Icons.SETTINGS_APPLICATIONS, choose, join(n))
                     for n in listing.get("programs", [])]
            if listing.get("truncated"):
                rows.append(ft.Text("(list cut short)", size=12))
            column.controls = rows
            self.app.page.update()

        await show(listing.get("path", start))
        self.app.page.show_dialog(sheets.sheet([
            ft.Text("Choose the program file", theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
            heading, column,
            ft.Row(alignment=ft.MainAxisAlignment.END, controls=[
                ft.TextButton(content="Cancel", on_click=self._close)])], scrollable=True))

    async def _close(self, _e) -> None:
        self.app.page.pop_dialog()

    @staticmethod
    def _entry_tile(label: str, icon, action, argument: str) -> ft.Control:
        async def tapped(_e) -> None:
            await action(argument)
        return ft.ListTile(leading=ft.Icon(icon), title=ft.Text(label), dense=True, on_click=tapped)


class RigsSection:
    """Radios kissterm reads through Hamlib's rigctld: list, New, Edit, Test,
    Forget, and Hamlib's model list as a filtered picker."""

    def __init__(self, app) -> None:
        self.app = app
        self.info: dict = {}
        self.rows = ft.Column(tight=True, spacing=0)
        self.control = ft.Container(padding=ft.Padding.symmetric(horizontal=16, vertical=4),
                                    content=ft.Column(tight=True, spacing=8, controls=[
            ft.Text("Radios (Hamlib)", theme_style=ft.TextThemeStyle.TITLE_SMALL),
            ft.Text("A radio kissterm reads and tunes through Hamlib's rigctld. Test reads its "
                    "frequency and mode and never transmits.", size=12, color=ft.Colors.OUTLINE),
            self.rows,
            ft.OutlinedButton(content="New radio", icon=ft.Icons.ADD, on_click=self._new)]))

    def load(self, info: dict) -> None:
        self.info = info
        self.rows.controls = [self._row(r) for r in info.get("rigs", [])] or [
            ft.Text("No radios saved yet.", size=12)]

    def _row(self, r: dict) -> ft.Control:
        bands = ", ".join(r.get("tune_bands") or []) or "never"
        where = r.get("device") or f"rigctld {r.get('host')}:{r.get('port')}"
        return ft.ListTile(
            title=ft.Text(r["name"]), dense=True,
            subtitle=ft.Text(f"Hamlib model {r.get('model')} on {where}; stops above SWR "
                             f"{r.get('swr_trip')}; tunes the ATU on: {bands}", size=12),
            trailing=ft.Row(tight=True, spacing=0, controls=[
                ft.IconButton(icon=ft.Icons.NETWORK_CHECK, tooltip=f"Test {r['name']}",
                              on_click=self._test(r)),
                ft.IconButton(icon=ft.Icons.EDIT, tooltip=f"Edit {r['name']}", on_click=self._edit(r)),
                ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip=f"Forget {r['name']}",
                              on_click=self._forget(r))]))

    async def _reload(self) -> None:
        self.load(await self.app.command("radio_info") or {})
        self.app.page.update()

    def _test(self, r: dict):
        async def go(_e) -> None:
            result = await self.app.command("rig_test", name=r["name"])
            if result:
                sheets.snack(self.app.page, result["text"], error=not result["ok"])
        return go

    def _forget(self, r: dict):
        async def ask(_e) -> None:
            async def go() -> None:
                result = await self.app.command("rig_forget", name=r["name"])
                if result and result["error"]:
                    sheets.snack(self.app.page, result["error"], error=True)
                await self._reload()
            sheets.confirm(self.app.page, f"Forget {r['name']}?",
                           "The radio is not touched.", "Forget", go, danger=True)
        return ask

    async def _new(self, _e) -> None:
        self._sheet({})

    def _edit(self, r: dict):
        async def open_sheet(_e) -> None:
            self._sheet(r)
        return open_sheet

    def _sheet(self, entry: dict) -> None:
        original = entry.get("name", "")
        bands = self.info.get("rig_form", {}).get("bands", [])
        name = ft.TextField(label="Name", value=original, dense=True, hint_text="e.g. ft991a")
        model = ft.TextField(label="Hamlib model number", value=str(entry.get("model", "")),
                             dense=True, keyboard_type=ft.KeyboardType.NUMBER)
        device = ft.TextField(label="CAT device (on the station)", value=entry.get("device", ""),
                              dense=True, hint_text="/dev/ttyUSB0 or COM3")
        speed = ft.TextField(label="CAT baud rate", value=str(entry.get("speed", "")), dense=True,
                             hint_text="rig default", keyboard_type=ft.KeyboardType.NUMBER)
        swr = ft.TextField(label="Stop transmitting above SWR", dense=True,
                           value=str(entry.get("swr_trip", 3.0)),
                           keyboard_type=ft.KeyboardType.NUMBER)
        chosen = set(entry.get("tune_bands") or [])
        boxes = {b: ft.Checkbox(label=b, value=b in chosen) for b in bands}
        host = ft.TextField(label="rigctld host", value=str(entry.get("host", "127.0.0.1")), dense=True)
        port = ft.TextField(label="rigctld port", value=str(entry.get("port", 4532)), dense=True,
                            keyboard_type=ft.KeyboardType.NUMBER)
        path = ft.TextField(label="rigctld program", value=entry.get("rigctld_path", ""), dense=True,
                            hint_text="rigctld on PATH")
        ptt = ft.TextField(label="Unkey after (seconds)", value=str(entry.get("ptt_timeout", 120)),
                           dense=True, keyboard_type=ft.KeyboardType.NUMBER)

        async def pick(_e) -> None:
            await self._pick_model(model)

        async def save() -> None:
            body = {"name": name.value or "", "model": model.value or "", "device": device.value or "",
                    "speed": speed.value or "", "swr_trip": swr.value or "", "host": host.value or "",
                    "port": port.value or "", "rigctld_path": path.value or "",
                    "ptt_timeout": ptt.value or "", "tune_bands": [b for b, c in boxes.items() if c.value]}
            result = await self.app.command("rig_save", entry=body, original=original)
            if result is None:
                return
            if result["error"]:
                sheets.snack(self.app.page, result["error"], error=True)
                self._sheet({**entry, **body})
                return
            await self._reload()

        sheets.form(self.app.page, "Edit radio" if original else "New radio",
                    [name, model,
                     ft.OutlinedButton(content="Pick from Hamlib's list", icon=ft.Icons.SEARCH,
                                       on_click=pick),
                     device, speed, swr,
                     ft.Text("Tune the ATU before connecting on (none = never):", size=12,
                             color=ft.Colors.OUTLINE),
                     ft.Row(wrap=True, spacing=8, controls=list(boxes.values())),
                     host, port, path, ptt], "Save", save)

    async def _pick_model(self, target: ft.TextField) -> None:
        models = await self.app.command("rig_models") or []
        filter_box = ft.TextField(label="Filter", dense=True, hint_text="e.g. FT-991 or IC-7300",
                                  autofocus=True)
        column = ft.Column(tight=True, spacing=0, scroll=ft.ScrollMode.AUTO, height=320)

        def draw() -> None:
            words = (filter_box.value or "").lower().split()
            rows = []
            for m in models:
                label = f"{m['make']} {m['name']}"
                if all(w in label.lower() for w in words):
                    rows.append(self._model_tile(label, m, target))
                    if len(rows) >= 200:
                        break
            column.controls = rows or [ft.Text(
                "No match." if models else "Hamlib's rigctl was not found on the station, so "
                "there is no list. Type the model number instead.", size=12)]

        async def changed(_e) -> None:
            draw()
            self.app.page.update()

        filter_box.on_change = changed
        draw()
        self.app.page.show_dialog(sheets.sheet([
            ft.Text("Choose your radio", theme_style=ft.TextThemeStyle.TITLE_MEDIUM), filter_box,
            column, ft.Row(alignment=ft.MainAxisAlignment.END, controls=[
                ft.TextButton(content="Cancel", on_click=self._close)])], scrollable=True))

    async def _close(self, _e) -> None:
        self.app.page.pop_dialog()

    def _model_tile(self, label: str, m: dict, target: ft.TextField) -> ft.Control:
        async def chosen(_e) -> None:
            target.value = str(m["model"])
            self.app.page.pop_dialog()
            self.app.page.update()
        return ft.ListTile(title=ft.Text(label), subtitle=ft.Text(f"{m['model']}  {m.get('status', '')}",
                                                                  size=12), dense=True, on_click=chosen)
