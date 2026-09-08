"""Paste protection: roadmap P2's bracketed-paste-style guard.

The channel the send line writes to has a real airtime cost and no protocol
of its own to reject anything -- so a paste, which can carry far more than a
keystroke ever would (multiple lines, thousands of characters, raw control
bytes from a binary clipboard), is sanitized in `_SendInput._on_paste`
*before* it ever reaches the field a plain Enter would transmit. This is the
opposite direction from `ansi.py`/`monitor.sanitize()`: those protect the
local screen from a remote station, this protects the channel from the
operator's own clipboard.
"""

from __future__ import annotations

import asyncio

import pytest
from textual import events
from textual.widgets import Input

from kissterm._isolate import isolate

isolate()

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.terminal_pane import _MAX_PASTE_CHARS  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
PEER = AX25Address.parse("WS1EC-7")


async def _connected_app():
    """A connected app on a loopback, transmit armed -- close enough to
    real use to check what actually goes out, not just what the field
    displays."""
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    a = AX25Station(MYCALL, ta, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    b = AX25Station(PEER, tb, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    incoming: list = []
    b.on_incoming.append(incoming.append)
    config = Config(mycall=str(MYCALL))
    config.tx_armed_at_start = True
    app = KissTermApp(config, a)
    return app, a, b, incoming


def _record_notices(app) -> list[str]:
    seen: list[str] = []
    app.notify = lambda message, *args, **kwargs: seen.append(message)
    return seen


async def _paste(pilot, app, text: str) -> None:
    field = app.query_one("#session-input", Input)
    field.focus()
    await pilot.pause()
    field.post_message(events.Paste(text))
    await pilot.pause()


@pytest.mark.asyncio
async def test_clean_short_paste_passes_through_untouched():
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        notices = _record_notices(app)
        await _paste(pilot, app, "CQ CQ DE N1ABC")

        assert app.query_one("#session-input", Input).value == "CQ CQ DE N1ABC"
        assert notices == []
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_multiline_paste_keeps_only_the_first_line_and_says_so():
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        notices = _record_notices(app)
        await _paste(pilot, app, "first line\nsecond line\nthird line")

        assert app.query_one("#session-input", Input).value == "first line"
        assert any("first line" in n for n in notices)
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_control_bytes_are_stripped_and_reported():
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        notices = _record_notices(app)
        # ESC, and a NUL, as a binary clipboard or a copied terminal
        # session might carry.
        await _paste(pilot, app, "ls \x1b[2Jdone\x00")

        assert app.query_one("#session-input", Input).value == "ls [2Jdone"
        assert any("control characters" in n for n in notices)
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_a_long_paste_is_cut_to_the_cap_and_says_so():
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        notices = _record_notices(app)
        await _paste(pilot, app, "x" * (_MAX_PASTE_CHARS * 4))

        value = app.query_one("#session-input", Input).value
        assert len(value) == _MAX_PASTE_CHARS
        assert any(str(_MAX_PASTE_CHARS) in n for n in notices)
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_sanitized_paste_is_what_actually_transmits():
    """The guard has to run before `send_line`, not just before display --
    otherwise a widget could show the clean text while the raw paste still
    reaches the wire some other way."""
    app, a, b, incoming = await _connected_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        assert link is not None
        app._bind_link(link)
        await asyncio.sleep(0.1)
        far = incoming[0]

        await _paste(pilot, app, "hello\x1bworld\nignored second line")
        await pilot.press("enter")
        await asyncio.sleep(0.4)

        assert app.query_one("#session-input", Input).value == ""
        sent = far.read_nowait().decode("latin-1")
        assert "helloworld" in sent
        assert "ignored" not in sent
        assert "\x1b" not in sent
    a.close()
    b.close()
