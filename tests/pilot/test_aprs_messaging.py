"""APRS message routing: recorded, auto-acked, and notified -- with no
connection, straight off the frame fan-out. Same shape as
`test_mail_waiting_notice.py`, which this deliberately mirrors: a UI frame
from a peer on the loopback, checked against `KissTermApp` state, never a
mocked decode path.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm import aprs  # noqa: E402
from kissterm.app import KissTermApp  # noqa: E402
from kissterm.aprs_conversations import ConversationStore  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.terminal_pane import TerminalPane  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
PEER = AX25Address.parse("WS1EC-15")


async def _app(tmp_path, *, tx_armed: bool = True, aprs_auto_ack: bool = True):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = Config(mycall=str(MYCALL))
    config.log_sessions = False
    config.tx_armed_at_start = tx_armed
    config.aprs_auto_ack = aprs_auto_ack
    params = LinkParams(t1=0.3, t2=0.05, t3=5.0, retries=2)
    mine = AX25Station(MYCALL, ta, params)
    theirs = AX25Station(PEER, tb, params)
    app = KissTermApp(config, mine)
    # `isolate()` (module-level, at import time) points every test in this
    # process at the SAME state directory, so `ConversationStore()`'s default
    # path would accumulate messages across test functions -- give each test
    # its own file instead, the same reason `test_addressbook.py` never
    # exercises `AddressBook()`'s own default path either.
    app.aprs_conversations = ConversationStore(tmp_path / "aprs_messages.json")
    return app, mine, theirs


async def _send_message(theirs: AX25Station, addressee: str, text: str, number: str) -> None:
    payload = aprs.message(addressee, text, number=number)
    frame = aprs.beacon_frame(PEER, AX25Address.parse("APRS"), (), payload)
    await theirs.transport.send_frame(frame, 0)


def _terminal_text(app: KissTermApp) -> str:
    return "\n".join(
        str(line) for line in app.query_one(TerminalPane).query_one("#session-log").lines
    )


@pytest.mark.asyncio
async def test_a_message_addressed_to_me_is_recorded_and_auto_acked(tmp_path):
    app, mine, theirs = await _app(tmp_path)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await _send_message(theirs, "N1ABC", "hello there", "1")
        for _ in range(20):
            if "Auto-ack sent" in _terminal_text(app):
                break
            await pilot.pause()
        convo = app.aprs_conversations.conversations["WS1EC-15"]
        assert convo.messages[0].direction == "in"
        assert convo.messages[0].text == "hello there"
        assert any(m.direction == "out" and m.text == "ack1" for m in convo.messages)
        assert "Auto-ack sent to WS1EC-15 (msg 1)" in _terminal_text(app)
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_matches_our_ssid_alias_even_when_the_message_addressee_has_none(tmp_path):
    """Same SSID-stripping rule as MAIL FOR -- our own callsign here carries
    an SSID the message never mentions."""
    app, mine, theirs = await _app(tmp_path)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await _send_message(theirs, "N1ABC", "hi", "1")
        for _ in range(20):
            if "WS1EC-15" in app.aprs_conversations.conversations:
                break
            await pilot.pause()
        assert "WS1EC-15" in app.aprs_conversations.conversations
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_a_message_to_someone_else_is_not_acked(tmp_path):
    app, mine, theirs = await _app(tmp_path)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await _send_message(theirs, "K1XYZ", "not for you", "1")
        for _ in range(10):
            await pilot.pause()
        # Still recorded (it crossed the channel, worth keeping), just not acked.
        convo = app.aprs_conversations.conversations["WS1EC-15"]
        assert convo.messages[0].direction == "in"
        assert not any(m.direction == "out" for m in convo.messages)
        assert "Auto-ack sent" not in _terminal_text(app)
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_no_auto_ack_when_disabled_in_config(tmp_path):
    app, mine, theirs = await _app(tmp_path, aprs_auto_ack=False)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await _send_message(theirs, "N1ABC", "hello", "1")
        for _ in range(10):
            await pilot.pause()
        convo = app.aprs_conversations.conversations["WS1EC-15"]
        assert not any(m.direction == "out" for m in convo.messages)
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_a_closed_transmit_gate_blocks_the_ack_and_never_reports_it_sent(tmp_path):
    """The one thing worse than not acking is claiming an ack went out when
    transmit was disabled -- AGENTS.md's "never report a suppressed
    transmission as a sent one" applies here exactly as it does to a beacon.
    """
    app, mine, theirs = await _app(tmp_path, tx_armed=False)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await _send_message(theirs, "N1ABC", "hello", "1")
        for _ in range(10):
            await pilot.pause()
        convo = app.aprs_conversations.conversations["WS1EC-15"]
        assert not any(m.direction == "out" for m in convo.messages)
        assert "Auto-ack sent" not in _terminal_text(app)
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_an_ack_reply_marks_our_own_outgoing_message_acked(tmp_path):
    app, mine, theirs = await _app(tmp_path)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        app.aprs_conversations.record_outgoing("WS1EC-15", "did you get this", number="42")
        ack_payload = aprs.ack("N1ABC", "42")
        frame = aprs.beacon_frame(PEER, AX25Address.parse("APRS"), (), ack_payload)
        await theirs.transport.send_frame(frame, 0)
        for _ in range(20):
            convo = app.aprs_conversations.conversations.get("WS1EC-15")
            if convo and any(m.acked for m in convo.messages):
                break
            await pilot.pause()
        assert any(m.number == "42" and m.acked for m in convo.messages)
        # An ack is never itself worth an unattended notification.
        assert ("WS1EC-15", "message") not in app._aprs_notify_cooldown._last_fired
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_an_emergency_mic_e_beacon_fires_the_notification_cooldown_key(tmp_path):
    """Full-decode path, not `evaluate_packet` called directly: a real
    Mic-E-shaped destination callsign and info field through the actual
    frame fan-out.

    Checked via `_notify_aprs_desktop`, not `Cooldown._last_fired` --
    `Cooldown.allow` returns True for an urgent key without recording it
    (there is nothing to suppress next time either way), so the internal
    dict is not evidence a notification actually happened.
    """
    app, mine, theirs = await _app(tmp_path)
    calls: list[tuple[str, str, bool]] = []
    app._notify_aprs_desktop = lambda title, body, *, urgent: calls.append((title, body, urgent))
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        # "422Q3P" + this exact info field is `tests/unit/test_aprs.py`'s
        # own `test_mic_e_emergency_message` fixture verbatim -- reused
        # rather than re-derived so this test cannot silently drift from a
        # real, independently-verified Emergency Mic-E encoding. Only the
        # routing (fan-out -> notify) is under test here.
        from kissterm.ax25.address import AX25Path
        from kissterm.ax25.frame import AX25Frame, UType, PID_NO_LAYER3

        dest = AX25Address.parse("422Q3P")
        path = AX25Path(destination=dest, source=PEER, repeaters=())
        info = b"`c\x1fN\x1f\x1cI>/Mobile"
        frame = AX25Frame.u_frame(path, UType.UI, pid=PID_NO_LAYER3, command=True, info=info)
        # Sanity: this really does decode as Emergency before relying on it
        # to exercise the notification path.
        assert aprs.parse_packet(frame).data.mic_e_message == "Emergency"
        await theirs.transport.send_frame(frame, 0)
        for _ in range(20):
            if calls:
                break
            await pilot.pause()
        assert calls == [("APRS EMERGENCY -- WS1EC-15", "Mobile", True)]
    mine.close()
    theirs.close()
