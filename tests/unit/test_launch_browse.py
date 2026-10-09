"""The program file browser shows folders and executables, nothing else."""

from __future__ import annotations

import os
import sys

import pytest

from kissterm import _isolate

_isolate.isolate()

from kissterm.launch.browse import MAX_ENTRIES, is_program, list_dir, validate_path  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX permissions")


def _file(path, mode=0o644, text="x"):
    path.write_text(text)
    path.chmod(mode)
    return path


def test_only_folders_and_executables_are_listed(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / ".hidden").mkdir()
    _file(tmp_path / "mercury", 0o755)
    _file(tmp_path / "VARA.exe")  # an .exe is offered for Wine without the bit
    _file(tmp_path / "notes.txt")
    _file(tmp_path / "run.sh")
    _file(tmp_path / ".secret", 0o755)
    listing = list_dir(str(tmp_path))
    assert listing.folders == ["bin"]
    assert listing.programs == ["mercury", "VARA.exe"] or listing.programs == ["VARA.exe", "mercury"]
    assert not listing.error and not listing.truncated


def test_windows_offers_only_exe_and_com(tmp_path):
    for name in ("a.exe", "b.com", "c.bat", "d.cmd", "e.ps1", "f.vbs"):
        _file(tmp_path / name, 0o755)
    assert sorted(list_dir(str(tmp_path), windows=True).programs) == ["a.exe", "b.com"]


def test_a_listing_never_raises_and_says_why(tmp_path):
    missing = list_dir(str(tmp_path / "nope"))
    assert missing.error and not missing.programs
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        if os.geteuid() != 0:
            assert "Cannot read" in list_dir(str(locked)).error
    finally:
        locked.chmod(0o755)


def test_the_parent_is_offered_up_to_the_root(tmp_path):
    assert list_dir(str(tmp_path)).parent == os.path.dirname(os.path.realpath(tmp_path))
    assert list_dir("/").parent == ""


def test_a_big_folder_is_cut_off_and_says_so(tmp_path):
    for i in range(MAX_ENTRIES + 5):
        (tmp_path / f"d{i:04}").mkdir()
    listing = list_dir(str(tmp_path))
    assert listing.truncated and len(listing.folders) == MAX_ENTRIES


def test_the_listing_gives_names_not_details(tmp_path):
    _file(tmp_path / "modem", 0o755)
    assert set(list_dir(str(tmp_path)).to_dict()) == {
        "path", "parent", "folders", "programs", "truncated", "error"}


def test_a_saved_path_must_be_an_existing_executable_file(tmp_path):
    good = _file(tmp_path / "modem", 0o755)
    assert validate_path(str(good)) == ""
    assert validate_path(sys.executable) == ""
    assert "required" in validate_path("")
    assert "not a file" in validate_path(str(tmp_path / "gone"))
    assert "not an executable" in validate_path(str(_file(tmp_path / "plain")))
    assert not is_program(str(tmp_path))  # a folder is not a program
