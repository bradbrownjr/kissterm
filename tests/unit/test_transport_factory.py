"""The contract between what discovery writes and what a constructor accepts.

kissterm 0.1.16 shipped a first run that wrote a valid-looking config file and
then could not open it:

    Could not open transport '10.6.26.5:8001':
    TcpKissTransport.__init__() got an unexpected keyword argument 'name'

`build_transport` forwarded every config key to the constructor, and every
entry discovery writes carries `name` -- so no wizard-configured transport of
any kind could be opened. Two things let that reach a release: nothing tested
`build_transport` against an entry the wizard actually produces, and
`--doctor` had its own hand-written dispatch table, so it exercised a path the
app never took and reported the broken config healthy.

These tests are the guard for both.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from kissterm import _isolate

_isolate.isolate()

import pytest  # noqa: E402

from kissterm import doctor  # noqa: E402
from kissterm.transport import _ENTRY_ONLY_KEYS, _VALID_KINDS, build_transport  # noqa: E402
from kissterm.transport.base import Transport  # noqa: E402

#: One config entry per kind, shaped the way the wizard writes them -- which
#: means every one carries `name`, the key that broke.
ENTRIES: dict[str, dict] = {
    "serial": {"kind": "serial", "name": "/dev/ttyUSB0", "device": "/dev/ttyUSB0", "baud": 9600},
    "tcp": {"kind": "tcp", "name": "10.6.26.5:8001", "host": "10.6.26.5", "port": 8001},
    "agwpe": {"kind": "agwpe", "name": "10.6.26.3:8000", "host": "10.6.26.3", "port": 8000},
    "bluetooth": {"kind": "bluetooth", "name": "TNC3", "address": "00:11:22:33:44:55"},
    "kernel": {"kind": "kernel", "name": "ax0", "ax25_port": "ax0", "mycall": "N1ABC-1"},
    "vara": {"kind": "vara", "name": "VARA HF", "host": "127.0.0.1", "mycall": "N1ABC-1"},
    "varafm": {"kind": "varafm", "name": "VARA FM", "host": "127.0.0.1", "mycall": "N1ABC-1"},
    "mercury": {"kind": "mercury", "name": "Mercury", "host": "127.0.0.1", "mycall": "N1ABC-1"},
}


def test_every_valid_kind_has_a_worked_entry_here():
    """So a new transport kind cannot be added without being covered."""
    assert set(ENTRIES) == set(_VALID_KINDS)


@pytest.mark.parametrize("kind", sorted(ENTRIES))
def test_a_wizard_shaped_entry_builds(kind):
    transport = build_transport(ENTRIES[kind])
    assert isinstance(transport, Transport)


@pytest.mark.parametrize("kind", sorted(ENTRIES))
def test_the_config_name_wins_over_the_class_derived_one(kind):
    """`active_transport` matches on the entry's name and the status bar shows
    it, so the transport has to agree with the config or "which one am I on?"
    has two answers."""
    assert build_transport(ENTRIES[kind]).info.name == ENTRIES[kind]["name"]


def test_an_unknown_key_still_fails_loudly():
    """Stripping entry-level keys must not turn into ignoring everything --
    a typo in a real setting should still be found, not silently dropped."""
    entry = dict(ENTRIES["tcp"], hsot="typo")
    with pytest.raises(TypeError):
        build_transport(entry)


def test_doctor_builds_transports_through_the_factory():
    """The bug reached a release because --doctor took a different path and
    reported the broken config healthy. A diagnostic that does not exercise
    the real path is worse than none, because it is believed."""
    source = inspect.getsource(doctor._build_transport)
    assert "build_transport(entry)" in source
    assert "TcpKissTransport" not in source, "doctor grew its own dispatch table again"
    assert "SerialKissTransport" not in source


# ---------------------------------------------------------------------------
# The static half: what discovery writes must be constructible
# ---------------------------------------------------------------------------


def _discovery_config_literals() -> list[dict[str, set[str] | str]]:
    """Every `config={...}` dict literal discovery hands to DiscoveredDevice.

    Read statically rather than by running discovery, which would need a
    serial port, a LAN and a Bluetooth adapter. Keys and the `kind` constant
    are all this needs, and both are literals.
    """
    tree = ast.parse(Path("kissterm/discovery.py").read_text())
    found = []

    def _record(node: ast.Dict) -> None:
        keys = {
            k.value for k in node.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
        if not keys:
            return  # the deliberately empty "cannot configure this" entry
        kind = None
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value == "kind":
                kind = value.value if isinstance(value, ast.Constant) else None
        found.append({"kind": kind, "keys": keys})

    for node in ast.walk(tree):
        # Shape one: config={...} passed inline to DiscoveredDevice.
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "DiscoveredDevice":
                for keyword in node.keywords:
                    if keyword.arg == "config" and isinstance(keyword.value, ast.Dict):
                        _record(keyword.value)
        # Shape two: `config = {...}` built into a local first, then passed.
        # Both shapes exist in discovery.py and only counting the first one
        # silently skipped the TCP path -- which is the path that broke.
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if "config" in names:
                _record(node.value)
    return found


def test_discovery_actually_produces_some_config_literals():
    """If the AST walk silently found nothing, the test below proves nothing."""
    assert len(_discovery_config_literals()) >= 3


def test_every_key_discovery_writes_is_accepted_somewhere():
    """The exact contract that broke: a key discovery writes must be either an
    entry-level key that `build_transport` strips, or a real constructor
    argument. Anything else reaches `__init__` as an unexpected keyword."""
    from kissterm.transport import agwpe, bluetooth, kernel_ax25, serial_kiss, tcp_kiss, vara

    classes = {
        "serial": serial_kiss.SerialKissTransport,
        "tcp": tcp_kiss.TcpKissTransport,
        "agwpe": agwpe.AgwpeTransport,
        "bluetooth": bluetooth.BluetoothKissTransport,
        "kernel": kernel_ax25.KernelAx25Transport,
        "vara": vara.VaraHfTransport,
        "varafm": vara.VaraFmTransport,
    }

    from kissterm.discovery import _WELL_KNOWN_PORTS

    # The TCP/AGWPE path picks its kind from _WELL_KNOWN_PORTS at runtime, so
    # the literal's "kind" is a variable, not a constant. Check that entry
    # against EVERY kind that table can actually write -- which is stricter
    # than checking one, and is the real contract.
    dynamic = sorted(
        {kind for _label, kind, complete in _WELL_KNOWN_PORTS.values() if kind and complete}
    )
    assert dynamic, "no port maps to a writable kind; the check below is vacuous"

    for entry in _discovery_config_literals():
        kinds = [entry["kind"]] if entry["kind"] is not None else dynamic
        for kind in kinds:
            assert kind in classes, f"discovery writes kind {kind!r} with no class"
            accepted = set(inspect.signature(classes[kind].__init__).parameters)
            for key in entry["keys"]:
                assert key in _ENTRY_ONLY_KEYS or key in accepted, (
                    f"discovery writes {key!r} for kind {kind!r}, but "
                    f"{classes[kind].__name__}.__init__ does not accept it and "
                    f"build_transport does not strip it"
                )


def test_discovery_maps_well_known_ports_to_the_right_kind():
    """An AGWPE engine spoken to as raw KISS decodes as garbage rather than
    failing cleanly, so the port-to-kind mapping is correctness, not polish."""
    from kissterm.discovery import _WELL_KNOWN_PORTS

    assert _WELL_KNOWN_PORTS[8000][1] == "agwpe"
    assert _WELL_KNOWN_PORTS[8001][1] == "tcp"
    assert _WELL_KNOWN_PORTS[8100][1] == "tcp"
    # VARA needs a callsign and two ports; a probe knows neither.
    assert _WELL_KNOWN_PORTS[8300][2] is False
    assert _WELL_KNOWN_PORTS[8400][2] is False
    # A modem's data port is not a second device to connect to.
    assert _WELL_KNOWN_PORTS[8301][1] is None
    assert _WELL_KNOWN_PORTS[8401][1] is None
