"""ARRL radiograms (`kissterm/mail/nts.py`), checked against the worked
examples in ARRL's NTS Methods and Practices Guidelines, chapters 1 and 6."""

from kissterm import _isolate

_isolate.isolate()

from datetime import datetime, timezone  # noqa: E402

from kissterm.mail import nts  # noqa: E402
from kissterm.mail.nts import Radiogram  # noqa: E402

JAN_1 = datetime(2002, 1, 1, tzinfo=timezone.utc)


def test_mpg_1_0_2_example_text_and_check():
    text = nts.encode_text("Thanks for message. Hope to see you at hamfest. 73")
    assert text == "THANKS FOR MESSAGE X HOPE TO SEE YOU AT HAMFEST X 73"
    assert nts.check(text) == "12"


def test_mpg_1_3_example_arl_check_is_arl_25():
    text = nts.encode_text(
        "ARL 46. Do you want the 304/BA equipment? The six-B type is no longer "
        "available. CU on 7013.5 73"
    )
    assert text.split()[:4] == ["ARL", "FORTY", "SIX", "X"]
    assert "304/BA" in text.split() and "7013R5" in text.split()
    assert "QUERY" in text.split() and "SIX DASH B" in text
    assert nts.check(text) == "ARL 25"


def test_mpg_1_3_4_group_counting():
    # One group each, however long (not one per five digits).
    for group in ("X", "145R67", "34TH/CMD", "7035R7KHZ", "1234567890123"):
        assert nts.check(group) == "1", group
    assert nts.check("555 5678") == "2"
    assert nts.check("301 555 3456") == "3"


def test_punctuation_is_spelled_and_x_never_ends_the_text():
    assert nts.encode_text("Call 207-555-1212, or write w1aw@arrl.org.") == (
        "CALL 207 555 1212 COMMA OR WRITE W1AW AT ARRL DOT ORG"
    )
    assert nts.encode_text("Don't worry!") == "DONT WORRY EXCLAMATION"
    assert nts.encode_text("See you...") == "SEE YOU"


def test_preamble_follows_1_1():
    gram = Radiogram(number="1", precedence="EMERGENCY", handling="hxe", origin="w1aw",
                     place="Newington, CT", time_filed="1830z", filed=JAN_1, text="Hi")
    assert gram.preamble() == "NR 1 EMERGENCY HXE W1AW 1 NEWINGTON CT 1830Z JAN 1"
    gram.test, gram.precedence = True, "R"
    assert gram.preamble().startswith("NR 1 TEST R HXE")


def test_mpg_6_2_1_packet_upload_example():
    gram = Radiogram(
        number="1", precedence="R", handling="HXG", origin="N3QA", place="Chestertown MD",
        filed=JAN_1, to_name="Guy Anyone", to_street="123 Main Street", to_city="Sometown",
        to_state="CA", to_zip="99999", to_phone="555-555-5555", text="ARL 50 see you soon",
        signature="John Q Public",
    )
    assert gram.body() == (
        "NR 1 R HXG N3QA ARL 5 CHESTERTOWN MD JAN 1\n"
        "GUY ANYONE\n123 MAIN STREET\nSOMETOWN CA 99999\n555 555 5555\n"
        "\nARL FIFTY SEE YOU SOON\n\nJOHN Q PUBLIC\n"
    )
    assert gram.subject() == "QTC SOMETOWN / 555 555"
    assert gram.routing() == ("99999", "NTSCA")
    assert gram.problems() == []


def test_address_rules_1_2():
    gram = Radiogram(to_name="John R Smith", to_call="w3xyz", to_street="23 East Oak Dr. SW, Apt #34",
                     to_city="Owings Mills", to_state="md", to_zip="21117-2345")
    assert gram.address()[:3] == [
        "JOHN R SMITH W3XYZ", "23 EAST OAK DR SW APT 34", "OWINGS MILLS MD 21117 DASH 2345",
    ]
    assert gram.routing() == ("21117", "NTSMD")


def test_subject_without_a_phone_and_its_30_character_limit():
    assert Radiogram(to_city="Waldorf").subject() == "QTC WALDORF / NO PHONE"
    assert Radiogram(to_city="Waldorf", to_call="kc1abc").subject() == "QTC WALDORF / KC1ABC"
    long = Radiogram(to_city="North Saint Paul Heights Township", to_phone="6515551212")
    assert len(long.subject()) <= nts.MAX_SUBJECT and long.subject().endswith("/ 651 555")


def test_problems_name_each_field():
    problems = " ".join(Radiogram(number="007", to_state="ON", to_zip="1234").problems())
    for word in ("Number", "Station of origin", "Place of origin", "State", "ZIP", "Text", "Signature"):
        assert word in problems, word
    assert "Time filed" in " ".join(Radiogram(time_filed="6:30pm").problems())
    many = Radiogram(text=" ".join(["word"] * 30))
    assert any("30 groups" in w for w in many.warnings())


def test_arl_texts_ship_complete_and_numbers_are_spelled():
    texts = nts.arl_texts()
    assert len(texts) == 87 and texts[0].groups == "ARL ONE"
    assert {t.number for t in texts} >= set(range(1, 41)) | set(range(46, 77))
    assert next(t for t in texts if t.number == 46).groups == "ARL FORTY SIX"
    assert nts.number_words(99) == "NINETY NINE" and nts.number_words(13) == "THIRTEEN"
    assert nts.next_number(["3", "12", "x"]) == "13" and nts.next_number([]) == "1"


def test_arl_used_takes_the_longest_number():
    used = nts.arl_used("ARL SIXTY TWO CHRISTMAS X ARL SIXTY BIRTHDAY X ARL ONE")
    assert [t.number for t in used] == [62, 60, 1]


def test_live_conversion_word_by_word_matches_the_whole_text():
    raw = 'He said "call 207-555-1212 (after 6)". Dont be late. ARL 46.'
    live = ""
    for word in raw.split():
        live = nts.encode_text(f"{live} {word} ", final=False)
    assert live.endswith(" X")  # still typing: the period stays
    assert nts.encode_text(live) == nts.encode_text(raw)
    assert "QUOTE CALL 207 555 1212 PAREN AFTER 6 UNPAREN UNQUOTE X" in live
    assert nts.encode_text(live) == nts.encode_text(nts.encode_text(live))
