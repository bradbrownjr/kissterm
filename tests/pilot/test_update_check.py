"""The update check as the operator meets it: a toast (never a Terminal line,
which an operator on Mail would not see), an Update dialog that names the command, and a refusal while anything is
under way. The network and the upgrade command are faked throughout; a test
mounting the app never checks GitHub (`check_updates` defaults off)."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402
from textual.widgets import Button  # noqa: E402

from kissterm import updater  # noqa: E402
from kissterm.app import KissTermApp  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.dialogs import UpdateScreen  # noqa: E402
from kissterm.ui.terminal_pane import TerminalPane  # noqa: E402
from tests.pilot._wait import wait_for  # noqa: E402

NEWER = "99.0.0"
PIPX = updater.InstallMethod("pipx", ("pipx", "upgrade", "kissterm"), "pipx upgrade kissterm")


def _log_text(app) -> str:
    log = app.query_one(TerminalPane).query_one("#session-log")
    return "\n".join(str(line) for line in log.lines)


def _plain(widget) -> str:
    from textual.geometry import Region

    size = widget.outer_size
    region = Region(0, 0, size.width or 200, size.height or 5)
    return "\n".join(strip.text for strip in widget.render_lines(region))


def _app(latest: str | None = NEWER) -> KissTermApp:
    app = KissTermApp(Config(mycall="N1ABC-1"))
    app._fetch_latest = lambda: latest
    return app


@pytest.mark.asyncio
async def test_a_test_app_never_checks_on_its_own():
    app = KissTermApp(Config(mycall="N1ABC-1"))
    calls = []
    app._fetch_latest = lambda: calls.append(1)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        assert app._check_updates is False and not calls


@pytest.mark.asyncio
async def test_a_newer_version_is_a_toast_once_not_a_terminal_line():
    app = _app()
    toasts = []
    async with app.run_test(size=(140, 32)) as pilot:
        await pilot.pause()
        real_notify = app.notify
        app.notify = lambda msg, **kw: (toasts.append(msg), real_notify(msg, **kw))
        app._update_check_worker(False)
        await wait_for(lambda: app._update_available == NEWER, "the check to finish")
        await pilot.pause()
        assert [t for t in toasts if f"kissterm {NEWER} is available" in t]
        assert "is available" not in _log_text(app)
        assert NEWER not in _plain(app.query_one("#status-bar"))
        # The launch check never pushes a dialog.
        assert not isinstance(app.screen, UpdateScreen)
        # Heard again (the cached answer next launch): not toasted twice.
        app._on_update_result(NEWER, False)
        assert sum("is available" in t for t in toasts) == 1


@pytest.mark.asyncio
async def test_current_or_unreachable_says_nothing_at_launch():
    for latest in (None, "0.0.1"):
        app = _app(latest)
        async with app.run_test(size=(110, 32)) as pilot:
            await pilot.pause()
            toasts = []
            app.notify = lambda msg, **kw: toasts.append(msg)
            app._on_update_result(latest, False)
            await pilot.pause()
            assert app._update_available is None and not toasts


@pytest.mark.asyncio
async def test_update_now_runs_the_named_command_and_asks_for_a_restart(monkeypatch):
    monkeypatch.setattr(updater, "detect_install", lambda: PIPX)
    ran = []

    def fake_upgrade(method):
        ran.append(method.command)
        return updater.UpgradeResult(True, NEWER, "upgraded")

    monkeypatch.setattr(updater, "run_upgrade", fake_upgrade)
    app = _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        app.action_check_updates()
        await wait_for(lambda: isinstance(app.screen, UpdateScreen), "the Update dialog")
        await pilot.pause()
        assert "pipx upgrade kissterm" in _plain(app.screen.query_one("#reminder-detail"))
        toasts = []
        real_notify = app.notify
        app.notify = lambda msg, **kw: (toasts.append(msg), real_notify(msg, **kw))
        await pilot.click("#connect-go")
        await wait_for(lambda: ran, "the upgrade to run")
        await wait_for(lambda: any("is installed" in t for t in toasts), "the restart toast")
        assert "is installed" not in _log_text(app)
        assert ran == [PIPX.command]
        assert app._update_available is None


@pytest.mark.asyncio
async def test_no_update_while_something_is_under_way(monkeypatch):
    monkeypatch.setattr(updater, "detect_install", lambda: PIPX)
    monkeypatch.setattr(
        updater, "run_upgrade", lambda m: pytest.fail("upgraded while busy")
    )
    app = _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        app._activity = "Send/Receive"
        app.action_check_updates()
        await wait_for(lambda: isinstance(app.screen, UpdateScreen), "the Update dialog")
        await pilot.pause()
        assert not app.screen.query("#connect-go"), "Update offered while busy"
        assert "Not now" in _plain(app.screen.query_one("#reminder-detail"))
        assert app.screen.query_one("#connect-cancel", Button).label.plain == "Close"
        await pilot.click("#connect-cancel")
        await pilot.pause()


@pytest.mark.asyncio
async def test_a_source_checkout_is_told_to_git_pull(monkeypatch):
    monkeypatch.setattr(
        updater, "detect_install",
        lambda: updater.InstallMethod("source", None, "This is a source checkout; update it with git pull there."),
    )
    app = _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        app.action_check_updates()
        await wait_for(lambda: isinstance(app.screen, UpdateScreen), "the Update dialog")
        await pilot.pause()
        assert not app.screen.query("#connect-go")
        assert "git pull" in _plain(app.screen.query_one("#reminder-detail"))
        await pilot.click("#connect-cancel")
        await pilot.pause()
