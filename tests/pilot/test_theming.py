"""The app actually applies `Config.theme`, live, and never crashes on a bad one.

kissterm's colors were CSS variables (`$primary`, `$accent`, `$background`)
throughout `styles.py` before theming existed, which is what makes this
feature possible without touching a single style rule -- these tests prove
the wiring works end to end, not just that the catalog data is sound
(`tests/unit/test_themes.py` covers that).
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.settings_pane import SettingsPane, _widget_id  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")


async def _app(config=None):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = config or Config(mycall=str(MYCALL))
    station = AX25Station(MYCALL, ta, LinkParams())
    return KissTermApp(config, station), station


@pytest.mark.asyncio
async def test_configured_theme_is_active_before_the_first_frame():
    """Applied in __init__, not on_mount -- no flash to a default first."""
    app, station = await _app(Config(mycall=str(MYCALL), theme="dracula"))
    assert app.theme == "dracula", "theme must be set before run_test even starts"
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        assert app.theme == "dracula"
    station.close()


@pytest.mark.asyncio
async def test_default_config_uses_tokyo_night():
    app, station = await _app(Config(mycall=str(MYCALL)))
    assert app.theme == "tokyo-night"
    station.close()


@pytest.mark.asyncio
async def test_a_bad_theme_name_falls_back_and_does_not_crash():
    app, station = await _app(Config(mycall=str(MYCALL), theme="not-a-real-theme"))
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        assert app.theme == "tokyo-night", "should fall back to the default"
    station.close()


@pytest.mark.asyncio
async def test_custom_theme_is_registered_and_activated():
    cfg = Config(mycall=str(MYCALL), theme="custom")
    cfg.custom_theme.primary = "#ff00ff"
    cfg.custom_theme.dark = False
    app, station = await _app(cfg)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        assert app.theme == "custom"
        registered = app.get_theme("custom")
        assert registered is not None
        assert registered.primary == "#ff00ff"
        assert registered.dark is False
    station.close()


@pytest.mark.asyncio
async def test_changing_theme_in_settings_repaints_live():
    app, station = await _app(Config(mycall=str(MYCALL), theme="tokyo-night"))
    async with app.run_test(size=(120, 60)) as pilot:
        app.action_show_tab("settings")
        await pilot.pause()
        app.query_one(f"#{_widget_id('theme')}").value = "nord"
        app.query_one(SettingsPane)._save()
        await pilot.pause()
        assert app.theme == "nord"
        assert app.config.theme == "nord"
    station.close()


@pytest.mark.asyncio
async def test_reload_from_file_reapplies_the_theme():
    from kissterm.config import save_config

    cfg = Config(mycall=str(MYCALL), theme="tokyo-night")
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 60)) as pilot:
        on_disk = Config(mycall=str(MYCALL), theme="gruvbox")
        save_config(on_disk)

        app.action_show_tab("settings")
        await pilot.pause()
        app.query_one(SettingsPane)._reload()
        await pilot.pause()
        assert app.theme == "gruvbox"
    station.close()


@pytest.mark.asyncio
async def test_settings_pane_offers_every_catalog_choice():
    from kissterm.ui import themes as themes_mod

    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        app.action_show_tab("settings")
        await pilot.pause()
        select = app.query_one(f"#{_widget_id('theme')}")
        offered = {value for _prompt, value, *_ in select._options}
        assert offered == set(themes_mod.all_theme_ids())
    station.close()
