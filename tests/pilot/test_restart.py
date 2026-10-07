"""Session > Restart kissterm (`core/restart.py`): asked first; Restart
exits the app with the restart requested, so `__main__` starts it again;
Cancel does nothing."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.dialogs import RestartScreen  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402
from tests.pilot._wait import wait_for  # noqa: E402


@pytest.mark.asyncio
@pytest.mark.parametrize("button, restarts", [("#connect-go", True), ("#connect-cancel", False)])
async def test_restart_asks_then_exits_for_a_restart(button, restarts):
    ta, tb = loopback_pair()
    await ta.open()
    config = Config(mycall="N1ABC-1")
    config.slideouts_auto_open = False
    app = KissTermApp(config, AX25Station(AX25Address.parse("N1ABC-1"), ta, LinkParams()))
    app.core.restarter.shutdown_wait = 60
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.pause()
        app.action_restart()
        await wait_for(lambda: isinstance(app.screen, RestartScreen), "the question")
        await pilot.pause()
        assert app.screen.focused.id == "connect-cancel", "Cancel is the default"
        await pilot.click(button)
        if restarts:
            await wait_for(lambda: not app.is_running, "the app to exit")
        else:
            await pilot.pause()
            assert not isinstance(app.screen, RestartScreen)
    app.core.restarter.cancel_watchdog()
    assert app.core.restarter.requested is restarts
    assert ta.sent == [], "nothing was connected, so nothing went on the air"
    await ta.close()
