"""Reconnect, bulletin categories and transcripts in the core, for the
terminal and the phone alike (`Connector.reconnect`,
`Mail.bulletin_categories`, `Sessions.transcripts`/`read_transcript`)."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.core import Core  # noqa: E402
from kissterm.serve.headless import HeadlessView  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402


class _Operator:
    def __init__(self) -> None:
        self.notices: list[str] = []

    def notice(self, notice) -> None:
        self.notices.append(notice.text)

    async def ask(self, question):
        return None


async def _core(tmp_path):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = Config(mycall="N1ABC-1")
    config.log_dir = str(tmp_path / "logs")
    core = Core(config, AX25Station(AX25Address.parse("N1ABC-1"), ta, LinkParams()))
    core.operator = _Operator()
    core.attach_view(HeadlessView(core))
    core.attach_station()
    return core


@pytest.mark.asyncio
async def test_reconnect_redials_the_sessions_own_request(tmp_path, monkeypatch):
    core = await _core(tmp_path)
    dialled = []

    async def connect(request, **_):
        dialled.append(request)

    monkeypatch.setattr(core.connector, "connect", connect)
    await core.connector.reconnect("W1AW-7")
    assert [r.target for r in dialled] == ["W1AW-7"]

    monkeypatch.setattr(core.connector, "session_is_live", lambda key: True)
    await core.connector.reconnect("W1AW-7")
    assert len(dialled) == 1 and "Already connected to W1AW-7." in core.operator.notices


@pytest.mark.asyncio
async def test_reconnect_with_nothing_dialled_says_so(tmp_path):
    core = await _core(tmp_path)
    await core.connector.reconnect("")
    assert any("Nothing to reconnect to" in n for n in core.operator.notices)


@pytest.mark.asyncio
async def test_bulletin_categories_are_none_until_listed_then_chosen_offline(tmp_path, monkeypatch):
    from kissterm.mail.bulletins import SubscriptionBook

    core = await _core(tmp_path)
    core.mail.subscriptions = SubscriptionBook(tmp_path / "bulletins.json")
    monkeypatch.setattr(core.mail, "bulletin_bbs", lambda: "WS1EC")
    assert core.mail.bulletin_categories() is None
    core.mail.choose_bulletin_categories(["WX"], all_=False)
    assert any("No categories yet" in n for n in core.operator.notices)

    core.mail.subscriptions.for_bbs("WS1EC").seen = {"WX": 4, "ARES": 2, "SALE": 9}
    choice = core.mail.bulletin_categories()
    assert choice.bbs == "WS1EC" and list(choice.seen) == ["ARES", "SALE", "WX"]
    core.mail.choose_bulletin_categories(["WX", "ARES"], all_=False)
    assert core.mail.bulletin_categories().chosen == ["ARES", "WX"]
    assert "Collecting ARES, WX." in core.operator.notices


@pytest.mark.asyncio
async def test_transcripts_are_listed_searched_and_read_by_name_only(tmp_path):
    core = await _core(tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "20261006-120000_N1ABC-1_W1AW-7.log").write_text("Welcome to W1AW\nBYE\n")
    (logs / "20261005-090000_N1ABC-1_WS1EC.log").write_text("BBS mail\n")
    (tmp_path / "secret.log").write_text("not yours")
    names = [t.path.name for t in core.sessions.transcripts()]
    assert names == ["20261006-120000_N1ABC-1_W1AW-7.log", "20261005-090000_N1ABC-1_WS1EC.log"]
    assert [t.peer for t in core.sessions.transcripts("mail")] == ["WS1EC"]
    assert "Welcome to W1AW" in core.sessions.read_transcript(names[0])
    with pytest.raises(FileNotFoundError):
        core.sessions.read_transcript("../secret.log")
    assert core.sessions.read_transcript(names[0], limit=4) == "BYE\n"
