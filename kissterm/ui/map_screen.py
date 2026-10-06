"""APRS > Map (F10, or Ctrl+P): heard stations with a position, objects
and items with coordinates, and this station, on an offline map drawn in
braille dots (operator, 2026-10-06: "a map of heard stations that have
coordinates and objects received ... Basic offline map if possible";
"Braille-dot map" for the terminal, the phone's Map in parity).

What it shows is the core's (`Aprs.map_points`), the same list the
phone's map reads; the outlines are `kissterm.geo`'s, shipped with
kissterm, so nothing is fetched. Counties, roads, rivers, lakes and the
detailed coast appear once zoomed in (`basemap.DETAIL_SPAN`).

**Keys** (DESIGN.md section 5): the list below the map has focus, so its
plain letters are the map's -- I zooms in, O out, F shows everything,
Enter centres the highlighted point -- and the point under the cursor is
marked on the map. Tab moves to the map, where the arrows pan and PgUp
and PgDn zoom; the mouse wheel zooms and a click centres. Esc closes.
**Nothing here transmits**; the list re-reads the station every few
seconds while open.

**A position is a claim**, as the Heard pane says: the list reads
"reported", never "is at".
"""

from __future__ import annotations

import time
from collections.abc import Callable

from rich.style import Style
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.color import Color
from textual.containers import Horizontal, Vertical
from textual.events import Click, MouseScrollDown, MouseScrollUp, Resize
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Footer, Label, Static

from ..geo import braille, project, render

#: Each kind's marker on the map and in the list's first column.
MARKERS = {"me": "@", "station": "*", "object": "+", "item": "+"}
#: The map's fixed legend (DESIGN.md section 2), the phone's too.
LEGEND = {"water": "#3B8EDB", "road": "#D99A2B", "object": "#E0565B"}
#: How often the open map re-reads the station, in seconds.
REFRESH_SECONDS = 5.0


def ago(when: float, now: float | None = None) -> str:
    seconds = max(0, (now or time.time()) - when)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    return f"{int(seconds // 86400)} d ago"


def draw(view: project.View, points: list[dict], selected: str | None, *,
         ascii_safe: bool = False, cols: int, rows: int) -> braille.Canvas:
    """The map in cells: outlines, then markers (this station's, the
    selected one's, stations', objects', in that order of who wins a
    cell), then names where they fit. `view` is in dots."""
    canvas = braille.Canvas(cols, rows, ascii_safe=ascii_safe)
    for layer, lines in render.screen_lines(view, step=1.0):
        for line in lines:
            canvas.polyline(line, layer)
    rank = {"me": 0, "station": 2, "object": 3, "item": 3}
    ordered = sorted(points, key=lambda p: 1 if p["name"] == selected
                     else rank.get(p.get("kind"), 2))
    placed = []
    for point in ordered:
        x, y = view.to_screen(point["lat"], point["lon"])
        col, row = int(x) // 2, int(y) // 4
        style = "selected" if point["name"] == selected else point.get("kind", "station")
        if canvas.write(col, row, MARKERS.get(point.get("kind"), "*"), style):
            placed.append((point, col, row))
    for point, col, row in placed:
        name = point["name"]
        style = "selected-label" if name == selected else "label"
        if not canvas.write(col + 1, row, name, style):
            canvas.write(col - len(name), row, name, style)
    return canvas


class _MapTable(DataTable):
    """The points, nearest first; its letters drive the map above."""

    BINDINGS = [
        Binding("enter", "centre", "Centre"),
        Binding("i", "zoom(2)", "Zoom in"),
        Binding("o", "zoom(0.5)", "Zoom out"),
        Binding("f", "fit", "Show everything"),
    ]

    def action_centre(self) -> None:
        self.screen.centre_selected()

    def action_zoom(self, factor: float) -> None:
        self.screen.zoom(factor)

    def action_fit(self) -> None:
        self.screen.fit()


