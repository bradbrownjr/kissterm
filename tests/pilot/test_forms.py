"""Message forms (`kissterm/ui/form_screen.py`): choosing a form as the
compose Type opens it; Continue brings the text back to the compose
screen to address; Save files it in the Outbox and sends nothing."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402
from textual.widgets import Button, Input, Label, Select, TextArea  # noqa: E402

from kissterm.config import Config  # noqa: E402
from kissterm.mail import MessageStore  # noqa: E402
from kissterm.mail.compose import BBS_OUTBOX  # noqa: E402
from kissterm.ui.app import KissTermApp  # noqa: E402
from kissterm.ui.compose import ComposeScreen  # noqa: E402
from kissterm.ui.form_screen import FormScreen  # noqa: E402
from kissterm.ui.mail_pane import MessageBrowser, MessageList  # noqa: E402
from tests.pilot._wait import wait_for  # noqa: E402


def _app(tmp_path):
    store = MessageStore(tmp_path / "mail")
    store.ensure_default_tree()
    config = Config(mycall="KC1JMH-1", start_tab="mail")
    config.transports = [{"name": "tnc", "kind": "tcp", "host": "127.0.0.1", "port": 8001}]
    app = KissTermApp(config)
    app.mail_store = store
    return app, store


async def _open(app, pilot, form_id: str) -> FormScreen:
    await pilot.pause()
    app.query_one("#mail-browser", MessageBrowser).query_one(MessageList).focus()
    await pilot.pause()
    await pilot.press("insert")
    await wait_for(lambda: isinstance(app.screen, ComposeScreen), "the compose screen")
    await pilot.pause()
    app.screen.query_one("#compose-type", Select).value = f"form:{form_id}"
    await wait_for(lambda: isinstance(app.screen, FormScreen), "the form screen")
    await pilot.pause()
    return app.screen


def _fill(screen, **values):
    for wid, value in values.items():
        widget = screen.query_one(f"#form-{wid}")
        if isinstance(widget, TextArea):
            widget.text = value
        else:
            widget.value = value


async def _fill_ics213(screen, pilot):
    _fill(screen, To_Name="J SMITH, EOC", fm_name="B BROWN, RADIO OP", Subjectline="Shelter status",
          Message="Shelter open.", Approved_Name="B BROWN")
    await pilot.pause()


@pytest.mark.asyncio
async def test_an_ics213_is_addressed_in_compose_and_saved(tmp_path):
    app, store = _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app, pilot, "ics213")
        await _fill_ics213(screen, pilot)
        await pilot.click("#form-continue")
        await wait_for(lambda: isinstance(app.screen, ComposeScreen), "the compose screen again")
        await pilot.pause()
        compose = app.screen
        assert compose.query_one("#compose-title", Input).value.startswith("ICS-213: Shelter status - ")
        assert "2. To (Name and Position): J SMITH, EOC" in compose.query_one("#compose-body", TextArea).text
        compose.query_one("#compose-to", Input).value = "w1bkw"
        await pilot.click("#compose-save")
        await wait_for(lambda: store.list(BBS_OUTBOX), "the Outbox message")
        [summary] = store.list(BBS_OUTBOX)
        message = store.read(summary.ref)
        assert message.to == "W1BKW" and message.extra["Send-Type"] == "P"
        assert message.extra["Form"] == "ics213"
        assert message.body.startswith("GENERAL MESSAGE (ICS 213)\n")


@pytest.mark.asyncio
async def test_the_station_half_is_remembered(tmp_path):
    app, store = _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app, pilot, "ics213")
        await _fill_ics213(screen, pilot)
        await pilot.click("#form-continue")
        await wait_for(lambda: isinstance(app.screen, ComposeScreen), "the compose screen again")
        await pilot.press("escape")
        await pilot.press("escape")
        await wait_for(lambda: not isinstance(app.screen, ComposeScreen), "compose closed")
        screen = await _open(app, pilot, "ics213")
        assert screen.query_one("#form-fm_name", Input).value == "B BROWN, RADIO OP"
        assert screen.query_one("#form-Subjectline", Input).value == ""


@pytest.mark.asyncio
async def test_missing_fields_are_named_and_nothing_continues(tmp_path):
    app, _ = _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app, pilot, "ics213")
        await pilot.click("#form-continue")
        await pilot.pause()
        assert "2. To is needed" in str(screen.query_one("#form-error", Label).render())
        assert isinstance(app.screen, FormScreen)


@pytest.mark.asyncio
async def test_213rr_adds_order_lines(tmp_path):
    app, _ = _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app, pilot, "ics213rr")
        assert screen.query("#form-order-1-Qty") and not screen.query("#form-order-2-Qty")
        screen.query_one("#form-order-add", Button).press()
        await pilot.pause()
        assert screen.query("#form-order-2-Qty")
        _fill(screen, **{"order-1-Qty": "40", "order-1-Item": "Cots", "order-2-Qty": "2",
                         "order-2-Item": "Generators"})
        rows = screen.values()["order"]
        assert [r["Qty"] for r in rows] == ["40", "2"]


@pytest.mark.asyncio
@pytest.mark.parametrize("form_id", ["ics213", "ics213rr", "winlink_checkin", "pktnet_checkin"])
async def test_fits_80x24(tmp_path, form_id):
    app, _ = _app(tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(app, pilot, form_id)
        box = screen.query_one("#form-box").region
        for button in screen.query(Button):
            if button.id in ("form-continue", "form-cancel"):
                region = button.region
                assert region.height >= 1 and region.bottom <= box.bottom - 1, button.id
        for widget in screen.query("#form-body Input"):
            if widget.region.height:
                assert widget.region.right <= box.right, widget.id


@pytest.mark.asyncio
async def test_a_pktnet_checkin_comes_back_addressed_as_a_bulletin(tmp_path):
    app, store = _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app, pilot, "pktnet_checkin")
        assert screen.query_one("#form-from", Input).value == "KC1JMH"
        _fill(screen, contact="Brad Brown", location="Home", town="Waterboro", state="ME")
        await pilot.pause()
        screen.query_one("#form-continue", Button).press()
        await wait_for(lambda: isinstance(app.screen, ComposeScreen), "the compose screen again")
        await pilot.pause()
        compose = app.screen
        assert compose.query_one("#compose-type", Select).value == "B"
        assert compose.query_one("#compose-to", Input).value == "PKTNET"
        assert compose.query_one("#compose-at", Input).value == "USA"
        assert compose.query_one("#compose-title", Input).value == "Brad Brown, KC1JMH, Waterboro, ME"
        compose.query_one("#compose-save", Button).press()
        await wait_for(lambda: store.list(BBS_OUTBOX), "the Outbox message")
        message = store.read(store.list(BBS_OUTBOX)[0].ref)
        assert (message.to, message.extra["Send-Type"], message.extra["Send-At"]) == ("PKTNET", "B", "USA")


@pytest.mark.asyncio
async def test_a_winlink_checkin_is_addressed_from_its_to_field(tmp_path):
    app, _ = _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(app, pilot, "winlink_checkin")
        _fill(screen, MsgTo="KW6GB", Location="Waterboro ME")
        await pilot.pause()
        screen.query_one("#form-continue", Button).press()
        await wait_for(lambda: isinstance(app.screen, ComposeScreen), "the compose screen again")
        await pilot.pause()
        assert app.screen.query_one("#compose-to", Input).value == "KW6GB"
