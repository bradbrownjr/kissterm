"""The APRS pane's (F4) contact list: CRUD only -- no sending yet.

Same shape as `test_addressbook_pane.py`, which this deliberately mirrors:
a real mounted app, a real dialog dismissed with a real result, checked
against `Config.aprs_contacts` -- never a mocked dialog.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402
from textual.widgets import DataTable, Select  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.aprs_pane import AprsPane  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")


async def _app(config=None):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = config or Config(mycall=str(MYCALL))
    config.tx_armed_at_start = True
    station = AX25Station(MYCALL, ta, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    return KissTermApp(config, station), station


async def _aprs_tab(app, pilot):
    app.action_show_tab("aprs")
    await pilot.pause()
    await asyncio.sleep(0.05)
    await pilot.pause()


@pytest.mark.asyncio
async def test_aprs_is_f4():
    app, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("f4")
        await pilot.pause()
        assert app.query_one("#main-tabs").active == "aprs"
    station.close()


@pytest.mark.asyncio
async def test_every_configured_contact_appears_in_the_table():
    config = Config(
        mycall=str(MYCALL),
        aprs_contacts=[
            {"name": "Jim", "callsign": "K1ABC-9", "service": "station"},
            {"name": "Mom", "callsign": "SMSGTE", "service": "sms", "detail": "5551234567"},
        ],
    )
    app, station = await _app(config)
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        table = app.query_one("#aprs-contact-table", DataTable)
        names = {str(table.get_cell_at((r, 0))) for r in range(table.row_count)}
        assert names == {"Jim", "Mom"}
    station.close()


@pytest.mark.asyncio
async def test_new_contact_via_the_dialog():
    app, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)

        app.query_one(AprsPane)._new_contact()
        await pilot.pause()
        await asyncio.sleep(0.05)

        from kissterm.aprs_contacts import Contact
        from kissterm.ui.dialogs import AprsContactScreen

        assert isinstance(app.screen, AprsContactScreen), type(app.screen).__name__
        await app.screen.dismiss(
            Contact(name="Jim", callsign="K1ABC-9", service="station", detail="", notes="")
        )
        await pilot.pause()

        assert app.config.aprs_contacts == [
            {"name": "Jim", "callsign": "K1ABC-9", "service": "station", "detail": "", "notes": ""}
        ]
    station.close()


@pytest.mark.asyncio
async def test_service_select_shows_the_right_detail_hint():
    """Switching to SMS/Email re-labels the detail field's placeholder --
    it stays one Input, not three widgets swapped in and out."""
    app, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        app.query_one(AprsPane)._new_contact()
        await pilot.pause()
        await asyncio.sleep(0.05)

        from kissterm.ui.dialogs import AprsContactScreen
        from textual.widgets import Input

        assert isinstance(app.screen, AprsContactScreen)
        service = app.screen.query_one("#aprs-contact-service", Select)
        service.value = "sms"
        await pilot.pause()
        detail = app.screen.query_one("#aprs-contact-detail", Input)
        assert "phone" in detail.placeholder.lower()

        service.value = "email"
        await pilot.pause()
        assert "email" in detail.placeholder.lower()
        await app.screen.dismiss(None)
    station.close()


@pytest.mark.asyncio
async def test_an_sms_contact_without_a_phone_number_is_refused():
    app, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        app.query_one(AprsPane)._new_contact()
        await pilot.pause()
        await asyncio.sleep(0.05)

        from textual.widgets import Input, Button
        from kissterm.ui.dialogs import AprsContactScreen

        assert isinstance(app.screen, AprsContactScreen)
        app.screen.query_one("#aprs-contact-name", Input).value = "Mom"
        app.screen.query_one("#aprs-contact-callsign", Input).value = "SMSGTE"
        app.screen.query_one("#aprs-contact-service", Select).value = "sms"
        await pilot.click("#aprs-contact-save")
        await pilot.pause()

        assert isinstance(app.screen, AprsContactScreen), "an incomplete SMS contact was saved"
        assert app.config.aprs_contacts == []
    station.close()


@pytest.mark.asyncio
async def test_editing_a_contact_updates_it_in_place():
    config = Config(
        mycall=str(MYCALL),
        aprs_contacts=[{"name": "Jim", "callsign": "K1ABC-9", "service": "station"}],
    )
    app, station = await _app(config)
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        table = app.query_one("#aprs-contact-table", DataTable)
        table.move_cursor(row=0)
        await pilot.pause()

        app.query_one(AprsPane)._edit_selected()
        await pilot.pause()
        await asyncio.sleep(0.05)

        from kissterm.aprs_contacts import Contact
        from kissterm.ui.dialogs import AprsContactScreen

        assert isinstance(app.screen, AprsContactScreen)
        await app.screen.dismiss(
            Contact(name="Jim W1ABC", callsign="K1ABC-9", service="station", detail="", notes="")
        )
        await pilot.pause()

        assert len(app.config.aprs_contacts) == 1
        assert app.config.aprs_contacts[0]["name"] == "Jim W1ABC"
    station.close()


@pytest.mark.asyncio
async def test_forgetting_a_contact():
    config = Config(
        mycall=str(MYCALL),
        aprs_contacts=[
            {"name": "Keep me", "callsign": "K1ABC", "service": "station"},
            {"name": "Drop me", "callsign": "K1XYZ", "service": "station"},
        ],
    )
    app, station = await _app(config)
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        table = app.query_one("#aprs-contact-table", DataTable)
        table.move_cursor(row=1)
        await pilot.pause()

        app.query_one(AprsPane)._forget_selected()
        await pilot.pause()

        assert [c["name"] for c in app.config.aprs_contacts] == ["Keep me"]
    station.close()


@pytest.mark.asyncio
async def test_selecting_a_contact_shows_its_message_history():
    config = Config(
        mycall=str(MYCALL),
        aprs_contacts=[{"name": "Jim", "callsign": "K1ABC-9", "service": "station"}],
    )
    app, station = await _app(config)
    async with app.run_test(size=(120, 40)) as pilot:
        app.aprs_conversations.record_incoming("K1ABC-9", "hello there", number="1")
        await _aprs_tab(app, pilot)
        table = app.query_one("#aprs-contact-table", DataTable)
        table.focus()
        table.move_cursor(row=0)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        from textual.widgets import RichLog

        log = app.query_one("#aprs-conversation-log", RichLog)
        text = "\n".join(str(line) for line in log.lines)
        assert "hello there" in text
    station.close()
