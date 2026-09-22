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
from textual.geometry import Region  # noqa: E402
from textual.widgets import Button, Input, RichLog, Static, Tabs  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.nodes import Command, CommandReference, load_family  # noqa: E402
from kissterm.ui import terminal_pane as tp  # noqa: E402
from kissterm.ui.dialogs import BbsHelperScreen, CommandReferenceScreen  # noqa: E402
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
    # Transmit is disabled on a fresh app (kissterm/tx.py); these tests are
    # about other behaviour and would otherwise all fail at the gate. The
    # closed-by-default guarantee itself is asserted in
    # tests/pilot/test_transmit_gate.py.
    config = Config(mycall=str(MYCALL))
    config.tx_armed_at_start = True
    app = KissTermApp(config, a)
    return app, a, b, incoming


def _feed(link, data: bytes) -> None:
    """Deliver `data` to every subscriber on `link`, exactly the way
    `AX25Link` does when a frame arrives.

    Calling `app._on_link_data` directly reaches only the app's own
    terminal/detection handler -- a hop-confirmation watch
    (`KissTermApp._await_hop_confirmation`) is a SEPARATE, temporary
    subscriber on the same fan-out, so a test that fed the app handler
    alone would silently never confirm a hop and would then "prove" the
    reset does not happen.
    """
    for callback in list(link.on_data):
        callback(data)


async def _hop_settled(app, session_key: str, timeout: float = 2.0) -> None:
    """Wait for a background hop-confirmation watch to finish.

    Polled with a bare `asyncio.sleep` rather than `pilot.pause()`: the
    watch is plain asyncio and does not need Textual's message pump to make
    progress, and AGENTS.md's testing section is explicit that a pause costs
    ~100ms of real time per call -- enough to dominate any timing budget it
    is polled inside.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.01)
        session = app._sessions.get(session_key)
        if session is None or session.hop_watch_task is None:
            return


def _plain(widget) -> str:
    """A widget's currently-rendered plain text -- reading `.renderable`
    directly is the internals-coupling `kissterm/ui/AGENTS.md` rule 21 warns
    against once it holds a Rich renderable rather than a bare string."""
    region = Region(0, 0, widget.size.width or 200, widget.size.height or 5)
    return "\n".join(strip.text for strip in widget.render_lines(region))


def _sent_data_frames(transport) -> list:
    """Outbound user data, excluding link-layer acknowledgements.

    The tests below are about text typed into the terminal.  An RR may be
    emitted later by the real AX.25 link's T2 timer while the UI is being
    exercised, and is neither a terminal send nor a payload the far end can
    mistake for operator input.
    """
    return [frame for frame in transport.sent if frame.kind == "I"]


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
        pane.write_incoming("", b"\x1b[2J\x1b]0;pwned\x07go to http://example.com/x\r\n")
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
async def test_the_send_button_leaves_focus_on_the_input():
    """From a real report: pressing Send with the mouse, then having to
    click back into the text field before typing the next line -- for
    every single line of a session. Clicking a Button moves focus to the
    button, Textual's ordinary behaviour for anything clicked; nothing
    here returned it to the input, so a mouse-only operator (or one whose
    terminal was swallowing Enter that same session -- see
    `test_enter_variants_a_terminal_might_misreport_also_send`) had to
    reach for the mouse twice per line instead of once."""
    app, a, b, incoming = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        assert link is not None
        app._bind_link(link)
        await asyncio.sleep(0.1)

        app.query_one("#session-input", Input).value = "n"
        await app.query_one(TerminalPane)._send_pressed()
        await pilot.pause()

        assert app.query_one("#session-input", Input).has_focus
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_enter_variants_a_terminal_might_misreport_also_send():
    """From a real report: typed text sent fine through the Send button,
    but plain Enter did nothing -- most likely a terminal under an
    enhanced keyboard protocol (this app already depends on one, for
    Ctrl+Shift+B/D) attaching a modifier to a bare Enter that a plain one
    would not carry, which changes the reported key name out from under
    Input's own "enter"-only binding. `_SendInput` adds a few plausible
    variants; this proves each one actually reaches `send_line`."""
    for key in ("shift+enter", "ctrl+enter", "alt+enter"):
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
            await pilot.press(key)
            await asyncio.sleep(0.4)
            assert b"u\r" in far.read_nowait(), f"{key} did not transmit"
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

        before = _sent_data_frames(app.station.transport)
        app.query_one("#session-input", Input).focus()
        for key in ("b", "y", "e"):
            await pilot.press(key)
        await pilot.pause()
        await asyncio.sleep(0.2)
        assert app.query_one("#session-input", Input).value == "bye"
        assert _sent_data_frames(app.station.transport) == before, "typing put frames on the air"
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

        before = _sent_data_frames(app.station.transport)
        app.query_one(TerminalPane).suggest("NODES")
        await pilot.pause()
        await asyncio.sleep(0.2)
        assert app.query_one("#session-input", Input).value == "NODES"
        assert _sent_data_frames(app.station.transport) == before, "a suggestion transmitted"
        assert far.read_nowait() == b"", "a suggestion reached the far end"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_bbs_helper_fills_a_parameterized_command_without_sending():
    """P5 helpers end at the compose box; Send remains a separate commit."""
    app, a, b, incoming = await _connected_app()
    chosen: list[str | None] = []
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        far = incoming[0]
        far.read_nowait()
        before = _sent_data_frames(app.station.transport)

        app.push_screen(BbsHelperScreen(), chosen.append)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, BbsHelperScreen)
        screen.query_one("#bbs-macro").value = "read"
        screen.query_one("#bbs-number", Input).value = "42"
        screen.query_one("#bbs-apply", Button).press()
        await pilot.pause()

        assert chosen == ["R 42"]
        assert _sent_data_frames(app.station.transport) == before
        assert far.read_nowait() == b""
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_bbs_helper_from_reference_reaches_compose_box_without_sending():
    """The nested picker keeps the reference's one fill-only return route."""
    app, a, b, incoming = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        far = incoming[0]
        far.read_nowait()
        before = _sent_data_frames(app.station.transport)

        await pilot.press("ctrl+r")
        await asyncio.sleep(0.1)
        reference = app.screen
        assert isinstance(reference, CommandReferenceScreen)
        reference.query_one("#ref-bbs", Button).press()
        await asyncio.sleep(0.1)
        helper = app.screen
        assert isinstance(helper, BbsHelperScreen)
        helper.query_one("#bbs-macro").value = "send"
        helper.query_one("#bbs-callsign", Input).value = "N1ABC-7"
        helper.query_one("#bbs-apply", Button).press()
        await asyncio.sleep(0.2)
        await pilot.pause()

        assert app.query_one("#session-input", Input).value == "SP N1ABC-7"
        assert _sent_data_frames(app.station.transport) == before
        assert far.read_nowait() == b""
    a.close()
    b.close()


