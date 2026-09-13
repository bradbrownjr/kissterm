"""Focused lifecycle tests for the VARA session transport."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402

from kissterm.ax25.address import parse_path  # noqa: E402
from kissterm.transport.base import TransportState  # noqa: E402
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
