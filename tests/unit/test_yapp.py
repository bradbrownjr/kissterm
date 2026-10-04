"""YAPP transfers run over two real connected-mode AX.25 links."""
from __future__ import annotations

import asyncio

import pytest

from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams
from kissterm.yapp import receive_file, send_file
from tests.loopback import loopback_pair


@pytest.mark.asyncio
async def test_yapp_upload_and_download_round_trip_binary_file(tmp_path):
    left, right = loopback_pair()
    await left.open()
    await right.open()
    a = AX25Station(AX25Address.parse("N1ABC"), left, LinkParams(t1=.1, t2=.01, t3=5))
    b = AX25Station(AX25Address.parse("W1AW"), right, LinkParams(t1=.1, t2=.01, t3=5))
    source = tmp_path / "sample.bin"
    payload = bytes(range(256)) + b"\x00YAPP\xff" * 40
    source.write_bytes(payload)
    try:
        incoming = []
        b.on_incoming.append(incoming.append)
        sender_link = await a.connect(AX25Path(AX25Address.parse("W1AW"), AX25Address.parse("N1ABC")))
        await asyncio.sleep(.05)
        receiver_link = incoming[0]
        download = tmp_path / "downloads"
        download.mkdir()
        receiving = asyncio.create_task(receive_file(receiver_link, download, timeout=2))
        await asyncio.sleep(0)
        uploaded = await send_file(sender_link, source, timeout=2)
        received = await receiving
        assert uploaded.size == received.size == len(payload)
        assert received.path.read_bytes() == payload
    finally:
        a.close()
        b.close()


@pytest.mark.asyncio
async def test_a_second_download_of_the_same_name_keeps_the_first(tmp_path):
    """Files > Downloads holds every download; one with a name already
    there is saved beside it (`sample-1.bin`), as AutoBIN does, never over it."""
    left, right = loopback_pair()
    await left.open()
    await right.open()
    a = AX25Station(AX25Address.parse("N1ABC"), left, LinkParams(t1=.1, t2=.01, t3=5))
    b = AX25Station(AX25Address.parse("W1AW"), right, LinkParams(t1=.1, t2=.01, t3=5))
    source = tmp_path / "sample.bin"
    source.write_bytes(b"second copy")
    download = tmp_path / "downloads"
    download.mkdir()
    (download / "sample.bin").write_bytes(b"first copy")
    try:
        incoming = []
        b.on_incoming.append(incoming.append)
        sender_link = await a.connect(AX25Path(AX25Address.parse("W1AW"), AX25Address.parse("N1ABC")))
        await asyncio.sleep(.05)
        receiving = asyncio.create_task(receive_file(incoming[0], download, timeout=2))
        await asyncio.sleep(0)
        await send_file(sender_link, source, timeout=2)
        received = await receiving
        assert received.path.name == "sample-1.bin"
        assert received.path.read_bytes() == b"second copy"
        assert (download / "sample.bin").read_bytes() == b"first copy"
    finally:
        a.close()
        b.close()


class _BpqLink:
    """A link whose far end is BPQMail's YAPP code, byte for byte
    (LinBPQ `BBSUtilities.c`): `script` maps what kissterm sends to what
    BPQ answers, and `sent` records every write."""

    def __init__(self, script: dict[bytes, bytes]) -> None:
        self.on_data: list = []
        self.sent: list[bytes] = []
        self.script = script

    async def send(self, data: bytes) -> None:
        self.sent.append(bytes(data))
        reply = self.script.get(bytes(data[:2]))
        if reply:
            asyncio.get_running_loop().call_soon(self.deliver, reply)

    def deliver(self, data: bytes) -> None:
        for callback in list(self.on_data):
            callback(data)


