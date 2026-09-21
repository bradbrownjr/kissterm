"""AutoBIN transfers run over two real connected-mode AX.25 links."""
from __future__ import annotations

import asyncio

import pytest

from kissterm.autobin import AutoBinError, crc16, receive_file, send_file
from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams
from tests.loopback import loopback_pair


def test_autobin_crc_matches_the_published_ccitt_variant():
    assert crc16(b"123456789") == 0x31C3


@pytest.mark.asyncio
async def test_autobin_bad_checksum_leaves_no_download(tmp_path):
    class Link:
        def __init__(self):
            self.on_data = []
            self.sent = []

        async def send(self, data):
            self.sent.append(data)

    link = Link()
    receiving = asyncio.create_task(receive_file(link, tmp_path, timeout=.2))
    await asyncio.sleep(0)
    for callback in link.on_data:
        callback(b"#BIN#3#|0#bad.bin\rabc")
    with pytest.raises(AutoBinError, match="checksum"):
        await receiving
    assert link.sent == [b"#OK#\r"]
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_autobin_upload_and_download_round_trip_binary_file(tmp_path):
    left, right = loopback_pair()
    await left.open()
    await right.open()
    a = AX25Station(AX25Address.parse("N1ABC"), left, LinkParams(t1=.1, t2=.01, t3=5))
    b = AX25Station(AX25Address.parse("W1AW"), right, LinkParams(t1=.1, t2=.01, t3=5))
    source = tmp_path / "sample.bin"
    payload = bytes(range(256)) + b"\x00AutoBIN\xff" * 40
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
