"""The terminal is read-only above, deliberate below.

The guarantee these tests defend: the scrollback is display-only and copyable,
and the ONLY way bytes reach the air is a deliberate commit -- Enter in the
input, or the Send button. Suggestions and the command reference may fill the
input; nothing may transmit on its own.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402
import inspect  # noqa: E402

import pytest  # noqa: E402
from textual.widgets import Button, Input, RichLog  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.nodes import CommandReference, load_family  # noqa: E402
from kissterm.ui import terminal_pane as tp  # noqa: E402
from kissterm.ui.dialogs import CommandReferenceScreen  # noqa: E402
from kissterm.ui.terminal_pane import TerminalPane, linkify  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
PEER = AX25Address.parse("WS1EC-7")


async def _connected_app():
    """An app with a real, connected link on a loopback -- no radio."""
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    a = AX25Station(MYCALL, ta, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    b = AX25Station(PEER, tb, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    incoming: list = []
    b.on_incoming.append(incoming.append)
    app = KissTermApp(Config(mycall=str(MYCALL)), a)
    return app, a, b, incoming


# ---------------------------------------------------------------------------
# Read-only, selectable, linkable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scrollback_is_a_log_not_an_editable_field():
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        log = app.query_one("#session-log")
        assert isinstance(log, RichLog), "scrollback must not be an editable widget"
        assert not isinstance(log, Input)
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_scrollback_allows_text_selection_for_copying():
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        assert app.query_one("#session-log").ALLOW_SELECT is True
    a.close()
    b.close()


def test_urls_become_links_with_the_target_matching_the_text():
    """A remote station must not be able to display one address and open another."""
    text = linkify("see http://example.com/x for details")
    spans = [s for s in text.spans if "link" in str(s.style)]
    assert spans, "no link produced"
    shown = str(text)[spans[0].start : spans[0].end]
    assert shown == "http://example.com/x"
    assert f"link {shown}" in str(spans[0].style), "link target differs from the text"


def test_trailing_punctuation_is_not_swallowed_into_a_link():
    text = linkify("visit https://example.com/page, then stop.")
    span = next(s for s in text.spans if "link" in str(s.style))
    assert str(text)[span.start : span.end] == "https://example.com/page"


def test_linkify_leaves_ordinary_text_alone():
    assert str(linkify("no urls here at all")) == "no urls here at all"


@pytest.mark.asyncio
async def test_incoming_text_is_still_sanitized_before_linkifying():
    """Linkification must not become a way around the sanitize rule."""
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        pane.write_incoming(b"\x1b[2J\x1b]0;pwned\x07go to http://example.com/x\r\n")
        await pilot.pause()
        rendered = "\n".join(str(line) for line in app.query_one("#session-log").lines)
        assert "http://example.com/x" in rendered
        assert "\x1b" not in rendered and "pwned" not in rendered
    a.close()
    b.close()


# ---------------------------------------------------------------------------
# Nothing transmits without a deliberate commit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enter_sends_and_the_send_button_sends():
    app, a, b, incoming = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        assert link is not None
        app._bind_link(link)
        await asyncio.sleep(0.1)
        far = incoming[0]

        field = app.query_one("#session-input", Input)
        field.focus()
        await pilot.pause()
        field.value = "u"
        await pilot.press("enter")
        await asyncio.sleep(0.4)
        assert b"u\r" in far.read_nowait(), "Enter did not transmit"

        app.query_one("#session-input", Input).value = "n"
        await app.query_one(TerminalPane)._send_pressed()
        await asyncio.sleep(0.4)
        assert b"n\r" in far.read_nowait(), "the Send button did not transmit"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_typing_alone_never_transmits():
    """Characters in the field are not on the air until committed."""
    app, a, b, incoming = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)

        before = len(ta_sent := app.station.transport.sent)
        app.query_one("#session-input", Input).focus()
        for key in ("b", "y", "e"):
            await pilot.press(key)
        await pilot.pause()
        await asyncio.sleep(0.2)
        assert app.query_one("#session-input", Input).value == "bye"
        assert len(ta_sent) == before, "typing put frames on the air"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_suggest_fills_the_input_without_sending():
    app, a, b, incoming = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        far = incoming[0]
        far.read_nowait()

        before = len(app.station.transport.sent)
        app.query_one(TerminalPane).suggest("NODES")
        await pilot.pause()
        await asyncio.sleep(0.2)
        assert app.query_one("#session-input", Input).value == "NODES"
        assert len(app.station.transport.sent) == before, "a suggestion transmitted"
        assert far.read_nowait() == b"", "a suggestion reached the far end"
    a.close()
    b.close()


def test_send_line_is_the_only_transmit_path_in_the_pane():
    """Read one method to answer 'what can key the transmitter?'.

    Asserted against the source because the failure guarded against is someone
    adding a second `link.send` call later, which would look ordinary in a diff.
    """
    source = inspect.getsource(tp)
    senders = [
        line.strip()
        for line in source.splitlines()
        if "link.send(" in line and not line.strip().startswith("#")
    ]
    assert len(senders) == 1, f"more than one transmit path in the pane: {senders}"


# ---------------------------------------------------------------------------
# Command reference
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_node_family_is_detected_passively_from_its_banner():
    """No question is asked of the node -- that would cost airtime."""
    app, a, b, incoming = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)

        before = len(app.station.transport.sent)
        app._on_link_data(b"Welcome to the node.\rW1AW-7:CCEMA}\r")
        await pilot.pause()
        assert app.reference.family is not None
        assert app.reference.family.id == "bpq32"
        assert len(app.station.transport.sent) == before, (
            "identifying the node transmitted something"
        )
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_reference_screen_opens_and_lists_commands():
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.reference = CommandReference(family=load_family("bpq32"))
        await pilot.press("f6")
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()
        assert isinstance(app.screen, CommandReferenceScreen)
        assert app.screen.query_one("#ref-table").row_count > 0
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_a_new_connection_forgets_the_previous_node():
    """Offering the last node's commands for a different one would mislead."""
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        app.reference = CommandReference(family=load_family("bpq32"))
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await pilot.pause()
        assert app.reference.family is None
    a.close()
    b.close()
