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


@pytest.mark.asyncio
async def test_i_on_a_winlink_folder_uses_the_cms_by_telnet(tmp_path, monkeypatch):
    from kissterm.mail import winlink_collect
    from kissterm.transcripts import list_transcripts

    gateway = Gateway([REAL.read_bytes()], challenge=True, telnet=True)

    async def handle(reader, writer):
        gateway.deliver = writer.write
        serving = asyncio.ensure_future(gateway.serve())
        while not reader.at_eof():
            data = await reader.read(4096)
            if not data:
                break
            gateway._rx += data
            gateway._got.set()
        serving.cancel()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    monkeypatch.setattr(winlink_collect, "CMS_HOST", "127.0.0.1")
    monkeypatch.setattr(winlink_collect, "CMS_PORT", server.sockets[0].getsockname()[1])
    app, station, _tb = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_show_tab("mail")
        await pilot.pause()
        browser = app.query_one("#mail-browser", MessageBrowser)
        browser.show_folder(WINLINK_INBOX)
        browser.query_one(MessageList).focus()
        await pilot.pause()
        assert "get_internet" in _footer_actions(app)
        toasts: list[str] = []
        real_notify = app.notify
        app.notify = lambda message, *a, **k: (toasts.append(str(message)), real_notify(message, *a, **k))[1]
        await pilot.press("i")
        await wait_for(lambda: any("Winlink message" in t for t in toasts), "the outcome toast", timeout=20)
        assert gateway.telnet_login == ["KC1JMH", "CMSTelnet"]
        assert ";PR: 95074758" in gateway.handshake and gateway.handshake[-1].startswith("; WL2K DE KC1JMH")
        assert len(app.mail_store.list(WINLINK_INBOX)) == 1
        assert not station.transport.sent  # nothing on the radio side
        # The log folder is shared by every test in this worker: find ours.
        texts = [t.path.read_text() for t in list_transcripts(app._transcript_directory())]
        [text] = [t for t in texts if "[WL2K-5.0-B2FWIHJM$]" in t and "Callsign :" in t]
        assert "FQ" in text
    server.close()
    station.close()


@pytest.mark.asyncio
async def test_i_on_a_bbs_folder_logs_in_to_the_node_and_gets_mail(tmp_path):
    """The Home BBS over a Telnet connection: BPQ's login, BBS, then LM."""
    from kissterm.config import find_credential
    from kissterm.transcripts import list_transcripts
    from kissterm.ui.dialogs import HomeBbsSetupScreen, LoginAskScreen
    from tests.pilot.test_get_mail import GREETING, REPLIES

    heard: list[str] = []

    async def handle(reader, writer):
        writer.write(b"\xff\xfb\x01\xff\xfb\x03user:")  # as TelnetV6.c sends it
        answers = {"KC1JMH": b"password:", "secret": b"Welcome\rWS1EC:WS1EC} ", "BBS": GREETING}
        buffer = b""
        while True:
            data = await reader.read(4096)
            if not data:
                break
            buffer += data
            while b"\r" in buffer:
                line, buffer = buffer.split(b"\r", 1)
                command = line.decode("latin-1").strip()
                heard.append(command)
                reply = answers.get(command) or REPLIES.get(command)
                if reply:
                    writer.write(reply)

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    app, station, _tb = await _app(tmp_path)
    app.addressbook.upsert("ws1ec-telnet", connect_by="telnet", host="127.0.0.1", port=str(port))
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_show_tab("mail")
        await pilot.pause()
        browser = app.query_one("#mail-browser", MessageBrowser)
        browser.show_folder("Mail/BBS/Inbox")
        browser.query_one(MessageList).focus()
        await pilot.pause()
        await pilot.press("i")
        await wait_for(lambda: isinstance(app.screen, HomeBbsSetupScreen), "the connection question")
        await pilot.pause()
        await pilot.click("#connect-go")
        await wait_for(lambda: isinstance(app.screen, LoginAskScreen), "the password question")
        app.screen.query_one("#login-ask-text").value = "secret"
        await pilot.press("enter")
        await wait_for(lambda: app.mail_store.list(BBS_INBOX), "the message to be filed", timeout=20)
        await wait_for(lambda: not app._collecting, "the run to finish")
        assert heard[:4] == ["KC1JMH", "secret", "BBS", "LM"]
        assert app.config.home_bbs.internet == "ws1ec-telnet"
        assert find_credential(app.config, app.config.home_bbs.internet_credential) == "secret"
        assert not station.transport.sent  # nothing on the radio side
        text = next(t for t in list_transcripts(app._transcript_directory())
                    if "ws1ec" in t.path.name.lower()).path.read_text()
        assert "(password sent)" in text and "secret" not in text
    server.close()
    station.close()


