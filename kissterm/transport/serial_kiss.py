"""KISS over a local serial port -- the original TNC connection, still common.

A hardware TNC (Kantronics, MFJ, a Mobilinkd over ``/dev/rfcomm0``, an
Arduino-based soundcard modem) or a software one bound to a virtual serial
pair all show up here identically: a device node that KISS bytes flow across
in both directions with no framing below the OS's own byte stream.

The awkward part is not KISS -- it is that asyncio has no *portable* serial
support of its own. `pyserial-asyncio-fast` (a maintained fork with a tighter
read loop) is what this module prefers; the older `pyserial-asyncio` is the
fallback. Neither is guaranteed to be present, and on a Raspberry Pi running
a stock Raspbian image it is common for *neither* to be installed while
plain `pyserial` is, because `pyserial-asyncio` pulls in a C extension chain
that does not always build cleanly on ARM. Rather than make kissterm
uninstallable there, this module falls back to a blocking `serial.Serial`
pumped from a thread via `loop.run_in_executor` -- slower and with one extra
context switch per read, but it works everywhere pyserial itself works, which
is everywhere. All three paths converge on the same `KissDecoder` and the same
`dispatch`, so nothing above this module needs to know or care which one is
active.

Imports are deferred to `open()`, not module scope, so that merely importing
`kissterm.transport` never fails on a machine with no serial support at all
(a TCP-only Direwolf setup, for instance, has no business needing pyserial).
"""

from __future__ import annotations

import asyncio
import contextlib

from ..ax25.address import AX25AddressError
from ..ax25.frame import AX25Frame, AX25FrameError
from .base import FrameTransport, TransportError, TransportInfo, TransportState
from .kiss import (
    KissCommand,
    KissDecoder,
    encode,
    exit_kiss,
    set_hardware,
)

#: KISS command bytes take one parameter byte, per the original KISS spec.
#: TXDELAY and TXTAIL are in 10ms units; PERSIST is a raw persistence value
#: (0-255 approximating a 0.0-1.0 probability); SLOTTIME is in 10ms units;
#: FULLDUPLEX is 0 (half) or 1 (full). kiss_params keys use these names.
_PARAM_COMMANDS: dict[str, KissCommand] = {
    "txdelay": KissCommand.TXDELAY,
    "persist": KissCommand.PERSIST,
    "slottime": KissCommand.SLOTTIME,
    "txtail": KissCommand.TXTAIL,
    "fullduplex": KissCommand.FULLDUPLEX,
}


