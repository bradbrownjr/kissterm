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
"""

from __future__ import annotations

import logging

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Input,
    Label,
    Select,
    Static,
    Switch,
    TabbedContent,
    TabPane,
)

from ..aprs import symbols
from ..locator import LocatorError, from_grid, to_grid
from .settings_schema import (
    SETTINGS_SCHEMA,
    Field,
    ValidationError,
    coerce,
    cross_check,
    format_value,
    get_value,
    set_value,
)

log = logging.getLogger(__name__)

#: Sentinel `Select` value meaning "use the text field below instead of any
#: preset" -- not a real config value, never written to `Config`. Only one
#: `"custom_choice"` field exists today (`aprs.path`), so this is not
#: namespaced per-field; generalize it if a second one is ever added.
_CUSTOM_SENTINEL = "__custom__"
_CUSTOM_LABEL = "Custom..."

#: The Transports block is emitted immediately after this schema section.
#: "Station" puts callsign and aliases at the very top of the page, with the
#: hardware they talk through right below -- identity first, then the radio,
#: then tuning.
TRANSPORTS_AFTER_SECTION = "Station"

APPLY_NOTE = {
    "live": "takes effect now",
    "connect": "next connection",
    "restart": "needs a restart",
}


def _widget_id(path: str) -> str:
    """A DOM-safe id from a dotted schema path (`aprs.latitude`)."""
    return "set-" + path.replace(".", "-")


def _tab_id(title: str) -> str:
    """A DOM-safe id for a section's `TabPane` (`"Link"` -> `settings-tab-link`)."""
    return "settings-tab-" + title.lower().replace(" ", "-")


#: What "Test selected" prints for each `discovery.Identity.verdict`. An
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
    "unknown": "UNKNOWN",
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
        reason = "open, identity unconfirmed (silent)"
    return f"{host}:{port}  {label}  --  {reason}"


