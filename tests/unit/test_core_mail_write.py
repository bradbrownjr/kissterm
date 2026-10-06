"""Writing, deleting and restoring mail in the core (`Mail.reply_start`,
`write`, `file_outbox`, `delete`, `restore`): one way for the terminal and
the phone (AGENTS.md: the front ends have parity). Nothing here transmits."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

from kissterm.config import Config  # noqa: E402
from kissterm.core import Core  # noqa: E402
from kissterm.core.events import MailChanged  # noqa: E402
from kissterm.mail.compose import has_others, reply_all_to  # noqa: E402
from kissterm.mail.message import Message  # noqa: E402


def _core() -> tuple[Core, list]:
    core = Core(Config(mycall="KC1JMH-7"), None)
    seen: list = []
    core.events.subscribe(lambda _seq, event: seen.append(event))
    return core, seen


def _winlink(**extra) -> Message:
    return Message(sender="W1AW", to="KC1JMH, N1ABC", subject="Net tonight", source="Winlink",
                   body="See you at 7\n", extra=dict(extra))


def test_reply_all_is_everyone_but_me_once():
    original = _winlink(Cc="kc1jmh@winlink.org, K1XYZ, n1abc")
    assert reply_all_to(original, "KC1JMH-7") == "W1AW, N1ABC, K1XYZ"
    assert has_others(original, "KC1JMH-7")
    bbs = Message(sender="W1BKW", to="KC1JMH", source="BBS WS1EC", subject="Hi")
    assert reply_all_to(bbs, "KC1JMH") == "W1BKW" and not has_others(bbs, "KC1JMH")


def test_a_reply_starts_addressed_titled_and_quoted_when_asked():
    core, _ = _core()
    ref = core.mail.store.add("Mail/Winlink/Inbox", _winlink())
    plain = core.mail.reply_start(ref)
    assert (plain.to, plain.title, plain.body, plain.send_type) == ("W1AW", "Re:Net tonight", "", "W")
    everyone = core.mail.reply_start(ref, quoted=True, everyone=True)
    assert everyone.to == "W1AW, N1ABC"
    assert everyone.body.startswith("\n\nOn ") and "> See you at 7" in everyone.body


def test_a_bbs_reply_by_number_says_the_bbs_addresses_it():
    core, _ = _core()
    ref = core.mail.store.add("Mail/BBS/Inbox", Message(
        sender="W1BKW", to="KC1JMH", subject="Hello", source="BBS WS1EC", body="Hi\n",
        extra={"Bbs-Number": "3105"}))
    start = core.mail.reply_start(ref)
    assert start.by_number and "SR 3105" in start.note and start.heading.startswith("Reply to #3105")


def test_write_files_in_the_outbox_or_says_why_not():
    core, seen = _core()
    problems, folder = core.mail.write(to="W1BKW-7", title="Hi", body="Hello")
    assert folder == "" and "SSID" in problems[0], "BPQMail would drop the SSID"
    assert not [e for e in seen if isinstance(e, MailChanged)]

    problems, folder = core.mail.write(to="w1bkw", title="Hi", body="Hello")
    assert problems == [] and folder == "Mail/BBS/Outbox"
    [summary] = [s for s in core.mail.store.list(folder) if s.subject == "Hi"]
    message = core.mail.store.read(summary.ref)
    assert (message.sender, message.to, message.extra["Send-Type"]) == ("KC1JMH-7", "W1BKW", "P")
    assert [e for e in seen if isinstance(e, MailChanged)]

    problems, folder = core.mail.write(to="W1AW, n0call@example.com", title="Hi",
                                       body="Hello", send_type="W")
    assert problems == [] and folder == "Mail/Winlink/Outbox"


def test_a_reply_goes_as_its_originals_kind():
    core, _ = _core()
    ref = core.mail.store.add("Mail/Winlink/Inbox", _winlink())
    problems, folder = core.mail.write(to="W1AW, N1ABC", title="Re:Net tonight", body="Yes",
                                       send_type="P", reply_to=ref)
    assert problems == [] and folder == "Mail/Winlink/Outbox"


def test_delete_then_restore_puts_it_back():
    core, seen = _core()
    ref = core.mail.store.add("Mail/BBS/Inbox", Message(sender="W1BKW", subject="Gone", body="x\n"))
    gone = core.mail.delete(ref)
    assert gone.startswith("Mail/BBS/Deleted/")
    back = core.mail.restore(gone)
    assert back.startswith("Mail/BBS/Inbox/")
    assert len([e for e in seen if isinstance(e, MailChanged)]) == 2


# ----------------------------------------------------------------------
# Radiograms: the terminal's form and the phone's check and save the same
# way (operator, 2026-10-06: "New Message lacks NTS").
# ----------------------------------------------------------------------

GRAM = {"number": "7", "precedence": "R", "handling": "", "origin": "KC1JMH",
        "place": "WATERBORO ME", "to_name": "JOHN SMITH", "to_street": "1 MAIN ST",
        "to_city": "RIVER CITY", "to_state": "MD", "to_zip": "00789",
        "to_phone": "301 555 3470", "text": "Arrived safely. Love", "signature": "JANE"}


def test_a_new_radiogram_starts_numbered_from_this_station():
    core, _ = _core()
    start = core.mail.radiogram_start()
    # The next number after any already in the Outbox or Sent (other
    # tests share this store), from this station without its SSID.
    assert start["number"].isdigit() and int(start["number"]) >= 1
    assert (start["origin"], start["handling"]) == ("KC1JMH", "")
    assert ["R", "Routine"] in start["precedences"] and start["arl"]
    assert core.mail.radiogram_start(ics213=True)["handling"] == "HXI"


def test_a_radiogram_check_shows_what_the_form_shows():
    core, _ = _core()
    result = core.mail.radiogram_check(GRAM)
    assert result["text"] == "ARRIVED SAFELY X LOVE"
    assert result["live"] == "ARRIVED SAFELY X LOVE "
    assert result["check"] == "4" and result["route"] == "ST 00789 @ NTSMD"
    assert result["problems"] == []
    assert core.mail.radiogram_check({**GRAM, "to_zip": ""})["problems"]


def test_a_radiogram_is_filed_in_the_bbs_outbox_or_says_why_not():
    core, seen = _core()
    problems, folder = core.mail.write_radiogram({**GRAM, "to_state": ""})
    assert folder == "" and any("State" in p for p in problems)
    problems, folder = core.mail.write_radiogram(GRAM)
    assert (problems, folder) == ([], "Mail/BBS/Outbox")
    [summary] = [s for s in core.mail.store.list("Mail/BBS/Outbox") if s.to == "00789"]
    message = core.mail.store.read(summary.ref)
    assert message.to == "00789" and message.extra["Send-At"] == "NTSMD"
    assert message.extra["Send-Type"] == "T" and any(isinstance(e, MailChanged) for e in seen)
    assert int(core.mail.radiogram_start()["number"]) >= 8, "the next one counts on"
