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


class CallsignScreen(ModalScreen[str | None]):
    """Change the station callsign without leaving the app.

    This exists because operators change callsign far more often than the
    "set it once at install time" model assumes: a `-1` SSID for a personal
    mailbox, a different SSID for portable or emergency-net operation, a club
    call for an event, a fresh SSID after someone else claimed the one you were
    using on the same channel. Before this dialog the only route was
    `kissterm --setup`, which re-runs the whole first-run wizard -- including a
    multi-second LAN sweep and transport re-selection -- to change one string.

    Validation is `AX25Address.parse`, the same function the wire encoder uses,
    so anything this dialog accepts is guaranteed encodable into an address
    field. Rejecting here is much better than discovering it at SABM time.
    """

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, current: str = "") -> None:
        super().__init__()
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-box"):
            yield Label("Station callsign", id="connect-title")
            yield Input(
                value=self._current,
                placeholder="N1ABC-1",
                id="callsign-value",
            )
            yield Label(
                "Saved to config.toml and used for the next connection.",
                id="callsign-hint",
            )
            yield Label("", id="callsign-error")
            with Horizontal(id="connect-buttons"):
                yield Button("Save", variant="primary", id="callsign-save")
                yield Button("Cancel", id="callsign-cancel")

    def on_mount(self) -> None:
        field = self.query_one("#callsign-value", Input)
        field.focus()
        # Cursor to the end, so backspacing an SSID off the current call is
        # one keystroke away -- the most common edit by far is N1ABC-1 to
        # N1ABC-9, not typing a whole new callsign.
        field.action_end()

    @on(Button.Pressed, "#callsign-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#callsign-save")
    @on(Input.Submitted, "#callsign-value")
    def _save(self) -> None:
        text = self.query_one("#callsign-value", Input).value.strip().upper()
        if not text:
            return
        from ..ax25 import AX25Address

        try:
            AX25Address.parse(text)
        except Exception as exc:
            self.query_one("#callsign-error", Label).update(f"[red]{exc}[/red]")
            return
        self.dismiss(text)
