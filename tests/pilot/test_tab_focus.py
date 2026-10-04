"""A tab opened by a click is focused as one opened by its key.

Clicking a tab's label left focus on the tab row: on Bulletins G and I
were missing from the Footer until the list was clicked, and on Terminal
typing went nowhere (operator, 2026-10-04). `KissTermApp._focus_tab_target`
now serves both ways in.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from tests.pilot.test_get_mail import _app  # noqa: E402

#: The tab, its key, and the widget that should hold focus.
TABS = [
    ("mail", "f2", "MessageList"),
    ("bulletins", "f3", "MessageList"),
    ("files", "f4", "MessageList"),
    ("terminal", "f5", "_SendInput"),
    ("aprs", "f6", "WordInput"),
    ("monitor", "f8", "Input"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("how", ["key", "click"])
async def test_each_tab_focuses_its_widget_however_it_is_opened(tmp_path, how):
    app, station, _tb = await _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        for tab, key, widget in TABS:
            await pilot.press("f7")  # from Heard, which focuses nothing
            await pilot.pause()
            if how == "key":
                await pilot.press(key)
            else:
                await pilot.click(f"#--content-tab-{tab}")
            await pilot.pause()
            await pilot.pause()
            assert type(app.focused).__name__ == widget, (tab, app.focused)
            if tab == "bulletins":
                assert "g" in app.screen.active_bindings
    station.close()
