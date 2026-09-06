"""The Address Book pane (F5): its own tab, dialing, and management.

`isolate()` runs FIRST -- see tests/pilot/test_app_mounts.py's module
docstring for why.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402
from textual.widgets import DataTable, Input  # noqa: E402

from kissterm.addressbook import AddressBook  # noqa: E402
from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.addressbook_pane import AddressBookPane  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")


async def _app(config=None):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = config or Config(mycall=str(MYCALL))
    config.tx_armed_at_start = True
    station = AX25Station(MYCALL, ta, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    return KissTermApp(config, station), station, ta, tb


def _fresh_book(app, tmp_path) -> AddressBook:
    app.addressbook = AddressBook(tmp_path / "addressbook.json")
    return app.addressbook


async def _addressbook_tab(app, pilot):
    app.action_show_tab("addressbook")
    await pilot.pause()
    await asyncio.sleep(0.05)
    await pilot.pause()


@pytest.mark.asyncio
async def test_address_book_is_f5_and_settings_is_f6():
    app, station, ta, tb = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("f5")
        await pilot.pause()
        assert app.query_one("#main-tabs").active == "addressbook"
        await pilot.press("f6")
        await pilot.pause()
        assert app.query_one("#main-tabs").active == "settings"
    station.close()


@pytest.mark.asyncio
async def test_every_saved_station_appears_in_the_table(tmp_path):
    app, station, ta, tb = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        book = _fresh_book(app, tmp_path)
        book.record_attempt("WS1EC-7", script="CLYDE")
        book.record_attempt("W1LH-6", hops="N1QFY", credential="Personal BBS login")
        await _addressbook_tab(app, pilot)

        table = app.query_one("#addressbook-table", DataTable)
        targets = {str(table.get_cell_at((r, 0))) for r in range(table.row_count)}
        assert targets == {"WS1EC-7", "W1LH-6"}
    station.close()


@pytest.mark.asyncio
async def test_new_entry_via_the_dialog(tmp_path):
    app, station, ta, tb = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        _fresh_book(app, tmp_path)
        await _addressbook_tab(app, pilot)

        app.query_one(AddressBookPane)._new_entry()
        await pilot.pause()
        await asyncio.sleep(0.05)

        from kissterm.ui.dialogs import AddressBookEdit, AddressBookEntryScreen

        assert isinstance(app.screen, AddressBookEntryScreen), type(app.screen).__name__
        await app.screen.dismiss(
            AddressBookEdit(
                "W1LH-6",
                hops="N1QFY, AB1KI-15",
                frequency="146.520 MHz",
                connection_type="1200 AFSK",
            )
        )
        await pilot.pause()

        entry = app.addressbook.entries[0]
        assert entry.target == "W1LH-6"
        assert entry.hops == "N1QFY, AB1KI-15"
        assert entry.frequency == "146.520 MHz"
        assert entry.connection_type == "1200 AFSK"
        assert entry.attempts == 0, "creating an entry here is not an attempt to reach it"
    station.close()


@pytest.mark.asyncio
async def test_editing_without_renaming_preserves_counters(tmp_path):
    app, station, ta, tb = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        book = _fresh_book(app, tmp_path)
        book.record_attempt("WS1EC-7")
        book.record_connect("WS1EC-7")
        await _addressbook_tab(app, pilot)
        app.query_one(AddressBookPane).refresh_from(book)
        await pilot.pause()

        table = app.query_one("#addressbook-table", DataTable)
        table.move_cursor(row=0)
        await pilot.pause()

        app.query_one(AddressBookPane)._edit_selected()
        await pilot.pause()
        await asyncio.sleep(0.05)

        from kissterm.ui.dialogs import AddressBookEdit, AddressBookEntryScreen

        assert isinstance(app.screen, AddressBookEntryScreen)
        await app.screen.dismiss(AddressBookEdit("WS1EC-7", script="NEWSCRIPT"))
        await pilot.pause()

        entry = book.entries[0]
        assert entry.target == "WS1EC-7"
        assert entry.script == "NEWSCRIPT"
        assert entry.attempts == 1
        assert entry.connects == 1
    station.close()


@pytest.mark.asyncio
async def test_renaming_an_entry_does_not_leave_a_stale_duplicate(tmp_path):
    """`_touch` matches whole strings, so a rename is a different key to it.
    The rename starts fresh (a different string is a different entry
    everywhere else in `AddressBook` too) -- it just must not leave the old
    spelling behind as well. See `AddressBook.upsert`'s docstring."""
    app, station, ta, tb = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        book = _fresh_book(app, tmp_path)
        book.record_attempt("WS1EC-7")
        book.record_connect("WS1EC-7")
        await _addressbook_tab(app, pilot)
        app.query_one(AddressBookPane).refresh_from(book)
        await pilot.pause()

        table = app.query_one("#addressbook-table", DataTable)
        table.move_cursor(row=0)
        await pilot.pause()

        app.query_one(AddressBookPane)._edit_selected()
        await pilot.pause()
        await asyncio.sleep(0.05)

        from kissterm.ui.dialogs import AddressBookEdit, AddressBookEntryScreen

        assert isinstance(app.screen, AddressBookEntryScreen)
        await app.screen.dismiss(AddressBookEdit("WS1EC-7 via W1AW-1"))
        await pilot.pause()

        assert [e.target for e in book.entries] == ["WS1EC-7 via W1AW-1"]
    station.close()


