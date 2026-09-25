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
    # From send_sp_w1bkw.txt (2026-09-25).
    "SP W1BKW": b"Address @W1BKW.#OXFO.ME.USA.NOAM added from HomeBBS\rEnter Title (only):\r",
    "Breakfast": b"Enter Message Text (end with /ex or ctrl/z)\r",
    "/EX": b"Message: 2803 Bid:  2803_WS1EC Size: 12\rde WS1EC#>\r",
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
            # A message body arrives as several lines in one send.
            for command in data.decode("latin-1").split("\r")[:-1]:
                command = command.strip()
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


def _status_text(app) -> str:
    table = app.query_one("#status-bar").content
    return " ".join(str(cell) for column in table.columns for cell in column._cells)


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
        tree_region = app.query_one("#mail-browser").query_one(MessageList).region
        shown: list[str] = []
        real_status = app._mail_status

        def _record(phase: str) -> None:
            real_status(phase)
            shown.append(_status_text(app))

        app._mail_status = _record
        toasts: list[str] = []
        real_notify = app.notify

        def _toast(message, *args, **kwargs):
            toasts.append(str(message))
            return real_notify(message, *args, **kwargs)

        app.notify = _toast
        await pilot.press("g")
        await pilot.pause()
        # The operator stays on Mail, told what is happening: a toast, and
        # the status bar -- never a line pushed in above the list.
        assert app.query_one("#main-tabs").active == "mail"
        await wait_for(lambda: shown, "the status-bar field")
        assert any("Connecting to WS1EC-2" in t for t in toasts)
        assert "GET MAIL connecting WS1EC-2" in shown[0]
        assert app.query_one("#mail-browser").query_one(MessageList).region == tree_region
        await wait_for(lambda: app.mail_store.list(BBS_INBOX), "the message to be filed")
        assert app.query_one("#main-tabs").active == "mail"
        await wait_for(
            lambda: any("1 new message" in t for t in toasts),
            "the outcome toast",
        )
        await wait_for(lambda: not app._activity, "the status-bar field to clear")
        assert any("GET MAIL reading 1/1" in text for text in shown)
        assert "GET MAIL" not in _status_text(app)
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


@pytest.mark.asyncio
async def test_g_sends_the_outbox_before_reading(tmp_path):
    from kissterm.mail.collect import BBS_SENT
    from kissterm.mail.compose import BBS_OUTBOX, outbox_message

    app, station, tb = await _app(tmp_path)
    app.mail_store.add(BBS_OUTBOX, outbox_message(
        sender="KC1JMH", to="W1BKW", at="", title="Breakfast", body="See you there\n"))
    bbs = AX25Station(BBS, tb, FAST)
    heard: list[str] = []
    _bpqmail(bbs, heard)
    toasts: list[str] = []
    async with app.run_test(size=(120, 40)) as pilot:
        real_notify = app.notify
        app.notify = lambda m, *a, **k: (toasts.append(str(m)), real_notify(m, *a, **k))[1]
        app.action_show_tab("mail")
        await pilot.pause()
        app.query_one("#mail-browser").query_one(MessageList).focus()
        await pilot.press("g")
        await wait_for(lambda: app.mail_store.list(BBS_INBOX) and not app._collecting,
                       "the run to finish")
        assert heard[:5] == ["SP W1BKW", "Breakfast", "See you there", "/EX", "LM"]
        assert app.mail_store.list(BBS_OUTBOX) == []
        [sent] = app.mail_store.list(BBS_SENT)
        assert app.mail_store.read(sent.ref).extra["Bbs-Number"] == "2803"
        assert any("1 sent, 1 new message" in t for t in toasts), toasts
    bbs.close()
    station.close()
