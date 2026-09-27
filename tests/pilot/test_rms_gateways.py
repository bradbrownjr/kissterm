"""F10 > Session > RMS gateways (`ui/gateways_screen.py`): the list from a
saved reply, nearest first; the one chosen becomes an Address Book contact
and the Winlink Dial. The live fetch needs a key kissterm does not have
yet, so Refresh is tested with `gateways.fetch` replaced."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm.addressbook import AddressBook  # noqa: E402
from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui import commands as cmdreg  # noqa: E402
from kissterm.ui.gateways_screen import RmsGatewaysScreen  # noqa: E402
from kissterm.winlink import gateways  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402
from tests.pilot._wait import wait_for  # noqa: E402
from tests.unit.test_winlink_gateways import SAMPLE  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")


async def _app(tmp_path, *, cached: bool = True, position=(43.54, -70.72)):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = Config(mycall=str(MYCALL))
    config.slideouts_auto_open = False
    if position:
        config.aprs.latitude, config.aprs.longitude = position
    app = KissTermApp(config, AX25Station(MYCALL, ta, LinkParams()))
    app.addressbook = AddressBook(tmp_path / "addressbook.json")
    cache = gateways.cache_path(tmp_path)
    if cached:
        gateways.save_cached(cache, SAMPLE)
    app._gateway_cache = lambda: cache
    return app, ta


def _command():
    return next(c for c in cmdreg.COMMANDS if c.action == "rms_gateways")


@pytest.mark.asyncio
async def test_without_a_key_or_a_list_the_menu_says_why(tmp_path):
    app, ta = await _app(tmp_path, cached=False)
    async with app.run_test(size=(100, 33)) as pilot:
        await pilot.pause()
        assert app.command_unavailable(_command()) == "needs an API key"
        app.push_screen(RmsGatewaysScreen(app._gateway_cache(), None, key=""))
        await pilot.pause()
        note = str(app.screen.query_one("#gateways-note").render())
        assert "waiting for its Winlink API key" in note
        assert app.screen.query_one("#gateways-refresh").disabled
        assert app.screen.query_one("#gateways-use").disabled
    await ta.close()


@pytest.mark.asyncio
async def test_a_saved_list_shows_packet_gateways_nearest_first(tmp_path):
    app, ta = await _app(tmp_path)
    async with app.run_test(size=(100, 33)) as pilot:
        await pilot.pause()
        assert app.command_unavailable(_command()) == ""
        app.action_rms_gateways()
        await wait_for(lambda: isinstance(app.screen, RmsGatewaysScreen), "the gateway list")
        await pilot.pause()
        table = app.screen.query_one("#gateways-table")
        rows = [table.get_row_at(i) for i in range(table.row_count)]
        assert [r[0] for r in rows] == ["N1ABC-10", "W1AW-10", "K1XYZ-10", "W9BAD-10"]
        assert rows[0][1] == "145.010 MHz" and rows[0][4].endswith(("N", "E", "S", "W", "NE", "NW", "SE", "SW",
                                                                     "NNE", "ENE", "ESE", "SSE", "SSW", "WSW",
                                                                     "WNW", "NNW"))
        assert "From winlink.org, fetched just now; 4 shown." in str(app.screen.query_one("#gateways-note").render())
        app.screen.query_one("#gateways-mode").value = "vara fm"
        await pilot.pause()
        assert [table.get_row_at(i)[0] for i in range(table.row_count)] == ["W1AW-10"]
        await pilot.press("escape")
    await ta.close()


@pytest.mark.asyncio
async def test_enter_makes_a_gateway_a_contact_and_the_winlink_dial(tmp_path):
    app, ta = await _app(tmp_path)
    async with app.run_test(size=(100, 33)) as pilot:
        await pilot.pause()
        app.action_rms_gateways()
        await wait_for(lambda: isinstance(app.screen, RmsGatewaysScreen), "the gateway list")
        await pilot.pause()
        await pilot.press("enter")
        await wait_for(lambda: app.config.winlink.route == "N1ABC-10", "the Winlink Dial to be set")
        entry = app.addressbook.find("N1ABC-10")
        assert entry is not None and entry.frequency == "145.010 MHz"
        assert entry.note == "Winlink RMS, Packet 1200, FN43"
        assert not ta.sent, "choosing a gateway transmits nothing"
        from kissterm.config import load_config

        assert load_config().winlink.route == "N1ABC-10"
    await ta.close()


@pytest.mark.asyncio
async def test_a_contact_already_there_keeps_its_route_and_login(tmp_path):
    app, ta = await _app(tmp_path)
    app.addressbook.upsert("N1ABC-10", hops="WS1EC-15", credential="mine", note="via the node")
    async with app.run_test(size=(100, 33)) as pilot:
        await pilot.pause()
        app.action_rms_gateways()
        await wait_for(lambda: isinstance(app.screen, RmsGatewaysScreen), "the gateway list")
        await pilot.pause()
        await pilot.click("#gateways-use")
        await wait_for(lambda: app.config.winlink.route == "N1ABC-10", "the Winlink Dial to be set")
        entry = app.addressbook.find("N1ABC-10")
        assert (entry.hops, entry.credential, entry.note) == ("WS1EC-15", "mine", "via the node")
    await ta.close()


@pytest.mark.asyncio
async def test_refresh_fetches_saves_and_shows(tmp_path, monkeypatch):
    app, ta = await _app(tmp_path, cached=False, position=None)
    calls = []
    monkeypatch.setattr(gateways, "fetch", lambda key: calls.append(key) or SAMPLE)
    async with app.run_test(size=(100, 33)) as pilot:
        await pilot.pause()
        app.push_screen(RmsGatewaysScreen(app._gateway_cache(), None, key="TESTKEY"))
        await pilot.pause()
        assert "Refresh fetches it from winlink.org" in str(app.screen.query_one("#gateways-note").render())
        await pilot.click("#gateways-refresh")
        table = app.screen.query_one("#gateways-table")
        await wait_for(lambda: table.row_count == 4, "the fetched list")
        assert calls == ["TESTKEY"]
        assert gateways.load_cached(app._gateway_cache())[0] == SAMPLE
        note = str(app.screen.query_one("#gateways-note").render())
        assert "Set your position in Settings > APRS" in note
    await ta.close()


@pytest.mark.asyncio
async def test_a_failed_refresh_keeps_the_list_and_says_why(tmp_path, monkeypatch):
    app, ta = await _app(tmp_path)

    def refuse(key):
        raise gateways.FetchError("winlink.org answered 403 Forbidden")

    monkeypatch.setattr(gateways, "fetch", refuse)
    async with app.run_test(size=(100, 33)) as pilot:
        await pilot.pause()
        app.push_screen(RmsGatewaysScreen(app._gateway_cache(), (43.54, -70.72), key="BAD"))
        await pilot.pause()
        await pilot.click("#gateways-refresh")
        note = app.screen.query_one("#gateways-note")
        await wait_for(lambda: "Not refreshed" in str(note.render()), "the refusal")
        assert "403 Forbidden" in str(note.render())
        assert app.screen.query_one("#gateways-table").row_count == 4
    await ta.close()


@pytest.mark.asyncio
async def test_the_list_fits_80x24(tmp_path):
    app, ta = await _app(tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.push_screen(RmsGatewaysScreen(app._gateway_cache(), (43.54, -70.72), key=""))
        await pilot.pause()
        for selector in ("#gateways-table", "#gateways-use", "#gateways-close", "#gateways-mode"):
            region = app.screen.query_one(selector).region
            assert region.height and region.bottom <= 24 and region.right <= 80, (selector, region)
    await ta.close()
