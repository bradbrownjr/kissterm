"""The BBS collector (`kissterm/mail/collect.py`) against a scripted BPQMail.

The scripted BBS answers from the real WS1EC-2 captures in
`tests/unit/data/bpqmail/`: the greeting, `LM`, a private read, not-found.
"""

from kissterm import _isolate

_isolate.isolate()

import asyncio  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from kissterm.mail import Message, MessageStore  # noqa: E402
from kissterm.mail.collect import (  # noqa: E402
    BBS_INBOX,
    BBS_SENT,
    BbsCollector,
    CollectOptions,
)
from kissterm.mail.compose import BBS_OUTBOX, outbox_message  # noqa: E402

DATA = Path(__file__).parent / "data" / "bpqmail"
PROMPT = "de WS1EC#>"


def _capture(name: str) -> list[str]:
    return (DATA / name).read_text(encoding="utf-8").split("\n")


GREETING = _capture("read_2578_private.txt")[:5]  # SID ... prompt
READ_2578 = _capture("read_2578_private.txt")[5:]  # From: ... [End], prompt
LIST_TWO = [
    "2578   16-Sep PY      25 KC1JMH @WS1EC  WS1EC  Test message",
    "2501   12-Sep PY     192 KC1JMH @WS1EC  WS1EC  RE: TEST OUTPOST",
    PROMPT,
]


def _read(number: int, body: str = "Hello") -> list[str]:
    return [
        "From: WS1EC", "To: KC1JMH", "Type/Status: PY", "Date/Time: 12-Sep 10:00Z",
        f"Bid: {number}_WS1EC", "Title: RE: TEST OUTPOST", "", body, "",
        f"[End of Message #{number} from WS1EC]", PROMPT,
    ]


class ScriptedBbs:
    """A link whose far end answers each command from a script.

    Each reply is a list of chunks; a chunk is sent as one delivery, so a
    page prompt can arrive without a line ending, the way BPQMail sends it.
    """

    def __init__(self, replies: dict[str, list[str]], greeting: list[str] | None = None):
        self.connected = True
        self.on_data: list = []
        self.sent: list[str] = []
        self.replies = dict(replies)
        self._greeting = GREETING if greeting is None else greeting

    def start(self) -> None:
        asyncio.get_event_loop().call_later(0.01, self._deliver, self._greeting)

    def _deliver(self, chunks: list[str]) -> None:
        for chunk in chunks:
            data = chunk.encode("latin-1") if chunk.endswith(">") and "Continue" in chunk \
                else (chunk + "\r").encode("latin-1")
            for callback in list(self.on_data):
                callback(data)

    async def send(self, data: bytes) -> None:
        # One send can carry several lines (a message body): each is a
        # command to the script, as it would be to the BBS.
        for command in data.decode("latin-1").split("\r")[:-1]:
            self.sent.append(command)
            reply = self.replies.get(command)
            if reply is not None:
                asyncio.get_event_loop().call_later(0.01, self._deliver, reply)


def _store(tmp_path) -> MessageStore:
    store = MessageStore(tmp_path / "mail")
    store.ensure_default_tree()
    return store


async def _run(bbs: ScriptedBbs, store, **options):
    notes: list[str] = []
    shown: list[str] = []
    gate = options.pop("gate", lambda: True)
    collector = BbsCollector(bbs, store, CollectOptions(**options),
                             note=notes.append, sent=shown.append, gate_open=gate)
    bbs.start()
    result = await asyncio.wait_for(collector.run(), 5)
    return result, notes, shown


@pytest.mark.asyncio
async def test_reads_only_new_mail_and_files_it_with_the_raw_reply(tmp_path):
    store = _store(tmp_path)
    store.add(BBS_INBOX, Message(sender="WS1EC", subject="RE: TEST OUTPOST", source="BBS WS1EC",
                                 message_id="2501_WS1EC", extra={"Bbs-Number": "2501"}))
    bbs = ScriptedBbs({"LM": LIST_TWO, "R 2578": READ_2578})
    result, notes, shown = await _run(bbs, store)
    assert bbs.sent == ["LM", "R 2578"]  # 2501 is already here: never read again
    assert shown == ["LM", "R 2578"]
    assert not result.stopped and result.listed == 2 and result.already_had == 1
    [ref] = result.filed
    message = store.read(ref)
    assert (message.subject, message.source, message.message_id) == (
        "Test message", "BBS WS1EC", "2578_WS1EC")
    assert message.extra["Bbs-Number"] == "2578"
    assert "test test" in message.body
    [raw] = store.raw_files(ref)
    assert raw.suffix == ".bbs" and b"[End of Message #2578 from WS1EC]" in raw.read_bytes()
    assert any("Reading 1 of 1: #2578" in n for n in notes)
    assert "Done: 1 received." in notes  # not "filed", which reads as "failed"


