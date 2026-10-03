"""kissterm's PKTNET forms write what the PKTNET pages write.

Each case fills a kissterm form (`mail/data/forms/pktnet_*.toml`) and the
page it reproduces (`tests/unit/data/pktnet/`) with the same values, runs
the page's own Generate handler under Node (`tests/tools/pktnet_generate.js`,
jQuery stubbed), and compares the two texts. Skipped without Node.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import json  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from kissterm.files_view import pktnet_form  # noqa: E402
from kissterm.mail import forms  # noqa: E402

DATA = Path(__file__).parent / "data" / "pktnet"
HARNESS = Path(__file__).parents[1] / "tools" / "pktnet_generate.js"
NODE = shutil.which("node")


def _page_text(page: str, values: dict, tmp_path: Path) -> str:
    path = tmp_path / "values.json"
    path.write_text(json.dumps(values))
    return subprocess.run([NODE, str(HARNESS), str(DATA / page), str(path)],
                          check=True, capture_output=True, text=True, timeout=30).stdout


def _kissterm_text(form_id: str, values: dict) -> str:
    form = forms.get_form(form_id)
    filled = forms.defaults(form)
    filled.update(values)
    assert forms.problems(form, filled) == []
    return forms.render(form, filled)[1]


CASES = {
    "pktnet_bulletin": ("bulletin.html", {
        "for": "ALL STATIONS", "bulletin_no": "7", "from": "KC1JMH",
        "date": "2026-10-03", "time": "19:00", "precedence": "Priority",
        "subject": "Net tonight", "message": "Net at 7 PM.\nBring a radio."}),
    "pktnet_checkin": ("check_in.html", {
        "agency": "WSSM ECT", "datetime": "2026-10-03 19:00", "to": "PKTNET@USA",
        "from": "KC1JMH", "contact": "Brad", "operator": "", "session_type": "EXERCISE",
        "service_type": "AMATEUR", "band": "VHF", "mode": "AX25 Packet",
        "location": "Waterboro, ME", "gridsquare": "FN43pp", "town": "Waterboro",
        "state": "ME", "comments": "On batteries."}),
    "pktnet_checkin_no_agency": ("check_in.html", {
        "agency": "", "datetime": "2026-10-03 19:00", "to": "PKTNET@USA",
        "from": "KC1JMH", "contact": "Brad", "operator": "", "session_type": "EXERCISE",
        "service_type": "AMATEUR", "band": "VHF", "mode": "AX25 Packet",
        "location": "Waterboro, ME", "gridsquare": "FN43pp", "town": "Waterboro",
        "state": "ME", "comments": ""}),
}


def _lines(text: str) -> list[str]:
    """Compared line by line without trailing spaces: the page leaves one
    after an empty field ("Initial Operator(s): "), kissterm's render does
    not, and nothing a reader sees differs."""
    return [line.rstrip() for line in text.rstrip("\n").split("\n")]


@pytest.mark.skipif(NODE is None, reason="needs Node to run the page's script")
@pytest.mark.parametrize("form_id", sorted(CASES))
def test_the_form_writes_what_the_page_writes(form_id, tmp_path):
    page, values = CASES[form_id]
    form_id = form_id.removesuffix("_no_agency")
    assert _lines(_kissterm_text(form_id, values)) == _lines(_page_text(page, values, tmp_path))


@pytest.mark.parametrize("page,form_id", [
    ("bulletin.html", "pktnet_bulletin"),
    ("check_in.html", "pktnet_checkin"),
    ("radiogram.html", "radiogram"),
])
def test_each_page_is_recognised_by_its_title(page, form_id):
    assert pktnet_form((DATA / page).read_bytes()) == form_id