@pytest.mark.asyncio
async def test_a_download_from_bpqmail_answers_its_two_byte_packets(tmp_path):
    """`YAPP bulletin.html.zip` at WS1EC-2: BPQ sends `ENQ 1` alone and
    waits for `ACK 1` (2026-10-03: kissterm read `ENQ 1` as the start of
    a three-byte packet, answered nothing and timed out)."""
    body = b"PK\x03\x04" + bytes(range(256)) * 2
    chunks = [body[i:i + 254] for i in range(0, len(body), 254)]  # paclen 256 - 2
    header = b"bulletin.html.zip\x00" + str(len(body)).encode() + b"\x00"
    link = _BpqLink({
        b"\x06\x01": bytes((1, len(header))) + header,
        b"\x06\x02": b"".join(bytes((2, len(c))) + c for c in chunks) + b"\x03\x01",
        b"\x06\x03": b"\x04\x01",
    })
    from kissterm.yapp import starts_download

    assert starts_download(b"\x05\x01")
    assert not starts_download(b"File x not found\r")
    result = await receive_file(link, tmp_path, timeout=2, initial=b"\x05\x01")
    assert result.path.read_bytes() == body
    assert link.sent == [b"\x06\x01", b"\x06\x02", b"\x06\x03", b"\x06\x04"]


@pytest.mark.asyncio
async def test_an_upload_to_bpqmail_sends_what_it_parses(tmp_path):
    """BPQ takes an upload at its prompt: `ENQ 1` alone, then the header,
    data packets of at most 255 bytes (a length of 0 is no data to BPQ,
    not 256), `ETX 1` and `EOT 1`, each control packet two bytes."""
    source = tmp_path / "form.txt"
    source.write_bytes(b"x" * 600)
    link = _BpqLink({
        b"\x05\x01": b"\x06\x01",
        b"\x01\x0d": b"\x06\x02",
        b"\x03\x01": b"\x06\x03",
        b"\x04\x01": b"\x06\x04",
    })
    await send_file(link, source, timeout=2)
    assert link.sent[0] == b"\x05\x01"
    assert link.sent[1] == b"\x01\x0dform.txt\x00600\x00"
    data = link.sent[2:-2]
    assert all(p[0] == 2 and 0 < p[1] <= 255 and p[1] == len(p) - 2 for p in data)
    assert b"".join(packet[2:] for packet in data) == b"x" * 600
    assert link.sent[-2:] == [b"\x03\x01", b"\x04\x01"]


@pytest.mark.asyncio
async def test_a_bpqmail_refusal_is_reported_with_its_reason(tmp_path):
    """BPQ refuses an upload whose name is taken with `NAK len reason`."""
    source = tmp_path / "form.txt"
    source.write_bytes(b"x")
    reason = b"YAPP File form.txt already exists\r"
    link = _BpqLink({
        b"\x05\x01": b"\x06\x01",
        b"\x01\x0b": bytes((21, len(reason))) + reason,
    })
    from kissterm.yapp import YappError

    with pytest.raises(YappError, match="refused: YAPP File form.txt already exists"):
        await send_file(link, source, timeout=2)
    # The peer ended it: nothing to cancel.
    assert not any(packet[:1] == b"\x18" for packet in link.sent)


@pytest.mark.asyncio
async def test_a_download_kissterm_gives_up_on_is_cancelled(tmp_path):
    """A header kissterm will not save ends in `CAN len reason`, so BPQ
    leaves YAPP mode (`ProcessYAPPMessage`'s CAN case) instead of eating
    the operator's next line."""
    header = b"../evil.sh\x00" + b"5\x00"
    link = _BpqLink({b"\x06\x01": bytes((1, len(header))) + header})
    from kissterm.yapp import YappError

    with pytest.raises(YappError, match="unsafe"):
        await receive_file(link, tmp_path, timeout=2, initial=b"\x05\x01")
    assert link.sent[0] == b"\x06\x01"
    cancel = link.sent[-1]
    assert cancel[0] == 0x18 and cancel[1] == len(cancel) - 2
    assert b"unsafe" in cancel[2:]


@pytest.mark.asyncio
async def test_a_silent_peer_is_cancelled_after_the_timeout(tmp_path):
    link = _BpqLink({})
    from kissterm.yapp import YappError

    with pytest.raises(YappError, match="did not respond"):
        await receive_file(link, tmp_path, timeout=0.05, initial=b"\x05\x01")
    assert link.sent[-1][:1] == b"\x18"
