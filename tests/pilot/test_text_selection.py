"""Mouse selection and Ctrl+C copy in the scrollbacks (`kissterm/ui/wraplog.py`).

Reported 2026-09-24: text in the terminal pane could not be highlighted to
copy it. `RichLog` has no selection support; `WrapLog` adds it.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402
from rich.text import Text  # noqa: E402

from kissterm.config import Config  # noqa: E402
from kissterm.ui.app import KissTermApp  # noqa: E402
from kissterm.ui.terminal_pane import TerminalPane  # noqa: E402
from kissterm.ui.wraplog import WrapLog  # noqa: E402


@pytest.mark.asyncio
async def test_drag_in_the_terminal_scrollback_selects_and_ctrl_c_copies():
    config = Config(mycall="KC1JMH")
    config.transports = [{"name": "tnc", "kind": "tcp", "host": "127.0.0.1", "port": 8001}]
    app = KissTermApp(config)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        log = app.query_one(TerminalPane).query(WrapLog).first()
        log.clear()
        log.write(Text("Message #2578 Killed", style="red"))
        log.write(Text("de WS1EC#>"))
        await pilot.pause()
        # Offsets are from the widget's edge; the text starts inside its border.
        dx = log.content_region.x - log.region.x
        dy = log.content_region.y - log.region.y
        await pilot.mouse_down(log, offset=(dx, dy))
        await pilot.hover(log, offset=(dx + 7, dy + 1))
        await pilot.mouse_up(log, offset=(dx + 7, dy + 1))
        await pilot.pause()
        assert app.screen.get_selected_text() == "Message #2578 Killed\nde WS1EC"
        # Copied on release, the way a copy-on-highlight terminal does.
        assert app.clipboard == "Message #2578 Killed\nde WS1EC"
        app._clipboard = ""
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert app.clipboard == "Message #2578 Killed\nde WS1EC"