# ---------------------------------------------------------------------------
# Inline suggestion strip -- docs/ROADMAP.md's "Inline completion on the
# send line". Tab fills in the input like `suggest()` above; it must never
# gain a second transmit path of its own.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_empty_or_unmatched_input_shows_no_strip():
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        app.reference = CommandReference(family=load_family("bpq32"))
        strip = app.query_one("#suggestion-strip", Static)
        assert strip.display is False, "nothing typed yet -- strip must start hidden"

        field = app.query_one("#session-input", Input)
        field.focus()
        await pilot.press("z", "z", "z", "z")
        await pilot.pause()
        assert strip.display is False, "no command starts with ZZZZ"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_typing_a_prefix_shows_matching_commands_without_transmitting():
    app, a, b, incoming = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        far = incoming[0]
        far.read_nowait()
        app.reference = CommandReference(family=load_family("bpq32"))

        before = _sent_data_frames(app.station.transport)
        field = app.query_one("#session-input", Input)
        field.focus()
        await pilot.press("c")
        await pilot.pause()

        strip = app.query_one("#suggestion-strip", Static)
        assert strip.display is True
        shown = " ".join(_plain(strip).split())
        # bpq32.toml ships C, CQ and CHAT -- complete() sorts shortest first.
        # The strip must say what the choices do, not just make a newcomer
        # infer their meaning from two-letter node jargon.
        assert "C: Connect onward to another station or node" in shown
        assert "CQ: Call CQ to other users connected to the node" in shown
        assert "CHAT: Enter the node's chat server, if it has one" in shown
        assert "Tab" in shown

        assert _sent_data_frames(app.station.transport) == before, "showing suggestions transmitted"
        assert far.read_nowait() == b"", "showing suggestions reached the far end"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_tab_accepts_the_top_suggestion_without_transmitting():
    app, a, b, incoming = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        far = incoming[0]
        far.read_nowait()
        app.reference = CommandReference(family=load_family("bpq32"))

        field = app.query_one("#session-input", Input)
        field.focus()
        await pilot.press("c")
        await pilot.pause()

        before = _sent_data_frames(app.station.transport)
        await pilot.press("tab")
        await pilot.pause()

        assert field.value == "C", "Tab must fill in the top match (shortest name first)"
        assert app.focused is field, "accepting a suggestion must leave the input focused"
        assert _sent_data_frames(app.station.transport) == before, "Tab acceptance transmitted"
        assert far.read_nowait() == b"", "Tab acceptance reached the far end"

        strip = app.query_one("#suggestion-strip", Static)
        assert strip.display is True, "the accepted text ('C') still matches itself"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_tab_cycles_all_matches_without_transmitting():
    app, a, b, incoming = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        far = incoming[0]
        far.read_nowait()
        app.reference = CommandReference(
            learned=tuple(Command(name=name, confidence="learned") for name in ("B", "BBS", "BYE"))
        )
        field = app.query_one("#session-input", Input)
        field.focus()
        await pilot.press("b")
        await pilot.pause()
        before = _sent_data_frames(app.station.transport)

        await pilot.press("tab")
        await pilot.press("tab")
        await pilot.press("tab")
        await pilot.press("tab")
        await pilot.pause()

        assert field.value == "B", "the fourth Tab must wrap to the first match"
        assert _sent_data_frames(app.station.transport) == before
        assert far.read_nowait() == b"", "completion cycling reached the far end"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_tab_moves_focus_normally_when_nothing_is_suggested():
    """The override must not trap Tab in an empty box -- see
    `_SendInput.action_accept_suggestion`'s fallback to `Screen.focus_next()`.
    """
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        field = app.query_one("#session-input", Input)
        field.focus()
        await pilot.pause()
        assert app.focused is field

        await pilot.press("tab")
        await pilot.pause()

        assert app.focused is not field, "Tab with no suggestion must still move focus"
        assert field.value == ""
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
        app._on_link_data(app._active_key(), b"Welcome to the node.\rW1AW-7:CCEMA}\r")
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
        await pilot.press("ctrl+r")
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()
        assert isinstance(app.screen, CommandReferenceScreen)
        assert app.screen.query_one("#ref-table").row_count > 0
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_glossary_toggle_shares_the_command_reference_pane():
    """docs/ROADMAP.md asks for a glossary "searchable in the same pane as
    commands" -- this is that pane, not a second modal or a second key."""
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.reference = CommandReference(family=load_family("bpq32"))
        await pilot.press("ctrl+r")
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, CommandReferenceScreen)
        assert isinstance(screen.query_one("#ref-mode-tabs"), Tabs)
        commands_rows = screen.query_one("#ref-table").row_count
        assert commands_rows > 0

        await pilot.click("#ref-mode-glossary")
        await pilot.pause()

        assert screen._mode == "glossary"
        table = screen.query_one("#ref-table")
        glossary_log = screen.query_one("#ref-glossary")
        # The glossary has its own term set, distinct from the node's commands,
        # and uses a wrapping Rich table rather than DataTable's one-line cells.
        from kissterm import glossary

        assert not table.display
        assert glossary_log.display
        assert glossary_log.lines
        rendered = "\n".join(str(line) for line in glossary_log.lines)
        assert "Terminal Node Controller." in rendered
        assert "hardware (or software, for a soundcard" in rendered

        # Selecting a glossary row must never dismiss the screen with a
        # value -- there is nothing for the terminal input to do with a
        # definition, unlike a command name.
        await pilot.click("#ref-mode-commands")
        await pilot.pause()
        assert screen._mode == "commands"
        assert screen.query_one("#ref-table").row_count == commands_rows
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_existing_scrollback_rewraps_when_the_addressbook_closes():
    """A width change must replay old lines, not only wrap future output."""
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        log = pane.query_one("#session-log", RichLog)
        assert app.query_one("#terminal-addressbook-column").display
        pane.clear("")
        pane.log("", "one long old line " * 20)
        await pilot.pause()
        narrow_lines = len(log.lines)

        await pilot.press("ctrl+g")
        await asyncio.sleep(0.1)
        await pilot.pause()

        assert not app.query_one("#terminal-addressbook-column").display
        assert len(log.lines) < narrow_lines
        assert "one long old line" in "\n".join(str(line) for line in log.lines)
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_reference_mode_switch_clears_the_other_views_search_filter():
    """A command filter must not make the unrelated glossary look empty."""
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.reference = CommandReference(family=load_family("bpq32"))
        await pilot.press("ctrl+r")
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, CommandReferenceScreen)
        search = screen.query_one("#ref-search", Input)
        search.value = "not-a-command"
        await pilot.pause()
        assert screen.query_one("#ref-table").row_count == 0

        await pilot.click("#ref-mode-glossary")
        await pilot.pause()

        assert search.value == ""
        assert screen.query_one("#ref-glossary", RichLog).lines
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_harvest_button_only_appears_with_a_connected_link():
    """Nothing to ask a node's `?` of when there is no live link -- the
    button must simply not be there, not be there-and-disabled."""
    app, a, b, incoming = await _connected_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, CommandReferenceScreen)
        assert len(screen.query("#ref-harvest")) == 0
        await screen.dismiss(None)
        await pilot.pause()

        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()

        screen2 = app.screen
        assert isinstance(screen2, CommandReferenceScreen)
        assert len(screen2.query("#ref-harvest")) == 1
        await screen2.dismiss(None)
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_cancelling_the_harvest_confirm_sends_nothing():
    from kissterm.ui.dialogs import HarvestConfirmScreen

    app, a, b, incoming = await _connected_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        far = incoming[0]
        far.read_nowait()  # drain the connect handshake

        await pilot.press("ctrl+r")
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, CommandReferenceScreen)

        screen.query_one("#ref-harvest").press()
        await pilot.pause()
        assert isinstance(app.screen, HarvestConfirmScreen)
        await app.screen.dismiss(False)
        await pilot.pause()
        await asyncio.sleep(0.2)

        assert far.read_nowait() == b"", "cancelling the harvest still transmitted"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_harvesting_learns_commands_and_caches_them_per_callsign():
    """The full opt-in-harvesting contract: confirm shows first, `?` goes
    out through the ordinary tx-gated send path, the node's reply is parsed
    into learned commands visible in the SAME table, and the result is
    cached under the peer's callsign so a reconnect gets it back for free."""
    from kissterm.ui import app as app_module
    from kissterm.ui.dialogs import HarvestConfirmScreen

    # `pilot.pause()` costs roughly 100ms of real wall time in this harness
    # (rendering a full frame each call) -- using it inside a tight polling
    # loop here silently ate most of the harvest window before `far.send`
    # even ran, which is what made this test flaky the first time it was
    # written. Polling with a bare `asyncio.sleep` is cheap and correct:
    # `harvest_commands` and the link's `on_data` callbacks are plain
    # asyncio, not gated on Textual's message pump, and `DataTable.row_count`
    # reflects `add_row` immediately, before the next render. `pilot.pause()`
    # is used only once, before anything is asserted about a widget.
    original_ceiling = app_module.HARVEST_MAX_WAIT_SECONDS
    original_quiet = app_module.HARVEST_QUIET_SECONDS
    original_poll = app_module.HARVEST_POLL_INTERVAL
    app_module.HARVEST_MAX_WAIT_SECONDS = 3.0
    app_module.HARVEST_QUIET_SECONDS = 0.2
    app_module.HARVEST_POLL_INTERVAL = 0.05
    app, a, b, incoming = await _connected_app()
    try:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            link = await a.connect(AX25Path(PEER, MYCALL))
            app._bind_link(link)
            await asyncio.sleep(0.1)
            far = incoming[0]
            far.read_nowait()  # drain the connect handshake

            await pilot.press("ctrl+r")
            await pilot.pause()
            await asyncio.sleep(0.2)
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, CommandReferenceScreen)

            screen.query_one("#ref-harvest").press()
            await pilot.pause()
            assert isinstance(app.screen, HarvestConfirmScreen)
            await app.screen.dismiss(True)

            for _ in range(40):
                await asyncio.sleep(0.02)
                harvest = screen.query_one("#ref-harvest", Button)
                if harvest.disabled:
                    break
            assert harvest.disabled
            assert str(harvest.label) == "Asking node..."

            sent = b""
            for _ in range(40):
                await asyncio.sleep(0.02)
                sent += far.read_nowait()
                if b"?\r" in sent:
                    break
            assert b"?\r" in sent, "confirming did not send '?'"

            await far.send(b"Valid commands are: CALENDAR FORMS WALL\r")

            table = screen.query_one("#ref-table")
            for _ in range(150):
                await asyncio.sleep(0.02)
                if table.row_count > 0:
                    break
            await pilot.pause()

            rows = {str(table.get_row_at(i)[0]) for i in range(table.row_count)}
            assert "CALENDAR" in rows, f"harvest never completed, rows={rows}"

            cached = app._harvested.for_callsign(str(PEER))
            assert "CALENDAR" in cached and "FORMS" in cached and "WALL" in cached
            status = screen.query_one("#ref-harvest-status", Static)
            assert status.display
            assert "Captured" in str(status.render())
            show = screen.query_one("#ref-show-harvest", Button)
            assert show.display
            show.press()
            output = screen.query_one("#ref-harvest-output", RichLog)
            for _ in range(50):
                await asyncio.sleep(0.02)
                if output.lines:
                    break
            await pilot.pause()
            assert output.display
            assert "CALENDAR FORMS WALL" in "\n".join(str(line) for line in output.lines)
            await screen.dismiss(None)
    finally:
        app_module.HARVEST_MAX_WAIT_SECONDS = original_ceiling
        app_module.HARVEST_QUIET_SECONDS = original_quiet
        app_module.HARVEST_POLL_INTERVAL = original_poll
        a.close()
        b.close()


