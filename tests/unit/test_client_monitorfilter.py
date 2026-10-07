"""The remote Monitor filter agrees with the terminal's, frame for frame."""

from kissterm._isolate import isolate

isolate()

import itertools  # noqa: E402

from kissterm.ax25.address import AX25Address, AX25Path  # noqa: E402
from kissterm.ax25.frame import AX25Frame, SType, UType  # noqa: E402
from kissterm.client.monitorfilter import MonitorFilter as ClientFilter  # noqa: E402
from kissterm.monitor import MonitorFilter  # noqa: E402
from kissterm.serve.wire import event  # noqa: E402
from kissterm.core import events as ev  # noqa: E402


def _frames():
    path = AX25Path(AX25Address.parse("W1AW-7"), AX25Address.parse("KC1JMH"),
                    (AX25Address.parse("WS1EC-2"),))
    return [AX25Frame.i_frame(path, 0, 0, b"Hello World"),
            AX25Frame.s_frame(path, SType.RR, 1),
            AX25Frame.u_frame(path, UType.SABM),
            AX25Frame.u_frame(path, UType.UI, info=b"beacon text")]


def test_the_two_filters_agree_on_every_frame():
    """The terminal's `MonitorFilter` and the client's, over every
    combination of the four type switches, a port, a call and a text."""
    for bits in itertools.product((True, False), repeat=4):
        kw = dict(zip(("show_supervisory", "show_unnumbered", "show_information",
                       "show_ui"), bits))
        for extra in ({}, {"ports": (1,)}, {"calls": ("w1aw-7",)}, {"calls": ("N0CALL",)},
                      {"contains": "hello"}, {"contains": "zzz"}):
            terminal, remote = MonitorFilter(**kw, **extra), ClientFilter(**kw, **extra)
            for frame in _frames():
                data = event(None, 0, ev.FrameSeen(frame, 0, False))["data"]
                assert remote.allows(data) == terminal.allows(frame, 0), (kw, extra, frame)


def test_query_splits_calls_from_text():
    f = ClientFilter()
    f.set_query("W1AW-7")
    assert f.calls == ("W1AW-7",) and f.contains == ""
    f.set_query("hello there")
    assert f.calls == () and f.contains == "hello there"
    f.set_query("")
    assert f.calls == () and f.contains == ""


def test_allows_by_type_port_call_and_text():
    base = {"kind": "I", "ui": False, "port": 1, "calls": ["W1AW-7", "KC1JMH", "WS1EC-2"],
            "text": "Hello World"}
    assert ClientFilter().allows(base)
    assert not ClientFilter(show_information=False).allows(base)
    assert not ClientFilter(show_supervisory=False).allows({**base, "kind": "S"})
    assert not ClientFilter(show_ui=False).allows({**base, "kind": "U", "ui": True})
    assert ClientFilter(show_ui=False).allows({**base, "kind": "U", "ui": False})
    assert not ClientFilter(show_unnumbered=False).allows({**base, "kind": "U", "ui": False})
    assert not ClientFilter(ports=(2,)).allows(base)
    assert ClientFilter(calls=("ws1ec-2",)).allows(base)
    assert not ClientFilter(calls=("N0CALL",)).allows(base)
    assert ClientFilter(contains="hello w").allows(base)
    assert not ClientFilter(contains="nope").allows(base)
