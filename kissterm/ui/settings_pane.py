"""The Settings pane -- read-only for now, and honest about it.

`config.toml` is still hand-edited (roadmap P6 makes this editable). Showing
the operator the values kissterm is actually running with, plus where the file
lives, is most of the value of a settings screen and none of the risk: a
half-finished editor that writes a malformed config is worse than no editor,
because `load_config` would then start the app with silently different values.

`render_settings` takes the config as an argument rather than reading
`self.app.config` so this pane can be rendered in a test without an app.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static


class SettingsPane(Container):
    """A static read-out of the running configuration."""

    def compose(self) -> ComposeResult:
        yield Static(id="settings-body", classes="placeholder")

    def render_settings(self, config) -> None:
        try:
            from ..config import config_path

            path = str(config_path())
        except Exception:
            # Never let a settings *display* problem stop the app; the operator
            # can still use the radio without knowing where the file lives.
            path = "(could not determine)"

        lines = [
            f"Callsign          {getattr(config, 'mycall', '') or '(unset)'}   (Ctrl+K to change)",
            f"Active transport  {getattr(config, 'active_transport', '') or '(none)'}",
            f"paclen / window   {getattr(config, 'paclen', '-')} / {getattr(config, 'window', '-')}",
            f"T1 / T2 / T3      {getattr(config, 't1', '-')} / {getattr(config, 't2', '-')} / {getattr(config, 't3', '-')}",
            f"Retries (N2)      {getattr(config, 'retries', '-')}",
            "",
            f"Config file       {path}",
            "",
            "Callsign is editable here with Ctrl+K, or from a shell with",
            "'kissterm --callsign W1AW-1'. The remaining settings are still",
            "hand-edited in config.toml (roadmap P6); 'kissterm --doctor'",
            "checks the file over and says what is wrong with it.",
        ]
        warnings = list(getattr(config, "warnings", ()) or ())
        if warnings:
            lines += ["", "Problems found in config.toml (defaults used instead):"]
            lines += [f"  - {w}" for w in warnings]
        self.query_one("#settings-body", Static).update("\n".join(lines))