@pytest.mark.asyncio
async def test_a_delayed_reply_is_still_captured_within_the_ceiling():
    """The exact bug from the real WS1EC-15/CCEMA report: a reply that takes
    real time to arrive (T1 retry/REJ recovery on a lossy link) must still
    be captured as long as it lands before the hard ceiling -- a fixed
    5-second window (the original, buggy implementation) would have missed
    this one."""
    from kissterm.ui import app as app_module

    original_ceiling = app_module.HARVEST_MAX_WAIT_SECONDS
    original_quiet = app_module.HARVEST_QUIET_SECONDS
    original_poll = app_module.HARVEST_POLL_INTERVAL
    app_module.HARVEST_MAX_WAIT_SECONDS = 1.5
    app_module.HARVEST_QUIET_SECONDS = 0.1
    app_module.HARVEST_POLL_INTERVAL = 0.02
    app, a, b, incoming = await _connected_app()
    try:
        async with app.run_test(size=(120, 40)):
            link = await a.connect(AX25Path(PEER, MYCALL))
            app._bind_link(link)
            await asyncio.sleep(0.1)
            far = incoming[0]
            far.read_nowait()

            async def _delayed_reply():
                # Deliberately late relative to the 1.5s patched ceiling --
                # arrives with under a second of margin, well past where a
                # short fixed window (like the original 5.0s default scaled
                # down proportionally) would already have given up.
                await asyncio.sleep(0.6)
                await far.send(b"Valid commands are: CALENDAR FORMS WALL\r")

            task = asyncio.create_task(_delayed_reply())
            names = await app.harvest_commands(app._active_key())
            await task

            assert set(names) == {"CALENDAR", "FORMS", "WALL"}, names
    finally:
        app_module.HARVEST_MAX_WAIT_SECONDS = original_ceiling
        app_module.HARVEST_QUIET_SECONDS = original_quiet
        app_module.HARVEST_POLL_INTERVAL = original_poll
        a.close()
        b.close()


