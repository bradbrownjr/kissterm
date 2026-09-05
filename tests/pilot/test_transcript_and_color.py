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

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.terminal_pane import TerminalPane  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

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
async def test_the_transcript_path_is_shown_to_the_operator(tmp_path):
    app, a, b, incoming = await _app(_config(tmp_path))
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await _connect(app, a, b, incoming, pilot)
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        log = pane.query_one("#session-log")
        assert "Transcript" in _rendered(log)
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
        pane.write_incoming(b"\x1b[2J\x1b[31mMENU\x1b[0m\x1b]0;pwned\x07")
        await pilot.pause()
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
        pane.write_incoming(b"\x1b[31mMENU\x1b[0m")
        await pilot.pause()
        log = pane.query_one("#session-log")
        rendered = _rendered(log)
        assert "MENU" in rendered
    a.close()
    b.close()
