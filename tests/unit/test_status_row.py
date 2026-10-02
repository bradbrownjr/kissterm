"""The status bar's transport field: the host, not the port (operator,
2026-10-02, to make room for a job's progress)."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm.ui.app import _without_port  # noqa: E402


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
