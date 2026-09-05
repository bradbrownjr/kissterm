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
from textual.widgets import Button, Input, Label, Select, Static, Switch

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


class SettingsPane(VerticalScroll):
    """Scrollable form over the whole schema, plus transport management."""

    def compose(self) -> ComposeResult:
        yield Static("", id="settings-banner", classes="settings-banner")

        # Schema order decides the page order, with one exception: the
        # hand-built Transports block is emitted straight after whichever
        # section is named below. Who you are on the air (Station: callsign,
        # aliases) belongs at the very top -- it is the first thing a new
        # operator sets and the thing most often changed later -- and the
        # hardware you talk through belongs immediately under it. Everything
        # after that is tuning.
        for section in SETTINGS_SCHEMA:
            yield Label(section.title, classes="settings-section")
            yield Static(section.note, classes="settings-note")
            for spec in section.fields:
                yield from self._compose_field(spec)
            if section.title == TRANSPORTS_AFTER_SECTION:
                yield from self._compose_transports()

        with Horizontal(classes="settings-row settings-actions"):
            yield Button("Save", variant="primary", id="settings-save")
            yield Button("Reload from file", id="settings-reload")
        yield Static("", id="settings-footer", classes="settings-note")

    def _compose_transports(self) -> ComposeResult:
        """The one hand-built section -- see the module docstring for why
        transports cannot be schema fields (a list of dicts with
        kind-specific keys, not scalars)."""
        yield Label("Transports", classes="settings-section")
        yield Static(
            "Which TNC or modem kissterm talks to. Changing this reopens the "
            "connection, so disconnect first. USB and serial TNCs are noticed "
            "automatically when you plug them in; scanning the network is "
            "manual, because a sweep is around 1500 connection attempts and "
            "does not belong on a timer.",
            classes="settings-note",
        )
        with Horizontal(classes="settings-row"):
            yield Label("Active", classes="settings-label")
            yield Select([], id="set-active-transport", allow_blank=True)
            yield Label("", classes="settings-apply")
        with Horizontal(classes="settings-row"):
            yield Label("", classes="settings-label")
            yield Button("Scan for hardware", id="settings-scan")
            yield Button("Test selected", id="settings-test")
            yield Button("Forget selected", id="settings-forget")
        yield Static("", id="settings-transport-detail", classes="settings-help")

    def _compose_field(self, spec: Field) -> ComposeResult:
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
            else:
                yield Input(id=wid, placeholder=spec.placeholder)
            yield Label(APPLY_NOTE.get(spec.apply, ""), classes="settings-apply")
        if spec.help:
            yield Static(spec.help, classes="settings-help")
        yield Label("", id=f"{wid}-error", classes="settings-error")

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def render_settings(self, config) -> None:
        """Populate every widget from `config`. Safe to call repeatedly."""
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
                else:
                    self.query_one(f"#{wid}", Input).value = format_value(spec, value)
                self._set_error(wid, "")

        self._render_transports(config)
        self._render_banner(config)

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
        select.value = value if value in valid else (spec.choices[0][1] if spec.choices else Select.BLANK)

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
        pending: dict[str, object] = {}
        failed = False

        for section in SETTINGS_SCHEMA:
            for spec in section.fields:
                wid = _widget_id(spec.path)
                if spec.kind == "bool":
                    raw = self.query_one(f"#{wid}", Switch).value
                elif spec.kind == "choice":
                    raw = self.query_one(f"#{wid}", Select).value
                else:
                    raw = self.query_one(f"#{wid}", Input).value
                try:
                    pending[spec.path] = coerce(spec, raw)
                    self._set_error(wid, "")
                except ValidationError as exc:
                    self._set_error(wid, str(exc))
                    failed = True

        if failed:
            # Nothing is written. A partial save leaves the operator unable to
            # tell which values took -- worse than refusing outright.
            self.query_one("#settings-footer", Static).update(
                "Not saved -- fix the fields marked above."
            )
            self.app.notify("Settings not saved: some values are invalid.", severity="error")
            return

        for path, value in pending.items():
            set_value(config, path, value)

        selected = self.query_one("#set-active-transport", Select).value
        if selected and selected != Select.BLANK:
            config.active_transport = str(selected)

        notes = cross_check(config)
        saved = self.app._save_config()  # type: ignore[attr-defined]
        self._apply_live(config)

        message = "Settings saved." if saved else "Applied for this session (could not write config)."
        if notes:
            message += " " + " ".join(notes)
        self.query_one("#settings-footer", Static).update(message)
        self.app.notify(message, severity="information" if saved else "warning")

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
            fresh = load_config()
        except Exception:
            log.exception("could not reload config")
            self.app.notify("Could not read config.toml.", severity="error")
            return
        self.app.config = fresh  # type: ignore[attr-defined]
        if hasattr(self.app, "apply_theme"):
            self.app.apply_theme()  # type: ignore[attr-defined]
        self.render_settings(fresh)
        self.query_one("#settings-footer", Static).update("Reloaded from config.toml.")

    @on(Select.Changed, "#set-active-transport")
    def _transport_changed(self) -> None:
        self._render_transport_detail(self.app.config)  # type: ignore[attr-defined]

    @on(Button.Pressed, "#settings-forget")
    def _forget(self) -> None:
        config = self.app.config  # type: ignore[attr-defined]
        name = self.query_one("#set-active-transport", Select).value
        if not name or name == Select.BLANK:
            return
        config.transports = [t for t in config.transports if t.get("name") != name]
        if config.active_transport == name:
            config.active_transport = (
                config.transports[0].get("name", "") if config.transports else ""
            )
        self.app._save_config()  # type: ignore[attr-defined]
        self._render_transports(config)
        self.app.notify(f"Forgot transport {name}.")

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
        if kind in ("serial", "bluetooth", "kernel"):
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
