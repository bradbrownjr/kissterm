"""Get bulletins (Bulletins tab, G) end to end: dial the Home BBS, offer
its categories, list the chosen one in a window, read and file what is new.

The BBS is a second `AX25Station` on the loopback answering with WS1EC-2's
own lines from the 2026-10-02 capture (`tests/unit/data/bpqmail/`).
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from datetime import datetime  # noqa: E402
from textual.widgets import SelectionList  # noqa: E402

from kissterm.ax25 import AX25Station  # noqa: E402
from kissterm.mail.bulletins import SubscriptionBook  # noqa: E402
from kissterm.ui.bulletin_screen import BulletinCategoriesScreen  # noqa: E402
from kissterm.ui.mail_pane import MessageList  # noqa: E402
from tests.pilot._wait import wait_for  # noqa: E402
from tests.pilot.test_get_mail import BBS, FAST, _app  # noqa: E402

DATA = Path(__file__).parents[1] / "unit" / "data" / "bpqmail"
PROMPT = b"de WS1EC#>\r"
GREETING = (
    b"[BPQ-6.0.23.1-B2FWIHJM$]\rHello Bradley. Welcome back to WS1EC-2 BBS. \r"
    b"Latest Message is 3104, Last listed is 1176.\r"
    b"You have 0 messages waiting for you.\r" + PROMPT
)


def _lines(name: str) -> bytes:
    return ("\r".join((DATA / name).read_text("utf-8").splitlines()) + "\r").encode()


REPLIES = {
    "LC": _lines("list_lc_ws1ec.txt") + PROMPT,
    "LB> WX 3005-3104": (
        b"3104   02-Oct BN    1386 WX     @ECBBS  N4SD   Tropical Weather Outlook\r"
        b"3039   29-Sep BN    2352 WX     @ECBBS  N4SD   Post-Tropical Cyclone Fay\r" + PROMPT
    ),
    "R 3104": _lines("read_3104_bulletin.txt") + PROMPT,
}


def _bpqmail(bbs: AX25Station, heard: list[str]) -> None:
    def _greet(link) -> None:
        def _answer(data: bytes) -> None:
            for command in data.decode("latin-1").split("\r")[:-1]:
                command = command.strip()
                heard.append(command)
                reply = REPLIES.get(command)
                if reply is not None:
                    asyncio.get_event_loop().create_task(link.send(reply))

        link.on_data.append(_answer)

        async def _banner() -> None:
            await asyncio.sleep(0.15)
            await link.send(GREETING)

        asyncio.get_event_loop().create_task(_banner())

    bbs.on_incoming.append(_greet)


@pytest.mark.asyncio
async def test_g_offers_the_categories_then_files_the_chosen(tmp_path, monkeypatch):
    # The listing is from 2026-10-02 and the window is two days, so "today"
    # is pinned to the day after the capture; on the real clock this test
    # started failing on its own on 2026-10-05.
    import kissterm.mail.collect as collect_module

    class _Day(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 3, 12, 0, tzinfo=tz)

    monkeypatch.setattr(collect_module, "datetime", _Day)
    app, station, tb = await _app(tmp_path)
    app.bulletin_subscriptions = SubscriptionBook(tmp_path / "subs.json")
    app.config.home_bbs.bulletin_days = 2
    bbs = AX25Station(BBS, tb, FAST)
    heard: list[str] = []
    _bpqmail(bbs, heard)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_show_tab("bulletins")
        await pilot.pause()
        app.query_one("#bulletins-browser").query_one(MessageList).focus()
        await pilot.pause()
        await pilot.press("g")
        await wait_for(lambda: isinstance(app.screen, BulletinCategoriesScreen),
                       "the category checklist")
        listing = app.screen.query_one("#categories-list", SelectionList)
        assert listing.option_count == 15
        prompts = [str(listing.get_option_at_index(i).prompt)
                   for i in range(listing.option_count)]
        assert "WX (310)" in prompts and "SPACWX (142)" in prompts
        listing.select("WX")
        await pilot.pause()
        await pilot.click("#connect-go")
        await wait_for(lambda: app.mail_store.list("Bulletins/WX"), "the bulletin to be filed",
                       timeout=15)
        assert heard[:3] == ["LC", "LB> WX 3005-3104", "R 3104"]
        [summary] = app.mail_store.list("Bulletins/WX")
        assert summary.subject == "Tropical Weather Outlook"
        subs = app.bulletin_subscriptions.for_bbs("WS1EC")
        assert subs.chosen == ["WX"] and "SPACWX" in subs.declined
        assert (tmp_path / "subs.json").exists()
    bbs.close()
    station.close()


@pytest.mark.asyncio
async def test_the_bulletins_footer_and_s_without_categories(tmp_path):
    app, station, _tb = await _app(tmp_path)
    app.bulletin_subscriptions = SubscriptionBook(tmp_path / "subs.json")
    toasts: list[str] = []
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        real_notify = app.notify
        app.notify = lambda m, *a, **k: (toasts.append(str(m)), real_notify(m, *a, **k))[1]
        app.action_show_tab("bulletins")
        await pilot.pause()
        app.query_one("#bulletins-browser").query_one(MessageList).focus()
        await pilot.pause()
        bound = {k: b.binding.action for k, b in app.screen.active_bindings.items()}
        assert (bound["g"], bound["i"], bound["s"]) == (
            "get_bulletins", "get_bulletins_internet", "bulletin_categories")
        await pilot.press("s")
        await wait_for(lambda: any("No categories yet" in t for t in toasts), "the toast")
        assert not station.transport.sent
        app.action_show_tab("mail")
        await pilot.pause()
        app.query_one("#mail-browser").query_one(MessageList).focus()
        await pilot.pause()
        assert app.screen.active_bindings["g"].binding.action != "get_bulletins"
        assert "s" not in app.screen.active_bindings
    station.close()


@pytest.mark.asyncio
async def test_s_changes_the_categories_offline(tmp_path):
    app, station, _tb = await _app(tmp_path)
    book = SubscriptionBook(tmp_path / "subs.json")
    subs = book.for_bbs("WS1EC")
    subs.seen = {"ALL": 1, "SPACWX": 142, "WX": 310}
    subs.answer(["ALL", "SPACWX", "WX"], ["WX"])
    app.bulletin_subscriptions = book
    app.config.home_bbs.call = "WS1EC"
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_bulletin_categories()
        await wait_for(lambda: isinstance(app.screen, BulletinCategoriesScreen), "the checklist")
        listing = app.screen.query_one("#categories-list", SelectionList)
        assert list(listing.selected) == ["WX"]
        listing.select("SPACWX")
        listing.deselect("WX")
        await pilot.pause()
        await pilot.click("#connect-go")
        await wait_for(lambda: book.for_bbs("WS1EC").chosen == ["SPACWX"], "the new choice")
        assert book.for_bbs("WS1EC").declined == ["ALL", "WX"]
        assert not station.transport.sent  # offline
    station.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("press, answer", [("enter", 20), ("escape", None)])
async def test_the_how_many_question_defaults_to_the_newest(press, answer):
    """More than `ASK_OVER` new: Newest is focused, so Enter reads the
    newest 20 and Escape reads none (`BulletinCountScreen`)."""
    from textual.app import App

    from kissterm.ui.bulletin_screen import BulletinCountScreen

    answers = []

    class Host(App):
        def on_mount(self) -> None:
            self.push_screen(BulletinCountScreen("WS1EC", 72, ["WX"], 20, radio=True),
                             answers.append)

    app = Host()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert "72 new bulletins on WS1EC" in str(app.screen.query_one("#connect-title").render())
        assert app.screen.focused.id == "count-newest"
        await pilot.press(press)
        await wait_for(lambda: answers, "the answer")
    assert answers == [answer]
