"""Pilot-test setup shared by every file in this directory.

The pilot suite was written while Terminal was the launch tab, and most of it
exercises the Terminal pane straight after mount. Mail became the launch tab
on 2026-09-23 (`kissterm.ui.app.DEFAULT_START_TAB`); rather than edit about
130 test configs, the tests launch on Terminal unless a test asks otherwise.
`tests/pilot/test_mail_pane.py` sets `Config.start_tab = "mail"` explicitly,
and `tests/unit/test_start_tab.py` checks the real default.
"""

import pytest


@pytest.fixture(autouse=True)
def _launch_on_terminal(monkeypatch):
    import kissterm.ui.app as ui_app

    monkeypatch.setattr(ui_app, "DEFAULT_START_TAB", "terminal")
