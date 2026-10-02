"""A saved login's password never reaches the Terminal or a transcript
(operator's WS1EC SSH session, 2026-10-02: it was in the transcript)."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

from kissterm.config import Config, login_text  # noqa: E402
from kissterm.ui.app import KissTermApp  # noqa: E402


def test_a_saved_password_line_is_masked_and_nothing_else():
    config = Config(mycall="N1ABC")
    config.credentials = [{"name": "WS1EC SSH login", "username": "N1ABC", "text": "YXVFFC"}]
    app = KissTermApp(config, station=None)
    username, password = login_text(config, "WS1EC SSH login").splitlines()
    assert app._masked(password) == "********"
    assert app._masked(username) == "N1ABC"
    assert app._masked("routes") == "routes"
    assert app._masked("") == ""