@pytest.mark.asyncio
async def test_a_fast_reply_does_not_wait_out_the_full_ceiling():
    """The quiet-exit exists so a two-line answer doesn't force the operator
    to sit through the full worst-case ceiling."""
    from kissterm.ui import app as app_module

    original_ceiling = app_module.HARVEST_MAX_WAIT_SECONDS
    original_quiet = app_module.HARVEST_QUIET_SECONDS
    original_poll = app_module.HARVEST_POLL_INTERVAL
    app_module.HARVEST_MAX_WAIT_SECONDS = 10.0
    app_module.HARVEST_QUIET_SECONDS = 0.2
    app_module.HARVEST_POLL_INTERVAL = 0.02
    app, a, b, incoming = await _connected_app()
    try:
        async with app.run_test(size=(120, 40)):
            link = await a.connect(AX25Path(PEER, MYCALL))
            app._bind_link(link)
            await asyncio.sleep(0.1)
            far = incoming[0]
            far.read_nowait()

            async def _fast_reply():
                await asyncio.sleep(0.05)
                await far.send(b"Valid commands are: CALENDAR\r")

            task = asyncio.create_task(_fast_reply())
            start = asyncio.get_event_loop().time()
            names = await app.harvest_commands(app._active_key())
            elapsed = asyncio.get_event_loop().time() - start
            await task

            assert "CALENDAR" in names
            assert elapsed < 2.0, (
                f"took {elapsed:.2f}s -- quiet-exit did not shortcut the "
                f"10s ceiling for a reply that arrived almost immediately"
            )
    finally:
        app_module.HARVEST_MAX_WAIT_SECONDS = original_ceiling
        app_module.HARVEST_QUIET_SECONDS = original_quiet
        app_module.HARVEST_POLL_INTERVAL = original_poll
        a.close()
        b.close()