@pytest.mark.asyncio
async def test_forgetting_an_entry(tmp_path):
    app, station, ta, tb = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        book = _fresh_book(app, tmp_path)
        book.record_attempt("Keep me")
        book.record_attempt("Drop me")
        await _addressbook_tab(app, pilot)
        app.query_one(AddressBookPane).refresh_from(book)
        await pilot.pause()

        table = app.query_one("#addressbook-table", DataTable)
        table.move_cursor(row=0)  # "Drop me" -- most recently touched
        await pilot.pause()

        app.query_one(AddressBookPane)._forget_selected()
        await pilot.pause()

        assert [e.target for e in book.entries] == ["Keep me"]
    station.close()


@pytest.mark.asyncio
async def test_insert_f2_and_delete_act_only_while_the_table_is_focused(tmp_path):
    """Bound on the table widget itself so Delete still deletes a character
    out of an Input on another tab, rather than forgetting a row on a tab
    that was not even open."""
    app, station, ta, tb = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        book = _fresh_book(app, tmp_path)
        book.record_attempt("WS1EC-7")
        await _addressbook_tab(app, pilot)
        app.query_one(AddressBookPane).refresh_from(book)
        await pilot.pause()

        app.action_show_tab("terminal")
        await pilot.pause()
        app.query_one("#session-input", Input).focus()
        await pilot.pause()

        await pilot.press("delete")
        await pilot.pause()

        assert [e.target for e in book.entries] == ["WS1EC-7"], (
            "Delete on another tab's Input forgot an address-book row"
        )
    station.close()


@pytest.mark.asyncio
async def test_connect_button_dials_the_selected_station(tmp_path):
    app, station, ta, tb = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        book = _fresh_book(app, tmp_path)
        book.record_attempt("WS1EC-7")
        await _addressbook_tab(app, pilot)
        app.query_one(AddressBookPane).refresh_from(book)
        await pilot.pause()

        table = app.query_one("#addressbook-table", DataTable)
        table.move_cursor(row=0)
        await pilot.pause()

        await pilot.click("#addressbook-connect")
        await pilot.pause()
        await asyncio.sleep(0.5)  # loopback has no answering peer -- attempt only

        assert book.entries[0].attempts == 2, "dialing did not record as an attempt"
        # Some SABMs actually went out -- a real connect attempt, not a no-op.
        assert ta.sent, "dialing from the pane never transmitted anything"
    station.close()
