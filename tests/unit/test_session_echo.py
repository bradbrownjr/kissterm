"""A session's far-end echo is removed (`_SessionLinkAdapter`).

BPQ's Telnet server echoes every byte but the password (LinBPQ
`TelnetV6.c`); over WS1EC's SSH account each line the operator typed showed
twice (operator, 2026-10-02).
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402

from kissterm.ui.app import _SessionLinkAdapter  # noqa: E402


class _Session:
    peer = "packet@ws1ec.example"
    connected = True
    state = None

    def __init__(self) -> None:
        self.incoming: asyncio.Queue[bytes] = asyncio.Queue()
        self.sent: list[bytes] = []

    def on_state_change(self, cb) -> None:
        pass

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        pass


async def _adapter():
    session = _Session()
    adapter = _SessionLinkAdapter(session)
    adapter.ECHO_WAIT = 0.2
    got: list[bytes] = []
    adapter.on_data.append(got.append)
    return session, adapter, got


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_the_echo_of_a_sent_line_is_dropped():
    session, adapter, got = await _adapter()
    await adapter.send(b"routes\r")
    await session.incoming.put(b"routes\r\nCCEMA:WS1EC-15} Routes\r\n")
    await _settle()
    assert b"".join(got) == b"CCEMA:WS1EC-15} Routes\r\n"
    adapter.close()


@pytest.mark.asyncio
async def test_an_echo_split_across_reads_is_still_dropped():
    session, adapter, got = await _adapter()
    await adapter.send(b"c 8 kc1uix-3\r")
    for chunk in (b"c 8 kc", b"1uix-3\r", b"\n", b"CCEMA:WS1EC-15} Connected\r\n"):
        await session.incoming.put(chunk)
    await _settle()
    assert b"".join(got) == b"CCEMA:WS1EC-15} Connected\r\n"
    adapter.close()


@pytest.mark.asyncio
async def test_a_password_the_server_does_not_echo_loses_nothing():
    session, adapter, got = await _adapter()
    await adapter.send(b"secret\r")
    await session.incoming.put(b"\r\nWelcome to the WS1EC-15 packet node.\r\n")
    await _settle()
    assert b"".join(got) == b"\r\nWelcome to the WS1EC-15 packet node.\r\n"
    # And the next line's echo is still caught.
    await adapter.send(b"i\r")
    await session.incoming.put(b"i\r\nCCEMA:WS1EC-15} info\r\n")
    await _settle()
    assert b"".join(got).endswith(b"node.\r\nCCEMA:WS1EC-15} info\r\n")
    adapter.close()


@pytest.mark.asyncio
async def test_text_that_only_begins_like_the_echo_is_delivered_whole():
    session, adapter, got = await _adapter()
    await adapter.send(b"routes\r")
    await session.incoming.put(b"rou")
    await _settle()
    assert got == []
    await session.incoming.put(b"nd and round\r\n")
    await _settle()
    assert b"".join(got) == b"round and round\r\n"
    adapter.close()


@pytest.mark.asyncio
async def test_a_partial_match_left_waiting_is_shown_after_a_moment():
    session, adapter, got = await _adapter()
    await adapter.send(b"routes\r")
    await session.incoming.put(b"rou")
    await _settle()
    await asyncio.sleep(0.3)
    assert b"".join(got) == b"rou"
    adapter.close()
