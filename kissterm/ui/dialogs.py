"""Modal screens layered on top of the app.

`ConnectScreen` is the only one that exists today, but it is pulled out into
its own module rather than left inline in `app.py` because it will not stay
the only one -- a "confirm disconnect", a transport picker, or a settings
editor (roadmap P6) are all `ModalScreen`s, and each one is a small, mostly
self-contained unit that a future editor should be able to add or change
without touching `app.py`'s bindings or fan-out wiring at all. Add new
modals here.
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label

from ..ax25 import parse_path


class ConnectScreen(ModalScreen[str | None]):
    """Ask for a connect target. Accepts ``CALL-SSID [via DIGI,DIGI]``."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-box"):
            yield Label("Connect to station", id="connect-title")
            yield Input(
                placeholder="WS1EC-7  or  WS1EC-7 via W1AW-1",
                id="connect-target",
            )
            yield Label("", id="connect-error")
            with Horizontal(id="connect-buttons"):
                yield Button("Connect", variant="primary", id="connect-go")
                yield Button("Cancel", id="connect-cancel")

    def on_mount(self) -> None:
        self.query_one("#connect-target", Input).focus()

    @on(Button.Pressed, "#connect-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#connect-go")
    @on(Input.Submitted, "#connect-target")
    def _go(self) -> None:
        text = self.query_one("#connect-target", Input).value.strip()
        if not text:
            return
        try:
            parse_path(text)
        except Exception as exc:
            self.query_one("#connect-error", Label).update(f"[red]{exc}[/red]")
            return
        self.dismiss(text)