@pytest.mark.asyncio
async def test_a_second_run_reads_nothing(tmp_path):
    store = _store(tmp_path)
    replies = {"LM": LIST_TWO, "R 2578": READ_2578, "R 2501": _read(2501)}
    await _run(ScriptedBbs(replies), store)
    bbs = ScriptedBbs(replies)
    result, notes, _ = await _run(bbs, store)
    assert bbs.sent == ["LM"] and result.filed == [] and result.already_had == 2
    assert any("No new mail" in n for n in notes)


@pytest.mark.asyncio
async def test_empty_lm_is_no_mail(tmp_path):
    bbs = ScriptedBbs({"LM": _capture("list_lm_empty.txt")})
    result, notes, _ = await _run(bbs, _store(tmp_path))
    assert not result.stopped and result.listed == 0 and bbs.sent == ["LM"]


@pytest.mark.asyncio
async def test_a_page_prompt_is_answered_with_enter(tmp_path):
    first, rest = _read(2501)[:8], _read(2501)[8:]
    bbs = ScriptedBbs({
        "LM": LIST_TWO[1:],
        "R 2501": [*first, "<A>bort, <CR> Continue..>"],
        "": rest,
    })
    result, _notes, shown = await _run(bbs, _store(tmp_path))
    assert bbs.sent == ["LM", "R 2501", ""]
    assert "(Enter: continue)" in shown
    [ref] = result.filed
    assert "Continue" not in MessageStore(tmp_path / "mail").read(ref).body


@pytest.mark.asyncio
async def test_not_found_is_noted_and_skipped(tmp_path):
    bbs = ScriptedBbs({"LM": LIST_TWO[1:], "R 2501": _capture("read_99999_not_found.txt")})
    result, notes, _ = await _run(bbs, _store(tmp_path))
    assert result.not_found == [2501] and not result.filed and not result.stopped


@pytest.mark.asyncio
async def test_an_aborted_read_stops_and_files_nothing(tmp_path):
    aborted = _read(2501)[:8] + ["Output aborted", PROMPT]
    bbs = ScriptedBbs({"LM": LIST_TWO[1:], "R 2501": aborted})
    store = _store(tmp_path)
    result, notes, _ = await _run(bbs, store)
    assert "not a complete message" in result.stopped
    assert store.list(BBS_INBOX) == []


@pytest.mark.asyncio
async def test_an_unrecognised_bbs_stops_before_any_command(tmp_path):
    # Not BPQMail's prompt, so the operator's "ready" text says when to start.
    greeting = ["Welcome to the XYZ mailbox", "XYZ>"]
    bbs = ScriptedBbs({"LM": LIST_TWO}, greeting=greeting)
    result, _notes, _ = await _run(bbs, _store(tmp_path), ready_text="XYZ>")
    assert "could not identify" in result.stopped and bbs.sent == []
    # Told it is BPQMail, and its callsign, it goes ahead.
    bbs = ScriptedBbs({"LM": _capture("list_lm_empty.txt")}, greeting=greeting)
    result, _notes, _ = await _run(bbs, _store(tmp_path), ready_text="XYZ>",
                                   software="bpqmail", bbs_call="XYZ")
    assert not result.stopped and bbs.sent == ["LM"]


@pytest.mark.asyncio
async def test_login_prompt_sends_the_credential_first(tmp_path):
    greeting = ["Callsign :"]
    bbs = ScriptedBbs({"KC1JMH": GREETING, "LM": _capture("list_lm_empty.txt")},
                      greeting=greeting)
    result, _notes, shown = await _run(bbs, _store(tmp_path),
                                       login_prompt="Callsign :", login_text="KC1JMH")
    assert bbs.sent == ["KC1JMH", "LM"] and shown[0] == "(login sent)"
    assert not result.stopped


