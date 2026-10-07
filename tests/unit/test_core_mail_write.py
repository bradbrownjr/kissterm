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


def test_a_form_opens_checks_and_files_with_its_xml_for_winlink_and_without_for_text_changes():
    core, _ = _core()
    assert {"ics213", "winlink_checkin"} <= {f["id"] for f in core.mail.forms_list()}
    start = core.mail.form_start("ics213")
    assert start["form"].id == "ics213" and start["form"].fields
    values = start["values"]
    # Nothing filled in: the form says what is needed and files nothing.
    found = core.mail.form_check("ics213", values)
    assert found["problems"] and "title" not in found
    needed = [f for f in start["form"].fields if f.required and f.kind != "rows"]
    for f in needed:
        values[f.id] = f.choices[0] if f.kind == "choice" else "W1AW" if f.id == "to" else "x"
    checked = core.mail.form_check("ics213", values)
    if checked["problems"]:  # a rule beyond "required": fill what it names
        raise AssertionError(checked["problems"])
    assert checked["body"].strip() and checked["title"]
    problems, folder, note = core.mail.write_form(
        form_id="ics213", values=values, to="KC1JMH", title=checked["title"],
        body=checked["body"], send_type="W")
    assert problems == [] and folder.endswith("Outbox") and note == ""
    store = core.mail.store
    mine = [x for x in store.list("Mail/Winlink/Outbox")
            if store.read(x.ref).extra.get("Form") == "ics213"]
    assert mine, "the form's id is kept as the Form header"
    assert any(p.suffix == ".xml" for x in mine for p in store.raw_files(x.ref))
    # The text edited after the form: it goes as text only, and says so.
    problems, folder, note = core.mail.write_form(
        form_id="ics213", values=values, to="KC1JMH", title=checked["title"],
        body=checked["body"] + "extra", send_type="W")
    assert problems == [] and "text only" in note
    # A problem with the message itself files nothing.
    problems, folder, note = core.mail.write_form(
        form_id="ics213", values=values, to="", title="", body="", send_type="W")
    assert problems and folder == ""


def test_the_mail_log_takes_the_mail_since_a_time_and_refuses_a_bad_time():
    core, _ = _core()
    bad = core.mail.form_mail_log("ics309", "log", "yesterday")
    assert bad["rows"] == [] and bad["problem"]
    assert core.mail.form_mail_log("ics309", "log", "2000-01-01")["problem"] == ""


def test_a_strip_is_answered_or_pasted_as_a_form_and_the_answer_files_as_a_reply():
    core, _ = _core()
    strip = "GYX WEATHER/Location/Sky//"
    ref = core.mail.store.add("Mail/BBS/Inbox", Message(
        sender="W1BKW", to="KC1JMH", subject="Wx request", source="BBS WS1EC",
        body=f"Please answer:\n{strip}\n", extra={"Bbs-Number": "3105"}))
    choices = core.mail.reply_choices(ref)
    assert choices == {"form": False, "strip": "strip:" + strip}
    start = core.mail.form_start(choices["strip"])
    assert start["key"] == choices["strip"] and start["form"].fields
    values = {f.id: "x" for f in start["form"].fields}
    checked = core.mail.form_check(start["key"], values)
    assert checked["problems"] == [] and checked["body"].strip()
    problems, folder, _note = core.mail.write_form(
        form_id=start["key"], values=values, to="", title="", body=checked["body"],
        send_type="P", reply_to=ref)
    assert problems == [] and folder == "Mail/BBS/Outbox", "an answer is a reply (SR to the number)"
    # Pasting is the first of two steps: it names the strip's questions.
    paste = core.mail.forms_list()[0]["id"]
    assert core.mail.form_check(paste, {"strip": "no strip here"})["problems"]
    assert core.mail.form_check(paste, {"strip": strip})["next_form"] == "strip:" + strip


