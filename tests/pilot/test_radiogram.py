"""The NTS radiogram form (`kissterm/ui/radiogram.py`): picking "NTS
radiogram (ST)" as the compose Type opens it; Save files an `ST` message
into the Outbox and sends nothing."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402
from textual.widgets import Input, Label, Select, Static, TextArea  # noqa: E402

from kissterm.config import Config  # noqa: E402
from kissterm.mail import MessageStore  # noqa: E402
from kissterm.mail.compose import BBS_OUTBOX, send_command  # noqa: E402
from kissterm.ui.app import KissTermApp  # noqa: E402
from kissterm.ui.compose import ComposeScreen  # noqa: E402
from kissterm.ui.mail_pane import MessageBrowser, MessageList  # noqa: E402
from kissterm.ui.radiogram import RadiogramScreen  # noqa: E402
from tests.pilot._wait import wait_for  # noqa: E402

FIELDS = {
    "#rg-place": "Waterboro ME", "#rg-name": "Jane Doe", "#rg-street": "12 Main St",
    "#rg-city": "Augusta", "#rg-state": "ME", "#rg-zip": "04330", "#rg-phone": "207-555-1212",
    "#rg-signature": "Brad",
}


def _app(tmp_path):
    store = MessageStore(tmp_path / "mail")
    store.ensure_default_tree()
    config = Config(mycall="KC1JMH-1", start_tab="mail")
    config.transports = [{"name": "tnc", "kind": "tcp", "host": "127.0.0.1", "port": 8001}]
    app = KissTermApp(config)
    app.mail_store = store
    return app, store


async def _open(app, pilot) -> RadiogramScreen:
    await pilot.pause()
    app.query_one("#mail-browser", MessageBrowser).query_one(MessageList).focus()
    await pilot.pause()
    await pilot.press("insert")
    await wait_for(lambda: isinstance(app.screen, ComposeScreen), "the compose screen")
    await pilot.pause()
    app.screen.query_one("#compose-type", Select).value = "T"
    await wait_for(lambda: isinstance(app.screen, RadiogramScreen), "the radiogram screen")
    await pilot.pause()
    return app.screen


async def _fill(screen, pilot, text: str) -> None:
    for wid, value in FIELDS.items():
        screen.query_one(wid, Input).value = value
    screen.query_one("#rg-text", TextArea).text = text
    await pilot.pause()


@pytest.mark.asyncio
async def test_a_radiogram_is_saved_as_st_to_the_outbox(tmp_path):
    app, store = _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app, pilot)
        assert screen.query_one("#rg-origin", Input).value == "KC1JMH"
        assert screen.query_one("#rg-number", Input).value == "1"
        await _fill(screen, pilot, "ARL 50. See you at the hamfest?")
        preview = str(screen.query_one("#rg-preview", Static).render())
        assert "ARL FIFTY X SEE YOU AT THE HAMFEST QUERY" in preview
        assert "Greetings by Amateur Radio" in preview
        status = str(screen.query_one("#rg-status", Static).render())
        assert "Check ARL 9" in status and "ST 04330 @ NTSME" in status
        await pilot.click("#rg-save")
        await wait_for(lambda: store.list(BBS_OUTBOX), "the Outbox message")
        [summary] = store.list(BBS_OUTBOX)
        message = store.read(summary.ref)
        assert message.subject == "QTC AUGUSTA / 207 555"
        assert message.body.startswith("NR 1 R KC1JMH ARL 9 WATERBORO ME ")
        assert send_command(message, "BBS WS1EC") == ("ST 04330 @ NTSME", True)


@pytest.mark.asyncio
async def test_the_next_radiogram_counts_on_and_keeps_the_place(tmp_path):
    app, store = _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app, pilot)
        await _fill(screen, pilot, "Hello")
        screen.query_one("#rg-number", Input).value = "41"
        await pilot.click("#rg-save")
        await wait_for(lambda: store.list(BBS_OUTBOX), "the Outbox message")
        screen = await _open(app, pilot)
        assert screen.query_one("#rg-number", Input).value == "42"
        assert screen.query_one("#rg-place", Input).value == "WATERBORO ME"


@pytest.mark.asyncio
async def test_problems_are_named_and_nothing_is_saved(tmp_path):
    app, store = _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app, pilot)
        await pilot.click("#rg-save")
        await pilot.pause()
        error = str(screen.query_one("#rg-error", Label).render())
        assert "Place of origin" in error
        assert isinstance(app.screen, RadiogramScreen) and not store.list(BBS_OUTBOX)


@pytest.mark.asyncio
async def test_fits_80x24(tmp_path):
    app, _ = _app(tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(app, pilot)
        box = screen.query_one("#rg-box").region
        for wid in ("#rg-number", "#rg-precedence", "#rg-hx", "#rg-test", "#rg-city",
                    "#rg-state", "#rg-zip", "#rg-save", "#rg-cancel"):
            region = screen.query_one(wid).region
            assert region.width > 0 and region.right <= box.right, wid
        assert screen.query_one("#rg-status").region.height >= 1
        assert screen.query_one("#rg-save").region.bottom <= 24
