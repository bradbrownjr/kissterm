"""F10 > APRS > Map (`ui/map_screen.py`): heard stations and objects with
a position on the braille map, nearest first in the list beneath it; the
list's letters zoom and fit, and the highlighted point is marked. Nothing
transmits (the loopback's peer hears nothing)."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm import aprs  # noqa: E402
from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui import commands as cmdreg  # noqa: E402
from kissterm.ui.map_screen import MapCanvas, MapScreen, draw  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402
from tests.pilot._wait import wait_for  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
HEARD = [("W1MRA-1", b"!4351.20N/07016.80W#W1MRA digi"),
         ("K1QRP-7", b"!4337.60N/07019.10W[hiking")]
OBJECT = b";SHELTER  *061830z4344.10N/07032.40WhShelter open"


async def _app():
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = Config(mycall=str(MYCALL))
    config.slideouts_auto_open = False
    config.aprs.latitude, config.aprs.longitude = 43.80, -70.42
    app = KissTermApp(config, AX25Station(MYCALL, ta, LinkParams()))
    return app, ta, tb


async def _hear(app, source: str, payload: bytes) -> None:
    frame = aprs.beacon_frame(AX25Address.parse(source), AX25Address.parse("APRS"), (), payload)
    app.core.heard.record(frame)
    await app.core.aprs.on_frame(frame)


def test_map_is_in_the_aprs_menu_with_no_key():
    command = next(c for c in cmdreg.COMMANDS if c.action == "aprs_map")
    assert (command.group, command.mnemonic, command.key) == ("APRS", "M", "")


@pytest.mark.asyncio
async def test_the_map_shows_what_was_heard_nearest_first_and_marks_the_cursor():
    app, ta, tb = await _app()
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.pause()
        for source, payload in HEARD:
            await _hear(app, source, payload)
        await _hear(app, "KC1XYZ-9", OBJECT)
        app.action_aprs_map()
        await wait_for(lambda: isinstance(app.screen, MapScreen), "the map")
        await pilot.pause()
        screen = app.screen
        table = screen.query_one("#map-table")
        names = [table.get_row_at(i)[1] for i in range(table.row_count)]
        assert names[0] == str(MYCALL)
        assert set(names[1:]) == {"W1MRA-1", "K1QRP-7", "SHELTER"}
        # Nearest first: the shelter is about 7 miles off, K1QRP-7 about 14.
        assert names.index("SHELTER") < names.index("K1QRP-7")
        caption = str(screen.query_one("#map-caption").render())
        assert "2 stations, 1 object" in caption and " mi" in caption
        canvas = screen.query_one(MapCanvas)
        drawn = str(canvas.render())
        assert "W1MRA-1" in drawn and "SHELTER" in drawn and "@" in drawn
        assert any(0x2800 < ord(c) <= 0x28FF for c in drawn), "no braille outlines"

        table.focus()
        await pilot.press("down")
        await pilot.pause()
        assert canvas.selected == names[1]
        span = canvas.view.span
        await pilot.press("i")
        assert canvas.view.span == pytest.approx(span / 2)
        await pilot.press("f")
        assert canvas.view.span == pytest.approx(span)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, MapScreen)
    assert ta.sent == [], "the map transmitted"
    await ta.close()
    await tb.close()


def test_ascii_safe_draws_dots_not_braille():
    from kissterm.geo.project import View

    points = [{"name": "W1AW", "lat": 43.66, "lon": -70.26, "kind": "station"}]
    view = View.fit([(43.66, -70.26), (43.8, -70.42)], 80, 80)
    canvas = draw(view, points, None, ascii_safe=True, cols=40, rows=20)
    text = "".join(c for row in canvas.cells() for c, _ in row)
    assert "W1AW" in text and "." in text
    assert not any(0x2800 <= ord(c) <= 0x28FF for c in text)


@pytest.mark.asyncio
async def test_insert_places_an_object_at_the_centre_and_delete_kills_only_yours():
    from kissterm.ui.dialogs import AprsObjectScreen

    app, ta, tb = await _app()
    async with app.run_test(size=(120, 44)) as pilot:
        await pilot.pause()
        await _hear(app, "KC1XYZ-9", OBJECT)
        app.action_aprs_map()
        await wait_for(lambda: isinstance(app.screen, MapScreen), "the map")
        await pilot.pause()
        screen = app.screen
        canvas = screen.query_one(MapCanvas)
        table = screen.query_one("#map-table")
        table.focus()
        # Someone else's object: no Move or Kill.
        row = [table.get_row_at(i)[1] for i in range(table.row_count)].index("SHELTER")
        table.move_cursor(row=row)
        await pilot.pause()
        assert not screen.selected_is_mine()
        await pilot.press("delete")
        await pilot.pause()
        assert isinstance(app.screen, MapScreen), "Delete opened a form for another's object"
        # Insert: the form, at the map's centre; Send is the only way out
        # that transmits.
        await pilot.press("insert")
        await wait_for(lambda: isinstance(app.screen, AprsObjectScreen), "the object form")
        await pilot.pause()
        form = app.screen
        assert float(form.query_one("#aprs-object-latitude").value) == pytest.approx(
            canvas.view.lat, abs=1e-4)
        assert ta.sent == [], "the form transmitted on opening"
        form.query_one("#aprs-object-name").value = "DRILL"
        await pilot.click("#aprs-object-send")
        await wait_for(lambda: isinstance(app.screen, MapScreen), "back on the map")
        await wait_for(lambda: ta.sent, "the object report")
        await pilot.pause()
        names = [table.get_row_at(i)[1] for i in range(table.row_count)]
        assert "DRILL" in names
        table.move_cursor(row=names.index("DRILL"))
        await pilot.pause()
        assert screen.selected_is_mine()
        await pilot.press("delete")
        await wait_for(lambda: isinstance(app.screen, AprsObjectScreen), "the kill form")
        await pilot.pause()
        assert app.screen.query_one("#aprs-object-alive").value == "killed"
        assert app.screen.query_one("#aprs-object-name").value == "DRILL"
        await pilot.press("escape")
        await pilot.pause()
    await ta.close()
    await tb.close()
