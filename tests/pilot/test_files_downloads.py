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


async def _files_tab(app, pilot, folder: str):
    app._reload_mail_tabs()
    app.action_show_tab("files")
    await pilot.pause()
    browser = app.query_one("#files-browser")
    browser.show_folder(folder)
    browser._select_tree_node()
    await pilot.pause()
    table = browser.query_one(MessageList)
    table.focus()
    await pilot.pause()
    return browser, table


@pytest.mark.asyncio
async def test_delete_and_u_on_the_files_tab(tmp_path):
    app, station, _tb = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        (app._downloads_dir() / "roster.txt").write_text("KC1JMH\n")
        browser, table = await _files_tab(app, pilot, "Files/Downloads")
        await wait_for(lambda: table.row_count == 1, "the file in the list")
        assert "delete" in app.screen.active_bindings
        await pilot.press("delete")
        await wait_for(lambda: table.row_count == 0, "the file gone from Downloads")
        deleted = app.mail_store.root / "Files" / "Deleted" / "roster.txt"
        assert deleted.exists()
        browser, table = await _files_tab(app, pilot, "Files/Deleted")
        await wait_for(lambda: table.row_count == 1, "the file in Deleted")
        await pilot.press("u")
        await wait_for(lambda: (app._downloads_dir() / "roster.txt").exists(), "the restore")
    station.close()


@pytest.mark.asyncio
async def test_s_sends_the_highlighted_file_only_while_connected(tmp_path):
    app, station, _tb = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        (app._downloads_dir() / "roster.txt").write_text("KC1JMH\n")
        browser, table = await _files_tab(app, pilot, "Files/Downloads")
        await wait_for(lambda: table.row_count == 1, "the file in the list")
        assert "s" not in app.screen.active_bindings  # nothing connected
        sent = []
        app.can_send_file = lambda: True
        app.action_file_transfer = sent.append
        table.refresh_bindings()
        await pilot.pause()
        assert app.screen.active_bindings["s"].binding.action == "send_file"
        await pilot.press("s")
        await wait_for(lambda: sent, "the transfer dialog")
        assert sent == [app.mail_store.root / "Files" / "Downloads" / "roster.txt"]
        assert not station.transport.sent
    station.close()


def _bpq_yapp_sender(far, body: bytes, name: str = "form.txt") -> list[bytes]:
    """BPQMail's `YAPP <name>` on `far`, byte for byte (LinBPQ
    `YAPPSendFile`/`ProcessYAPPMessage`): `ENQ 1` alone, then the header,
    data and `ETX 1`, `EOT 1`, each after kissterm's answer. Returns what
    kissterm sent."""
    import asyncio

    header = name.encode() + b"\x00" + str(len(body)).encode() + b"\x00"
    script = {
        b"\x06\x01": bytes((1, len(header))) + header,
        b"\x06\x02": bytes((2, len(body))) + body + b"\x03\x01",
        b"\x06\x03": b"\x04\x01",
    }
    heard: list[bytes] = []

    def answer(data: bytes) -> None:
        heard.append(bytes(data))
        if data.upper().startswith(b"YAPP "):
            reply = b"\x05\x01"
        else:
            reply = script.get(bytes(data[:2]))
        if reply:
            asyncio.get_event_loop().create_task(far.send(reply))

    far.on_data.append(answer)
    return heard


@pytest.mark.asyncio
async def test_asking_bpq_for_a_file_downloads_it_without_arming_anything(tmp_path):
    """The operator types `YAPP form.txt`; the BBS's `ENQ 1` starts the
    download by itself, into Files > Downloads, and none of its bytes
    reach the Terminal (operator, 2026-10-03)."""
    import asyncio

    from kissterm.ax25 import AX25Path, AX25Station
    from kissterm.ui.terminal_pane import TerminalPane
    from tests.pilot.test_get_mail import BBS, FAST, MYCALL, _log_text

    app, station, tb = await _app(tmp_path)
    bbs = AX25Station(BBS, tb, FAST)
    incoming = []
    bbs.on_incoming.append(incoming.append)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        link = await station.connect(AX25Path(BBS, MYCALL), timeout=2.0)
        app._bind_link(link)
        await pilot.pause()
        await wait_for(lambda: incoming, "the BBS to see the connect")
        heard = _bpq_yapp_sender(incoming[0], b"ICS 213\r\x00\xff\x01\x05\x01 binary")
        await app.query_one(TerminalPane).send_line("YAPP form.txt")
        saved = app._downloads_dir() / "form.txt"
        await wait_for(lambda: saved.exists(), "the download saved")
        assert saved.read_bytes() == b"ICS 213\r\x00\xff\x01\x05\x01 binary"
        await wait_for(lambda: b"\x06\x04" in heard, "the final ACK 4")
        await asyncio.sleep(0.1)
        await pilot.pause()
        assert "ICS 213" not in _log_text(app)
        assert not app._transfer_active
    station.close()
    bbs.close()


