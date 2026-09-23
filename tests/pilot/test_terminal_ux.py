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
from kissterm.addressbook import Entry  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.nodes import Command, CommandReference, load_family  # noqa: E402
from kissterm.ui import terminal_pane as tp  # noqa: E402
from kissterm.ui.dialogs import BbsHelperScreen, CommandReferenceScreen  # noqa: E402
from kissterm.ui.terminal_pane import TerminalPane, linkify  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402
from tests.pilot._wait import wait_for  # noqa: E402

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
    against once it holds a Rich renderable rather than a bare string.

    Render at `outer_size`, NOT `size`. `Widget.size` is the CONTENT box,
    while `render_lines` paints the padded/bordered box -- so on any widget
    with horizontal padding this helper silently cropped the right-hand
    edge and reported a real character as missing. `#suggestion-strip` has
    `padding: 0 1`, and that is exactly how this read a correctly wrapped
    command summary back as truncated mid-word ("... or nod").
    """
    size = widget.outer_size
    region = Region(0, 0, size.width or 200, size.height or 5)
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
    `test_plain_enter_sends`) had to
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
async def test_plain_enter_sends():
    """Enter is the primary commit path and must work on its own.

    This replaces a test that drove `shift+enter`/`ctrl+enter`/`alt+enter`
    and asserted each transmitted. Those bindings were added against a real
    report -- typed text sent fine through the Send button while plain Enter
    did nothing -- on the theory that an enhanced keyboard protocol was
    attaching a modifier and changing the key name out from under `Input`'s
    binding. The theory was wrong and the report came back. Measured with
    `scripts/keycheck.py` on the affected station, Enter produced NO key
    event at all, so no binding under any name could have helped; Textual's
    enhanced protocol was turning it into a bare `CSI 13 u` sequence that
    terminal was losing. The protocol is off now (see
    `tests/unit/test_keyboard_protocol.py`) and this asserts the contract
    that actually matters rather than the workaround.
    """
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
        assert b"u\r" in far.read_nowait(), "plain Enter did not transmit"
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
        await wait_for(
            lambda: isinstance(app.screen, CommandReferenceScreen)
            and app.screen.query_one("#ref-bbs", Button),
            "the command reference to open",
        )
        app.screen.query_one("#ref-bbs", Button).press()
        await wait_for(
            lambda: isinstance(app.screen, BbsHelperScreen)
            and app.screen.query_one("#bbs-apply", Button),
            "the BBS helper to open",
        )
        # Let the helper's own Select post its initial Changed first; a value
        # set before that is reset by it (the fixed sleep here used to hide
        # this ordering).
        await pilot.pause()
        helper = app.screen
        helper.query_one("#bbs-macro").value = "send"
        helper.query_one("#bbs-callsign", Input).value = "N1ABC-7"
        helper.query_one("#bbs-apply", Button).press()
        await wait_for(
            lambda: app.query_one("#session-input", Input).value == "SP N1ABC-7",
            "the helper's command to reach the compose box",
        )
        await asyncio.sleep(0.2)  # give a wrongly-wired send time to show up

        assert app.query_one("#session-input", Input).value == "SP N1ABC-7"
        assert _sent_data_frames(app.station.transport) == before
        assert far.read_nowait() == b""
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_bbs_list_suggestions_are_stacked_with_their_meanings():
    """A narrow terminal must not push the explanation off the right edge."""
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(55, 32)) as pilot:
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        app.reference = CommandReference(family=load_family("bpqmail"))
        pane._update_suggestions("L")
        await pilot.pause()
        strip = app.query_one("#suggestion-strip", Static)
        rendered = _plain(strip)
        assert "LM - List messages to you" in rendered
        assert "LB - List bulletins" in rendered
        assert rendered.index("LM - List messages to you") < rendered.index("LB - List bulletins")
        assert any(
            command.name == "LL" and command.summary == "List the last n messages"
            for command in pane._suggestion_matches
        ), "the shipped reference must not depend on a node having learned it"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_up_down_choose_a_stacked_suggestion_and_tab_fills_it():
    """Arrow navigation selects only; Tab remains the deliberate fill step."""
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(55, 32)) as pilot:
        await pilot.pause()
        app.reference = CommandReference(family=load_family("bpqmail"))
        field = app.query_one("#session-input", Input)
        field.focus()
        field.value = "L"
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        assert pane._suggestion_index == 0

        await pilot.press("down", "down")
        assert pane._suggestion_index == 2
        assert field.value == "L", "navigation must not fill or send"

        # Read the expected command off the candidate list rather than
        # naming one. Which BBS command sits third under "L" is shipped
        # data (`kissterm/nodes/data/bpqmail.toml`), and it has already moved once --
        # documenting the full L* set turned the third entry from LB into
        # LM and failed this test for a reason that had nothing to do with
        # navigation. What must hold is that Tab fills the entry the arrows
        # selected, whatever it happens to be.
        chosen = pane._suggestion_matches[2].name
        assert chosen != "L", "the arrows must have moved off the first entry"
        await pilot.press("tab")
        assert field.value == chosen
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_bbs_helpers_explain_empty_learned_command_suggestions():
    """Harvesting tells us a name, while the shipped reference provides its
    meaning -- and the name appears once, not once per source."""
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(55, 32)) as pilot:
        await pilot.pause()
        app.reference = CommandReference(
            family=load_family("bpqmail"),
            learned=(Command("LM", context="bbs"), Command("LL", context="bbs")),
        )
        field = app.query_one("#session-input", Input)
        field.value = "L"
        await pilot.pause()
        rendered = _plain(app.query_one("#suggestion-strip", Static))
        assert "LM - List messages to you" in rendered
        field.value = "LL"
        await pilot.pause()
        rendered = _plain(app.query_one("#suggestion-strip", Static))
        assert "LL - List the last n messages" in rendered
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_starting_a_connection_hides_the_addressbook_and_netrom_slideout():
    """Live connection status needs the Terminal column, not side context."""
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(120, 32)) as pilot:
        await pilot.pause()
        column = app.query_one("#terminal-addressbook-column")
        assert column.display
        assert app.query_one("#known-nodes-table").display

        app.action_connect(prefill=Entry(str(PEER)))
        await asyncio.sleep(0.1)
        await pilot.pause()

        assert not column.display
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_crlf_split_across_frames_does_not_render_a_blank_line():
    """A live BPQ mail list exposed this exact AX.25 frame boundary.

    This used to assert the opposite of the first check below -- that a
    trailing CR was HELD back until its possible LF partner arrived. That is
    how the blank line was avoided originally, and it was the wrong trade: a
    node's prompt is the last thing it sends and it is CR-terminated, so
    holding the CR made the most important line on the screen wait for an
    idle timer, and when that timer did not fire (see
    `test_an_unterminated_tail_is_flushed_off_the_event_loop`) the operator
    was left looking at a session that appeared to have gone quiet. The line
    goes out immediately now and the orphaned LF is dropped instead, which
    keeps this test's real guarantee -- no blank line -- without that cost.
    """
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(80, 32)) as pilot:
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        pane.clear("")
        pane.write_incoming("", b"first line\r")
        assert [rendered.plain for rendered, _expand in pane._buffers[""]] == [
            "first line"
        ], "a CR-terminated line is complete and must not wait for a possible LF"

        pane.write_incoming("", b"\nsecond line\r\n")
        assert [rendered.plain for rendered, _expand in pane._buffers[""]] == [
            "first line", "second line"
        ]
        assert pane._pending_incoming[""] == b""
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_bare_cr_stream_still_flushes_without_waiting_for_lf():
    """TNC-style CR-only output remains a supported line ending."""
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(80, 32)) as pilot:
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        pane.clear("")
        pane.write_incoming("", b"first\rsecond\rthird")
        assert [rendered.plain for rendered, _expand in pane._buffers[""]] == [
            "first", "second"
        ]
        assert pane._pending_incoming[""] == b"third"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_bbs_lines_are_written_once_without_losing_real_blank_lines():
    """RichLog owns record breaks; received CRLF terminators must not too."""
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(80, 32)) as pilot:
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        pane.clear("")
        pane.write_incoming("", b"first\r\nsecond\r\n\r\nthird\r\n")
        assert [rendered.plain for rendered, _expand in pane._buffers[""]] == [
            "first", "second", "", "third"
        ]
        await pilot.pause()
        log = app.query_one("#session-log", RichLog)
        rendered = "\n".join(strip.text.rstrip() for strip in log.lines)
        assert "first\nsecond\n\nthird" in rendered
        assert "first\n\nsecond" not in rendered
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_a_final_pager_prompt_is_followed_into_view():
    """A node that is waiting for Enter must never look like it went silent."""
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        pane.clear("")
        pane.write_incoming(
            "", b"".join(f"listing line {number}\r\n".encode() for number in range(60))
        )
        # Packet pagers generally leave this final prompt unterminated. It
        # reaches the log on the idle flush, with no later node output to
        # trigger a deferred RichLog auto-scroll.
        pane.write_incoming("", b"<A>bort, <CR> Continue...")
        await pilot.pause(0.3)
        log = app.query_one("#session-log", RichLog)
        assert pane._pending_incoming[""] == b""
        assert log.lines[-1].text.rstrip() == "<A>bort, <CR> Continue..."
        assert log.scroll_y == log.max_scroll_y
        assert "<A>bort, <CR> Continue..." in log.render_line(log.size.height - 1).text
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
        # infer their meaning from two-letter node jargon. One candidate per
        # line, `NAME - summary`, is the shipped format (see
        # `_update_suggestions`); the whole summary has to survive the wrap,
        # which is the half of this a rendering bug would break.
        assert "C - Connect onward to a node, alias or station" in shown
        assert "CQ - Send a CQ beacon while in LISTEN mode on one port" in shown
        assert "CHAT - Enter the node's chat server, if it has one" in shown
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


@pytest.mark.asyncio
async def test_the_pane_leaves_textuals_own_log_alone():
    """Textual calls `self.log.warning(...)` on a widget from its own timer and
    callback dispatch. The pane used to define `log(session_key, text)` over
    that property, so those calls raised `AttributeError` inside Textual's
    machinery instead of logging. Local notes are `write_note`."""
    app, station, peer, _ = await _connected_app()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        pane.log.warning("pane logger reachable")  # must not raise
        pane.write_note(pane.active_session_key, "*** a local note\n")
        await pilot.pause()
        assert any("a local note" in line for line in _log_lines(app))
    station.close()
    peer.close()


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
        app._on_link_data(app._active_key(), b"Welcome to the node.\rCCEMA:WS1EC-15}\r")
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
        pane.write_note("", "one long old line " * 20)
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
            # Bounded by the mechanism, not by how busy the machine is: the
            # loop counts its wait in polls and `asyncio.sleep` never returns
            # early, so running to the ceiling cannot take less than the
            # ceiling in real time. Anything well under it was the quiet
            # exit. A fixed 2 s budget here failed under parallel load (3.14s).
            assert elapsed < 0.8 * app_module.HARVEST_MAX_WAIT_SECONDS, (
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
        assert row[2] == "offered by this node, not in the published reference"
        assert row[3] == "BBS"
        assert row[4] == "harvested only"
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
        _feed(link, b"Welcome.\rCCEMA:WS1EC-15}\r")
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
        _feed(link, b"Welcome.\rCCEMA:WS1EC-15}\r")
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
        _feed(link, b"Welcome.\rCCEMA:WS1EC-15}\r")
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
        _feed(link, b"Welcome.\rCCEMA:WS1EC-15}\r")
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
            _feed(link, b"Welcome.\rCCEMA:WS1EC-15}\r")
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
        pane.write_note("", "*** Disconnected")
        pane.write_incoming("", b"hello from the far end\r\n")
        pane._flush_incoming("", final=True)


async def _page_of_output(pane, pilot, lines: int = 40) -> str:
    """Fill the active session with `lines` of node output ending in a prompt
    that has NO trailing newline -- the shape the bug was reported against."""
    key = pane.active_session_key
    for n in range(lines):
        pane.write_incoming(key, f"line {n:02d} of node output\r".encode())
    pane.write_incoming(key, b"N1ABC-1:WS1EC-7} ")
    await pilot.pause()
    await asyncio.sleep(0.3)
    await pilot.pause()
    return key


def _at_bottom(log) -> bool:
    """Is the last written line actually inside the visible region?

    `scroll_offset.y` against `max_scroll_y` is the question the operator is
    really asking: anything between them is written, rendered, and below the
    fold. Reading the widget's own `auto_scroll` instead would answer a
    different question and answer it wrongly -- it stays True throughout the
    bug this guards.
    """
    return log.scroll_offset.y >= log.max_scroll_y


@pytest.mark.asyncio
async def test_the_last_line_stays_visible_when_the_suggestion_strip_appears():
    """The reported bug, reproduced at its cause: a log that was at the bottom
    must still be at the bottom after something takes rows away from it.

    Four previous fixes went into `TerminalPane._append`, i.e. into what
    happens when a line is *written*. That half was already working. What was
    missing is that `RichLog.auto_scroll` acts only on `write`, so the stacked
    suggestion strip -- seven rows tall for a prefix with several matches --
    pushed the tail of the scrollback under the fold with no new write left to
    bring it back. Measured at 80x24 before the fix: `scroll_y` stayed at 27
    while `max_scroll_y` became 34, hiding the last seven lines including the
    prompt. That is exactly the report: it looks like the node has gone quiet
    when it is in fact waiting on you.
    """
    app, a, _b, incoming = await _connected_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        incoming[0].read_nowait()
        app.reference = CommandReference(family=load_family("bpq32"))

        pane = app.query_one(TerminalPane)
        await _page_of_output(pane, pilot)
        log = app.query_one("#session-log", RichLog)
        assert _at_bottom(log), "the output itself must land at the bottom"

        field = app.query_one("#session-input", Input)
        field.focus()
        await pilot.press("c")
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()

        strip = app.query_one("#suggestion-strip", Static)
        assert strip.display is True, "this test is meaningless without the strip"
        assert strip.outer_size.height > 1, "a one-row strip would not hide anything"
        assert _at_bottom(log), (
            "the prompt fell below the fold when the suggestion strip "
            f"appeared: scroll_y={log.scroll_offset.y} "
            f"max_scroll_y={log.max_scroll_y}"
        )


@pytest.mark.asyncio
async def test_the_last_line_stays_visible_when_the_find_bar_opens():
    """The same defect through a second door, which is why the fix is general.

    The strip is not special; the find bar, and closing the Address Book
    slide-out, take rows or columns from the same log. A fix written against
    the suggestion strip alone would leave these two reported the same way.
    """
    app, a, _b, incoming = await _connected_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        incoming[0].read_nowait()

        pane = app.query_one(TerminalPane)
        await _page_of_output(pane, pilot)
        log = app.query_one("#session-log", RichLog)
        assert _at_bottom(log)

        pane.open_find()
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()
        assert _at_bottom(log), (
            "the prompt fell below the fold when the find bar opened: "
            f"scroll_y={log.scroll_offset.y} max_scroll_y={log.max_scroll_y}"
        )


@pytest.mark.asyncio
async def test_an_operator_scrolled_back_is_not_yanked_to_the_bottom():
    """The other half of the guarantee, and the reason this is an anchor
    rather than a `scroll_end` on every layout pass.

    Following the bottom is only correct while the operator is *at* the
    bottom. Someone reading back through a node's listing must be able to
    keep their place while the strip appears under them -- a scrollback that
    snaps to the end whenever anything repaints is a different bug of the
    same size, and one this pane would hit constantly, because the retry and
    status timers repaint it on their own schedule.
    """
    app, a, _b, incoming = await _connected_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        incoming[0].read_nowait()
        app.reference = CommandReference(family=load_family("bpq32"))

        pane = app.query_one(TerminalPane)
        await _page_of_output(pane, pilot)
        log = app.query_one("#session-log", RichLog)

        log.scroll_to(y=5, animate=False, immediate=True)
        await pilot.pause()
        assert log.scroll_offset.y == 5

        field = app.query_one("#session-input", Input)
        field.focus()
        await pilot.press("c")
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()

        assert log.scroll_offset.y == 5, (
            "reading back through the scrollback must survive the strip "
            "appearing underneath it"
        )

        # ...and returning to the bottom re-arms the follow, so the next
        # thing that shrinks the log does not strand the prompt again.
        log.scroll_end(animate=False, immediate=True)
        await pilot.pause()
        pane.open_find()
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()
        assert _at_bottom(log), "scrolling back to the bottom must resume following it"


# ----------------------------------------------------------------------
# The node's prompt is the last thing it sends, and it must appear.
#
# These replay the real CCEMA (WS1EC-15) session of 2026-09-22 that this was
# diagnosed from: four I-frames, the last of them 53 bytes ending in a
# CR-terminated prompt with nothing after it. Two independent defects kept
# that prompt off the screen, and each test below pins one of them.
# ----------------------------------------------------------------------

#: The real final frame, byte for byte -- its 53 bytes match the length the
#: operator's own debug log recorded for `I S3 R0 P cmd len=53`, and the
#: instrumented run confirmed the tail left unwritten was `b'de WS1EC>\r'`.
CCEMA_LAST_FRAME = (
    b" \t- Disconnect\r"
    b"? \t- List of node commands\r"
    b"\r"
    b"de WS1EC>\r"
)


def _log_lines(app) -> list[str]:
    return [strip.text.rstrip() for strip in app.query_one("#session-log", RichLog).lines]


@pytest.mark.asyncio
async def test_a_cr_terminated_prompt_appears_without_waiting_for_the_idle_flush():
    """The prompt is a complete line the moment its CR arrives.

    It used to be held back on the chance that the CR was the first half of a
    CRLF split across two frames, which made the single most important line on
    screen depend on a timer firing. It is flushed immediately now; a LF
    opening the next frame is swallowed instead (see the CRLF test below).

    No `asyncio.sleep` here on purpose -- waiting would hide the defect by
    giving the idle flush time to run. One `pilot.pause()` to let the write
    render, and the prompt has to be there already.
    """
    app, station, peer, _ = await _connected_app()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        pane.write_incoming(pane.active_session_key, CCEMA_LAST_FRAME)
        await pilot.pause()

        assert "de WS1EC>" in _log_lines(app), (
            "the node prompt must be on screen as soon as its CR arrives, "
            f"not after an idle timer -- got {_log_lines(app)!r}"
        )
    station.close()
    peer.close()


@pytest.mark.asyncio
async def test_an_unterminated_tail_is_flushed_off_the_event_loop():
    """A prompt with NO terminator at all still has to appear, and the thing
    that makes it appear must not be the pane's message queue.

    On a real station, twice in one evening, a `Widget.set_timer` armed here
    ran zero times while `write_incoming` kept working. The cause was frames
    dispatched outside the app's context (tests/pilot/test_frame_context.py),
    which `run_test` cannot show because its pilot already runs inside that
    context. The flush stays off Textual's timers regardless, so this asserts the
    mechanism rather than the symptom: the scheduled flush is an
    `asyncio.TimerHandle` on the event loop, not a Textual timer.
    """
    app, station, peer, _ = await _connected_app()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        key = pane.active_session_key
        pane.write_incoming(key, b"CCEMA:WS1EC-15} ")  # no terminator at all

        # Read before any `pilot.pause()`: a pause costs 100-120ms of real
        # time (see AGENTS.md sec. 6) and the flush is scheduled for 200ms,
        # so pausing first races the very handle being asserted on.
        handle = pane._flush_timers.get(key)
        assert isinstance(handle, asyncio.TimerHandle), (
            "the idle flush must be scheduled on the event loop, not through "
            f"the pane's message queue -- got {handle!r}"
        )

        await asyncio.sleep(0.4)
        await pilot.pause()
        assert "CCEMA:WS1EC-15}" in _log_lines(app), (
            f"an unterminated prompt never appeared: {_log_lines(app)!r}"
        )
    station.close()
    peer.close()


# ---------------------------------------------------------------------------
# Context: node, application, unknown (command catalog, 2026-09-23)
# ---------------------------------------------------------------------------


def _status_parts(app, monkeypatch) -> str:
    """The status bar's fields as text, before the grid lays them out
    (a narrow column would wrap the field this is looking for)."""
    import kissterm.ui.app as app_module

    captured: list[str] = []
    real = app_module._status_row
    monkeypatch.setattr(
        app_module, "_status_row", lambda parts: (captured.extend(parts), real(parts))[1]
    )
    app._refresh_status()
    monkeypatch.setattr(app_module, "_status_row", real)
    return " | ".join(captured)


def _suggested(app, prefix: str) -> list[str]:
    pane = app.query_one(TerminalPane)
    pane._update_suggestions(prefix)
    return [command.name for command in pane._suggestion_matches]


@pytest.mark.asyncio
async def test_suggestions_follow_the_session_into_the_bbs_and_back(monkeypatch):
    """"L" is LINKS at a BPQ32 node and "list new mail" in its BBS. The node
    says which one is in effect ("Connected to BBS", "Returned to Node"),
    and the suggestions follow it, reading nothing but what arrived anyway."""
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        _feed(link, b"Welcome.\rCCEMA:WS1EC-15} ")
        await pilot.pause()
        assert app.reference.family.id == "bpq32"
        at_node = _suggested(app, "L")
        assert "LINKS" in at_node and "LM" not in at_node

        # The line can arrive split across frames; it is matched whole.
        app.log_sent(app._active_key(), "BBS")
        _feed(link, b"CCEMA:WS1EC-15} Connec")
        _feed(link, b"ted to BBS\r[BPQ-6.0.23.1-B2FWIHJM$]\rde WS1EC#>\r")
        await pilot.pause()
        assert app.reference.family.id == "bpqmail"
        in_bbs = _suggested(app, "L")
        assert in_bbs[:3] == ["L", "LR", "LM"] and "LINKS" not in in_bbs
        assert {"LD", "LF", "LH", "LK", "LL"} <= set(in_bbs)
        assert "BPQ32 > BPQMAIL" in _status_parts(app, monkeypatch)

        _feed(link, b"Returned to Node CCEMA:WS1EC-15} ")
        await pilot.pause()
        assert app.reference.family.id == "bpq32"
        assert "LINKS" in _suggested(app, "L")
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_an_application_with_no_reference_suggests_nothing(monkeypatch):
    """A sysop's own CALENDAR has commands kissterm does not know. Offering
    the node's there would be a guess, so the strip stays empty."""
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        _feed(link, b"CCEMA:WS1EC-15} ")
        await pilot.pause()
        app.log_sent(app._active_key(), "CALENDAR")
        _feed(link, b"CCEMA:WS1EC-15} Connected to CALENDAR\r")
        await pilot.pause()
        assert app.reference.family is None
        assert _suggested(app, "L") == []
        assert _suggested(app, "C") == []
        assert "BPQ32 > CALENDAR" in _status_parts(app, monkeypatch)
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_an_unidentified_prompt_suggests_nothing():
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        _feed(link, b"Hello from somewhere\r> ")
        await pilot.pause()
        assert app.reference.family is None
        assert _suggested(app, "L") == []
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_sysop_commands_are_never_suggested():
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        app.reference = CommandReference(family=load_family("bpq32"))
        assert "PASSWORD" not in _suggested(app, "PA")
        app.reference = CommandReference(family=load_family("bpqmail"))
        assert "KH" not in _suggested(app, "K")
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_the_reference_screen_lists_every_context_with_its_source():
    """At a BPQ32 node, Ctrl+R lists the node's commands first, then its
    BBS's and chat server's, each row saying which context it belongs to
    and where its description came from. A harvested name matching a
    shipped command marks that row; it never adds a second one."""
    app, a, b, _ = await _connected_app()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        _feed(link, b"CCEMA:WS1EC-15} ")
        await pilot.pause()
        app.reference.learned = (
            Command(name="NODES", confidence="learned"),
            Command(name="WALL", confidence="learned"),
        )
        await pilot.press("ctrl+r")
        await wait_for(lambda: isinstance(app.screen, CommandReferenceScreen), "Ctrl+R")
        table = app.screen.query_one("#ref-table")
        rows = [table.get_row_at(i) for i in range(table.row_count)]
        contexts = [row[3] for row in rows]
        assert contexts[0] == "Node"
        assert contexts.index("BBS") > max(
            i for i, c in enumerate(contexts) if c.startswith("Node")
        ), "the current context comes first"
        assert "BPQChat" in contexts

        by_name = {(str(row[0]), row[3]): row for row in rows}
        assert by_name[("N / NODES", "Node")][4] == "verified on air, offered here"
        assert by_name[("WALL", "Node")][4] == "harvested only"
        assert sum(1 for row in rows if str(row[0]).startswith("N / NODES")) == 1
        assert by_name[("NRR", "Node")][4] == "published"
        assert by_name[("PASSWORD", "Node, sysop")][4] == "published"
        assert by_name[("T / TALK", "Node")][4] == "recalled, unverified"
        assert by_name[("LD", "BBS")][2].startswith("List messages with status D")
    a.close()
    b.close()
