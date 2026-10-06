"""The APRS map on the phone: heard stations with a position, objects and
items with coordinates, and this station, over an offline map (operator,
2026-10-06: "a button next to Send Position on the APRS Messages to show
a map of heard stations ... Basic offline map if possible").

Opened by **Map** beside Position. What it shows is the station's
(`map_points`, `Aprs.map_points`); the outlines are `kissterm.geo`'s,
shipped with kissterm (Natural Earth), so nothing is fetched from the
Internet and the map works on a station with no connection but its
radio. Counties, roads, rivers, lakes and the detailed coast appear
once zoomed in (`basemap.DETAIL_SPAN`).

**Drawn on a canvas**: drag to pan, pinch or the mouse wheel to zoom,
+ and - for a hand without a second finger, the fit button to see every
point again. A tap on a point shows what the station said about it:
symbol, distance and bearing from here, when it was heard, its comment,
and who reported an object. **A position is a claim** (AGENTS.md: "A
callsign is a claim, not an identity"): the panel says "reported", never
"is at". Message opens the conversation.

**Placing an object** (operator, 2026-10-06): a long press opens the
object form at that spot (`aprs_object.py`); on one of this station's
objects the panel has Move (then a long press where it goes) and Kill.
The map itself never transmits: the form's Send and Kill each ask first.

Redrawn as the heard list changes (`stale heard`), at most every few
seconds, and only while the map is in front.
"""

from __future__ import annotations

import time

import flet as ft
import flet.canvas as cv

from ...geo import project, render
from .messages import ago

#: How each outline is drawn: (colour, width, filled). Water, roads and
#: object pins are a fixed legend, as on a paper map and the terminal's
#: (DESIGN.md section 2); the rest follows the theme.
STYLES = {
    "lake": (ft.Colors.with_opacity(0.35, "#3B8EDB"), 1.0, True),
    "river": (ft.Colors.with_opacity(0.7, "#3B8EDB"), 1.0, False),
    "coast": ("#3B8EDB", 1.2, False),
    "county": (ft.Colors.with_opacity(0.35, ft.Colors.OUTLINE), 0.8, False),
    "country": (ft.Colors.OUTLINE, 1.6, False),
    "state": (ft.Colors.OUTLINE, 1.1, False),
    "road": (ft.Colors.with_opacity(0.8, "#D99A2B"), 1.2, False),
}
#: Each kind of point: (colour, radius).
MARKS = {
    "me": (ft.Colors.PRIMARY, 6.0),
    "station": (ft.Colors.TERTIARY, 4.5),
    "object": ("#E0565B", 4.5),
    "item": ("#E0565B", 4.5),
}
KIND_NAMES = {"me": "This station", "station": "Station", "object": "Object",
              "item": "Item"}
#: Finger-sized: a tap within this many pixels picks the nearest point.
TAP_SLOP = 28.0
#: At most one redraw from new traffic per this many seconds.
REFRESH_SECONDS = 5.0


