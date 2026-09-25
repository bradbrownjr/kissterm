"""Writing BBS mail from the Mail tab (`kissterm/ui/compose.py`): Insert,
R and Q open the compose screen; Save files into the Outbox and sends
nothing."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

from datetime import datetime, timezone  # noqa: E402

import pytest  # noqa: E402
from textual.widgets import Input, Label, TextArea  # noqa: E402

from kissterm.config import Config  # noqa: E402
from kissterm.mail import Message, MessageStore  # noqa: E402
from kissterm.mail.compose import BBS_OUTBOX  # noqa: E402
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
