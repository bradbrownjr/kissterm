"""BPQMail replies parsed from real WS1EC-2 captures (tests/unit/data/bpqmail/)."""

from kissterm import _isolate

_isolate.isolate()

from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

from kissterm.mail import KIND_BULLETIN  # noqa: E402
from kissterm.mail.bpqmail import (  # noqa: E402
    infer_date,
    killed,
    not_found,
    parse_list,
    parse_list_line,
    parse_read,
    prompt_call,
    strip_page_prompts,
    to_message,
)

DATA = Path(__file__).parent / "data" / "bpqmail"
NOW = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)


def _lines(name: str) -> list[str]:
    return (DATA / name).read_text(encoding="utf-8").split("\n")


def test_listing_from_lr():
    entries = parse_list(_lines("list_lr.txt"))
    assert len(entries) == 23
    first = entries[0]
    assert (first.number, first.date, first.type, first.status) == (2712, "22-Sep", "B", "N")
    assert (first.size, first.to, first.at, first.sender) == (2584, "WX", "ECBBS", "N4SD")
    assert first.title == "Tropical Storm Fay Discussion Number  12"
    wp = next(e for e in entries if e.number == 2705)
    assert (wp.status, wp.to, wp.at, wp.sender) == ("$", "WP", "WS1EC", "WD1O")


def test_listing_of_private_mail():
    # From LM on 2026-09-22 (the capture's frame-split lines rejoined).
    e = parse_list_line("2578   16-Sep PY      25 KC1JMH @WS1EC  WS1EC  Test message")
    assert (e.type, e.status, e.to, e.sender, e.title) == ("P", "Y", "KC1JMH", "WS1EC", "Test message")


def test_prompts_and_page_prompts_are_not_list_lines():
    assert parse_list_line("<A>bort, <R Message>, <CR> = Continue..>") is None
    assert parse_list_line("de WS1EC#>") is None
    assert prompt_call("de WS1EC#>") == "WS1EC"
    assert prompt_call("Hello Bradley.") == ""


def test_complete_read_to_the_end_marker():
    read = parse_read(_lines("read_2686_excerpt.txt"))
    assert read.complete and not read.aborted and read.number == 2686
    assert read.headers["Bid"] == "22806_N4SD"
    assert len(read.routes) == 5
    assert read.body[0] == "WTNT41 KNHC 210836"
    assert read.body[-1] == "More Info: N4SD@N4SD.#TIDE.VA.USA.NOAM"
    assert not any("Continue..>" in line for line in read.body)


def test_aborted_reads_are_incomplete():
    for name, routes in (("read_2738_aborted.txt", 8), ("read_2712_aborted.txt", 5)):
        read = parse_read(_lines(name))
        assert read.aborted and not read.complete, name
        assert len(read.routes) == routes, name
        assert not read.body[0].startswith("R:"), name


def test_read_2738_after_the_greeting():
    read = parse_read(_lines("read_2738_aborted.txt"))
    assert read.headers["From"] == "HP2DFA"
    assert read.body[0] == "Upcoming ARISS Contact Schedule as of 2026-09-23 05:00 UTC"
    # Non-ASCII survives (the UTF-8 decode fix, confirmed on this message).
    assert any("“" in line for line in read.body)


def test_to_message():
    msg = to_message(parse_read(_lines("read_2686_excerpt.txt")), "WS1EC", now=NOW)
    assert msg.source == "BBS WS1EC"
    assert msg.message_id == "22806_N4SD"
    assert msg.kind == KIND_BULLETIN and msg.category == "WX"
    assert msg.date == datetime(2026, 9, 21, 8, 37, tzinfo=timezone.utc)
    assert msg.extra == {"Bbs-Number": "2686", "Bbs-Type": "BN"}
    assert "R:260921" not in msg.body


def test_infer_date_rolls_back_a_year_across_new_year():
    jan = datetime(2027, 1, 2, tzinfo=timezone.utc)
    assert infer_date("30-Dec 10:00Z", jan).year == 2026
    assert infer_date("01-Jan 10:00Z", jan).year == 2027
    assert infer_date("nonsense", jan) is None


def test_the_same_read_without_paging_parses_identically():
    # Paging is a per-user BBS setting; a user with it off gets no prompts.
    paged = _lines("read_2686_excerpt.txt")
    unpaged = [line for line in paged if "Continue..>" not in line]
    a, b = parse_read(paged), parse_read(unpaged)
    assert (a.headers, a.routes, a.body, a.complete) == (b.headers, b.routes, b.body, b.complete)


def test_a_page_prompt_glued_to_text_is_cut_out():
    assert strip_page_prompts("<A>bort, <CR> Continue..>nudged down to 55 kt") == "nudged down to 55 kt"
    assert strip_page_prompts("last line<A>bort, <R Msg(s)>, <CR> = Continue..>") == "last line"
    assert strip_page_prompts("<A>bort, <CR> Continue..>  ") is None
    assert strip_page_prompts("an ordinary line") == "an ordinary line"
    lines = ["From: N4SD", "Title: t", "", "one", "<A>bort, <CR> Continue..>two",
             "[End of Message #1 from N4SD]"]
    assert parse_read(lines).body == ["one", "two"]


def test_private_message_read_to_its_end():
    # R 2578 on 2026-09-24: PY, no routing lines, two blank lines first.
    read = parse_read(_lines("read_2578_private.txt"))
    assert read.complete and read.number == 2578 and read.routes == []
    assert read.headers["Type/Status"] == "PY"
    assert read.body == ["test test", "", "de WS1EC"]
    message = to_message(read, "WS1EC", NOW)
    assert (message.kind, message.message_id, message.subject) == (
        "mail", "2578_WS1EC", "Test message")
    assert message.date == datetime(2026, 9, 16, 16, 33, tzinfo=timezone.utc)


def test_kill_confirmation_and_not_found():
    assert killed(_lines("kill_2578.txt")) == 2578
    assert not_found(_lines("kill_2578.txt")) is None
    lines = _lines("read_99999_not_found.txt")
    assert not_found(lines) == 99999 and killed(lines) is None
    assert parse_read(lines) is None
