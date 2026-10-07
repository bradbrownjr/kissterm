"""The remote-control server (`kissterm/serve/`) on a loopback station.

What a phone may rely on, and what it must never be able to do: a wrong
token learns nothing, every client sees every event, the first answer to
a question wins, a question with nobody to answer it is a cancel, and a
command is the core's own method -- so the transmit gate holds exactly as
it does at the keyboard.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import stat  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("websockets")

from websockets.asyncio.client import connect as ws_connect  # noqa: E402
from websockets.exceptions import ConnectionClosed  # noqa: E402

from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config, ServeConfig  # noqa: E402
from kissterm.core import Core, Notice  # noqa: E402
from kissterm.core import events as ev  # noqa: E402
from kissterm.core.questions import (  # noqa: E402
    SETUP_SKIP,
    ChooseCategories,
    HowManyBulletins,
    GatewayChoice,
    RadioReminder,
    WinlinkGateway,
)
from kissterm.serve import pairing, wire  # noqa: E402
from kissterm.serve.headless import HeadlessView, pairing_text  # noqa: E402
from kissterm.serve.operator import FanOutOperator  # noqa: E402
from kissterm.serve.server import UNAUTHORIZED, RemoteServer  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
PEER = AX25Address.parse("WS1EC-7")
TOKEN = "t" * 43


def _params() -> LinkParams:
    return LinkParams(t1=0.2, t2=0.05, t3=5.0, connect_retries=3)


async def _serve(*, standalone: bool = True):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    station = AX25Station(MYCALL, ta, _params())
    peer = AX25Station(PEER, tb, _params(), accept_incoming=True)
    config = Config(mycall=str(MYCALL), serve=ServeConfig(listen="127.0.0.1", port=0))
    core = Core(config, station)
    server = RemoteServer(core, token=TOKEN, standalone=standalone, web=False)
    core.operator = server.operator
    core.attach_view(HeadlessView(core))
    core.attach_station()
    await server.start()
    return core, server, ta, peer


class _Client:
    def __init__(self, ws) -> None:
        self.ws = ws
        self.seen: list[dict] = []

    async def next(self, predicate=lambda m: True, timeout: float = 3.0) -> dict:
        async def _read():
            while True:
                message = json.loads(await self.ws.recv())
                self.seen.append(message)
                if predicate(message):
                    return message
        return await asyncio.wait_for(_read(), timeout)

    async def send(self, message: dict) -> None:
        await self.ws.send(json.dumps(message))

    async def command(self, cid: str, name: str, **args) -> dict:
        await self.send({"type": "command", "id": cid, "name": name, "args": args})
        return await self.next(lambda m: m.get("type") == "result" and m.get("id") == cid)


async def _join(server, *, token: str = TOKEN, since: int = 0) -> _Client:
    ws = await ws_connect(f"ws://127.0.0.1:{server.port}/v1")
    await ws.send(json.dumps({"type": "hello", "token": token, "client": "test", "since": since}))
    client = _Client(ws)
    return client


async def _until(condition, timeout: float = 3.0) -> None:
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not condition():
        assert loop.time() < end, "condition never became true"
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_a_wrong_token_is_closed_4401_and_told_nothing():
    core, server, ta, peer = await _serve()
    client = await _join(server, token="nope")
    with pytest.raises(ConnectionClosed) as closed:
        await client.next()
    assert closed.value.rcvd.code == UNAUTHORIZED
    assert client.seen == []
    assert not server.has_clients()
    await server.stop()


@pytest.mark.asyncio
async def test_the_right_token_gets_a_welcome_then_live_events():
    core, server, ta, peer = await _serve()
    client = await _join(server)
    welcome = await client.next()
    assert welcome["type"] == "welcome"
    assert welcome["station"]["callsign"] == str(MYCALL)
    assert welcome["snapshot"]["gate"] is False
    await _until(server.has_clients)
    core.gate.set(True)
    event = await client.next(lambda m: m["type"] == "event")
    assert (event["name"], event["data"]) == ("GateChanged", {"enabled": True})
    await client.ws.close()
    await server.stop()


@pytest.mark.asyncio
async def test_a_late_client_replays_events_after_since():
    core, server, ta, peer = await _serve()
    first = core.events.publish(ev.ActivityChanged("one"))
    core.events.publish(ev.ActivityChanged("two"))
    client = await _join(server, since=first)
    welcome = await client.next()
    assert welcome["snapshot"]["activity"] == "two"
    replay = await client.next(lambda m: m["type"] == "event")
    assert replay["replay"] is True and replay["data"] == {"text": "two"}
    await client.ws.close()
    await server.stop()


@pytest.mark.asyncio
async def test_the_first_answer_wins_and_the_other_client_is_told():
    core, server, ta, peer = await _serve()
    a, b = await _join(server), await _join(server)
    await a.next()
    await b.next()
    await _until(lambda: len(server.clients) == 2)
    asked = asyncio.ensure_future(core.operator.ask(RadioReminder("145.090")))
    qa = await a.next(lambda m: m["type"] == "question")
    qb = await b.next(lambda m: m["type"] == "question")
    assert qa["id"] == qb["id"] and qa["name"] == "RadioReminder"
    assert qa["data"]["frequency"] == "145.090"
    await a.send({"type": "answer", "id": qa["id"], "value": True})
    assert await asyncio.wait_for(asked, 3) is True
    await b.next(lambda m: m["type"] == "question_closed" and m["id"] == qa["id"])
    # A late answer to a closed question changes nothing.
    await b.send({"type": "answer", "id": qa["id"], "value": False})
    await a.ws.close()
    await b.ws.close()
    await server.stop()


@pytest.mark.asyncio
async def test_headless_with_nobody_connected_a_question_is_a_cancel():
    core, server, ta, peer = await _serve()
    assert await core.operator.ask(RadioReminder("145.090")) is None
    await server.stop()


@pytest.mark.asyncio
async def test_the_last_client_leaving_cancels_an_open_question():
    core, server, ta, peer = await _serve()
    client = await _join(server)
    await client.next()
    await _until(server.has_clients)
    asked = asyncio.ensure_future(core.operator.ask(RadioReminder("145.090")))
    await client.next(lambda m: m["type"] == "question")
    await client.ws.close()
    assert await asyncio.wait_for(asked, 3) is None
    await server.stop()


@pytest.mark.asyncio
async def test_a_line_to_no_session_transmits_nothing_and_arms_nothing():
    core, server, ta, peer = await _serve()
    client = await _join(server)
    await client.next()
    result = await client.command("c1", "send_line", key="WS1EC-7", text="BBS")
    assert result["ok"] is True and result["value"] is False
    # The notice comes before the result: the command raised it.
    assert {"Not connected."} == {m["text"] for m in client.seen if m["type"] == "notice"}
    assert ta.sent == [] and core.gate.enabled is False
    await client.ws.close()
    await server.stop()


@pytest.mark.asyncio
async def test_a_beacon_from_a_phone_still_refuses_with_the_gate_closed():
    core, server, ta, peer = await _serve()
    client = await _join(server)
    await client.next()
    await client.command("c1", "beacon_now")
    notice = next(m for m in client.seen if m["type"] == "notice")
    assert "Transmit is disabled" in notice["text"]
    assert "Ctrl" not in notice["text"], "a phone was told to press a key it has not got"
    assert ta.sent == []
    await client.ws.close()
    await server.stop()


@pytest.mark.asyncio
async def test_a_remote_connect_arms_the_gate_visibly_and_opens_the_session():
    core, server, ta, peer = await _serve()
    client = await _join(server)
    await client.next()
    result = await client.command("c1", "connect", target="ws1ec-7")
    assert result["ok"] is True
    assert core.gate.enabled is True
    names = [m.get("name") for m in client.seen if m["type"] == "event"]
    assert "GateChanged" in names and "SessionOpened" in names
    assert any(m["type"] == "notice" and "ENABLED" in m["text"] for m in client.seen)
    # The phone shows an hourglass from these, and its Cancel while one is up.
    connecting = [m["data"]["keys"] for m in client.seen
                  if m["type"] == "event" and m["name"] == "ConnectingChanged"]
    assert connecting[0] == ["WS1EC-7"] and connecting[-1] == []
    await client.ws.close()
    await server.stop()
    core.sessions.shutdown()


@pytest.mark.asyncio
async def test_transmit_wants_a_real_boolean():
    core, server, ta, peer = await _serve()
    client = await _join(server)
    await client.next()
    refused = await client.command("c1", "transmit", enabled="false")
    assert refused["ok"] is False and core.gate.enabled is False
    unknown = await client.command("c2", "rm_rf")
    assert unknown["ok"] is False
    await client.ws.close()
    await server.stop()


@pytest.mark.asyncio
async def test_rotating_drops_every_client_and_the_old_token_stops_working(monkeypatch):
    core, server, ta, peer = await _serve()
    monkeypatch.setattr(pairing, "rotate_token", lambda path=None: "n" * 43)
    client = await _join(server)
    await client.next()
    await _until(server.has_clients)
    server.rotate()
    with pytest.raises(ConnectionClosed) as closed:
        await client.next()
    assert closed.value.rcvd.code == UNAUTHORIZED
    again = await _join(server)
    with pytest.raises(ConnectionClosed):
        await again.next()
    await server.stop()


@pytest.mark.asyncio
async def test_inside_the_terminal_the_first_of_screen_or_phone_wins():
    core, server, ta, peer = await _serve(standalone=False)

    class _Screen:
        def __init__(self) -> None:
            self.notices: list[Notice] = []
            self.cancelled = False

        def notice(self, notice):
            self.notices.append(notice)

        async def ask(self, question):
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    screen = _Screen()
    core.operator = FanOutOperator(screen, server.operator)
    # No client connected: the screen is still there to answer, so the
    # remote side waits rather than cancelling.
    asked = asyncio.ensure_future(core.operator.ask(RadioReminder()))
    client = await _join(server)
    await client.next()
    question = await client.next(lambda m: m["type"] == "question")
    await client.send({"type": "answer", "id": question["id"], "value": True})
    assert await asyncio.wait_for(asked, 3) is True
    assert screen.cancelled, "the terminal's question stayed up after the phone answered"
    await client.ws.close()
    await server.stop()


def test_session_text_is_filtered_on_the_station():
    data = b"\x1b[31mred\x1b[0m \x1b]0;title\x07\x9bok\xe2\x80\xae!\r\n"
    message = wire.event(None, 7, ev.SessionData("WS1EC-7", data))
    text = message["data"]["text"]
    assert "\x1b" not in text and "\x9b" not in text and "‮" not in text
    assert text.startswith("red ")
    assert message["data"]["spans"] and message["data"]["spans"][0][:2] == [0, 3]


def test_answers_become_what_the_flow_expects():
    gateway = WinlinkGateway(("W1AW-10",))
    assert wire.answer(gateway, {"target": "W1AW-10", "remember": True}) == \
        GatewayChoice("W1AW-10", True)
    assert wire.answer(gateway, "skip") == SETUP_SKIP
    assert wire.answer(ChooseCategories("W1AW", {"ARES": 2}), {"categories": ["ARES"]}) == \
        (["ARES"], False)
    with pytest.raises(wire.BadAnswer):
        wire.answer(gateway, {"remember": True})
    many = HowManyBulletins("W1AW", 72, ("WX",), 20)
    assert [wire.answer(many, v) for v in (20, 72, 500, -3)] == [20, 72, 72, 0]


def test_the_token_is_kept_private_and_stable(tmp_path):
    path = tmp_path / "remote-token"
    token = pairing.load_token(path)
    assert pairing.load_token(path) == token and len(token) >= 32
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert pairing.rotate_token(path) != token


def test_the_pairing_link_carries_the_token_in_the_fragment():
    serve = ServeConfig(public_url="https://kissterm.example.org/")
    assert pairing.pairing_url(serve, TOKEN) == f"https://kissterm.example.org/#t={TOKEN}"
    assert pairing.websocket_url(serve) == "wss://kissterm.example.org/v1"
    local = ServeConfig(listen="127.0.0.1", port=7425)
    assert pairing.websocket_url(local) == "ws://127.0.0.1:7425/v1"
    assert TOKEN in pairing_text(local, TOKEN)
    from kissterm import __version__
    from kissterm.serve.headless import banner

    assert banner(Config(mycall="N1ABC-1")) == f"kissterm {__version__} serving N1ABC-1"


@pytest.mark.asyncio
async def test_the_settings_a_phone_gets_name_no_keys_and_no_secrets():
    core, server, ta, peer = await _serve()
    client = await _join(server)
    await client.next()
    result = await client.command("c1", "settings_schema")
    fields = [f for section in result["value"] for f in section["fields"]]
    helps = " ".join(f["help"] for f in fields)
    assert "{key:" not in helps and "Ctrl+" not in helps and "F10" not in helps
    assert all(f["value"] is None for f in fields if f["kind"] == "secret")
    await client.ws.close()
    await server.stop()


@pytest.mark.asyncio
async def test_aprs_threads_are_read_with_off_air_text_filtered():
    core, server, ta, peer = await _serve()
    core.aprs.conversations.record_incoming("W1AW-7", "net \x1b[31mstarts\x9b now", number="7")
    client = await _join(server)
    await client.next()
    convos = (await client.command("c1", "aprs_conversations"))["value"]
    assert convos[0]["callsign"] == "W1AW-7"
    thread = (await client.command("c2", "aprs_thread", callsign="w1aw-7"))["value"]
    assert thread[0]["direction"] == "in" and "\x1b" not in thread[0]["text"]
    assert "\x9b" not in thread[0]["text"]
    await client.ws.close()
    await server.stop()


@pytest.mark.asyncio
async def test_a_contact_script_never_leaves_and_an_edit_keeps_it():
    core, server, ta, peer = await _serve()
    core.addressbook.upsert("W1AW-2", script="BBS\nPASSWORD hunter2", note="home")
    client = await _join(server)
    await client.next()
    book = (await client.command("c1", "addressbook"))["value"]
    entry = next(e for e in book if e["target"] == "W1AW-2")
    assert "script" not in entry and entry["has_script"] is True
    assert "hunter2" not in str(book)
    saved = await client.command("c2", "addressbook_save",
                                 entry={"target": "W1AW-2", "note": "home BBS"})
    assert saved["ok"]
    assert core.addressbook.find("W1AW-2").script == "BBS\nPASSWORD hunter2"
    assert core.addressbook.find("W1AW-2").note == "home BBS"
    refused = await client.command("c3", "addressbook_save",
                                   entry={"target": "W1AW-2", "attempts": "99"})
    assert refused["ok"] is False
    await client.ws.close()
    await server.stop()


def test_a_transport_question_sends_names_not_config_entries():
    from kissterm.core.questions import ChooseSessionTransport

    asked = ChooseSessionTransport(({"name": "bbs-ssh", "kind": "ssh", "password": "hunter2"},
                                    {"name": "node", "kind": "telnet"}), "node")
    message = wire.question("q1", asked)
    assert message["data"]["transports"] == ["bbs-ssh", "node"]
    assert "hunter2" not in str(message)



@pytest.mark.asyncio
async def test_a_bbs_message_is_read_with_its_routing_lines(tmp_path):
    from kissterm.mail.message import Message

    core, server, ta, peer = await _serve()
    raw = (b"From: W1BKW\rTo: N1ABC\rType/Status: PN\rDate/Time: 02-Oct 23:21Z\r"
           b"Bid: 8243_W1BKW\rTitle: Hello\rR:261002/2321Z 8243@W1BKW.#OXFO.ME.USA.NOAM BPQ6.0.25\r"
           b"\rHello\r\r[End of Message #3105 from W1BKW]\r")
    ref = core.mail.store.add("Mail/BBS/Inbox", Message(sender="W1BKW", subject="Hello", body="Hello"),
                              raw=raw, raw_suffix=".bbs")
    client = await _join(server)
    await client.next()
    result = await client.command("r1", "mail_read", ref=ref)
    assert result["value"]["routing"] == ["R:261002/2321Z 8243@W1BKW.#OXFO.ME.USA.NOAM BPQ6.0.25"]
    await client.ws.close()
    await server.stop()
    core.sessions.shutdown()


@pytest.mark.asyncio
async def test_a_client_writes_replies_deletes_and_restores_mail():
    """The phone's Write, Reply, Delete and Undo: core methods (`Mail.write`,
    `reply_start`, `delete`, `restore`), none of which transmits."""
    from kissterm.mail.message import Message

    core, server, ta, peer = await _serve()
    ref = core.mail.store.add("Mail/Winlink/Inbox", Message(
        sender="W1AW", to=f"{MYCALL}, K1XYZ", subject="Net", source="Winlink", body="7 pm\n"))
    client = await _join(server)
    await client.next()
    read = (await client.command("r1", "mail_read", ref=ref))["value"]
    assert read["reply_all"] is True and read["reply_on"] == {"form": False, "strip": ""}
    strip = "GYX WEATHER/Location/Sky//"
    asked = core.mail.store.add("Mail/BBS/Inbox", Message(
        sender="W1BKW", to=str(MYCALL), subject="Wx", source="BBS WS1EC", body=f"Answer:\n{strip}\n"))
    key = (await client.command("r1a", "mail_read", ref=asked))["value"]["reply_on"]["strip"]
    assert key == "strip:" + strip
    opened = (await client.command("r1b", "form_start", form=key))["value"]
    assert opened["key"] == key and opened["form"]["fields"]
    start =(await client.command("r2", "mail_reply_start", ref=ref, all=True))["value"]
    assert start["to"] == "W1AW, K1XYZ" and start["send_type"] == "W"
    bad = (await client.command("r3", "mail_write", to="", title="x", body="y"))["value"]
    assert bad["folder"] == "" and bad["problems"]
    good = (await client.command("r4", "mail_write", to=start["to"], title=start["title"],
                                 body="Yes", reply_to=ref))["value"]
    assert good == {"problems": [], "folder": "Mail/Winlink/Outbox"}
    gone = (await client.command("r5", "mail_delete", ref=ref))["value"]
    assert gone.startswith("Mail/Winlink/Deleted/")
    back = (await client.command("r6", "mail_restore", ref=gone))["value"]
    assert back.startswith("Mail/Winlink/Inbox/")
    # All Inboxes, the terminal's combined view, by name.
    core.mail.store.add("Mail/BBS/Inbox", Message(sender="W1BKW", subject="Hi", body="x"))
    every = (await client.command("r7", "mail_list", folder="All Inboxes"))["value"]
    assert {m["folder"] for m in every} == {"Mail/BBS/Inbox", "Mail/Winlink/Inbox"}
    await client.ws.close()
    await server.stop()
    core.sessions.shutdown()


@pytest.mark.asyncio
async def test_a_files_folder_lists_its_files_and_reads_a_preview():
    """The phone showed an empty Files > Downloads with two YAPP downloads
    in it (2026-10-07): `mail_list` asked the message index, which covers
    no files. A Files folder is now the directory, as the terminal lists
    it, and a read is the terminal's preview, never a path outside Files."""
    import io
    import zipfile

    core, server, ta, peer = await _serve()
    folder = core.mail.downloads_dir()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("bulletin.html", "<p>x</p>")
    (folder / "bulletin.html.zip").write_bytes(buffer.getvalue())
    (folder / "notes.md").write_text("# Net\n")
    (folder / ".bulletin.html.zip.from").write_text("hidden")
    client = await _join(server)
    await client.next()
    listed = (await client.command("f1", "mail_list", folder="Files/Downloads"))["value"]
    assert {f["subject"] for f in listed} == {"bulletin.html.zip", "notes.md"}
    zipped = next(f for f in listed if f["subject"] == "bulletin.html.zip")
    assert zipped["file"] is True and zipped["size"] == len(buffer.getvalue())
    read = (await client.command("f2", "mail_read", ref=zipped["ref"]))["value"]
    assert read["kind"] == "zip" and "bulletin.html" in read["body"]
    escape = await client.command("f3", "mail_read", ref="Files/../config.toml")
    assert escape.get("error") or not escape.get("value")
    # Opened: a zip's members, then one member formatted; a bad path is refused.
    opened = (await client.command("f4", "file_open", ref=zipped["ref"]))["value"]
    assert opened["kind"] == "zip" and opened["members"] == [["bulletin.html", 8]]
    inner = (await client.command("f5", "file_open", ref=zipped["ref"],
                                  member=["bulletin.html"]))["value"]
    assert inner["kind"] == "html" and "x" in inner["markdown"]
    notes = (await client.command("f6", "file_open", ref="Files/Downloads/notes.md"))["value"]
    assert notes["kind"] == "markdown" and notes["markdown"].startswith("# Net")
    # A transfer is refused (nothing is connected), and a path outside Files too.
    for args in ({"key": "W1AW-7", "protocol": "yapp", "mode": "upload", "ref": zipped["ref"]},
                 {"key": "W1AW-7", "protocol": "yapp", "mode": "upload", "ref": "Files/../x"}):
        refused = await client.command("f8", "transfer_start", **args)
        assert refused.get("error") and not refused.get("ok", False)
    for bad in ({"ref": "Files/../config.toml"}, {"ref": zipped["ref"], "member": ["nope"]}):
        refused = await client.command("f7", "file_open", **bad)
        assert refused.get("error") and not refused.get("ok", False)
    await client.ws.close()
    await server.stop()
    core.sessions.shutdown()


