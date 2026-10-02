"""Bulletin categories and subscriptions (`kissterm/mail/bulletins.py`),
and the collector's bulletin run against a scripted BPQMail.

The `LC` and `LB>` shapes are LinBPQ's (`BBSUtilities.c` ListCategories,
`%-6s %-3d` nine to a line; the list loop's `>` selector), confirmed by
the operator's 2026-10-02 capture from WS1EC-2 (`data/bpqmail/list_lc_ws1ec.txt`,
`list_lb_wx_page1.txt`, `read_3104_bulletin.txt`).
"""

from kissterm import _isolate

_isolate.isolate()

import asyncio  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402

from kissterm.mail import Message  # noqa: E402
from kissterm.mail.bulletins import (  # noqa: E402
    SubscriptionBook,
    Subscriptions,
    list_command,
    parse_categories,
)
from kissterm.mail.collect import BbsCollector, CollectOptions  # noqa: E402

from .test_mail_collect import PROMPT, ScriptedBbs, _capture, _store  # noqa: E402

NOW = datetime(2026, 10, 2, 22, 0, tzinfo=timezone.utc)


def _lc(*pairs: tuple[str, int]) -> list[str]:
    """An `LC` reply the way ListCategories prints it."""
    line = "".join(f"{name:<6} {count:<3d}" for name, count in pairs)
    return [line, "", PROMPT]


# -- LC ------------------------------------------------------------------------


def test_the_captured_lc():
    """WS1EC-2's own reply, `SPACWX 142UPDATE 49` included."""
    assert parse_categories(_capture("list_lc_ws1ec.txt")) == {
        "ALERT": 30, "AMSAT": 54, "DTN": 1, "EMGSVC": 9, "KEP": 8, "KEPS": 3,
        "LETTER": 2, "MEBBS": 1, "NTS": 1, "SOLAR": 8, "SPACE": 4, "SPACWX": 142,
        "UPDATE": 49, "WP": 32, "WX": 310}


def test_lc_is_name_count_pairs():
    assert parse_categories(_lc(("ALL", 12), ("ARES", 3), ("WX", 40))) == {
        "ALL": 12, "ARES": 3, "WX": 40}


def test_a_long_name_pushes_the_rest_along():
    assert parse_categories(["WEATHER 5  WX     2  "]) == {"WEATHER": 5, "WX": 2}


def test_lines_that_are_not_categories_are_skipped():
    lines = ["LC", "<A>bort, <CR> Continue..>", "", "ALL    2  ", PROMPT,
             "Message 99 not found"]
    assert parse_categories(lines) == {"ALL": 2}


def test_the_listing_asks_only_for_what_is_newer():
    assert list_command("WX") == "LB> WX"
    assert list_command("WX", 2800) == "LB> WX 2801-"


# -- subscriptions ---------------------------------------------------------------


def test_the_list_is_due_first_and_then_every_few_days():
    subs = Subscriptions()
    assert subs.due(NOW, 7)
    subs.checked = NOW
    assert subs.due(NOW, 7)  # never answered: asked again
    subs.answer(["WX"], ["WX"])
    assert not subs.due(NOW + timedelta(days=6), 7)
    assert subs.due(NOW + timedelta(days=7), 7)


def test_a_declined_category_is_never_offered_again():
    subs = Subscriptions()
    subs.answer(["ALL", "ARES", "WX"], ["WX"])
    assert subs.chosen == ["WX"] and subs.declined == ["ALL", "ARES"]
    assert subs.to_offer({"ALL": 1, "ARES": 1, "WX": 1, "SKYWRN": 4}) == ["SKYWRN"]
    assert subs.collect() == ["WX"]


def test_all_takes_new_categories_without_asking():
    subs = Subscriptions()
    subs.answer(["ALL", "WX"], [], all_=True)
    subs.seen = {"ALL": 1, "WX": 2, "SKYWRN": 4}
    assert subs.to_offer(subs.seen) == []
    assert subs.collect() == ["ALL", "SKYWRN", "WX"]


def test_subscriptions_survive_a_restart(tmp_path):
    book = SubscriptionBook(tmp_path / "subs.json")
    subs = book.for_bbs("ws1ec")
    subs.answer(["ALL", "WX"], ["WX"])
    subs.seen, subs.checked = {"ALL": 1, "WX": 2}, NOW
    book.save()
    again = SubscriptionBook(tmp_path / "subs.json")
    again.load()
    loaded = again.for_bbs("WS1EC")
    assert (loaded.chosen, loaded.declined, loaded.seen, loaded.checked) == (
        ["WX"], ["ALL"], {"ALL": 1, "WX": 2}, NOW)


def test_an_unreadable_file_is_nothing_chosen(tmp_path):
    file = tmp_path / "subs.json"
    file.write_text("{not json", "utf-8")
    book = SubscriptionBook(file)
    book.load()
    assert not book.for_bbs("WS1EC").asked and book.for_bbs("WS1EC").due(NOW, 7)


# -- the bulletin run ------------------------------------------------------------


def _bulletin(number: int, category: str = "WX") -> list[str]:
    return [
        "From: N1XYZ", f"To: {category}", "Type/Status: B$", "Date/Time: 01-Oct 10:00Z",
        f"Bid: {number}_N1XYZ", f"Title: Bulletin {number}", "", "R:261001/1000Z @:N1XYZ",
        "", "Text", "", f"[End of Message #{number} from N1XYZ]", PROMPT,
    ]


def _listed(*numbers: int, category: str = "WX") -> list[str]:
    return [f"{n:<6d} 01-Oct B$     120 {category:<7}@ALLUS  N1XYZ  Bulletin {n}"
            for n in numbers] + [PROMPT]


