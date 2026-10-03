"""The Files viewer's reading: zips in memory, HTML to Markdown."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import io  # noqa: E402
import zipfile  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from kissterm.files_view import (  # noqa: E402
    MAX_MEMBER,
    html_title,
    html_to_markdown,
    kind_of,
    zip_members,
    zip_read,
)

DATA = Path(__file__).parent / "data" / "pktnet"


def _zip(**members: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in members.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def test_kinds_by_name_then_content():
    assert kind_of("a.zip") == "zip"
    assert kind_of("download.bin", b"PK\x03\x04rest") == "zip"
    assert kind_of("notes.md", b"# hi") == "markdown"
    assert kind_of("form.HTML", b"<html>") == "html"
    assert kind_of("x.txt", b"hello") == "text"
    assert kind_of("x.md", b"\x00\x01") == "binary"


def test_a_zip_is_listed_and_read_in_memory_whatever_its_names_say(tmp_path):
    data = _zip(**{"../../evil.sh": b"rm -rf ~", "docs/readme.md": b"# Read me"})
    assert zip_members(data) == [("../../evil.sh", 8), ("docs/readme.md", 9)]
    assert zip_read(data, "docs/readme.md") == b"# Read me"
    assert not any(tmp_path.iterdir())
    assert not (Path.cwd().parent / "evil.sh").exists()


def test_a_member_over_the_cap_is_refused_with_its_size():
    data = _zip(big=b"x" * (MAX_MEMBER + 1))
    with pytest.raises(ValueError, match="reads up to"):
        zip_read(data, "big")


def test_not_a_zip_says_so():
    with pytest.raises(ValueError, match="not a readable zip"):
        zip_members(b"PK\x03\x04 truncated")


def test_the_pktnet_bulletin_form_reads_as_its_layout():
    """KN4LQN's form from WS1EC-2 (2026-10-03): fields as blanks, the
    precedence list showing its selected option, scripts and the remote
    jQuery dropped."""
    page = (DATA / "bulletin.html").read_bytes()
    assert html_title(page) == "PACKET BULLETIN MESSAGE"
    text = html_to_markdown(page)
    assert "For (Name/Group): [________]   Bulletin #: [________]" in text
    assert "Precedence: [Routine v]" in text
    assert "[ Generate/Save as Text ]" in text
    assert "jquery" not in text.lower() and "$(document)" not in text
    assert "| Form Concept By: N3MEL | Form Created By: KN4LQN | Ver 1.1 |" in text


def test_page_text_cannot_become_markdown_or_escape_codes():
    text = html_to_markdown(b"<p>[click](http://x) # not a heading \x1b[31mred</p>"
                            b"<h2>Real</h2><a href='http://example.org'>site</a>")
    assert "\\[click\\](http://x)" in text
    assert "\\# not a heading" in text
    assert "\x1b" not in text
    assert "## Real" in text
    assert "site (http://example.org)" in text