@pytest.mark.asyncio
async def test_silence_and_a_closed_gate_stop_by_name(tmp_path):
    bbs = ScriptedBbs({}, greeting=["[BPQ-6.0.23.1-B2FWIHJM$]"])
    result, _notes, _ = await _run(bbs, _store(tmp_path), idle_timeout=0.2)
    assert result.stopped == "nothing from the BBS for 0 s"
    bbs = ScriptedBbs({"LM": LIST_TWO})
    result, _notes, _ = await _run(bbs, _store(tmp_path), gate=lambda: False)
    assert result.stopped == "transmit is off" and bbs.sent == []


# -- sending the Outbox (captures send_sr_2784.txt, send_sp_w1bkw.txt) ----------

SR = _capture("send_sr_2784.txt")
SP = _capture("send_sp_w1bkw.txt")
DAVE = Message(sender="KC1UIX", to="KC1JMH", subject="Test message", source="BBS WS1EC",
               extra={"Bbs-Number": "2784"})


def _outbox(store, **fields):
    return store.add(BBS_OUTBOX, outbox_message(sender="KC1JMH", **fields))


@pytest.mark.asyncio
async def test_a_reply_goes_out_as_sr_and_moves_to_sent(tmp_path):
    store = _store(tmp_path)
    _outbox(store, to="KC1UIX", at="", title="Re:Test message",
            body="Hi Dave,\n\nI received your message!\n\n73 de KC1JMH\n", reply_to=DAVE)
    bbs = ScriptedBbs({"SR 2784": SR[2:4], "/EX": SR[10:12],
                       "LM": _capture("list_lm_empty.txt")})
    result, notes, shown = await _run(bbs, store)
    assert bbs.sent == ["SR 2784", "Hi Dave,", "", "I received your message!", "",
                        "73 de KC1JMH", "/EX", "LM"]
    assert not result.stopped and store.list(BBS_OUTBOX) == []
    [ref] = result.sent
    sent = store.read(ref)
    assert ref.startswith(BBS_SENT) and sent.extra["Bbs-Number"] == "2801"
    assert sent.message_id == "2801_WS1EC" and sent.source == "BBS WS1EC"
    assert any("Sent as #2801" in n for n in notes)


@pytest.mark.asyncio
async def test_a_new_message_answers_the_title_prompt(tmp_path):
    store = _store(tmp_path)
    _outbox(store, to="W1BKW", at="", title="Received your radiogram", body="Hi Brian,\n73\n")
    bbs = ScriptedBbs({"SP W1BKW": SP[5:7], "Received your radiogram": SP[8:9],
                       "/EX": SP[18:20], "LM": _capture("list_lm_empty.txt")})
    result, _notes, _ = await _run(bbs, store)
    assert bbs.sent == ["SP W1BKW", "Received your radiogram", "Hi Brian,", "73", "/EX", "LM"]
    assert not result.stopped and len(result.sent) == 1


@pytest.mark.asyncio
async def test_a_refusal_stops_the_run_and_keeps_the_message(tmp_path):
    store = _store(tmp_path)
    _outbox(store, to="W1BKW", at="", title="Hello", body="Hi\n")
    bbs = ScriptedBbs({"SP W1BKW": SP[2:4], "LM": LIST_TWO})
    result, _notes, _ = await _run(bbs, store)
    assert "refused 'SP W1BKW'" in result.stopped and "'TO' callsign" in result.stopped
    assert bbs.sent == ["SP W1BKW"]  # no body, no LM
    assert len(store.list(BBS_OUTBOX)) == 1 and result.sent == []


@pytest.mark.asyncio
async def test_a_reply_from_another_bbs_goes_as_sp(tmp_path):
    store = _store(tmp_path)
    elsewhere = Message(sender="KC1UIX", subject="Test", source="BBS N1XYZ",
                        extra={"Bbs-Number": "12"})
    _outbox(store, to="KC1UIX", at="", title="Re:Test", body="Hi\n", reply_to=elsewhere)
    bbs = ScriptedBbs({"SP KC1UIX": SP[5:7], "Re:Test": SP[8:9], "/EX": SP[18:20],
                       "LM": _capture("list_lm_empty.txt")})
    result, _notes, _ = await _run(bbs, store)
    assert bbs.sent[:2] == ["SP KC1UIX", "Re:Test"] and not result.stopped
