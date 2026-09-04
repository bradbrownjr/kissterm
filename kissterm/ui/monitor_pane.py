"""The Monitor pane: the raw channel log and its filter bar.

kissterm's monitor is the operator's equivalent of `listen -a` -- see
`kissterm/monitor.py` for why that matters. This pane's job stops at
*displaying* a line and *deciding what the filter widgets should change on
`MonitorFilter`*; it never decodes a frame itself. `format_frame` runs once,
in `app.py`'s frame fan-out, and the already-rendered text is handed here via
`write_line` -- adding a second place that turns a frame into text is exactly
the "second decode path" the fan-out rule in `app.py`'s docstring warns
against.

The filter state itself (`MonitorFilter`) lives on the app, not on this pane,
because the same filter also has to gate what `app.py`'s fan-out even bothers
rendering before it gets here -- a widget-local copy would need to be kept in
sync with the app's copy on every change instead of being the single source
of truth. This pane reaches it as `self.app.monitor_filter`, a documented
attribute of `KissTermApp`.
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, Input, RichLog


class MonitorPane(Container):
    """The filter bar (`#monitor-filter`) plus the channel log (`#monitor-log`)."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="monitor-filter"):
            yield Input(placeholder="filter: callsign or text", id="monitor-query")
            yield Button("Supervisory", id="monitor-toggle-s")
        yield RichLog(
            id="monitor-log", wrap=True, markup=False, highlight=False, max_lines=5000
        )

    # ------------------------------------------------------------------
    def write_line(self, text: str) -> None:
        """Append one already-rendered monitor line. Called from `app.py`'s
        frame fan-out with `format_frame(...).as_text()` -- this pane never
        touches an `AX25Frame` directly.
        """
        self.query_one("#monitor-log", RichLog).write(text)

    def clear(self) -> None:
        self.query_one("#monitor-log", RichLog).clear()

    # ------------------------------------------------------------------
    @on(Input.Changed, "#monitor-query")
    def _update_filter(self, event: Input.Changed) -> None:
        monitor_filter = self.app.monitor_filter  # type: ignore[attr-defined]
        value = event.value.strip()
        if not value:
            monitor_filter.calls = ()
            monitor_filter.contains = ""
        elif any(c.isdigit() for c in value) and " " not in value:
            monitor_filter.calls = (value,)
            monitor_filter.contains = ""
        else:
            monitor_filter.calls = ()
            monitor_filter.contains = value

    @on(Button.Pressed, "#monitor-toggle-s")
    def _toggle_supervisory(self) -> None:
        monitor_filter = self.app.monitor_filter  # type: ignore[attr-defined]
        monitor_filter.show_supervisory = not monitor_filter.show_supervisory
        state = "on" if monitor_filter.show_supervisory else "off"
        self.app.notify(f"Supervisory frames {state}")
