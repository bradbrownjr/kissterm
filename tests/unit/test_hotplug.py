"""Serial hotplug watching, and the guarantee that it never touches the network.

The asymmetry these tests defend: serial ports are cheap and local, so they are
polled; a network sweep is ~1500 TCP connections, so it happens only when a
human asks. A future change that "helpfully" adds a periodic rescan should fail
here.
"""

from __future__ import annotations

from kissterm import _isolate

_isolate.isolate()

import asyncio  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402

from kissterm import hotplug  # noqa: E402
from kissterm.hotplug import PortEvent, SerialPortWatcher  # noqa: E402


def _port(device, description="USB Serial", manufacturer="", vid=None, pid=None):
    return SimpleNamespace(
        device=device,
        description=description,
        manufacturer=manufacturer,
        vid=vid,
        pid=pid,
    )


class _FakePorts:
    """Stands in for `serial.tools.list_ports`, so nothing real is enumerated."""

    def __init__(self, ports):
        self.ports = list(ports)
        self.calls = 0

    def comports(self):
        self.calls += 1
        return list(self.ports)


@pytest.fixture
def fake_ports(monkeypatch):
    """Replace `comports` itself, not the module in `sys.modules`.

    `from serial.tools import list_ports` resolves through the *package
    attribute* once anything has imported it, so patching `sys.modules` only
    works when this test happens to run before any other test that touches
    pyserial. That version passed alone and failed in the full suite -- the
    worst kind of test bug, because it looks like a real regression.
    """
    fake = _FakePorts([])
    monkeypatch.setattr("serial.tools.list_ports.comports", fake.comports)
    return fake


@pytest.mark.asyncio
async def test_priming_reports_nothing_already_present(fake_ports):
    """Ports present at launch are not news and must not produce events."""
    fake_ports.ports = [_port("/dev/ttyUSB0"), _port("/dev/ttyUSB1")]
    seen: list[PortEvent] = []
    w = SerialPortWatcher(on_event=seen.append)
    await w.prime()
    assert seen == []
    assert await w.poll() == []
    assert seen == []


@pytest.mark.asyncio
async def test_detects_a_device_being_plugged_in(fake_ports):
    seen: list[PortEvent] = []
    w = SerialPortWatcher(on_event=seen.append)
    await w.prime()
    fake_ports.ports = [_port("/dev/ttyUSB0", "Mobilinkd TNC3")]
    events = await w.poll()
    assert len(events) == 1
    assert events[0].action == "added"
    assert events[0].device == "/dev/ttyUSB0"
    assert seen == events


@pytest.mark.asyncio
async def test_detects_a_device_being_unplugged(fake_ports):
    fake_ports.ports = [_port("/dev/ttyUSB0")]
    w = SerialPortWatcher()
    await w.prime()
    fake_ports.ports = []
    events = await w.poll()
    assert [e.action for e in events] == ["removed"]
    assert events[0].device == "/dev/ttyUSB0"


@pytest.mark.asyncio
async def test_scoring_matches_discovery(fake_ports):
    """One opinion about what looks like a TNC, not two."""
    w = SerialPortWatcher()
    await w.prime()
    fake_ports.ports = [
        _port("/dev/ttyUSB0", "Mobilinkd TNC3"),
        _port("/dev/ttyACM9", "Broadcom Bluetooth modem"),
    ]
    by_device = {e.device: e for e in await w.poll()}
    assert by_device["/dev/ttyUSB0"].likely_tnc, "a named TNC must be flagged"
    assert not by_device["/dev/ttyACM9"].likely_tnc, "a modem must not be"


@pytest.mark.asyncio
async def test_a_bad_enumeration_never_raises(monkeypatch):
    def boom():
        raise OSError("device busy")

    monkeypatch.setattr("serial.tools.list_ports.comports", boom)
    w = SerialPortWatcher()
    await w.prime()
    assert await w.poll() == []


@pytest.mark.asyncio
async def test_a_raising_handler_does_not_stop_the_others(fake_ports):
    good: list[PortEvent] = []

    def bad(_event):
        raise RuntimeError("handler blew up")

    w = SerialPortWatcher()
    w.subscribe(bad)
    w.subscribe(good.append)
    await w.prime()
    fake_ports.ports = [_port("/dev/ttyUSB0", "Mobilinkd TNC3")]
    await w.poll()
    assert len(good) == 1, "one bad handler suppressed the rest"


@pytest.mark.asyncio
async def test_polling_loop_runs_on_its_interval(fake_ports):
    w = SerialPortWatcher(interval=0.05)
    await w.prime()
    w.start()
    await asyncio.sleep(0.22)
    w.stop()
    assert w.polls >= 3, f"only polled {w.polls} times"


def test_hotplug_never_touches_the_network():
    """A periodic network sweep is ~1500 TCP connections. Not on a timer.

    Asserted against the source rather than behaviour, because the failure this
    guards against is someone adding a convenience rescan later -- which would
    look perfectly reasonable in a diff and be antisocial on a club network.
    """
    import inspect

    source = inspect.getsource(hotplug)
    for forbidden in (
        "discover_network",
        "discover_all",
        "open_connection",
        "socket",
        "discover_bluetooth",
    ):
        assert forbidden not in source, (
            f"hotplug.py references {forbidden!r}; this module must stay local "
            f"and must never scan the network on a timer"
        )
