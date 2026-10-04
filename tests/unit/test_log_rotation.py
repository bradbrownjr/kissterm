"""kissterm.log is set aside at launch once it is too big
(`kissterm.__main__._rotate_log`)."""

from kissterm import _isolate

_isolate.isolate()

from kissterm.__main__ import _rotate_log  # noqa: E402


def test_a_small_log_is_left_alone(tmp_path):
    log = tmp_path / "kissterm.log"
    log.write_text("x" * 10)
    _rotate_log(log, max_bytes=100)
    assert log.read_text() == "x" * 10 and not (tmp_path / "kissterm.log.1").exists()


def test_a_big_log_moves_up_and_the_oldest_is_dropped(tmp_path):
    log = tmp_path / "kissterm.log"
    for name, text in (("kissterm.log", "now" * 50), ("kissterm.log.1", "one"),
                       ("kissterm.log.2", "two"), ("kissterm.log.3", "three")):
        (tmp_path / name).write_text(text)
    _rotate_log(log, max_bytes=100, keep=3)
    assert not log.exists()
    assert (tmp_path / "kissterm.log.1").read_text() == "now" * 50
    assert (tmp_path / "kissterm.log.2").read_text() == "one"
    assert (tmp_path / "kissterm.log.3").read_text() == "two"
    assert not (tmp_path / "kissterm.log.4").exists()


def test_no_log_yet_is_nothing_to_do(tmp_path):
    _rotate_log(tmp_path / "kissterm.log", max_bytes=1)
    assert not list(tmp_path.iterdir())
