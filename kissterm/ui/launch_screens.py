"""Settings > Radio: the dialogs for Programs and Rigs (ROADMAP P3a).

Each is a thin view over `core.radio` (`save_program`, `save_rig`,
`browse_programs`, `rig_models`), which validates and saves, so the phone
and web client, which call the same methods, cannot disagree with this one
about what is valid. A dialog shows `Radio`'s own error text and closes only
once the entry is saved.
"""

from __future__ import annotations

import sys

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.coordinate import Coordinate
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Footer, Input, Label, Select, SelectionList, Static

from ..launch.presets import DARWIN, LINUX, PRESETS, WINDOWS, default_args, default_path, needs_wine
from ..transport.forms import BANDS, KEYING_LABELS


def platform_name() -> str:
    """`launch.presets`' name for this computer."""
    if sys.platform.startswith("win"):
        return WINDOWS
    return DARWIN if sys.platform == "darwin" else LINUX


class ProgramFileScreen(ModalScreen["str | None"]):
    """Choose a modem program's file on THIS computer. Folders and
    executables only (`launch/browse.py`); Enter or Choose acts on the
    highlighted row. Returns the full path, or None."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, radio, start: str = "") -> None:
        super().__init__()
        self._radio = radio
        self._path = start
        self._listing: dict = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="transport-box"):
            yield Label("Choose the program file", id="connect-title")
            yield Static("", id="program-file-path")
            yield DataTable(id="program-file-table", cursor_type="row")
            with Horizontal(id="connect-buttons"):
                yield Button("Choose", variant="primary", id="program-file-choose")
                yield Button("Cancel", id="program-file-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#program-file-table", DataTable).add_columns("Name", "Kind")
        self._show(self._path)

    def _show(self, path: str) -> None:
        listing = self._radio.browse_programs(path)
        self._listing = listing
        self._path = listing["path"]
        table = self.query_one("#program-file-table", DataTable)
        table.clear()
        if listing["parent"]:
            table.add_row("..", "folder", key="..")
        else:
            for root in listing["roots"]:
                if root != listing["path"]:
                    table.add_row(root, "drive" if root[1:2] == ":" else "folder", key=f"root:{root}")
        for name in listing["folders"]:
            table.add_row(name + "/", "folder", key=f"d:{name}")
        for name in listing["programs"]:
            table.add_row(name, "program", key=f"f:{name}")
        shown = listing["error"] or listing["path"] + ("  (list cut short)" if listing["truncated"] else "")
        self.query_one("#program-file-path", Static).update(shown)
        if table.row_count:
            table.move_cursor(row=0)

    def _open(self, key: str) -> None:
        import os

        if key == "..":
            self._show(self._listing["parent"])
        elif key.startswith("root:"):
            self._show(key[5:])
        elif key.startswith("d:"):
            self._show(os.path.join(self._path, key[2:]))
        elif key.startswith("f:"):
            self.dismiss(os.path.join(self._path, key[2:]))

    @on(DataTable.RowSelected, "#program-file-table")
    def _selected(self, event: DataTable.RowSelected) -> None:
        self._open(str(event.row_key.value))

    @on(Button.Pressed, "#program-file-choose")
    def _choose(self) -> None:
        table = self.query_one("#program-file-table", DataTable)
        if table.row_count and table.cursor_row >= 0:
            self._open(str(table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key.value))

    @on(Button.Pressed, "#program-file-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


class ProgramEntryScreen(ModalScreen["str | None"]):
    """Add or edit one Programs entry. Returns its name once saved."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, radio, entry: dict | None = None) -> None:
        super().__init__()
        self._radio = radio
        self._entry = dict(entry) if entry else {}
        self._original = str(self._entry.get("name", ""))
        self._preset = str(self._entry.get("preset") or "custom")
        self._platform = platform_name()

    def compose(self) -> ComposeResult:
        e = self._entry
        with Vertical(id="transport-box"):
            yield Label("Edit program" if self._original else "New program", id="connect-title")
            with VerticalScroll(id="transport-form"):
                yield self._row("Name", Input(str(e.get("name", "")), compact=True, id="prog-name",
                                              placeholder="e.g. mercury, vara-hf"))
                yield self._row("Program", Select(
                    [(p.label, p.key) for p in PRESETS.values()], value=self._preset,
                    allow_blank=False, compact=True, id="prog-preset"))
                yield self._row("Program file", Input(str(e.get("path", "")), compact=True,
                                                      id="prog-path"))
                yield Horizontal(Label("", classes="settings-label"),
                                 Button("Browse this computer...", compact=True, id="prog-browse"),
                                 classes="settings-row")
                yield self._row("Arguments", Input(str(e.get("args", "")), compact=True,
                                                   id="prog-args"))
                yield self._row("Keys the radio", Select(
                    [(label, key) for key, label in KEYING_LABELS.items()],
                    value=str(e.get("keying") or "own"), allow_blank=False, compact=True,
                    id="prog-keying"))
                wine = Checkbox("Run under Wine", bool(e.get("wine")), compact=True, id="prog-wine")
                wine.display = self._platform != WINDOWS
                yield wine
                yield Static("", id="prog-note")
                yield Label("Advanced", id="transport-script-title")
                yield self._row("Working folder", Input(str(e.get("cwd", "")), compact=True,
                                                        id="prog-cwd", placeholder="its own folder"))
                yield self._row("Seconds to wait", Input(str(e.get("start_timeout", 30)),
                                                         compact=True, id="prog-timeout"))
                yield Checkbox("Stop it when kissterm exits", bool(e.get("stop_on_exit", True)),
                               compact=True, id="prog-stop")
                yield Label("", id="transport-error")
            with Horizontal(id="connect-buttons"):
                yield Button("Save", variant="primary", id="prog-save")
                yield Button("Cancel", id="prog-cancel")

    @staticmethod
    def _row(label: str, widget) -> Horizontal:
        return Horizontal(Label(label, classes="settings-label"), widget, classes="settings-row")

    def on_mount(self) -> None:
        self._show_note(self._preset)
        self.query_one("#prog-name", Input).focus()

    def _show_note(self, preset: str) -> None:
        p = PRESETS.get(preset)
        text = ""
        if p is not None and p.note:
            text = f"{p.note} (path: {p.source})"
        self.query_one("#prog-note", Static).update(text)

    @on(Select.Changed, "#prog-preset")
    def _preset_changed(self, event: Select.Changed) -> None:
        key = str(event.value)
        if key not in PRESETS or key == self._preset:
            return
        old = self._preset
        self._preset = key
        path, args = self.query_one("#prog-path", Input), self.query_one("#prog-args", Input)
        # Fill only what the operator has not typed: empty, or still the
        # previous preset's own default.
        if not path.value.strip() or path.value == default_path(old, self._platform):
            path.value = default_path(key, self._platform)
        if not args.value.strip() or args.value == default_args(old):
            args.value = default_args(key)
        self.query_one("#prog-wine", Checkbox).value = needs_wine(key, self._platform)
        self._show_note(key)

    @on(Button.Pressed, "#prog-browse")
    async def _browse(self) -> None:
        import os

        current = self.query_one("#prog-path", Input).value.strip()
        start = os.path.dirname(current) if current and os.path.isabs(current) else ""
        chosen = await self.app.push_screen_wait(ProgramFileScreen(self._radio, start))
        if chosen:
            self.query_one("#prog-path", Input).value = chosen

    @on(Button.Pressed, "#prog-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#prog-save")
    def _save(self) -> None:
        q = self.query_one
        entry = dict(self._entry)
        entry.update(
            name=q("#prog-name", Input).value.strip(), preset=self._preset,
            path=q("#prog-path", Input).value.strip(), args=q("#prog-args", Input).value.strip(),
            keying=str(q("#prog-keying", Select).value),
            wine=q("#prog-wine", Checkbox).value, cwd=q("#prog-cwd", Input).value.strip(),
            start_timeout=q("#prog-timeout", Input).value.strip(),
            stop_on_exit=q("#prog-stop", Checkbox).value)
        error = self._radio.save_program(entry, self._original)
        if error:
            q("#transport-error", Label).update(f"[red]{error}[/red]")
            return
        self.dismiss(entry["name"])