@pytest.mark.asyncio
async def test_a_reconnect_applies_the_cache_with_no_new_airtime():
    """AGENTS.md: cached forever so it is never paid twice -- a second
    connect to the same callsign must show the learned commands immediately,
    with no harvest button interaction and no '?' sent."""
    from kissterm.harvested import HarvestedCommands

    app, a, b, incoming = await _connected_app()
    async with app.run_test(size=(120, 40)) as pilot:
        app._harvested = HarvestedCommands(app._harvested.file)
        app._harvested.add(str(PEER), ("CALENDAR", "FORMS"))

        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        far = incoming[0]
        far.read_nowait()

        await pilot.press("ctrl+r")
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, CommandReferenceScreen)

        table = screen.query_one("#ref-table")
        rows = {str(table.get_row_at(i)[0]) for i in range(table.row_count)}
        assert "CALENDAR" in rows and "FORMS" in rows
        assert far.read_nowait() == b"", "applying the cache transmitted something"
        await screen.dismiss(None)
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_command_picker_labels_harvested_bbs_commands():
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.reference = CommandReference(
            learned=(Command(name="LIST", confidence="learned", context="bbs"),)
        )
        await pilot.press("ctrl+r")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, CommandReferenceScreen)
        table = screen.query_one("#ref-table")
        row = table.get_row_at(0)
        assert row[0] == "LIST"
        assert row[3] == "BBS"
        assert row[4] == "learned"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_harvest_is_refused_while_the_transmit_gate_is_closed():
    app, a, b, incoming = await _connected_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        far = incoming[0]
        far.read_nowait()
        app.gate.set(False)

        names = await app.harvest_commands(app._active_key())
        await asyncio.sleep(0.1)

        assert names == ()
        assert far.read_nowait() == b"", "harvesting transmitted with the gate closed"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_timer_recovery_flapping_does_not_clutter_the_terminal():
    """From a real report: WS1EC-15/CCEMA's link flapped timer-recovery and
    connected three times waiting out T1/REJ recovery for one reply, and
    every flap wrote its own line into the scrollback among the node's
    actual text. The status bar already shows link state live -- this
    should not be said twice."""
    from kissterm.transport.base import SessionState

    app, a, b, incoming = await _connected_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        await pilot.pause()

        key = app._active_key()
        app._on_link_state(key, SessionState.TIMER_RECOVERY)
        await pilot.pause()
        app._on_link_state(key, SessionState.CONNECTED)
        await pilot.pause()
        app._on_link_state(key, SessionState.TIMER_RECOVERY)
        await pilot.pause()
        app._on_link_state(key, SessionState.CONNECTED)
        await pilot.pause()

        text = _plain(app.query_one("#session-log"))
        assert "timer-recovery" not in text, text
        # The bug this test originally missed: suppressing the flap notes
        # is not the same as suppressing the repeated *resolution* back to
        # CONNECTED after each one. Two flap cycles must not print "***
        # connected" twice.
        assert text.count("*** connected") == 0, text
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_a_genuine_disconnect_still_shows_inline():
    """The suppression is specific to timer-recovery churn, not a blanket
    silencing of every state note -- disconnecting must still be visible
    inline, since nothing else announces it."""
    from kissterm.transport.base import SessionState

    app, a, b, incoming = await _connected_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        await pilot.pause()

        key = app._active_key()
        app._on_link_state(key, SessionState.DISCONNECTING)
        await pilot.pause()

        text = _plain(app.query_one("#session-log"))
        assert "disconnecting" in text
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


