"""`kissterm --web-terminal` (`kissterm/webterm.py`): an opt-in with its
warning on the command line, localhost unless told otherwise."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm import webterm  # noqa: E402
from kissterm.__main__ import _build_parser  # noqa: E402


def test_off_unless_asked_and_localhost_when_asked():
    assert _build_parser().parse_args([]).web_terminal is None
    args = _build_parser().parse_args(["--web-terminal"])
    assert webterm.parse_address(args.web_terminal) == ("127.0.0.1", 8765)


@pytest.mark.parametrize(("text", "expected"), [
    ("9000", ("127.0.0.1", 9000)),
    ("0.0.0.0:9000", ("0.0.0.0", 9000)),
    ("myhost", ("myhost", 8765)),
])
def test_addresses(text, expected):
    assert webterm.parse_address(text) == expected


def test_the_warning_says_no_login_and_names_the_remote_control():
    local = webterm.warning("127.0.0.1", 8765)
    assert "no pairing link and no login" in local and "kissterm --serve" in local
    assert "ANYONE ON THE NETWORK" in webterm.warning("0.0.0.0", 8765)


def test_the_command_runs_this_kissterm_with_its_station_options():
    args = _build_parser().parse_args(
        ["--web-terminal", "--profile", "field", "--transport", "dw"])
    cmd = webterm.command(args)
    assert "-m kissterm" in cmd and "--profile field" in cmd and "--transport dw" in cmd
    assert "--web-terminal" not in cmd, "each session would start another server"


def test_the_warning_prints_before_serving(monkeypatch, capsys):
    served = []

    class FakeServer:
        def __init__(self, command, host, port, title):
            served.append((host, port))

        def serve(self):
            pass

    pytest.importorskip("textual_serve")
    import textual_serve.server

    monkeypatch.setattr(textual_serve.server, "Server", FakeServer)
    args = _build_parser().parse_args(["--web-terminal"])
    assert webterm.run(args) == 0
    assert served == [("127.0.0.1", 8765)]
    assert "no login" in capsys.readouterr().err
