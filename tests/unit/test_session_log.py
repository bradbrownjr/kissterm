"""Unit tests for `kissterm.session_log`.

`SessionLog` takes an explicit `directory` in its constructor and never
touches `platformdirs`, so -- unlike `test_config.py` -- there is no ordering
hazard around when `kissterm.config` gets imported. `kissterm._isolate` is
not needed here for that reason, but every filesystem operation still goes
through pytest's `tmp_path` so a bug in the sanitizer cannot write outside
the test's own scratch directory.
"""

from __future__ import annotations

import os
import stat
import time

import pytest

from kissterm.session_log import SessionLog, transcript_name


# ---------------------------------------------------------------------------
# transcript_name: sanitization is the security-relevant part of this module
# ---------------------------------------------------------------------------


def test_transcript_name_shape():
    when = time.time()
    name = transcript_name("W1AW-1", "WS1EC-7", when)

    assert name.endswith("_W1AW-1_WS1EC-7.log")
    # The timestamp portion must be the fixed-width YYYYMMDD-HHMMSS format
    # and match local time, independent of the timezone the test runs in.
    stamp = name.split("_", 1)[0]
    assert stamp == time.strftime("%Y%m%d-%H%M%S", time.localtime(when))
    assert len(stamp) == 15
    assert stamp[8] == "-"


@pytest.mark.parametrize(
    "peer",
    [
        "../../etc/passwd",
        "A/B",
        "..",
        "",
        "W1AW-1",
        "NUL\x00BYTE",
        "X" * 200,
    ],
)
def test_transcript_name_sanitizes_peer(tmp_path, peer):
    name = transcript_name("N0CALL-1", peer, time.time())

    assert os.sep not in name
    assert "/" not in name
    assert not name.startswith(".")

    resolved = (tmp_path / name).resolve()
    assert resolved.parent == tmp_path.resolve()
    # Belt and suspenders on the "stays inside directory" requirement: the
    # resolved path's string must be rooted at the resolved directory.
    assert str(resolved).startswith(str(tmp_path.resolve()) + os.sep)


def test_transcript_name_caps_each_token_length():
    name = transcript_name("A" * 200, "B" * 200, time.time())
    mycall_token, peer_token = name.split("_")[1], name.split("_")[2].removesuffix(".log")
    assert len(mycall_token) <= 12
    assert len(peer_token) <= 12


def test_transcript_name_empty_or_all_punctuation_becomes_unknown():
    assert "_UNKNOWN_" in transcript_name("", "W1AW-1", time.time())
    assert transcript_name("W1AW-1", "..", time.time()).endswith("_UNKNOWN.log")
    assert transcript_name("///", "***", time.time()).split("_", 1)[1] == "UNKNOWN_UNKNOWN.log"


def test_transcript_name_uppercases_and_strips_punctuation():
    name = transcript_name("w1aw-1", "a/b.c", time.time())
    assert "_W1AW-1_ABC.log" in name


def test_transcript_name_is_stable_for_the_same_inputs():
    when = time.time()
    assert transcript_name("W1AW-1", "N0CALL", when) == transcript_name("W1AW-1", "N0CALL", when)


# ---------------------------------------------------------------------------
# open() / writing / close(): the happy path
# ---------------------------------------------------------------------------


def test_open_creates_directory_and_file(tmp_path):
    log_dir = tmp_path / "logs"
    log = SessionLog(log_dir, "W1AW-1", "N0CALL-2", started=time.time())

    assert log.open() is True
    assert log.failed == ""
    assert log_dir.is_dir()
    assert log.path.exists()
    assert log.path.parent == log_dir

    log.close()


def test_sent_received_note_markers_are_unambiguous(tmp_path):
    log = SessionLog(tmp_path, "W1AW-1", "N0CALL-2", started=time.time(), timestamps=False)
    log.open()

    log.sent("hello there")
    log.received("general kenobi")
    log.note("link established")
    log.close()

    text = log.path.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert lines[0] == "> hello there"
    assert lines[1] == "< general kenobi"
    assert lines[2] == "* link established"