class RigModelScreen(ModalScreen["int | None"]):
    """Pick a radio from the models this computer's Hamlib supports
    (`rigctl -l`, run once). Type to filter. Returns Hamlib's model number."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]
    LIMIT = 200

    def __init__(self, radio) -> None:
        super().__init__()
        self._radio = radio
        self._models: list[dict] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="transport-box"):
            yield Label("Choose your radio", id="connect-title")
            yield Input(placeholder="Type to filter, e.g. FT-991 or IC-7300", compact=True,
                        id="rig-model-filter")
            yield Static("", id="rig-model-note")
            yield DataTable(id="rig-model-table", cursor_type="row")
            with Horizontal(id="connect-buttons"):
                yield Button("Choose", variant="primary", id="rig-model-choose")
                yield Button("Cancel", id="rig-model-cancel")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#rig-model-table", DataTable).add_columns("Model", "Number", "Status")
        self.query_one("#rig-model-note", Static).update("Reading Hamlib's list...")
        self._models = await self._radio.rig_models()
        if not self._models:
            self.query_one("#rig-model-note", Static).update(
                "Hamlib's rigctl was not found, so there is no list. Install Hamlib "
                "(libhamlib-utils), or type the model number in the radio's form.")
        self._filter("")
        self.query_one("#rig-model-filter", Input).focus()

    def _filter(self, text: str) -> None:
        words = text.lower().split()
        table = self.query_one("#rig-model-table", DataTable)
        table.clear()
        shown = 0
        for m in self._models:
            label = f"{m['make']} {m['name']}"
            if all(w in label.lower() for w in words):
                table.add_row(label, str(m["model"]), m.get("status", ""), key=str(m["model"]))
                shown += 1
                if shown >= self.LIMIT:
                    break
        if self._models:
            self.query_one("#rig-model-note", Static).update(
                f"{shown} shown" + (" (filter to see more)" if shown >= self.LIMIT else ""))

    @on(Input.Changed, "#rig-model-filter")
    def _changed(self, event: Input.Changed) -> None:
        self._filter(event.value)

    @on(DataTable.RowSelected, "#rig-model-table")
    def _selected(self, event: DataTable.RowSelected) -> None:
        self.dismiss(int(str(event.row_key.value)))

    @on(Button.Pressed, "#rig-model-choose")
    def _choose(self) -> None:
        table = self.query_one("#rig-model-table", DataTable)
        if table.row_count and table.cursor_row >= 0:
            key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key.value
            self.dismiss(int(str(key)))

    @on(Button.Pressed, "#rig-model-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


class RigEntryScreen(ModalScreen["str | None"]):
    """Add or edit one Rigs entry (a radio reached through Hamlib's
    `rigctld`). Returns its name once saved."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, radio, entry: dict | None = None) -> None:
        super().__init__()
        self._radio = radio
        self._entry = dict(entry) if entry else {}
        self._original = str(self._entry.get("name", ""))

    @staticmethod
    def _row(label: str, widget) -> Horizontal:
        return Horizontal(Label(label, classes="settings-label"), widget, classes="settings-row")

    def compose(self) -> ComposeResult:
        e = self._entry
        with Vertical(id="transport-box"):
            yield Label("Edit radio" if self._original else "New radio", id="connect-title")
            with VerticalScroll(id="transport-form"):
                yield self._row("Name", Input(str(e.get("name", "")), compact=True, id="rig-name",
                                              placeholder="e.g. ft991a"))
                yield self._row("Hamlib model", Input(str(e.get("model", "")), compact=True,
                                                      id="rig-model", placeholder="number"))
                yield Horizontal(Label("", classes="settings-label"),
                                 Button("Pick from Hamlib's list...", compact=True, id="rig-pick"),
                                 classes="settings-row")
                yield self._row("CAT device", Input(str(e.get("device", "")), compact=True,
                                                    id="rig-device",
                                                    placeholder="/dev/ttyUSB0 or COM3"))
                yield self._row("CAT baud rate", Input(str(e.get("speed", "")), compact=True,
                                                       id="rig-speed", placeholder="rig default"))
                yield self._row("Stop above SWR", Input(str(e.get("swr_trip", 3.0)), compact=True,
                                                        id="rig-swr"))
                yield Label("Tune the ATU before connecting on these bands (none = never):",
                            id="transport-script-hint")
                chosen = set(e.get("tune_bands") or [])
                yield SelectionList(*[(b, b, b in chosen) for b in BANDS], id="rig-bands")
                yield Label("Advanced", id="transport-script-title")
                yield self._row("rigctld host", Input(str(e.get("host", "127.0.0.1")),
                                                      compact=True, id="rig-host"))
                yield self._row("rigctld port", Input(str(e.get("port", 4532)), compact=True,
                                                      id="rig-port"))
                yield self._row("rigctld program", Input(str(e.get("rigctld_path", "")),
                                                         compact=True, id="rig-path",
                                                         placeholder="rigctld on PATH"))
                yield self._row("Unkey after (s)", Input(str(e.get("ptt_timeout", 120)),
                                                         compact=True, id="rig-ptt"))
                yield Label("", id="transport-error")
            with Horizontal(id="connect-buttons"):
                yield Button("Save", variant="primary", id="rig-save")
                yield Button("Cancel", id="rig-cancel")

    def on_mount(self) -> None:
        self.query_one("#rig-name", Input).focus()

    @on(Button.Pressed, "#rig-pick")
    async def _pick(self) -> None:
        model = await self.app.push_screen_wait(RigModelScreen(self._radio))
        if model is not None:
            self.query_one("#rig-model", Input).value = str(model)

    @on(Button.Pressed, "#rig-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#rig-save")
    def _save(self) -> None:
        q = self.query_one
        entry = dict(self._entry)
        entry.update(
            name=q("#rig-name", Input).value.strip(), model=q("#rig-model", Input).value.strip(),
            device=q("#rig-device", Input).value.strip(), speed=q("#rig-speed", Input).value.strip(),
            swr_trip=q("#rig-swr", Input).value.strip(), host=q("#rig-host", Input).value.strip(),
            port=q("#rig-port", Input).value.strip(), rigctld_path=q("#rig-path", Input).value.strip(),
            ptt_timeout=q("#rig-ptt", Input).value.strip(),
            tune_bands=[b for b in q("#rig-bands", SelectionList).selected])
        error = self._radio.save_rig(entry, self._original)
        if error:
            q("#transport-error", Label).update(f"[red]{error}[/red]")
            return
        self.dismiss(entry["name"])
