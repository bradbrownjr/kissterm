"""Unit tests for `kissterm.config` and the `kissterm.discovery` scoring heuristics.

`kissterm._isolate.isolate()` is called below, before any other `kissterm`
import, so that even a test that forgets to pass an explicit `path=` to
`load_config`/`save_config` cannot land on a real user's config directory.
See the CRITICAL SAFETY RULE in `kissterm/config.py` and the docstring of
`kissterm/_isolate.py` for why that ordering is load-bearing, not
decorative.

No real I/O happens against hardware or the network anywhere in this file:
`serial.tools.list_ports.comports` is monkeypatched with fabricated port
data for the discovery-scoring tests, and every config test reads/writes
only files under pytest's `tmp_path`.
"""

from __future__ import annotations

import asyncio
import dataclasses
import tomllib
from pathlib import Path

import pytest

from kissterm import _isolate

# Must happen before any other `kissterm` import -- see module docstring.
_isolate.isolate()

from kissterm import config as kconfig  # noqa: E402
from kissterm import discovery  # noqa: E402


# ---------------------------------------------------------------------------
# load_config: defaults, malformed files, invalid callsigns
# ---------------------------------------------------------------------------


def test_defaults_load_with_no_file(tmp_path):
    cfg = kconfig.load_config(path=tmp_path / "does-not-exist.toml")

    assert cfg.warnings == []
    assert cfg.mycall == ""
    assert cfg.mycall_aliases == []
    assert cfg.transports == []
    assert cfg.active_transport == ""
    assert cfg.paclen == 256
    assert cfg.window == 4
    assert cfg.retries == 10
    assert cfg.t1 == 3.0
    assert cfg.t2 == 3.0
    assert cfg.t3 == 300.0
    assert cfg.monitor_filter == ""
    assert cfg.log_dir == ""
    assert cfg.theme == "tokyo-night"
    assert cfg.ascii_safe is False
    assert cfg.aprs.enabled is False
    assert cfg.aprs.path == "WIDE1-1,WIDE2-1"
    assert cfg.autoconnect == []


