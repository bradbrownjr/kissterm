"""The remote-control server inside the terminal UI, as the operator meets
it: off unless Settings says so, REMOTE in the status bar while on, a
question on the station's screen and the phone at once (the first answer
takes the other down), and a pairing dialog that fits 80x24 and rotates
the link only when confirmed.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402
import json  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("websockets")

from textual.widgets import Static  # noqa: E402
from websockets.asyncio.client import connect as ws_connect  # noqa: E402
from websockets.exceptions import ConnectionClosed  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.config import Config, ServeConfig  # noqa: E402
from kissterm.core.questions import RadioReminder  # noqa: E402
from kissterm.serve.server import UNAUTHORIZED  # noqa: E402
from kissterm.ui.dialogs import RadioReminderScreen, RemotePairingScreen, RotateTokenScreen  # noqa: E402
from tests.pilot._wait import wait_for  # noqa: E402


def _app(enabled: bool) -> KissTermApp:
    serve = ServeConfig(enabled=enabled, listen="127.0.0.1", port=0)
    return KissTermApp(Config(mycall="N1ABC-1", serve=serve))


def _status(app) -> str:
    from textual.geometry import Region

    app._refresh_status()
    bar = app.query_one("#status-bar")
    region = Region(0, 0, bar.outer_size.width or 200, bar.outer_size.height or 1)
    return "\n".join(strip.text for strip in bar.render_lines(region))


async def _client(app):
    ws = await ws_connect(f"ws://127.0.0.1:{app.remote.server.port}/v1")
    await ws.send(json.dumps({"type": "hello", "token": app.remote.token()}))
    assert json.loads(await ws.recv())["type"] == "welcome"
    return ws


async def _next(ws, kind: str) -> dict:
    async def read():
        while True:
            message = json.loads(await ws.recv())
            if message["type"] == kind:
                return message
    return await asyncio.wait_for(read(), 3)


@pytest.mark.asyncio
async def test_off_by_default_and_the_dialog_still_shows_the_link():
    app = _app(enabled=False)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.remote.server is None and "REMOTE" not in _status(app)
        app.action_remote_pairing()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, RemotePairingScreen)
        assert app.remote.token() in str(screen.query_one("#pairing-url", Static).render())
        assert str(screen.query_one("#pairing-status", Static).render()).startswith("Off.")
        box = screen.query_one("#connect-box").region
        assert box.bottom <= 24 and box.right <= 80, "the dialog runs off an 80x24 screen"
        assert screen.query_one("#pairing-close").region.bottom <= 24
        qr = screen.query_one("#pairing-qr", Static)
        assert qr.region.height >= 17, "no room for the QR code"


@pytest.mark.asyncio
async def test_on_a_question_goes_to_both_and_the_phone_can_answer_it():
    app = _app(enabled=True)
    async with app.run_test(size=(110, 32)) as pilot:
        await wait_for(lambda: app.remote.server is not None, "the server to start")
        await pilot.pause()
        assert "REMOTE" in _status(app)
        ws = await _client(app)
        asked = asyncio.ensure_future(app.core.operator.ask(RadioReminder("145.090")))
        question = await _next(ws, "question")
        await pilot.pause()
        assert isinstance(app.screen, RadioReminderScreen)
        await ws.send(json.dumps({"type": "answer", "id": question["id"], "value": True}))
        assert await asyncio.wait_for(asked, 3) is True
        await pilot.pause()
        assert not isinstance(app.screen, RadioReminderScreen), \
            "the station's question stayed up after the phone answered"
        await ws.close()


@pytest.mark.asyncio
async def test_rotate_asks_first_then_drops_every_client():
    app = _app(enabled=True)
    async with app.run_test(size=(110, 32)) as pilot:
        await wait_for(lambda: app.remote.server is not None, "the server to start")
        ws = await _client(app)
        await wait_for(lambda: app.remote.clients == 1, "the client to register")
        old = app.remote.token()
        app.action_remote_pairing()
        await pilot.pause()
        await pilot.click("#pairing-rotate")
        await pilot.pause()
        assert isinstance(app.screen, RotateTokenScreen)
        await pilot.click("#connect-cancel")
        await pilot.pause()
        assert app.remote.token() == old, "Cancel still rotated the link"
        await pilot.click("#pairing-rotate")
        await pilot.pause()
        await pilot.click("#connect-go")
        # Rotating restarts the server in a worker: wait for it, not a pause.
        await wait_for(lambda: app.remote.token() != old, "the link to rotate")
        with pytest.raises(ConnectionClosed) as closed:
            await asyncio.wait_for(ws.recv(), 3)
        assert closed.value.rcvd.code == UNAUTHORIZED


@pytest.mark.asyncio
async def test_turning_it_off_in_settings_stops_it_and_the_screen_answers_alone():
    app = _app(enabled=True)
    async with app.run_test(size=(110, 32)) as pilot:
        await wait_for(lambda: app.remote.server is not None, "the server to start")
        local = app.remote.local
        app.config.serve.enabled = False
        app.apply_runtime_settings()
        await wait_for(lambda: app.remote.server is None, "the server to stop")
        await pilot.pause()
        assert app.core.operator is local and "REMOTE" not in _status(app)


@pytest.mark.asyncio
async def test_turning_it_on_keeps_the_screen_drawing_and_shows_the_qr_code(monkeypatch):
    """Operator, 2026-10-06: turning it on "locked up the whole program"
    (Flet's import, seconds long, ran on the event loop), and then there
    was no QR code anywhere in sight. The import is a thread's; the
    pairing screen opens once the server is up."""
    import time

    from kissterm.ui import remote

    real = remote._preload

    def slow_preload():
        real()  # the real imports, so `start` finds them done
        time.sleep(0.6)  # and a slow disk on top

    monkeypatch.setattr(remote, "_preload", slow_preload)
    app = _app(enabled=False)
    # A configured radio, so first-run onboarding is not the screen up.
    app.config.transports = [{"name": "dw", "kind": "tcp", "host": "127.0.0.1", "port": 8001}]
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        assert app.remote.server is None and not isinstance(app.screen, RemotePairingScreen), \
            "the pairing screen opened at launch, with nothing turned on"
        loop = asyncio.get_running_loop()
        gaps, last = [], loop.time()

        async def tick():
            nonlocal last
            while True:
                await asyncio.sleep(0.02)
                gaps.append(loop.time() - last)
                last = loop.time()

        ticker = asyncio.ensure_future(tick())
        app.config.serve.enabled = True
        app.apply_runtime_settings()
        await wait_for(lambda: app.remote.server is not None, "the server to start")
        ticker.cancel()
        assert max(gaps) < 0.3, f"the event loop stalled {max(gaps):.2f}s while starting"
        await wait_for(lambda: isinstance(app.screen, RemotePairingScreen), "the pairing screen")
        await pilot.pause()
        qr = app.screen.query_one("#pairing-qr", Static)
        assert "-none" not in qr.classes, "the pairing screen came up without its QR code"


@pytest.mark.asyncio
async def test_a_paired_link_turns_on_quietly_and_settings_has_the_button():
    """Operator, 2026-10-06: a device already paired does not need the
    pairing screen each time remote access is turned on; Settings > Remote
    has a button for it instead, and only that section shows it."""
    from textual.widgets import Button

    from kissterm.serve import pairing
    from kissterm.ui.settings_pane import SettingsPane

    app = _app(enabled=False)
    app.config.transports = [{"name": "dw", "kind": "tcp", "host": "127.0.0.1", "port": 8001}]
    pairing.mark_paired(pairing.load_token())
    try:
        async with app.run_test(size=(110, 32)) as pilot:
            await pilot.pause()
            app.config.serve.enabled = True
            app.apply_runtime_settings()
            await wait_for(lambda: app.remote.server is not None, "the server to start")
            await pilot.pause()
            assert not isinstance(app.screen, RemotePairingScreen), \
                "the pairing screen opened for a link a device already uses"

            app.action_show_tab("settings")
            pane = app.query_one(SettingsPane)
            button = pane.query_one("#settings-pairing", Button)
            pane.show_section("Radio")
            await pilot.pause()
            assert not button.display
            pane.show_section("Remote")
            await pilot.pause()
            assert button.display
            await pilot.click("#settings-pairing")
            await wait_for(lambda: isinstance(app.screen, RemotePairingScreen), "the pairing screen")
            await pilot.pause()
    finally:
        pairing.paired_path().unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_a_client_signing_in_marks_the_link_paired_and_rotating_clears_it():
    from kissterm.serve import pairing

    pairing.paired_path().unlink(missing_ok=True)
    app = _app(enabled=True)
    try:
        async with app.run_test(size=(110, 32)):
            await wait_for(lambda: app.remote.server is not None, "the server to start")
            assert not app.remote.server.paired
            ws = await _client(app)
            assert app.remote.server.paired and pairing.has_paired(app.remote.token())
            app.remote.rotate()
            assert not app.remote.server.paired
            assert not pairing.has_paired(app.remote.token())
            await ws.close()
    finally:
        pairing.paired_path().unlink(missing_ok=True)