def test_multiline_text_prefixes_every_line(tmp_path):
    log = SessionLog(tmp_path, "W1AW-1", "N0CALL-2", started=time.time(), timestamps=False)
    log.open()

    log.received("line one\nline two\nline three")
    log.close()

    text = log.path.read_text(encoding="utf-8")
    body = [line for line in text.splitlines() if line.startswith("<")]
    assert body == ["< line one", "< line two", "< line three"]


def test_trailing_newline_does_not_produce_a_blank_prefixed_line(tmp_path):
    log = SessionLog(tmp_path, "W1AW-1", "N0CALL-2", started=time.time(), timestamps=False)
    log.open()

    log.sent("hello\n")
    log.close()

    text = log.path.read_text(encoding="utf-8")
    sent_lines = [line for line in text.splitlines() if line.startswith(">")]
    assert sent_lines == ["> hello"]


def test_timestamps_enabled_by_default(tmp_path):
    log = SessionLog(tmp_path, "W1AW-1", "N0CALL-2", started=time.time())
    log.open()
    log.sent("hi")
    log.close()

    text = log.path.read_text(encoding="utf-8")
    sent_line = next(line for line in text.splitlines() if "hi" in line and line.startswith("["))
    # [HH:MM:SS] > hi
    assert sent_line[0] == "["
    assert sent_line[9] == "]"
    assert sent_line[3] == ":" and sent_line[6] == ":"


def test_timestamps_false_suppresses_the_per_line_prefix(tmp_path):
    log = SessionLog(tmp_path, "W1AW-1", "N0CALL-2", started=time.time(), timestamps=False)
    log.open()
    log.sent("hi")
    log.note("state change")
    log.close()

    for line in log.path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            continue
        assert not line.startswith("[")


def test_date_appears_once_in_the_header_not_per_line(tmp_path):
    when = time.time()
    log = SessionLog(tmp_path, "W1AW-1", "N0CALL-2", started=when)
    log.open()
    log.sent("one")
    log.received("two")
    log.close()

    date_str = time.strftime("%Y-%m-%d", time.localtime(when))
    text = log.path.read_text(encoding="utf-8")
    assert text.count(date_str) == 1


def test_append_mode_extends_rather_than_destroys(tmp_path):
    when = time.time()
    log1 = SessionLog(tmp_path, "W1AW-1", "N0CALL-2", started=when, timestamps=False)
    log1.open()
    log1.sent("first session line")
    log1.close()

    # Same directory, same names, same second -- forces a filename collision.
    log2 = SessionLog(tmp_path, "W1AW-1", "N0CALL-2", started=when, timestamps=False)
    assert log2.path == log1.path
    log2.open()
    log2.sent("second session line")
    log2.close()

    text = log2.path.read_text(encoding="utf-8")
    assert "first session line" in text
    assert "second session line" in text


def test_received_text_is_written_verbatim_not_resanitized(tmp_path):
    # This module must not import kissterm.monitor.sanitize -- the caller
    # owns sanitization. Feed it something sanitize() would have stripped
    # (a raw ESC byte) and confirm it lands in the file untouched.
    log = SessionLog(tmp_path, "W1AW-1", "N0CALL-2", started=time.time(), timestamps=False)
    log.open()
    raw = "before\x1b[31mafter"
    log.received(raw)
    log.close()

    text = log.path.read_text(encoding="utf-8")
    assert raw in text


def test_module_does_not_import_monitor():
    assert "kissterm.monitor" not in _module_imports("kissterm.session_log")


def _module_imports(module_name: str) -> set[str]:
    import ast
    import importlib.util

    spec = importlib.util.find_spec(module_name)
    source = spec.loader.get_source(module_name)
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


# ---------------------------------------------------------------------------
# close(): idempotent from every reachable state
# ---------------------------------------------------------------------------


def test_close_is_idempotent_after_a_normal_open(tmp_path):
    log = SessionLog(tmp_path, "W1AW-1", "N0CALL-2", started=time.time())
    log.open()
    log.close()
    log.close()  # must not raise


