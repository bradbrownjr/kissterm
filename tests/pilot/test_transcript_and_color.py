"""Two things that are only true end to end.

A unit test can prove `SessionLog` writes a file and `ansi.to_text` filters an
escape sequence. Neither proves the app actually *wires* them to a link -- and
a transcript nobody calls, or a colour setting the pane ignores, both pass
their own unit tests perfectly.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402
from textual.geometry import Region  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.terminal_pane import TerminalPane  # noqa: E402
from tests.loopback import loopback_pair
from tests.pilot._wait import wait_for  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
PEER = AX25Address.parse("WS1EC-7")


async def _app(config: Config):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    a = AX25Station(MYCALL, ta, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    b = AX25Station(PEER, tb, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    incoming: list = []
    b.on_incoming.append(incoming.append)
    return KissTermApp(config, a), a, b, incoming


def _rendered(log) -> str:
    """The text a RichLog is holding, the way the other pilot tests read it.

    `RichLog.lines` is the widget's own rendered content and survives
    scrolling; `render_lines(region)` returns only what is currently on
    screen, which for a log that has scrolled is blank space.
    """
    return "\n".join(str(line) for line in log.lines)


def _config(tmp_path, **kw) -> Config:
    cfg = Config(mycall=str(MYCALL))
    # See tests/pilot/test_transmit_gate.py for the closed-by-default rule;
    # a transcript needs a session, and a session needs to transmit.
    cfg.tx_armed_at_start = True
    cfg.log_dir = str(tmp_path / "logs")
    for key, value in kw.items():
        setattr(cfg, key, value)
    return cfg


async def _connect(app, a, b, incoming, pilot):
    link = await a.connect(AX25Path(PEER, MYCALL), timeout=2.0)
    assert link is not None and link.connected
    app._bind_link(link)
    await pilot.pause()
    await asyncio.sleep(0.1)
    assert incoming, "peer never saw the connection"
    return link, incoming[0]


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_connected_session_writes_both_directions_to_disk(tmp_path):
    app, a, b, incoming = await _app(_config(tmp_path))
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link, far = await _connect(app, a, b, incoming, pilot)

        await app.query_one(TerminalPane).send_line("L")
        await far.send(b"No messages.\r")
        await asyncio.sleep(0.3)
        await pilot.pause()

        assert app.transcript is not None
        text = app.transcript.path.read_text()
    a.close()
    b.close()

    assert "> L" in text, text
    assert "< No messages." in text, text


@pytest.mark.asyncio
async def test_transcript_recording_is_shown_in_the_status_bar(tmp_path):
    """Recording should not consume a row from the live terminal."""
    app, a, b, incoming = await _app(_config(tmp_path))
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await _connect(app, a, b, incoming, pilot)
        await pilot.pause()
        status = app.query_one("#status-bar")
        region = Region(0, 0, status.size.width, status.size.height)
        assert "LOGGING" in "\n".join(strip.text for strip in status.render_lines(region))
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_remote_escape_sequences_never_reach_the_transcript(tmp_path):
    """`cat` on a transcript would execute whatever escapes it contains."""
    app, a, b, incoming = await _app(_config(tmp_path))
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        _, far = await _connect(app, a, b, incoming, pilot)
        await far.send(b"\x1b[2J\x1b]0;pwned\x07NODE ready\r")
        await asyncio.sleep(0.3)
        await pilot.pause()
        text = app.transcript.path.read_text()
    a.close()
    b.close()
    assert "\x1b" not in text and "pwned" not in text, repr(text)
    assert "NODE ready" in text


@pytest.mark.asyncio
async def test_logging_off_writes_nothing(tmp_path):
    directory = tmp_path / "logs"
    app, a, b, incoming = await _app(_config(tmp_path, log_sessions=False))
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await _connect(app, a, b, incoming, pilot)
        await app.query_one(TerminalPane).send_line("L")
        await asyncio.sleep(0.2)
        assert app.transcript is None
    a.close()
    b.close()
    assert not directory.exists() or not list(directory.iterdir())


@pytest.mark.asyncio
async def test_an_unwritable_log_directory_does_not_disturb_the_link(tmp_path):
    """A full or read-only disk must not take the station off the air."""
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    app, a, b, incoming = await _app(_config(tmp_path, log_dir=str(blocked)))
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link, far = await _connect(app, a, b, incoming, pilot)
        assert app.transcript is None
        await app.query_one(TerminalPane).send_line("still works")
        await asyncio.sleep(0.3)
        assert link.connected
    a.close()
    b.close()


# ---------------------------------------------------------------------------
# Remote colour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remote_color_setting_reaches_the_pane(tmp_path):
    for enabled in (True, False):
        app, a, b, _ = await _app(_config(tmp_path, remote_color=enabled))
        async with app.run_test(size=(110, 32)) as pilot:
            await pilot.pause()
            assert app.query_one(TerminalPane).remote_color is enabled
        a.close()
        b.close()


@pytest.mark.asyncio
async def test_colour_is_kept_but_cursor_control_is_not(tmp_path):
    """Both halves in one assertion, because the tempting bug is to relax the
    filter in order to let the colour through."""
    app, a, b, _ = await _app(_config(tmp_path, remote_color=True))
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        pane.write_incoming(pane.active_session_key, b"\x1b[2J\x1b[31mMENU\x1b[0m\x1b]0;pwned\x07")
        # No trailing newline in that chunk, so TerminalPane holds it back
        # (see `_flush_incoming`) until its idle timer fires.
        await pilot.pause(0.3)
        log = pane.query_one("#session-log")
        rendered = _rendered(log)
        assert "MENU" in rendered
        assert "pwned" not in rendered
        assert "\x1b" not in rendered
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_colour_off_still_shows_the_text(tmp_path):
    app, a, b, _ = await _app(_config(tmp_path, remote_color=False))
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        pane.write_incoming(pane.active_session_key, b"\x1b[31mMENU\x1b[0m")
        # No trailing newline in that chunk -- see the comment in the sibling
        # test above.
        await pilot.pause(0.3)
        log = pane.query_one("#session-log")
        rendered = _rendered(log)
        assert "MENU" in rendered
    a.close()
    b.close()


# ---------------------------------------------------------------------------
# Reply watch -- "they got it, are they just not answering?"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_note_appears_once_a_sent_line_goes_unanswered(tmp_path, monkeypatch):
    """From a real report: WS1EC-15 ACKed a typed line (an RR, at the AX.25
    layer) within 3 seconds and then said nothing for 22 more, and the
    operator had no on-screen way to tell "they got it, they are just
    slow" from "this went nowhere" -- the ACK is a supervisory frame the
    Monitor tab used to hide by default, and nothing else marked it."""
    from kissterm.ui import app as app_module

    # 1 s, not 0.2: the note is written only if the far end has already
    # ACKed by then, and under parallel load the loopback's ACK sometimes
    # took longer than 0.2 s -- the note was then correctly skipped and the
    # test failed with nothing wrong in the app (P0.4).
    monkeypatch.setattr(app_module, "REPLY_WAIT_SECONDS", 1.0)
    app, a, b, incoming = await _app(_config(tmp_path))
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await _connect(app, a, b, incoming, pilot)
        await pilot.pause()

        await app.query_one(TerminalPane).send_line("L")
        # Nothing sent back on purpose -- b's own link still ACKs the I-frame
        # at the AX.25 layer automatically, same as any real peer would.
        # Waits on the note itself, not a fixed 0.5 s: under parallel load
        # the ACK plus the 0.2 s reply wait did not always fit (P0.4).
        log = app.query_one(TerminalPane).query_one("#session-log")
        await wait_for(lambda: "acknowledged that" in _rendered(log), "the no-reply note")
        await pilot.pause()

        text = _rendered(log)
        assert "acknowledged that" in text, text
        assert str(PEER) in text, text
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_no_note_when_a_reply_actually_arrives(tmp_path, monkeypatch):
    """The note exists to fill a real silence, not to shadow every send --
    an actual reply must cancel it."""
    from kissterm.ui import app as app_module

    monkeypatch.setattr(app_module, "REPLY_WAIT_SECONDS", 0.2)
    app, a, b, incoming = await _app(_config(tmp_path))
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link, far = await _connect(app, a, b, incoming, pilot)
        await pilot.pause()

        await app.query_one(TerminalPane).send_line("L")
        await far.send(b"No messages.\r")
        await asyncio.sleep(0.5)
        await pilot.pause()

        text = _rendered(app.query_one(TerminalPane).query_one("#session-log"))
        assert "acknowledged that" not in text, text
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_no_note_while_the_line_is_still_unacknowledged(tmp_path, monkeypatch):
    """If the AX.25 layer itself has nothing outstanding acknowledged yet,
    T1/timer-recovery is already retrying and already wrote its own note --
    this one would only repeat that with less information. Simulated with
    100% loss on the sending transport, so the I-frame never reaches the
    peer at all and V(A) never advances past what it was before the send."""
    from kissterm.ui import app as app_module

    monkeypatch.setattr(app_module, "REPLY_WAIT_SECONDS", 0.2)
    app, a, b, incoming = await _app(_config(tmp_path))
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link, far = await _connect(app, a, b, incoming, pilot)
        await pilot.pause()
        a.transport.loss = 1.0

        await app.query_one(TerminalPane).send_line("L")
        await asyncio.sleep(0.5)
        await pilot.pause()

        text = _rendered(app.query_one(TerminalPane).query_one("#session-log"))
        assert "acknowledged that" not in text, text
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_no_note_after_an_empty_line(tmp_path, monkeypatch):
    """From a real report (CCEMA, 2026-09-22 16:30): with the node's prompt
    hidden, the operator pressed Enter on an empty line to prod the node. It
    ACKed at the AX.25 layer and, reasonably, said nothing -- and 15 seconds
    later the note blamed the silence on the far end while the node was
    waiting on the operator. A blank line is a nudge, not a question."""
    from kissterm.ui import app as app_module

    monkeypatch.setattr(app_module, "REPLY_WAIT_SECONDS", 0.2)
    app, a, b, incoming = await _app(_config(tmp_path))
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await _connect(app, a, b, incoming, pilot)
        await pilot.pause()

        await app.query_one(TerminalPane).send_line("")
        await asyncio.sleep(0.5)
        await pilot.pause()

        text = _rendered(app.query_one(TerminalPane).query_one("#session-log"))
        assert "acknowledged that" not in text, text
    a.close()
    b.close()
