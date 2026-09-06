"""The station list behind the connect dialog."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import json  # noqa: E402

import pytest  # noqa: E402

from kissterm.addressbook import MAX_ENTRIES, AddressBook  # noqa: E402


@pytest.fixture
def book(tmp_path):
    return AddressBook(tmp_path / "addressbook.json")


def test_a_script_is_saved_alongside_the_attempt(book):
    book.record_attempt("WS1EC-7", script="C WS1EC-7\nCLYDE\nMYPASS")
    assert book.entries[0].script == "C WS1EC-7\nCLYDE\nMYPASS"


def test_a_blank_script_clears_a_previously_saved_one(book):
    """The Connect dialog's script field is the one place a script can be
    entered or removed -- reconnecting with it left blank has to actually
    clear a script the operator no longer wants, not silently keep the old
    one because nothing new was typed."""
    book.record_attempt("WS1EC-7", script="C WS1EC-7")
    book.record_attempt("WS1EC-7", script="")
    assert book.entries[0].script == ""


def test_a_hop_chain_and_credential_are_saved_alongside_the_attempt(book):
    """Node-to-node connect entries: an ordered list of intermediate nodes,
    and a live reference to a saved credential rather than typed text."""
    book.record_attempt("W1LH-6", hops="N1QFY, AB1KI-15", credential="Personal BBS login")
    entry = book.entries[0]
    assert entry.hops == "N1QFY, AB1KI-15"
    assert entry.credential == "Personal BBS login"
    assert entry.script == ""  # a credential reference, not literal text


def test_an_attempt_is_remembered_even_though_it_failed(book):
    """The case this was built for: a connect that got no answer is the one
    you are about to try again. Waiting for a UA to record it would withhold
    the entry at the moment it is most wanted."""
    book.record_attempt("WS1EC-15")
    assert [e.target for e in book.entries] == ["WS1EC-15"]
    assert book.entries[0].attempts == 1
    assert book.entries[0].connects == 0
    assert "never connected" in book.entries[0].summary


def test_attempts_and_connects_are_counted_separately(book):
    for _ in range(3):
        book.record_attempt("WS1EC-15")
    book.record_connect("WS1EC-15")
    entry = book.entries[0]
    assert (entry.attempts, entry.connects) == (3, 1)
    assert entry.summary == "connected 1x"


def test_the_most_recent_station_comes_first(book):
    book.record_attempt("W1AW-1")
    book.record_attempt("WS1EC-7")
    book.record_attempt("W1AW-1")
    assert [e.target for e in book.entries] == ["W1AW-1", "WS1EC-7"]


def test_case_does_not_create_a_second_entry(book):
    """Callsigns are conventionally upper case; `ws1ec-7` is the same station.
    Two entries for one node is how a list becomes useless."""
    book.record_attempt("ws1ec-7")
    book.record_attempt("WS1EC-7")
    assert len(book.entries) == 1
    assert book.entries[0].target == "WS1EC-7", "the newer spelling should win"
    assert book.entries[0].attempts == 2


def test_a_digipeater_path_is_kept_exactly_as_typed(book):
    """What goes back into the dialog has to be what worked -- re-rendering a
    parsed path is a chance to render it differently from how it was entered."""
    book.record_attempt("WS1EC-7 via W1AW-1,W1XYZ")
    assert book.entries[0].target == "WS1EC-7 via W1AW-1,W1XYZ"


def test_upsert_creates_an_entry_with_no_attempts(book):
    """Setting up a station in advance in Settings > Address Book is not an
    attempt to reach it."""
    book.upsert("WS1EC-7", script="CLYDE", hops="N1QFY")
    entry = book.entries[0]
    assert entry.target == "WS1EC-7"
    assert entry.script == "CLYDE"
    assert entry.hops == "N1QFY"
    assert entry.attempts == 0
    assert entry.connects == 0


def test_upsert_edits_in_place_without_touching_counters(book):
    book.record_attempt("WS1EC-7")
    book.record_connect("WS1EC-7")
    book.upsert("WS1EC-7", script="NEWSCRIPT", original_target="WS1EC-7")
    entry = book.entries[0]
    assert entry.script == "NEWSCRIPT"
    assert entry.attempts == 1
    assert entry.connects == 1


def test_upsert_renaming_the_target_does_not_leave_a_stale_duplicate(book):
    """`_touch` matches targets as whole strings, so a rename is a
    different key to it -- upsert has to explicitly drop the old spelling
    or it survives as a second, orphaned entry. The rename starts fresh
    (a different string is a different entry everywhere else in this
    class too), it just must not leave the old one behind as well."""
    book.record_attempt("WS1EC-7")
    book.record_connect("WS1EC-7")
    book.upsert("WS1EC-7 via W1AW-1", original_target="WS1EC-7")
    assert [e.target for e in book.entries] == ["WS1EC-7 via W1AW-1"]


def test_forget_removes_a_row_and_reports_it(book):
    book.record_attempt("WS1EC-7")
    book.record_attempt("W1AW-1")
    assert book.forget("WS1EC-7") is True
    assert [e.target for e in book.entries] == ["W1AW-1"]
    assert book.forget("WS1EC-7") is False


def test_the_list_is_capped(book):
    for i in range(MAX_ENTRIES + 20):
        book.record_attempt(f"N{i}ABC-1")
    assert len(book.entries) == MAX_ENTRIES
    assert book.entries[0].target == f"N{MAX_ENTRIES + 19}ABC-1"


def test_it_survives_a_round_trip(tmp_path):
    first = AddressBook(tmp_path / "addressbook.json")
    first.record_attempt("WS1EC-15", script="C WS1EC-15\nCLYDE")
    first.record_attempt("W1LH-6", hops="N1QFY, AB1KI-15", credential="Personal BBS login")
    first.record_connect("W1AW-1")

    second = AddressBook(tmp_path / "addressbook.json")
    second.load()
    assert [e.target for e in second.entries] == ["W1AW-1", "W1LH-6", "WS1EC-15"]
    assert second.entries[0].connects == 1
    assert second.entries[1].hops == "N1QFY, AB1KI-15"
    assert second.entries[1].credential == "Personal BBS login"
    assert second.entries[2].script == "C WS1EC-15\nCLYDE"


def test_a_missing_file_is_not_an_error(tmp_path):
    book = AddressBook(tmp_path / "nothing-here.json")
    book.load()
    assert book.entries == []


def test_a_corrupt_file_costs_the_history_and_nothing_else(tmp_path):
    """A station list is a convenience. Failing to read one must never stop
    the app from starting."""
    path = tmp_path / "addressbook.json"
    path.write_text("{not json at all", "utf-8")
    book = AddressBook(path)
    book.load()
    assert book.entries == []
    book.record_attempt("WS1EC-7")
    assert json.loads(path.read_text("utf-8"))[0]["target"] == "WS1EC-7"


def test_junk_rows_are_skipped_not_fatal(tmp_path):
    path = tmp_path / "addressbook.json"
    path.write_text(
        json.dumps([{"target": "WS1EC-7"}, "nonsense", {"no_target": 1}, {"target": ""}]),
        "utf-8",
    )
    book = AddressBook(path)
    book.load()
    assert [e.target for e in book.entries] == ["WS1EC-7"]


def test_an_unwritable_location_does_not_raise(tmp_path):
    """Saving happens in the middle of a connect. It must not be able to take
    that connect down."""
    path = tmp_path / "a-file"
    path.write_text("blocking the directory", "utf-8")
    book = AddressBook(path / "addressbook.json")
    book.record_attempt("WS1EC-7")  # must not raise
    assert book.entries[0].target == "WS1EC-7"
