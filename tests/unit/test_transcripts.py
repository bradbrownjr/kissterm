"""Unit tests for `kissterm.transcripts`.

Same reasoning as `test_session_log.py`: everything here takes an explicit
directory and never touches `platformdirs`, so no `_isolate` ordering hazard
applies -- `tmp_path` is the only filesystem this module ever sees in tests.
"""

from __future__ import annotations

from kissterm.session_log import SessionLog
from kissterm.transcripts import export_transcript, list_transcripts, search_transcripts


def _make_session(tmp_path, mycall, peer, started, text_lines):
    log = SessionLog(tmp_path, mycall, peer, started=started)
    assert log.open()
    for line in text_lines:
        log.received(line)
    log.close()
    return log.path


def test_list_transcripts_is_newest_first(tmp_path):
    _make_session(tmp_path, "N1ABC-1", "WS1EC-7", 1000.0, ["hello"])
    _make_session(tmp_path, "N1ABC-1", "CCEMA", 2000.0, ["world"])

    infos = list_transcripts(tmp_path)

    assert [i.peer for i in infos] == ["CCEMA", "WS1EC-7"]


def test_list_transcripts_parses_call_and_peer(tmp_path):
    path = _make_session(tmp_path, "N1ABC-1", "WS1EC-15", 1_700_000_000.0, ["hi"])

    (info,) = list_transcripts(tmp_path)

    assert info.path == path
    assert info.mycall == "N1ABC-1" or info.mycall == "N1ABC"  # SSID may or may not survive sanitizing
    assert info.peer.startswith("WS1EC")
    assert info.started  # non-empty: the filename matched the expected shape
    assert info.size > 0


def test_list_transcripts_on_a_missing_directory_is_empty_not_an_error(tmp_path):
    assert list_transcripts(tmp_path / "never-created") == []


def test_list_transcripts_tolerates_a_foreign_log_file(tmp_path):
    """A `.log` file that isn't a session transcript at all -- an operator's
    own note, or a leftover from some other tool -- must still be listed,
    just without a parsed call/peer/date."""
    (tmp_path / "notes.log").write_text("not a transcript\n")

    (info,) = list_transcripts(tmp_path)

    assert info.started == ""
    assert info.mycall == ""
    assert info.peer == ""


def test_search_with_empty_needle_returns_everything(tmp_path):
    _make_session(tmp_path, "N1ABC-1", "WS1EC-7", 1000.0, ["hello"])
    _make_session(tmp_path, "N1ABC-1", "CCEMA", 2000.0, ["world"])

    assert len(search_transcripts(tmp_path, "")) == 2
    assert len(search_transcripts(tmp_path, "   ")) == 2


def test_search_matches_on_peer_callsign(tmp_path):
    _make_session(tmp_path, "N1ABC-1", "WS1EC-7", 1000.0, ["hello"])
    _make_session(tmp_path, "N1ABC-1", "CCEMA", 2000.0, ["world"])

    found = search_transcripts(tmp_path, "ws1ec")

    assert len(found) == 1
    assert found[0].peer == "WS1EC-7" or found[0].peer.startswith("WS1EC")


def test_search_falls_back_to_file_contents(tmp_path):
    """The real-world case this earns its "search" name for: the operator
    remembers something said mid-session but not which callsign it was
    to/from."""
    _make_session(tmp_path, "N1ABC-1", "WS1EC-7", 1000.0, ["the quick brown fox"])
    _make_session(tmp_path, "N1ABC-1", "CCEMA", 2000.0, ["nothing relevant here"])

    found = search_transcripts(tmp_path, "brown fox")

    assert len(found) == 1
    assert found[0].peer.startswith("WS1EC")


def test_export_transcript_copies_the_file(tmp_path):
    path = _make_session(tmp_path, "N1ABC-1", "WS1EC-7", 1000.0, ["hello there"])
    (info,) = list_transcripts(tmp_path)
    dest = tmp_path / "exported" / "copy.log"

    export_transcript(info, dest)

    assert dest.read_text() == path.read_text()


def test_export_transcript_raises_on_failure(tmp_path):
    """The UI turns this into a notification; the function itself must not
    swallow it, unlike `SessionLog`'s own courtesy-degrade rule -- this runs
    from a one-shot action with no live link to protect from the failure."""
    path = _make_session(tmp_path, "N1ABC-1", "WS1EC-7", 1000.0, ["hello there"])
    info = list_transcripts(tmp_path)[0]
    assert info.path == path

    import pytest

    with pytest.raises(OSError):
        # A directory as the destination path is not a writable file.
        export_transcript(info, tmp_path)