@pytest.mark.asyncio
async def test_hopping_onward_forgets_the_node_it_hopped_through():
    """From a real report: connect to a BPQ32 node, harvest it, then type
    "C <other-node>" to hop onward -- the AX.25 link never changes (the hop
    is the far node's own application layer relaying text, invisible to
    kissterm's link state), so nothing else ever tells this session it
    might now be talking to a different family. A CONFIRMED hop must reset
    detection so the NEXT banner gets a clean read instead of the old
    family sticking around forever.

    The reset is deliberately NOT immediate -- see the failed-hop and
    timed-out-hop tests below, which are the other half of this contract."""
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        key = app._active_key()
        _feed(link, b"Welcome.\rW1AW-7:CCEMA}\r")
        await pilot.pause()
        assert app.reference.family is not None and app.reference.family.id == "bpq32"

        app.log_sent(key, "C JNOSNODE")
        # The node confirms the hop; only THEN does detection re-arm.
        _feed(link, b"*** CONNECTED to JNOSNODE\r")
        await _hop_settled(app, key)
        assert app.reference.family is None, "a confirmed hop kept the old family"
        assert app.current_node == "JNOSNODE"

        _feed(link, b"Welcome to JNOS\r")
        await pilot.pause()
        assert app.reference.family is not None and app.reference.family.id == "jnos"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_hopping_onward_also_clears_stale_autocomplete_suggestions():
    """`_update_suggestions` reads `app.reference` fresh on every keystroke
    (never a cached copy), so the hop-reset above should already fix this
    for free -- this pins that down rather than trusting it stays true."""
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        key = app._active_key()
        _feed(link, b"Welcome.\rW1AW-7:CCEMA}\r")
        await pilot.pause()

        field = app.query_one("#session-input", Input)
        field.focus()
        await pilot.press("c")
        await pilot.pause()
        strip = app.query_one("#suggestion-strip", Static)
        assert strip.display is True, "bpq32's C/CQ/CHAT should suggest before the hop"

        field.value = ""
        app.log_sent(key, "C JNOSNODE")
        _feed(link, b"*** CONNECTED to JNOSNODE\r")
        await _hop_settled(app, key)
        await pilot.press("c")
        await pilot.pause()
        assert strip.display is False, "old node's commands still suggested after hopping"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_a_command_that_merely_starts_with_c_does_not_reset_detection():
    """"CQ" (call CQ) and "CHAT" are real bpq32.toml commands -- the
    hop-reset must match the whole first word, not a prefix, or ordinary
    node commands would spuriously wipe out a correct identification."""
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        key = app._active_key()
        _feed(link, b"Welcome.\rW1AW-7:CCEMA}\r")
        await pilot.pause()
        assert app.reference.family is not None

        app.log_sent(key, "CQ any takers?")
        assert app.reference.family is not None, "CQ was mistaken for a hop"
        app.log_sent(key, "CHAT")
        assert app.reference.family is not None, "CHAT was mistaken for a hop"
        # A bare "C" names no node to hop to, so there is nothing to confirm.
        app.log_sent(key, "C")
        assert app._sessions[key].hop_watch_task is None, (
            "a bare C with no target started a hop watch"
        )
        # Nothing above should have started a watch that a later, unrelated
        # CONNECTED could still commit.
        _feed(link, b"*** CONNECTED to SOMEWHERE\r")
        await _hop_settled(app, key)
        assert app.reference.family is not None, "an ordinary command reset detection"
        assert app.current_node == str(PEER)
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_a_port_qualified_hop_targets_the_callsign_not_the_port():
    """bpq32.toml documents two forms: "C <call>" and "C <port> <call>".
    The target is the LAST word either way -- taking the first word after
    "C" would read "C 2 JNOSNODE" as a hop to a node literally named "2",
    which then confirms against the wrong node's traffic and would cache a
    real harvest under a callsign that was never actually reached."""
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        key = app._active_key()

        app.log_sent(key, "C 2 JNOSNODE")
        _feed(link, b"*** CONNECTED to JNOSNODE\r")
        await _hop_settled(app, key)

        assert app.current_node == "JNOSNODE", "the port number was taken as the target"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_a_hop_that_is_refused_leaves_the_node_we_are_still_on_alone():
    """The regression the confirmation step exists to fix, found in live
    testing against a real BPQ32 node: the first version of the hop reset
    fired the instant the command went out. A hop that answers BUSY leaves
    the operator on the SAME node they were already correctly identified
    against -- wiping detection there turns a working command reference and
    working autocomplete into "unknown node" for a node that never went
    anywhere."""
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        key = app._active_key()
        _feed(link, b"Welcome.\rW1AW-7:CCEMA}\r")
        await pilot.pause()
        before = app.reference.family
        assert before is not None and before.id == "bpq32"

        field = app.query_one("#session-input", Input)
        field.focus()
        await pilot.press("c")
        await pilot.pause()
        strip = app.query_one("#suggestion-strip", Static)
        assert strip.display is True
        field.value = ""

        app.log_sent(key, "C SOMEWHERE")
        _feed(link, b"*** BUSY from SOMEWHERE\r")
        await _hop_settled(app, key)

        assert app.reference.family is before, "a refused hop wiped the node we are on"
        assert app.current_node == str(PEER), "a refused hop moved the logical peer"
        await pilot.press("c")
        await pilot.pause()
        assert strip.display is True, "a refused hop lost the autocomplete we still want"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_a_hop_that_times_out_leaves_the_node_we_are_still_on_alone():
    """Silence is the other way a hop fails, and it must be just as
    harmless as a refusal. `HOP_TIMEOUT` is patched down rather than waited
    out -- 20 seconds of real time in a unit test is not a test, it is a
    pause."""
    from kissterm.ui import app as app_module

    original_timeout = app_module.HOP_TIMEOUT
    app_module.HOP_TIMEOUT = 0.3
    app, a, b, _ = await _connected_app()
    try:
        async with app.run_test(size=(110, 32)) as pilot:
            await pilot.pause()
            link = await a.connect(AX25Path(PEER, MYCALL))
            app._bind_link(link)
            await asyncio.sleep(0.1)
            key = app._active_key()
            _feed(link, b"Welcome.\rW1AW-7:CCEMA}\r")
            await pilot.pause()
            before = app.reference.family
            assert before is not None

            app.log_sent(key, "C NOWHERE")
            # Nothing comes back at all -- the node never answers.
            await _hop_settled(app, key)

            assert app.reference.family is before, "a silent hop wiped detection"
            assert app.current_node == str(PEER)
    finally:
        app_module.HOP_TIMEOUT = original_timeout
        a.close()
        b.close()


