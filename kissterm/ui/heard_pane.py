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
import math
import time
from typing import TYPE_CHECKING, Iterable

from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Button, DataTable, Static

from ..geo import bearing_distance_mi, compass_point

if TYPE_CHECKING:
    from ..heard import HeardTable

_COLUMNS = ("Callsign", "Last heard", "Count", "Path", "Direct", "Distance", "Bearing")
_SORTABLE = ("Distance", "Bearing")

#: A received position older than this is still useful context, but should not
#: look current on a quick directional display.  This is deliberately a
#: presentation marker, not an expiry: MHEARD remains the source of truth.
_STALE_SECONDS = 30 * 60


def _radar_label(index: int) -> str:
    """One compact, ASCII-only legend marker for a station."""
    alphabet = "123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return alphabet[index] if index < len(alphabet) else "+"


def render_radar(
    entries: Iterable["HeardEntry"],
    my_position: tuple[float, float] | None,
    *,
    now: float | None = None,
    width: int = 31,
    height: int = 15,
) -> str:
    """Render a receive-only ASCII radar from an MHEARD snapshot.

    Coordinates never enter this view unless both the configured station
    position and a received, finite latitude/longitude claim are present.
    The symbols are legend indices rather than APRS symbols: this is a small
    directional aid, not a claim of a surveyed map or station identity.
    """
    entries = list(entries)
    positioned = []
    unknown = 0
    for entry in entries:
        if entry.last_position is None:
            unknown += 1
            continue
        lat, lon = entry.last_position
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            unknown += 1
            continue
        positioned.append((entry, lat, lon))

    if my_position is None:
        return (
            "Radar needs this station's position (Settings).\n"
            f"Received position claims: {len(positioned)}; no known position: {unknown}."
        )
    my_lat, my_lon = my_position
    if not (math.isfinite(my_lat) and math.isfinite(my_lon) and -90 <= my_lat <= 90 and -180 <= my_lon <= 180):
        return "Radar cannot use this station's invalid configured position."

    now = time.time() if now is None else now
    points = []
    for entry, lat, lon in positioned:
        bearing, distance = bearing_distance_mi(my_lat, my_lon, lat, lon)
        points.append((entry, bearing, distance))
    if not points:
        return "No received position claims to plot."

    # Keep the map compact enough for a normal and narrow terminal.  Its
    # scale is explicitly shown because positions are claims, not precision
    # navigation data; the outer ring is the farthest displayed claim.
    width = max(21, width | 1)
    height = max(9, height | 1)
    max_distance = max(distance for _entry, _bearing, distance in points)
    radius_mi = max(1.0, max_distance)
    center_x, center_y = width // 2, height // 2
    radius_x, radius_y = max(1, center_x - 1), max(1, center_y - 1)
    grid = [[" " for _x in range(width)] for _y in range(height)]
    for x in range(width):
        grid[0][x] = "-"
        grid[-1][x] = "-"
    for y in range(height):
        grid[y][0] = grid[y][-1] = "|"
    grid[0][0] = grid[0][-1] = grid[-1][0] = grid[-1][-1] = "+"
    grid[0][center_x] = "N"
    grid[center_y][center_x] = "@"

    legend = []
    for index, (entry, bearing, distance) in enumerate(points):
        label = _radar_label(index)
        radians = math.radians(bearing)
        x = round(center_x + math.sin(radians) * min(distance / radius_mi, 1.0) * radius_x)
        y = round(center_y - math.cos(radians) * min(distance / radius_mi, 1.0) * radius_y)
        x = min(width - 2, max(1, x))
        y = min(height - 2, max(1, y))
        grid[y][x] = label
        stale = " ~" if now - entry.last_heard > _STALE_SECONDS else ""
        legend.append(f"{label} {entry.callsign} {distance:.0f}mi {compass_point(bearing)}{stale}")

    lines = [f"Radar: @ this station; outer ring {radius_mi:.0f} mi; received position claims."]
    lines.extend("".join(row).rstrip() for row in grid)
    lines.append("~ heard over 30 min ago; no known position: " + str(unknown) + ".")
    lines.extend(legend)
    return "\n".join(lines)


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
        self._show_radar = False
        self._last_heard: HeardTable | None = None
        self._last_my_position: tuple[float, float] | None = None
        #: Set once `on_mount` has built the table's columns. The app's 2 s
        #: refresh interval and tab activation can reach this pane before
        #: that, and a `query_one` then raised `NoMatches` out of a timer.
        self._table_ready = False

    def compose(self) -> ComposeResult:
        yield Button("Show radar", id="heard-radar")
        yield DataTable(id="heard-table", cursor_type="row", zebra_stripes=True)
        yield Static(id="heard-radar-view")

    def on_mount(self) -> None:
        table = self.query_one("#heard-table", DataTable)
        # Explicit keys equal to the label text: `_apply_sort` addresses the
        # Callsign column by that string, and an auto-generated key
        # (Textual's default when none is given) hashes by object identity,
        # not by value, so `table.sort("Callsign", ...)` would raise
        # `KeyError` instead of finding the column.
        table.add_columns(*[(label, label) for label in _COLUMNS])
        self.query_one("#heard-radar-view", Static).display = False
        self._table_ready = True
        if self._last_heard is not None:
            self.refresh_from(self._last_heard, self._last_my_position)

    def refresh_from(
        self, heard: "HeardTable", my_position: tuple[float, float] | None = None
    ) -> None:
        """Rebuild every row from a fresh `heard.entries()` snapshot.

        `my_position` is `(latitude, longitude)` if the operator has entered
        one, `None` otherwise -- distance and bearing render as "-" without
        it, since there is nothing to measure from.
        """
        self._last_heard = heard
        self._last_my_position = my_position
        if not self._table_ready:
            return  # painted by `on_mount`
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
        if self._show_radar:
            self._refresh_radar()

    @on(Button.Pressed, "#heard-radar")
    def _toggle_radar(self) -> None:
        """Switch between the detailed list and the compact receive-only view."""
        self._show_radar = not self._show_radar
        table = self.query_one("#heard-table", DataTable)
        radar = self.query_one("#heard-radar-view", Static)
        button = self.query_one("#heard-radar", Button)
        table.display = not self._show_radar
        radar.display = self._show_radar
        button.label = "Show list" if self._show_radar else "Show radar"
        if self._show_radar:
            self._refresh_radar()

    def _refresh_radar(self) -> None:
        if self._last_heard is None:
            return
        radar = self.query_one("#heard-radar-view", Static)
        # Measure the pane rather than the Static: a newly revealed Static
        # initially sizes itself to its old content, which would otherwise
        # keep the radar at its narrow minimum on a wide terminal.
        width = min(31, max(21, (self.size.width or 31) - 4))
        radar.update(render_radar(self._last_heard.entries(), self._last_my_position, width=width))

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
