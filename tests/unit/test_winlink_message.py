"""B2 message format, against wl2k-go's rules and a real message
(`tests/unit/data/winlink/LPE5NXDVLVSQ.b2f`, from wl2k-go's test data)."""

from kissterm._isolate import isolate

isolate()

from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from kissterm.winlink import message as b2  # noqa: E402

REAL = Path(__file__).parent / "data" / "winlink" / "LPE5NXDVLVSQ.b2f"


def test_a_real_message_parses_and_writes_back_byte_for_byte():
    raw = REAL.read_bytes()
    parsed = b2.parse(raw)
    assert parsed.mid == "LPE5NXDVLVSQ"
    assert parsed.sender == "LA5NTA" and parsed.to == ["LA4TTA"]
    assert parsed.subject == "73 fra Brekke"
    assert parsed.date == datetime(2016, 7, 20, 19, 21, tzinfo=timezone.utc)
    assert "prøver meg på å sende" in parsed.text
    assert [(name, len(data)) for name, data in parsed.files] == [("1469042410710.jpg", 31028)]
    assert parsed.files[0][1][:2] == b"\xff\xd8"  # a JPEG, whole
    assert b2.serialize(parsed) == raw


def test_build_round_trips_and_is_mid_first_then_sorted():
    when = datetime(2026, 9, 26, 12, 5, tzinfo=timezone.utc)
    built = b2.build(sender="kc1jmh", to=["w1aw", "foo@bar.com", "LA5NTA@winlink.org"],
                     cc=["n0call"], subject="Net report", body="Line one\nLine two\n",
                     mid="ABCDEFGHIJKL", date=when)
    raw = b2.serialize(built)
    lines = raw.split(b"\r\n\r\n", 1)[0].split(b"\r\n")
    assert lines[0] == b"Mid: ABCDEFGHIJKL"
    assert [line.split(b":")[0] for line in lines[1:]] == sorted(line.split(b":")[0] for line in lines[1:])
    assert b"Date: 2026/09/26 12:05" in lines
    assert b"To: SMTP:foo@bar.com" in lines and b"To: LA5NTA" in lines
    assert raw.endswith(b"\r\n\r\nLine one\r\nLine two\r\n")
    back = b2.parse(raw)
    assert back.to == ["W1AW", "SMTP:foo@bar.com", "LA5NTA"] and back.cc == ["N0CALL"]
    assert back.text == "Line one\nLine two\n"
    assert b2.serialize(back) == raw


def test_attachments_round_trip():
    built = b2.build(sender="KC1JMH", to=["W1AW"], subject="Files", body="See attached",
                     files=[("a.txt", b"alpha"), ("empty.bin", b"")])
    raw = b2.serialize(built)
    assert b"File: 5 a.txt\r\n" in raw and b"File: 0 empty.bin\r\n" in raw
    assert b2.parse(raw).files == [("a.txt", b"alpha"), ("empty.bin", b"")]


@pytest.mark.parametrize("subject", ["Blåbær_sylte? ok", "Snowman ☃", "=?not a word"])
def test_non_ascii_subject_is_an_encoded_word_and_decodes(subject):
    encoded = b2.encode_header(subject)
    assert all(32 <= ord(c) < 127 for c in encoded)
    assert b2.decode_header(encoded) == subject


def test_a_raw_utf8_or_latin1_subject_is_read():
    assert b2.decode_header("Blåbær".encode("utf-8").decode("latin-1")) == "Blåbær"
    assert b2.decode_header("Blåbær") == "Blåbær"


@pytest.mark.parametrize("text", ["2016/12/30 01:00", "2016.12.30 01:00", "2016-12-30 01:00",
                                  "20161230010000", "Fri, 30 Dec 2016 01:00:00 -0000",
                                  "Fri, 30 Dec 2016 01:00:00 GMT"])
def test_dates_seen_in_the_wild(text):
    # wl2k-go's TestParseDate cases.
    assert b2.parse_date(text) == datetime(2016, 12, 30, 1, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(("text", "expect"), [
    ("LA5NTA", "LA5NTA"), ("la5nta", "LA5NTA"), ("la5nta@WINLINK.org", "LA5NTA"),
    ("foo@bar.baz", "SMTP:foo@bar.baz"), ("SMTP:foo@bar.baz", "SMTP:foo@bar.baz"),
])
def test_addresses(text, expect):
    # wl2k-go's TestAddressFromString cases.
    assert b2.address(text) == expect


def test_long_lines_are_cut_and_unencodable_characters_replaced():
    data = b2.body_bytes("x" * 2000 + "\n☃")
    assert [len(line) for line in data.split(b"\r\n")] == [998, 998, 4, 1, 0]
    assert data.endswith(b"?\r\n")


def test_mids_are_twelve_characters_and_differ():
    mids = {b2.generate_mid("KC1JMH") for _ in range(50)}
    assert len(mids) == 50 and all(len(m) == 12 for m in mids)


def test_what_cannot_be_sent_is_refused_with_every_reason():
    with pytest.raises(b2.B2Error) as caught:
        b2.build(sender="KC1JMH", to=[], subject="", body="")
    assert "no recipient" in str(caught.value) and "Subject is empty" in str(caught.value)
    assert "no text" in str(caught.value)


@pytest.mark.parametrize("raw", [b"", b"\r\n\r\nfoobar", b"Mid: X\r\nBody: 50\r\n\r\nshort",
                                 b"Body: 1\r\n\r\nx"])
def test_malformed_is_refused(raw):
    # wl2k-go's TestEmptyMessageReadError, plus short and Mid-less messages.
    with pytest.raises(b2.B2Error):
        b2.parse(raw)


def test_leading_whitespace_is_skipped():
    raw = b2.serialize(b2.build(sender="LA5NTA", to=["N0CALL"], subject="Hi", body="Hello world"))
    assert b2.parse(b"\r\n\r\n\t " + raw).mid == b2.parse(raw).mid


def test_to_mail_files_it_as_a_winlink_message():
    mail = b2.to_mail(b2.parse(REAL.read_bytes()))
    assert (mail.sender, mail.to, mail.message_id, mail.source) == ("LA5NTA", "LA4TTA", "LPE5NXDVLVSQ", "Winlink")
    assert mail.extra["Attachments"] == "1469042410710.jpg (31028 bytes)"
    assert mail.body.startswith("Hei!")
