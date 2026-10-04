"""Get files (Files tab, G) end to end: dial the Home BBS, `FILES`, the
checklist with sizes and airtime, then a YAPP download of the one ticked
into Files > Downloads, the Terminal holding the binary meanwhile.

The BBS is a second `AX25Station` on the loopback answering `FILES` with
WS1EC-2's own reply (2026-10-03, `tests/unit/data/bpqmail/`) and `YAPP`
with BPQMail's bytes (`YAPPSendFile`, `YAPPSendData`).
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402
from textual.widgets import SelectionList, Static  # noqa: E402

from kissterm.ax25 import AX25Station  # noqa: E402
from kissterm.ui.bbs_files_screen import BbsFilesScreen  # noqa: E402
from kissterm.ui.mail_pane import MessageList  # noqa: E402
from tests.pilot._wait import wait_for  # noqa: E402
from tests.pilot.test_get_bulletins import GREETING, PROMPT, _lines  # noqa: E402
from tests.pilot.test_get_mail import BBS, FAST, _app, _log_text  # noqa: E402

BODY = b"PK\x03\x04" + bytes(range(256)) * 3


def _bpqmail(bbs: AX25Station, heard: list[str]) -> None:
    header = b"fsr.html.zip\x00" + str(len(BODY)).encode() + b"\x00"
    chunks = [BODY[i:i + 200] for i in range(0, len(BODY), 200)]
    yapp = {
        b"\x06\x01": bytes((1, len(header))) + header,
        b"\x06\x02": b"".join(bytes((2, len(c))) + c for c in chunks) + b"\x03\x01",
        b"\x06\x03": b"\x04\x01",
    }

    def _greet(link) -> None:
        def _send(data: bytes) -> None:
            asyncio.get_event_loop().create_task(link.send(data))

        def _answer(data: bytes) -> None:
            if bytes(data[:2]) in yapp or data[:2] == b"\x06\x04":
                heard.append(repr(bytes(data[:2])))
                if bytes(data[:2]) in yapp:
                    _send(yapp[bytes(data[:2])])
                return
            for command in data.decode("latin-1").split("\r")[:-1]:
                command = command.strip()
                heard.append(command)
                if command == "FILES":
                    _send(_lines("files_ws1ec.txt"))
                elif command == "YAPP fsr.html.zip":
                    _send(b"\x05\x01")

        link.on_data.append(_answer)

        async def _banner() -> None:
            await asyncio.sleep(0.15)
            await link.send(GREETING)

        asyncio.get_event_loop().create_task(_banner())

    bbs.on_incoming.append(_greet)


@pytest.mark.asyncio
async def test_g_lists_the_files_and_downloads_the_one_ticked(tmp_path):
    app, station, tb = await _app(tmp_path)
    bbs = AX25Station(BBS, tb, FAST)
    heard: list[str] = []
    _bpqmail(bbs, heard)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_show_tab("files")
        await pilot.pause()
        app.query_one("#files-browser").query_one(MessageList).focus()
        await pilot.pause()
        assert app.screen.active_bindings["g"].binding.action == "get_files"
        await pilot.press("g")
        await wait_for(lambda: isinstance(app.screen, BbsFilesScreen), "the file checklist",
                       timeout=15)
        listing = app.screen.query_one("#bbs-files-list", SelectionList)
        assert listing.option_count == 8
        prompts = [str(listing.get_option_at_index(i).prompt)
                   for i in range(listing.option_count)]
        assert "fsr.html.zip  3,471 bytes, about 29 s" in prompts
        assert not listing.selected
        listing.select("fsr.html.zip")
        await pilot.pause()
        total = str(app.screen.query_one("#bbs-files-total", Static).render())
        assert total.startswith("1 ticked, 3,471 bytes")
        await pilot.click("#connect-go")
        saved = app._downloads_dir() / "fsr.html.zip"
        await wait_for(saved.exists, "the download", timeout=15)
        await wait_for(lambda: "b'\\x06\\x04'" in heard, "the last ACK")
        assert saved.read_bytes() == BODY
        assert heard[:2] == ["FILES", "YAPP fsr.html.zip"]
        # The Terminal printed none of the file.
        terminal = _log_text(app)
        assert "YAPP fsr.html.zip" in terminal and "PK" not in terminal
    bbs.close()
    station.close()
