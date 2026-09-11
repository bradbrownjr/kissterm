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


async def _send_third_party(theirs: AX25Station, inner_source: str, inner_payload: bytes) -> None:
    """`inner_payload` (already-encoded, e.g. `aprs.message(...)`/`aprs.ack(...)`)
    wrapped in a third-party (`}`) relay header, the shape a message-relay
    service with no RF presence of its own (WHO-IS, WXBOT) actually replies
    in -- its own callsign never touches RF, only the igate's does.
    `inner_source` deliberately need not be a legal AX.25 callsign (`WHO-IS`
    is not one): that is exactly the case this unwrapping has to handle.
    """
    payload = b"}" + f"{inner_source}>APJIW4:".encode("ascii") + inner_payload
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
        # The auto-ack transmits (the terminal line below is its record) but
        # is never filed as a chat line -- same as an incoming ack, which is
        # only ever a `mark_acked` flip, never a `record_incoming` message.
        assert not any(m.direction == "out" for m in convo.messages)
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
async def test_a_telemetry_definition_message_is_not_recorded_as_chat(tmp_path):
    """A telemetry-equipped station labelling its own channels sends this as
    a message addressed to itself -- real traffic, but not a line a human
    wrote, so it must never land in the conversation log or the merged "All"
    view it feeds. See `kissterm.aprs.types.Message.is_telemetry_definition`.
    """
    app, mine, theirs = await _app(tmp_path)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        payload = aprs.message("WS1EC-15", "PARM.Vin,Rx1h,Eff1h", number=None)
        frame = aprs.beacon_frame(PEER, AX25Address.parse("APRS"), (), payload)
        await theirs.transport.send_frame(frame, 0)
        for _ in range(10):
            await pilot.pause()
        assert "WS1EC-15" not in app.aprs_conversations.conversations
        assert "Auto-ack sent" not in _terminal_text(app)
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_purge_removes_legacy_telemetry_definition_lines_but_keeps_real_chat(tmp_path):
    """`_on_aprs_frame` has kept telemetry-definition lines out of chat since
    2026-09-10, but a history file written by an older build still has them
    sitting in it -- `KissTermApp._purge_stale_telemetry_definitions` (run
    once at startup, right after `ConversationStore.load()`) is the
    one-time cleanup for exactly that. A real human message in the same
    conversation must survive the purge untouched."""
    app, mine, theirs = await _app(tmp_path)
    store = app.aprs_conversations
    store.record_incoming("W1UWS-1", "PARM.Vin,Rx1h,Eff1h", number=None)
    store.record_incoming("W1UWS-1", "hello from a human", number=None)
    app._purge_stale_telemetry_definitions()
    convo = store.conversations["W1UWS-1"]
    assert [m.text for m in convo.messages] == ["hello from a human"]
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
async def test_a_third_party_relayed_message_addressed_to_us_is_recorded_and_acked(tmp_path):
    """WHO-IS/WXBOT-style services have no RF presence of their own: their
    reply reaches us only wrapped in a third-party relay header (an igate's
    callsign as the outer frame source, the service's own non-callsign
    identity -- "WHO-IS" -- inside it). Before this, `_on_aprs_frame` only
    ever matched `packet.kind == "message"` at the top level, so a wrapped
    reply was never recorded or acked even though it decoded and displayed
    fine in the "All" tab -- an answered query looked stuck retrying
    forever. Source is the relay header's own text ("WHO-IS"), not the
    igate that carried it, so the reply files under the same contact the
    query was sent to.
    """
    app, mine, theirs = await _app(tmp_path)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await _send_third_party(theirs, "WHO-IS", aprs.message("N1ABC-1", "found it", "9"))
        for _ in range(20):
            if "Auto-ack sent" in _terminal_text(app):
                break
            await pilot.pause()
        convo = app.aprs_conversations.conversations["WHO-IS"]
        assert convo.messages[0].direction == "in"
        assert convo.messages[0].text == "found it"
        assert not any(m.direction == "out" for m in convo.messages)
        assert "Auto-ack sent to WHO-IS (msg 9)" in _terminal_text(app)
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_a_third_party_relayed_ack_stops_a_pending_retry(tmp_path):
    app, mine, theirs = await _app(tmp_path)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        app.aprs_conversations.record_outgoing("WHO-IS", "N1ABC", number="7")
        await _send_third_party(theirs, "WHO-IS", aprs.ack("N1ABC-1", "7"))
        for _ in range(20):
            convo = app.aprs_conversations.conversations.get("WHO-IS")
            if convo and any(m.acked for m in convo.messages):
                break
            await pilot.pause()
        assert any(m.number == "7" and m.acked for m in convo.messages)
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
