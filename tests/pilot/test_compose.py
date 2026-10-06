"""Writing BBS mail from the Mail tab (`kissterm/ui/compose.py`): Insert,
R and Q open the compose screen; Save files into the Outbox and sends
nothing."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

from datetime import datetime, timezone  # noqa: E402

import pytest  # noqa: E402
from textual.widgets import Input, Label, Select, TextArea  # noqa: E402

from kissterm.config import Config  # noqa: E402
from kissterm.mail import Message, MessageStore  # noqa: E402
from kissterm.mail.compose import BBS_OUTBOX, outbox_message  # noqa: E402
from kissterm.ui.app import KissTermApp  # noqa: E402
from kissterm.ui.compose import ComposeScreen  # noqa: E402
from kissterm.ui.mail_pane import MessageBrowser, MessageList  # noqa: E402
from tests.pilot._wait import wait_for  # noqa: E402

WHEN = datetime(2026, 9, 24, 20, 35, tzinfo=timezone.utc)


def _app(tmp_path, *, reply_quote: bool = False):
    store = MessageStore(tmp_path / "mail")
    store.ensure_default_tree()
    store.add("Mail/BBS/Inbox", Message(
        sender="KC1UIX", to="KC1JMH", subject="Test message", date=WHEN,
        source="BBS WS1EC", body="This was sent to kc1jmh.\nDave\n",
        extra={"Bbs-Number": "2784", "Bbs-Type": "PN"}))
    config = Config(mycall="KC1JMH", start_tab="mail", reply_quote=reply_quote)
    config.transports = [{"name": "tnc", "kind": "tcp", "host": "127.0.0.1", "port": 8001}]
    app = KissTermApp(config)
    app.mail_store = store
    return app, store


async def _focus_list(app, pilot) -> MessageList:
    await pilot.pause()
    table = app.query_one("#mail-browser", MessageBrowser).query_one(MessageList)
    table.focus()
    await pilot.pause()
    return table


@pytest.mark.asyncio
async def test_insert_writes_a_new_message_into_the_outbox(tmp_path):
    app, store = _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _focus_list(app, pilot)
        assert "insert" in app.screen.active_bindings  # New, in the Footer
        await pilot.press("insert")
        await wait_for(lambda: isinstance(app.screen, ComposeScreen), "the compose screen")
        await pilot.pause()
        screen = app.screen
        screen.query_one("#compose-to", Input).value = "w1bkw"
        screen.query_one("#compose-title", Input).value = "Breakfast"
        screen.query_one("#compose-body", TextArea).text = "Hi Brian,\n\n73"
        await pilot.click("#compose-save")
        await wait_for(lambda: store.list(BBS_OUTBOX), "the Outbox message")
        [summary] = store.list(BBS_OUTBOX)
        message = store.read(summary.ref)
        assert (message.to, message.subject, message.sender) == ("W1BKW", "Breakfast", "KC1JMH")
        assert message.extra["Send-Type"] == "P" and message.body == "Hi Brian,\n\n73\n"


@pytest.mark.asyncio
async def test_bpqmail_limits_are_shown_and_nothing_is_saved(tmp_path):
    app, store = _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _focus_list(app, pilot)
        await pilot.press("insert")
        await wait_for(lambda: isinstance(app.screen, ComposeScreen), "the compose screen")
        await pilot.pause()
        screen = app.screen
        screen.query_one("#compose-to", Input).value = "KC1JMH-7"
        screen.query_one("#compose-title", Input).value = "x"
        screen.query_one("#compose-body", TextArea).text = "one\n/ex\ntwo"
        await pilot.click("#compose-save")
        await pilot.pause()
        error = str(screen.query_one("#compose-error", Label).render())
        assert "SSID" in error and "Line 2" in error
        assert isinstance(app.screen, ComposeScreen) and store.list(BBS_OUTBOX) == []


@pytest.mark.asyncio
async def test_r_replies_by_number_and_leaves_the_body_empty(tmp_path):
    app, store = _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _focus_list(app, pilot)
        await pilot.press("r")
        await wait_for(lambda: isinstance(app.screen, ComposeScreen), "the compose screen")
        await pilot.pause()
        screen = app.screen
        to = screen.query_one("#compose-to", Input)
        assert to.value == "KC1UIX" and to.disabled  # the BBS addresses an SR reply
        assert screen.query_one("#compose-title", Input).value == "Re:Test message"
        assert "SR 2784" in str(screen.query_one("#compose-note").render())
        body = screen.query_one("#compose-body", TextArea)
        assert body.text == "" and app.focused is body
        await pilot.press(*"Got it")
        await pilot.click("#compose-save")
        await wait_for(lambda: store.list(BBS_OUTBOX), "the Outbox message")
        message = store.read(store.list(BBS_OUTBOX)[0].ref)
        assert message.extra["Reply-Number"] == "2784" and message.body == "Got it\n"


@pytest.mark.asyncio
async def test_q_quotes_and_the_setting_makes_r_quote_too(tmp_path):
    app, _store = _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _focus_list(app, pilot)
        await pilot.press("q")
        await wait_for(lambda: isinstance(app.screen, ComposeScreen), "the compose screen")
        await pilot.pause()
        text = app.screen.query_one("#compose-body", TextArea).text
        assert text.startswith("\n\nOn 2026-09-24 20:35Z, KC1UIX wrote:\n> This was sent")
    app, _store = _app(tmp_path / "second", reply_quote=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await _focus_list(app, pilot)
        await pilot.press("r")
        await wait_for(lambda: isinstance(app.screen, ComposeScreen), "the compose screen")
        await pilot.pause()
        assert "> Dave" in app.screen.query_one("#compose-body", TextArea).text


@pytest.mark.asyncio
async def test_esc_asks_before_discarding_typed_text(tmp_path):
    app, store = _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _focus_list(app, pilot)
        await pilot.press("r")
        await wait_for(lambda: isinstance(app.screen, ComposeScreen), "the compose screen")
        await pilot.pause()
        await pilot.press(*"Long message")
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, ComposeScreen)
        assert "Discard" in str(app.screen.query_one("#compose-error", Label).render())
        await pilot.press("escape")
        await wait_for(lambda: not isinstance(app.screen, ComposeScreen), "the screen to close")
        assert store.list(BBS_OUTBOX) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("size,rows", [((80, 24), 12), ((100, 30), 17)])
async def test_the_text_gets_the_height(tmp_path, size, rows):
    """DESIGN.md section 3, "Dense where the content is the point": the
    compose dialog had two rows to write in at 80x24 (2026-09-25)."""
    app, _store = _app(tmp_path)
    async with app.run_test(size=size) as pilot:
        await _focus_list(app, pilot)
        await pilot.press("r")
        await wait_for(lambda: isinstance(app.screen, ComposeScreen), "the compose screen")
        await pilot.pause()
        body = app.screen.query_one("#compose-body", TextArea)
        assert body.region.height >= rows, body.region
        for wid in ("#compose-to", "#compose-title"):
            assert app.screen.query_one(wid).region.height == 1


@pytest.mark.asyncio
async def test_a_bulletin_offers_categories_and_distributions_that_fill_to_and_at(tmp_path):
    app, store = _app(tmp_path)
    # One bulletin sent before, to a local flood area: offered first next time.
    store.add(BBS_OUTBOX, outbox_message(sender="KC1JMH", to="ARES", at="ECBBS", title="Drill",
                                         body="x", send_type="B"))
    async with app.run_test(size=(80, 24)) as pilot:
        await _focus_list(app, pilot)
        await pilot.press("insert")
        await wait_for(lambda: isinstance(app.screen, ComposeScreen), "the compose screen")
        await pilot.pause()
        screen = app.screen
        row = screen.query_one("#compose-bulletin-row")
        assert not row.display  # a private message has no category
        screen.query_one("#compose-type", Select).value = "B"
        await pilot.pause()
        assert row.display and row.region.height == 1
        category = screen.query_one("#compose-category", Select)
        distribution = screen.query_one("#compose-distribution", Select)
        assert [v for _l, v in category._options if isinstance(v, str)][:2] == ["ARES", "WX"]
        assert [v for _l, v in distribution._options if isinstance(v, str)] == ["-", "ECBBS", "USA", "WW"]
        category.value = "WX"
        distribution.value = "USA"
        await pilot.pause()
        assert screen.query_one("#compose-to", Input).value == "WX"
        assert screen.query_one("#compose-at", Input).value == "USA"
        distribution.value = "-"
        await pilot.pause()
        assert screen.query_one("#compose-at", Input).value == ""
        assert len(store.list(BBS_OUTBOX)) == 1  # picking saves nothing


@pytest.mark.asyncio
async def test_a_winlink_message_has_no_at_and_goes_to_the_winlink_outbox(tmp_path):
    from kissterm.mail.winlink_collect import WINLINK_OUTBOX

    app, store = _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _focus_list(app, pilot)
        await pilot.press("insert")
        await wait_for(lambda: isinstance(app.screen, ComposeScreen), "the compose screen")
        await pilot.pause()
        screen = app.screen
        screen.query_one("#compose-type", Select).value = "W"
        await pilot.pause()
        assert not screen.query_one("#compose-at", Input).display
        # With @ gone, To takes the row, as wide as Title (addresses are long).
        to, title = screen.query_one("#compose-to", Input), screen.query_one("#compose-title", Input)
        assert to.region.right == title.region.right
        screen.query_one("#compose-to", Input).value = "w1aw, N0Call@Example.com"
        screen.query_one("#compose-title", Input).value = "A" * 100  # over BPQMail's 60
        screen.query_one("#compose-body", TextArea).text = "Hello"
        await pilot.click("#compose-save")
        await wait_for(lambda: store.list(WINLINK_OUTBOX), "the Winlink Outbox message")
        assert not store.list(BBS_OUTBOX)
        message = store.read(store.list(WINLINK_OUTBOX)[0].ref)
        assert message.to == "W1AW, N0Call@Example.com" and len(message.subject) == 100
        assert message.extra["Send-Type"] == "W" and "Send-At" not in message.extra


@pytest.mark.asyncio
async def test_winlink_limits_are_shown(tmp_path):
    app, store = _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _focus_list(app, pilot)
        await pilot.press("insert")
        await wait_for(lambda: isinstance(app.screen, ComposeScreen), "the compose screen")
        await pilot.pause()
        screen = app.screen
        screen.query_one("#compose-type", Select).value = "W"
        screen.query_one("#compose-to", Input).value = "not an address!"
        screen.query_one("#compose-title", Input).value = "x" * 129
        screen.query_one("#compose-body", TextArea).text = "Hello"
        await pilot.click("#compose-save")
        await pilot.pause()
        error = str(screen.query_one("#compose-error", Label).render())
        assert "not a callsign or email address" in error and "128" in error
        assert isinstance(app.screen, ComposeScreen)


@pytest.mark.asyncio
async def test_on_a_winlink_folder_new_and_reply_are_winlink(tmp_path):
    from kissterm.mail.winlink_collect import WINLINK_INBOX, WINLINK_OUTBOX

    app, store = _app(tmp_path)
    store.add(WINLINK_INBOX, Message(
        sender="SMTP:friend@example.com", to="KC1JMH", subject="Checking in", date=WHEN,
        source="Winlink", message_id="ABCDEFGHIJKL", body="All well?\n"))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        browser = app.query_one("#mail-browser", MessageBrowser)
        browser.show_folder(WINLINK_INBOX)
        table = browser.query_one(MessageList)
        table.focus()
        await pilot.pause()
        await pilot.press("insert")
        await wait_for(lambda: isinstance(app.screen, ComposeScreen), "the compose screen")
        await pilot.pause()
        assert app.screen.query_one("#compose-type", Select).value == "W"
        await pilot.press("escape")
        await wait_for(lambda: not isinstance(app.screen, ComposeScreen), "compose to close")
        await pilot.press("r")
        await wait_for(lambda: isinstance(app.screen, ComposeScreen), "the reply")
        await pilot.pause()
        screen = app.screen
        assert "by Winlink" in str(screen.query_one("#compose-heading", Label).render())
        assert not screen.query_one("#compose-at", Input).display
        to = screen.query_one("#compose-to", Input)
        assert to.value == "SMTP:friend@example.com" and not to.disabled
        screen.query_one("#compose-body", TextArea).text = "Yes"
        await pilot.click("#compose-save")
        await wait_for(lambda: store.list(WINLINK_OUTBOX), "the reply in the Winlink Outbox")
        reply = store.read(store.list(WINLINK_OUTBOX)[0].ref)
        assert reply.subject == "Re:Checking in" and reply.extra["Send-Type"] == "W"


@pytest.mark.asyncio
async def test_a_replies_to_everyone_on_a_winlink_message_only(tmp_path):
    """Reply all (A), the phone's Reply all: the sender and the other
    recipients, never this station; offered only where there are others."""
    from kissterm.mail.winlink_collect import WINLINK_INBOX, WINLINK_OUTBOX

    app, store = _app(tmp_path)
    store.add(WINLINK_INBOX, Message(
        sender="W1AW", to="KC1JMH, K1XYZ", subject="Net", date=WHEN, source="Winlink",
        message_id="ABCDEFGHIJKM", body="7 pm\n", extra={"Cc": "kc1jmh@winlink.org"}))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        browser = app.query_one("#mail-browser", MessageBrowser)
        table = await _focus_list(app, pilot)
        browser.show_folder("Mail/BBS/Inbox")
        browser.open_selected()
        await pilot.pause()
        assert not table.check_action("reply_all", ()), \
            "A shown for a BBS message, which has one recipient"
        browser.show_folder(WINLINK_INBOX)
        table.focus()
        browser.open_selected()
        await pilot.pause()
        assert table.check_action("reply_all", ()) is True
        await pilot.press("a")
        await wait_for(lambda: isinstance(app.screen, ComposeScreen), "the reply")
        await pilot.pause()
        assert app.screen.query_one("#compose-to", Input).value == "W1AW, K1XYZ"
        app.screen.query_one("#compose-body", TextArea).text = "Yes"
        await pilot.click("#compose-save")
        await wait_for(lambda: store.list(WINLINK_OUTBOX), "the reply in the Winlink Outbox")
