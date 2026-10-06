"""`kissterm --serve` stops on Esc or Ctrl+Q at its terminal (operator,
2026-10-06: "make ^q or even just ESC work to exit it"), on a real
pseudo-terminal: what is read, and that the terminal is put back."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

import pytest  # noqa: E402

from kissterm.serve.headless import is_quit, watch_keys  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX terminals")


def test_esc_alone_or_ctrl_q_stops_and_an_arrow_key_does_not():
    assert is_quit(b"\x1b") and is_quit(b"\x11") and is_quit(b"ab\x11")
    assert not is_quit(b"\x1b[A") and not is_quit(b"q") and not is_quit(b"\x03")


async def _until(event: asyncio.Event, seconds: float = 2.0) -> bool:
    try:
        await asyncio.wait_for(event.wait(), seconds)
    except asyncio.TimeoutError:
        return False
    return True


@pytest.mark.asyncio
@pytest.mark.parametrize("key", [b"\x1b", b"\x11"])
async def test_a_key_at_the_terminal_stops_the_station_and_restores_it(key):
    import pty
    import termios

    controller, terminal = pty.openpty()
    try:
        before = termios.tcgetattr(terminal)
        stop = asyncio.Event()
        undo = watch_keys(stop, terminal)
        assert undo is not None
        mode = termios.tcgetattr(terminal)
        assert not mode[0] & termios.IXON, "Ctrl+Q would be eaten as XON"
        assert mode[3] & termios.ISIG, "Ctrl+C must still stop it"
        os.write(controller, b"\x1b[A")  # an arrow key: keeps serving
        assert not await _until(stop, 0.3)
        os.write(controller, key)
        assert await _until(stop)
        undo()
        assert termios.tcgetattr(terminal) == before
    finally:
        os.close(controller)
        os.close(terminal)


@pytest.mark.asyncio
async def test_with_no_terminal_nothing_is_watched():
    read, write = os.pipe()
    try:
        assert watch_keys(asyncio.Event(), read) is None
    finally:
        os.close(read)
        os.close(write)
