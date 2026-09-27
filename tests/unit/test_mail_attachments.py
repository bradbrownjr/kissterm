"""Attachment names from an unauthenticated sender (ROADMAP P10's rules)."""

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm.mail.attachments import MAX_NAME, safe_filename, save_attachment  # noqa: E402


@pytest.mark.parametrize(("raw", "clean"), [
    ("report.pdf", "report.pdf"),
    ("../../etc/passwd", "passwd"),
    ("C:\\Windows\\system32\\evil.dll", "evil.dll"),
    (".bashrc", "bashrc"),
    ("readme\u202etxt.exe", "readmetxt.exe"),        # right-to-left override
    ("bell\x07and\x00nul.txt", "bellandnul.txt"),
    ('a<b>c:d"e|f?g*h.txt', "a_b_c_d_e_f_g_h.txt"),
    ("NUL.txt", "_NUL.txt"),
    ("  spaced   out  .txt", "spaced out .txt"),
    ("...", "attachment"),
    ("", "attachment"),
    ("Pl\u00e4ne f\u00fcr Samstag.txt", "Pl\u00e4ne f\u00fcr Samstag.txt"),  # real names survive
])
def test_safe_filename(raw, clean):
    assert safe_filename(raw) == clean


def test_a_long_name_keeps_its_real_extension():
    name = safe_filename("x" * 300 + ".exe")
    assert len(name) == MAX_NAME and name.endswith(".exe")


def test_nothing_is_overwritten(tmp_path):
    first = save_attachment(tmp_path, "a.txt", b"one")
    second = save_attachment(tmp_path, "a.txt", b"two")
    third = save_attachment(tmp_path, "noext", b"three")
    fourth = save_attachment(tmp_path, "noext", b"four")
    assert (first.name, second.name, third.name, fourth.name) == (
        "a.txt", "a-1.txt", "noext", "noext-1")
    assert first.read_bytes() == b"one" and second.read_bytes() == b"two"
