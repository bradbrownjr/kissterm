"""`kissterm.aprs_conversations` -- the chat history behind the APRS pane."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import json  # noqa: E402

import pytest  # noqa: E402

from kissterm.aprs_conversations import (  # noqa: E402
    MAX_MESSAGES_PER_CONVERSATION,
    ConversationStore,
    PendingAcks,
)


@pytest.fixture
def store(tmp_path):
    return ConversationStore(tmp_path / "aprs_messages.json")


def test_an_outgoing_message_is_recorded(store):
    store.record_outgoing("K1ABC-9", "hello", number="1")
    convo = store.conversations["K1ABC-9"]
    assert convo.messages[0].direction == "out"
    assert convo.messages[0].text == "hello"
    assert convo.messages[0].number == "1"
    assert convo.messages[0].acked is False


def test_an_incoming_message_is_recorded(store):
    store.record_incoming("K1ABC-9", "hi there", number="7")
    convo = store.conversations["K1ABC-9"]
    assert convo.messages[0].direction == "in"


def test_callsign_and_ssid_are_a_different_conversation_than_bare_call(store):
    """Unlike the "addressed to me" check in aprs_notify, a conversation key
    keeps the SSID -- these may be different physical stations."""
    store.record_outgoing("K1ABC-9", "to the mobile", number="1")
    store.record_outgoing("K1ABC", "to the home station", number="2")
    assert len(store.conversations) == 2
    assert store.conversations["K1ABC-9"].messages[0].text == "to the mobile"
    assert store.conversations["K1ABC"].messages[0].text == "to the home station"


def test_mark_acked_flips_the_matching_outgoing_message(store):
    store.record_outgoing("K1ABC-9", "hello", number="1")
    assert store.mark_acked("K1ABC-9", "1") is True
    assert store.conversations["K1ABC-9"].messages[0].acked is True


def test_mark_acked_on_an_unknown_number_finds_nothing(store):
    store.record_outgoing("K1ABC-9", "hello", number="1")
    assert store.mark_acked("K1ABC-9", "99") is False


def test_forget_deletes_one_conversation_and_leaves_others(store):
    store.record_outgoing("K1ABC-9", "hello", number="1")
    store.record_incoming("K1XYZ", "hi", number=None)
    store.forget("K1ABC-9")
    assert "K1ABC-9" not in store.conversations
    assert "K1XYZ" in store.conversations


def test_forget_on_an_unknown_callsign_is_a_no_op(store):
    store.forget("NOBODY")
    assert store.conversations == {}


def test_clear_all_deletes_every_conversation(store):
    store.record_outgoing("K1ABC-9", "hello", number="1")
    store.record_incoming("K1XYZ", "hi", number=None)
    store.clear_all()
    assert store.conversations == {}


def test_persistence_round_trips(tmp_path):
    file = tmp_path / "aprs_messages.json"
    a = ConversationStore(file)
    a.record_outgoing("K1ABC-9", "hello", number="1", service="sms")
    a.record_incoming("K1ABC-9", "reply", number="2")
    a.mark_acked("K1ABC-9", "1")

    b = ConversationStore(file)
    b.load()
    convo = b.conversations["K1ABC-9"]
    assert len(convo.messages) == 2
    assert convo.messages[0].service == "sms"
    assert convo.messages[0].acked is True
    assert convo.messages[1].direction == "in"


def test_a_missing_file_loads_as_empty(tmp_path):
    store = ConversationStore(tmp_path / "does-not-exist.json")
    store.load()
    assert store.conversations == {}


def test_a_corrupt_file_loads_as_empty_and_does_not_raise(tmp_path):
    file = tmp_path / "aprs_messages.json"
    file.write_text("not json at all {{{", "utf-8")
    store = ConversationStore(file)
    store.load()
    assert store.conversations == {}


def test_per_conversation_message_count_is_capped(store):
    for i in range(MAX_MESSAGES_PER_CONVERSATION + 10):
        store.record_outgoing("K1ABC-9", f"msg {i}", number=None)
    assert len(store.conversations["K1ABC-9"].messages) == MAX_MESSAGES_PER_CONVERSATION
    # The oldest were dropped, not the newest.
    assert store.conversations["K1ABC-9"].messages[-1].text == f"msg {MAX_MESSAGES_PER_CONVERSATION + 9}"


def test_save_writes_valid_json(store):
    store.record_outgoing("K1ABC-9", "hello", number="1")
    raw = json.loads(store.file.read_text("utf-8"))
    assert "K1ABC-9" in raw


# -- PendingAcks --------------------------------------------------------


def test_a_fresh_pending_message_is_not_due_before_its_retry_window():
    pending = PendingAcks(retry_seconds=30.0)
    pending.add("K1ABC-9", "1", "hello", now=0.0)
    assert pending.due(now=10.0) == []


def test_a_pending_message_is_due_after_its_retry_window():
    pending = PendingAcks(retry_seconds=30.0)
    pending.add("K1ABC-9", "1", "hello", now=0.0)
    assert pending.due(now=31.0) == [("K1ABC-9", "1", "hello")]


def test_due_reschedules_rather_than_repeating_immediately():
    pending = PendingAcks(retry_seconds=30.0, max_retries=5)
    pending.add("K1ABC-9", "1", "hello", now=0.0)
    assert pending.due(now=31.0) == [("K1ABC-9", "1", "hello")]
    assert pending.due(now=32.0) == []  # just retried, not due again yet
    assert pending.due(now=61.0) == [("K1ABC-9", "1", "hello")]


def test_a_message_is_dropped_after_max_retries():
    pending = PendingAcks(retry_seconds=10.0, max_retries=2)
    pending.add("K1ABC-9", "1", "hello", now=0.0)
    assert pending.due(now=11.0) == [("K1ABC-9", "1", "hello")]  # attempt 1
    assert pending.due(now=22.0) == [("K1ABC-9", "1", "hello")]  # attempt 2
    assert pending.due(now=33.0) == []  # max_retries used up, dropped


def test_discard_removes_a_pending_entry():
    pending = PendingAcks(retry_seconds=10.0)
    pending.add("K1ABC-9", "1", "hello", now=0.0)
    pending.discard("K1ABC-9", "1")
    assert pending.due(now=100.0) == []


def test_discard_for_drops_every_number_for_that_callsign_only():
    pending = PendingAcks(retry_seconds=10.0)
    pending.add("K1ABC-9", "1", "hello", now=0.0)
    pending.add("K1ABC-9", "2", "again", now=0.0)
    pending.add("K1XYZ", "1", "unrelated", now=0.0)
    pending.discard_for("K1ABC-9")
    assert pending.due(now=100.0) == [("K1XYZ", "1", "unrelated")]


def test_clear_drops_every_pending_entry():
    pending = PendingAcks(retry_seconds=10.0)
    pending.add("K1ABC-9", "1", "hello", now=0.0)
    pending.add("K1XYZ", "1", "unrelated", now=0.0)
    pending.clear()
    assert pending.due(now=100.0) == []


def test_discard_acked_stops_a_retry_once_the_store_shows_it_acked(tmp_path):
    store = ConversationStore(tmp_path / "aprs_messages.json")
    pending = PendingAcks(retry_seconds=10.0)
    store.record_outgoing("K1ABC-9", "hello", number="1")
    pending.add("K1ABC-9", "1", "hello", now=0.0)

    store.mark_acked("K1ABC-9", "1")
    pending.discard_acked(store)

    assert pending.due(now=100.0) == []


def test_discard_acked_leaves_an_unacked_message_alone(tmp_path):
    store = ConversationStore(tmp_path / "aprs_messages.json")
    pending = PendingAcks(retry_seconds=10.0)
    store.record_outgoing("K1ABC-9", "hello", number="1")
    pending.add("K1ABC-9", "1", "hello", now=0.0)

    pending.discard_acked(store)

    assert pending.due(now=100.0) == [("K1ABC-9", "1", "hello")]
