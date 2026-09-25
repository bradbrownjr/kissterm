"""Composing BBS mail (`kissterm/mail/compose.py`): BPQMail's limits, reply
quoting, and the command a draft goes out with."""

from kissterm import _isolate

_isolate.isolate()

from datetime import datetime, timezone  # noqa: E402

from kissterm.mail import Message, MessageStore  # noqa: E402
from kissterm.mail.compose import (  # noqa: E402
    SEND_BULLETIN,
    can_reply_by_number,
    check,
    ends_text_early,
    outbox_message,
    quote,
    reply_title,
    send_command,
)

WHEN = datetime(2026, 9, 24, 20, 35, tzinfo=timezone.utc)
DAVE = Message(sender="KC1UIX", to="KC1JMH", subject="Test message", date=WHEN,
               source="BBS WS1EC", body="This was sent to kc1jmh.\nRegards,\nDave\n",
               extra={"Bbs-Number": "2784", "Bbs-Type": "PN"})


def test_a_good_message_passes():
    assert check("W1BKW", "", "Received your radiogram", "Hi Brian,\n\n73") == []


def test_bpqmail_limits_are_checked_before_saving():
    assert any("SSID" in p for p in check("KC1JMH-7", "", "t", "x"))
    assert any("6 characters" in p for p in check("KC1JMHX", "", "t", "x"))
    assert any("cancel" in p for p in check("W1BKW", "", "  ", "x"))
    assert any("60" in p for p in check("W1BKW", "", "x" * 61, "x"))
    assert any("40" in p for p in check("W1BKW", "A" * 41, "t", "x"))
    assert any("no text" in p for p in check("W1BKW", "", "t", "\n\n"))


def test_a_line_that_would_end_the_text_is_refused():
    assert ends_text_early("/EX") and ends_text_early("  /ex ") and ends_text_early("\x1afoo")
    assert not ends_text_early("see /ex below")
    [problem] = check("W1BKW", "", "t", "one\n/Ex\nthree")
    assert "Line 2" in problem


def test_an_sr_reply_skips_the_to_and_title_checks():
    assert check("", "", "", "Thanks", reply_by_number=True) == []


def test_reply_title_and_quote():
    assert reply_title("Test message") == "Re:Test message"  # as BPQMail's SR
    assert reply_title("RE: already") == "RE: already"
    assert len(reply_title("x" * 80)) == 60
    text = quote(DAVE)
    assert text.startswith("On 2026-09-24 20:35Z, KC1UIX wrote:\n> This was sent")
    assert "> Dave" in text


def test_a_reply_goes_out_as_sr_only_on_its_own_bbs():
    assert can_reply_by_number(DAVE)
    reply = outbox_message(sender="kc1jmh", to="KC1UIX", at="", title=reply_title(DAVE.subject),
                           body="Thanks\n", reply_to=DAVE, now=WHEN)
    assert send_command(reply, "BBS WS1EC") == ("SR 2784", False)
    # Elsewhere the number means nothing: an ordinary private message.
    assert send_command(reply, "BBS N1XYZ") == ("SP KC1UIX", True)


def test_new_messages_and_bulletins():
    private = outbox_message(sender="KC1JMH", to="w1bkw", at="w1bkw.#oxfo.me.usa.noam",
                             title="Hello", body="Hi\r\n\tthere\x07\n")
    assert send_command(private, "BBS WS1EC") == ("SP W1BKW @ W1BKW.#OXFO.ME.USA.NOAM", True)
    assert private.body == "Hi\n    there\n"  # CRLF, tab and BEL cleaned
    bulletin = outbox_message(sender="KC1JMH", to="WX", at="ALLUS", title="Storm",
                              body="Watch out\n", send_type=SEND_BULLETIN)
    assert send_command(bulletin, "BBS WS1EC") == ("SB WX @ ALLUS", True)


def test_an_outbox_message_round_trips_through_the_store(tmp_path):
    store = MessageStore(tmp_path / "mail")
    store.ensure_default_tree()
    reply = outbox_message(sender="KC1JMH", to="KC1UIX", at="", title="Re:Test message",
                           body="Thanks\n", reply_to=DAVE, now=WHEN)
    ref = store.add("Mail/BBS/Outbox", reply)
    back = store.read(ref)
    assert back.extra["Reply-Number"] == "2784" and back.extra["Send-Type"] == "P"
    assert send_command(back, "BBS WS1EC") == ("SR 2784", False)
