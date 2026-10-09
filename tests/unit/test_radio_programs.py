"""Programs and Rigs entries: validated, saved, and refused while in use."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from kissterm import _isolate

_isolate.isolate()

from kissterm.config import Config  # noqa: E402
from kissterm.core.radio import Radio  # noqa: E402


def _radio():
    saved = []
    core = SimpleNamespace(
        config=Config(),
        save_config=lambda: saved.append(1) or True,
        events=SimpleNamespace(publish=lambda event: None),
    )
    return Radio(core), core, saved


def _program(**over):
    # Saving checks the file is a real executable (ROADMAP P3a decision 1).
    entry = {"name": "dw", "preset": "direwolf", "path": sys.executable}
    entry.update(over)
    return entry


def test_a_program_is_saved_with_typed_defaults():
    radio, core, saved = _radio()
    assert radio.save_program(_program(args="-t 0")) == ""
    entry = core.config.programs[0]
    assert entry["start_timeout"] == 30 and entry["stop_on_exit"] is True
    assert entry["wine"] is False and entry["args"] == "-t 0"
    assert saved


def test_a_program_needs_a_name_a_path_and_a_known_preset():
    radio, core, _ = _radio()
    assert "Name" in radio.save_program(_program(name=""))
    assert "required" in radio.save_program(_program(path=""))
    assert "not a file" in radio.save_program(_program(path="/no/such/file"))
    assert "not an executable" in radio.save_program(_program(path=__file__))
    assert "Not a known" in radio.save_program(_program(preset="nope"))
    assert core.config.programs == []


def test_a_name_in_use_is_refused_but_an_edit_may_keep_its_own():
    radio, core, _ = _radio()
    radio.save_program(_program())
    assert "already in use" in radio.save_program(_program(args="-x"))
    assert radio.save_program(_program(args="-x"), original="dw") == ""
    assert [p["args"] for p in core.config.programs] == ["-x"]


def test_a_program_a_transport_uses_cannot_be_forgotten_and_renames_follow():
    radio, core, _ = _radio()
    radio.save_program(_program())
    core.config.transports = [{"name": "kiss", "kind": "tcp", "host": "h", "port": 8001,
                               "program": "dw"}]
    assert "still used by kiss" in radio.forget_program("dw")
    assert radio.save_program(_program(name="dw2"), original="dw") == ""
    assert core.config.transports[0]["program"] == "dw2"
    core.config.transports = []
    assert radio.forget_program("dw2") == ""
    assert "no program" in radio.forget_program("dw2")


def test_a_rig_is_saved_with_the_swr_trip_on_at_three():
    radio, core, _ = _radio()
    assert radio.save_rig({"name": "ft991a", "model": "1035", "tune_bands": "40m 80m"}) == ""
    rig = core.config.rigs[0]
    assert rig["model"] == 1035 and rig["swr_trip"] == 3.0
    assert rig["host"] == "127.0.0.1" and rig["port"] == 4532
    assert rig["tune_bands"] == ["40m", "80m"]


def test_tuning_is_off_on_every_band_unless_chosen():
    radio, core, _ = _radio()
    radio.save_rig({"name": "r", "model": 1})
    assert core.config.rigs[0]["tune_bands"] == []


def test_a_rig_refuses_a_bad_band_model_or_trip():
    radio, core, _ = _radio()
    assert "Not a band" in radio.save_rig({"name": "r", "model": 1, "tune_bands": ["99m"]})
    assert "number" in radio.save_rig({"name": "r", "model": "x"})
    assert "required" in radio.save_rig({"name": "r"})
    assert "more than 1.0" in radio.save_rig({"name": "r", "model": 1, "swr_trip": "1"})
    assert core.config.rigs == []


def test_a_transport_may_only_name_a_program_and_rig_that_exist():
    radio, core, _ = _radio()
    entry = {"name": "kiss", "kind": "tcp", "host": "127.0.0.1", "port": 8001, "program": "dw"}
    assert "no program named" in radio.save_transport(entry)
    radio.save_program(_program())
    assert radio.save_transport(entry) == ""
    assert core.config.transports[0]["program"] == "dw"
    entry = {**entry, "program": "", "rig": "ghost"}
    assert "no rig named" in radio.save_transport(entry, original="kiss")
    assert radio.save_transport({**entry, "rig": ""}, original="kiss") == ""
    assert "program" not in core.config.transports[0]
