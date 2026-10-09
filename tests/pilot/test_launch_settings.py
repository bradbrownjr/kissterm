"""Settings > Radio: the Programs and Rigs lists and their dialogs (P3a M3)."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402
import sys  # noqa: E402

import pytest  # noqa: E402
from textual.widgets import Button, Checkbox, DataTable, Input, Select, SelectionList, Static  # noqa: E402

from kissterm.config import Config  # noqa: E402
from kissterm.ui.launch_screens import (  # noqa: E402
    ProgramEntryScreen,
    ProgramFileScreen,
    RigEntryScreen,
    RigModelScreen,
)
from kissterm.ui.settings_pane import SettingsPane  # noqa: E402
from tests.pilot._wait import wait_for  # noqa: E402
from tests.pilot.test_settings import MYCALL, _app, _settings_tab  # noqa: E402


async def _screen(app, cls):
    await wait_for(lambda: isinstance(app.screen, cls), cls.__name__)
    # The screen is current before its widgets are composed; a row's inputs
    # arrive after its buttons.
    ready = {ProgramEntryScreen: "#prog-save", RigEntryScreen: "#rig-save"}.get(cls)
    if ready:
        await wait_for(lambda: app.screen.query(ready) and app.screen.query("Input"),
                       f"{cls.__name__}'s fields")
        await asyncio.sleep(0.2)


@pytest.mark.asyncio
async def test_a_program_is_added_from_the_dialog_and_listed():
    app, station = await _app(Config(mycall=str(MYCALL)))
    async with app.run_test(size=(120, 50)) as pilot:
        await _settings_tab(app, pilot)
        app.query_one(SettingsPane)._edit_program(True)
        await _screen(app, ProgramEntryScreen)
        screen = app.screen
        screen.query_one("#prog-name", Input).value = "py"
        screen.query_one("#prog-path", Input).value = sys.executable
        screen.query_one("#prog-args", Input).value = "-c pass"
        await pilot.pause()
        await pilot.click("#prog-save")
        await wait_for(lambda: not isinstance(app.screen, ProgramEntryScreen), "the dialog to close")
        assert [p["name"] for p in app.config.programs] == ["py"]
        assert app.config.programs[0]["args"] == "-c pass"
        assert app.query_one("#set-program", Select).value == "py"
        detail = str(app.query_one("#settings-program-detail", Static).render())
        assert "not started by kissterm" in detail
    station.close()


@pytest.mark.asyncio
async def test_the_dialog_shows_the_cores_reason_and_stays_open():
    app, station = await _app(Config(mycall=str(MYCALL)))
    async with app.run_test(size=(120, 50)) as pilot:
        await _settings_tab(app, pilot)
        app.query_one(SettingsPane)._edit_program(True)
        await _screen(app, ProgramEntryScreen)
        app.screen.query_one("#prog-name", Input).value = "ghost"
        app.screen.query_one("#prog-path", Input).value = "/no/such/program"
        await pilot.pause()
        await pilot.click("#prog-save")
        await pilot.pause()
        assert isinstance(app.screen, ProgramEntryScreen)
        assert "not a file" in str(app.screen.query_one("#transport-error").render())
        assert app.config.programs == []
    station.close()


@pytest.mark.asyncio
async def test_choosing_a_preset_fills_its_path_and_arguments_only_when_untouched():
    app, station = await _app(Config(mycall=str(MYCALL)))
    async with app.run_test(size=(120, 50)) as pilot:
        await _settings_tab(app, pilot)
        app.query_one(SettingsPane)._edit_program(True)
        await _screen(app, ProgramEntryScreen)
        screen = app.screen
        screen.query_one("#prog-preset", Select).value = "mercury"
        await pilot.pause()
        assert screen.query_one("#prog-args", Input).value == "-p 8300"
        screen.query_one("#prog-args", Input).value = "-p 9000"
        screen.query_one("#prog-preset", Select).value = "direwolf"
        await pilot.pause()
        assert screen.query_one("#prog-args", Input).value == "-p 9000"  # typed, so kept
    station.close()


@pytest.mark.asyncio
async def test_the_file_browser_lists_programs_and_returns_the_choice(tmp_path):
    modem = tmp_path / "modem"
    modem.write_text("x")
    modem.chmod(0o755)
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    app, station = await _app(Config(mycall=str(MYCALL)))
    result = []
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(ProgramFileScreen(app.core.radio, str(tmp_path)), result.append)
        await _screen(app, ProgramFileScreen)
        await pilot.pause()
        table = app.screen.query_one("#program-file-table", DataTable)
        rows = [str(table.get_row_at(i)[0]) for i in range(table.row_count)]
        assert "sub/" in rows and "modem" in rows and "notes.txt" not in rows
        table.move_cursor(row=rows.index("modem"))
        await pilot.pause()
        await pilot.click("#program-file-choose")
        await wait_for(lambda: result, "the choice")
        assert result == [str(modem)]
    station.close()


@pytest.mark.asyncio
async def test_a_rig_is_saved_with_bands_and_the_model_picker_reads_hamlibs_list():
    app, station = await _app(Config(mycall=str(MYCALL)))
    async with app.run_test(size=(120, 60)) as pilot:
        async def models(path=""):
            return [{"model": 1035, "make": "Yaesu", "name": "FT-991A", "status": "Stable"},
                    {"model": 3073, "make": "Icom", "name": "IC-7300", "status": "Stable"}]

        app.core.radio.rig_models = models
        await _settings_tab(app, pilot)
        app.query_one(SettingsPane)._edit_rig(True)
        await _screen(app, RigEntryScreen)
        screen = app.screen
        screen.query_one("#rig-name", Input).value = "ft991a"
        await pilot.click("#rig-pick")
        await _screen(app, RigModelScreen)
        await pilot.pause()
        app.screen.query_one("#rig-model-filter", Input).value = "991"
        await pilot.pause()
        table = app.screen.query_one("#rig-model-table", DataTable)
        assert table.row_count == 1
        await pilot.click("#rig-model-choose")
        await _screen(app, RigEntryScreen)
        assert app.screen.query_one("#rig-model", Input).value == "1035"
        app.screen.query_one("#rig-bands", SelectionList).select("40m")
        await pilot.pause()
        await pilot.click("#rig-save")
        await wait_for(lambda: not isinstance(app.screen, RigEntryScreen), "the dialog to close")
        rig = app.config.rigs[0]
        assert (rig["name"], rig["model"], rig["tune_bands"], rig["swr_trip"]) == (
            "ft991a", 1035, ["40m"], 3.0)
        assert "tunes the ATU on: 40m" in str(app.query_one("#settings-rig-detail", Static).render())
    station.close()


@pytest.mark.asyncio
async def test_a_transport_form_can_name_a_program_and_a_rig():
    from kissterm.ui.dialogs import TransportEntryScreen

    config = Config(mycall=str(MYCALL))
    config.programs = [{"name": "py", "path": sys.executable}]
    config.rigs = [{"name": "ft991a", "model": 1035}]
    app, station = await _app(config)
    async with app.run_test(size=(120, 60)) as pilot:
        await _settings_tab(app, pilot)
        app.query_one(SettingsPane)._new_transport()
        await _screen(app, TransportEntryScreen)
        await pilot.pause()
        screen = app.screen
        screen.query_one("#transport-name", Input).value = "kiss"
        screen.query_one("#transport-kind", Select).value = "tcp"
        await wait_for(lambda: screen.query_one("#transport-field-host", Input), "the tcp fields")
        screen.query_one("#transport-field-host", Input).value = "127.0.0.1"
        screen.query_one("#transport-program", Select).value = "py"
        screen.query_one("#transport-rig", Select).value = "ft991a"
        screen.query_one("#transport-frequency", Input).value = "a home"
        await pilot.pause()
        screen.query_one("#transport-save", Button).press()
        await wait_for(lambda: "No frequency" in str(screen.query_one("#transport-error").render()),
                       "the refusal of a home that is no frequency")
        assert isinstance(app.screen, TransportEntryScreen)
        screen.query_one("#transport-frequency", Input).value = "145.050 FM"
        await pilot.pause()
        screen.query_one("#transport-save", Button).press()
        await wait_for(lambda: not isinstance(app.screen, TransportEntryScreen), "the dialog")
        entry = app.config.transports[0]
        assert entry["program"] == "py" and entry["rig"] == "ft991a"
        assert entry["frequency"] == "145.050 FM"
    station.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(80, 24), (100, 33)])
async def test_the_new_dialogs_keep_their_buttons_on_screen(size):
    from kissterm.ui.dialogs import TransportEntryScreen

    app, station = await _app(Config(mycall=str(MYCALL)))
    async with app.run_test(size=size) as pilot:
        await _settings_tab(app, pilot)
        for opener, cls, save in ((lambda: app.query_one(SettingsPane)._edit_program(True),
                                   ProgramEntryScreen, "#prog-save"),
                                  (lambda: app.query_one(SettingsPane)._edit_rig(True),
                                   RigEntryScreen, "#rig-save"),
                                  (lambda: app.query_one(SettingsPane)._new_transport(),
                                   TransportEntryScreen, "#transport-save")):
            opener()
            await _screen(app, cls)
            await pilot.pause()
            button = app.screen.query_one(save, Button)
            region, screen = button.region, app.screen.region
            assert 0 <= region.y and region.bottom <= screen.bottom, (cls.__name__, region, screen)
            assert region.right <= screen.right
            await app.screen.dismiss(None)
            await pilot.pause()
    station.close()