@pytest.mark.asyncio
async def test_a_second_hop_replaces_the_first_ones_watch():
    """Two hop commands in flight at once would be two watchers on the same
    `link.on_data` bytes -- the first one's target committing on the second
    one's CONNECTED reply, which is exactly the mislabelling the logical
    peer exists to prevent."""
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        key = app._active_key()

        app.log_sent(key, "C FIRST")
        first_watch = app._sessions[key].hop_watch_task
        app.log_sent(key, "C SECOND")
        assert app._sessions[key].hop_watch_task is not first_watch

        _feed(link, b"*** CONNECTED to SECOND\r")
        await _hop_settled(app, key)

        assert first_watch.cancelled(), "the first hop's watcher was left running"
        assert app.current_node == "SECOND", "the wrong hop was committed"
        assert app._sessions[key].hop_watch_task is None
        # The cancelled watcher must also be off the fan-out, or it would go
        # on matching unrelated traffic for the rest of the session.
        assert len(link.on_data) == 1, f"stale watchers left subscribed: {link.on_data}"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_harvesting_after_a_hop_caches_under_the_node_that_answered():
    """The bug this pairs with: `harvest_commands` used to key its cache on
    `link.peer`, which stays the FIRST node's callsign for the life of a hop
    chain -- so harvesting a node reached by hopping wrote its commands into
    a different node's entry, corrupting a real reference with another
    node's syntax."""
    from kissterm.harvested import HarvestedCommands
    from kissterm.ui import app as app_module

    original_ceiling = app_module.HARVEST_MAX_WAIT_SECONDS
    original_quiet = app_module.HARVEST_QUIET_SECONDS
    original_poll = app_module.HARVEST_POLL_INTERVAL
    app_module.HARVEST_MAX_WAIT_SECONDS = 2.0
    app_module.HARVEST_QUIET_SECONDS = 0.1
    app_module.HARVEST_POLL_INTERVAL = 0.02
    app, a, b, _ = await _connected_app()
    try:
        async with app.run_test(size=(110, 32)) as pilot:
            app._harvested = HarvestedCommands(app._harvested.file)
            await pilot.pause()
            link = await a.connect(AX25Path(PEER, MYCALL))
            app._bind_link(link)
            await asyncio.sleep(0.1)
            key = app._active_key()

            app.log_sent(key, "C W1LH-6")
            _feed(link, b"*** CONNECTED to W1LH-6\r")
            await _hop_settled(app, key)
            assert app.current_node == "W1LH-6"

            async def _reply():
                await asyncio.sleep(0.05)
                _feed(link, b"Valid commands are: CALENDAR FORMS WALL\r")

            task = asyncio.create_task(_reply())
            names = await app.harvest_commands(key)
            await task

            assert set(names) == {"CALENDAR", "FORMS", "WALL"}, names
            assert "CALENDAR" in app._harvested.for_callsign("W1LH-6")
            assert app._harvested.for_callsign(str(PEER)) == (), (
                "harvest was filed under the AX.25 peer we merely hopped through"
            )
    finally:
        app_module.HARVEST_MAX_WAIT_SECONDS = original_ceiling
        app_module.HARVEST_QUIET_SECONDS = original_quiet
        app_module.HARVEST_POLL_INTERVAL = original_poll
        a.close()
        b.close()


