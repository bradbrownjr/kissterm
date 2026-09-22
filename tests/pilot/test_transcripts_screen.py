"""`TranscriptsScreen`: finding, reading and exporting past session logs
from inside the running app -- the roadmap gap this closes was "the only
way to find one again is a shell and `ls`/`grep`".
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402
from textual.widgets import DataTable, Input  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.dialogs import TranscriptsScreen  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
PEER = AX25Address.parse("WS1EC-7")


async def _connected_app(log_dir):
    """`log_dir` is a per-test directory, not the shared isolated state dir.

    `kissterm._isolate.isolate()` only takes effect on the FIRST `kissterm`
    import in the whole pytest process (see that module's docstring) --
    every pilot test in a full-suite run therefore shares one `log_path()`
    directory and accumulates every transcript any of them ever wrote.
    Pointing `Config.log_dir` at pytest's own per-test `tmp_path` is what
    keeps a row-count assertion here meaningful regardless of run order or
    what ran before it.
    """
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    a = AX25Station(MYCALL, ta, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    b = AX25Station(PEER, tb, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    config = Config(mycall=str(MYCALL))
    config.tx_armed_at_start = True
    config.log_dir = str(log_dir)
    app = KissTermApp(config, a)
    return app, a, b


@pytest.mark.asyncio
async def test_the_menu_opens_the_screen_and_lists_the_live_transcript(tmp_path):
    app, a, b = await _connected_app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        assert link is not None
        app._bind_link(link)
        await asyncio.sleep(0.1)
        assert app.transcript is not None
        transcript_path = app.transcript.path

        # Session > Transcripts. It gave up Ctrl+O to the key standard:
        # every command is in the menu, so few need a key of their own.
        await pilot.press("f10")
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.press("r")
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.pause()

        assert isinstance(app.screen, TranscriptsScreen)
        table = app.screen.query_one("#transcripts-table", DataTable)
        assert table.row_count == 1
        assert table.get_row_at(0)[1].startswith("WS1EC")

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, TranscriptsScreen)

        # The file really is there, independent of the screen's own read.
        assert transcript_path.exists()
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_search_filters_by_content_not_just_by_callsign(tmp_path):
    app, a, b = await _connected_app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        app._note(app._active_key(), "a very particular phrase")
        app.transcript.close()  # flush + stop, so the search reads a settled file
        app.transcript = None

        app.action_show_transcripts()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, TranscriptsScreen)

        search = screen.query_one("#transcripts-search", Input)
        search.value = "particular phrase"
        screen._populate(search.value)
        await pilot.pause()

        table = screen.query_one("#transcripts-table", DataTable)
        assert table.row_count == 1

        search.value = "no such text anywhere"
        screen._populate(search.value)
        await pilot.pause()
        assert table.row_count == 0
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_export_copies_the_selected_transcript(tmp_path):
    log_dir = tmp_path / "logs"
    app, a, b = await _connected_app(log_dir)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(PEER, MYCALL))
        app._bind_link(link)
        await asyncio.sleep(0.1)
        original_text = app.transcript.path.read_text()

        app.action_show_transcripts()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, TranscriptsScreen)

        table = screen.query_one("#transcripts-table", DataTable)
        table.move_cursor(row=0)
        await pilot.pause()
        assert screen._current is not None

        dest = tmp_path / "exported" / "ws1ec.log"
        screen.query_one("#transcripts-dest", Input).value = str(dest)
        from textual.widgets import Button

        screen.query_one("#transcripts-export", Button).press()
        await pilot.pause()

        assert dest.read_text() == original_text
    a.close()
    b.close()
