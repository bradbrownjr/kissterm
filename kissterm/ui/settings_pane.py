"""The Settings pane: every setup answer, editable, without leaving the app.

Generated from `settings_schema.SETTINGS_SCHEMA` rather than hand-built. Adding
a config option means adding one schema entry; nothing here changes. That is
deliberate -- the first version of this pane was hand-written, read-only, and
already out of date with `Config` on the day it shipped.

Two things this pane must get right, both learned the hard way:

**Save nothing until everything validates.** Coerce every field first, collect
the failures, and only then write to `Config`. A partial save leaves the
operator with some new values and some old ones and no way to tell which --
worse than refusing outright.

**Say when a change takes effect.** `Field.apply` distinguishes "live", "next
connection" and "restart", and the pane labels each field accordingly. Link
parameters deliberately do *not* touch an established link: paclen, window and
the timers were negotiated when it came up, and changing them underneath a
running conversation corrupts it.

Transports get their own section rather than schema fields, because they are a
list of dicts with kind-specific keys -- a serial port has a baud rate, a TCP
host has an address -- and flattening that would hard-code every transport kind
into the UI. See `settings_schema`'s docstring.

Every other section is one list with a row per field and one shared editor,
not a widget per field; `SettingsPane`'s docstring says why (startup time).
"""

from __future__ import annotations

import logging

from textual import events, on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.message import Message
from textual.widgets import (
    Button,
    Checkbox,
    ContentSwitcher,
    Input,
    Label,
    OptionList,
    Select,
    Static,
)
from textual.widgets.option_list import Option, OptionDoesNotExist

from ..config import (
    SECRET_LOGINS,
    credential_store,
    find_credential,
    forget_credential,
    set_credential,
)
from ..aprs import symbols
from ..gps import discover_serial_gps
from ..locator import LocatorError, from_grid, to_grid
from .settings_schema import (
    SETTINGS_SCHEMA,
    Field,
    Section,
    ValidationError,
    coerce,
    cross_check,
    format_value,
    get_value,
    set_value,
)
from .symbol_picker import SymbolPicker

log = logging.getLogger(__name__)

#: Sentinel `Select` value meaning "use the text field below instead of any
#: preset" -- not a real config value, never written to `Config`. Only one
#: `"custom_choice"` field exists today (`aprs.path`), so this is not
#: namespaced per-field; generalize it if a second one is ever added.
_CUSTOM_SENTINEL = "__custom__"
_CUSTOM_LABEL = "Custom..."

#: The two hand-built sections: transports, and saved logins and scripts.
RADIO = "Radio"
LOGINS = "Logins"

#: Radio comes straight after this schema section. "Station" puts callsign
#: and aliases at the very top, with the hardware they talk through right
#: below -- identity first, then the radio, then tuning.
TRANSPORTS_AFTER_SECTION = "Station"

#: Added to a field's help line only where Save alone is not the whole
#: story: every field takes effect on Save, so saying so for most of them
#: was noise (operator, 2026-09-24).
APPLY_NOTE = {
    "live": "",
    "connect": "Used from the next connection.",
    "restart": "Needs a restart.",
}

#: The help line before any field has focus.
_HELP_IDLE = "Up and Down choose a setting, Enter changes it; its help shows here."

#: A row: the label padded to the settings grid's first column (DESIGN.md
#: section 4), then the value, cut short past this many characters.
_LABEL_WIDTH = 26
_VALUE_WIDTH = 60


def _GAP() -> Option:
    """A blank row before a heading."""
    return Option("", disabled=True)


def _tab_id(title: str) -> str:
    """A DOM-safe id for a section (`"Link"` -> `settings-tab-link`)."""
    return "settings-tab-" + title.lower().replace(" ", "-")


def section_titles() -> list[str]:
    """The section list, top to bottom: the schema's, plus Radio and Logins."""
    titles = [section.title for section in SETTINGS_SCHEMA]
    titles.insert(titles.index(TRANSPORTS_AFTER_SECTION) + 1, RADIO)
    titles.append(LOGINS)
    return titles


#: What "Test" prints for each `discovery.Identity.verdict`. An
#: operator pressing this button wants OK or FAILED, not the paragraph
#: `identity.summary` carries for the scan results list -- that wording stays
#: in `discovery.py` for the audience that has never seen a silent KISS port
#: before. This button's audience just asked a specific transport a direct
#: question and wants a direct answer.
_TEST_LABEL = {
    "agwpe": "OK",
    "kiss": "OK",
    "not-a-tnc": "FAILED",
    "unreachable": "FAILED",
    # Silence is normal for an idle KISS TNC.  Calling it UNKNOWN sounded like
    # a failed setup, even though the TCP connection itself is open.
    "unknown": "OPEN",
}


def _test_result_line(host: str, port: int, identity) -> str:
    label = _TEST_LABEL.get(identity.verdict, "UNKNOWN")
    if identity.is_tnc:
        reason = identity.summary.removeprefix("Confirmed: ").rstrip(".")
    elif identity.verdict in ("not-a-tnc", "unreachable"):
        # Already one short sentence, and the wording ("Not a TNC", what
        # answered) is exactly what an operator needs to fix config.toml.
        reason = identity.summary.rstrip(".")
    else:
        # Silence is inconclusive, not a failure -- an idle KISS TNC looks
        # exactly like this. Say so in five words, not a paragraph.
        reason = "open, identity unconfirmed (silent KISS is normal)"
    return f"{host}:{port}  {label}  --  {reason}"




#: Field path -> its schema entry, and the title of its section.
_SPECS: dict[str, Field] = {f.path: f for s in SETTINGS_SCHEMA for f in s.fields}
_SECTION_OF: dict[str, str] = {f.path: s.title for s in SETTINGS_SCHEMA for f in s.fields}
#: A field list's id -> its section.
_SECTION_BY_TAB: dict[str, Section] = {_tab_id(s.title): s for s in SETTINGS_SCHEMA}
#: Field path -> the heading (`Field.rule_before`) of the group it is in:
#: its own, or the last one before it in its section.
_GROUP_OF: dict[str, str] = {}
for _section in SETTINGS_SCHEMA:
    _group = ""
    for _field in _section.fields:
        _group = _field.rule_before or _group
        _GROUP_OF[_field.path] = _group
#: The notes above Radio and Logins, which have no schema section.
_HAND_BUILT_NOTES = {
    _tab_id(RADIO): (
        "The TNC or modem kissterm talks through. USB and serial TNCs are "
        "noticed when you plug them in. 'Scan for hardware' looks on the "
        "network and paired Bluetooth; add a VARA or Mercury modem with "
        "'New'. A node reached by Telnet or SSH is an Address Book contact "
        "(Ctrl+G, New). Nothing here transmits."
    ),
    _tab_id(LOGINS): (
        "Logins and command scripts an Address Book contact can use by name, "
        "so a change here reaches every contact that uses it. Nothing is "
        "sent until a connect uses one."
    ),
}
#: Fields another field's `only_when` depends on.
_CONTROLS = {f.only_when[0] for f in _SPECS.values() if f.only_when}


class _FieldList(OptionList):
    """One section's settings, a row each: the label and the current value.

    Enter changes the highlighted one (an on/off setting flips at once);
    the editor under the list follows the highlight."""

    BINDINGS = [Binding("enter", "select", "Change")]


