"""The map's pieces with no UI: the shipped outlines, the projection,
the object store, and what the core hands a map (`Aprs.map_points`): this station, heard stations with a position, live
objects with coordinates, a killed object gone."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm import aprs  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.core import Core  # noqa: E402
from kissterm.geo import basemap, placemarks, project  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

# Portland, Maine, and Waterboro, about 20 miles west-southwest of it.
PORTLAND = (43.6591, -70.2568)
WATERBORO = (43.5354, -70.7153)


def test_a_station_is_described_as_the_heard_pane_does():
    line = project.describe(*PORTLAND, *WATERBORO)
    assert line.startswith("24.") and line.endswith("\N{DEGREE SIGN} WSW")
    assert " mi 250" in line


def test_a_view_round_trips_and_fits_its_points():
    view = project.View.fit([PORTLAND, WATERBORO], 400, 300)
    for lat, lon in (PORTLAND, WATERBORO):
        x, y = view.to_screen(lat, lon)
        assert 0 < x < 400 and 0 < y < 300
        back = view.to_map(x, y)
        assert back == pytest.approx((lat, lon))
    # North is up, east is right.
    px, py = view.to_screen(*PORTLAND)
    wx, wy = view.to_screen(*WATERBORO)
    assert px > wx and py < wy
    west, south, east, north = view.bounds()
    assert west < WATERBORO[1] < PORTLAND[1] < east
    assert south < WATERBORO[0] < PORTLAND[0] < north
    span = view.span
    view.zoom(2)
    assert view.span == pytest.approx(span / 2)
    lon = view.lon
    view.pan(100, 0)  # dragging right shows what is to the west
    assert view.lon < lon


def test_a_lone_point_or_none_still_gets_a_view():
    one = project.View.fit([PORTLAND], 400, 300)
    assert one.span >= 0.5
    assert project.View.fit([], 400, 300).span > 10


def test_the_shipped_outlines_cover_maine_and_detail_only_when_zoomed():
    wide = basemap.lines_in(-130, 20, -60, 55)
    assert {layer for layer, _ in wide} >= {"coast", "country", "state"}
    assert "county" not in {layer for layer, _ in wide}
    near = {layer for layer, _ in basemap.lines_in(-71.5, 43, -69.5, 44.5)}
    assert {"county", "road", "coast", "state"} <= near
    # Nothing in the middle of the South Pacific but maybe a coastline.
    assert not [x for x in basemap.lines_in(-140, -40, -139, -39) if x[0] == "road"]
    for _layer, points in basemap.lines_in(-71.5, 43, -69.5, 44.5)[:50]:
        assert len(points) % 2 == 0 and len(points) >= 4
        assert all(-180 <= v <= 180 for v in points[0::2])
        assert all(-90 <= v <= 90 for v in points[1::2])


def test_a_killed_object_goes_and_objects_without_coordinates_never_arrive():
    store = placemarks.Placemarks()
    store.object("FIRE", "W1AW", True, 43.6, -70.3, comment="brush fire")
    store.object("NOWHERE", "W1AW", True)
    assert list(store.objects) == ["FIRE"]
    store.object("fire ", "N1XYZ", False)
    assert store.objects == {}


def test_objects_are_capped_oldest_first(monkeypatch):
    monkeypatch.setattr(placemarks, "MAX_OBJECTS", 3)
    store = placemarks.Placemarks()
    for name in "ABCD":
        store.object(name, "W1AW", True, 43.0, -70.0)
    store.object("B", "W1AW", True, 43.1, -70.0)  # updated: now the newest
    assert list(store.objects) == ["C", "D", "B"]


MYCALL = AX25Address.parse("N1ABC-1")
PEER = AX25Address.parse("W1AW-9")


async def _core(**aprs_config):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    station = AX25Station(MYCALL, ta, LinkParams())
    config = Config(mycall=str(MYCALL), log_sessions=False)
    for name, value in aprs_config.items():
        setattr(config.aprs, name, value)
    core = Core(config, station)
    core.attach_station()
    return core, station


async def _hear(core, payload: bytes, source=PEER):
    frame = aprs.beacon_frame(source, AX25Address.parse("APRS"), (), payload)
    core.heard.record(frame)  # what the channel does first on the fan-out
    await core.aprs.on_frame(frame)


@pytest.mark.asyncio
async def test_map_points_has_me_stations_and_live_objects():
    core, station = await _core(latitude=WATERBORO[0], longitude=WATERBORO[1])
    await _hear(core, b"!4339.55N/07015.41W-Portland \x1b[31mhome")
    await _hear(core, b";SHELTER  *061830z4335.00N/07040.00WhRed Cross shelter")
    await _hear(core, b";GONE     *061830z4335.00N/07040.00Wh")
    await _hear(core, b";GONE     _061831z4335.00N/07040.00Wh")
    points = {p["name"]: p for p in core.aprs.map_points()}
    me = core.aprs.map_points()[0]
    assert me["kind"] == "me" and me["lat"] == pytest.approx(WATERBORO[0])
    peer = points[str(PEER)]
    assert peer["kind"] == "station" and peer["symbol"] == "/-"
    assert peer["symbol_name"]
    assert "\x1b" not in peer["comment"] and "home" in peer["comment"]
    assert peer["where"].endswith(("ENE", " NE"))
    shelter = points["SHELTER"]
    assert shelter["kind"] == "object" and shelter["by"] == str(PEER)
    assert shelter["comment"] == "Red Cross shelter"
    assert "GONE" not in points
    station.close()


@pytest.mark.asyncio
async def test_no_position_of_my_own_means_no_me_and_no_distances():
    core, station = await _core()
    await _hear(core, b"!4339.55N/07015.41W-")
    points = core.aprs.map_points()
    assert [p["kind"] for p in points] == ["station"]
    assert "where" not in points[0]
    station.close()


def test_geo_never_reaches_into_a_ui_or_the_station():
    """The phone client imports kissterm.geo (client/AGENTS.md): it must
    run with no station, Textual or Flet in it."""
    import ast
    from pathlib import Path

    import kissterm.geo

    banned = ("kissterm.core", "kissterm.ui", "kissterm.serve", "kissterm.transport",
              "kissterm.ax25", "kissterm.client", "textual", "flet")
    root = Path(kissterm.geo.__file__).parent
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.ImportFrom):
                name = node.module or ""
                if node.level:
                    name = "kissterm." + name if node.level == 2 else "kissterm.geo." + name
            elif isinstance(node, ast.Import):
                name = node.names[0].name
            else:
                continue
            assert not name.startswith(banned), f"{path.name} imports {name}"
