"""Focused cancellation lifecycle tests for session transports."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402

from kissterm.ax25.address import parse_path  # noqa: E402
from kissterm.transport.base import TransportState  # noqa: E402
from kissterm.transport import kernel_ax25  # noqa: E402
from kissterm.transport.kernel_ax25 import KernelAx25Transport  # noqa: E402
from kissterm.transport.vara import VaraHfTransport  # noqa: E402


@pytest.mark.asyncio
async def test_cancelling_connect_aborts_the_pending_vara_request(monkeypatch):
    """The app cancels SessionTransport.connect() for Ctrl+D, but VARA has
    already received CONNECT by then and needs its explicit ABORT command.
    """
    transport = VaraHfTransport("127.0.0.1", "N1ABC")
    transport.state = TransportState.OPEN
    commands: list[str] = []

    async def record_command(command: str) -> None:
        commands.append(command)

    monkeypatch.setattr(transport, "_send_command", record_command)
    task = asyncio.create_task(transport.connect(parse_path("K1ABC")))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert commands[0] == "CONNECT N1ABC K1ABC"
    assert commands[-1] == "ABORT"


@pytest.mark.asyncio
async def test_cancelling_kernel_ax25_connect_closes_the_partial_socket(monkeypatch):
    """A nonblocking AF_AX25 socket exists before its connect await ends."""

    class FakeSocket:
        closed = False

        def setblocking(self, value: bool) -> None:
            assert value is False

        def close(self) -> None:
            self.closed = True

    class BlockingLoop:
        def __init__(self) -> None:
            self.started = asyncio.Event()

        async def sock_connect(self, sock, address) -> None:
            self.started.set()
            await asyncio.Event().wait()

    fake_socket = FakeSocket()
    loop = BlockingLoop()
    monkeypatch.setattr(kernel_ax25.socket, "socket", lambda *args: fake_socket)
    monkeypatch.setattr(kernel_ax25.asyncio, "get_running_loop", lambda: loop)

    transport = KernelAx25Transport("radio1", "N1ABC")
    transport.state = TransportState.OPEN
    task = asyncio.create_task(transport.connect(parse_path("K1ABC")))
    await asyncio.wait_for(loop.started.wait(), timeout=1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert fake_socket.closed
