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

Bearing and distance are computed here, not stored on `HeardEntry`: they are
a function of two positions (the operator's own, and the station's last
reported one) recomputed fresh on every `refresh_from`, never cached, so a
Settings change to the operator's own position is reflected the next repaint
with no invalidation logic needed anywhere. `app.py` decides whether the
operator's own position is set at all (see its "no position set" convention,
shared with `AprsBeaconer`) and passes it in as `my_position`; this pane
never reads `Config` directly. `kissterm.geo` and `kissterm.heard` both stay
positionless-safe: neither owning position raises when there is nothing to
compute from, they just render "-".

Clicking the Distance or Bearing header sorts the table by that value,
click again to reverse -- the "sorted bearing/distance-from-me list" the
roadmap asked for. Every other column keeps `HeardTable.entries()`'s own
order (last heard, most recent first) and does not respond to a header
click; making every column independently sortable is a bigger feature this
task did not ask for; `Count` in particular is stored as display text
("12"), which sorts lexically wrong ("12" before "9") without a numeric key
of its own -- undertaking that is future scope, not silently shipped here.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import DataTable

from ..geo import bearing_distance_mi, compass_point

if TYPE_CHECKING:
    from ..heard import HeardTable

_COLUMNS = ("Callsign", "Last heard", "Count", "Path", "Direct", "Distance", "Bearing")
_SORTABLE = ("Distance", "Bearing")


class HeardPane(Container):
    """The MHEARD table (`#heard-table`)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        #: callsign -> (distance_mi, bearing_deg) for every row currently
        #: shown with a known fix, refreshed on every `refresh_from`. Kept
        #: alongside the table (rather than parsed back out of formatted
        #: cell text like "12.4 mi") so a header click can sort numerically.
        self._geo: dict[str, tuple[float, float]] = {}
        #: `None` means "use `HeardTable`'s own order", the default. Set to
        #: "Distance" or "Bearing" by a header click.
        self._sort_column: str | None = None
        self._sort_reverse: bool = False

    def compose(self) -> ComposeResult:
        yield DataTable(id="heard-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        table = self.query_one("#heard-table", DataTable)
        # Explicit keys equal to the label text: `_apply_sort` addresses the
        # Callsign column by that string, and an auto-generated key
        # (Textual's default when none is given) hashes by object identity,
        # not by value, so `table.sort("Callsign", ...)` would raise
        # `KeyError` instead of finding the column.
        table.add_columns(*[(label, label) for label in _COLUMNS])

    def refresh_from(
        self, heard: "HeardTable", my_position: tuple[float, float] | None = None
    ) -> None:
        """Rebuild every row from a fresh `heard.entries()` snapshot.

        `my_position` is `(latitude, longitude)` if the operator has entered
        one, `None` otherwise -- distance and bearing render as "-" without
        it, since there is nothing to measure from.
        """
        table = self.query_one("#heard-table", DataTable)
        table.clear()
        self._geo.clear()
        for entry in heard.entries():
            distance_text = bearing_text = "-"
            if my_position is not None and entry.last_position is not None:
                lat, lon = entry.last_position
                bearing_deg, distance_mi = bearing_distance_mi(*my_position, lat, lon)
                self._geo[entry.callsign] = (distance_mi, bearing_deg)
                distance_text = f"{distance_mi:.1f} mi"
                bearing_text = f"{bearing_deg:.0f}\N{DEGREE SIGN} {compass_point(bearing_deg)}"
            table.add_row(
                entry.callsign,
                datetime.fromtimestamp(entry.last_heard).strftime("%H:%M:%S"),
                str(entry.count),
                entry.last_path or "-",
                "yes" if entry.direct else "via",
                distance_text,
                bearing_text,
                key=entry.callsign,
            )
        if self._sort_column is not None:
            self._apply_sort(table)

    @on(DataTable.HeaderSelected, "#heard-table")
    def _on_header_selected(self, event: DataTable.HeaderSelected) -> None:
        column = event.column_key.value
        if column not in _SORTABLE:
            return
        if column == self._sort_column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = False
        self._apply_sort(event.data_table)

    def _apply_sort(self, table: DataTable) -> None:
        slot = 0 if self._sort_column == "Distance" else 1
        # A station with no fix yet sorts to the end regardless of
        # direction, rather than jumping to the front on a distance sort
        # because "unknown" happens to be less than every real number.
        table.sort(
            "Callsign",
            key=lambda callsign: self._geo.get(callsign, (float("inf"), float("inf")))[slot],
            reverse=self._sort_reverse,
        )
