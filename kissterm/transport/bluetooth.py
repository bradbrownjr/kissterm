"""KISS over Bluetooth RFCOMM -- Mobilinkd TNC2/TNC3 and the clones of them.

The Mobilinkd family (and most compatible TNCs) speak plain KISS over a
classic-Bluetooth RFCOMM serial profile. Once paired, every mainstream OS
turns that into a socket. On Linux specifically there are two equally valid
ways to reach it:

1. Let ``rfcomm`` bind the paired device to ``/dev/rfcommN`` and hand that
   device path to `kissterm.transport.serial_kiss.SerialKissTransport`. This
   needs no code in this module at all -- from pyserial's point of view a
   bound RFCOMM device node is indistinguishable from a USB-serial TNC, and
   reusing the serial transport means the pyserial-asyncio-fast /
   pyserial-asyncio / blocking-thread fallback chain that module already has
   is inherited for free. This is the recommended route and the one to reach
   for first.

2. Open an `AF_BLUETOOTH` / `BTPROTO_RFCOMM` socket directly, skipping the
   `rfcomm` bind step. That is what this module implements: useful when a
   device should not need a persistent `/dev/rfcommN` binding managed by udev
   or `rfcomm.conf`, or on setups where creating one is inconvenient
   (containers, machines without `bluez-utils` rfcomm tooling installed).

`socket.AF_BLUETOOTH` exists only where `bluez`'s socket support was compiled
into Python (Linux; CPython does not expose it on macOS or Windows), so the
same import-time-safe pattern as `kernel_ax25.py` applies: never fail at
import, only when `open()` is actually asked to use it.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket

from ..ax25.address import AX25AddressError
from ..ax25.frame import AX25Frame, AX25FrameError
from .base import FrameTransport, TransportError, TransportInfo, TransportState
from .kiss import KissCommand, KissDecoder, encode

#: RFCOMM channel most Bluetooth-serial TNCs advertise for their SPP-alike
#: service. It is *not* universally 1 -- some stacks assign it dynamically
#: and expect SDP channel discovery -- but plain channel 1 is what the
#: common Mobilinkd pairing instructions assume and is a reasonable default.
DEFAULT_RFCOMM_CHANNEL = 1


class BluetoothKissTransport(FrameTransport):
    """KISS framing over a direct ``AF_BLUETOOTH``/RFCOMM socket.

    ``address`` is the remote device's Bluetooth MAC (``"AA:BB:CC:DD:EE:FF"``).
    Prefer `SerialKissTransport` against a `/dev/rfcommN` path instead of this
    class unless there is a specific reason to avoid the OS-level RFCOMM bind
    step -- see the module docstring.
    """

    def __init__(self, address: str, channel: int = DEFAULT_RFCOMM_CHANNEL, ports: int = 1) -> None:
        info = TransportInfo(
            kind="bluetooth",
            name=address,
            detail=f"{address} ch{channel} (RFCOMM)",
            tier="frame",
        )
        super().__init__(info, ports=ports)
        self.address = address
        self.channel = channel

        self.decode_errors = 0

        self._sock: socket.socket | None = None
        self._read_task: asyncio.Task[None] | None = None
        self._decoder = KissDecoder()

    async def open(self) -> None:
        if not hasattr(socket, "AF_BLUETOOTH") or not hasattr(socket, "BTPROTO_RFCOMM"):
            self.state = TransportState.ERROR
            self._error = "AF_BLUETOOTH/RFCOMM sockets are not available on this platform"
            raise TransportError(
                "Bluetooth RFCOMM sockets are not available on this platform "
                "(this needs Linux + BlueZ). Bind the device with 'rfcomm "
                "bind' and use SerialKissTransport against the resulting "
                "/dev/rfcommN instead."
            )

        self.state = TransportState.OPENING
        self._error = ""
        loop = asyncio.get_running_loop()
        sock: socket.socket | None = None
        try:
            # `hasattr` above only proves the AF_BLUETOOTH/BTPROTO_RFCOMM
            # constants exist in this Python build; the kernel can still lack
            # Bluetooth support entirely (no controller, bluez not running),
            # which socket.socket() itself is what fails on. Constructing the
            # socket inside this try, not before it, is what turns that into
            # a clean TransportError instead of a raw OSError escaping open().
            sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            sock.setblocking(False)

            # RESEARCH: the exact sockaddr tuple shape for BTPROTO_RFCOMM
            # connect() is (address, channel) per CPython's socket docs for
            # AF_BLUETOOTH, but this has not been exercised against a real
            # paired Mobilinkd device -- verify before relying on it, and
            # confirm PIN/pairing must already be complete via bluetoothctl
            # first (this socket layer does no pairing of its own).
            await loop.sock_connect(sock, (self.address, self.channel))
        except OSError as exc:
            if sock is not None:
                sock.close()
            self.state = TransportState.ERROR
            self._error = str(exc)
            raise TransportError(f"RFCOMM connect to {self.address} failed: {exc}") from exc

        self._sock = sock
        self._read_task = asyncio.create_task(
            self._read_loop(), name=f"bt-kiss-read:{self.address}"
        )
        self.state = TransportState.OPEN

    async def _read_loop(self) -> None:
        assert self._sock is not None
        loop = asyncio.get_running_loop()
        try:
            while True:
                chunk = await loop.sock_recv(self._sock, 1024)
                if not chunk:
                    self.state = TransportState.ERROR
                    self._error = "RFCOMM socket closed by peer"
                    return
                for port, command, payload in self._decoder.feed(chunk):
                    if command != KissCommand.DATA:
                        continue
                    try:
                        frame = AX25Frame.decode(payload)
                    except (AX25FrameError, AX25AddressError):
                        # A dropped Bluetooth packet or a noisy RF hop behind
                        # the TNC produces garbage now and then; one bad
                        # frame must not take the link down. Address-field
                        # failures raise AX25AddressError, not AX25FrameError,
                        # so both are caught here.
                        self.decode_errors += 1
                        continue
                    await self.dispatch(frame, port)
        except asyncio.CancelledError:
            raise
        except OSError as exc:
            self.state = TransportState.ERROR
            self._error = str(exc)

    async def _send_frame(self, frame: AX25Frame, port: int = 0) -> None:
        if self._sock is None or self.state is not TransportState.OPEN:
            raise TransportError("Bluetooth transport is not open")
        loop = asyncio.get_running_loop()
        await loop.sock_sendall(self._sock, encode(frame.encode(), port))

    async def close(self) -> None:
        if self._read_task is not None:
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._read_task
            self._read_task = None
        if self._sock is not None:
            with contextlib.suppress(Exception):
                self._sock.close()
            self._sock = None
        self.state = TransportState.CLOSED


# Mobilinkd's documented KISS TNC service. Keep these configurable because a
# BLE-UART bridge can expose KISS with different UUIDs.
MOBILINKD_KISS_SERVICE_UUID = "00000001-ba2a-46c9-ae49-01b0961f68bb"
MOBILINKD_KISS_NOTIFY_UUID = "00000002-ba2a-46c9-ae49-01b0961f68bb"
MOBILINKD_KISS_WRITE_UUID = "00000003-ba2a-46c9-ae49-01b0961f68bb"


class BleKissTransport(FrameTransport):
    """KISS over a BLE GATT UART service, including Mobilinkd TNC4.

    ``address`` is a paired device address on Linux/Windows or the UUID that
    CoreBluetooth reports on macOS. The default UUIDs are Mobilinkd's KISS TNC
    service; ``notify_uuid`` and ``write_uuid`` allow another KISS BLE-UART
    bridge to be configured explicitly. Pairing remains the operating
    system's job -- opening this transport never starts a scan or transmits.
    """

    def __init__(
        self,
        address: str,
        *,
        notify_uuid: str = MOBILINKD_KISS_NOTIFY_UUID,
        write_uuid: str = MOBILINKD_KISS_WRITE_UUID,
        ports: int = 1,
    ) -> None:
        info = TransportInfo(
            kind="ble",
            name=address,
            detail=f"{address} (BLE GATT)",
            tier="frame",
        )
        super().__init__(info, ports=ports)
        self.address = address
        self.notify_uuid = notify_uuid
        self.write_uuid = write_uuid
        self.decode_errors = 0
        self._client: object | None = None
        self._decoder = KissDecoder()

    async def open(self) -> None:
        # Bleak must stay lazy: constructing every configured transport at
        # startup cannot make TCP-only installations require its BLE extra.
        try:
            from bleak import BleakClient
        except ImportError as exc:
            self.state = TransportState.ERROR
            self._error = "Bleak is not installed"
            raise TransportError(
                "BLE KISS support needs the optional bleak dependency; "
                "install it with 'pip install kissterm[ble]'"
            ) from exc

        self.state = TransportState.OPENING
        self._error = ""
        client = BleakClient(self.address)
        try:
            await client.connect()
            if not client.is_connected:
                raise TransportError(f"BLE device {self.address} did not connect")
            await client.start_notify(self.notify_uuid, self._notification)
        except Exception as exc:
            with contextlib.suppress(Exception):
                await client.disconnect()
            self.state = TransportState.ERROR
            self._error = str(exc)
            if isinstance(exc, TransportError):
                raise
            raise TransportError(f"BLE connect to {self.address} failed: {exc}") from exc

        self._client = client
        self.state = TransportState.OPEN

    async def _notification(self, _sender: object, data: bytearray) -> None:
        """Decode notifications incrementally; BLE may split a KISS frame."""
        try:
            for port, command, payload in self._decoder.feed(bytes(data)):
                if command != KissCommand.DATA:
                    continue
                try:
                    frame = AX25Frame.decode(payload)
                except (AX25FrameError, AX25AddressError):
                    self.decode_errors += 1
                    continue
                await self.dispatch(frame, port)
        except Exception as exc:  # A malformed notification must not stop BLE RX.
            self.decode_errors += 1
            self._error = f"BLE notification processing failed: {exc}"

    async def _send_frame(self, frame: AX25Frame, port: int = 0) -> None:
        client = self._client
        if client is None or self.state is not TransportState.OPEN:
            raise TransportError("BLE transport is not open")

        packet = encode(frame.encode(), port)
        # Bleak exposes the negotiated command-write size on the resolved
        # characteristic. The BLE minimum is 20 bytes, a safe fallback for
        # fake/older backends which do not expose that property.
        services = getattr(client, "services", None)
        characteristic = services.get_characteristic(self.write_uuid) if services else None
        chunk_size = getattr(characteristic, "max_write_without_response_size", 20) or 20
        for start in range(0, len(packet), chunk_size):
            await client.write_gatt_char(
                self.write_uuid, packet[start : start + chunk_size], response=False
            )

    async def close(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            with contextlib.suppress(Exception):
                await client.stop_notify(self.notify_uuid)
            with contextlib.suppress(Exception):
                await client.disconnect()
        self._decoder.reset()
        self.state = TransportState.CLOSED
