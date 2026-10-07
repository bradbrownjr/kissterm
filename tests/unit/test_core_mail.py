"""Mail Send/Receive and file transfers in the core, with no UI.

What a remote client relies on: a setup question's "go there" cancels the
run and asks the client to go, Skip on All Inboxes moves on to the next
service, nothing is dialed or transmitted while questions are answered,
and a YAPP request opens the download window only for what was asked.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import json  # noqa: E402

import pytest  # noqa: E402

from kissterm.addressbook import AddressBook  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.core import Core, Notice  # noqa: E402
from kissterm.core.events import SetupRequested  # noqa: E402
from kissterm.core.questions import (  # noqa: E402
    SETUP_GO,
    SETUP_SKIP,
    HomeBbsRoute,
    WinlinkGateway,
)
from kissterm.mail.store import ALL_INBOXES  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")


class _Operator:
    """Answers each question type from `answers`; records what was asked."""

    def __init__(self, answers: dict) -> None:
        self.answers = answers
        self.asked: list = []
        self.notices: list[Notice] = []

    def notice(self, notice: Notice) -> None:
        self.notices.append(notice)

    async def ask(self, question):
        self.asked.append(question)
        return self.answers.get(type(question))


class _View:
    def active_key(self) -> str:
        return ""

    def has_room_for(self, key) -> bool:
        return True

    def open_session(self, key, *, kind, focus) -> None:
        pass

    def is_active(self, key) -> bool:
        return True

    def focus_input(self) -> None:
        pass


async def _core(tmp_path, answers, **config):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    operator = _Operator(answers)
    station = AX25Station(MYCALL, ta, LinkParams())
    core = Core(Config(mycall=str(MYCALL), log_sessions=False, **config), station,
                operator=operator)
    core.addressbook = AddressBook(tmp_path / "book.json")
    core.attach_view(_View())
    core.attach_station()
    events: list = []
    core.events.subscribe(lambda seq, event: events.append(event))
    return core, operator, station, ta, events


@pytest.mark.asyncio
async def test_go_there_cancels_the_run_and_asks_the_client_to_go(tmp_path):
    core, operator, station, ta, events = await _core(tmp_path, {HomeBbsRoute: SETUP_GO})
    await core.mail.send_receive("")
    assert [type(q) for q in operator.asked] == [HomeBbsRoute]
    # An empty Address Book: "there" is a new connection.
    assert SetupRequested("connect") in events
    assert ta.sent == [] and core.gate.enabled is False
    assert core.mail.collecting is False
    station.close()


@pytest.mark.asyncio
async def test_skip_on_all_inboxes_moves_on_to_winlink(tmp_path):
    core, operator, station, ta, events = await _core(
        tmp_path, {HomeBbsRoute: SETUP_SKIP, WinlinkGateway: None})
    core.config.home_bbs.route = "WS1EC-2"     # set, but not in the book
    core.config.winlink.route = "W1GW-10"      # likewise
    await core.mail.send_receive(ALL_INBOXES)
    asked = [type(q) for q in operator.asked]
    assert asked == [HomeBbsRoute, WinlinkGateway]
    assert "All Inboxes" in operator.asked[0].all_note
    assert operator.asked[0].skip == "Skip Home BBS"
    assert any(n.text == "Skipping Home BBS this time." for n in operator.notices)
    assert ta.sent == [], "a cancelled setup dialed anyway"
    assert core.mail.collecting is False
    station.close()


@pytest.mark.asyncio
async def test_a_second_run_is_refused_while_one_runs(tmp_path):
    core, operator, station, ta, events = await _core(tmp_path, {})
    core.mail.collecting = True
    await core.mail.get_files()
    assert [n.text for n in operator.notices] == ["Already sending and receiving."]
    assert operator.asked == []
    station.close()


@pytest.mark.asyncio
async def test_a_transfer_needs_a_connected_session(tmp_path):
    core, operator, station, ta, events = await _core(tmp_path, {})
    assert core.transfers.refusal("WS1EC-2") == "Connect before starting a file transfer."
    assert core.transfers.can_send("WS1EC-2") is False
    station.close()


@pytest.mark.asyncio
async def test_cancel_stops_a_run_still_calling_and_says_so(tmp_path):
    """Operator, 2026-10-06, from a phone: tap the turning Send/Receive
    button "to cancel and disconnect". Here the BBS never answers: the
    SABMs stop, the run ends, and every client is told it did."""
    import asyncio

    from kissterm.core.events import MailRunChanged

    core, operator, station, ta, events = await _core(tmp_path, {})
    core.addressbook.upsert("WS1EC-2")
    core.config.home_bbs.route = "WS1EC-2"
    run = asyncio.ensure_future(core.mail.send_receive("Mail/BBS/Inbox"))
    for _ in range(200):
        if core.connector.connecting:
            break
        await asyncio.sleep(0.01)
    assert core.mail.session_key in core.connector.connecting
    assert await core.mail.cancel() is True
    await asyncio.wait_for(run, 5)
    sent = len(ta.sent)
    await asyncio.sleep(0.3)
    assert len(ta.sent) == sent, "SABMs went on after the cancel"
    assert core.mail.collecting is False
    assert [e.running for e in events if isinstance(e, MailRunChanged)] == [True, False]
    assert any(n.text == "Send/Receive cancelled." for n in operator.notices)
    assert await core.mail.cancel() is False, "nothing left to cancel"
    station.close()


@pytest.mark.asyncio
async def test_cancel_stops_a_run_with_no_session_of_its_own(tmp_path):
    """An Internet run (the Winlink CMS, the BBS by I) is a task cancelled;
    the run ends quietly, not the task that asked for it."""
    import asyncio

    core, operator, station, ta, events = await _core(tmp_path, {})
    started = asyncio.Event()

    async def slow(*_args):
        started.set()
        await asyncio.sleep(3600)

    async def prepared(*_args):
        return [(slow, ())]

    core.mail._prepare_runs = prepared
    run = asyncio.ensure_future(core.mail.send_receive("", internet=True))
    await asyncio.wait_for(started.wait(), 2)
    assert await core.mail.cancel() is True
    await asyncio.wait_for(run, 2)
    assert not run.cancelled(), "the caller's task was cancelled, not just the run"
    assert core.mail.collecting is False
    assert any(n.text == "Send/Receive cancelled." for n in operator.notices)
    station.close()


@pytest.mark.asyncio
async def test_cancel_after_the_link_is_up_disconnects_and_reports_cancelled(tmp_path):
    """The BBS answered but the run is not done: cancel ends the link as a
    disconnect does, and the one outcome notice says it was cancelled."""
    import asyncio

    core, operator, station, ta, events = await _core(tmp_path, {})
    peer = AX25Station(AX25Address.parse("WS1EC-2"), ta.peer, LinkParams(),
                       accept_incoming=True)
    core.addressbook.upsert("WS1EC-2")
    core.config.home_bbs.route = "WS1EC-2"
    run = asyncio.ensure_future(core.mail.send_receive("Mail/BBS/Inbox"))
    for _ in range(300):
        link = core.sessions.link("WS1EC-2")
        if link is not None and link.connected:
            break
        await asyncio.sleep(0.01)
    assert link is not None and link.connected
    assert await core.mail.cancel() is True
    # Well inside the collector's 300 s idle timeout: the drop wakes it.
    await asyncio.wait_for(run, 3)
    assert core.mail.collecting is False
    assert any(n.text.startswith("Send/Receive stopped: cancelled.") for n in operator.notices)
    link = core.sessions.link("WS1EC-2")
    assert link is None or not link.connected
    station.close()
    peer.close()


@pytest.mark.asyncio
async def test_a_gateway_chosen_is_filed_as_the_winlink_dial_and_nothing_is_sent(tmp_path):
    from kissterm.winlink import gateways

    core, operator, station, ta, events = await _core(tmp_path, {})
    cache = core.mail.gateway_cache()
    gateways.save_cached(cache, json.dumps({"Gateways": [{
        "Callsign": "W1AW-10", "BaseCallsign": "W1AW", "Latitude": 41.7, "Longitude": -72.7,
        "GatewayChannels": [{"Frequency": 145050000, "SupportedModes": "Packet 1200",
                             "Gridsquare": "FN31pr"}]}]}).encode())
    listed = core.mail.rms_gateways("packet")
    assert [c["callsign"] for c in listed["channels"]] == ["W1AW-10"]
    assert listed["channels"][0]["frequency"] == "145.050 MHz" and listed["modes"]
    assert core.mail.rms_gateways("vara fm")["channels"] == []
    assert listed["can_refresh"] is bool(gateways.ACCESS_KEY) and "fetched" in listed["note"]
    if not gateways.ACCESS_KEY:
        assert "Not refreshed" in await core.mail.rms_refresh()
    core.mail.use_gateway("W1AW-10", "145.050 MHz", "Packet 1200", "FN31pr")
    assert core.addressbook.find("W1AW-10") is not None
    assert core.config.winlink.route == "W1AW-10"
    assert ta.sent == [] and core.gate.enabled is False
    station.close()