def test_malformed_toml_yields_defaults_and_warnings(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("this is [not valid TOML at all = \n\n[[[", encoding="utf-8")

    cfg = kconfig.load_config(path=path)  # must not raise

    assert cfg.mycall == ""
    assert cfg.paclen == 256  # defaults intact
    assert len(cfg.warnings) >= 1
    assert "malformed" in cfg.warnings[0].lower()


def test_missing_readable_dir_does_not_raise(tmp_path):
    # A path whose parent doesn't exist should just be treated as "no file".
    cfg = kconfig.load_config(path=tmp_path / "nested" / "config.toml")
    assert cfg.warnings == []
    assert cfg.mycall == ""


def test_invalid_callsign_is_a_warning_not_an_exception(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        'mycall = "THIS-CALLSIGN-IS-WAY-TOO-LONG"\n'
        'mycall_aliases = ["ALSO-WAY-TOO-LONG-TO-BE-VALID", "N0CALL-2"]\n',
        encoding="utf-8",
    )

    cfg = kconfig.load_config(path=path)  # must not raise

    assert cfg.mycall == ""
    assert cfg.mycall_aliases == ["N0CALL-2"]  # the valid one survives
    assert any("callsign" in w.lower() for w in cfg.warnings)


def test_window_out_of_range_is_clamped_with_warning(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("window = 12\n", encoding="utf-8")

    cfg = kconfig.load_config(path=path)

    assert cfg.window == 7
    assert any("window" in w.lower() for w in cfg.warnings)


def test_wrong_type_field_falls_back_to_default(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('paclen = "not a number"\nascii_safe = "yes"\n', encoding="utf-8")

    cfg = kconfig.load_config(path=path)

    assert cfg.paclen == 256
    assert cfg.ascii_safe is False
    assert len(cfg.warnings) >= 2


def test_non_table_transport_entries_are_dropped(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('transports = ["not-a-table", 42]\n', encoding="utf-8")

    cfg = kconfig.load_config(path=path)

    assert cfg.transports == []
    assert any("transports" in w.lower() for w in cfg.warnings)


# ---------------------------------------------------------------------------
# save_config: round-trip, atomicity
# ---------------------------------------------------------------------------


def _fully_populated_config() -> kconfig.Config:
    cfg = kconfig.Config()
    cfg.mycall = "N0CALL-1"
    cfg.mycall_aliases = ["N0CALL-2", "N0CALL-3"]
    cfg.transports = [
        {"name": "direwolf", "kind": "tcp", "host": "127.0.0.1", "port": 8001},
        {"name": "kantronics", "kind": "serial", "device": "/dev/ttyUSB0", "baud": 9600},
    ]
    cfg.active_transport = "direwolf"
    cfg.paclen = 128
    cfg.window = 7
    cfg.retries = 5
    cfg.t1 = 4.5
    cfg.t2 = 1.5
    cfg.t3 = 120.0
    cfg.monitor_filter = "APRS"
    cfg.log_dir = "/tmp/kissterm-logs"
    cfg.theme = "solarized"
    cfg.ascii_safe = True
    cfg.aprs = kconfig.AprsConfig(
        enabled=True,
        beacon_interval_minutes=15,
        symbol="/-",
        latitude=41.7,
        longitude=-72.7,
        comment="test station",
        path="WIDE2-1",
    )
    cfg.autoconnect = [{"target": "W1AW-1", "path": "WIDE1-1", "transport": "direwolf"}]
    cfg.credentials = [{"name": "Personal BBS login", "text": "CLYDE\nMYPASS"}]
    return cfg


def test_save_load_round_trips_every_field(tmp_path):
    path = tmp_path / "config.toml"
    original = _fully_populated_config()

    kconfig.save_config(original, path=path)
    loaded = kconfig.load_config(path=path)

    assert loaded.warnings == []
    assert loaded.mycall == original.mycall
    assert loaded.mycall_aliases == original.mycall_aliases
    assert loaded.transports == original.transports
    assert loaded.active_transport == original.active_transport
    assert loaded.paclen == original.paclen
    assert loaded.window == original.window
    assert loaded.retries == original.retries
    assert loaded.t1 == original.t1
    assert loaded.t2 == original.t2
    assert loaded.t3 == original.t3
    assert loaded.monitor_filter == original.monitor_filter
    assert loaded.log_dir == original.log_dir
    assert loaded.theme == original.theme
    assert loaded.ascii_safe == original.ascii_safe
    assert loaded.aprs == original.aprs
    assert loaded.autoconnect == original.autoconnect
    assert loaded.credentials == original.credentials


def test_atomic_save_leaves_no_temp_file_behind(tmp_path):
    path = tmp_path / "config.toml"
    kconfig.save_config(_fully_populated_config(), path=path)

    entries = sorted(p.name for p in tmp_path.iterdir())
    assert entries == ["config.toml"]
    assert not list(tmp_path.glob(".config-*"))


def test_save_creates_missing_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "config.toml"
    kconfig.save_config(_fully_populated_config(), path=path)

    assert path.exists()
    loaded = kconfig.load_config(path=path)
    assert loaded.mycall == "N0CALL-1"


# ---------------------------------------------------------------------------
# discovery.py: serial scoring heuristics (fabricated comports() data only)
# ---------------------------------------------------------------------------


class _FakePort:
    def __init__(self, device, description="", manufacturer="", vid=None, pid=None):
        self.device = device
        self.description = description
        self.manufacturer = manufacturer
        self.vid = vid
        self.pid = pid


def test_discover_serial_scores_known_tnc_highest(monkeypatch):
    fake_ports = [
        _FakePort("/dev/ttyACM0", description="Mobilinkd TNC3", manufacturer="Mobilinkd LLC"),
        _FakePort("/dev/ttyUSB0", description="FTDI FT232R USB UART", vid=0x0403, pid=0x6001),
        _FakePort("/dev/ttyUSB1", description="USB Serial Device"),
        _FakePort("/dev/rfcomm0", description="Standard Bluetooth Serial over Link"),
    ]

    import serial.tools.list_ports as list_ports

    monkeypatch.setattr(list_ports, "comports", lambda: fake_ports)

    results = asyncio.run(discovery.discover_serial())

    by_device = {d.label: d for d in results}
    assert by_device["/dev/ttyACM0"].confidence == pytest.approx(0.9)
    assert by_device["/dev/ttyUSB0"].confidence == pytest.approx(0.5)
    assert by_device["/dev/ttyUSB1"].confidence == pytest.approx(0.3)
    assert by_device["/dev/rfcomm0"].confidence == pytest.approx(0.1)

    # Highest confidence first.
    assert [d.label for d in results] == [
        "/dev/ttyACM0",
        "/dev/ttyUSB0",
        "/dev/ttyUSB1",
        "/dev/rfcomm0",
    ]

    # Every result must carry a config dict shaped like a transports entry.
    for device in results:
        assert device.config["kind"] == "serial"
        assert device.config["device"] == device.label


def test_discover_serial_returns_empty_when_no_ports(monkeypatch):
    import serial.tools.list_ports as list_ports

    monkeypatch.setattr(list_ports, "comports", lambda: [])

    results = asyncio.run(discovery.discover_serial())

    assert results == []


def test_score_serial_port_recognizes_known_brands_by_substring():
    confidence, note = discovery._score_serial_port("Kantronics KPC3+", "", None, None)
    assert confidence == pytest.approx(0.9)
    assert "kantronics" in note.lower()


def test_score_serial_port_unknown_device_gets_middling_score():
    confidence, _note = discovery._score_serial_port("Generic Widget", "Acme", None, None)
    assert confidence == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# Sequence-number mode. The window ceiling scales with it -- hard-coding 7
# silently capped every extended link at a modulo-8 window, which looks like
# poor throughput rather than a config bug.
# ---------------------------------------------------------------------------


def test_modulo_defaults_to_8():
    assert kconfig.Config().modulo == 8


def test_modulo_accepts_only_8_and_128(tmp_path):
    for value, expected, warns in ((8, 8, False), (128, 128, False), (16, 8, True), ("x", 8, True)):
        path = tmp_path / f"m{value}.toml"
        path.write_text(f"modulo = {value!r}\n" if isinstance(value, str) else f"modulo = {value}\n")
        cfg = kconfig.load_config(path)
        assert cfg.modulo == expected, f"modulo={value!r} gave {cfg.modulo}"
        assert bool(cfg.warnings) is warns


def test_window_ceiling_follows_modulo(tmp_path):
    path = tmp_path / "w.toml"
    path.write_text("modulo = 8\nwindow = 64\n")
    cfg = kconfig.load_config(path)
    assert cfg.window == 7, "modulo-8 must cap k at 7"
    assert cfg.warnings

    path.write_text("modulo = 128\nwindow = 64\n")
    cfg = kconfig.load_config(path)
    assert cfg.window == 64, "modulo-128 must allow a window of 64"
    assert not cfg.warnings


def test_modulo_survives_a_round_trip(tmp_path):
    path = tmp_path / "rt.toml"
    cfg = kconfig.Config(mycall="N1ABC-1", modulo=128, window=32)
    kconfig.save_config(cfg, path)
    back = kconfig.load_config(path)
    assert (back.modulo, back.window) == (128, 32)


# ---------------------------------------------------------------------------
# TOML escaping. A write path that corrupts the file it just wrote is worse
# than one that raises: load_config() is deliberately forgiving, so a broken
# file silently reverts EVERY setting to its default.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "carriage\rreturn",       # connect_banner is CR-separated; packet is
        "new\nline",
        "tab\tseparated",
        'quote"inside',
        "back\\slash",
        "bell\x07and\x00nul",
        "form\ffeed",
        "delete\x7fchar",
        "everything\r\n\t\"\\\x01",
    ],
)
def test_control_characters_survive_a_round_trip(tmp_path, value):
    path = tmp_path / "esc.toml"
    cfg = kconfig.Config(mycall="N1ABC-1", connect_banner=value, paclen=77)
    kconfig.save_config(cfg, path)
    back = kconfig.load_config(path)
    assert not back.warnings, f"file did not parse: {back.warnings}"
    assert back.connect_banner == value
    # The real damage was collateral: an unparseable file reverts everything.
    assert back.paclen == 77, "an unparseable file silently reset other settings"


def test_a_banner_with_a_carriage_return_does_not_corrupt_the_file(tmp_path):
    """The specific regression: the default banner is CR-separated."""
    path = tmp_path / "banner.toml"
    cfg = kconfig.Config(mycall="N1ABC-1", modulo=128, window=32)
    assert "\r" in cfg.connect_banner, "default banner should be CR-separated"
    kconfig.save_config(cfg, path)
    back = kconfig.load_config(path)
    assert (back.modulo, back.window) == (128, 32)


def test_answering_is_off_by_default():
    """Answering is unattended transmission under the operator's callsign."""
    assert kconfig.Config().accept_incoming is False


def test_accept_incoming_round_trips(tmp_path):
    path = tmp_path / "ai.toml"
    kconfig.save_config(kconfig.Config(mycall="N1ABC-1", accept_incoming=True), path)
    assert kconfig.load_config(path).accept_incoming is True


# ---------------------------------------------------------------------------
# Clock toggles, and migration from the `clock_source` enum they replaced.
# Silently reverting someone's clock to defaults because a key was renamed is
# exactly the surprise load_config exists to avoid.
# ---------------------------------------------------------------------------


def test_local_time_is_on_by_default_and_utc_is_not():
    cfg = kconfig.Config()
    assert cfg.show_local_time is True
    assert cfg.show_utc_time is False
    assert cfg.show_date is False


def test_clock_toggles_round_trip(tmp_path):
    path = tmp_path / "clock.toml"
    cfg = kconfig.Config(
        mycall="N1ABC-1", show_local_time=False, show_utc_time=True, show_date=True
    )
    kconfig.save_config(cfg, path)
    back = kconfig.load_config(path)
    assert (back.show_local_time, back.show_utc_time, back.show_date) == (False, True, True)


@pytest.mark.parametrize(
    "legacy,expected",
    [("local", (True, False)), ("utc", (False, True)), ("both", (True, True))],
)
def test_legacy_clock_source_is_migrated_not_ignored(tmp_path, legacy, expected):
    path = tmp_path / "legacy.toml"
    path.write_text(f'clock_source = "{legacy}"\n')
    cfg = kconfig.load_config(path)
    assert (cfg.show_local_time, cfg.show_utc_time) == expected
    assert any("obsolete" in w for w in cfg.warnings), cfg.warnings


def test_new_keys_win_over_a_leftover_legacy_one(tmp_path):
    path = tmp_path / "mixed.toml"
    path.write_text('clock_source = "both"\nshow_local_time = false\nshow_utc_time = true\n')
    cfg = kconfig.load_config(path)
    assert (cfg.show_local_time, cfg.show_utc_time) == (False, True)


def test_an_unrecognised_legacy_value_falls_back_to_defaults(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text('clock_source = "gmt"\n')
    cfg = kconfig.load_config(path)
    assert (cfg.show_local_time, cfg.show_utc_time) == (True, False)
    assert cfg.warnings


# ---------------------------------------------------------------------------
# Doctor diagnostics must not report problems that are not problems -- a
# check that cries wolf gets ignored at the moment it matters.
# ---------------------------------------------------------------------------


def test_only_one_async_serial_backend_is_required():
    """They are alternatives. With the preferred one installed, the absence
    of the fallback is not a finding."""
    from kissterm import doctor

    checks = doctor._check_optional_deps()
    backend = [c for c in checks if c.name == "serial async backend"]
    assert len(backend) == 1, "the backends should be one check, not one each"
    if doctor._module_present("serial_asyncio_fast") or doctor._module_present(
        "serial_asyncio"
    ):
        assert backend[0].status == "ok"


def test_unimplemented_optional_deps_are_skipped_not_warned():
    """Telling someone to install bleak to 'unlock' a stub sends them
    installing a package and then wondering why nothing works."""
    from kissterm import doctor

    checks = {c.name: c for c in doctor._check_optional_deps()}
    bleak = checks["dependency: bleak"]
    assert bleak.status == "skip"
    assert not bleak.remedy, "a skipped check must not tell the user to install it"


# ---------------------------------------------------------------------------
# config.toml.example is documentation that has to actually work
# ---------------------------------------------------------------------------


def test_example_config_loads_with_no_warnings():
    """The file we tell people to copy must be a valid config.

    `load_config` never raises, so a broken example would otherwise fail
    silently -- which is exactly what happened: five settings documented
    after the [custom_theme] header were read as custom-theme keys and
    discarded, and nothing anywhere said so.
    """
    example = Path(__file__).resolve().parents[2] / "config.toml.example"
    cfg = kconfig.load_config(example)
    assert cfg.warnings == [], cfg.warnings


def test_every_top_level_setting_in_the_example_is_actually_top_level():
    """TOML puts a bare key under the last [table] header above it.

    Any top-level `Config` field documented below the first table header is
    silently swallowed by that table. This test compares what the example
    file parses to as top-level against what it appears to document.
    """
    example = Path(__file__).resolve().parents[2] / "config.toml.example"
    text = example.read_text()
    with example.open("rb") as fh:
        parsed = tomllib.load(fh)

    documented = {
        line.split("=", 1)[0].strip()
        for line in text.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    top_level_fields = {f.name for f in dataclasses.fields(kconfig.Config)}
    nested = {"warnings"}

    for name in sorted(documented & top_level_fields - nested):
        assert name in parsed, (
            f"{name!r} is documented in config.toml.example but parses as a "
            f"key of some [table] instead of top-level -- move it above the "
            f"first table header."
        )
