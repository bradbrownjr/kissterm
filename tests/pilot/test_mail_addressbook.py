"""Ctrl+G on the Mail, Bulletins and Files tabs: the Address Book slides in
beside the message list, to pick a BBS and dial it (operator, 2026-09-25).

`isolate()` runs FIRST -- see tests/pilot/test_app_mounts.py.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402
from textual.widgets import DataTable  # noqa: E402

from kissterm.addressbook import AddressBook  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.addressbook_pane import AddressBookPane  # noqa: E402
from kissterm.ui.app import KissTermApp  # noqa: E402
from kissterm.ui.mail_pane import MessageBrowser, MessageList  # noqa: E402
from kissterm.ui.terminal_pane import TerminalPane  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402
from tests.pilot._wait import wait_for  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")


async def _app(tmp_path):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = Config(mycall=str(MYCALL), start_tab="mail")
    config.tx_armed_at_start = True
    station = AX25Station(MYCALL, ta, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    app = KissTermApp(config, station)
    app.addressbook = AddressBook(tmp_path / "addressbook.json")
    app.addressbook.record_attempt("WS1EC-2")
    return app, station, ta


def _browser_book(app, tab: str) -> AddressBookPane:
    return app.query_one(f"#{tab}-browser", MessageBrowser).query_one(AddressBookPane)


@pytest.mark.asyncio
@pytest.mark.parametrize("tab", ["mail", "bulletins", "files"])
async def test_ctrl_g_opens_and_closes_the_addressbook_on_a_mail_tab(tmp_path, tab):
    app, station, _ta = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_show_tab(tab)
        await pilot.pause()
        browser = app.query_one(f"#{tab}-browser", MessageBrowser)
        column = browser.query_one(".mail-addressbook-column")
        assert not column.display  # never opens by itself here
        browser.query_one(MessageList).focus()
        await pilot.pause()
        await pilot.press("ctrl+g")
        await wait_for(lambda: bool(browser.query(AddressBookPane)), "the Address Book")
        await pilot.pause()
        pane = _browser_book(app, tab)
        table = pane.query_one("#addressbook-table", DataTable)
        assert column.display and table.row_count == 1 and app.focused is table
        assert column.region.width > 0 and browser.query_one(".mail-right").region.width > 0
        # Stations only: the NET/ROM claims stay on the Terminal tab.
        assert not pane.query_one("#known-nodes-table").display
        await pilot.press("ctrl+g")
        await pilot.pause()
        assert not column.display and isinstance(app.focused, MessageList)
    station.close()


@pytest.mark.asyncio
async def test_escape_closes_it_and_the_terminal_copy_is_still_the_apps_first(tmp_path):
    app, station, _ta = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        browser = app.query_one("#mail-browser", MessageBrowser)
        browser.toggle_addressbook()
        await wait_for(lambda: bool(browser.query(AddressBookPane)), "the Address Book")
        await pilot.pause()
        # Terminal's own lookups stay scoped to its copy.
        terminal = app.query_one(TerminalPane).query_one(AddressBookPane)
        assert terminal.query_ancestor("#terminal-addressbook-column")
        await pilot.press("escape")
        await pilot.pause()
        assert not browser.query_one(".mail-addressbook-column").display
    station.close()


@pytest.mark.asyncio
async def test_an_edit_in_one_copy_shows_in_the_other(tmp_path):
    app, station, _ta = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        browser = app.query_one("#mail-browser", MessageBrowser)
        browser.toggle_addressbook()
        await wait_for(lambda: bool(browser.query(AddressBookPane)), "the Address Book")
        await pilot.pause()
        pane = _browser_book(app, "mail")
        pane.query_one("#addressbook-table", DataTable).move_cursor(row=0)
        pane._forget_selected()
        await pilot.pause()
        terminal_table = app.query_one(TerminalPane).query_one("#addressbook-table", DataTable)
        assert terminal_table.row_count == 0
    station.close()


@pytest.mark.asyncio
async def test_dialing_from_the_mail_tab_connects_on_terminal(tmp_path):
    app, station, ta = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        browser = app.query_one("#mail-browser", MessageBrowser)
        browser.toggle_addressbook()
        await wait_for(lambda: bool(browser.query(AddressBookPane)), "the Address Book")
        await pilot.pause()
        pane = _browser_book(app, "mail")
        pane.query_one("#addressbook-table", DataTable).move_cursor(row=0)
        await pilot.pause()
        pane._connect_selected()
        await wait_for(lambda: bool(ta.sent), "a SABM")
        await pilot.pause()
        assert app.addressbook.entries[0].attempts == 2
        assert not browser.query_one(".mail-addressbook-column").display
        await asyncio.sleep(0.05)
        await pilot.pause()
        assert app.query_one("#main-tabs").active == "terminal"
    station.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(120, 32), (80, 24)])
async def test_the_folder_tree_keeps_its_width_and_the_list_gives_way(tmp_path, size):
    """The split is of what is right of the tree (`MessageBrowser.on_resize`):
    with the whole tab split, a 120-column screen left the message list
    about 20 columns and an 80-column one about 12 (2026-09-25)."""
    app, station, _ta = await _app(tmp_path)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        browser = app.query_one("#mail-browser", MessageBrowser)
        browser.toggle_addressbook()
        await wait_for(lambda: bool(browser.query(AddressBookPane)), "the Address Book")
        await pilot.pause()
        tree = browser.query_one(".mail-tree").region.width
        right = browser.query_one(".mail-right")
        book = browser.query_one(".mail-addressbook-column").region.width
        assert tree == 28
        if size[0] >= 120:
            assert right.region.width >= 40 and book >= 40
        else:  # no room for both: the Address Book takes the list's place
            assert not right.display and book >= 40
    station.close()