async def _bulletins(bbs, store, book, choose=None, now=NOW, **options):
    notes: list[str] = []
    collector = BbsCollector(bbs, store, CollectOptions(bulletins=True, **options),
                             note=notes.append, sent=lambda _t: None,
                             subscriptions=book, choose=choose, now=lambda: now)
    bbs.start()
    result = await asyncio.wait_for(collector.run(), 5)
    return result, notes


@pytest.mark.asyncio
async def test_the_first_run_offers_the_categories_then_reads_the_chosen(tmp_path):
    store, book = _store(tmp_path), SubscriptionBook(tmp_path / "subs.json")
    offers = []

    async def choose(offer, counts, first):
        offers.append((offer, counts, first))
        return ["WX"], False

    bbs = ScriptedBbs({"LC": _lc(("ALL", 1), ("WX", 2)), "LB> WX": _listed(2802, 2801),
                       "R 2801": _bulletin(2801), "R 2802": _bulletin(2802)})
    result, _ = await _bulletins(bbs, store, book, choose)
    assert offers == [(["ALL", "WX"], {"ALL": 1, "WX": 2}, True)]
    assert bbs.sent == ["LC", "LB> WX", "R 2801", "R 2802"]  # oldest first
    assert not result.stopped and len(result.filed) == 2
    assert all(ref.startswith("Bulletins/WX/") for ref in result.filed)
    assert book.for_bbs("WS1EC").declined == ["ALL"]


@pytest.mark.asyncio
async def test_a_later_run_skips_lc_and_lists_only_newer(tmp_path):
    store, book = _store(tmp_path), SubscriptionBook(tmp_path / "subs.json")
    subs = book.for_bbs("WS1EC")
    subs.answer(["WX"], ["WX"])
    subs.checked = NOW
    store.add("Bulletins/WX", Message(sender="N1XYZ", to="WX", source="BBS WS1EC",
                                      kind="bulletin", category="WX",
                                      extra={"Bbs-Number": "2802"}))
    bbs = ScriptedBbs({"LB> WX 2803-": _listed(2803), "R 2803": _bulletin(2803)})
    result, _ = await _bulletins(bbs, store, book, now=NOW + timedelta(days=1))
    assert bbs.sent == ["LB> WX 2803-", "R 2803"]
    assert len(result.filed) == 1


@pytest.mark.asyncio
async def test_a_new_category_is_offered_at_the_next_check_only(tmp_path):
    store, book = _store(tmp_path), SubscriptionBook(tmp_path / "subs.json")
    subs = book.for_bbs("WS1EC")
    subs.answer(["ALL", "WX"], ["WX"])
    subs.checked = NOW
    offers = []

    async def choose(offer, counts, first):
        offers.append((offer, first))
        return [], False

    replies = {"LC": _lc(("ALL", 1), ("SKYWRN", 3), ("WX", 2)), "LB> WX": [PROMPT]}
    bbs = ScriptedBbs(replies)
    await _bulletins(bbs, store, book, choose, now=NOW + timedelta(days=8))
    assert bbs.sent == ["LC", "LB> WX"] and offers == [(["SKYWRN"], False)]
    assert "SKYWRN" in book.for_bbs("WS1EC").declined


@pytest.mark.asyncio
async def test_nothing_chosen_stops_by_name(tmp_path):
    store, book = _store(tmp_path), SubscriptionBook(tmp_path / "subs.json")

    async def choose(offer, counts, first):
        return None  # cancelled

    bbs = ScriptedBbs({"LC": _lc(("WX", 2))})
    result, _ = await _bulletins(bbs, store, book, choose)
    assert bbs.sent == ["LC"]
    assert "S on the Bulletins tab" in result.stopped
    again = ScriptedBbs({"LC": _lc(("WX", 2))})
    await _bulletins(again, store, book, choose, now=NOW + timedelta(minutes=5))
    assert again.sent == ["LC"]  # unanswered: offered again on the next run


@pytest.mark.asyncio
async def test_a_first_run_goes_back_only_first_days_and_stops_the_listing(tmp_path):
    """WS1EC-2 held 310 WX bulletins (operator, 2026-10-02: "Last N days").
    The captured first page reaches 29-Sep; with one day back from 2 Oct,
    the page prompt is answered A and only 1-2 Oct are read."""
    store, book = _store(tmp_path), SubscriptionBook(tmp_path / "subs.json")
    subs = book.for_bbs("WS1EC")
    subs.answer(["WX"], ["WX"])
    subs.checked = NOW
    page = [line for line in _capture("list_lb_wx_page1.txt") if line]
    replies = {"LB> WX": page, "A": [PROMPT],
               "R 3104": [*_capture("read_3104_bulletin.txt"), PROMPT], "": []}
    kept = (3076, 3079, 3083, 3084, 3096, 3099)
    replies.update({f"R {n}": _bulletin(n) for n in kept})
    bbs = ScriptedBbs(replies)
    result, _ = await _bulletins(bbs, store, book, now=NOW, first_days=1)
    assert not result.stopped, result.stopped
    assert bbs.sent[:2] == ["LB> WX", "A"]
    assert [c for c in bbs.sent if c.startswith("R ")] == [
        f"R {n}" for n in sorted((*kept, 3104))]
    filed = store.read(next(r for r in result.filed if "3104" in store.read(r).extra.get(
        "Bbs-Number", "")))
    assert (filed.kind, filed.category, filed.message_id) == ("bulletin", "WX", "23459_N4SD")
    assert "Tropical Weather Outlook" in filed.body and "R:261002" not in filed.body
