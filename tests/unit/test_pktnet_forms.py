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
    "pktnet_ics213": ("ics213.html", {
        "incident": "SHELTER DRILL", "to": "W1AW, Town Hall", "from": "KC1JMH, EOC Radio",
        "subject": "Blankets", "date": "2026-10-03", "time": "23:10Z",
        "message": "20 blankets leave the EOC at 1630.", "sender_name": "Brad",
        "sender_signature": "BB", "sender_position": "Radio officer", "reply": "",
        "reply_name": "", "reply_signature": "", "reply_position": ""}),
    "pktnet_fsr": ("fsr.html", {
        "agency": "WSSM ECT", "precedence": "P/ Priority", "datetime": "2026-10-03 23:10:00Z",
        "task": "4", "from": "KC1JMH", "to": "CCEMA", "info": "", "lifesafety": "NO",
        "city": "Waterboro", "county": "York", "state": "ME", "territory": "",
        "gridsquare": "FN43pp", "latitude": "43.53", "longitude": "-70.71",
        "pots": "YES", "voip": "NO", "cellcalls": "YES", "celltexts": "YES", "amfm": "YES",
        "otatv": "Unknown - N/A", "sattv": "Unknown - N/A", "cabletv": "NO", "water": "YES",
        "powerfunc": "NO", "powerstable": "NO - Brown outs/blinking lights", "gas": "Unknown - N/A",
        "internet": "NO", "noaafunc": "YES", "noaadeg": "NO",
        "comments": "Power out since 1500.", "poc": "KC1JMH"}),
    "pktnet_severe_wx": ("severe_wx.html", {
        "sender": "KC1JMH", "datetime": "2026-10-03 19:10:00", "report_version": "1st Report",
        "reporting_name": "Brad", "reporting_phone": "", "reporting_email": "",
        "city": "Waterboro", "state": "ME", "county": "York", "other": "",
        "gridsquare": "FN43pp", "flood": "Minor Street Flooding", "hail_size": "None",
        "high_wind_speed": "45", "high_wind_units": "MPH", "tornado_cloud": "None",
        "wind_damage": "Small Tree Limbs Down", "winter_precip": "None",
        "snow": "", "snow_units": "inches", "freezing_rain": "", "freezing_rain_units": "inches",
        "heavy_rain": "1.5", "heavy_rain_units": "inches", "time_period": "2",
        "additional_info": "Route 5 closed."}),
    "pktnet_form309": ("form309.html", {
        "task_number": "4", "date_prepared": "2026-10-03", "time_prepared": "19:00",
        "operational_period": "1", "task_name": "SET", "operator_name": "Brad",
        "station_id": "KC1JMH",
        "log": [
            {"log_time": "1905", "log_to": "NCS", "log_from": "KC1JMH", "log_subject": "Check-in"},
            {"log_time": "1912", "log_to": "KC1JMH", "log_from": "W1AW", "log_subject": "Traffic"},
        ]}),
}


def _page_values(values: dict) -> dict:
    """The page's own field ids: Form 309's log rows are `log_time_1`...
    with `number_rows` saying how many the page holds."""
    flat = {k: v for k, v in values.items() if k != "log"}
    rows = values.get("log", [])
    for number, row in enumerate(rows, 1):
        flat.update({f"{column}_{number}": text for column, text in row.items()})
    if rows:
        flat["number_rows"] = str(len(rows) + 3)  # the page holds spare rows
    return flat


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
    assert _lines(_kissterm_text(form_id, values)) == _lines(
        _page_text(page, _page_values(values), tmp_path))


@pytest.mark.parametrize("page,form_id", [
    ("bulletin.html", "pktnet_bulletin"),
    ("check_in.html", "pktnet_checkin"),
    ("radiogram.html", "radiogram"),
    ("ics213.html", "pktnet_ics213"),
    ("fsr.html", "pktnet_fsr"),
    ("severe_wx.html", "pktnet_severe_wx"),
    ("form309.html", "pktnet_form309"),
])
def test_each_page_is_recognised_by_its_title(page, form_id):
    assert pktnet_form((DATA / page).read_bytes()) == form_id
