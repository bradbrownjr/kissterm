"""Restart (`core/restart.py`): disconnect first, force after a timeout,
then hand over to the front end; a watchdog re-executes if the shutdown
hangs. The operator's two asks (2026-10-07): "do a disconnect before
restart rather than refusing", and "add a timeout in case graceful
disconnect won't work ... and force the disconnect"."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402
import threading  # noqa: E402

import pytest  # noqa: E402

from kissterm.core.restart import RESTART_EXIT, command_line, describe  # noqa: E402
from kissterm.ax25 import AX25Path  # noqa: E402
from kissterm.ax25.frame import UType  # noqa: E402
from tests.unit.test_serve import MYCALL, PEER, _join, _serve  # noqa: E402


async def _connected(core):
    core.gate.set(True)
    link = await core.station.connect(AX25Path(PEER, MYCALL))
    assert link.connected
    core.sessions.bind(link)
    return link


def _quick(core, fired: list) -> None:
    restarter = core.restarter
    restarter.disconnect_wait = 0.5
    restarter.shutdown_wait = 30
    restarter.on_restart = lambda: fired.append("stop")


@pytest.mark.asyncio
async def test_a_restart_disconnects_politely_then_stops_the_front_end():
    core, server, ta, peer = await _serve()
    link = await _connected(core)
    fired: list = []
    _quick(core, fired)
    assert core.restarter.plan()["sessions"] == [str(PEER)]
    await core.restarter.restart("a test")
    core.restarter.cancel_watchdog()
    assert fired == ["stop"] and core.restarter.requested
    assert not link.connected, "the DISC was answered: the link is down"
    assert [f.utype for f in ta.sent].count(UType.DISC) == 1, "one DISC, answered"
    await server.stop()
    core.sessions.shutdown()


@pytest.mark.asyncio
async def test_an_unanswered_disc_is_forced_after_the_timeout():
    core, server, ta, peer = await _serve()
    link = await _connected(core)
    ta.peer = None  # the far station has gone: nothing it sends is heard
    fired: list = []
    _quick(core, fired)
    started = asyncio.get_running_loop().time()
    await core.restarter.restart("a test")
    core.restarter.cancel_watchdog()
    took = asyncio.get_running_loop().time() - started
    assert fired == ["stop"]
    assert 0.4 < took < 3, f"forced after {took:.1f} s"
    assert link not in core.station.links.values(), "dropped, so shutdown sends no DISC"
    assert [f.utype for f in ta.sent].count(UType.DISC) >= 1, "it was asked politely first"
    sent = len(ta.sent)
    await core.station.disconnect_all()
    await asyncio.sleep(0.5)
    assert len(ta.sent) == sent, "the forced link kept transmitting"
    await server.stop()
    core.sessions.shutdown()


@pytest.mark.asyncio
async def test_the_watchdog_restarts_a_shutdown_that_hangs():
    core, server, ta, peer = await _serve()
    forced = threading.Event()
    core.restarter.shutdown_wait = 0.2
    core.restarter.force = forced.set
    core.restarter.on_restart = lambda: None  # a front end that never exits
    await core.restarter.restart("a test")
    assert await asyncio.to_thread(forced.wait, 3), "no restart from the watchdog"
    await server.stop()
    core.sessions.shutdown()


@pytest.mark.asyncio
async def test_a_remote_client_restarts_the_station():
    core, server, ta, peer = await _serve()
    fired: list = []
    _quick(core, fired)
    client = await _join(server)
    await client.next()
    plan = (await client.command("p1", "restart_plan"))["value"]
    assert plan == {"sessions": [], "aprs_unacked": 0}
    assert (await client.command("p2", "restart"))["value"] is True
    for _ in range(50):
        if fired:
            break
        await asyncio.sleep(0.05)
    core.restarter.cancel_watchdog()
    assert fired == ["stop"]
    await client.ws.close()
    await server.stop()
    core.sessions.shutdown()


def test_the_words_and_the_command_line():
    assert "Disconnects WS1EC-7 first" in describe({"sessions": ["WS1EC-7"], "aprs_unacked": 2})
    assert "2 APRS messages" in describe({"sessions": [], "aprs_unacked": 2})
    line = command_line()
    assert line[1:3] == ["-m", "kissterm"]
    assert RESTART_EXIT not in (0, 1, 2, 3, 130)


def test_restart_is_in_the_session_menu_with_no_key():
    from kissterm.ui import commands as cmdreg

    command = next(c for c in cmdreg.COMMANDS if c.action == "restart")
    assert (command.group, command.mnemonic, command.key) == ("Session", "K", "")


@pytest.mark.asyncio
async def test_a_remote_shutdown_stops_without_starting_again():
    """Operator, 2026-10-07: "so we have the option of not restarting"."""
    core, server, ta, peer = await _serve()
    link = await _connected(core)
    fired: list = []
    _quick(core, fired)
    client = await _join(server)
    await client.next()
    assert (await client.command("s1", "shutdown"))["value"] is True
    for _ in range(60):
        if fired:
            break
        await asyncio.sleep(0.05)
    core.restarter.cancel_watchdog()
    assert fired == ["stop"]
    assert core.restarter.requested and not core.restarter.restarting
    assert not link.connected, "disconnected first, as a restart does"
    await client.ws.close()
    await server.stop()
    core.sessions.shutdown()


@pytest.mark.asyncio
async def test_a_hung_shutdown_exits_rather_than_restarting():
    core, server, ta, peer = await _serve()
    halted, forced = threading.Event(), threading.Event()
    core.restarter.shutdown_wait = 0.2
    core.restarter.force, core.restarter.halt = forced.set, halted.set
    core.restarter.on_restart = lambda: None
    await core.restarter.restart("a test", again=False)
    assert await asyncio.to_thread(halted.wait, 3) and not forced.is_set()
    await server.stop()
    core.sessions.shutdown()


def test_the_shutdown_words_say_it_stays_stopped():
    assert "stays stopped" in describe({"sessions": []}, again=False)
