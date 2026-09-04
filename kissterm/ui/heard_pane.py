"""The Heard pane: a snapshot view of `kissterm.heard.HeardTable`.

This pane owns nothing about *what* has been heard -- that is
`HeardTable`'s job, and it is fed by `app.py`'s frame fan-out via
`HeardTable.record`, once, for every frame the transport produces (see that
module's docstring for why it lives independent of any single protocol).
All this widget does is render the current snapshot into its `DataTable`
when asked. It is asked from `app.py` on a periodic timer and only while
this tab is the active one, which is a UI-refresh-rate decision that belongs
in the app, not here -- this pane does not know or care whether it is
currently visible.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import DataTable

if TYPE_CHECKING:
    from ..heard import HeardTable


class HeardPane(Container):
    """The MHEARD table (`#heard-table`)."""

    def compose(self) -> ComposeResult:
        yield DataTable(id="heard-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        table = self.query_one("#heard-table", DataTable)
        table.add_columns("Callsign", "Last heard", "Count", "Path", "Direct")

    def refresh_from(self, heard: "HeardTable") -> None:
        """Rebuild every row from a fresh `heard.entries()` snapshot."""
        table = self.query_one("#heard-table", DataTable)
        table.clear()
        for entry in heard.entries():
            table.add_row(
                entry.callsign,
                datetime.fromtimestamp(entry.last_heard).strftime("%H:%M:%S"),
                str(entry.count),
                entry.last_path or "-",
                "yes" if entry.direct else "via",
            )
