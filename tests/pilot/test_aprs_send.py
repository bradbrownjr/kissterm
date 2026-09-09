"""Sending an APRS message from the pane, ack matching, and retry.

Same loopback-peer shape as `test_aprs_messaging.py` (which covers incoming
messages and auto-ack) and `test_aprs_contacts_pane.py` (contacts CRUD) --
this one is the send half: a real compose input, a real Send button, a real
frame on the wire, and a real ack sent back from the peer.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402
from textual.widgets import Input, RichLog  # noqa: E402

from kissterm import aprs  # noqa: E402
from kissterm.app import KissTermApp  # noqa: E402
from kissterm.aprs_conversations import ConversationStore, PendingAcks  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.aprs_pane import AprsPane  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
PEER = AX25Address.parse("WS1EC-15")


async def _app(tmp_path, *, tx_armed: bool = True):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = Config(mycall=str(MYCALL))
    config.tx_armed_at_start = tx_armed
    params = LinkParams(t1=0.3, t2=0.05, t3=5.0, retries=2)
    mine = AX25Station(MYCALL, ta, params)
    theirs = AX25Station(PEER, tb, params)
    app = KissTermApp(config, mine)
    app.aprs_conversations = ConversationStore(tmp_path / "aprs_messages.json")
    return app, mine, theirs, ta


async def _aprs_tab(app, pilot):
    app.action_show_tab("aprs")
    await pilot.pause()
    await asyncio.sleep(0.05)
    await pilot.pause()


def _terminal_text(app: KissTermApp) -> str:
    from kissterm.ui.terminal_pane import TerminalPane

    return "\n".join(
        str(line) for line in app.query_one(TerminalPane).query_one("#session-log").lines
    )


@pytest.mark.asyncio
async def test_sending_composes_and_transmits_a_real_frame(tmp_path):
    app, mine, theirs, ta = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)

        app.query_one("#aprs-to-input", Input).value = "WS1EC-15"
        app.query_one("#aprs-compose-input", Input).value = "hello there"
        await pilot.click("#aprs-send-button")
        for _ in range(20):
            if "Sent APRS message" in _terminal_text(app):
                break
            await pilot.pause()

        convo = app.aprs_conversations.conversations["WS1EC-15"]
        assert convo.messages[0].direction == "out"
        assert convo.messages[0].text == "hello there"
        assert not convo.messages[0].acked

        # A real frame went out and decodes back to the same message.
        sent = [f for f in ta.sent if f.info.startswith(b":WS1EC-15")]
        assert sent, "no APRS message frame was actually transmitted"
        packet = aprs.parse_packet(sent[-1])
        assert packet.kind == "message"
        assert packet.data.text == "hello there"

        # The compose field is cleared after a successful send.
        assert app.query_one("#aprs-compose-input", Input).value == ""
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_sending_with_no_addressee_is_refused_without_transmitting(tmp_path):
    app, mine, theirs, ta = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        app.query_one("#aprs-compose-input", Input).value = "hello"
        await pilot.click("#aprs-send-button")
        await pilot.pause()
        assert not ta.sent
        assert app.aprs_conversations.conversations == {}
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_a_closed_transmit_gate_refuses_the_send_and_records_nothing(tmp_path):
    app, mine, theirs, ta = await _app(tmp_path, tx_armed=False)
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        app.query_one("#aprs-to-input", Input).value = "WS1EC-15"
        app.query_one("#aprs-compose-input", Input).value = "hello"
        await pilot.click("#aprs-send-button")
        await pilot.pause()
        assert not ta.sent
        assert app.aprs_conversations.conversations == {}
        assert "Sent APRS message" not in _terminal_text(app)
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_an_incoming_ack_marks_the_sent_message_acked_and_stops_retrying(tmp_path):
    app, mine, theirs, ta = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        pane = app.query_one(AprsPane)
        pane._pending = PendingAcks(retry_seconds=0.1, max_retries=5)

        app.query_one("#aprs-to-input", Input).value = "WS1EC-15"
        app.query_one("#aprs-compose-input", Input).value = "hello there"
        await pilot.click("#aprs-send-button")
        for _ in range(20):
            if "WS1EC-15" in app.aprs_conversations.conversations:
                break
            await pilot.pause()

        # The peer acks it.
        ack_payload = aprs.ack("N1ABC-1", "1")
        frame = aprs.beacon_frame(PEER, AX25Address.parse("APRS"), (), ack_payload)
        await theirs.transport.send_frame(frame, 0)
        for _ in range(20):
            convo = app.aprs_conversations.conversations["WS1EC-15"]
            if any(m.acked for m in convo.messages):
                break
            await pilot.pause()
        assert convo.messages[0].acked

        # Retry check now sees it acked and does not resend.
        pane._check_retries()
        await asyncio.sleep(0.3)
        await pilot.pause()
        assert "Resent APRS message" not in _terminal_text(app)
        assert pane._pending.due(now=time.monotonic() + 1000) == []
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_an_unacked_message_is_retried(tmp_path):
    app, mine, theirs, ta = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        pane = app.query_one(AprsPane)
        pane._pending = PendingAcks(retry_seconds=0.1, max_retries=3)

        app.query_one("#aprs-to-input", Input).value = "WS1EC-15"
        app.query_one("#aprs-compose-input", Input).value = "hello there"
        await pilot.click("#aprs-send-button")
        for _ in range(20):
            if "Sent APRS message" in _terminal_text(app):
                break
            await pilot.pause()

        await asyncio.sleep(0.2)
        pane._check_retries()
        for _ in range(20):
            if "Resent APRS message" in _terminal_text(app):
                break
            await pilot.pause()
        assert "Resent APRS message" in _terminal_text(app)

        # Never a second history entry for a retry -- same logical message.
        convo = app.aprs_conversations.conversations["WS1EC-15"]
        assert len(convo.messages) == 1
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_sending_to_an_sms_contact_transmits_the_templated_body(tmp_path):
    """The wire body is `<phone> <text>`, but the conversation log keeps
    what the operator actually typed -- readable history, not a wire dump.
    A retry must resend the templated body, not re-template the human text
    a second time."""
    config = Config(
        mycall=str(MYCALL),
        aprs_contacts=[
            {"name": "Mom", "callsign": "SMSGTE", "service": "sms", "detail": "5551234567"},
        ],
    )
    config.tx_armed_at_start = True
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    params = LinkParams(t1=0.3, t2=0.05, t3=5.0, retries=2)
    mine = AX25Station(MYCALL, ta, params)
    theirs = AX25Station(PEER, tb, params)
    app = KissTermApp(config, mine)
    app.aprs_conversations = ConversationStore(tmp_path / "aprs_messages.json")

    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        app.query_one(AprsPane).toggle_contacts()
        await pilot.pause()
        table = app.query_one("#aprs-contact-table")
        table.focus()
        table.move_cursor(row=0)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one("#aprs-to-input", Input).value == "SMSGTE"

        app.query_one("#aprs-compose-input", Input).value = "running late"
        await pilot.click("#aprs-send-button")
        for _ in range(20):
            if "Sent APRS message" in _terminal_text(app):
                break
            await pilot.pause()

        # Human-readable text in the conversation log.
        convo = app.aprs_conversations.conversations["SMSGTE"]
        assert convo.messages[0].text == "running late"
        assert convo.messages[0].service == "sms"

        # Templated body actually on the wire.
        sent = [f for f in ta.sent if f.info.startswith(b":SMSGTE")]
        assert sent, "no APRS message frame was actually transmitted"
        packet = aprs.parse_packet(sent[-1])
        assert packet.data.text == "5551234567 running late"
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_a_configured_sms_template_changes_the_wire_body(tmp_path):
    config = Config(
        mycall=str(MYCALL),
        aprs_contacts=[
            {"name": "Mom", "callsign": "SMSGTE", "service": "sms", "detail": "5551234567"},
        ],
        aprs_sms_template="SMS {detail}: {text}",
    )
    config.tx_armed_at_start = True
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    params = LinkParams(t1=0.3, t2=0.05, t3=5.0, retries=2)
    mine = AX25Station(MYCALL, ta, params)
    theirs = AX25Station(PEER, tb, params)
    app = KissTermApp(config, mine)
    app.aprs_conversations = ConversationStore(tmp_path / "aprs_messages.json")

    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        app.query_one("#aprs-to-input", Input).value = "SMSGTE"
        app.query_one("#aprs-compose-input", Input).value = "hi"
        await pilot.click("#aprs-send-button")
        for _ in range(20):
            if "Sent APRS message" in _terminal_text(app):
                break
            await pilot.pause()

        sent = [f for f in ta.sent if f.info.startswith(b":SMSGTE")]
        packet = aprs.parse_packet(sent[-1])
        assert packet.data.text == "SMS 5551234567: hi"
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_the_conversation_shows_sent_then_ack(tmp_path):
    """APRS messaging is acknowledged end to end, and "did that get through?"
    is the question the whole numbered-message mechanism exists to answer.
    The pane used to throw the answer away except for a bare "(acked)"."""
    app, mine, theirs, ta = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        pane = app.query_one(AprsPane)

        app.query_one("#aprs-to-input", Input).value = "WLNK-1"
        app.query_one("#aprs-compose-input", Input).value = "L"
        pane._send_pressed()
        await pilot.pause()
        await asyncio.sleep(0.2)

        lines = _log_lines(app)
        assert any("[sent]" in line for line in lines), lines

        # The far end acks it; the status must follow without the operator
        # clicking away and back.
        number = pane._pending._pending and list(pane._pending._pending)[0][1]
        app.aprs_conversations.mark_acked("WLNK-1", number)
        pane.refresh_conversation()
        await pilot.pause()

        lines = _log_lines(app)
        assert any("[ack]" in line for line in lines), lines
        assert not any("[sent]" in line for line in lines), lines
    mine.close()
    theirs.close()


def _log_lines(app):
    log = app.query_one("#aprs-conversation-log", RichLog)
    return [seg.text for line in log.lines for seg in line._segments]