class SettingsPane(Vertical):
    """A tabbed form over the whole schema, plus transport management.

    One `TabPane` per schema section rather than one long scrolling page.
    The single-scroll version put Save at the bottom of a page that could run
    to several screens once Beacon, APRS and Link params were all on it --
    reaching it meant scrolling past everything else first, every time. Save
    and Reload now live in a bar below the tabs that never scrolls, so they
    are always one click away regardless of which section is open or how far
    down it the operator has scrolled.
    """

    def compose(self) -> ComposeResult:
        # Schema order decides the tab order, with one exception: the
        # hand-built Transports tab is inserted straight after whichever
        # section is named below. Who you are on the air (Station: callsign,
        # aliases) belongs first -- it is the first thing a new operator sets
        # and the thing most often changed later -- and the hardware you talk
        # through belongs immediately after it. Everything else is tuning.
        with TabbedContent(id="settings-tabs"):
            for section in SETTINGS_SCHEMA:
                with TabPane(section.title, id=_tab_id(section.title)):
                    with VerticalScroll(classes="settings-tab-scroll"):
                        yield Static(section.note, classes="settings-note")
                        for spec in section.fields:
                            yield from self._compose_field(spec)
                if section.title == TRANSPORTS_AFTER_SECTION:
                    with TabPane("Transports", id=_tab_id("Transports")):
                        with VerticalScroll(classes="settings-tab-scroll"):
                            yield from self._compose_transports()
                    with TabPane("Credentials", id=_tab_id("Credentials")):
                        with VerticalScroll(classes="settings-tab-scroll"):
                            yield from self._compose_credentials()
                    with TabPane("Scripts", id=_tab_id("Scripts")):
                        with VerticalScroll(classes="settings-tab-scroll"):
                            yield from self._compose_scripts()

        with Vertical(id="settings-bar"):
            yield Static("", id="settings-banner", classes="settings-banner")
            with Horizontal(classes="settings-row settings-actions"):
                yield Button("Save", variant="primary", id="settings-save")
                yield Button("Reload from file", id="settings-reload")
            yield Static("", id="settings-footer", classes="settings-note")

    def _compose_transports(self) -> ComposeResult:
        """The one hand-built tab -- see the module docstring for why
        transports cannot be schema fields (a list of dicts with
        kind-specific keys, not scalars)."""
        yield Static(
            "Which TNC or modem kissterm talks to. Changing this reopens the "
            "connection, so disconnect first. USB and serial TNCs are noticed "
            "automatically when you plug them in; scanning the network is "
            "manual, because a sweep is around 1500 connection attempts and "
            "does not belong on a timer. 'Scan for hardware' only finds a "
            "KISS TNC or AGWPE engine it can identify by itself -- add a "
            "VARA/Mercury modem, a Telnet or SSH node, or a second entry for "
            "hardware already found with 'New'.",
            classes="settings-note",
        )
        with Horizontal(classes="settings-row"):
            yield Label("Active", classes="settings-label")
            yield Select([], id="set-active-transport", allow_blank=True)
            yield Label("", classes="settings-apply")
        with Horizontal(classes="settings-row"):
            yield Label("", classes="settings-label")
            yield Button("Scan for hardware", id="settings-scan")
            yield Button("New", id="transport-new")
            yield Button("Edit selected", id="transport-edit")
            yield Button("Test selected", id="settings-test")
            yield Button("Forget selected", id="settings-forget")
        yield Static("", id="settings-transport-detail", classes="settings-help")

    def _compose_credentials(self) -> ComposeResult:
        """Saved logins, referenced by name from a station's Connect entry.

        A list of `{"name", "text"}` dicts for the same reason `transports`
        is a list of dicts and not schema fields: `Config.credentials` has
        no fixed shape a scalar form field could bind to, and Add/Edit here
        open `CredentialScreen` rather than being generated.
        """
        yield Static(
            "Reusable logins a station's Connect entry can point at by name "
            "instead of storing its own copy -- change one here and every "
            "entry that names it uses the new text on its next connect. "
            "Nothing here is sent until a Connect entry actually references it.",
            classes="settings-note",
        )
        with Horizontal(classes="settings-row"):
            yield Label("Saved", classes="settings-label")
            yield Select([], id="set-credential", allow_blank=True)
            yield Label("", classes="settings-apply")
        with Horizontal(classes="settings-row"):
            yield Label("", classes="settings-label")
            yield Button("New", id="credential-new")
            yield Button("Edit selected", id="credential-edit")
            yield Button("Forget selected", id="credential-forget")
        yield Static("", id="settings-credential-detail", classes="settings-help")

    def _compose_scripts(self) -> ComposeResult:
        """Saved command sequences, referenced by name from a station's
        Connect entry -- same shape and mechanism as Credentials
        (`{"name", "text"}`, live lookup by name), kept as a separate list
        on purpose: a credential is a login, named for the account it
        belongs to; a script is any sequence of commands sent after
        connecting, named for what it does -- "Check WS1EC mail", not an
        account name. See `Config.scripts`'s docstring.
        """
        yield Static(
            "Reusable command sequences a station's Connect entry can point "
            "at by name instead of storing its own copy -- a login followed "
            "by a node hop, a mailbox check, anything sent one line at a "
            "time after connecting. Checked after a saved credential, "
            "before any literal text typed into an entry directly. Nothing "
            "here is sent until a Connect entry actually references it.",
            classes="settings-note",
        )
        with Horizontal(classes="settings-row"):
            yield Label("Saved", classes="settings-label")
            yield Select([], id="set-script", allow_blank=True)
            yield Label("", classes="settings-apply")
        with Horizontal(classes="settings-row"):
            yield Label("", classes="settings-label")
            yield Button("New", id="script-new")
            yield Button("Edit selected", id="script-edit")
            yield Button("Forget selected", id="script-forget")
        yield Static("", id="settings-script-detail", classes="settings-help")

    def _compose_field(self, spec: Field) -> ComposeResult:
        if spec.custom_render:
            # Only `aprs.latitude` triggers the hand-built block; longitude
            # and grid_square are covered by that same block (it yields
            # widgets for all three ids) and yield nothing of their own here.
            if spec.path == "aprs.latitude":
                yield from self._compose_aprs_position()
            return
        wid = _widget_id(spec.path)
        with Horizontal(classes="settings-row"):
            yield Label(spec.label, classes="settings-label")
            if spec.kind == "bool":
                yield Switch(id=wid)
            elif spec.kind == "choice":
                yield Select(
                    [(label, value) for label, value in spec.choices],
                    id=wid,
                    allow_blank=False,
                )
            elif spec.kind == "custom_choice":
                # Only `aprs.path` uses this today -- see `_CUSTOM_SENTINEL`.
                with Vertical(classes="settings-custom-choice"):
                    yield Select(
                        [(label, value) for label, value in spec.choices]
                        + [(_CUSTOM_LABEL, _CUSTOM_SENTINEL)],
                        id=wid,
                        allow_blank=False,
                    )
                    yield Input(
                        id=f"{wid}-custom", placeholder=spec.placeholder,
                        classes="settings-custom-choice-input",
                    )
            elif spec.kind == "filtered_choice":
                # Only `aprs.symbol` uses this today. The full table is
                # static (unlike Transports' dynamic list), so it is
                # composed here directly rather than populated at render
                # time; typing in the filter Input narrows it live.
                with Vertical(classes="settings-filtered-choice"):
                    yield Input(
                        id=f"{wid}-filter", placeholder="Filter by name...",
                        classes="settings-filtered-choice-filter",
                    )
                    yield Select(
                        [
                            (s.display_label(ascii_safe=self.app.config.ascii_safe), s.key)
                            for s in symbols.SYMBOLS
                        ],
                        id=wid,
                        allow_blank=False,
                    )
            elif spec.kind == "color":
                yield Input(
                    id=wid, placeholder=spec.placeholder or "#1A1B26",
                    classes="settings-color-input",
                )
                yield Static("", id=f"{wid}-swatch", classes="settings-swatch")
            else:
                yield Input(id=wid, placeholder=spec.placeholder)
            yield Label(APPLY_NOTE.get(spec.apply, ""), classes="settings-apply")
        if spec.help:
            yield Static(spec.help, classes="settings-help")
        yield Label("", id=f"{wid}-error", classes="settings-error")

    def _compose_aprs_position(self) -> ComposeResult:
        """Latitude/longitude/grid-square as one hand-built block, outside
        the generic per-`Field` loop -- the same escape hatch Transports
        uses, because a position has two equally valid on-screen forms and
        the schema's one-Field-one-widget model cannot express that. See
        `kissterm/locator.py`. `_save`/`render_settings`/`coerce` treat
        `aprs.latitude`/`aprs.longitude`/`aprs.grid_square` exactly like any
        other field -- this only changes what builds their widgets, not how
        their values are read, written, or validated.
        """
        with Horizontal(classes="settings-row"):
            yield Label("Position entry", classes="settings-label")
            yield Select(
                [("Decimal degrees", "decimal"), ("Maidenhead grid square", "grid")],
                id="aprs-position-mode",
                allow_blank=False,
                value="decimal",
            )
            yield Label("", classes="settings-apply")
        with Horizontal(classes="settings-row", id="aprs-decimal-row"):
            yield Label("Latitude / Longitude", classes="settings-label")
            with Horizontal(classes="settings-decimal-pair"):
                yield Input(id="set-aprs-latitude", placeholder="41.7")
                yield Input(id="set-aprs-longitude", placeholder="-72.7")
            yield Label(APPLY_NOTE["live"], classes="settings-apply")
        yield Label("", id="set-aprs-latitude-error", classes="settings-error")
        yield Label("", id="set-aprs-longitude-error", classes="settings-error")
        with Horizontal(classes="settings-row", id="aprs-grid-row"):
            yield Label("Grid square", classes="settings-label")
            yield Input(id="set-aprs-grid_square", placeholder="FN31pr")
            yield Label(APPLY_NOTE["live"], classes="settings-apply")
        yield Label("", id="set-aprs-grid_square-error", classes="settings-error")
        yield Static(
            "Decimal degrees or a Maidenhead grid square (4, 6, or 8 "
            "characters) -- both edit the same underlying position; "
            "switching modes converts whatever is already entered.",
            classes="settings-help",
        )

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def render_settings(self, config) -> None:
        """Populate every widget from `config`. Safe to call repeatedly.

        `_aprs_position_loading` is held for the whole pass (see
        `_loading_aprs_position`'s docstring) and released only after
        Textual's message queue has drained, via `call_after_refresh` --
        not cleared synchronously here, which would be too early relative
        to when the `Changed` messages this bulk population posts actually
        get processed.
        """
        self._aprs_position_loading = True
        try:
            self._render_settings_fields(config)
        finally:
            self.call_after_refresh(self._stop_loading_aprs_position)

    def _stop_loading_aprs_position(self) -> None:
        self._aprs_position_loading = False

    def _render_settings_fields(self, config) -> None:
        for section in SETTINGS_SCHEMA:
            for spec in section.fields:
                wid = _widget_id(spec.path)
                try:
                    value = get_value(config, spec.path)
                except AttributeError:
                    # A schema entry naming a field the config does not have is
                    # a bug, but not one worth taking the pane down for.
                    log.warning("settings schema references unknown %s", spec.path)
                    continue
                if spec.kind == "bool":
                    self.query_one(f"#{wid}", Switch).value = bool(value)
                elif spec.kind == "choice":
                    self._set_select_value(wid, spec, value)
                elif spec.kind == "custom_choice":
                    self._set_custom_choice_value(wid, spec, value)
                elif spec.kind == "filtered_choice":
                    self._set_symbol_value(wid, value)
                else:
                    text = format_value(spec, value)
                    input_widget = self.query_one(f"#{wid}", Input)
                    if spec.custom_render:
                        # aprs.latitude/longitude/grid_square: silent set,
                        # no Changed message. These three widgets' own
                        # Changed handlers keep each other in sync on a
                        # genuine keystroke, and firing that same machinery
                        # here -- three separate messages processed later,
                        # asynchronously, on three different widgets --
                        # cannot be reliably suppressed by any one flag's
                        # timing (a `call_after_refresh` measured against
                        # ONE widget's queue does not bound when ANOTHER
                        # widget's queued message actually runs). Loading
                        # these three needs no recompute at all: `config`
                        # already stores a consistent decimal and grid
                        # square, so the loop is just copying, not deriving.
                        input_widget.set_reactive(Input.value, text)
                        input_widget.refresh()  # set_reactive skips the
                        # widget's own repaint trigger along with its
                        # watcher; without this the loaded value is
                        # correct in .value but not yet visible on screen.
                    else:
                        input_widget.value = text
                    if spec.kind == "color":
                        self._update_swatch(wid, text)
                self._set_error(wid, "")

        self._render_transports(config)
        self._render_credentials(config)
        self._render_scripts(config)
        self._render_banner(config)
        self._sync_aprs_position_mode(config)

    def _set_custom_choice_value(self, wid: str, spec: Field, value) -> None:
        """Select a matching preset, or fall back to Custom + the literal
        text -- "disable, never clear": a value from a hand-edited
        config.toml that matches no preset must still be visible and still
        round-trip on Save, not silently discarded (same rule
        `ConnectScreen._sync_login_controls` follows in `dialogs.py`)."""
        preset_values = {v for _label, v in spec.choices}
        select = self.query_one(f"#{wid}", Select)
        custom_input = self.query_one(f"#{wid}-custom", Input)
        if value in preset_values:
            select.value = value
            custom_input.value = str(value)
            custom_input.display = False
        else:
            select.value = _CUSTOM_SENTINEL
            custom_input.value = "" if value is None else str(value)
            custom_input.display = True

    def _set_symbol_value(self, wid: str, value) -> None:
        """Same tolerate-an-unknown-value rule as `_set_select_value`,
        against the symbol table instead of a schema's own `Field.choices`."""
        select = self.query_one(f"#{wid}", Select)
        known = {s.key for s in symbols.SYMBOLS}
        select.value = value if value in known else (
            symbols.SYMBOLS[0].key if symbols.SYMBOLS else Select.NULL
        )

    def _set_select_value(self, wid: str, spec: Field, value) -> None:
        """Set a Select's value, tolerating one that is not among its options.

        This is what a stale or hand-edited `config.toml` produces: e.g.
        `theme = "not-a-real-theme"` survives `load_config()` in the field
        itself (an unknown theme name is not, by itself, a schema violation --
        `themes.resolve_theme_id` is what actually falls back, at the point
        the theme is *applied*, not at load time). Setting a Textual `Select`
        to a value outside its options raises `InvalidSelectValueError`,
        which would otherwise crash the whole app the instant the Settings
        tab is opened -- turning a cosmetic config typo into total data loss
        for the session. Falls back to the first offered choice instead.
        """
        select = self.query_one(f"#{wid}", Select)
        valid = {v for _label, v in spec.choices}
        select.value = value if value in valid else (spec.choices[0][1] if spec.choices else Select.NULL)

    def _update_swatch(self, wid: str, text: str) -> None:
        """Fill the color-picker swatch next to a `"color"` field's `Input`
        with the color it names, live as the operator types.

        A hex value the operator has not finished typing yet ("#1A1B" or an
        empty field mid-edit) is simply not a valid `Theme` color -- that is
        not a bug to report inline the way `_save` reports one, it is the
        normal state of an input between keystrokes. The swatch goes back to
        the neutral `-invalid` border and no fill rather than raising or
        showing an error; `_save`'s own validation is what actually stops a
        bad value from being written.
        """
        from textual.css.query import NoMatches

        try:
            swatch = self.query_one(f"#{wid}-swatch", Static)
        except NoMatches:
            return
        from ..config import HEX_COLOR_RE

        text = text.strip()
        if HEX_COLOR_RE.match(text):
            swatch.remove_class("-invalid")
            swatch.styles.background = text
        else:
            swatch.add_class("-invalid")
            swatch.styles.background = None

    @on(Input.Changed, ".settings-color-input")
    def _on_color_input_changed(self, event: Input.Changed) -> None:
        if event.input.id:
            self._update_swatch(event.input.id, event.value)

    # ------------------------------------------------------------------
    # APRS: WIDE-path preset/custom, symbol filter, position mode switch
    # ------------------------------------------------------------------
    @on(Select.Changed, "#set-aprs-path")
    def _on_aprs_path_changed(self, event: Select.Changed) -> None:
        self.query_one("#set-aprs-path-custom", Input).display = (
            event.value == _CUSTOM_SENTINEL
        )

    @on(Input.Changed, "#set-aprs-symbol-filter")
    def _on_aprs_symbol_filter_changed(self, event: Input.Changed) -> None:
        """Narrow the symbol list as the operator types.

        Two things go wrong here if the filter result is used naively, and
        both did:

        * **A filter matching nothing crashed the app.** `set_options([])` on
          a `Select` built with `allow_blank=False` raises `EmptySelectError`
          -- out of a message handler, which takes the whole app down. Typing
          any word that is not in the symbol table (or simply overshooting a
          word that is) was enough. This is the third distinct way this
          project has been bitten by `Select`'s value/option invariants; see
          AGENTS.md sec. 7's `Select.NULL` entry for the other two.
        * **The selection was silently dropped.** `set_options` resets
          `.value`, and the old code restored it only when it survived the
          filter -- so narrowing past your own symbol blanked it, and saving
          then wrote an empty symbol. Losing a setting because you typed in a
          search box is not something an operator would ever expect, and
          nothing on screen said it had happened.

        Both are fixed by the same rule: **the currently-selected symbol is
        always in the list.** It is pinned even when it does not match, so
        the value can never be lost and the list can never be empty. A filter
        matching nothing therefore shows exactly the current symbol, which
        also reads correctly as "nothing else matched".
        """
        select = self.query_one("#set-aprs-symbol", Select)
        current = select.value
        matches = symbols.filter_symbols(event.value)
        ascii_safe = self.app.config.ascii_safe
        options = [(s.display_label(ascii_safe=ascii_safe), s.key) for s in matches]

        current_key = current if isinstance(current, str) else ""
        if current_key and current_key not in {s.key for s in matches}:
            pinned = symbols.lookup(current_key[0], current_key[1:]) if len(current_key) >= 2 else None
            if pinned is not None:
                options.insert(0, (pinned.display_label(ascii_safe=ascii_safe), pinned.key))

        if not options:
            # Only reachable when the stored symbol is not in the table at
            # all (a hand-edited config.toml) AND the filter matches nothing.
            # Showing everything beats showing nothing, and beats crashing.
            options = [
                (s.display_label(ascii_safe=ascii_safe), s.key)
                for s in symbols.SYMBOLS
            ]

        select.set_options(options)
        if current_key in {key for _, key in options}:
            select.value = current_key

    def _sync_aprs_position_mode(self, config) -> None:
        """Pick the initial Decimal/Grid mode from `config.aprs.grid_square`,
        recomputing rather than trusting it blindly -- a hand-edited
        config.toml can carry a grid square that no longer matches the
        lat/lon next to it.

        Deliberately does NOT go through the interactive recompute path:
        `render_settings` has *just* populated the lat/lon/grid Inputs
        straight from `config` a few lines up, and those are already
        correct and authoritative. Letting `Select.Changed` fire its usual
        recompute here would overwrite an exact stored latitude with the
        CENTER of its own grid square -- a real bug caught by
        `tests/pilot/test_settings.py`. `_apply_aprs_position_mode` (show/
        hide only) always runs; `.value` is only touched when it would
        actually change, so a `Changed` message is queued if and only if
        `_suppress_aprs_position_recompute` will be there to catch it --
        no window where a leaked, never-cleared flag could suppress a
        later, real operator-driven mode switch.
        """
        aprs = config.aprs
        mode = "decimal"
        if aprs.grid_square:
            try:
                g_lat, g_lon = from_grid(aprs.grid_square)
            except LocatorError:
                g_lat = g_lon = None
            if (
                g_lat is not None
                and abs(g_lat - aprs.latitude) < 1.0
                and abs(g_lon - aprs.longitude) < 1.0
            ):
                mode = "grid"
        self._apply_aprs_position_mode(mode)
        select = self.query_one("#aprs-position-mode", Select)
        select.value = mode

    def _apply_aprs_position_mode(self, mode: str) -> None:
        self.query_one("#aprs-decimal-row").display = mode == "decimal"
        self.query_one("#aprs-grid-row").display = mode == "grid"

    def _loading_aprs_position(self) -> bool:
        """True while `render_settings` is (or was, very recently) bulk-
        populating the position widgets.

        `render_settings` sets `.value` on the grid Input, then the
        latitude Input, then the longitude Input, then (via
        `_sync_aprs_position_mode`) the mode Select -- each of those posts
        its own `Changed` message, and Textual processes a widget's message
        queue asynchronously, not inline with the assignment that posted
        it. A message queued early (e.g. the grid Input's, while mode was
        still "decimal") can end up PROCESSED late, after mode has already
        flipped to "grid" -- so a same-instant mode check inside a handler
        is not enough; a message that looked harmless when it was posted
        can become corrupting by the time it actually runs. One flag held
        for the whole render pass, and released only after Textual's
        message queue has drained (`call_after_refresh`, not a synchronous
        clear), is what actually closes that window. Caught by
        `tests/pilot/test_settings.py::test_loading_a_saved_grid_square_
        does_not_corrupt_the_decimal_position_it_was_computed_from`.
        """
        return getattr(self, "_aprs_position_loading", False)

    @on(Select.Changed, "#aprs-position-mode")
    def _on_aprs_position_mode_changed(self, event: Select.Changed) -> None:
        """Switching modes is a view toggle, not an edit -- it must never
        overwrite a representation that already has real content with a
        recomputed approximation of the other one (that would silently
        discard a loaded decimal's precision the instant the operator
        merely looks at the grid tab and back). It only fills in a
        representation that is genuinely still blank, e.g. the first time
        an operator with a real decimal position switches to grid mode and
        has never typed one -- matching the compose-time help text's
        promise that switching modes "converts what's already there",
        never what wasn't.
        """
        if self._loading_aprs_position():
            return
        self._apply_aprs_position_mode(event.value)
        if event.value == "grid":
            if not self.query_one("#set-aprs-grid_square", Input).value.strip():
                self._recompute_grid_from_decimal()
        else:
            lat_blank = not self.query_one("#set-aprs-latitude", Input).value.strip()
            lon_blank = not self.query_one("#set-aprs-longitude", Input).value.strip()
            if lat_blank and lon_blank:
                self._recompute_decimal_from_grid()

    @on(Input.Changed, "#set-aprs-grid_square")
    def _on_aprs_grid_changed(self, event: Input.Changed) -> None:
        if self._loading_aprs_position():
            return
        if self.query_one("#aprs-position-mode", Select).value == "grid":
            self._recompute_decimal_from_grid()

    @on(Input.Changed, "#set-aprs-latitude")
    @on(Input.Changed, "#set-aprs-longitude")
    def _on_aprs_decimal_changed(self, event: Input.Changed) -> None:
        if self._loading_aprs_position():
            return
        if self.query_one("#aprs-position-mode", Select).value == "decimal":
            self._recompute_grid_from_decimal()

    def _recompute_decimal_from_grid(self) -> None:
        """Live grid -> decimal conversion, into the (possibly hidden)
        lat/lon Inputs `_save` already reads generically. Silently does
        nothing on an incomplete or invalid grid square -- that is the
        normal state of this field mid-keystroke, not an error to report."""
        text = self.query_one("#set-aprs-grid_square", Input).value.strip()
        try:
            lat, lon = from_grid(text)
        except LocatorError:
            return
        self.query_one("#set-aprs-latitude", Input).value = f"{lat:.6f}"
        self.query_one("#set-aprs-longitude", Input).value = f"{lon:.6f}"

    def _recompute_grid_from_decimal(self) -> None:
        """The mirror image of `_recompute_decimal_from_grid`, so
        `aprs.grid_square` stays a faithful redisplay of whatever position
        decimal-mode editing last settled on."""
        try:
            lat = float(self.query_one("#set-aprs-latitude", Input).value)
            lon = float(self.query_one("#set-aprs-longitude", Input).value)
        except ValueError:
            return
        try:
            grid = to_grid(lat, lon, 6)
        except LocatorError:
            return
        self.query_one("#set-aprs-grid_square", Input).value = grid

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
        lines = str(entry.get("text", "")).count("\n") + 1 if entry.get("text") else 0
        detail.update(f"{lines} line(s) saved." if lines else "(empty)")

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

    def _set_error(self, wid: str, message: str) -> None:
        label = self.query_one(f"#{wid}-error", Label)
        label.update(message)
        label.display = bool(message)

    # ------------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------------
    @on(Button.Pressed, "#settings-save")
    def _save(self) -> None:
        config = self.app.config  # type: ignore[attr-defined]
        previous_active = config.active_transport
        pending: dict[str, object] = {}
        failed = False
        failed_sections: set[str] = set()

        for section in SETTINGS_SCHEMA:
            for spec in section.fields:
                wid = _widget_id(spec.path)
                if spec.kind == "bool":
                    raw = self.query_one(f"#{wid}", Switch).value
                elif spec.kind == "choice":
                    raw = self.query_one(f"#{wid}", Select).value
                elif spec.kind == "custom_choice":
                    select_value = self.query_one(f"#{wid}", Select).value
                    if select_value == _CUSTOM_SENTINEL:
                        raw = self.query_one(f"#{wid}-custom", Input).value
                    else:
                        raw = "" if select_value == Select.NULL else select_value
                elif spec.kind == "filtered_choice":
                    select_value = self.query_one(f"#{wid}", Select).value
                    raw = "" if select_value == Select.NULL else select_value
                else:
                    raw = self.query_one(f"#{wid}", Input).value
                try:
                    pending[spec.path] = coerce(spec, raw)
                    self._set_error(wid, "")
                except ValidationError as exc:
                    self._set_error(wid, str(exc))
                    failed = True
                    failed_sections.add(section.title)

        if failed:
            # Nothing is written. A partial save leaves the operator unable to
            # tell which values took -- worse than refusing outright. Naming
            # the tabs matters now that a bad field is not necessarily on the
            # one currently open, and jumping to the first one means the
            # operator does not have to go hunting for it themselves.
            self.query_one("#settings-tabs", TabbedContent).active = _tab_id(
                sorted(failed_sections)[0]
            )
            self.query_one("#settings-footer", Static).update(
                "Not saved -- fix the fields in: " + ", ".join(sorted(failed_sections))
            )
            self.app.notify("Settings not saved: some values are invalid.", severity="error")
            return

        for path, value in pending.items():
            set_value(config, path, value)

        selected = self.query_one("#set-active-transport", Select).value
        if selected and selected != Select.NULL:
            config.active_transport = str(selected)

        notes = cross_check(config)
        saved = self.app._save_config()  # type: ignore[attr-defined]
        self._apply_live(config)

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
        self.app.notify(message, severity="information" if saved else "warning")

        if config.active_transport and config.active_transport != previous_active:
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
        """Shared by New and Edit selected: push the form, then -- per
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
        self.app.notify(f"Saved transport {result['name']!r}.")  # type: ignore[attr-defined]

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
        self.app.notify(f"Forgot transport {name}.")

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
        config.credentials = [c for c in config.credentials if c.get("name") != result.name]
        config.credentials.append({"name": result.name, "text": result.text})
        self.app._save_config()  # type: ignore[attr-defined]
        self._render_credentials(config)
        self.query_one("#set-credential", Select).value = result.name
        self._render_credential_detail(config)
        self.app.notify(f"Saved credential {result.name!r}.")  # type: ignore[attr-defined]

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
            CredentialScreen(entry.get("name", ""), entry.get("text", ""))
        )
        if result is None:
            return
        # Drop both the old name and the new one (a rename could collide
        # with an existing entry) before re-adding, so a rename replaces
        # the old entry in place rather than leaving a stale duplicate a
        # station could still resolve to.
        config.credentials = [
            c for c in config.credentials if c.get("name") not in (name, result.name)
        ]
        config.credentials.append({"name": result.name, "text": result.text})
        self.app._save_config()  # type: ignore[attr-defined]
        self._render_credentials(config)
        self.query_one("#set-credential", Select).value = result.name
        self._render_credential_detail(config)
        self.app.notify(f"Saved credential {result.name!r}.")  # type: ignore[attr-defined]

    @on(Button.Pressed, "#credential-edit")
    def _edit_credential_pressed(self) -> None:
        self._edit_credential()

    @on(Button.Pressed, "#credential-forget")
    def _forget_credential(self) -> None:
        config = self.app.config  # type: ignore[attr-defined]
        name = self.query_one("#set-credential", Select).value
        if not name or name == Select.NULL:
            return
        config.credentials = [c for c in config.credentials if c.get("name") != name]
        self.app._save_config()  # type: ignore[attr-defined]
        self._render_credentials(config)
        self.app.notify(f"Forgot credential {name!r}.")  # type: ignore[attr-defined]

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
        self.app.notify(f"Saved script {result.name!r}.")  # type: ignore[attr-defined]

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
        self.app.notify(f"Saved script {result.name!r}.")  # type: ignore[attr-defined]

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
        self.app.notify(f"Forgot script {name!r}.")  # type: ignore[attr-defined]

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