@pytest.mark.asyncio
async def test_a_client_checks_and_files_a_radiogram():
    """The phone's radiogram form: the station's rules, nothing transmits."""
    core, server, ta, peer = await _serve()
    client = await _join(server)
    await client.next()
    start = (await client.command("g1", "radiogram_start", ics213=True))["value"]
    assert start["handling"] == "HXI" and start["arl"]
    fields = {"number": start["number"], "handling": "HXI", "origin": "N1ABC",
              "place": "WATERBORO ME", "to_name": "EOC", "to_city": "AUGUSTA",
              "to_state": "ME", "to_zip": "04330", "text": "Shelter open.",
              "signature": "JANE DOE MANAGER", "ics_subject": "SHELTER"}
    check = (await client.command("g2", "radiogram_check", fields=fields, ics213=True))["value"]
    assert check["route"] == "ST 04330 @ NTSME" and check["problems"] == []
    saved = (await client.command("g3", "radiogram_write", fields=fields, ics213=True))["value"]
    assert saved == {"problems": [], "folder": "Mail/BBS/Outbox"}
    await client.ws.close()
    await server.stop()
    core.sessions.shutdown()


@pytest.mark.asyncio
async def test_a_client_reads_transcripts_and_bulletin_categories(tmp_path):
    core, server, ta, peer = await _serve()
    core.config.log_dir = str(tmp_path)
    (tmp_path / "20261006-120000_N1ABC-1_W1AW-7.log").write_text("Welcome\n")
    from kissterm.mail.bulletins import SubscriptionBook

    core.mail.subscriptions = SubscriptionBook(tmp_path / "bulletins.json")
    core.mail.subscriptions.for_bbs("WS1EC").seen = {"WX": 3}
    core.mail.bulletin_bbs = lambda: "WS1EC"
    client = await _join(server)
    await client.next()
    [listed] = (await client.command("t1", "transcripts"))["value"]
    assert listed["peer"] == "W1AW-7"
    text = (await client.command("t2", "transcript_read", file=listed["name"]))["value"]
    assert text == "Welcome\n"
    refused = await client.command("t3", "transcript_read", file="../../config.toml")
    assert refused["ok"] is False
    choice = (await client.command("t4", "bulletin_categories"))["value"]
    assert choice == {"bbs": "WS1EC", "seen": {"WX": 3}, "chosen": [], "all": False}
    await client.command("t5", "bulletin_categories_save", picked=["WX"], all=False)
    assert core.mail.bulletin_categories().chosen == ["WX"]
    await client.ws.close()
    await server.stop()
    core.sessions.shutdown()


@pytest.mark.asyncio
async def test_the_waiting_page_is_served_and_the_console_says_what_is_happening(capsys):
    """A restarting station sends its web page to /restarting, which polls
    until the station is back; the console names who asked."""
    pytest.importorskip("starlette")
    from starlette.testclient import TestClient

    from kissterm.serve.http import RESTARTING_PAGE, build_app

    core, server, ta, peer = await _serve()
    page = TestClient(build_app(server, "0")).get("/restarting")
    assert page.status_code == 200 and "location.replace" in page.text
    assert page.text == RESTARTING_PAGE
    core.restarter.by = "a remote client"
    assert core.restarter.what() == "Restarting kissterm (asked from a remote client)..."
    core.restarter.again = False
    assert core.restarter.what().startswith("Shutting down kissterm")
    await server.stop()
    core.sessions.shutdown()
