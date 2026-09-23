"""The message store (`kissterm/mail/`): plain files, a rebuildable index,
Deleted as a folder, raw copies that travel with their message."""

from kissterm import _isolate

_isolate.isolate()

import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402

from kissterm import config  # noqa: E402
from kissterm.mail import KIND_BULLETIN, Message, MessageStore, check_folder  # noqa: E402
from kissterm.mail.message import format_message, parse_message  # noqa: E402
from kissterm.mail.store import ALL_INBOXES, INDEX_NAME  # noqa: E402

WHEN = datetime(2026, 9, 23, 18, 0, 0, tzinfo=timezone.utc)
INBOX = "Mail/BBS/Inbox"


def _msg(**kw) -> Message:
    base = dict(sender="KC1JMH", to="WS1EC", subject="Net tonight", date=WHEN, body="Hello\n")
    base.update(kw)
    return Message(**base)


@pytest.fixture
def store(tmp_path):
    s = MessageStore(tmp_path / "mail")
    s.ensure_default_tree()
    return s


def test_mail_path_is_under_the_isolated_data_dir():
    assert config.mail_path() == config.state_path() / "mail"


# -- the file format ---------------------------------------------------------


def test_a_message_round_trips_through_its_file():
    m = _msg(
        message_id="12345_WS1EC",
        source="BBS WS1EC",
        kind=KIND_BULLETIN,
        category="WX",
        expires=WHEN + timedelta(days=7),
        extra={"X-Bbs-Number": "2738"},
    )
    back = parse_message(format_message(m).encode("utf-8"))
    assert back == m


def test_the_file_is_readable_text():
    text = format_message(_msg())
    assert text == (
        "From: KC1JMH\nTo: WS1EC\nSubject: Net tonight\n"
        "Date: 2026-09-23T18:00:00Z\n\nHello\n"
    )


def test_a_newline_in_a_header_cannot_forge_another():
    m = _msg(subject="hi\r\nStatus: read\n\nfake body")
    back = parse_message(format_message(m))
    assert back.status == "new"
    assert back.subject == "hi Status: read fake body"
    assert back.body == "Hello\n"


def test_a_file_without_headers_is_all_body():
    back = parse_message(b"Just a note the operator dropped in.\nSecond line\n")
    assert back.sender == ""
    assert back.body.startswith("Just a note")


def test_non_utf8_bytes_decode_as_latin1():
    back = parse_message(b"Subject: caf\xe9\n\nbody")
    assert back.subject == "café"


# -- folders -----------------------------------------------------------------


@pytest.mark.parametrize(
    "bad", ["", "..", "Mail/../x", "/etc", ".hidden", "Mail/.x", "a/b\x00", "Inbox.", "a:b"]
)
def test_unsafe_folder_names_are_refused(bad):
    with pytest.raises(ValueError):
        check_folder(bad)


def test_default_tree_has_no_folder_per_source(store):
    folders = store.folders()
    for f in ("Mail/Winlink/Inbox", "Files/Attachments",
              INBOX, "Mail/BBS/Outbox", "Bulletins/Deleted"):
        assert f in folders
    # Local is P9's mailbox and appears only once that ships.
    assert not any(f.startswith("Mail/Local") for f in folders)


def test_all_inboxes_is_a_view_over_every_mail_inbox(store):
    store.add(INBOX, _msg(subject="bbs", date=WHEN - timedelta(hours=1)))
    store.add("Mail/Winlink/Inbox", _msg(subject="winlink"))
    store.add("Mail/BBS/Sent", _msg(subject="sent"))
    store.add("Bulletins/WX", _msg(subject="wx", kind=KIND_BULLETIN))
    assert [s.subject for s in store.list_inboxes()] == ["winlink", "bbs"]
    assert [s.folder for s in store.list_inboxes()] == ["Mail/Winlink/Inbox", INBOX]
    with pytest.raises(ValueError):
        check_folder(ALL_INBOXES)


# -- add, list, read ---------------------------------------------------------


def test_add_writes_a_dated_file_and_lists_newest_first(store):
    older = store.add(INBOX, _msg(date=WHEN - timedelta(hours=1), subject="old"))
    newer = store.add(INBOX, _msg(subject="new"))
    assert newer.endswith("20260923-180000_KC1JMH.txt")
    assert [s.subject for s in store.list(INBOX)] == ["new", "old"]
    assert store.read(older).subject == "old"
    assert store.unread_count(INBOX) == 2