async def _all_inboxes_with_winlink_gone(app, pilot):
    """G on All Inboxes with the Winlink entry forgotten (operator's
    screenshot, 2026-09-27): the Winlink question comes up."""
    from kissterm.mail.store import ALL_INBOXES
    from kissterm.ui.dialogs import HomeBbsSetupScreen

    app.action_show_tab("mail")
    await pilot.pause()
    browser = app.query_one("#mail-browser", MessageBrowser)
    browser.show_folder(ALL_INBOXES)
    browser.query_one(MessageList).focus()
    await pilot.pause()
    await pilot.press("g")
    await wait_for(lambda: isinstance(app.screen, HomeBbsSetupScreen), "the Winlink question")
    await pilot.pause()


@pytest.mark.asyncio
async def test_all_inboxes_says_why_winlink_is_asked_and_skip_runs_the_bbs(tmp_path):
    from textual.widgets import Static

    from tests.pilot.test_get_mail import BBS, _bpqmail

    app, station, tb = await _app(tmp_path)
    app.config.home_bbs.route = "WS1EC-2"
    app.addressbook.forget("WS1EC-10")
    app.addressbook.record_attempt("WS1EC-2")
    bbs = AX25Station(BBS, tb, FAST)
    heard: list[str] = []
    _bpqmail(bbs, heard)
    async with app.run_test(size=(120, 40)) as pilot:
        await _all_inboxes_with_winlink_gone(app, pilot)
        note = str(app.screen.query_one("#setup-all-note", Static).render())
        assert "G on All Inboxes" in note and "Winlink needs this first" in note
        # Fits an 80x24 terminal too: see test_setup_questions_fit_80x24.
        # Centred, not in the top-left corner.
        box, screen = app.screen.query_one("#connect-box").region, app.screen.region
        assert abs((box.x - screen.x) - (screen.right - box.right)) <= 1
        assert box.y > 0
        assert not station.transport.sent  # asked before any dial
        await pilot.click("#setup-skip")
        await wait_for(lambda: app.mail_store.list(BBS_INBOX), "the BBS run alone", timeout=30)
        await wait_for(lambda: not app._collecting, "the run to finish", timeout=20)
        assert app.config.winlink.route == "WS1EC-10"  # skipping changes nothing
        assert not app.mail_store.list(WINLINK_INBOX)
    bbs.close()
    station.close()


@pytest.mark.asyncio
async def test_the_setup_question_goes_to_the_setting_it_names(tmp_path):
    app, station, _tb = await _app(tmp_path)
    app.config.home_bbs.route = "WS1EC-2"
    app.addressbook.forget("WS1EC-10")
    app.addressbook.record_attempt("WS1EC-2")
    async with app.run_test(size=(120, 40)) as pilot:
        await _all_inboxes_with_winlink_gone(app, pilot)
        await pilot.click("#setup-go")
        await wait_for(lambda: not app._collecting, "the run to be cancelled")
        await pilot.pause()
        assert app.query_one("#main-tabs").active == "settings"
        assert app.focused is not None and app.focused.id == "set-winlink-account"
        assert not station.transport.sent
    station.close()


