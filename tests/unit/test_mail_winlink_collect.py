"""Winlink Send/Receive (`kissterm/mail/winlink_collect.py`) against a
scripted gateway that speaks the master's side of B2F."""

from kissterm import _isolate

_isolate.isolate()

import asyncio  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

from kissterm.mail import Message, MessageStore  # noqa: E402
from kissterm.mail.winlink_collect import (  # noqa: E402
    WINLINK_INBOX,
    WINLINK_OUTBOX,
    WINLINK_SENT,
    WinlinkCollector,
    WinlinkOptions,
)
from kissterm.winlink import b2f, lzhuf  # noqa: E402
from kissterm.winlink import message as b2  # noqa: E402

REAL = Path(__file__).parent / "data" / "winlink" / "LPE5NXDVLVSQ.b2f"


class Gateway:
    """A link whose far end is a Winlink CMS: SID, prompt, then turns."""

    def __init__(self, inbound: list[bytes] = (), *, challenge: bool = False, answer: str = "+",
                 fail_login: bool = False, telnet: bool = False, node: bool = False):
        self.connected = True
        self.on_data: list = []
        self.inbound = list(inbound)
        self.challenge = challenge
        self.answer = answer
        self.fail_login = fail_login
        self.telnet = telnet
        self.telnet_login: list[str] = []
        #: A BPQ node in front: its login, then the command to reach RMS.
        self.node = node
        self.node_login: list[str] = []
        self.handshake: list[str] = []
        self.received: list[bytes] = []
        self._rx = bytearray()
        self._got = asyncio.Event()

    def deliver(self, data: bytes) -> None:
        for callback in list(self.on_data):
            callback(data)

    async def send(self, data: bytes) -> None:
        self._rx += data
        self._got.set()

    async def _need(self, n: int) -> bytes:
        while len(self._rx) < n:
            self._got.clear()
            await self._got.wait()
        chunk = bytes(self._rx[:n])
        del self._rx[:n]
        return chunk

    async def _line(self) -> str:
        while b"\r" not in self._rx:
            self._got.clear()
            await self._got.wait()
        end = self._rx.index(b"\r")
        line = self._rx[:end].decode("latin-1")
        del self._rx[:end + 1]
        return line

    async def _message(self) -> bytes:
        header = await self._need(2)
        assert header[0] == 1
        await self._need(header[1])
        data = bytearray()
        while True:
            kind = (await self._need(1))[0]
            if kind == 4:
                check = (await self._need(1))[0]
                assert (sum(data) + check) & 0xFF == 0
                return lzhuf.decompress(bytes(data))
            size = (await self._need(1))[0]
            data += await self._need(size)

    def _blocks(self, raw: bytes) -> tuple[bytes, int]:
        data = lzhuf.compress(raw)
        out = bytes((1, 7)) + b"Test\x000\x00"
        for start in range(0, len(data), 250):
            out += bytes((2, len(data[start:start + 250]))) + data[start:start + 250]
        return out + bytes((4, -sum(data) & 0xFF)), len(data)

    async def serve(self) -> None:
        if self.node:
            # BPQ's Telnet login: its prompts end with no line end, the
            # first after its option bytes (TelnetV6.c).
            self.deliver(b"\xff\xfb\x01user:")
            self.node_login.append(await self._line())
            self.deliver(b"password:")
            self.node_login.append(await self._line())
            self.deliver(b"Welcome to WS1EC\rWS1EC:WS1EC} ")
            self.node_login.append(await self._line())
        if self.telnet:
            # The CMS Telnet port's own login (wl2k-go listen.go).
            self.deliver(b"Callsign :\r")
            self.telnet_login.append(await self._line())
            self.deliver(b"Password :\r")
            self.telnet_login.append(await self._line())
        self.deliver(b"Connected to WS1EC-10\r[WL2K-5.0-B2FWIHJM$]\r"
                     + (b";PQ: 23753528\r" if self.challenge else b"") + b"CMS >\r")
        while True:
            line = await self._line()
            self.handshake.append(line)
            if line.startswith("; ") and " DE " in line:
                break
        if self.fail_login:
            self.deliver(b"*** [1] Secure login failed - account password does not match. - Disconnecting\r")
            self.connected = False
            return
        client_had_nothing = False
        while True:
            line = await self._line()
            if line == "FQ":
                self.connected = False
                return
            if line == "FF":
                client_had_nothing = True
            else:
                proposals = []
                while not line.startswith("F>"):
                    proposals.append(line)
                    line = await self._line()
                self.deliver(f"FS {self.answer * len(proposals)}\r".encode())
                if self.answer == "+":
                    for _ in proposals:
                        self.received.append(await self._message())
                client_had_nothing = False
            if self.inbound:
                messages, self.inbound = self.inbound, []
                sent = [self._blocks(raw) for raw in messages]
                lines = [f"FC EM {b2.parse(raw).mid} {len(raw)} {size} 0" for raw, (_, size) in zip(messages, sent)]
                self.deliver("".join(f"{x}\r" for x in lines).encode()
                             + f"F> {b2f.checksum(lines):02X}\r".encode())
                answers = (await self._line())[3:]
                for (data, _), answer in zip(sent, answers):
                    if answer == "+":
                        self.deliver(data)
            else:
                self.deliver(b"FQ\r" if client_had_nothing else b"FF\r")
                if client_had_nothing:
                    self.connected = False
                    return