def test_close_before_open_is_safe(tmp_path):
    log = SessionLog(tmp_path, "W1AW-1", "N0CALL-2", started=time.time())
    log.close()  # must not raise, must not create anything
    assert not log.path.exists()


def test_close_writes_a_closing_line(tmp_path):
    log = SessionLog(tmp_path, "W1AW-1", "N0CALL-2", started=time.time(), timestamps=False)
    log.open()
    log.sent("hi")
    log.close()

    text = log.path.read_text(encoding="utf-8")
    assert "closed" in text.splitlines()[-1].lower()


def test_methods_after_close_are_silent_no_ops(tmp_path):
    log = SessionLog(tmp_path, "W1AW-1", "N0CALL-2", started=time.time(), timestamps=False)
    log.open()
    log.close()
    before = log.path.read_text(encoding="utf-8")

    log.sent("should not appear")
    log.received("should not appear either")
    log.note("nor this")

    after = log.path.read_text(encoding="utf-8")
    assert before == after


def test_methods_before_open_are_silent_no_ops(tmp_path):
    log = SessionLog(tmp_path, "W1AW-1", "N0CALL-2", started=time.time())

    log.sent("nothing")
    log.received("nothing")
    log.note("nothing")

    assert not log.path.exists()
    assert log.failed == ""


# ---------------------------------------------------------------------------
# Failure handling: a transcript is a convenience, a live link is not
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root ignores directory permission bits, so this cannot fail as root",
)
def test_open_on_unwritable_directory_returns_false_and_never_raises(tmp_path):
    parent = tmp_path / "readonly"
    parent.mkdir()
    parent.chmod(stat.S_IREAD | stat.S_IEXEC)
    try:
        log = SessionLog(parent / "sessions", "W1AW-1", "N0CALL-2", started=time.time())
        result = log.open()  # must not raise
        assert result is False
        assert log.failed != ""
    finally:
        parent.chmod(stat.S_IRWXU)


def test_open_when_path_component_is_a_file_returns_false(tmp_path):
    # `directory` collides with an existing plain file, so mkdir(parents=True)
    # must fail with OSError/FileExistsError rather than raising unhandled.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    log = SessionLog(blocker / "sessions", "W1AW-1", "N0CALL-2", started=time.time())

    assert log.open() is False
    assert log.failed != ""


def test_calls_after_a_write_failure_are_silent_no_ops(tmp_path, monkeypatch):
    log = SessionLog(tmp_path, "W1AW-1", "N0CALL-2", started=time.time(), timestamps=False)
    log.open()

    def _boom(*args, **kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr(log._handle, "write", _boom)
    log.sent("this write fails")

    assert log.failed != ""
    before = log.failed

    # Further calls must not raise, must not change `failed` again, and
    # close() must still be safe to call.
    log.received("also silent")
    log.note("also silent")
    assert log.failed == before
    log.close()


def test_failed_property_defaults_to_empty_string(tmp_path):
    log = SessionLog(tmp_path, "W1AW-1", "N0CALL-2", started=time.time())
    assert log.failed == ""


# ---------------------------------------------------------------------------
# path property
# ---------------------------------------------------------------------------


def test_path_is_available_before_open(tmp_path):
    when = time.time()
    log = SessionLog(tmp_path, "W1AW-1", "N0CALL-2", started=when)
    assert log.path == tmp_path / transcript_name("W1AW-1", "N0CALL-2", when)


def test_started_defaults_to_now_when_omitted(tmp_path):
    before = time.time()
    log = SessionLog(tmp_path, "W1AW-1", "N0CALL-2")
    after = time.time()

    stamp = log.path.name.split("_", 1)[0]
    parsed = time.mktime(time.strptime(stamp, "%Y%m%d-%H%M%S"))
    # Allow a one-second slop for the truncation to whole seconds in the
    # filename format itself.
    assert before - 1 <= parsed <= after + 1
