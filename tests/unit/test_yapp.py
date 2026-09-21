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