def _store(tmp_path) -> MessageStore:
    store = MessageStore(tmp_path / "mail")
    store.ensure_default_tree()
    return store


async def _run(gateway: Gateway, store, **options):
    log: list[str] = []
    collector = WinlinkCollector(
        gateway, store, WinlinkOptions("KC1JMH", target="WS1EC-10", locator="FN43", **options),
        note=lambda t: log.append(f"* {t}"), sent=lambda t: log.append(f"> {t}"),
        received=lambda t: log.append(f"< {t}"),
    )
    server = asyncio.ensure_future(gateway.serve())
    result = await asyncio.wait_for(collector.run(), 10)
    server.cancel()
    return result, log


def _outbox(store, subject="Net report", to="W1AW", body="All stations accounted for.\n"):
    return store.add(WINLINK_OUTBOX, Message(sender="KC1JMH", to=to, subject=subject, body=body,
                                             date=datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)))


def test_nothing_either_way(tmp_path):
    store = _store(tmp_path)
    result, log = asyncio.run(_run(Gateway(), store))
    assert not result.stopped and not result.filed and not result.sent
    assert "> FF" in log and "< FQ" in log
    assert "< Connected to WS1EC-10" in log  # the node's line, logged


def test_send_and_receive(tmp_path):
    store = _store(tmp_path)
    _outbox(store)
    raw = REAL.read_bytes()
    gateway = Gateway([raw])
    result, log = asyncio.run(_run(gateway, store))
    assert not result.stopped, log
    # Ours arrived whole, with the MID now saved on the message in Sent.
    assert len(gateway.received) == 1
    sent = b2.parse(gateway.received[0])
    assert sent.subject == "Net report" and sent.to == ["W1AW"] and sent.sender == "KC1JMH"
    assert not store.list(WINLINK_OUTBOX)
    assert [store.read(r).message_id for r in result.sent] == [sent.mid]
    assert store.list(WINLINK_SENT)[0].ref == result.sent[0]
    # Theirs is in the Inbox, with its B2 bytes (picture included) beside it.
    [ref] = result.filed
    filed = store.read(ref)
    assert (filed.message_id, filed.sender, filed.source) == ("LPE5NXDVLVSQ", "LA5NTA", "Winlink")
    assert ref.startswith(WINLINK_INBOX)
    [raw_file] = store.raw_files(ref)
    assert raw_file.suffix == ".b2f" and raw_file.read_bytes() == raw
    assert any(line.startswith("> [message ") for line in log)


def test_a_form_goes_with_its_winlink_xml(tmp_path):
    from kissterm.mail import form_xml, forms

    store = _store(tmp_path)
    form = forms.get_form("ics213")
    values = forms.defaults(form, mycall="KC1JMH")
    values.update(inc_name="ICE STORM", Subjectline="Shelter", Message="Open.")
    subject, body = forms.render(form, values)
    xml = form_xml.build(form, values, callsign="KC1JMH")
    store.add(WINLINK_OUTBOX, Message(sender="KC1JMH", to="W1AW", subject=subject, body=body,
                                      date=datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)),
              raw=xml, raw_suffix=".xml")
    gateway = Gateway()
    result, log = asyncio.run(_run(gateway, store))
    assert not result.stopped, log
    sent = b2.parse(gateway.received[0])
    assert sent.files == [("RMS_Express_Form_ICS213_Initial_Viewer.xml", xml)]
    assert "ICE STORM" in sent.text
    # The XML moved to Sent with its message.
    [kept] = store.raw_files(result.sent[0])
    assert kept.read_bytes() == xml


def test_a_message_already_here_is_not_sent_again(tmp_path):
    store = _store(tmp_path)
    raw = REAL.read_bytes()
    asyncio.run(_run(Gateway([raw]), store))
    result, log = asyncio.run(_run(Gateway([raw]), store))
    assert not result.filed and not result.stopped
    assert "> FS -" in log


def test_the_mid_is_kept_for_a_retry(tmp_path):
    store = _store(tmp_path)
    ref = _outbox(store)
    result, _ = asyncio.run(_run(Gateway(answer="="), store))
    assert result.deferred == 1 and not result.sent
    mid = store.read(ref).message_id
    assert len(mid) == 12
    gateway = Gateway()
    asyncio.run(_run(gateway, store))
    assert b2.parse(gateway.received[0]).mid == mid