class SerialKissTransport(FrameTransport):
    """KISS framing over a local serial device.

    ``ports`` mirrors `FrameTransport` -- a TNC with several KISS ports
    multiplexed onto one serial line (rare, but some multi-channel hardware
    does this) is still one transport. ``init_delay`` exists because a good
    number of USB-serial TNCs and Arduino modems reset on DTR assertion when
    the port opens, and the first bytes written before the reset completes
    are simply lost; sleeping briefly before sending KISS parameters avoids a
    confusing "it worked the second time" bug report.
    """

    def __init__(
        self,
        device: str,
        baud: int = 9600,
        ports: int = 1,
        init_delay: float = 0.0,
        kiss_params: dict | None = None,
        leave_kiss_on_close: bool = False,
    ) -> None:
        info = TransportInfo(
            kind="serial",
            name=device,
            detail=f"{device} @ {baud}",
            tier="frame",
        )
        super().__init__(info, ports=ports)
        self.device = device
        self.baud = baud
        self.init_delay = init_delay
        self.kiss_params = kiss_params or {}
        self.leave_kiss_on_close = leave_kiss_on_close

        self.decode_errors = 0

        # Exactly one of these two I/O strategies is populated by open(),
        # depending on what is importable. `_writer` abstracts the difference
        # away from send_frame so it does not need to know which is active.
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._blocking_serial = None  # a serial.Serial, thread-pumped fallback
        self._read_task: asyncio.Task[None] | None = None
        self._decoder = KissDecoder()

    async def open(self) -> None:
        self.state = TransportState.OPENING
        self._error = ""
        try:
            await self._open_backend()
        except TransportError:
            self.state = TransportState.ERROR
            raise
        except Exception as exc:  # noqa: BLE001 -- surfaced via TransportError
            self.state = TransportState.ERROR
            self._error = str(exc)
            raise TransportError(f"could not open {self.device}: {exc}") from exc

        if self.init_delay:
            await asyncio.sleep(self.init_delay)

        await self._send_kiss_params()

        self._read_task = asyncio.create_task(
            self._read_loop(), name=f"serial-kiss-read:{self.device}"
        )
        self.state = TransportState.OPEN

    async def _open_backend(self) -> None:
        """Pick the best available serial I/O strategy, in preference order."""
        try:
            import serial_asyncio_fast as serial_asyncio  # type: ignore[import-untyped]
        except ImportError:
            try:
                import serial_asyncio  # type: ignore[import-untyped,no-redef]
            except ImportError:
                await self._open_blocking_fallback()
                return

        self._reader, self._writer = await serial_asyncio.open_serial_connection(
            url=self.device, baudrate=self.baud
        )

    async def _open_blocking_fallback(self) -> None:
        """Pump a blocking ``serial.Serial`` from a thread.

        Used when neither `serial_asyncio_fast` nor `serial_asyncio` is
        importable but plain `pyserial` is -- the common state of affairs on
        a Raspberry Pi. Reads happen in a dedicated thread via
        `run_in_executor` because `serial.Serial.read` blocks the calling
        thread until data arrives or it times out; a short read timeout on
        the port keeps that thread responsive to cancellation instead of
        wedging the whole event loop's default executor.
        """
        try:
            import serial  # type: ignore[import-untyped]
        except ImportError as exc:
            raise TransportError(
                "no serial backend available. Install one of: "
                "'pip install pyserial-asyncio-fast' (preferred), "
                "'pip install pyserial-asyncio', or at minimum "
                "'pip install pyserial' for the blocking fallback."
            ) from exc

        loop = asyncio.get_running_loop()

        def _open() -> "serial.Serial":
            return serial.Serial(self.device, self.baud, timeout=0.25)

        self._blocking_serial = await loop.run_in_executor(None, _open)

    async def _send_kiss_params(self) -> None:
        for port in range(self.ports):
            for key, command in _PARAM_COMMANDS.items():
                if key not in self.kiss_params:
                    continue
                value = int(self.kiss_params[key])
                await self._write(encode(bytes([value]), port, command))
            hw = self.kiss_params.get("sethardware")
            if hw is not None:
                payload = hw.encode("ascii") if isinstance(hw, str) else bytes(hw)
                await self._write(set_hardware(payload, port))

    async def _write(self, data: bytes) -> None:
        if self._writer is not None:
            self._writer.write(data)
            await self._writer.drain()
        elif self._blocking_serial is not None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._blocking_serial.write, data)
        else:
            raise TransportError("serial transport is not open")

    async def _read_loop(self) -> None:
        try:
            if self._reader is not None:
                await self._read_loop_asyncio()
            else:
                await self._read_loop_blocking()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- a dead read loop must not crash the app
            self.state = TransportState.ERROR
            self._error = f"read loop failed: {exc}"

    async def _read_loop_asyncio(self) -> None:
        assert self._reader is not None
        while True:
            chunk = await self._reader.read(1024)
            if not chunk:
                # EOF: the underlying device vanished (USB-serial unplugged).
                self.state = TransportState.ERROR
                self._error = "serial port closed (device disconnected?)"
                return
            await self._feed(chunk)

    async def _read_loop_blocking(self) -> None:
        assert self._blocking_serial is not None
        loop = asyncio.get_running_loop()
        while True:
            chunk = await loop.run_in_executor(
                None, self._blocking_serial.read, 1024
            )
            if chunk:
                await self._feed(chunk)
            # An empty chunk here just means the read timeout (0.25s) elapsed
            # with nothing to report -- normal for a blocking read, not EOF.

    async def _feed(self, chunk: bytes) -> None:
        for port, command, payload in self._decoder.feed(chunk):
            if command != KissCommand.DATA:
                continue  # parameter echoes and hardware replies, not traffic
            try:
                frame = AX25Frame.decode(payload)
            except (AX25FrameError, AX25AddressError):
                # RF is noisy; a garbled frame is routine, not exceptional.
                # AX25Frame.decode raises AX25AddressError (not caught by
                # AX25FrameError alone) for a malformed address field, which
                # is at least as common as a bad control byte on real RF, so
                # both must be swallowed here. Killing the read loop over one
                # bad frame would lose every frame after it too.
                self.decode_errors += 1
                continue
            await self.dispatch(frame, port)

    async def _send_frame(self, frame: AX25Frame, port: int = 0) -> None:
        if self.state is not TransportState.OPEN:
            raise TransportError("serial transport is not open")
        await self._write(encode(frame.encode(), port))

    async def close(self) -> None:
        if self._read_task is not None:
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._read_task
            self._read_task = None

        if self.leave_kiss_on_close:
            with contextlib.suppress(Exception):
                for port in range(self.ports):
                    await self._write(exit_kiss(port))

        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()
            self._writer = None
            self._reader = None
        if self._blocking_serial is not None:
            with contextlib.suppress(Exception):
                self._blocking_serial.close()
            self._blocking_serial = None

        self.state = TransportState.CLOSED