class MapCanvas(Widget, can_focus=True):
    """The braille map. Arrows pan, PgUp and PgDn zoom, the wheel zooms,
    a click centres."""

    BINDINGS = [
        Binding("pageup", "zoom(2)", "Zoom in"),
        Binding("pagedown", "zoom(0.5)", "Zoom out"),
        Binding("left", "pan(1, 0)", "Pan", show=False),
        Binding("right", "pan(-1, 0)", "Pan", show=False),
        Binding("up", "pan(0, 1)", "Pan", show=False),
        Binding("down", "pan(0, -1)", "Pan", show=False),
    ]

    DEFAULT_CSS = "MapCanvas { height: 1fr; }"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.view: project.View | None = None
        self.points: list[dict] = []
        self.selected: str | None = None
        self.ascii_safe = False

    def on_resize(self, event: Resize) -> None:
        cols, rows = event.size.width, event.size.height
        if self.view is None:
            self.view = project.View(0, 0, 1, cols * 2, rows * 4)
            self.fit()
        else:
            self.view.width, self.view.height = cols * 2, rows * 4
        self.screen.show_scale()

    def fit(self) -> None:
        if self.view is not None:
            self.view = project.View.fit([(p["lat"], p["lon"]) for p in self.points],
                                         self.view.width, self.view.height)
            self.refresh()

    def action_zoom(self, factor: float) -> None:
        self.screen.zoom(factor)

    def action_pan(self, dx: int, dy: int) -> None:
        if self.view is not None:
            # A quarter of the map per press.
            self.view.pan(dx * self.view.width / 4, dy * self.view.height / 4)
            self.refresh()

    def on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        if self.view is not None:
            self.view.zoom_at(1.5, event.x * 2, event.y * 4)
            self.screen.show_scale()
            self.refresh()

    def on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        if self.view is not None:
            self.view.zoom_at(1 / 1.5, event.x * 2, event.y * 4)
            self.screen.show_scale()
            self.refresh()

    def on_click(self, event: Click) -> None:
        if self.view is not None:
            self.view.pan(self.view.width / 2 - event.x * 2, self.view.height / 2 - event.y * 4)
            self.refresh()

    def _styles(self) -> dict[str, Style]:
        css = self.app.get_css_variables()
        background = Color.parse(css.get("background", "#121212"))

        def colour(name: str, fallback: str, fade: float = 0.0) -> str:
            try:
                value = Color.parse(css.get(name) or fallback)
            except Exception:
                value = Color.parse(fallback)
            return value.blend(background, fade).hex if fade else value.hex

        # The legend is fixed, as on a paper map (DESIGN.md section 2): a
        # theme's primary may be purple, and $warning or $error would say
        # "something is wrong". The rest follows the theme.
        water = LEGEND["water"]
        return {
            "lake": Style(color=water), "river": Style(color=water),
            "coast": Style(color=water),
            "county": Style(color=colour("foreground", "#E0E0E0", 0.65)),
            "state": Style(color=colour("foreground", "#E0E0E0", 0.35)),
            "country": Style(color=colour("foreground", "#E0E0E0")),
            "road": Style(color=LEGEND["road"]),
            "me": Style(color=colour("accent", "#FEA62B"), bold=True),
            "station": Style(color=colour("primary", "#0178D4"), bold=True),
            "object": Style(color=LEGEND["object"], bold=True),
            "item": Style(color=LEGEND["object"], bold=True),
            "selected": Style(reverse=True, bold=True),
            "selected-label": Style(reverse=True),
            "label": Style(color=colour("foreground", "#E0E0E0")),
        }

    def render(self) -> Text:
        if self.view is None or not self.size.width:
            return Text("")
        canvas = draw(self.view, self.points, self.selected, ascii_safe=self.ascii_safe,
                      cols=self.size.width, rows=self.size.height)
        styles = self._styles()
        out = Text(no_wrap=True, overflow="crop")
        for r, row in enumerate(canvas.cells()):
            if r:
                out.append("\n")
            run, key = "", None
            for char, style in row:
                if style != key and run:
                    out.append(run, styles.get(key or "", None))
                    run = ""
                key = style
                run += char
            if run:
                out.append(run, styles.get(key or "", None))
        return out