@pytest.mark.asyncio
async def test_setup_questions_fit_80x24(tmp_path):
    """Centred, the All Inboxes Winlink question was 26 rows on a 24-row
    terminal and its buttons fell off the bottom."""
    app, station, _tb = await _app(tmp_path)
    app.config.home_bbs.route = "WS1EC-2"
    app.addressbook.forget("WS1EC-10")
    app.addressbook.record_attempt("WS1EC-2")
    async with app.run_test(size=(80, 24)) as pilot:
        await _all_inboxes_with_winlink_gone(app, pilot)
        for button in app.screen.query("#connect-buttons Button"):
            r = button.region
            assert r.height == 3 and r.bottom <= 24 and r.right <= 80, f"{button.id} at {r}"
        await pilot.click("#connect-cancel")
        await wait_for(lambda: not app._collecting, "the run to be cancelled")
    station.close()


@pytest.mark.asyncio
async def test_a_password_in_the_login_name_setting_is_never_shown(tmp_path):
    """The operator's screenshot, 2026-09-27: "Saved as the login
    "<their password>"". At launch it becomes the saved login "Winlink";
    no screen shows it."""
    from kissterm.config import find_credential

    app, station, _tb = await _app(tmp_path)
    app.config.credentials = []
    app.config.winlink.credential = "SECRET123"
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(lambda: app.config.winlink.credential == "Winlink", "the rescue")
        assert find_credential(app.config, "Winlink") == "SECRET123"
        await pilot.pause()
        text = "\n".join(str(w.render()) for w in app.screen.query("Static, Label"))
        assert "SECRET123" not in text
    station.close()


@pytest.mark.asyncio
async def test_a_refused_password_is_asked_again_and_saved(tmp_path):
    """Rather than "set the password in Settings > Mail > Winlink", the
    refusal asks for it there and then; nothing more is dialed."""
    from textual.widgets import Input

    from kissterm.config import find_credential
    from kissterm.ui.dialogs import LoginAskScreen

    app, station, tb = await _app(tmp_path)
    rms = AX25Station(RMS, tb, FAST)
    gateway = Gateway([], challenge=True, fail_login=True)
    _gateway(rms, gateway)
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_show_tab("mail")
        await pilot.pause()
        browser = app.query_one("#mail-browser", MessageBrowser)
        browser.show_folder(WINLINK_INBOX)
        browser.query_one(MessageList).focus()
        await pilot.pause()
        await pilot.press("g")
        await wait_for(lambda: isinstance(app.screen, LoginAskScreen), "the password asked again",
                       timeout=20)
        await pilot.pause()
        assert "refused" in str(app.screen.query_one("#connect-title").render())
        assert str(app.screen.query_one("#connect-go").label) == "Save"
        app.screen.query_one("#login-ask-text", Input).value = "Right0ne"
        await pilot.click("#connect-go")
        await wait_for(lambda: find_credential(app.config, "Winlink") == "Right0ne", "the new password")
        assert app.config.winlink.credential == "Winlink"
        await wait_for(lambda: not app._collecting, "the run to end")
        assert not station.link_to(RMS).connected
    rms.close()
    station.close()


@pytest.mark.asyncio
async def test_i_with_no_internet_contact_offers_a_new_one(tmp_path):
    from textual.widgets import Select

    from kissterm.ui.dialogs import AddressBookEntryScreen, HomeBbsSetupScreen

    app, station, _tb = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_show_tab("mail")
        await pilot.pause()
        browser = app.query_one("#mail-browser", MessageBrowser)
        browser.show_folder("Mail/BBS/Inbox")
        browser.query_one(MessageList).focus()
        await pilot.pause()
        await pilot.press("i")
        await wait_for(lambda: isinstance(app.screen, HomeBbsSetupScreen), "the question")
        await pilot.pause()
        assert str(app.screen.query_one("#setup-go").label) == "New contact"
        await pilot.click("#setup-go")
        await wait_for(lambda: isinstance(app.screen, AddressBookEntryScreen), "the editor")
        await pilot.pause()
        assert app.screen.query_one("#addressbook-connect-by", Select).value == "ssh"
        assert not station.transport.sent
    station.close()
