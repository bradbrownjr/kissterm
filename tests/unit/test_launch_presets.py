"""Presets are data: every platform's answer is testable on any platform."""

from __future__ import annotations

from kissterm import _isolate

_isolate.isolate()

from kissterm.launch.presets import (  # noqa: E402
    DARWIN, LINUX, PLATFORMS, PRESETS, WINDOWS, default_args, default_path, needs_wine,
)


def test_every_preset_has_a_known_provenance():
    for preset in PRESETS.values():
        assert preset.source in ("documented", "recalled", "unverified"), preset.key


def test_mercury_paths_follow_its_readme():
    assert default_path("mercury", LINUX) == "/usr/bin/mercury"
    assert default_path("mercury", WINDOWS) == "mercury.exe"
    assert default_args("mercury") == "-p 8300"


def test_a_windows_only_program_answers_its_wine_prefix_elsewhere():
    assert default_path("vara-hf", WINDOWS) == r"C:\VARA\VARA.exe"
    assert default_path("vara-hf", LINUX).endswith("drive_c/VARA/VARA.exe")
    assert needs_wine("vara-hf", LINUX) and needs_wine("vara-hf", DARWIN)
    assert not needs_wine("vara-hf", WINDOWS)


def test_a_native_program_never_needs_wine():
    for platform in PLATFORMS:
        assert not needs_wine("mercury", platform)
    assert not needs_wine("direwolf", LINUX)


def test_unknown_and_custom_presets_answer_nothing():
    for key in ("custom", "no-such-program"):
        assert default_path(key, LINUX) == ""
        assert default_args(key) == ""


def test_a_program_that_reads_settings_from_its_folder_says_so():
    assert PRESETS["qtsoundmodem"].cwd_is_program_folder
    assert not PRESETS["mercury"].cwd_is_program_folder
