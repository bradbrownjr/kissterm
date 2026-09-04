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

    async def send_frame(self, frame: AX25Frame, port: int = 0) -> None:
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


class BleKissTransport(FrameTransport):
    """Not implemented: BLE (GATT) TNCs such as the Mobilinkd TNC4 family.

    TNC4-class devices drop classic Bluetooth/RFCOMM entirely and speak KISS
    framed over a vendor GATT service (a characteristic for TX, one for RX,
    typically driven with notify/write-without-response) instead of a serial
    profile. That needs a BLE stack in Python -- realistically `bleak`, since
    it is the only actively-maintained cross-platform option -- plus the
    vendor's specific service/characteristic UUIDs, which have not been
    looked up here. Rather than guess at UUIDs and produce something that
    silently fails to find its characteristics on real hardware, this is
    left as an explicit stub.

    Roadmapped, not built: see docs/ROADMAP.md.
    """

    _NOT_IMPLEMENTED = (
        "BLE GATT KISS TNCs (e.g. Mobilinkd TNC4) are not implemented yet "
        "-- this needs a 'bleak' dependency and vendor GATT UUIDs. "
        "See docs/ROADMAP.md."
    )

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError(self._NOT_IMPLEMENTED)

    async def open(self) -> None:
        raise NotImplementedError(self._NOT_IMPLEMENTED)

    async def close(self) -> None:
        raise NotImplementedError(self._NOT_IMPLEMENTED)

    async def send_frame(self, frame: AX25Frame, port: int = 0) -> None:
        raise NotImplementedError(self._NOT_IMPLEMENTED)
