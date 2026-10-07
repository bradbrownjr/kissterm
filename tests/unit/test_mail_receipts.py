"""Outpost-style delivery and read receipts (`kissterm/mail/receipts.py`).
The wire shapes are from github.com/rothskeller/packet (v4)
`message/receipt` and `message/payload/outpost.go`, whose own test message
is reproduced below."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

from datetime import datetime  # noqa: E402

from kissterm.config import Config  # noqa: E402
from kissterm.core import Core  # noqa: E402
from kissterm.mail import receipts  # noqa: E402
from kissterm.mail.collect import BbsCollector  # noqa: E402
from kissterm.mail.message import Message  # noqa: E402

WHEN = datetime(2022, 1, 9, 20, 0)


def test_request_flags_are_read_off_the_front_of_the_body_and_only_there():
    assert receipts.request_flags(True, True) == "!RDR!!RRR!"
    assert receipts.split_requests("!RDR!Hello\nthere\n") == (True, False, "Hello\nthere\n")
    assert receipts.split_requests("\n!URG!!RRR!!RDR!Hi\n") == (True, True, "Hi\n")
    assert receipts.split_requests("Hello !RDR! not a flag\n") == (False, False, "Hello !RDR! not a flag\n")
    body = "!B64!SGVsbG8=\n"
    assert receipts.split_requests(body) == (False, False, body), "Base64 is left alone"


def test_the_receipts_have_outposts_text_and_are_recognised_back():
    title, body = receipts.delivery_receipt(
        local_id="XXX-123P", to="kc6rsc@w1xsc.ampr.org", subject="RSC-100P_R_Hello", when=WHEN)
    assert title == "DELIVERED: RSC-100P_R_Hello"
    assert body == ("!LMI!XXX-123P!DR!01/09/2022 20:00\nYour Message\nTo: kc6rsc@w1xsc.ampr.org\n"
                    "Subject: RSC-100P_R_Hello\nwas delivered on 01/09/2022 20:00\n"
                    "Recipient's Local Message ID: XXX-123P\n")
    assert receipts.receipt_kind(title, body) == "delivered"
    title, body = receipts.read_receipt(to="W1BKW", subject="Net", when=WHEN)
    assert title == "READ: Net"
    assert body == "!RR!01/09/2022 20:00\nYour Message\n\nTo: W1BKW\nSubject: Net\n\nwas read on 01/09/2022 20:00\n"
    assert receipts.receipt_kind(title, body) == "read"
    assert receipts.receipt_kind("Hello", "!RR!x") == ""
    assert len(receipts.delivery_receipt(local_id="A-1P", to="x", subject="y" * 80, when=WHEN)[0]) <= 60
    for bad in ("", "a!b", "a\nb"):
        try:
            receipts.delivery_receipt(local_id=bad, to="x", subject="y", when=WHEN)
        except ValueError:
            continue
        raise AssertionError(bad)


def _core(**config) -> Core:
    return Core(Config(mycall="KC1JMH-7", **config), None)


def _inbound(core: Core, *, flags: str = "!RDR!!RRR!", sender: str = "W1BKW", number: str = "3105") -> str:
    message = Message(sender=sender, to="KC1JMH", subject="Dam status", source="BBS WS1EC",
                      body=flags + "Water is high.\n", extra={"Bbs-Number": number, "Bbs-Type": "PN"},
                      message_id="BID" + number)
    BbsCollector._note_receipts(message)
    return core.mail.store.add("Mail/BBS/Inbox", message)


def test_collecting_moves_the_flags_into_headers_and_marks_a_receipt():
    core = _core()
    ref = _inbound(core)
    got = core.mail.store.read(ref)
    assert got.body == "Water is high.\n" and got.extra["Request-DR"] == "Y" and got.extra["Request-RR"] == "Y"
    title, body = receipts.delivery_receipt(local_id="X-1P", to="a", subject="b", when=WHEN)
    receipt = Message(sender="W1BKW", subject=title, body=body)
    BbsCollector._note_receipts(receipt)
    assert receipt.extra["Receipt"] == "delivered"


def _outbox(core: Core) -> list[Message]:
    store = core.mail.store
    return [store.read(s.ref) for s in store.list("Mail/BBS/Outbox")]


def test_a_delivery_request_is_answered_into_the_outbox_once_and_only_when_enabled():
    off = _core()
    ref = _inbound(off)
    before = len(_outbox(off))
    assert off.mail.answer_receipts([ref]) == 0 and len(_outbox(off)) == before
    core = _core(receipt_answer_delivery=True)
    ref = _inbound(core, number="3106")
    assert core.mail.answer_receipts([ref]) == 1
    [queued] = [m for m in _outbox(core) if m.subject == "DELIVERED: Dam status" and "JMH-3106P" in m.body]
    assert queued.to == "W1BKW" and queued.subject == "DELIVERED: Dam status"
    assert queued.body.startswith("!LMI!JMH-3106P!DR!") and queued.extra["Receipt"] == "delivered"
    assert queued.extra["Send-Type"] == "P"
    count = len(_outbox(core))
    assert core.mail.answer_receipts([ref]) == 0 and len(_outbox(core)) == count, "once"
    # A receipt is never answered with a receipt, and a bulletin-like sender is skipped.
    receipt = _inbound(core, flags="!RDR!", sender="W1BKW", number="9")
    message = core.mail.store.read(receipt)
    message.extra["Receipt"] = "delivered"
    core.mail.store.update(receipt, message)
    assert core.mail.answer_receipts([receipt]) == 0
    odd = _inbound(core, sender="not a call!", number="10")
    assert core.mail.answer_receipts([odd]) == 0


def test_opening_marks_read_and_answers_a_read_request_once_when_enabled():
    core = _core(receipt_answer_read=True)
    ref = _inbound(core)
    core.mail.opened(ref)
    assert core.mail.store.read(ref).is_read
    reads = [m for m in _outbox(core) if m.subject.startswith("READ:")]
    assert len(reads) == 1 and reads[0].body.startswith("!RR!")
    core.mail.opened(ref)
    assert len([m for m in _outbox(core) if m.subject.startswith("READ:")]) == 1, "once per message"
    quiet = _core()
    before = len(_outbox(quiet))
    other = _inbound(quiet, number="77")
    quiet.mail.opened(other)
    assert quiet.mail.store.read(other).is_read and len(_outbox(quiet)) == before, "off: only marks read"


def test_requests_are_marked_on_private_bbs_messages_written_here_and_sent_as_flags():
    core = _core(receipt_request_delivery=True, receipt_request_read=True)
    assert core.mail.write(to="W1BKW", title="Hello", body="Line one\nLine two")[0] == []
    [message] = [m for m in _outbox(core) if m.subject == "Hello"]
    assert message.extra["Request-DR"] == "Y" and message.extra["Request-RR"] == "Y"
    assert message.body == "Line one\nLine two\n", "the stored text stays clean"
    bulletin = core.mail.write(to="ALL", at="USA", title="Net", body="x", send_type="B")
    assert bulletin[0] == []
    assert all("Request-DR" not in m.extra for m in _outbox(core) if m.subject == "Net")
    wl = core.mail.write(to="W1AW", title="WL", body="x", send_type="W")
    assert wl[0] == []
    # No numbering on a receipt even when numbering is on.
    from kissterm.mail import numbering
    assert numbering.applies({"Send-Type": "P", "Receipt": "read"}, "READ: x") is False
