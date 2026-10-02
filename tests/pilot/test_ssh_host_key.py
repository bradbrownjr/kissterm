"""First contact with an SSH server, as the operator meets it: the key's
fingerprint in a Trust/Cancel dialog with Cancel focused, Trust writes it to
the known_hosts file and the connect goes ahead, Cancel writes nothing and
fails the connect (operator, 2026-10-02). The transport is faked; the real
handshake is in tests/unit/test_ssh_transport.py."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402
from textual.widgets import Button  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.transport.base import TransportError  # noqa: E402
from kissterm.transport.ssh import UnknownHostKey  # noqa: E402
from kissterm.ui.dialogs import TrustHostKeyScreen  # noqa: E402
from tests.pilot._wait import wait_for  # noqa: E402

LINE = "[ws1ec.example.org]:4722 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample"


class _NewServer:
    """Unknown on the first connect, connected after that."""

    def __init__(self, path) -> None:
        self.path = path
        self.calls = 0

    async def connect(self):
        self.calls += 1
        if self.calls == 1:
            raise UnknownHostKey("ws1ec.example.org", 4722, self.path, "ssh-ed25519",
                                 "SHA256:abc123", LINE)
        return "session"


async def _ask(app, pilot, transport):
    task = asyncio.ensure_future(app._session_connect(transport))
    await wait_for(lambda: isinstance(app.screen, TrustHostKeyScreen), "the trust dialog")
    await pilot.pause()
    return task


@pytest.mark.asyncio
async def test_trust_saves_the_key_and_connects(tmp_path):
    path = tmp_path / "ssh_known_hosts"
    transport = _NewServer(path)
    app = KissTermApp(Config(mycall="N1ABC-1"))
    async with app.run_test(size=(100, 30)) as pilot:
        task = await _ask(app, pilot, transport)
        screen = app.screen
        assert "SHA256:abc123" in str(screen.query_one("#reminder-detail").render())
        # A stray Enter must not trust a key.
        assert app.focused is screen.query_one("#connect-cancel", Button)
        await pilot.click("#connect-go")
        assert await task == "session"
    assert transport.calls == 2
    assert path.read_text() == LINE + "\n"


@pytest.mark.asyncio
async def test_cancel_trusts_nothing(tmp_path):
    path = tmp_path / "ssh_known_hosts"
    transport = _NewServer(path)
    app = KissTermApp(Config(mycall="N1ABC-1"))
    async with app.run_test(size=(100, 30)) as pilot:
        task = await _ask(app, pilot, transport)
        await pilot.press("enter")
        with pytest.raises(TransportError, match="not trusted"):
            await task
    assert transport.calls == 1
    assert not path.exists()
