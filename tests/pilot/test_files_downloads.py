"""A YAPP or AutoBIN download is saved in Files > Downloads and shows in
the Files tab (ROADMAP P2: they went to the state folder, out of sight)."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402
from textual.widgets import Tree  # noqa: E402

from kissterm.ui.mail_pane import MessageList  # noqa: E402
from tests.pilot._wait import wait_for  # noqa: E402
from tests.pilot.test_get_mail import _app  # noqa: E402


@pytest.mark.asyncio
async def test_downloads_go_to_files_downloads_and_show_there(tmp_path):
    app, station, _tb = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        folder = app._downloads_dir()
        assert folder == app.mail_store.root / "Files" / "Downloads" and folder.is_dir()
        (folder / "net-roster.txt").write_text("KC1JMH\n")
        app._reload_mail_tabs()
        app.action_show_tab("files")
        await pilot.pause()
        browser = app.query_one("#files-browser")
        tree = browser.query_one(Tree)
        node = next(n for n in tree.root.children if n.data == "Files/Downloads")
        tree.select_node(node)
        await pilot.pause()
        table = browser.query_one(MessageList)
        await wait_for(lambda: table.row_count == 1, "the download in the list")
        assert "net-roster.txt" in str(table.get_row_at(0))
    station.close()