@pytest.mark.asyncio
async def test_hopping_to_an_already_harvested_node_reapplies_its_cache():
    """The other half of "cached forever so it is never paid twice"
    (`test_a_reconnect_applies_the_cache_with_no_new_airtime` covers the
    connect path): arriving at a known node by hopping is the same arrival,
    and must not re-spend the airtime either."""
    from kissterm.harvested import HarvestedCommands

    app, a, b, incoming = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        app._harvested = HarvestedCommands(app._harvested.file)
        app._harvested.add("W1LH-6", ("CALENDAR", "FORMS"))

        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        far = incoming[0]
        far.read_nowait()
        key = app._active_key()
        assert app.reference.learned == ()

        app.log_sent(key, "C W1LH-6")
        _feed(link, b"*** CONNECTED to W1LH-6\r")
        await _hop_settled(app, key)

        learned = {c.name for c in app.reference.learned}
        assert learned == {"CALENDAR", "FORMS"}, learned
        assert far.read_nowait() == b"", "applying the cache after a hop transmitted"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_writing_to_a_torn_down_terminal_pane_does_not_raise():
    """A link outlives the UI, and its callbacks must survive teardown.

    `KissTermApp._to_terminal` tolerates the pane being gone; this covers the
    window one level in, where the pane is still mounted but its children
    have already been removed. A callback landing there used to raise
    `NoMatches` out of a worker with nowhere for the exception to go, which
    showed up as an intermittent failure in an unrelated pilot test rather
    than as anything pointing at the real cause.
    """
    app, _a, _b, _incoming = await _connected_app()
    async with app.run_test(size=(100, 30)):
        pane = app.query_one(TerminalPane)
        # Exactly what shutdown does: the pane stays, its children go.
        await pane.query("#session-log").remove()

        # Both callback-reachable write paths, neither of which may raise.
        pane.log("", "*** Disconnected")
        pane.write_incoming("", b"hello from the far end\r\n")
        pane._flush_incoming("", final=True)