@pytest.mark.asyncio
async def test_an_enq_nobody_asked_for_is_not_a_download(tmp_path):
    """No `YAPP <name>` sent, no download: an unasked sender is the
    unattended mailbox's business (ROADMAP P9), not the Terminal's."""
    import asyncio

    from kissterm.ax25 import AX25Path, AX25Station
    from tests.pilot.test_get_mail import BBS, FAST, MYCALL

    app, station, tb = await _app(tmp_path)
    bbs = AX25Station(BBS, tb, FAST)
    incoming = []
    bbs.on_incoming.append(incoming.append)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        link = await station.connect(AX25Path(BBS, MYCALL), timeout=2.0)
        app._bind_link(link)
        await wait_for(lambda: incoming, "the BBS to see the connect")
        await incoming[0].send(b"\x05\x01")
        await asyncio.sleep(0.3)
        await pilot.pause()
        assert not app._transfer_active
        assert not any(app._downloads_dir().iterdir())
    station.close()
    bbs.close()


@pytest.mark.asyncio
async def test_browse_files_opens_the_picker_and_picks_a_file(tmp_path):
    """F10 > File transfer > Browse files crashed the app (operator,
    2026-10-03): the picker's helper replaced Textual's `_render`."""
    from textual.widgets import DataTable

    from kissterm.ui.dialogs import FilePickerScreen, FileTransferScreen

    (tmp_path / "form.txt").write_text("ICS 213\n")
    app, station, _tb = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.push_screen(FileTransferScreen())
        await pilot.pause()
        app.screen.query_one("#yapp-browse").press()
        await pilot.pause()
        assert isinstance(app.screen, FilePickerScreen)
        picker = app.screen
        picker.directory = tmp_path
        picker._list_folder()
        await pilot.pause()
        table = picker.query_one(DataTable)
        row = next(i for i in range(table.row_count) if table.get_row_at(i)[0] == "form.txt")
        table.move_cursor(row=row)
        await pilot.pause()
        picker.query_one("#file-picker-choose").press()  # the button, not only Enter
        await pilot.pause()
        assert isinstance(app.screen, FileTransferScreen)
        assert app.screen.query_one("#yapp-path").value == str(tmp_path / "form.txt")
    station.close()


@pytest.mark.asyncio
async def test_enter_opens_a_zip_and_its_files_formatted(tmp_path):
    """Enter on a downloaded zip lists its files; Enter on one shows it
    formatted; Esc goes back a level each time (operator, 2026-10-03)."""
    import io
    import zipfile
    from pathlib import Path

    from textual.widgets import DataTable, Markdown

    from kissterm.ui.file_viewer import FileViewerScreen

    page = (Path(__file__).parents[1] / "unit" / "data" / "pktnet" / "bulletin.html").read_bytes()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("bulletin.html", page)
        archive.writestr("README.md", b"# Forms\n\nRead **me**.\n")
    app, station, _tb = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        (app._downloads_dir() / "forms.zip").write_bytes(buffer.getvalue())
        browser, table = await _files_tab(app, pilot, "Files/Downloads")
        await wait_for(lambda: table.row_count == 1, "the zip in the list")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, FileViewerScreen) and app.screen.kind == "zip"
        members = app.screen.query_one(DataTable)
        assert members.row_count == 2
        members.move_cursor(row=0)
        await pilot.press("enter")
        await pilot.pause()
        viewer = app.screen
        assert isinstance(viewer, FileViewerScreen) and viewer.kind == "html"
        assert "Precedence: [Routine v]" in viewer.query_one(Markdown).source
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen.kind == "zip"
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, FileViewerScreen)
    station.close()


@pytest.mark.asyncio
async def test_enter_on_a_pktnet_form_opens_kissterms_form_for_it(tmp_path):
    """Enter in the viewer on KN4LQN's bulletin page opens the PKTNET Bulletin
    form, as Mail > Insert does; nothing is sent (operator, 2026-10-03)."""
    from pathlib import Path

    from kissterm.ui.file_viewer import FileViewerScreen
    from kissterm.ui.form_screen import FormScreen

    page = (Path(__file__).parents[1] / "unit" / "data" / "pktnet" / "bulletin.html").read_bytes()
    app, station, _tb = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.push_screen(FileViewerScreen("bulletin.html", page))
        await pilot.pause()
        assert app.screen.active_bindings["enter"].binding.action == "fill_in"
        await pilot.press("enter")
        await wait_for(lambda: isinstance(app.screen, FormScreen), "the form screen")
        assert app.screen.form.id == "pktnet_bulletin"
        await pilot.press("escape")
        await pilot.pause()
        assert not station.transport.sent
    station.close()


@pytest.mark.asyncio
async def test_fill_in_is_absent_on_a_page_that_is_no_known_form(tmp_path):
    from kissterm.ui.file_viewer import FileViewerScreen

    app, station, _tb = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.push_screen(FileViewerScreen("page.html", b"<title>Hello</title><p>hi</p>"))
        await pilot.pause()
        assert "enter" not in app.screen.active_bindings
    station.close()