def shapes(view: project.View, points: list[dict], selected: str | None = None) -> list:
    """Everything on the canvas for this view: outlines, then points and
    their labels, then the scale bar. Pure, so a test can count it."""
    out: list = []
    for layer, lines in render.screen_lines(view, step=2.0):
        colour, width, filled = STYLES.get(layer, (ft.Colors.OUTLINE, 1.0, False))
        elements: list = []
        for line in lines:
            (x, y), rest = line[0], line[1:]
            elements.append(cv.Path.MoveTo(round(x, 1), round(y, 1)))
            elements += [cv.Path.LineTo(round(px, 1), round(py, 1)) for px, py in rest]
            if filled:
                elements.append(cv.Path.Close())
        out.append(cv.Path(elements, paint=ft.Paint(
            color=colour, stroke_width=width, anti_alias=True,
            style=ft.PaintingStyle.FILL if filled else ft.PaintingStyle.STROKE)))
    # Objects first, stations over them, this station on top; labels the
    # other way round, so this station's name is never the one crowded
    # out, and a label only where it does not sit on another (a busy
    # channel stays readable, and a tap still names any point).
    order = {"object": 0, "item": 0, "station": 1, "me": 2}
    shown = []
    for point in sorted(points, key=lambda p: order.get(p.get("kind"), 1)):
        x, y = view.to_screen(point["lat"], point["lon"])
        if -20 <= x <= view.width + 20 and -20 <= y <= view.height + 20:
            shown.append((point, x, y))
    for point, x, y in shown:
        colour, radius = MARKS.get(point.get("kind"), MARKS["station"])
        if point["name"] == selected:
            out.append(cv.Circle(x, y, radius + 5, paint=ft.Paint(
                color=colour, stroke_width=2, style=ft.PaintingStyle.STROKE)))
        out.append(cv.Circle(x, y, radius, paint=ft.Paint(color=colour)))
    taken: list[tuple[float, float]] = []
    for point, x, y in reversed(shown):
        if any(abs(x - tx) < 70 and abs(y - ty) < 16 for tx, ty in taken):
            continue
        taken.append((x, y))
        radius = MARKS.get(point.get("kind"), MARKS["station"])[1]
        clear = radius + (10 if point["name"] == selected else 3)  # past the ring
        out.append(cv.Text(x + clear, y - 8, point["name"], style=ft.TextStyle(
            size=11, color=ft.Colors.ON_SURFACE,
            weight=ft.FontWeight.BOLD if point.get("kind") == "me" else None)))
    length, label = view.scale_bar(min(120.0, view.width / 3))
    base = view.height - 14
    bar = ft.Paint(color=ft.Colors.ON_SURFACE, stroke_width=2)
    out += [cv.Line(12, base, 12 + length, base, paint=bar),
            cv.Line(12, base - 4, 12, base, paint=bar),
            cv.Line(12 + length, base - 4, 12 + length, base, paint=bar),
            cv.Text(12, base - 20, label, style=ft.TextStyle(size=11, color=ft.Colors.ON_SURFACE))]
    return out


def nearest(view: project.View, points: list[dict], x: float, y: float) -> dict | None:
    """The point drawn nearest (x, y), if one is within `TAP_SLOP`."""
    best, best_d = None, TAP_SLOP * TAP_SLOP
    for point in points:
        px, py = view.to_screen(point["lat"], point["lon"])
        d = (px - x) ** 2 + (py - y) ** 2
        if d <= best_d:
            best, best_d = point, d
    return best


def details(point: dict, now: float | None = None) -> list[str]:
    """The lines the panel shows under a point's name."""
    kind = KIND_NAMES.get(point.get("kind"), "Station")
    symbol = point.get("symbol_name") or ""
    lines = [f"{kind}{', ' + symbol if symbol else ''}"]
    if point.get("where"):
        lines.append(f"Reported {point['where']} from here")
    if point.get("kind") != "me" and point.get("when"):
        heard = "heard" if point.get("kind") == "station" else "reported"
        lines.append(f"Last {heard} {ago(point['when'], now)}"
                     f"{'' if ago(point['when'], now) == 'just now' else ' ago'}")
    if point.get("mine"):
        lines.append("Yours: sent from this station")
    elif point.get("by"):
        lines.append(f"Reported by {point['by']}")
    if point.get("comment"):
        lines.append(point["comment"])
    return lines


