"""Get mail (Mail tab, G) end to end: dial the Home BBS, collect, disconnect.

The BBS is a second `AX25Station` on the loopback answering the way
WS1EC-2's BPQMail did in the captures (`tests/unit/data/bpqmail/`).
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402

from kissterm.addressbook import AddressBook  # noqa: E402
from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.mail import MessageStore  # noqa: E402
from kissterm.mail.collect import BBS_INBOX  # noqa: E402
from kissterm.ui.mail_pane import FolderTree, MessageList  # noqa: E402
from kissterm.ui.terminal_pane import TerminalPane  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402
from tests.pilot._wait import wait_for  # noqa: E402

MYCALL = AX25Address.parse("KC1JMH")
BBS = AX25Address.parse("WS1EC-2")
FAST = LinkParams(t1=0.3, t2=0.05, t3=5.0)

GREETING = (
    b"[BPQ-6.0.23.1-B2FWIHJM$]\rHello Bradley. Welcome back to WS1EC-2 BBS.\r"
    b"You have 1 messages waiting for you.\rde WS1EC#>\r"
)
REPLIES = {
    "LM": b"2578   16-Sep PN      25 KC1JMH @WS1EC  WS1EC  Test message\rde WS1EC#>\r",
    "R 2578": (
        b"From: WS1EC\rTo: KC1JMH\rType/Status: PN\rDate/Time: 16-Sep 16:33Z\r"
        b"Bid: 2578_WS1EC\rTitle: Test message\r\r\rtest test\r\rde WS1EC\r"
        b"[End of Message #2578 from WS1EC]\rde WS1EC#>\r"
    ),
}


def _bpqmail(bbs: AX25Station, heard: list[str]) -> None:
    def _greet(link) -> None:
        def _answer(data: bytes) -> None:
            command = data.decode("latin-1").strip()
            heard.append(command)
            reply = REPLIES.get(command)
            if reply is not None:
                asyncio.get_event_loop().create_task(link.send(reply))

        link.on_data.append(_answer)

        async def _banner() -> None:
            await asyncio.sleep(0.15)
            await link.send(GREETING)

        asyncio.get_event_loop().create_task(_banner())

    bbs.on_incoming.append(_greet)


async def _app(tmp_path, route: str = "WS1EC-2"):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = Config(mycall=str(MYCALL))
    config.tx_armed_at_start = True
    config.slideouts_auto_open = False
    config.home_bbs.route = route
    station = AX25Station(MYCALL, ta, FAST)
    app = KissTermApp(config, station)
    app.addressbook = AddressBook(tmp_path / "addressbook.json")
    app.addressbook.record_attempt("WS1EC-2")
    app.mail_store = MessageStore(tmp_path / "mail")
    app.mail_store.ensure_default_tree()
    return app, station, tb


def _log_text(app) -> str:
    log = app.query_one(TerminalPane).query_one("#session-log")
    return "\n".join(str(line) for line in log.lines)


@pytest.mark.asyncio
async def test_g_dials_the_home_bbs_files_new_mail_and_disconnects(tmp_path):
    app, station, tb = await _app(tmp_path)
    bbs = AX25Station(BBS, tb, FAST)
    heard: list[str] = []
    _bpqmail(bbs, heard)
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_show_tab("mail")
        await pilot.pause()
        app.query_one("#mail-browser").query_one(MessageList).focus()
        await pilot.press("g")
        await pilot.pause()
        # The operator stays on Mail, told what is happening.
        assert app.query_one("#main-tabs").active == "mail"
        assert any("Connecting to WS1EC-2" in str(n.message) for n in app._notifications)
        await wait_for(lambda: app.mail_store.list(BBS_INBOX), "the message to be filed")
        assert app.query_one("#main-tabs").active == "mail"
        status = app.query_one("#mail-browser .mail-status")
        await wait_for(lambda: "1 new message" in str(status.render()), "the status line")
        link = station.link_to(BBS)
        await wait_for(lambda: not link.connected, "the disconnect")
        assert heard == ["LM", "R 2578"]
        [summary] = app.mail_store.list(BBS_INBOX)
        assert (summary.subject, summary.source) == ("Test message", "BBS WS1EC")
        text = _log_text(app)
        assert "*** Mail: Reading 1 of 1: #2578" in text, text
        assert "R 2578" in text
        app.action_show_tab("mail")
        await pilot.pause()
        # The Mail tab shows it without a manual refresh.
        assert app.query_one("#mail-browser").query_one(MessageList).row_count == 1

        # Again: nothing new, so only LM goes out. A real BBS greets every
        # caller; this one greets only a new link object, so drop the old.
        await wait_for(lambda: not app._collecting, "the first run to finish")
        bbs.links.clear()
        heard.clear()
        app.action_show_tab("mail")
        await pilot.pause()
        app.query_one("#mail-browser").query_one(MessageList).focus()
        await pilot.press("g")
        await wait_for(lambda: heard == ["LM"] and not station.link_to(BBS).connected,
                       "a second run that reads nothing")
    bbs.close()
    station.close()


@pytest.mark.asyncio
async def test_g_without_a_home_bbs_asks_for_the_entry_then_gets_mail(tmp_path):
    from kissterm.ui.dialogs import HomeBbsSetupScreen

    app, station, tb = await _app(tmp_path, route="")
    bbs = AX25Station(BBS, tb, FAST)
    heard: list[str] = []
    _bpqmail(bbs, heard)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()  # let startup finish before switching tabs
        app.action_show_tab("mail")
        await wait_for(lambda: isinstance(app.focused, (MessageList, FolderTree)),
                       "the Mail tab to take focus")
        await pilot.press("g")
        await wait_for(lambda: isinstance(app.screen, HomeBbsSetupScreen), "the setup dialog")
        assert not station.transport.sent  # nothing transmitted to ask
        await pilot.pause()
        await pilot.click("#connect-go")
        await wait_for(lambda: app.mail_store.list(BBS_INBOX), "the message to be filed")
        assert app.config.home_bbs.route == "WS1EC-2"
    bbs.close()
    station.close()


@pytest.mark.asyncio
async def test_g_with_an_empty_address_book_explains_and_sends_nothing(tmp_path):
    from kissterm.ui.dialogs import HomeBbsSetupScreen

    app, station, _tb = await _app(tmp_path, route="")
    app.addressbook = AddressBook(tmp_path / "empty.json")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()  # let startup finish before switching tabs
        app.action_show_tab("mail")
        await wait_for(lambda: isinstance(app.focused, (MessageList, FolderTree)),
                       "the Mail tab to take focus")
        await pilot.press("g")
        await wait_for(lambda: isinstance(app.screen, HomeBbsSetupScreen), "the setup dialog")
        assert "Address Book" in str(app.screen.query_one("#reminder-detail").render())
        await pilot.pause()
        await pilot.click("#connect-cancel")
        await pilot.pause()
        assert not isinstance(app.screen, HomeBbsSetupScreen)
        assert not station.transport.sent
    station.close()


@pytest.mark.asyncio
async def test_mail_opens_with_its_list_focused_and_g_in_the_footer(tmp_path):
    app, station, _tb = await _app(tmp_path)
    app.config.start_tab = "mail"
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.focused, MessageList)
        assert "g" in app.screen.active_bindings
        app.query_one("#mail-browser").query_one(FolderTree).focus()
        await pilot.pause()
        assert "g" in app.screen.active_bindings  # the tree too
        app.action_show_tab("bulletins")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.focused, MessageList)
        assert "g" not in app.screen.active_bindings  # Mail only
    station.close()


@pytest.mark.asyncio
async def test_the_launch_footer_shows_g_on_mail(tmp_path):
    from textual.widgets._footer import FooterKey

    from kissterm.ui.app import KissTermFooter

    app, station, _tb = await _app(tmp_path)
    app.config.start_tab = "mail"
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await wait_for(
            lambda: "get_mail" in [k.action for k in app.query_one(KissTermFooter).query(FooterKey)],
            "G in the footer at launch",
        )
    station.close()
