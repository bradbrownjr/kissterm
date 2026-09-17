"""BLE GATT KISS transport, using a fake Bleak client instead of a radio."""

from __future__ import annotations

import sys
import types

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm.ax25.address import AX25Address, AX25Path  # noqa: E402
from kissterm.ax25.frame import AX25Frame, UType  # noqa: E402
from kissterm.transport.base import TransportError, TransportState  # noqa: E402
from kissterm.transport.bluetooth import (  # noqa: E402
    MOBILINKD_KISS_NOTIFY_UUID,
    MOBILINKD_KISS_WRITE_UUID,
    BleKissTransport,
)
from kissterm.transport.kiss import encode  # noqa: E402


class _Characteristic:
    max_write_without_response_size = 7


class _Services:
    def get_characteristic(self, _uuid: str) -> _Characteristic:
        return _Characteristic()


class _FakeClient:
    latest: "_FakeClient | None" = None

    def __init__(self, address: str) -> None:
        self.address = address
        self.is_connected = False
        self.services = _Services()
        self.callback = None
        self.writes: list[tuple[str, bytes, bool]] = []
        self.stopped: list[str] = []
        self.disconnected = False
        type(self).latest = self

    async def connect(self) -> None:
        self.is_connected = True

    async def disconnect(self) -> None:
        self.disconnected = True
        self.is_connected = False

    async def start_notify(self, uuid: str, callback) -> None:
        assert uuid == MOBILINKD_KISS_NOTIFY_UUID
        self.callback = callback

    async def stop_notify(self, uuid: str) -> None:
        self.stopped.append(uuid)

    async def write_gatt_char(self, uuid: str, data: bytes, *, response: bool) -> None:
        self.writes.append((uuid, bytes(data), response))


@pytest.fixture
def fake_bleak(monkeypatch):
    _FakeClient.latest = None
    monkeypatch.setitem(sys.modules, "bleak", types.SimpleNamespace(BleakClient=_FakeClient))
    return _FakeClient


def _frame() -> AX25Frame:
    return AX25Frame.u_frame(
        AX25Path(AX25Address("DEST"), AX25Address("SOURCE")), UType.UI, info=b"hello"
    )


@pytest.mark.asyncio
async def test_ble_gatt_decodes_fragmented_notifications_and_chunks_writes(fake_bleak):
    transport = BleKissTransport("AA:BB:CC:DD:EE:FF")
    received: list[AX25Frame] = []
    transport.subscribe(lambda frame, _port: received.append(frame))

    await transport.open()
    client = fake_bleak.latest
    assert client is not None
    assert transport.state is TransportState.OPEN

    inbound = encode(_frame().encode())
    await client.callback(None, bytearray(inbound[:4]))
    await client.callback(None, bytearray(inbound[4:]))
    assert [frame.info for frame in received] == [b"hello"]

    await transport.send_frame(_frame())
    sent = b"".join(data for uuid, data, response in client.writes if uuid == MOBILINKD_KISS_WRITE_UUID)
    assert sent == encode(_frame().encode())
    assert all(response is False for _uuid, _data, response in client.writes)
    assert all(len(data) <= 7 for _uuid, data, _response in client.writes)

    await transport.close()
    assert client.stopped == [MOBILINKD_KISS_NOTIFY_UUID]
    assert client.disconnected
    assert transport.state is TransportState.CLOSED


@pytest.mark.asyncio
async def test_ble_gatt_explains_missing_optional_dependency(monkeypatch):
    monkeypatch.delitem(sys.modules, "bleak", raising=False)
    transport = BleKissTransport("AA:BB:CC:DD:EE:FF")

    # This test only proves the actionable failure branch; the test
    # environment normally does not install Bleak as part of the dev extra.
    import builtins

    real_import = builtins.__import__

    def missing_bleak(name, *args, **kwargs):
        if name == "bleak":
            raise ImportError("no bleak")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_bleak)
    with pytest.raises(TransportError, match=r"pip install kissterm\[ble\]"):
        await transport.open()
    assert transport.state is TransportState.ERROR