def test_secure_login_and_a_wrong_password(tmp_path):
    store = _store(tmp_path)
    gateway = Gateway(challenge=True)
    result, log = asyncio.run(_run(gateway, store, password="FooBar"))
    assert not result.stopped and ";PR: 95074758" in gateway.handshake
    # The log shows that it answered, never the answer (beside ;PQ: it
    # would let the password be guessed offline).
    assert "> ;PR: (secure login answer, not logged)" in log
    assert not any("95074758" in line for line in log)
    result, _ = asyncio.run(_run(Gateway(challenge=True, fail_login=True), store, password="x"))
    assert "Secure login failed - account password does not match" in result.stopped


def test_an_unsendable_message_stays_in_the_outbox_with_a_reason(tmp_path):
    store = _store(tmp_path)
    _outbox(store, subject="")
    result, log = asyncio.run(_run(Gateway(), store))
    assert len(store.list(WINLINK_OUTBOX)) == 1
    assert result.skipped and "Subject is empty" in result.skipped[0]
    assert any("Not sent" in line for line in log)


def test_a_closed_gate_stops_before_anything_is_sent(tmp_path):
    store = _store(tmp_path)
    gateway = Gateway()
    collector = WinlinkCollector(
        gateway, store, WinlinkOptions("KC1JMH"), note=lambda t: None, sent=lambda t: None,
        received=lambda t: None, gate_open=lambda: False,
    )

    async def go():
        server = asyncio.ensure_future(gateway.serve())
        result = await asyncio.wait_for(collector.run(), 5)
        server.cancel()
        return result

    result = asyncio.run(go())
    assert result.stopped == "transmit is off" and not gateway.handshake


def test_silence_stops_the_run(tmp_path):
    store = _store(tmp_path)
    gateway = Gateway()
    gateway.serve = lambda: asyncio.sleep(0)
    result, _ = asyncio.run(_run(gateway, store, idle_timeout=0.05))
    assert "nothing from the gateway" in result.stopped


def test_the_cms_telnet_login_comes_first(tmp_path):
    store = _store(tmp_path)
    gateway = Gateway([REAL.read_bytes()], challenge=True, telnet=True)
    result, log = asyncio.run(_run(gateway, store, password="FooBar", telnet_login=True))
    assert not result.stopped, log
    assert gateway.telnet_login == ["KC1JMH", "CMSTelnet"]
    assert ";PR: 95074758" in gateway.handshake  # the real password, only as the answer
    assert "FooBar" not in " ".join(gateway.telnet_login + gateway.handshake)
    assert len(result.filed) == 1


def test_through_a_node_its_login_then_rms_come_first(tmp_path):
    """Operator, 2026-10-02: pull Winlink through the node's RMS
    application over the Home BBS's own Telnet or SSH contact."""
    store = _store(tmp_path)
    gateway = Gateway([REAL.read_bytes()], challenge=True, node=True)
    result, log = asyncio.run(_run(gateway, store, password="FooBar", node_command="RMS",
                                   node_user="KC1JMH", node_password="nodepw"))
    assert not result.stopped, log
    assert gateway.node_login == ["KC1JMH", "nodepw", "RMS"]
    assert ";PR: 95074758" in gateway.handshake
    assert len(result.filed) == 1
    # The node's password is never written to the transcript.
    assert "nodepw" not in "\n".join(log) and "(password sent)" in "\n".join(log)


def test_attachments_are_saved_to_files_and_named_in_the_message(tmp_path):
    from kissterm.winlink import message as b2

    store = _store(tmp_path)
    inbound = b2.serialize(b2.build(
        sender="LA5NTA", to=["KC1JMH"], subject="Plans", body="Attached.",
        files=[("../../plan.txt", b"north gate"), ("plan.txt", b"second copy"),
               ("photo\u202egpj.exe", b"\x00MZ")]))
    result, log = asyncio.run(_run(Gateway([inbound]), store))
    assert not result.stopped and len(result.filed) == 1
    folder = store.root / "Files" / "Attachments"
    names = sorted(p.name for p in folder.iterdir())
    # The path is dropped, the repeat numbered, the bidi override removed.
    assert names == ["photogpj.exe", "plan-1.txt", "plan.txt"]
    assert (folder / "plan.txt").read_bytes() == b"north gate"
    line = store.read(result.filed[0]).extra["Attachments"]
    assert "Files/Attachments/plan.txt (10 bytes)" in line
    assert "Files/Attachments/photogpj.exe (3 bytes)" in line
    assert any("Saved the attachment plan-1.txt" in entry for entry in log)
