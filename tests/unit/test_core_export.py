"""Save as text (`core/export.py`): one message, conversation or session as
a plain-text file, the same text for every front end."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from kissterm._isolate import isolate

isolate()

from kissterm.aprs_conversations import Conversation, MessageEntry  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.core.export import Exporter, save  # noqa: E402
from kissterm.core.sessions import SCREEN_LIMIT, LiveSession, Sessions  # noqa: E402
from kissterm.mail.message import KIND_BULLETIN, Message  # noqa: E402
from kissterm.mail.store import MessageStore  # noqa: E402


def _core(tmp_path, *, sessions=None, conversations=None, heard=()):
    store = MessageStore(tmp_path / "mail")
    mail = SimpleNamespace(store=store, routing=lambda ref: [])
    return SimpleNamespace(
        mail=mail, config=Config(mycall="KC1JMH"),
        aprs=SimpleNamespace(conversations=SimpleNamespace(conversations=conversations or {})),
        broadcast=SimpleNamespace(recent=lambda: list(heard)),
        sessions=sessions)


def test_a_mail_message_is_its_headers_then_its_body(tmp_path):
    core = _core(tmp_path)
    ref = core.mail.store.add("Mail/Inbox", Message(
        sender="W1AW", to="KC1JMH", subject="Net report: 9 Oct",
        date=datetime(2026, 10, 9, 23, 5, tzinfo=timezone.utc),
        body="Ten check-ins.\r\nNo traffic.", source="BBS WS1EC"))
    core.mail.routing = lambda r: ["R:261009/2305Z @:WS1EC.#CUMB.ME.USA.NOAM"]
    made = Exporter(core).mail(ref)
    assert made.name == "mail-w1aw-2026-10-09-net-report-9-oct.txt"
    assert made.text == ("From: W1AW\nTo: KC1JMH\nDate: 2026-10-09 23:05Z\n"
                         "Subject: Net report: 9 Oct\nSource: BBS WS1EC\n\n"
                         "R:261009/2305Z @:WS1EC.#CUMB.ME.USA.NOAM\n\n"
                         "Ten check-ins.\nNo traffic.\n")


def test_a_bulletin_is_addressed_to_its_category_and_named_a_bulletin(tmp_path):
    core = _core(tmp_path)
    ref = core.mail.store.add("Bulletins/WX", Message(
        sender="N1XYZ", to="WX@ALLUS", category="WX", kind=KIND_BULLETIN,
        subject="Wind ../../etc", body="Gusts to 40."))
    made = Exporter(core).mail(ref)
    assert made.name.startswith("bulletin-n1xyz-") and "/" not in made.name
    assert made.text.startswith("From: N1XYZ\nTo: WX\n")


def test_an_aprs_conversation_is_oldest_first_with_who_and_acks(tmp_path):
    convo = Conversation("W1BKW", [
        MessageEntry("in", "Are you on the net?", timestamp=1_760_000_000.0),
        MessageEntry("out", "Yes, checking in", timestamp=1_760_000_060.0,
                     number="12", acked=True),
        MessageEntry("out", "73", timestamp=1_760_000_120.0, number="13")])
    made = Exporter(_core(tmp_path, conversations={"W1BKW": convo})).aprs("w1bkw")
    assert made.name.startswith("aprs-w1bkw-")
    lines = made.text.splitlines()
    assert lines[0] == "APRS messages with W1BKW"
    assert lines[2].endswith("W1BKW: Are you on the net?")
    assert lines[3].endswith("KC1JMH: Yes, checking in  [acked]")
    assert lines[4].endswith("KC1JMH: 73  [not acked]")
    with pytest.raises(KeyError):
        Exporter(_core(tmp_path)).aprs("N0ONE")


def test_a_session_is_what_its_tab_shows_received_and_sent(tmp_path):
    sessions = Sessions.__new__(Sessions)
    sessions.by_key = {"WS1EC-15": LiveSession()}
    session = sessions.by_key["WS1EC-15"]
    sessions._publish = lambda event: None
    sessions.log_sent = lambda *a, **k: None
    Sessions.keep_screen(session, "Hello Bradley\nde WS1EC>")
    sessions.echo_sent("WS1EC-15", "B", "B")
    Sessions.keep_screen(session, "73\n")
    made = Exporter(_core(tmp_path, sessions=sessions)).session("WS1EC-15")
    assert made.name.startswith("session-ws1ec-15-")
    assert made.text == "Hello Bradley\nde WS1EC>\nB\n73\n"
    with pytest.raises(KeyError):
        Exporter(_core(tmp_path, sessions=sessions)).session("N0ONE")


def test_a_session_keeps_only_its_last_megabyte():
    session = LiveSession()
    Sessions.keep_screen(session, "a" * SCREEN_LIMIT)
    Sessions.keep_screen(session, "end")
    assert len(session.screen) == SCREEN_LIMIT and session.screen.endswith("end")


def test_the_broadcast_tab_is_its_heard_and_sent_lines(tmp_path):
    heard = [{"source": "W1BKW", "to": "CQ", "text": "Net at 7", "at": 1_760_000_000.0,
              "own": False},
             {"source": "KC1JMH-7", "to": "QST", "text": "Checking in", "at": 1_760_000_060.0,
              "own": True}]
    made = Exporter(_core(tmp_path, heard=heard)).session("")
    assert made.name.startswith("broadcast-")
    assert [line.split("  ", 1)[1] for line in made.text.splitlines()] == [
        "W1BKW > CQ: Net at 7", "KC1JMH-7 > QST: Checking in"]


def test_save_writes_into_a_folder_or_to_a_path_and_makes_the_folder(tmp_path):
    made = Exporter(_core(tmp_path)).session("")
    folder = tmp_path / "out"
    folder.mkdir()
    assert save(made, folder) == folder / made.name
    deep = tmp_path / "a" / "b" / "report.txt"
    assert save(made, deep) == deep and deep.read_text() == made.text