class _Editor(Vertical):
    """The one set of controls every field is edited with."""

    BINDINGS = [Binding("escape", "done", "Back to the list")]

    def action_done(self) -> None:
        self.post_message(_Editor.Done())

    class Done(Message):
        """Esc in the editor: back to the list."""


class SettingsPane(Vertical):
    """A section list, one section's settings, one editor, and a bar that
    never scrolls.

    **Rebuilt 2026-09-27 for startup time** (operator: "Go ahead with the
    speed-up"). The 2026-09-25 form was a label and a control per field,
    430 of the app's 630 widgets, and Textual built and styled every one
    before the first screen: 2.3 of the 4.5 s to the first screen. Building
    them when a section opens was turned down on 2026-09-25 (a wait while
    moving around is worse than a slow launch), so there are fewer widgets
    instead. A section is one `OptionList`, a row per field with its
    current value, and one editor under it (an input, a list, an on/off
    box) changes the highlighted row. About 60 widgets; the first screen
    comes 2 s sooner, the same as with no Settings at all.

    What the 2026-09-25 rebuild settled still holds: sections down the
    left, one row per field, the help for the field you are on in one line
    at the bottom with when it takes effect and any error in red, the
    custom theme colours only while Theme is Custom (`Field.only_when`).
    Tuning the defaults already get right sits under each section's
    "Advanced" heading, after everything else.

    **Edits are a draft** (`_draft`, path -> what was typed or chosen) until
    Save, and Save still validates everything before writing anything.
    Save and Reload walk the whole schema, whatever is on screen.
    """

    def __init__(self) -> None:
        super().__init__()
        #: Row id -> (label, help, apply) for the help line (Radio, Logins).
        self._row_help: dict[str, tuple[str, str, str]] = {}
        #: Field path -> what the editor holds for it, not yet saved.
        self._draft: dict[str, object] = {}
        #: Field path -> the validation error Save found in it.
        self._errors: dict[str, str] = {}
        #: Secret field path -> where its saved value is, as words.
        self._secret_where: dict[str, str] = {}
        #: The field the editor is showing, "" for none.
        self._editing = ""

    def compose(self) -> ComposeResult:
        ascii_safe = self.app.config.ascii_safe  # type: ignore[attr-defined]
        with Horizontal(id="settings-body"):
            yield OptionList(
                *(Option(title, id=_tab_id(title)) for title in section_titles()),
                id="settings-sections",
            )
            with Vertical(id="settings-main"):
                yield Static(SETTINGS_SCHEMA[0].note, id="settings-note", classes="settings-note")
                with ContentSwitcher(id="settings-switcher", initial=_tab_id(SETTINGS_SCHEMA[0].title)):
                    for section in SETTINGS_SCHEMA:
                        yield _FieldList(id=_tab_id(section.title), classes="settings-fields")
                        if section.title == TRANSPORTS_AFTER_SECTION:
                            with VerticalScroll(id=_tab_id(RADIO), classes="settings-section"):
                                yield from self._compose_transports()
                    with VerticalScroll(id=_tab_id(LOGINS), classes="settings-section"):
                        yield from self._compose_credentials()
                        yield from self._compose_scripts()
                with _Editor(id="settings-editor"):
                    with Horizontal(classes="settings-row"):
                        yield Label("", id="settings-edit-label", classes="settings-label")
                        yield Input(id="settings-edit-input", compact=True)
                        yield Select([("-", "-")], id="settings-edit-select", allow_blank=False, compact=True)
                        yield Checkbox("off", id="settings-edit-check", compact=True)
                        yield SymbolPicker(
                            picker_id="settings-edit-symbol", select_id="settings-edit-symbol-select",
                            ascii_safe=ascii_safe, compact=True,
                        )
                        yield Static("", id="settings-edit-swatch", classes="settings-swatch")
                        yield Button("Scan", compact=True, id="aprs-gps-scan")
                    with Horizontal(classes="settings-row", id="settings-edit-extra"):
                        yield Label("", classes="settings-label")
                        yield Input(id="settings-edit-custom", compact=True)
                        yield Select(
                            [("Scan local serial ports first", Select.BLANK)],
                            id="aprs-gps-device-picker", allow_blank=True, compact=True,
                        )

        with Vertical(id="settings-bar"):
            yield Static("", id="settings-banner", classes="settings-banner")
            yield Static(_HELP_IDLE, id="settings-help-line")
            with Horizontal(classes="settings-actions"):
                yield Static("", id="settings-footer")
                yield Button("Save", variant="primary", compact=True, id="settings-save")
                yield Button("Reload", compact=True, id="settings-reload")

    # -- sections -------------------------------------------------------------

    def show_section(self, title: str) -> None:
        """Open a section by its title (`"Radio"`) or its id."""
        tab = title if title.startswith("settings-tab-") else _tab_id(title)
        self.query_one("#settings-switcher", ContentSwitcher).current = tab
        sections = self.query_one("#settings-sections", OptionList)
        index = sections.get_option_index(tab)
        if sections.highlighted != index:
            sections.highlighted = index
        self._section_opened(tab)

    @property
    def current_section(self) -> str:
        return self.query_one("#settings-switcher", ContentSwitcher).current or ""

    @on(OptionList.OptionHighlighted, "#settings-sections")
    def _section_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id:
            self.query_one("#settings-switcher", ContentSwitcher).current = event.option.id
            self._section_opened(event.option.id)

    def _section_opened(self, tab: str) -> None:
        section = _SECTION_BY_TAB.get(tab)
        note = self.query_one("#settings-note", Static)
        note.update(section.note if section is not None else _HAND_BUILT_NOTES.get(tab, ""))
        editor = self.query_one("#settings-editor")
        editor.display = section is not None
        if section is None:
            self._editing = ""
            self._show_help("")
            return
        fields = self.query_one(f"#{tab}", _FieldList)
        option = fields.highlighted_option
        self._load_editor(_SPECS[option.id] if option is not None and option.id else None)

    # -- the field lists --------------------------------------------------------

    def _visible(self, spec: Field) -> bool:
        if not spec.only_when:
            return True
        path, value = spec.only_when
        return self._draft.get(path) == value

    def _build_list(self, section: Section) -> None:
        """Fill a section's list from the draft, keeping the highlight."""
        fields = self.query_one(f"#{_tab_id(section.title)}", _FieldList)
        current = fields.highlighted_option
        keep = current.id if current is not None else None
        options: list[Option | None] = []
        visible = [f for f in section.fields if self._visible(f)]
        basic = [f for f in visible if not f.advanced]
        advanced = [f for f in visible if f.advanced]
        ascii_safe = self.app.config.ascii_safe  # type: ignore[attr-defined]

        def heading(title: str) -> None:
            # A rule under each heading (DESIGN.md section 4) is OptionList's
            # separator, a box-drawing line; ASCII-safe mode has the blank
            # row above and the heading alone.
            if options:
                options.append(_GAP())
            options.append(Option(Content.styled(title, "bold $accent"), disabled=True))
            if not ascii_safe:
                options.append(None)

        for spec in basic:
            if spec.rule_before:
                heading(spec.rule_before)
            options.append(Option(self._row_prompt(spec), id=spec.path))
        # Under Advanced, each field keeps the heading of the group it
        # belongs to ("Advanced: Winlink ..."), so Winlink's grid square is
        # not read as a BBS setting.
        shown = None
        for spec in advanced:
            if _GROUP_OF[spec.path] != shown:
                shown = _GROUP_OF[spec.path]
                heading(f"Advanced: {shown}" if shown else "Advanced")
            options.append(Option(self._row_prompt(spec), id=spec.path))
        fields.set_options(options)
        ids = [o.id for o in fields.options if o.id]
        if keep in ids:
            fields.highlighted = fields.get_option_index(keep)
        elif ids:
            fields.highlighted = fields.get_option_index(ids[0])

    def _row_prompt(self, spec: Field) -> Content:
        value = self._display(spec)
        label_style = "bold $error" if spec.path in self._errors else ""
        if len(value) > _VALUE_WIDTH:
            value = value[: _VALUE_WIDTH - 3] + "..."
        return Content.assemble(
            (f"{spec.label:<{_LABEL_WIDTH}} ", label_style),
            (value, "") if value else ("(not set)", "dim"),
        )

    def _display(self, spec: Field) -> str:
        """A field's draft value as its row shows it."""
        raw = self._draft.get(spec.path)
        if spec.kind == "bool":
            return "on" if raw else "off"
        if spec.kind in ("choice", "custom_choice"):
            label = next((label for label, value in spec.choices if value == raw), None)
            if label is not None:
                return str(label)
            return f"{raw} (custom)" if spec.kind == "custom_choice" and raw else str(raw or "")
        if spec.kind == "filtered_choice":
            text = str(raw or "")
            found = symbols.lookup(text[0], text[1:]) if len(text) >= 2 else None
            return found.display_label(ascii_safe=self.app.config.ascii_safe) if found else text  # type: ignore[attr-defined]
        if spec.kind == "secret":
            return "typed, saved on Save" if raw else self._secret_where.get(spec.path, "not set")
        if spec.kind == "contact" and raw and self._find_contact(str(raw)) is None:
            return f"{raw} (not in the Address Book)"
        # Content never reads markup; a control character from a
        # hand-edited config.toml would still move the cursor.
        return "".join(ch if ch.isprintable() else " " for ch in str(raw or ""))

    def _refresh_row(self, path: str) -> None:
        spec = _SPECS[path]
        fields = self.query_one(f"#{_tab_id(_SECTION_OF[path])}", _FieldList)
        try:
            fields.replace_option_prompt(path, self._row_prompt(spec))
        except OptionDoesNotExist:
            pass  # hidden by `only_when`; rebuilt when shown

    @on(OptionList.OptionHighlighted, ".settings-fields")
    def _row_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == self.current_section and event.option.id:
            self._load_editor(_SPECS[event.option.id])

    @on(OptionList.OptionSelected, ".settings-fields")
    def _row_chosen(self, event: OptionList.OptionSelected) -> None:
        """Enter on a row: flip an on/off setting, else go to the editor."""
        if not event.option.id:
            return
        spec = _SPECS[event.option.id]
        self._load_editor(spec)
        if spec.kind == "bool":
            self.set_field(spec.path, not self._draft.get(spec.path))
        elif spec.kind in ("choice", "custom_choice", "contact"):
            select = self.query_one("#settings-edit-select", Select)
            select.focus()
            select.expanded = True
        elif spec.kind == "filtered_choice":
            self.query_one("#settings-edit-symbol-select-filter", Input).focus()
        else:
            editor = self.query_one("#settings-edit-input", Input)
            editor.focus()
            editor.cursor_position = len(editor.value)

    def _back_to_list(self) -> None:
        if self.current_section in _SECTION_BY_TAB:
            self.query_one(f"#{self.current_section}", _FieldList).focus()

    @on(_Editor.Done)
    def _editor_done(self) -> None:
        self._back_to_list()

    @on(Input.Submitted, "#settings-edit-input, #settings-edit-custom")
    def _editor_submitted(self) -> None:
        self._back_to_list()

    # -- the editor -------------------------------------------------------------

    def _load_editor(self, spec: Field | None) -> None:
        """Show the controls `spec` is edited with, holding its draft value.

        Setting a control's value posts its Changed message; `prevent`
        stops those, and the handlers also ignore a message whose value is
        no longer the control's (a queued one from the field before)."""
        self._editing = spec.path if spec else ""
        self._show_help(self._editing)
        widgets = {
            "input": self.query_one("#settings-edit-input", Input),
            "select": self.query_one("#settings-edit-select", Select),
            "check": self.query_one("#settings-edit-check", Checkbox),
            "symbol": self.query_one("#settings-edit-symbol", SymbolPicker),
            "swatch": self.query_one("#settings-edit-swatch", Static),
            "scan": self.query_one("#aprs-gps-scan", Button),
        }
        extra = self.query_one("#settings-edit-extra")
        custom = self.query_one("#settings-edit-custom", Input)
        picker = self.query_one("#aprs-gps-device-picker", Select)
        self.query_one("#settings-edit-label", Label).update(spec.label if spec else "")
        if spec is None:
            for widget in widgets.values():
                widget.display = False
            extra.display = False
            return
        kind = spec.kind
        raw = self._draft.get(spec.path)
        shown = {
            "bool": {"check"},
            "choice": {"select"},
            "custom_choice": {"select"},
            "contact": {"select"},
            "filtered_choice": {"symbol"},
            "color": {"input", "swatch"},
        }.get(kind, {"input"})
        if spec.path == "aprs.gps_device":
            shown = {"input", "scan"}
        for name, widget in widgets.items():
            widget.display = name in shown
        extra.display = spec.path == "aprs.gps_device" or (
            kind == "custom_choice" and raw not in {v for _l, v in spec.choices})
        custom.display = kind == "custom_choice"
        picker.display = spec.path == "aprs.gps_device"
        with self.prevent(Input.Changed, Select.Changed, Checkbox.Changed):
            if kind == "bool":
                widgets["check"].value = bool(raw)
                widgets["check"].label = "on" if raw else "off"
            elif kind == "contact":
                select = widgets["select"]
                options = self._contact_options(spec, str(raw or ""))
                select.set_options(options)
                select.value = str(raw or "")
            elif kind in ("choice", "custom_choice"):
                options = [(str(label), value) for label, value in spec.choices]
                if kind == "custom_choice":
                    options.append((_CUSTOM_LABEL, _CUSTOM_SENTINEL))
                select = widgets["select"]
                select.set_options(options)
                values = {v for _l, v in spec.choices}
                if raw in values:
                    select.value = raw
                elif kind == "custom_choice":
                    select.value = _CUSTOM_SENTINEL
                    custom.value = str(raw or "")
                    custom.placeholder = spec.placeholder
                else:
                    select.value = options[0][1]
            elif kind == "filtered_choice":
                widgets["symbol"].set_value(str(raw or ""))
            else:
                editor = widgets["input"]
                editor.password = kind == "secret"
                editor.placeholder = (
                    self._secret_where.get(spec.path, "not set") if kind == "secret"
                    else spec.placeholder or ("#1A1B26" if kind == "color" else "")
                )
                editor.value = str(raw or "")
                editor.cursor_position = len(editor.value)
                if kind == "color":
                    self._update_swatch(editor.value)

    def _find_contact(self, target: str):
        book = getattr(self.app, "addressbook", None)
        return book.find(target) if book is not None and target else None

    def _contact_options(self, spec: Field, current: str) -> list[tuple[str, str]]:
        """"(none)", then the Address Book contacts of the kind `spec`
        wants, and the current value even when it is gone from the book
        (a list without it would clear it on Save)."""
        book = getattr(self.app, "addressbook", None)
        internet = spec.contacts == "internet"
        targets = [e.target for e in (book.entries if book is not None else ())
                   if e.is_internet == internet]
        options = [("(none)", "")] + [(t, t) for t in targets]
        if current and current not in targets:
            options.append((f"{current} (not in the Address Book)", current))
        return options

    def _editing_spec(self) -> Field | None:
        return _SPECS.get(self._editing)

    @on(Input.Changed, "#settings-edit-input")
    def _input_changed(self, event: Input.Changed) -> None:
        spec = self._editing_spec()
        if spec is None or event.value != event.input.value:
            return
        if spec.kind == "color":
            self._update_swatch(event.value)
        self.set_field(spec.path, event.value, from_editor=True)

    @on(Input.Changed, "#settings-edit-custom")
    def _custom_changed(self, event: Input.Changed) -> None:
        spec = self._editing_spec()
        if spec is None or spec.kind != "custom_choice" or event.value != event.input.value:
            return
        self.set_field(spec.path, event.value, from_editor=True)

    @on(Select.Changed, "#settings-edit-select")
    def _select_changed(self, event: Select.Changed) -> None:
        spec = self._editing_spec()
        if (spec is None or spec.kind not in ("choice", "custom_choice", "contact")
                or event.value != event.select.value):
            return
        if spec.kind == "custom_choice":
            custom = self.query_one("#settings-edit-custom", Input)
            is_custom = event.value == _CUSTOM_SENTINEL
            self.query_one("#settings-edit-extra").display = is_custom
            if is_custom:
                custom.placeholder = spec.placeholder
                self.set_field(spec.path, custom.value, from_editor=True)
                return
        self.set_field(spec.path, event.value, from_editor=True)

    @on(Checkbox.Changed, "#settings-edit-check")
    def _check_changed(self, event: Checkbox.Changed) -> None:
        event.checkbox.label = "on" if event.value else "off"
        spec = self._editing_spec()
        if spec is None or spec.kind != "bool" or event.value != event.checkbox.value:
            return
        self.set_field(spec.path, event.value, from_editor=True)

    @on(Select.Changed, "#settings-edit-symbol-select")
    def _symbol_changed(self, event: Select.Changed) -> None:
        spec = self._editing_spec()
        if (spec is None or spec.kind != "filtered_choice" or not isinstance(event.value, str)
                or event.value != event.select.value):
            return
        self.set_field(spec.path, event.value, from_editor=True)

    def _update_swatch(self, text: str) -> None:
        """Fill the swatch beside a colour field with the colour it names.

        A value still being typed ("#1A1B") is not an error, just not a
        colour yet: the swatch gets the neutral `-invalid` border and no
        fill. Save is what refuses a bad value."""
        from ..config import HEX_COLOR_RE

        swatch = self.query_one("#settings-edit-swatch", Static)
        text = text.strip()
        if HEX_COLOR_RE.match(text):
            swatch.remove_class("-invalid")
            swatch.styles.background = text
        else:
            swatch.add_class("-invalid")
            swatch.styles.background = None

    @on(Button.Pressed, "#aprs-gps-scan")
    @work
    async def _scan_gps_devices(self) -> None:
        picker = self.query_one("#aprs-gps-device-picker", Select)
        picker.set_options([("Scanning local serial ports...", Select.BLANK)])
        devices = await discover_serial_gps()
        options = [(f"{item.label} -- {item.detail}", item.label) for item in devices]
        picker.set_options(options or [("No local serial ports found", Select.BLANK)])
        if options:
            picker.value = options[0][1]

    @on(Select.Changed, "#aprs-gps-device-picker")
    def _choose_gps_device(self, event: Select.Changed) -> None:
        if event.value not in (Select.BLANK, Select.NULL) and self._editing == "aprs.gps_device":
            self.query_one("#settings-edit-input", Input).value = str(event.value)

    # -- the draft ----------------------------------------------------------------

    def field_value(self, path: str) -> object:
        """What Settings holds for `path`, saved or not."""
        return self._draft.get(path)

    def set_field(self, path: str, raw: object, *, from_editor: bool = False) -> None:
        """Change a field's draft, as typing or choosing in the editor does.

        Its row shows the new value, an error Save found in it is cleared,
        a position entered one way is converted to the other, and the
        fields that depend on it (`Field.only_when`) are shown or hidden."""
        spec = _SPECS[path]
        if self._draft.get(path) == raw and path not in self._errors:
            return
        self._draft[path] = raw
        self._errors.pop(path, None)
        self._refresh_row(path)
        for other in self._sync_position(path):
            self._refresh_row(other)
            if other == self._editing:
                self._load_editor(spec if other == path else _SPECS[other])
        if path in _CONTROLS:
            for section in SETTINGS_SCHEMA:
                if any(f.only_when and f.only_when[0] == path for f in section.fields):
                    self._build_list(section)
        if path == self._editing:
            if not from_editor:
                self._load_editor(spec)
            self._show_help(path)

    def _sync_position(self, path: str) -> list[str]:
        """A grid square typed in gives the latitude and longitude of its
        centre; a latitude or longitude gives the six-character square.
        Only on an edit: loading copies what config.toml has, which is
        already consistent, and recomputing then would replace an exact
        position with its square's centre. Returns what changed."""
        if path == "aprs.grid_square":
            try:
                lat, lon = from_grid(str(self._draft.get(path, "")).strip())
            except LocatorError:
                return []
            self._draft["aprs.latitude"] = f"{lat:.6f}"
            self._draft["aprs.longitude"] = f"{lon:.6f}"
            return ["aprs.latitude", "aprs.longitude"]
        if path in ("aprs.latitude", "aprs.longitude"):
            try:
                grid = to_grid(float(str(self._draft.get("aprs.latitude"))),
                               float(str(self._draft.get("aprs.longitude"))), 6)
            except (ValueError, LocatorError):
                return []
            self._draft["aprs.grid_square"] = grid
            return ["aprs.grid_square"]
        return []

    def open_field(self, path: str, *, focus: bool = True) -> None:
        """Show a field: its section, its row highlighted, the list focused."""
        self.show_section(_SECTION_OF[path])
        fields = self.query_one(f"#{_tab_id(_SECTION_OF[path])}", _FieldList)
        try:
            fields.highlighted = fields.get_option_index(path)
        except OptionDoesNotExist:
            return
        self._load_editor(_SPECS[path])
        if focus:
            fields.focus()

    def row_text(self, path: str) -> str:
        """A field's row as shown, for tests and the help line."""
        return self._row_prompt(_SPECS[path]).plain

    # -- the help line ----------------------------------------------------------

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        """Radio and Logins' rows say what they are when focused; a field
        list's help follows its highlighted row instead."""
        if self.current_section in _SECTION_BY_TAB:
            return
        node = event.control
        while node is not None and node is not self:
            if node.id in self._row_help:
                self._show_help(node.id)
                return
            node = node.parent
        self._show_help("")

    def _show_help(self, key: str) -> None:
        line = self.query_one("#settings-help-line", Static)
        if key in _SPECS:
            spec = _SPECS[key]
            label, text, apply = spec.label, spec.help, spec.apply
        elif key in self._row_help:
            label, text, apply = self._row_help[key]
        else:
            line.update(_HELP_IDLE)
            line.remove_class("-error")
            return
        error = self._errors.get(key, "")
        if error:
            line.update(f"{label}: {error}")
        else:
            line.update(f"{label}: {text} {APPLY_NOTE.get(apply, '')}".rstrip())
        line.set_class(bool(error), "-error")

    def _register_row(self, row_id: str, label: str, text: str, apply: str, *wids: str) -> str:
        self._row_help[row_id] = (label, text, apply)
        return row_id

    def error_for(self, path: str) -> str:
        """The validation error Save found in this field, or ""."""
        return self._errors.get(path, "")

    # -- Radio and Logins ---------------------------------------------------

    def _compose_transports(self) -> ComposeResult:
        """The one hand-built tab -- see the module docstring for why
        transports cannot be schema fields (a list of dicts with
        kind-specific keys, not scalars)."""
        row = self._register_row(
            "set-active-transport-row", "Radio in use",
            "Which one kissterm uses. Changing it reopens the connection, so "
            "disconnect first.", "live", "set-active-transport",
        )
        with Horizontal(classes="settings-row", id=row):
            yield Label("Radio in use", classes="settings-label")
            yield Select([], id="set-active-transport", allow_blank=True, compact=True)
        with Horizontal(classes="settings-row settings-buttons"):
            yield Button("Scan for hardware", compact=True, id="settings-scan")
            yield Button("New", compact=True, id="transport-new")
            yield Button("Edit", compact=True, id="transport-edit")
            yield Button("Test", compact=True, id="settings-test")
            yield Button("Forget", compact=True, id="settings-forget")
        yield Static("", id="settings-transport-detail", classes="settings-detail")

    def _compose_credentials(self) -> ComposeResult:
        """Saved logins, referenced by name from a station's Connect entry.

        A list of `{"name", "text"}` dicts for the same reason `transports`
        is a list of dicts and not schema fields: `Config.credentials` has
        no fixed shape a scalar form field could bind to, and Add/Edit here
        open `CredentialScreen` rather than being generated.
        """
        row = self._register_row(
            "set-credential-row", "Login", "A saved login: the lines sent after "
            "connecting, often a callsign and a password.", "live", "set-credential",
        )
        with Horizontal(classes="settings-row", id=row):
            yield Label("Login", classes="settings-label")
            yield Select([], id="set-credential", allow_blank=True, compact=True)
        with Horizontal(classes="settings-row settings-buttons"):
            yield Button("New", compact=True, id="credential-new")
            yield Button("Edit", compact=True, id="credential-edit")
            yield Button("Forget", compact=True, id="credential-forget")
        yield Static("", id="settings-credential-detail", classes="settings-detail")

    def _compose_scripts(self) -> ComposeResult:
        """Saved command sequences, referenced by name from a station's
        Connect entry -- same shape and mechanism as Credentials
        (`{"name", "text"}`, live lookup by name), kept as a separate list
        on purpose: a credential is a login, named for the account it
        belongs to; a script is any sequence of commands sent after
        connecting, named for what it does -- "Check WS1EC mail", not an
        account name. See `Config.scripts`'s docstring.
        """
        row = self._register_row(
            "set-script-row", "Script", "Commands sent one line at a time after "
            "connecting, after any login: a node hop, a mailbox check.", "live",
            "set-script",
        )
        with Horizontal(classes="settings-row", id=row):
            yield Label("Script", classes="settings-label")
            yield Select([], id="set-script", allow_blank=True, compact=True)
        with Horizontal(classes="settings-row settings-buttons"):
            yield Button("New", compact=True, id="script-new")
            yield Button("Edit", compact=True, id="script-edit")
            yield Button("Forget", compact=True, id="script-forget")
        yield Static("", id="settings-script-detail", classes="settings-detail")

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def render_settings(self, config) -> None:
        """Fill the draft and every list from `config`. Safe to call
        repeatedly; anything typed and not saved is replaced."""
        self._errors.clear()
        for section in SETTINGS_SCHEMA:
            for spec in section.fields:
                try:
                    value = get_value(config, spec.path)
                except AttributeError:
                    # A schema entry naming a field the config does not have is
                    # a bug, but not one worth taking the pane down for.
                    log.warning("settings schema references unknown %s", spec.path)
                    continue
                self._draft[spec.path] = self._initial(spec, value, config)
        for section in SETTINGS_SCHEMA:
            self._build_list(section)

        self._render_transports(config)
        self._render_credentials(config)
        self._render_scripts(config)
        self._render_banner(config)
        self._section_opened(self.current_section)

    def _initial(self, spec: Field, value, config) -> object:
        """A stored value as the draft holds it."""
        if spec.kind == "bool":
            return bool(value)
        if spec.kind == "choice":
            # A stale or hand-edited config.toml can hold a value that is
            # not offered (`theme = "not-a-real-theme"`): show the first
            # choice rather than one the list cannot select.
            valid = {v for _label, v in spec.choices}
            return value if value in valid else (spec.choices[0][1] if spec.choices else value)
        if spec.kind in ("custom_choice", "filtered_choice"):
            # "Disable, never clear": a value matching no preset is kept
            # and shown as custom, so it survives a Save.
            return "" if value is None else str(value)
        if spec.kind == "secret":
            # Never the value: only whether one is saved, and where.
            self._secret_where[spec.path] = {
                "keyring": "saved in the system keyring",
                "config": "saved in config.toml",
            }.get(credential_store(config, str(value or "")), "not set")
            return ""
        return format_value(spec, value)

    def _render_transports(self, config) -> None:
        select = self.query_one("#set-active-transport", Select)
        options = [
            (f"{t.get('name', '?')}  ({t.get('kind', '?')})", t.get("name", ""))
            for t in config.transports
        ]
        select.set_options(options)
        if config.active_transport and any(
            v == config.active_transport for _, v in options
        ):
            select.value = config.active_transport
        self._render_transport_detail(config)

    def _render_transport_detail(self, config) -> None:
        name = self.query_one("#set-active-transport", Select).value
        entry = next(
            (t for t in config.transports if t.get("name") == name), None
        )
        detail = self.query_one("#settings-transport-detail", Static)
        if entry is None:
            detail.update(
                "No transport configured. 'Scan for hardware' looks for serial "
                "TNCs, KISS and AGWPE services on your network, and paired "
                "Bluetooth TNCs. Nothing it does transmits. Plugging in a USB "
                "TNC is noticed without scanning."
            )
            return
        keys = ", ".join(
            f"{k} = {v}" for k, v in sorted(entry.items()) if k not in ("name",)
        )
        detail.update(keys or "(no settings)")

    def _render_credentials(self, config) -> None:
        select = self.query_one("#set-credential", Select)
        names = [c.get("name", "") for c in config.credentials if c.get("name")]
        select.set_options((name, name) for name in names)
        if select.value not in names:
            select.value = Select.NULL
        self._render_credential_detail(config)

    def _render_credential_detail(self, config) -> None:
        name = self.query_one("#set-credential", Select).value
        entry = next((c for c in config.credentials if c.get("name") == name), None)
        detail = self.query_one("#settings-credential-detail", Static)
        if entry is None:
            detail.update(
                "No credentials saved yet. 'New' adds one; a station's "
                "Connect entry can then pick it from a dropdown instead of "
                "storing its own copy of the text."
            )
            return
        text = find_credential(config, str(name))
        lines = text.count("\n") + 1 if text else 0
        where = ("in the system keyring" if credential_store(config, str(name)) == "keyring"
                 else "in config.toml (no system keyring here)")
        if not text and credential_store(config, str(name)) == "keyring":
            detail.update("Kept in the system keyring, which did not answer: unlock it, or Edit to save it again.")
            return
        detail.update(f"{lines} line(s) saved, {where}." if lines else "(empty)")

    def _render_scripts(self, config) -> None:
        select = self.query_one("#set-script", Select)
        names = [s.get("name", "") for s in config.scripts if s.get("name")]
        select.set_options((name, name) for name in names)
        if select.value not in names:
            select.value = Select.NULL
        self._render_script_detail(config)

    def _render_script_detail(self, config) -> None:
        name = self.query_one("#set-script", Select).value
        entry = next((s for s in config.scripts if s.get("name") == name), None)
        detail = self.query_one("#settings-script-detail", Static)
        if entry is None:
            detail.update(
                "No scripts saved yet. 'New' adds one; a station's Connect "
                "entry can then pick it from a dropdown instead of storing "
                "its own copy of the text."
            )
            return
        lines = str(entry.get("text", "")).count("\n") + 1 if entry.get("text") else 0
        detail.update(f"{lines} line(s) saved." if lines else "(empty)")

    def _render_banner(self, config) -> None:
        warnings = list(getattr(config, "warnings", ()) or ())
        banner = self.query_one("#settings-banner", Static)
        if warnings:
            banner.update(
                "Problems were found in config.toml and defaults were used "
                "instead:\n  - " + "\n  - ".join(warnings)
            )
            banner.display = True
        else:
            banner.display = False

    def _set_error(self, path: str, message: str) -> None:
        """Record or clear a field's error; its row's label turns red."""
        if message:
            self._errors[path] = message
        else:
            self._errors.pop(path, None)
        self._refresh_row(path)

    # ------------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------------
    @on(Button.Pressed, "#settings-save")
    def _save(self) -> None:
        config = self.app.config  # type: ignore[attr-defined]
        previous_active = config.active_transport
        pending: dict[str, object] = {}
        failed = False
        #: Passwords typed into "secret" fields: (field path, text).
        secrets: list[tuple[str, str]] = []
        #: Fields that failed, in schema order: the first is opened.
        failures: list[Field] = []

        for section in SETTINGS_SCHEMA:
            for spec in section.fields:
                if spec.path not in self._draft:
                    continue
                raw = self._draft[spec.path]
                if spec.kind == "secret":
                    if raw:
                        secrets.append((spec.path, str(raw)))
                    continue
                try:
                    pending[spec.path] = coerce(spec, raw)
                    self._set_error(spec.path, "")
                except ValidationError as exc:
                    self._set_error(spec.path, str(exc))
                    failed = True
                    failures.append(spec)

        # These two values have a relationship no one Field can express. Do
        # it before mutating Config so an invalid pair gets the same all-or-
        # nothing save behavior as every individual field.
        slow_speed = pending.get("aprs.smart_slow_speed_knots")
        fast_speed = pending.get("aprs.smart_fast_speed_knots")
        if (
            isinstance(slow_speed, int)
            and isinstance(fast_speed, int)
            and slow_speed >= fast_speed
        ):
            message = "Must be below Smart fast speed."
            for path in ("aprs.smart_slow_speed_knots", "aprs.smart_fast_speed_knots"):
                self._set_error(path, message)
                failures.append(_SPECS[path])
            failed = True

        if failed:
            # Nothing is written. A partial save leaves the operator unable to
            # tell which values took -- worse than refusing outright. A bad
            # field is not necessarily in the open section, so open the first
            # one and put the cursor on it: its error is then in the help line.
            self.open_field(failures[0].path)
            self._show_help(failures[0].path)
            names = ", ".join(dict.fromkeys(f"{spec.label} ({_SECTION_OF[spec.path]})" for spec in failures))
            self.query_one("#settings-footer", Static).update(f"Not saved -- fix: {names}")
            self.app.notify("Settings not saved: some values are invalid.", severity="error")
            return

        for path, value in pending.items():
            set_value(config, path, value)
        names = dict(SECRET_LOGINS)
        for path, text in secrets:
            set_credential(config, names[path], text)
            set_value(config, path, names[path])

        selected = self.query_one("#set-active-transport", Select).value
        if selected and selected != Select.NULL:
            config.active_transport = str(selected)

        notes = cross_check(config)
        saved = self.app._save_config()  # type: ignore[attr-defined]
        for path, _text in secrets:
            # Out of the draft once saved; the row says where it went.
            self._secret_where[path] = {"keyring": "saved in the system keyring"}.get(
                credential_store(config, names[path]), "saved in config.toml")
            self._draft[path] = ""
            self._refresh_row(path)
            if path == self._editing:
                self._load_editor(_SPECS[path])
        self._apply_live(config)
        # ASCII-safe mode decides how headings are ruled.
        for section in SETTINGS_SCHEMA:
            self._build_list(section)


        # The toast and the footer say different amounts on purpose. The
        # toast disappears in a few seconds, so a long paragraph of
        # cross-check notes there is unreadable before it goes -- it showed
        # up looking like noise. The footer does not disappear, so the detail
        # belongs there instead.
        message = "Settings saved." if saved else "Applied for this session (could not write config)."
        detail = message
        if notes:
            detail += " " + " ".join(notes)
        self.query_one("#settings-footer", Static).update(detail)
        # The footer above already says "Settings saved"; a toast is only
        # for the case the operator must act on.
        if not saved:
            self.app.notify(message, severity="warning")

        # Nothing open at all (the modem was not answering at launch): Save is
        # the retry, even with Active unchanged -- the operator has just
        # started the modem software or fixed its address and wants it used.
        nothing_open = (
            getattr(self.app, "station", None) is None
            and getattr(self.app, "session_transport", None) is None
        )
        if config.active_transport and (
            config.active_transport != previous_active or nothing_open
        ):
            # Picking a different entry from Active used to change this one
            # string and nothing else -- the station kept talking to the OLD
            # transport object, so the status bar kept showing the old TNC no
            # matter how many times this ran. See `_reopen_transport`.
            self._reopen_transport(config)

    def _apply_live(self, config) -> None:
        """Push the settings that can change under a running app.

        Link parameters are deliberately excluded from any *established* link:
        paclen, window and the timers were agreed when it came up, and changing
        them underneath a running conversation corrupts it. New links pick them
        up, which is what `Field.apply == "connect"` promises.
        """
        app = self.app
        if hasattr(app, "apply_theme"):
            # Independent of whether a station/transport is configured at
            # all -- a theme change must not be silently skipped just because
            # nothing is connected yet.
            app.apply_theme()  # type: ignore[attr-defined]

        if hasattr(app, "apply_runtime_settings"):
            # One generic hook rather than a growing list of feature-specific
            # calls here. Anything the app has to reconfigure after a save --
            # the beacon, remote colour -- belongs behind it, so adding a
            # setting stays "one entry in the schema" and this pane keeps
            # knowing nothing about what the settings mean.
            app.apply_runtime_settings()  # type: ignore[attr-defined]

        station = getattr(app, "station", None)
        if station is None:
            return
        from ..ax25.address import AX25Address

        try:
            station.mycall = AX25Address.parse(config.mycall)
            station.aliases = tuple(
                AX25Address.parse(a) for a in config.mycall_aliases
            )
        except Exception:
            log.exception("could not apply callsign settings")

        params = station.params
        params.paclen = config.paclen
        params.window = config.window
        params.modulo = config.modulo
        params.retries = config.retries
        params.t1 = config.t1
        params.t2 = config.t2
        params.t3 = config.t3

        monitor_filter = getattr(app, "monitor_filter", None)
        if monitor_filter is not None:
            monitor_filter.contains = config.monitor_filter

    @on(Button.Pressed, "#settings-reload")
    def _reload(self) -> None:
        from ..config import load_config

        try:
            fresh = load_config(profile=self.app.config.profile_name)  # type: ignore[attr-defined]
        except Exception:
            log.exception("could not reload config")
            self.app.notify("Could not read the selected configuration.", severity="error")
            return
        self.app.config = fresh  # type: ignore[attr-defined]
        if hasattr(self.app, "apply_theme"):
            self.app.apply_theme()  # type: ignore[attr-defined]
        self.render_settings(fresh)
        self.query_one("#settings-footer", Static).update("Reloaded selected configuration.")

    @on(Select.Changed, "#set-active-transport")
    def _transport_changed(self) -> None:
        self._render_transport_detail(self.app.config)  # type: ignore[attr-defined]

    @work
    async def _new_transport(self) -> None:
        config = self.app.config  # type: ignore[attr-defined]
        await self._edit_transport_entry(None, config)

    @on(Button.Pressed, "#transport-new")
    def _new_transport_pressed(self) -> None:
        self._new_transport()

    @work
    async def _edit_transport(self) -> None:
        config = self.app.config  # type: ignore[attr-defined]
        name = self.query_one("#set-active-transport", Select).value
        entry = next((t for t in config.transports if t.get("name") == name), None)
        if entry is None:
            self.app.notify("Select a transport first.", severity="warning")  # type: ignore[attr-defined]
            return
        await self._edit_transport_entry(entry, config)

    @on(Button.Pressed, "#transport-edit")
    def _edit_transport_pressed(self) -> None:
        self._edit_transport()

    async def _edit_transport_entry(self, entry: dict | None, config) -> None:
        """Shared by New and Edit: push the form, then -- per
        `AGENTS.md`'s "one way to build a transport" rule -- prove the
        result actually constructs before saving it. A config entry that
        looks right and fails at `open()` is worse than catching it here,
        while the operator is still looking at the form that produced it.
        """
        from .dialogs import TransportEntryScreen

        existing_names = tuple(
            t.get("name", "") for t in config.transports if t.get("name")
        )
        result = await self.app.push_screen_wait(  # type: ignore[attr-defined]
            TransportEntryScreen(
                entry, config.credentials, config.scripts, existing_names
            )
        )
        if result is None:
            return

        from .. import transport as transport_mod

        try:
            transport_mod.build_transport(result)
        except Exception as exc:
            self.app.notify(f"Could not save {result['name']!r}: {exc}", severity="error")  # type: ignore[attr-defined]
            return

        old_name = entry.get("name", "") if entry else ""
        config.transports = [
            t for t in config.transports if t.get("name") not in (old_name, result["name"])
        ]
        config.transports.append(result)
        if config.active_transport == old_name or not config.active_transport:
            config.active_transport = result["name"]
        self.app._save_config()  # type: ignore[attr-defined]
        self._render_transports(config)
        self.query_one("#set-active-transport", Select).value = result["name"]
        self._render_transport_detail(config)
        # A first-run app has no station yet, so the normal "reopen" path
        # cannot swap a transport underneath one.  Open this newly saved
        # entry now; otherwise every APRS and beacon action correctly but
        # bafflingly reports "no transport" until the operator restarts.
        if getattr(self.app, "station", None) is None and getattr(self.app, "session_transport", None) is None:
            await self.app._open_initial_transport(result["name"])  # type: ignore[attr-defined]

    @on(Button.Pressed, "#settings-forget")
    def _forget(self) -> None:
        config = self.app.config  # type: ignore[attr-defined]
        name = self.query_one("#set-active-transport", Select).value
        if not name or name == Select.NULL:
            return
        config.transports = [t for t in config.transports if t.get("name") != name]
        if config.active_transport == name:
            config.active_transport = (
                config.transports[0].get("name", "") if config.transports else ""
            )
        self.app._save_config()  # type: ignore[attr-defined]
        self._render_transports(config)

    @on(Select.Changed, "#set-credential")
    def _credential_changed(self) -> None:
        self._render_credential_detail(self.app.config)  # type: ignore[attr-defined]

    @work
    async def _new_credential(self) -> None:
        from .dialogs import CredentialScreen

        result = await self.app.push_screen_wait(CredentialScreen())
        if result is None:
            return
        config = self.app.config  # type: ignore[attr-defined]
        set_credential(config, result.name, result.text)
        self.app._save_config()  # type: ignore[attr-defined]
        self._render_credentials(config)
        self.query_one("#set-credential", Select).value = result.name
        self._render_credential_detail(config)

    @on(Button.Pressed, "#credential-new")
    def _new_credential_pressed(self) -> None:
        self._new_credential()

    @work
    async def _edit_credential(self) -> None:
        from .dialogs import CredentialScreen

        config = self.app.config  # type: ignore[attr-defined]
        name = self.query_one("#set-credential", Select).value
        entry = next((c for c in config.credentials if c.get("name") == name), None)
        if entry is None:
            self.app.notify("Select a credential first.", severity="warning")  # type: ignore[attr-defined]
            return
        result = await self.app.push_screen_wait(
            CredentialScreen(entry.get("name", ""), find_credential(config, entry.get("name", "")))
        )
        if result is None:
            return
        # Drop both the old name and the new one (a rename could collide
        # with an existing entry) before re-adding, so a rename replaces
        # the old entry in place rather than leaving a stale duplicate a
        # station could still resolve to.
        set_credential(config, result.name, result.text, old_name=str(name))
        self.app._save_config()  # type: ignore[attr-defined]
        self._render_credentials(config)
        self.query_one("#set-credential", Select).value = result.name
        self._render_credential_detail(config)

    @on(Button.Pressed, "#credential-edit")
    def _edit_credential_pressed(self) -> None:
        self._edit_credential()

    @on(Button.Pressed, "#credential-forget")
    def _forget_credential(self) -> None:
        config = self.app.config  # type: ignore[attr-defined]
        name = self.query_one("#set-credential", Select).value
        if not name or name == Select.NULL:
            return
        forget_credential(config, str(name))
        self.app._save_config()  # type: ignore[attr-defined]
        self._render_credentials(config)

    @on(Select.Changed, "#set-script")
    def _script_changed(self) -> None:
        self._render_script_detail(self.app.config)  # type: ignore[attr-defined]

    @work
    async def _new_script(self) -> None:
        from .dialogs import CredentialScreen

        result = await self.app.push_screen_wait(CredentialScreen(kind="script"))
        if result is None:
            return
        config = self.app.config  # type: ignore[attr-defined]
        config.scripts = [s for s in config.scripts if s.get("name") != result.name]
        config.scripts.append({"name": result.name, "text": result.text})
        self.app._save_config()  # type: ignore[attr-defined]
        self._render_scripts(config)
        self.query_one("#set-script", Select).value = result.name
        self._render_script_detail(config)

    @on(Button.Pressed, "#script-new")
    def _new_script_pressed(self) -> None:
        self._new_script()

    @work
    async def _edit_script(self) -> None:
        from .dialogs import CredentialScreen

        config = self.app.config  # type: ignore[attr-defined]
        name = self.query_one("#set-script", Select).value
        entry = next((s for s in config.scripts if s.get("name") == name), None)
        if entry is None:
            self.app.notify("Select a script first.", severity="warning")  # type: ignore[attr-defined]
            return
        result = await self.app.push_screen_wait(
            CredentialScreen(entry.get("name", ""), entry.get("text", ""), kind="script")
        )
        if result is None:
            return
        # Same rename handling as `_edit_credential`: drop both the old and
        # new name before re-adding, so a rename replaces the entry in
        # place rather than leaving a stale duplicate a station could
        # still resolve to.
        config.scripts = [
            s for s in config.scripts if s.get("name") not in (name, result.name)
        ]
        config.scripts.append({"name": result.name, "text": result.text})
        self.app._save_config()  # type: ignore[attr-defined]
        self._render_scripts(config)
        self.query_one("#set-script", Select).value = result.name
        self._render_script_detail(config)

    @on(Button.Pressed, "#script-edit")
    def _edit_script_pressed(self) -> None:
        self._edit_script()

    @on(Button.Pressed, "#script-forget")
    def _forget_script(self) -> None:
        config = self.app.config  # type: ignore[attr-defined]
        name = self.query_one("#set-script", Select).value
        if not name or name == Select.NULL:
            return
        config.scripts = [s for s in config.scripts if s.get("name") != name]
        self.app._save_config()  # type: ignore[attr-defined]
        self._render_scripts(config)

    @work
    async def _scan(self) -> None:
        config = self.app.config  # type: ignore[attr-defined]
        detail = self.query_one("#settings-transport-detail", Static)
        detail.update("Scanning serial ports, the local network, and paired Bluetooth...")
        try:
            from .. import discovery

            # Coverage, because "nothing found" and "gave up before looking"
            # are different answers and the scan used to give the first when
            # it meant the second -- it reached 43 of 254 addresses and said
            # nothing, so a TNC at .128 was invisible.
            coverage = discovery.ScanCoverage()
            found = await discovery.discover_all(coverage=coverage)
        except Exception:
            log.exception("discovery failed")
            detail.update("Scan failed. 'kissterm --doctor' may say why.")
            return

        reach = coverage.summary if coverage.hosts_planned else ""
        if not found:
            detail.update(
                "Nothing found. That is not proof there is no TNC -- a silent "
                "KISS TNC looks like a wrong serial port until a frame "
                f"arrives.{chr(10) + reach if reach else ''}"
            )
            return

        added = 0
        for dev in found:
            entry = dict(dev.config)
            entry.setdefault("name", dev.label)
            if any(t.get("name") == entry["name"] for t in config.transports):
                continue
            config.transports.append(entry)
            added += 1
        if added and not config.active_transport:
            config.active_transport = config.transports[0].get("name", "")
        self.app._save_config()  # type: ignore[attr-defined]
        self._render_transports(config)
        summary = f"Found {len(found)}; added {added} new."
        if coverage.truncated:
            summary = f"{summary}  {coverage.summary}"
        detail.update(summary)
        self.app.notify(f"Discovery added {added} transport(s).")

    @on(Button.Pressed, "#settings-scan")
    def _scan_pressed(self) -> None:
        self._scan()

    @work
    async def _test_transport(self) -> None:
        """Ask the selected transport whether anything real is on the far end.

        Deliberately NOT a connect attempt to another station: this answers
        "is my TNC there and is it what the config says it is", which is the
        question that has to be answered first and the one an operator
        otherwise answers by trying to connect to a node and misreading the
        silence as a dead path. Nothing here transmits -- see
        `discovery.identify_tcp` for exactly what goes out on the socket.
        """
        config = self.app.config  # type: ignore[attr-defined]
        detail = self.query_one("#settings-transport-detail", Static)
        name = self.query_one("#set-active-transport", Select).value
        entry = next((t for t in config.transports if t.get("name") == name), None)
        if entry is None:
            detail.update("Select a transport first.")
            return

        kind = entry.get("kind", "")
        if kind in ("serial", "bluetooth", "ble", "kernel"):
            # A serial probe opens the port exclusively, so running one while
            # the app holds it open would report a failure it caused itself.
            detail.update(
                f"Testing {kind} transports from here is not wired up yet -- "
                "'kissterm --doctor' checks the device, permissions and "
                "dependencies for those."
            )
            return

        host, port = entry.get("host", ""), entry.get("port", 0)
        if not host or not port:
            detail.update(f"{name} has no host and port to test.")
            return

        detail.update(f"Testing {host}:{port}...")
        try:
            from .. import discovery

            identity = await discovery.identify_tcp(host, int(port), kind=kind)
        except Exception:
            log.exception("transport test failed")
            detail.update("The test itself failed. 'kissterm --doctor' may say why.")
            return

        line = _test_result_line(host, port, identity)
        detail.update(line)
        severity = (
            "information" if identity.is_tnc
            else "error" if identity.verdict in ("not-a-tnc", "unreachable")
            else "warning"
        )
        # The result is already in the detail line; toast only a problem.
        if not identity.is_tnc:
            self.app.notify(line, severity=severity)

    @on(Button.Pressed, "#settings-test")
    def _test_pressed(self) -> None:
        self._test_transport()

    @work
    async def _reopen_transport(self, config) -> None:
        """Actually open the newly-selected transport.

        Without this, choosing a different entry from Active and hitting Save
        changed `Config.active_transport` and nothing else -- the live
        station kept its old `FrameTransport` object, so the status bar kept
        reporting the old TNC no matter how many times the operator saved.
        Delegates to `KissTermApp._switch_frame_transport`, shared with the
        Connect dialog's own transport picker in `action_connect` -- one
        implementation of "actually open the newly-selected transport".
        """
        await self.app._switch_frame_transport(config.active_transport)  # type: ignore[attr-defined]
