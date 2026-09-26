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
                 fail_login: bool = False):
        self.connected = True
        self.on_data: list = []
        self.inbound = list(inbound)
        self.challenge = challenge
        self.answer = answer
        self.fail_login = fail_login
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
    result, _ = asyncio.run(_run(gateway, store, password="FooBar"))
    assert not result.stopped and ";PR: 95074758" in gateway.handshake
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