class MapPage:
    """The map, as a page of `MessagesView` (its back arrow returns to the
    conversations)."""

    def __init__(self, view) -> None:
        self.view = view
        self.app = view.app
        self.points: list[dict] = []
        self.map: project.View | None = None
        self.selected: str | None = None
        self._loaded_at = 0.0
        self._pending = False
        self._fitted = False
        self._span_at_start = 0.0
        self.canvas = cv.Canvas(expand=True, on_resize=self._resized)
        self.counts = ft.Text("", size=12, color=ft.Colors.OUTLINE)
        self.info_name = ft.Text("", theme_style=ft.TextThemeStyle.TITLE_SMALL, expand=True)
        self.info_lines = ft.Text("", size=12, selectable=True)
        self.message = ft.TextButton(content="Message", icon=ft.Icons.CHAT_BUBBLE_OUTLINE,
                                     on_click=self._message)
        #: On one of this station's objects (`mine`): Move, then a long
        #: press where it goes; Kill, after asking.
        self.move = ft.TextButton(content="Move", icon=ft.Icons.OPEN_WITH, on_click=self._move)
        self.kill = ft.TextButton(content="Kill", icon=ft.Icons.DELETE_OUTLINE,
                                  on_click=self._kill)
        #: The name of the object being moved, while waiting for its place.
        self.moving: str | None = None
        self.banner_text = ft.Text("", expand=True)
        self.banner = ft.Container(
            visible=False, padding=ft.Padding.symmetric(horizontal=16, vertical=6),
            bgcolor=ft.Colors.SECONDARY_CONTAINER, content=ft.Row(controls=[
                self.banner_text,
                ft.TextButton(content="Cancel", on_click=self._cancel_move)]))
        self.info = ft.Container(
            visible=False, left=8, right=8, bottom=34, padding=ft.Padding.all(12),
            border_radius=12, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            content=ft.Column(tight=True, spacing=4, controls=[
                ft.Row(spacing=0, controls=[
                    self.info_name, self.message, self.move, self.kill,
                    ft.IconButton(icon=ft.Icons.CLOSE, tooltip="Close",
                                  on_click=self._unselect)]),
                self.info_lines]))
        #: Built once: the object form returns to this same page.
        self.root = self.control()

    def control(self) -> ft.Control:
        gestures = ft.GestureDetector(
            expand=True, content=self.canvas, on_tap_up=self._tapped,
            on_long_press_start=self._long_pressed,
            on_scale_start=self._scale_start, on_scale_update=self._scaled,
            on_scroll=self._scrolled)
        zoom = ft.Column(top=8, right=8, spacing=4, controls=[
            ft.FilledTonalIconButton(icon=ft.Icons.ADD, tooltip="Zoom in",
                                     on_click=lambda _e: self._zoom(2.0)),
            ft.FilledTonalIconButton(icon=ft.Icons.REMOVE, tooltip="Zoom out",
                                     on_click=lambda _e: self._zoom(0.5)),
            ft.FilledTonalIconButton(icon=ft.Icons.FIT_SCREEN, tooltip="Show everything",
                                     on_click=self._fit)])
        return ft.Column(expand=True, spacing=0, controls=[
            ft.Row(controls=[
                ft.IconButton(icon=ft.Icons.ARROW_BACK, tooltip="All messages",
                              on_click=self.view._back),
                ft.Text("Map", theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                ft.Container(expand=True), self.counts, ft.Container(width=12)]),
            self.banner,
            ft.Stack(expand=True, clip_behavior=ft.ClipBehavior.HARD_EDGE,
                     controls=[ft.Container(expand=True, left=0, top=0, right=0, bottom=0,
                                            bgcolor=ft.Colors.SURFACE, content=gestures),
                               zoom, self.info])])

    # -- data ----------------------------------------------------------------
    async def reload(self) -> None:
        self._loaded_at = time.monotonic()
        self.points = await self.app.command("map_points") or []
        kinds = [p.get("kind") for p in self.points]
        stations = kinds.count("station")
        objects = kinds.count("object") + kinds.count("item")
        self.counts.value = (f"{stations} station{'s' * (stations != 1)}, "
                             f"{objects} object{'s' * (objects != 1)}")
        if self.map is not None and not self._fitted and self.points:
            self._fit_points()  # sized before the points came
        self.draw()

    def stale(self) -> None:
        """The heard list changed: reload, but not more often than
        `REFRESH_SECONDS` (a busy channel would redraw constantly)."""
        if self._pending:
            return
        wait = REFRESH_SECONDS - (time.monotonic() - self._loaded_at)

        async def later() -> None:
            import asyncio

            if wait > 0:
                await asyncio.sleep(wait)
            self._pending = False
            await self.reload()

        self._pending = True
        self.app.page.run_task(later)

    # -- drawing -------------------------------------------------------------
    def _fit_points(self) -> None:
        self._fitted = bool(self.points)
        width, height = (self.map.width, self.map.height) if self.map else (400.0, 600.0)
        self.map = project.View.fit([(p["lat"], p["lon"]) for p in self.points], width, height)

    def draw(self) -> None:
        if self.map is None:
            return
        self.canvas.shapes = shapes(self.map, self.points, self.selected)
        self.app.page.update()

    def _resized(self, e) -> None:
        if not e.width or not e.height:
            return
        if self.map is None:
            self.map = project.View(0, 0, 1, e.width, e.height)
            self._fit_points()
        else:
            self.map.width, self.map.height = e.width, e.height
        self.draw()

    def _zoom(self, factor: float) -> None:
        if self.map is not None:
            self.map.zoom(factor)
            self.draw()

    def _fit(self, _e) -> None:
        self._fit_points()
        self.draw()

    # -- gestures ------------------------------------------------------------
    def _scale_start(self, _e) -> None:
        if self.map is not None:
            self._span_at_start = self.map.span

    def _scaled(self, e) -> None:
        if self.map is None:
            return
        if e.pointer_count >= 2 and e.scale and self._span_at_start:
            focal = e.local_focal_point
            factor = self.map.span / (self._span_at_start / e.scale)
            self.map.zoom_at(factor, focal.x, focal.y)
        delta = e.focal_point_delta
        if delta is not None:
            self.map.pan(delta.x, delta.y)
        self.draw()

    def _scrolled(self, e) -> None:
        if self.map is None or e.scroll_delta is None or not e.scroll_delta.y:
            return
        factor = 1.25 if e.scroll_delta.y < 0 else 0.8
        self.map.zoom_at(factor, e.local_position.x, e.local_position.y)
        self.draw()

    def _tapped(self, e) -> None:
        if self.map is None or e.local_position is None:
            return
        point = nearest(self.map, self.points, e.local_position.x, e.local_position.y)
        if point is None:
            self._unselect(None)
            return
        self.selected = point["name"]
        self.info_name.value = point["name"]
        self.info_lines.value = "\n".join(details(point))
        self.message.visible = point.get("kind") == "station"
        self.move.visible = self.kill.visible = bool(point.get("mine"))
        self.info.visible = True
        self.draw()

    async def _long_pressed(self, e) -> None:
        """A new object at this spot, or the one being moved, moved here:
        the form, filled in; only its Send transmits."""
        if self.map is None or e.local_position is None:
            return
        lat, lon = self.map.to_map(e.local_position.x, e.local_position.y)
        name, self.moving = self.moving or "", None
        self.banner.visible = False
        await self.view.open_object_form(lat, lon, name)

    def _move(self, _e) -> None:
        if not self.selected:
            return
        self.moving = self.selected
        self.banner_text.value = f"Long-press where {self.selected} goes."
        self.banner.visible = True
        self._unselect(None)

    def _cancel_move(self, _e) -> None:
        self.moving = None
        self.banner.visible = False
        self.app.page.update()

    async def _kill(self, _e) -> None:
        from .aprs_object import kill

        point = next((p for p in self.points if p["name"] == self.selected), None)
        if point is None:
            return

        async def done() -> None:
            self._unselect(None)
            await self.reload()

        await kill(self.app, point, done)

    def _unselect(self, _e) -> None:
        self.selected = None
        self.info.visible = False
        self.draw()

    async def _message(self, _e) -> None:
        if self.selected:
            await self.view.open(self.selected)
