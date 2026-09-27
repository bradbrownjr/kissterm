"""RMS gateways (F10 > Session): Winlink gateways nearest first, one to use.

`kissterm/winlink/gateways.py` holds the list, the fetch and why the fetch
needs an access key kissterm does not have yet; this is display and
wiring only. Nothing here goes on the air: Refresh is an HTTPS request to
winlink.org, made only when pressed, and the result is kept in a file so
the list opens without the Internet (an emergency station often has
none).

Choosing a gateway ("Use for Winlink", or Enter on its row) dismisses with
that channel; the app adds it to the Address Book and makes it the
Winlink Dial (`KissTermApp.action_rms_gateways`). Every contact lives in
the Address Book, whatever reaches it (operator, 2026-09-26).
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Label, Select, Static

from ..geo import compass_point
from ..winlink import gateways

#: The most rows shown; the full list is a few thousand channels.
SHOWN = 200


class _GatewayTable(DataTable):
    BINDINGS = [Binding("enter", "select_cursor", "Use for Winlink")]


class RmsGatewaysScreen(ModalScreen["gateways.Channel | None"]):
    """The gateway list, filtered by mode, nearest first."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Close")]

    def __init__(self, cache: Path, position: tuple[float, float] | None, *,
                 key: str | None = None) -> None:
        super().__init__()
        self._cache = cache
        self._position = position
        self._key = gateways.ACCESS_KEY if key is None else key
        self._channels: list[gateways.Channel] = []
        self._shown: list[gateways.Channel] = []
        self._fetched_at: float | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="gateways-box"):
            yield Label("RMS gateways", id="gateways-title")
            yield Static("", id="gateways-note")
            with Horizontal(id="gateways-filter"):
                yield Label("Mode", id="gateways-mode-label")
                yield Select([(label, value) for label, value in gateways.MODES],
                             value="packet", allow_blank=False, compact=True, id="gateways-mode")
            yield _GatewayTable(id="gateways-table", cursor_type="row", zebra_stripes=True)
            with Horizontal(id="connect-buttons"):
                yield Button("Refresh", id="gateways-refresh", disabled=not self._key)
                yield Button("Use for Winlink", variant="primary", id="gateways-use")
                yield Button("Close", id="gateways-close")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#gateways-table", DataTable)
        table.add_columns("Gateway", "Frequency", "Mode", "Grid", "Distance", "Hours")
        cached = gateways.load_cached(self._cache)
        if cached is not None:
            data, self._fetched_at = cached
            try:
                self._load(data)
            except ValueError:
                self._channels = []
                self._fetched_at = None
        self._show()
        table.focus()

    def _load(self, data: bytes) -> None:
        lat, lon = self._position if self._position else (None, None)
        self._channels = gateways.parse(data, lat=lat, lon=lon)

    def _show(self) -> None:
        mode = self.query_one("#gateways-mode", Select).value
        self._shown = gateways.nearest(self._channels, str(mode or ""), limit=SHOWN)
        table = self.query_one("#gateways-table", DataTable)
        table.clear()
        for channel in self._shown:
            if channel.distance_mi is None:
                distance = ""
            else:
                distance = f"{channel.distance_mi:.0f} mi {compass_point(channel.bearing or 0.0)}"
            table.add_row(channel.callsign, channel.frequency, channel.modes, channel.grid,
                          distance, channel.hours)
        self.query_one("#gateways-use", Button).disabled = not self._shown
        self._say()

    def _say(self, problem: str = "") -> None:
        parts = []
        if problem:
            parts.append(problem)
        if self._fetched_at is not None:
            parts.append(f"From winlink.org, {gateways.age_text(self._fetched_at)}; "
                         f"{len(self._shown)} shown.")
        elif not self._key:
            parts.append("No gateway list yet, and this version of kissterm cannot fetch "
                         "one: it is waiting for its Winlink API key.")
        else:
            parts.append("No gateway list yet. Refresh fetches it from winlink.org over "
                         "the Internet; nothing goes on the air.")
        if self._channels and self._position is None:
            parts.append("Set your position in Settings > APRS to sort by distance.")
        self.query_one("#gateways-note", Static).update(" ".join(parts))

    @on(Select.Changed, "#gateways-mode")
    def _mode_changed(self) -> None:
        self._show()

    @on(Button.Pressed, "#gateways-refresh")
    @work(exclusive=True)
    async def _refresh(self) -> None:
        button = self.query_one("#gateways-refresh", Button)
        button.disabled = True
        self._say("Fetching the list from winlink.org...")
        try:
            data = await asyncio.to_thread(gateways.fetch, self._key)
            await asyncio.to_thread(gateways.save_cached, self._cache, data)
        except (gateways.NoAccessKey, gateways.FetchError, OSError) as exc:
            self._say(f"Not refreshed: {exc}.")
            return
        finally:
            button.disabled = not self._key
        cached = gateways.load_cached(self._cache)
        self._fetched_at = cached[1] if cached else time.time()
        self._load(data)
        self._show()

    def _chosen(self) -> gateways.Channel | None:
        row = self.query_one("#gateways-table", DataTable).cursor_row
        return self._shown[row] if 0 <= row < len(self._shown) else None

    @on(DataTable.RowSelected, "#gateways-table")
    @on(Button.Pressed, "#gateways-use")
    def _use(self) -> None:
        channel = self._chosen()
        if channel is not None:
            self.dismiss(channel)

    @on(Button.Pressed, "#gateways-close")
    def _close(self) -> None:
        self.dismiss(None)