def test_a_received_form_offers_its_reply_form_with_its_blocks_filled_in():
    import pytest

    core, _ = _core()
    start = core.mail.form_start("ics213")
    values = start["values"]
    for f in start["form"].fields:
        if f.required and f.kind != "rows":
            values[f.id] = f.choices[0] if f.kind == "choice" else "W1AW" if f.id == "to" else "x"
    made = core.mail.form_check("ics213", values)
    ref = core.mail.store.add("Mail/BBS/Inbox", Message(
        sender="W1BKW", to="KC1JMH", subject=made["title"], source="BBS WS1EC",
        body=made["body"], extra={"Form": "ics213", "Bbs-Number": "12"}))
    assert core.mail.reply_choices(ref)["form"] is True
    reply = core.mail.form_start("", reply_to=ref)
    assert reply["key"] == reply["form"].id != ""
    assert any(reply["values"].get(f.id) for f in reply["form"].fields), "the original's half"
    plain = core.mail.store.add("Mail/BBS/Inbox", Message(
        sender="W1BKW", to="KC1JMH", subject="Hi", source="BBS WS1EC", body="Hi\n"))
    with pytest.raises(ValueError):
        core.mail.form_start("", reply_to=plain)


def test_an_upload_is_kept_in_files_uploads_cleaned_and_never_replaces_a_file():
    import pytest

    core, seen = _core()
    ref = core.mail.save_upload("../../evil/..\\report?.txt", b"hello")
    assert ref == "Files/Uploads/report_.txt" and core.mail.store.file_path(ref).read_bytes() == b"hello"
    again = core.mail.save_upload("report?.txt", b"second")
    assert again == "Files/Uploads/report_-1.txt" and any(isinstance(e, MailChanged) for e in seen)
    with pytest.raises(ValueError):
        core.mail.save_upload("x", b"")
    with pytest.raises(ValueError):
        core.mail.save_upload("x", b"y" * (core.mail.MAX_UPLOAD + 1))


def test_bbs_messages_are_numbered_when_asked_and_a_number_is_never_reused_or_doubled():
    from kissterm.mail import numbering

    assert numbering.default_prefix("K6PE-7") == "6PE" and numbering.clean_prefix("a b-c!", "W1AW") == "ABC"
    core, _ = _core()
    core.config.message_numbering = True
    core.config.message_prefix = ""

    def titles() -> list[str]:
        store = core.mail.store
        return sorted(m.subject for m in (store.read(x.ref) for x in store.list("Mail/BBS/Outbox"))
                      if "Gauge reading" in m.subject)

    assert core.mail.write(to="W1BKW", title="Gauge reading", body="x")[0] == []
    assert titles() == ["JMH-1P: Gauge reading"]
    assert core.mail.write(to="W1BKW", title="Gauge reading", body="x")[0] == []
    assert titles() == ["JMH-1P: Gauge reading", "JMH-2P: Gauge reading"], "the number counts on"
    bulletin = core.mail.write(to="ALL", at="USA", title="Net tonight", body="x", send_type="B")
    assert bulletin[0] == []
    assert any(m.startswith("JMH-3B: Net tonight") for m in [
        core.mail.store.read(x.ref).subject for x in core.mail.store.list("Mail/BBS/Outbox")])
    # Never numbered: a title already numbered, a Winlink message, a long title is cut.
    assert numbering.applies({"Send-Type": "P"}, "JMH-2P: x") is False
    assert numbering.applies({"Send-Type": "W"}, "x") is False
    assert numbering.applies({"Send-Type": "P", "Form": "ics213"}, "x") is False
    assert numbering.applies({"Send-Type": "P", "Reply-Number": "3"}, "x") is False
    cut = numbering.numbered_title("JMH", 12, "P", "y" * 60)
    assert cut.startswith("JMH-12P: ") and len(cut) == 60


def test_numbering_is_off_by_default_and_a_bad_counter_file_never_blocks_filing(tmp_path):
    from kissterm.mail.numbering import Counter

    core, _ = _core()
    problems, folder = core.mail.write(to="W1BKW", title="Plain", body="x")
    assert problems == [] and [s.subject for s in core.mail.store.list(folder)
                               if s.subject == "Plain"]
    bad = tmp_path / "n.json"
    bad.write_text("not json")
    counter = Counter(bad)
    assert counter.take() == 1 and counter.take() == 2
