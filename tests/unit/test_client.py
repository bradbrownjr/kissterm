"""The remote client's connection and model (`kissterm/client/`) against a
real server on a loopback station.

What a phone relies on: it learns the station's state from the welcome,
follows events, reconnects without losing what the station kept, stops
for good on a wrong token, and shows a line as sent only when the station
says it went.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import ast  # noqa: E402
import asyncio  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("uvicorn")

from kissterm.client.connection import CommandFailed, Connection  # noqa: E402
from kissterm.client.state import StationState  # noqa: E402
from kissterm.core import events as ev  # noqa: E402
from kissterm.core.questions import RadioReminder  # noqa: E402
from tests.unit.test_serve import TOKEN, _serve, _until  # noqa: E402

CLIENT = Path(__file__).resolve().parents[2] / "kissterm" / "client"


async def _client(server, token: str = TOKEN):
    state = StationState()
    statuses: list[str] = []
    conn = Connection(f"ws://127.0.0.1:{server.port}/v1", token,
                      on_message=state.apply, on_status=statuses.append)
    conn.start()
    return conn, state, statuses


@pytest.mark.asyncio
async def test_the_welcome_and_events_build_the_model():
    core, server, ta, peer = await _serve()
    conn, state, _ = await _client(server)
    assert await conn.wait_connected()
    assert state.callsign == "N1ABC-1" and state.gate is False
    seen = []
    state.subscribe(lambda kind, data: seen.append(kind))
    core.gate.set(True)
    await _until(lambda: state.gate is True)
    assert "gate" in seen
    await conn.close()
    await server.stop()


@pytest.mark.asyncio
async def test_a_wrong_token_stops_for_good():
    core, server, ta, peer = await _serve()
    conn, state, statuses = await _client(server, token="wrong")
    await _until(lambda: conn.status == "refused")
    assert not await conn.wait_connected(0.1)
    await conn.close()
    await server.stop()


@pytest.mark.asyncio
async def test_a_reconnect_asks_only_for_what_it_missed():
    core, server, ta, peer = await _serve()
    conn, state, _ = await _client(server)
    assert await conn.wait_connected()
    core.events.publish(ev.SessionData("WS1EC-7", b"one\r\n"))
    await _until(lambda: "one" in state.session("WS1EC-7").text())
    for client in list(server.clients):
        await client.ws.close(1001, "going away")
    await _until(lambda: conn.status != "connected")
    core.events.publish(ev.SessionData("WS1EC-7", b"two\r\n"))
    assert await conn.wait_connected(15)
    await _until(lambda: "two" in state.session("WS1EC-7").text())
    assert state.session("WS1EC-7").text().count("one") == 1, "a replay doubled the text"
    await conn.close()
    await server.stop()


@pytest.mark.asyncio
async def test_a_line_is_shown_only_once_the_station_sent_it():
    core, server, ta, peer = await _serve()
    conn, state, _ = await _client(server)
    assert await conn.wait_connected()
    assert await conn.command("send_line", key="WS1EC-7", text="BBS") is False
    await asyncio.sleep(0.2)
    assert "BBS" not in state.session("WS1EC-7").text()
    assert any(n["text"] == "Not connected." for n in state.notices)
    with pytest.raises(CommandFailed):
        await conn.command("no_such_command")
    await conn.close()
    await server.stop()


@pytest.mark.asyncio
async def test_a_question_is_answered_through_the_model():
    core, server, ta, peer = await _serve()
    conn, state, _ = await _client(server)
    assert await conn.wait_connected()
    asked = asyncio.ensure_future(core.operator.ask(RadioReminder("145.090")))
    await _until(lambda: bool(state.questions))
    question = next(iter(state.questions.values()))
    assert question.name == "RadioReminder" and question.data["frequency"] == "145.090"
    await conn.answer(question.qid, True)
    assert await asyncio.wait_for(asked, 3) is True
    await _until(lambda: not state.questions)
    await conn.close()
    await server.stop()


def test_timer_recovery_is_still_connected():
    state = StationState()
    state.apply({"type": "event", "seq": 1, "name": "SessionStateChanged",
                 "data": {"key": "W1AW-7", "state": "timer-recovery"}})
    assert state.session("W1AW-7").connected


def _absolute(path: Path, node: ast.ImportFrom) -> str:
    package = list(path.relative_to(CLIENT.parent.parent).with_suffix("").parts[:-1])
    if node.level:
        package = package[: len(package) - node.level + 1]
        return ".".join(package + ([node.module] if node.module else []))
    return node.module or ""


def test_the_client_never_reaches_into_the_station():
    """The client is the protocol's other end: it must run on a phone with
    no station in it, and never take a shortcut around the gate."""
    station = ("kissterm.core", "kissterm.ui", "kissterm.serve", "kissterm.transport",
               "kissterm.ax25")
    for path in CLIENT.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [_absolute(path, node)]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            for name in names:
                assert not name.startswith(station), \
                    f"{path.name} imports {name}: the client talks only the protocol"
