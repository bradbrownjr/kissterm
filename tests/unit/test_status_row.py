"""The status bar's transport field: the host, not the port (operator,
2026-10-02, to make room for a job's progress)."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm.ui import app  # noqa: E402
from kissterm.ui.app import _short_peer, _without_port  # noqa: E402


@pytest.mark.parametrize(("detail", "shown"), [
    ("10.6.26.128:8001", "10.6.26.128"),
    ("10.6.26.128:8001 RECONNECTING", "10.6.26.128 RECONNECTING"),
    ("localhost:8000 (AGWPE)", "localhost (AGWPE)"),
    ("kc1jmh@ws1ec.example:22", "kc1jmh@ws1ec.example"),
    ("127.0.0.1:8300/8301 (HF)", "127.0.0.1 (HF)"),
    ("[fe80::1]:8001", "[fe80::1]"),
    # Nothing to cut, or nowhere safe to cut it.
    ("fe80::1", "fe80::1"),
    ("/dev/ttyUSB0 @ 9600", "/dev/ttyUSB0 @ 9600"),
    ("00:11:22:33:44:55 ch1 (RFCOMM)", "00:11:22:33:44:55 ch1 (RFCOMM)"),
    ("AF_AX25 radio as KC1JMH", "AF_AX25 radio as KC1JMH"),
])
def test_only_a_port_is_cut(detail, shown):
    assert _without_port(detail) == shown


@pytest.mark.parametrize(("peer", "shown"), [
    ("packet@ws1ec.mainepacketradio.org:4722", "WS1EC"),
    ("ws1ec.mainepacketradio.org", "WS1EC"),
    ("WS1EC-15", "WS1EC-15"),
    ("localhost:8010", "localhost"),
    ("10.0.0.2:23", "10.0.0.2"),
    ("[::1]:22", "[::1]"),
])
def test_a_link_peer_is_named_briefly(peer, shown):
    """Operator, 2026-10-02: "kc1uix-3 via" was all that fit."""
    assert _short_peer(peer) == shown


def test_every_field_shows_whole_on_the_operators_bar():
    """Operator, 2026-10-02: "Checking for" with "mail" cut off, and the
    link state and retry count gone, nine fields across 119 columns."""
    from rich.console import Console

    parts = ["10.6.26.128", "KC1JMH", "WS1EC-2 connected", "tx 3 rx 3 rtx 0",
             "Checking for mail", "ANSWERING", "BEACON", "APRS BEACON", "LOGGING"]
    console = Console(width=119, record=True, color_system=None)
    console.print(app._status_row(parts))
    text = console.export_text()
    assert text.count("\n") == 1, text
    for part in parts:
        assert part in text, text
