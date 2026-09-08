"""herdr's notification CLI is optional and external -- this only proves
kissterm's own side: detection is conservative, and a subprocess failure of
any kind degrades to "did not notify", never an exception out of a
background task (AGENTS.md sec. 7)."""

from __future__ import annotations

import pytest

from kissterm import desktop_notify


def test_not_present_without_the_binary(monkeypatch):
    monkeypatch.setattr(desktop_notify, "_HERDR_BIN", None)
    monkeypatch.setenv("HERDR_ENV", "1")
    assert desktop_notify.herdr_present() is False


def test_not_present_without_the_env_marker(monkeypatch):
    """The binary merely existing on PATH is not enough -- kissterm must not
    pop notifications into a herdr session it was not actually launched
    under."""
    monkeypatch.setattr(desktop_notify, "_HERDR_BIN", "/usr/bin/herdr")
    monkeypatch.delenv("HERDR_ENV", raising=False)
    assert desktop_notify.herdr_present() is False


def test_present_with_both(monkeypatch):
    monkeypatch.setattr(desktop_notify, "_HERDR_BIN", "/usr/bin/herdr")
    monkeypatch.setenv("HERDR_ENV", "1")
    assert desktop_notify.herdr_present() is True


@pytest.mark.asyncio
async def test_notify_does_nothing_when_herdr_is_absent(monkeypatch):
    monkeypatch.setattr(desktop_notify, "_HERDR_BIN", None)

    async def _boom(*a, **kw):
        raise AssertionError("must not spawn a subprocess when herdr is absent")

    monkeypatch.setattr(desktop_notify.asyncio, "create_subprocess_exec", _boom)
    assert await desktop_notify.notify("title", "body") is False


class _FakeProcess:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode

    async def wait(self) -> int:
        return self.returncode


@pytest.mark.asyncio
async def test_notify_reports_success(monkeypatch):
    monkeypatch.setattr(desktop_notify, "_HERDR_BIN", "/usr/bin/herdr")
    monkeypatch.setenv("HERDR_ENV", "1")
    seen = {}

    async def _fake_exec(*args, **kw):
        seen["args"] = args
        return _FakeProcess(0)

    monkeypatch.setattr(desktop_notify.asyncio, "create_subprocess_exec", _fake_exec)
    ok = await desktop_notify.notify("Mail waiting", "heard on the channel", sound="request")
    assert ok is True
    assert seen["args"][:3] == ("/usr/bin/herdr", "notification", "show")
    assert "Mail waiting" in seen["args"]
    assert "--body" in seen["args"]
    assert "--sound" in seen["args"]


@pytest.mark.asyncio
async def test_notify_swallows_a_missing_binary_at_call_time(monkeypatch):
    """The PATH lookup happened at import time; if the binary vanished
    between then and now, that is still just "did not notify"."""
    monkeypatch.setattr(desktop_notify, "_HERDR_BIN", "/usr/bin/herdr")
    monkeypatch.setenv("HERDR_ENV", "1")

    async def _raise(*args, **kw):
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(desktop_notify.asyncio, "create_subprocess_exec", _raise)
    assert await desktop_notify.notify("title") is False


@pytest.mark.asyncio
async def test_notify_swallows_a_timeout(monkeypatch):
    monkeypatch.setattr(desktop_notify, "_HERDR_BIN", "/usr/bin/herdr")
    monkeypatch.setenv("HERDR_ENV", "1")

    class _HangingProcess:
        returncode = None

        async def wait(self):
            import asyncio

            await asyncio.sleep(10)

    async def _fake_exec(*args, **kw):
        return _HangingProcess()

    monkeypatch.setattr(desktop_notify.asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(desktop_notify, "_TIMEOUT", 0.05)
    assert await desktop_notify.notify("title") is False