def test_same_second_same_sender_gets_a_distinct_name(store):
    a = store.add(INBOX, _msg())
    b = store.add(INBOX, _msg())
    assert a != b and b.endswith("-2.txt")


def test_raw_copy_is_kept_beside_the_message(store):
    ref = store.add(INBOX, _msg(), raw=b"\x01raw b2f\x00", raw_suffix=".b2f")
    (raw,) = store.raw_files(ref)
    assert raw.suffix == ".b2f" and raw.read_bytes() == b"\x01raw b2f\x00"


def test_set_read(store):
    ref = store.add(INBOX, _msg())
    store.set_read(ref)
    assert store.list(INBOX)[0].is_read
    assert store.unread_count(INBOX) == 0


# -- delete, restore, purge --------------------------------------------------


def test_delete_moves_to_deleted_and_restore_moves_back(store):
    ref = store.add(INBOX, _msg(), raw=b"raw")
    gone = store.delete(ref)
    assert gone.startswith("Mail/BBS/Deleted/")
    assert store.list(INBOX) == []
    assert store.read(gone).deleted_from == INBOX
    assert len(store.raw_files(gone)) == 1

    back = store.restore(gone)
    assert back.startswith(INBOX + "/")
    assert store.read(back).deleted_from == ""
    assert len(store.raw_files(back)) == 1
    assert store.list("Mail/BBS/Deleted") == []


def test_purge_only_from_deleted(store):
    ref = store.add(INBOX, _msg(), raw=b"raw")
    with pytest.raises(ValueError):
        store.purge(ref)
    gone = store.delete(ref)
    with pytest.raises(ValueError):
        store.delete(gone)
    store.purge(gone)
    deleted_dir = store.root / "Mail/BBS/Deleted"
    assert list(deleted_dir.iterdir()) == []


def test_restore_without_a_record_goes_to_the_inbox(store):
    ref = store.add("Mail/BBS/Deleted", _msg())
    assert store.restore(ref).startswith(INBOX + "/")


def test_refs_cannot_leave_the_root(store):
    for bad in ("../x.txt", "/etc/passwd.txt", "Mail/../../x.txt", "Mail/x.b2f", "Mail/.i.txt"):
        with pytest.raises(ValueError):
            store.read(bad)


# -- the index is only a cache -----------------------------------------------


def test_index_rebuilds_from_the_files(store):
    ref = store.add(INBOX, _msg(message_id="MID1"))
    index = store.root / INDEX_NAME
    assert index.exists()
    index.write_text("{not json")
    fresh = MessageStore(store.root)
    assert [s.ref for s in fresh.list(INBOX)] == [ref]
    assert json.loads(index.read_text())["messages"][ref]["summary"]["message_id"] == "MID1"


def test_a_file_edited_by_hand_is_picked_up(store):
    ref = store.add(INBOX, _msg())
    path = store.root / ref
    path.write_text(path.read_text().replace("Net tonight", "Changed"))
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert store.list(INBOX)[0].subject == "Changed"


def test_a_file_dropped_in_by_hand_is_listed(store):
    (store.root / INBOX / "note.txt").write_text("From: N0CALL\n\nhi\n")
    assert [s.sender for s in store.list(INBOX)] == ["N0CALL"]


def test_symlinks_and_dotfiles_are_skipped(store, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("From: EVIL\n\nx")
    (store.root / INBOX / "link.txt").symlink_to(outside)
    (store.root / INBOX / ".hidden.txt").write_text("From: HIDDEN\n\nx")
    assert store.list(INBOX) == []


# -- lookups -----------------------------------------------------------------


def test_find_by_message_id_spans_routes_and_deleted(store):
    # One BBS reached two ways files into one Inbox; the second read is a dup.
    ref = store.add(INBOX, _msg(message_id="2738", source="BBS WS1EC"))
    assert len(store.find("2738", source="BBS WS1EC")) == 1
    assert store.find("2738", source="BBS N0BBS") == []
    store.delete(ref)
    assert len(store.find("2738", source="BBS WS1EC")) == 1
    assert store.find("") == []


def test_expired_bulletins(store):
    wx = "Bulletins/WX"
    store.add(wx, _msg(kind=KIND_BULLETIN, category="WX", expires=WHEN))
    store.add(wx, _msg(kind=KIND_BULLETIN, category="WX", expires=WHEN + timedelta(days=9)))
    store.add(INBOX, _msg(expires=WHEN))  # mail with an Expires header is still mail
    assert len(store.expired(now=WHEN + timedelta(days=1))) == 1
