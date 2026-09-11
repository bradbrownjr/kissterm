"""Tabbed APRS conversations: who is talking, who is unread, and "All".

The pane used to have one conversation viewer showing whoever was picked
last, so a message from anybody else left no mark on the screen at all and
"who has written to me?" was answerable only from a toast that had already
gone. These are the assertions that say it now does -- driven with real UI
frames off the loopback, the same way `test_aprs_messaging.py` does, never a
mocked decode path.

The one that matters most is
`test_a_third_party_message_opens_no_tab_and_marks_nothing`: every message
packet on the channel is recorded in `ConversationStore`, deliberately, so
without the `to_me` gate two strangers chatting on the frequency would fill
this strip with tabs for conversations nobody here has to answer.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402
from textual.widgets import Input, RichLog, Tabs  # noqa: E402

from kissterm import aprs  # noqa: E402
from kissterm.app import KissTermApp  # noqa: E402
from kissterm.aprs_conversations import ConversationStore  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.aprs_pane import _ALL_TAB, _MAX_CONVO_TABS, AprsPane, _tab_id  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
PEER = AX25Address.parse("WS1EC-15")


async def _app(tmp_path):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = Config(mycall=str(MYCALL))
    config.log_sessions = False
    config.tx_armed_at_start = True
    params = LinkParams(t1=0.3, t2=0.05, t3=5.0, retries=2)
    mine = AX25Station(MYCALL, ta, params)
    theirs = AX25Station(PEER, tb, params)
    app = KissTermApp(config, mine)
    app.aprs_conversations = ConversationStore(tmp_path / "aprs_messages.json")
    return app, mine, theirs


async def _aprs_tab(app, pilot):
    app.action_show_tab("aprs")
    await pilot.pause()
    await asyncio.sleep(0.05)
    await pilot.pause()


async def _send_message(theirs, source, addressee, text, number="1"):
    """One real APRS message frame, from `source`, on the wire."""
    payload = aprs.message(addressee, text, number=number)
    frame = aprs.beacon_frame(
        AX25Address.parse(source), AX25Address.parse("APRS"), (), payload
    )
    await theirs.transport.send_frame(frame, 0)


async def _settle(pilot, tries: int = 20):
    for _ in range(tries):
        await pilot.pause()
    await asyncio.sleep(0.05)
    await pilot.pause()


def _tabs(app) -> Tabs:
    return app.query_one("#aprs-convo-tabs", Tabs)


def _labels(app) -> list[str]:
    return [tab.label_text for tab in _tabs(app).query("Tab")]


def _log_lines(app) -> list[str]:
    log = app.query_one("#aprs-conversation-log", RichLog)
    return [seg.text for line in log.lines for seg in line._segments]


@pytest.mark.asyncio
async def test_all_is_the_left_most_tab_and_the_one_active_at_launch(tmp_path):
    """Settled with the operator: no conversation tabs at launch, and "All"
    is where the pane opens. It is composed in rather than added, so it is
    active from the first frame with no flicker through an empty strip."""
    app, mine, theirs = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        assert _labels(app) == ["All"]
        assert _tabs(app).active == _ALL_TAB
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_a_message_to_us_opens_a_tab_and_marks_it_unread(tmp_path):
    app, mine, theirs = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        await _send_message(theirs, "WS1EC-15", "N1ABC-1", "are you there")
        await _settle(pilot)

        assert "*WS1EC-15" in _labels(app), _labels(app)
        # It must NOT steal the view: the operator may be part-way through a
        # reply to somebody else.
        assert _tabs(app).active == _ALL_TAB
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_a_third_party_message_opens_no_tab_and_marks_nothing(tmp_path):
    """`_on_aprs_frame` records EVERY message packet it decodes, before it
    checks the addressee -- that is deliberate and unchanged. What must not
    happen is the channel's own traffic raising unread markers here, which
    would mean asterisks beside stations nobody in this shack has to answer.
    """
    app, mine, theirs = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        await _send_message(theirs, "WS1EC-15", "K1XYZ", "nothing to do with us")
        await _settle(pilot)

        assert _labels(app) == ["All"], _labels(app)
        assert app.query_one(AprsPane)._unread == set()
        # Still recorded, and still visible in "All" -- that is the point.
        assert "WS1EC-15" in app.aprs_conversations.conversations
        assert any("nothing to do with us" in line for line in _log_lines(app))
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_activating_a_tab_clears_the_mark_and_shows_that_conversation(tmp_path):
    app, mine, theirs = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        await _send_message(theirs, "WS1EC-15", "N1ABC-1", "are you there")
        await _settle(pilot)
        assert "*WS1EC-15" in _labels(app)

        _tabs(app).active = _tab_id("WS1EC-15")
        await _settle(pilot)

        assert "WS1EC-15" in _labels(app)
        assert "*WS1EC-15" not in _labels(app)
        assert app.query_one(AprsPane)._unread == set()
        assert any("are you there" in line for line in _log_lines(app))
        # Switching addresses it too, or a reply typed straight away goes to
        # whoever happened to be in the "To:" field before.
        assert app.query_one("#aprs-to-input", Input).value == "WS1EC-15"
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_a_message_from_the_station_on_screen_is_not_unread(tmp_path):
    """Reading a conversation while the other end is typing into it is the
    normal case, not a notification."""
    app, mine, theirs = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        app.query_one(AprsPane).select_conversation("WS1EC-15", "WS1EC-15")
        await _settle(pilot, 5)

        await _send_message(theirs, "WS1EC-15", "N1ABC-1", "still here")
        await _settle(pilot)

        assert app.query_one(AprsPane)._unread == set()
        assert "*WS1EC-15" not in _labels(app)
        assert any("still here" in line for line in _log_lines(app))
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_the_all_tab_merges_more_than_one_callsign(tmp_path):
    app, mine, theirs = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        await _send_message(theirs, "WS1EC-15", "N1ABC-1", "first one", number="1")
        await _settle(pilot, 8)
        await _send_message(theirs, "K1XYZ-7", "N1ABC", "second one", number="2")
        await _settle(pilot)

        _tabs(app).active = _ALL_TAB
        await _settle(pilot, 5)

        lines = _log_lines(app)
        assert any("WS1EC-15" in line and "first one" in line for line in lines), lines
        assert any("K1XYZ-7" in line and "second one" in line for line in lines), lines
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_sending_to_a_callsign_with_no_tab_opens_and_activates_one(tmp_path):
    app, mine, theirs = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        app.query_one("#aprs-to-input", Input).value = "WS1EC-15"
        app.query_one("#aprs-compose-input", Input).value = "hello there"
        await pilot.click("#aprs-send-button")
        await _settle(pilot)

        assert "WS1EC-15" in _labels(app), _labels(app)
        assert _tabs(app).active == _tab_id("WS1EC-15")
        assert any("hello there" in line for line in _log_lines(app))
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_delete_closes_the_active_tab_but_never_all(tmp_path):
    app, mine, theirs = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        pane = app.query_one(AprsPane)
        pane.select_conversation("WS1EC-15", "WS1EC-15")
        await _settle(pilot, 5)
        assert "WS1EC-15" in _labels(app)

        pane.close_active_tab()
        await _settle(pilot, 5)
        assert _labels(app) == ["All"]
        assert _tabs(app).active == _ALL_TAB

        # "All" is the fallback `remove_tab` lands on and the only view that
        # is always available; closing it would leave nothing to repaint.
        pane.close_active_tab()
        await _settle(pilot, 5)
        assert _labels(app) == ["All"]
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_the_cap_evicts_a_read_tab_and_never_an_unread_one(tmp_path):
    """Twelve tabs is a tidiness rule; not losing a message is not. The
    eviction skips anything unread and the tab on screen, and if everything
    open is one of those the strip is allowed to run over rather than
    silently throwing away the only record that somebody called."""
    app, mine, theirs = await _app(tmp_path)
    async with app.run_test(size=(200, 40)) as pilot:
        await _aprs_tab(app, pilot)
        pane = app.query_one(AprsPane)

        for i in range(_MAX_CONVO_TABS):
            pane.select_conversation(f"K{i}ABC", f"K{i}ABC")
            await pilot.pause()
        await _settle(pilot, 5)
        assert len(_labels(app)) == _MAX_CONVO_TABS + 1  # plus "All"

        # K0ABC is the least recently viewed and has nothing unread.
        pane.select_conversation("W1AW", "W1AW")
        await _settle(pilot, 5)
        labels = _labels(app)
        assert "K0ABC" not in labels, labels
        assert "W1AW" in labels
        assert len(labels) == _MAX_CONVO_TABS + 1

        # Now make every remaining conversation unread and confirm nothing is
        # thrown away to make room.
        pane._unread.update(pane._recent)
        pane.select_conversation("K9ZZZ", "K9ZZZ")
        await _settle(pilot, 5)
        labels = _labels(app)
        assert "K9ZZZ" in labels
        assert len(labels) == _MAX_CONVO_TABS + 2, labels
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_an_unread_contact_is_starred_in_the_contact_table(tmp_path):
    """The other half of the marker. A row the operator has not read is `*`
    plus the theme's warning colour -- the first styled `DataTable` cell in
    this app, so this checks the rendered cell rather than the model."""
    from textual.widgets import DataTable

    app, mine, theirs = await _app(tmp_path)
    app.config.aprs_contacts = [
        {"name": "Emcomm", "callsign": "WS1EC-15", "service": "station"}
    ]
    async with app.run_test(size=(140, 40)) as pilot:
        await _aprs_tab(app, pilot)
        table = app.query_one("#aprs-contact-table", DataTable)
        assert str(table.get_cell_at((0, 0))) == "WS1EC-15"

        await _send_message(theirs, "WS1EC-15", "N1ABC-1", "are you there")
        await _settle(pilot)

        assert str(table.get_cell_at((0, 0))) == "*WS1EC-15"

        _tabs(app).active = _tab_id("WS1EC-15")
        await _settle(pilot)
        assert str(table.get_cell_at((0, 0))) == "WS1EC-15"
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_restores_a_tab_for_every_conversation_already_on_disk(tmp_path):
    """`ConversationStore` is persisted JSON and outlives the process; the
    tabs above it did not, before `_restore_tabs` -- a station closing and
    reopening kissterm mid-conversation landed back on a bare "All" with
    that history reachable only by re-picking the contact, even though "the
    conversation remains in All" the whole time. Restoring must not steal
    "All" as the tab on screen at launch, the same rule an incoming message
    already follows.
    """
    app, mine, theirs = await _app(tmp_path)
    app.aprs_conversations.record_incoming("WHO-IS", "found it", number="1")
    app.aprs_conversations.record_outgoing("WHO-IS", "KC1JMH", number="1")
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        assert "WHO-IS" in _labels(app), _labels(app)
        assert _tabs(app).active == _ALL_TAB
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_ctrl_l_on_all_clears_packet_lines_and_every_conversation(tmp_path):
    """`action_clear_log` used to fall through to `TerminalPane.clear_active`
    for every tab except Monitor, so Ctrl+L on APRS silently cleared the
    (invisible) Terminal pane instead of anything on screen.

    On "All", Ctrl+L clears everything merged into it -- requested directly
    after an earlier version left conversation history untouched there and
    it looked unresponsive: with third-party-relayed replies filed as real
    chat rather than raw packet lines, most of what "All" shows *is*
    conversation content, so sparing it left barely anything visibly
    cleared. There is deliberately no confirmation step.
    """
    app, mine, theirs = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        payload = aprs.position_report(49.05, -72.0175, "/", ">", comment="mobile")
        frame = aprs.beacon_frame(
            AX25Address.parse("WS1EC-15"), AX25Address.parse("APRS"), (), payload
        )
        await theirs.transport.send_frame(frame, 0)
        await _settle(pilot)
        await _send_message(theirs, "WS1EC-15", "N1ABC-1", "are you there")
        await _settle(pilot)
        assert any("49.0500" in line for line in _log_lines(app))

        app.action_clear_log()
        await _settle(pilot)

        lines = _log_lines(app)
        assert not any("49.0500" in line for line in lines)
        assert app.aprs_conversations.conversations == {}
        assert not any("are you there" in line for line in lines)
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_ctrl_l_on_a_conversation_tab_deletes_only_that_conversation(tmp_path):
    app, mine, theirs = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        await _send_message(theirs, "WS1EC-15", "N1ABC-1", "are you there")
        await _settle(pilot)
        app.aprs_conversations.record_incoming("K1XYZ", "hello from someone else", number=None)
        app.query_one(AprsPane).select_conversation("WS1EC-15", "WS1EC-15")
        await _settle(pilot)

        app.action_clear_log()
        await _settle(pilot)

        assert "WS1EC-15" not in app.aprs_conversations.conversations
        assert "K1XYZ" in app.aprs_conversations.conversations
        lines = _log_lines(app)
        assert any("no messages yet" in line for line in lines)
    mine.close()
    theirs.close()


@pytest.mark.asyncio
async def test_a_position_beacon_shows_as_a_readable_line_in_all(tmp_path):
    """A non-message packet (a position report here) has no correspondent
    and so never enters `ConversationStore` -- but it must still show up
    somewhere as more than raw bytes. `AprsPane.note_packet`, fed from
    `KissTermApp._on_aprs_frame` via `aprs.format_packet`, is that path; this
    drives a real position frame off the loopback rather than calling
    `note_packet` directly, so the whole decode-to-display chain is checked."""
    app, mine, theirs = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _aprs_tab(app, pilot)
        payload = aprs.position_report(49.05, -72.0175, "/", ">", comment="mobile")
        frame = aprs.beacon_frame(
            AX25Address.parse("WS1EC-15"), AX25Address.parse("APRS"), (), payload
        )
        await theirs.transport.send_frame(frame, 0)
        await _settle(pilot)

        lines = _log_lines(app)
        assert any("WS1EC-15" in line and "49.0500" in line for line in lines), lines
        # Never written to the persisted message store -- it has no
        # correspondent to be filed under.
        assert app.aprs_conversations.conversations == {}
    mine.close()
    theirs.close()
