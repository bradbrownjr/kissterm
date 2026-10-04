"""G on the Files tab: BPQMail's `FILES` listing and the downloads it
leads to (`kissterm/mail/bbs_files.py`, `collect.BbsCollector`'s files
run), against the WS1EC-2 capture and BPQ's YAPP bytes."""

from kissterm import _isolate

_isolate.isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402

from kissterm.mail.bbs_files import BbsFile, describe_airtime, parse_files  # noqa: E402
from kissterm.mail.collect import BbsCollector, CollectOptions  # noqa: E402

from .test_mail_collect import PROMPT, ScriptedBbs, _capture, _store  # noqa: E402

FILES_REPLY = _capture("files_ws1ec.txt")


def test_the_captured_listing_offers_eight_files_not_the_hint():
    files = parse_files(FILES_REPLY)
    assert len(files) == 8
    assert files[0] == BbsFile("bulletin.html.zip", 2286)
    assert files[-1] == BbsFile("strip_read_write.html.zip", 11651)
    assert not any("YAPP" in f.name for f in files)


def test_names_bpq_would_refuse_are_not_offered():
    assert parse_files(["../secret 10", "a/b 10", "empty 0", "ok.txt 5"]) == [BbsFile("ok.txt", 5)]


def test_airtime_is_shown_as_an_estimate():
    assert describe_airtime(2286) == "about 19 s"
    assert describe_airtime(11651) == "about 2 min"


def _yapp_reply(name: str, body: bytes) -> dict[bytes, bytes]:
    header = name.encode() + b"\x00" + str(len(body)).encode() + b"\x00"
    return {
        b"\x06\x01": bytes((1, len(header))) + header,
        b"\x06\x02": bytes((2, len(body))) + body + b"\x03\x01",
        b"\x06\x03": b"\x04\x01",
    }


class FilesBbs(ScriptedBbs):
    """A scripted BPQMail with a Files folder: `YAPP <name>` sends `ENQ 1`
    and answers the receiver's ACKs as `YAPPSendData` does; an unknown
    name gets "File x not found" and the prompt (`YAPPSendFile`)."""

    def __init__(self, files: dict[str, bytes]):
        super().__init__({"FILES": FILES_REPLY})
        self.files = files
        self.yapp: dict[bytes, bytes] = {}

    def _raw(self, data: bytes) -> None:
        for callback in list(self.on_data):
            callback(data)

    async def send(self, data: bytes) -> None:
        reply = self.yapp.get(bytes(data[:2]))
        if reply is not None:
            self.sent.append(repr(bytes(data)))
            asyncio.get_event_loop().call_later(0.01, self._raw, reply)
            return
        command = data.decode("latin-1").rstrip("\r")
        if command.startswith("YAPP "):
            self.sent.append(command)
            name = command[5:]
            if name in self.files:
                self.yapp = _yapp_reply(name, self.files[name])
                asyncio.get_event_loop().call_later(0.01, self._raw, b"\x05\x01")
            else:
                asyncio.get_event_loop().call_later(
                    0.01, self._deliver, [f"File {name} not found", PROMPT])
            return
        await super().send(data)


async def _files(bbs, tmp_path, pick):
    notes: list[str] = []
    states: list[bool] = []
    offered: list[list[BbsFile]] = []

    async def picker(files):
        offered.append(files)
        return pick

    folder = tmp_path / "Downloads"
    folder.mkdir()
    collector = BbsCollector(bbs, _store(tmp_path), CollectOptions(files=True),
                             note=notes.append, sent=lambda _t: None,
                             pick_files=picker, files_dir=folder,
                             transferring=states.append)
    bbs.start()
    result = await asyncio.wait_for(collector.run(), 5)
    return result, notes, states, offered, folder


@pytest.mark.asyncio
async def test_g_lists_the_files_and_downloads_each_one_picked(tmp_path):
    bbs = FilesBbs({"bulletin.html.zip": b"PK\x03\x04one", "fsr.html.zip": b"PK\x03\x04two"})
    result, notes, states, offered, folder = await _files(
        bbs, tmp_path, ["bulletin.html.zip", "fsr.html.zip"])
    assert not result.stopped, result.stopped
    assert len(offered[0]) == 8
    assert [p.name for p in result.downloaded] == ["bulletin.html.zip", "fsr.html.zip"]
    assert (folder / "fsr.html.zip").read_bytes() == b"PK\x03\x04two"
    commands = [s for s in bbs.sent if not s.startswith("b'")]
    assert commands == ["FILES", "YAPP bulletin.html.zip", "YAPP fsr.html.zip"]
    # The Terminal is told to hold its output for each transfer, then let go.
    assert states == [True, False, True, False]


@pytest.mark.asyncio
async def test_a_file_that_is_not_there_is_noted_and_the_next_is_fetched(tmp_path):
    bbs = FilesBbs({"fsr.html.zip": b"two"})
    result, notes, _states, _offered, _folder = await _files(
        bbs, tmp_path, ["gone.zip", "fsr.html.zip"])
    assert not result.stopped, result.stopped
    assert [p.name for p in result.downloaded] == ["fsr.html.zip"]
    assert "BBS: File gone.zip not found" in notes


@pytest.mark.asyncio
async def test_nothing_picked_downloads_nothing(tmp_path):
    bbs = FilesBbs({})
    result, notes, states, _offered, _folder = await _files(bbs, tmp_path, None)
    assert bbs.sent == ["FILES"] and not result.downloaded and not states
    assert "No files chosen." in notes