class MapScreen(ModalScreen[None]):
    """The map above, the list of what is on it below."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Close")]

    def __init__(self, points: Callable[[], list[dict]], *, ascii_safe: bool = False) -> None:
        super().__init__()
        self._source = points
        self._ascii_safe = ascii_safe
        self._rows: list[dict] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="map-box"):
            with Horizontal(id="map-heading"):
                yield Label("APRS map", id="map-title")
                yield Static("", id="map-caption")
            canvas = MapCanvas(id="map-canvas")
            canvas.ascii_safe = self._ascii_safe
            yield canvas
            yield _MapTable(id="map-table", cursor_type="row", zebra_stripes=True)
            with Horizontal(id="connect-buttons"):
                yield Button("Zoom in", id="map-zoom-in")
                yield Button("Zoom out", id="map-zoom-out")
                yield Button("Show everything", id="map-fit")
                yield Button("Close", id="map-close")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(_MapTable)
        table.add_columns("", "Name", "Where (reported)", "Heard", "Comment")
        self.reload()
        table.focus()
        self.set_interval(REFRESH_SECONDS, self.reload)

    # -- data ----------------------------------------------------------------
    def reload(self) -> None:
        canvas = self.query_one(MapCanvas)
        first = not canvas.points
        points = self._source()
        canvas.points = points
        others = [p for p in points if p.get("kind") != "me"]
        stations = sum(1 for p in others if p.get("kind") == "station")
        objects = len(others) - stations
        self._counts = (f"{stations} station{'s' * (stations != 1)}, "
                        f"{objects} object{'s' * (objects != 1)}")
        self._fill(points)
        if first and points:
            canvas.fit()
        self.show_scale()
        canvas.refresh()

    def _fill(self, points: list[dict]) -> None:
        table = self.query_one(_MapTable)
        keep = self._rows[table.cursor_row]["name"] if self._rows and table.row_count else None
        # Nearest first when this station's position is known; else newest.
        def distance(p: dict) -> float:
            try:
                return float((p.get("where") or "").split()[0])
            except ValueError:
                return float("inf")
        me = [p for p in points if p.get("kind") == "me"]
        rest = sorted((p for p in points if p.get("kind") != "me"),
                      key=(distance if me else (lambda p: -p.get("when", 0))))
        self._rows = me + rest
        table.clear()
        for p in self._rows:
            kind = p.get("kind", "station")
            where = p.get("where") or ("here" if kind == "me" else "")
            heard = "" if kind == "me" else ago(p.get("when", 0))
            comment = p.get("comment", "")
            if p.get("by"):
                comment = f"by {p['by']}: {comment}" if comment else f"by {p['by']}"
            table.add_row(MARKERS.get(kind, "*"), p["name"], where, heard, comment)
        if keep is not None:
            for i, p in enumerate(self._rows):
                if p["name"] == keep:
                    table.move_cursor(row=i)
                    break

    # -- the map -------------------------------------------------------------
    def show_scale(self) -> None:
        canvas = self.query_one(MapCanvas)
        caption = getattr(self, "_counts", "")
        if canvas.view is not None:
            length, label = canvas.view.scale_bar(24.0)
            cells = max(2, round(length / 2))
            bar = "|" + "-" * (cells - 2) + "|"
            caption = f"{caption}    {bar} {label}"
        self.query_one("#map-caption", Static).update(caption)

    def zoom(self, factor: float) -> None:
        canvas = self.query_one(MapCanvas)
        if canvas.view is not None:
            canvas.view.zoom(factor)
            self.show_scale()
            canvas.refresh()

    def fit(self) -> None:
        self.query_one(MapCanvas).fit()
        self.show_scale()

    def centre_selected(self) -> None:
        canvas = self.query_one(MapCanvas)
        point = next((p for p in self._rows if p["name"] == canvas.selected), None)
        if canvas.view is not None and point is not None:
            canvas.view.lat, canvas.view.lon = point["lat"], point["lon"]
            canvas.refresh()

    @on(DataTable.RowHighlighted, "#map-table")
    def _highlighted(self, event: DataTable.RowHighlighted) -> None:
        canvas = self.query_one(MapCanvas)
        if 0 <= event.cursor_row < len(self._rows):
            canvas.selected = self._rows[event.cursor_row]["name"]
            canvas.refresh()

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "map-zoom-in":
                self.zoom(2)
            case "map-zoom-out":
                self.zoom(0.5)
            case "map-fit":
                self.fit()
            case "map-close":
                self.dismiss(None)
