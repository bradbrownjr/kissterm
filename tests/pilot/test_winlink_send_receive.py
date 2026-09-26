"""Winlink Send/Receive (G on a Mail/Winlink folder) end to end.

The gateway is a second `AX25Station` on the loopback, WS1EC-10, speaking
the master's side of B2F through the scripted `Gateway` of
`tests/unit/test_mail_winlink_collect.py`.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

import pytest  # noqa: E402

from kissterm.addressbook import AddressBook  # noqa: E402
from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.mail import Message, MessageStore  # noqa: E402
from kissterm.mail.collect import BBS_INBOX  # noqa: E402
from kissterm.mail.winlink_collect import WINLINK_INBOX, WINLINK_OUTBOX, WINLINK_SENT  # noqa: E402
from kissterm.ui.mail_pane import MessageBrowser, MessageList  # noqa: E402
from kissterm.ui.terminal_pane import TerminalPane  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402
from tests.pilot._wait import wait_for  # noqa: E402
from tests.unit.test_mail_winlink_collect import REAL, Gateway  # noqa: E402

MYCALL = AX25Address.parse("KC1JMH-7")
RMS = AX25Address.parse("WS1EC-10")
FAST = LinkParams(t1=0.3, t2=0.05, t3=5.0)


def _gateway(rms: AX25Station, gateway: Gateway) -> None:
    def _answer(link) -> None:
        gateway.deliver = lambda data: asyncio.get_event_loop().create_task(link.send(data))

        def _heard(data: bytes) -> None:
            gateway._rx += data
            gateway._got.set()

        link.on_data.append(_heard)
        asyncio.get_event_loop().create_task(gateway.serve())

    rms.on_incoming.append(_answer)


async def _app(tmp_path, route: str = "WS1EC-10"):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = Config(mycall=str(MYCALL))
    config.tx_armed_at_start = True
    config.slideouts_auto_open = False
    config.winlink.route = route
    config.winlink.credential = "winlink"
    config.credentials = [{"name": "winlink", "text": "FooBar"}]
    station = AX25Station(MYCALL, ta, FAST)
    app = KissTermApp(config, station)
    app.addressbook = AddressBook(tmp_path / "addressbook.json")
    app.addressbook.record_attempt("WS1EC-10")
    app.mail_store = MessageStore(tmp_path / "mail")
    app.mail_store.ensure_default_tree()
    return app, station, tb


def _log_text(app) -> str:
    log = app.query_one(TerminalPane).query_one("#session-log")
    return "\n".join(str(line) for line in log.lines)


def _footer_actions(app) -> set[str]:
    return {b.binding.action for b in app.screen.active_bindings.values() if b.enabled}


@pytest.mark.asyncio
async def test_g_on_a_winlink_folder_sends_and_receives_with_winlink(tmp_path):
    app, station, tb = await _app(tmp_path)
    app.mail_store.add(WINLINK_OUTBOX, Message(
        sender="KC1JMH", to="W1AW", subject="Net report", body="All accounted for.\n",
        date=datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)))
    rms = AX25Station(RMS, tb, FAST)
    gateway = Gateway([REAL.read_bytes()], challenge=True)
    _gateway(rms, gateway)
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_show_tab("mail")
        await pilot.pause()
        browser = app.query_one("#mail-browser", MessageBrowser)
        browser.show_folder("Mail/BBS/Inbox")
        browser.query_one(MessageList).focus()
        await pilot.pause()
        assert "get_mail" in _footer_actions(app) and "get_winlink" not in _footer_actions(app)
        browser.show_folder(WINLINK_INBOX)
        await pilot.pause()
        # The Footer says which: G here is Winlink.
        assert "get_winlink" in _footer_actions(app) and "get_mail" not in _footer_actions(app)
        toasts: list[str] = []
        real_notify = app.notify
        app.notify = lambda message, *a, **k: (toasts.append(str(message)), real_notify(message, *a, **k))[1]
        await pilot.press("g")
        await wait_for(lambda: any("Winlink message" in t for t in toasts), "the outcome toast", timeout=20)
        assert app.query_one("#main-tabs").active == "mail"
        [inbox] = app.mail_store.list(WINLINK_INBOX)
        assert (inbox.sender, inbox.source) == ("LA5NTA", "Winlink")
        assert not app.mail_store.list(WINLINK_OUTBOX) and len(app.mail_store.list(WINLINK_SENT)) == 1
        assert not app.mail_store.list(BBS_INBOX)
        assert gateway.handshake[0] == ";FW: KC1JMH"  # the account, no SSID
        assert gateway.handshake[-1] == "; WS1EC-10 DE KC1JMH ()"
        assert ";PR: 95074758" in gateway.handshake  # the saved login answered it
        text = _log_text(app)
        assert "[WL2K-5.0-B2FWIHJM$]" in text and "FC EM " in text
        assert "[message " in text  # the compressed bytes, summarised
        assert "\x02" not in text
        await wait_for(lambda: not station.link_to(RMS).connected, "the disconnect")
    rms.close()
    station.close()


@pytest.mark.asyncio
async def test_g_on_winlink_without_a_route_asks_with_winlink_words(tmp_path):
    from textual.widgets import Label

    from kissterm.ui.dialogs import HomeBbsSetupScreen

    app, station, _tb = await _app(tmp_path, route="")
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_show_tab("mail")
        await pilot.pause()
        browser = app.query_one("#mail-browser", MessageBrowser)
        browser.show_folder(WINLINK_INBOX)
        browser.query_one(MessageList).focus()
        await pilot.pause()
        await pilot.press("g")
        await wait_for(lambda: isinstance(app.screen, HomeBbsSetupScreen), "the setup dialog")
        assert str(app.screen.query_one("#connect-title", Label).render()) == "Set up Winlink"
        assert not station.transport.sent
        await pilot.pause()
        await pilot.click("#connect-cancel")
        await wait_for(lambda: not isinstance(app.screen, HomeBbsSetupScreen), "the dialog to close")
        assert app.config.winlink.route == "" and app.config.home_bbs.route == ""
    station.close()


@pytest.mark.asyncio
async def test_without_a_password_g_asks_before_dialing(tmp_path):
    from textual.widgets import Input

    from kissterm.config import find_credential
    from kissterm.ui.dialogs import LoginAskScreen

    app, station, tb = await _app(tmp_path)
    app.config.winlink.credential = ""
    app.config.credentials = []
    rms = AX25Station(RMS, tb, FAST)
    gateway = Gateway(challenge=True)
    _gateway(rms, gateway)
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_show_tab("mail")
        await pilot.pause()
        browser = app.query_one("#mail-browser", MessageBrowser)
        browser.show_folder(WINLINK_INBOX)
        browser.query_one(MessageList).focus()
        await pilot.pause()
        await pilot.press("g")
        await wait_for(lambda: isinstance(app.screen, LoginAskScreen), "the password question")
        assert not station.transport.sent  # asked before anything was dialed
        field = app.screen.query_one("#login-ask-text", Input)
        assert field.password  # masked
        field.value = "FooBar"
        await pilot.press("enter")
        await wait_for(lambda: gateway.handshake and gateway.handshake[-1].startswith("; "),
                       "the handshake", timeout=20)
        assert ";PR: 95074758" in gateway.handshake
        assert app.config.winlink.credential == "Winlink"
        assert find_credential(app.config, "Winlink") == "FooBar"
        await wait_for(lambda: not app._collecting, "the run to finish", timeout=20)
    rms.close()
    station.close()


@pytest.mark.asyncio
async def test_cancelling_the_password_question_sends_nothing(tmp_path):
    from kissterm.ui.dialogs import LoginAskScreen

    app, station, _tb = await _app(tmp_path)
    app.config.winlink.credential = ""
    app.config.credentials = []
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_show_tab("mail")
        await pilot.pause()
        browser = app.query_one("#mail-browser", MessageBrowser)
        browser.show_folder(WINLINK_INBOX)
        browser.query_one(MessageList).focus()
        await pilot.pause()
        await pilot.press("g")
        await wait_for(lambda: isinstance(app.screen, LoginAskScreen), "the password question")
        await pilot.pause()
        await pilot.click("#connect-cancel")
        await wait_for(lambda: not app._collecting, "G to give up")
        assert not station.transport.sent and app.config.credentials == []
    station.close()


@pytest.mark.asyncio
async def test_all_inboxes_label_follows_what_is_set_up(tmp_path):
    from kissterm.mail.store import ALL_INBOXES

    app, station, _tb = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_show_tab("mail")
        await pilot.pause()
        browser = app.query_one("#mail-browser", MessageBrowser)
        browser.show_folder(ALL_INBOXES)
        browser.query_one(MessageList).focus()
        await pilot.pause()
        assert "get_winlink" in _footer_actions(app)  # only Winlink set up
        app.config.home_bbs.route = "WS1EC-2"
        app.screen.refresh_bindings()
        await pilot.pause()
        assert "get_all" in _footer_actions(app)
        assert not {"get_mail", "get_winlink"} & _footer_actions(app)
        browser.show_folder("Mail/BBS/Inbox")
        await pilot.pause()
        assert "get_mail" in _footer_actions(app) and "get_all" not in _footer_actions(app)
    station.close()


@pytest.mark.asyncio
async def test_g_on_all_inboxes_runs_the_bbs_then_winlink(tmp_path):
    from kissterm.mail.store import ALL_INBOXES
    from tests.pilot.test_get_mail import BBS, _bpqmail

    app, station, tb = await _app(tmp_path)
    app.config.home_bbs.route = "WS1EC-2"
    app.addressbook.record_attempt("WS1EC-2")
    bbs = AX25Station(BBS, tb, FAST)
    heard: list[str] = []
    _bpqmail(bbs, heard)
    rms = AX25Station(RMS, tb, FAST)
    gateway = Gateway([REAL.read_bytes()])
    _gateway(rms, gateway)
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_show_tab("mail")
        await pilot.pause()
        browser = app.query_one("#mail-browser", MessageBrowser)
        browser.show_folder(ALL_INBOXES)
        browser.query_one(MessageList).focus()
        await pilot.pause()
        await pilot.press("g")
        await wait_for(lambda: app.mail_store.list(BBS_INBOX) and app.mail_store.list(WINLINK_INBOX),
                       "mail from both", timeout=30)
        assert heard[:2] == ["LM", "R 2578"]  # the BBS came first
        await wait_for(lambda: not app._collecting, "both runs to finish", timeout=20)
        assert not station.link_to(BBS).connected and not station.link_to(RMS).connected
    bbs.close()
    rms.close()
    station.close()
