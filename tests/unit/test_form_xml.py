"""Winlink form XML (`kissterm/mail/form_xml.py`).

The attachments here are hand-made in the shape of Pat's `TestBuildXML`
(`internal/forms/builder_test.go`) with the variables Winlink Standard
Forms 1.1.20.0's viewers read; no real Winlink Express capture exists yet
(docs/ON-AIR-TESTS.md).
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

from datetime import datetime, timezone  # noqa: E402

import pytest  # noqa: E402

from kissterm import __version__  # noqa: E402
from kissterm.mail import form_xml  # noqa: E402
from kissterm.mail.forms import defaults, filled_rows, get_form, load_forms, render  # noqa: E402
from kissterm.winlink.message import build, serialize  # noqa: E402

ICS213 = b"""<?xml version="1.0" encoding="UTF-8"?>
<RMS_Express_Form>
  <form_parameters>
    <xml_file_version>1.0</xml_file_version>
    <rms_express_version>1.7.17.0</rms_express_version>
    <submission_datetime>20260926180500</submission_datetime>
    <senders_callsign>W1AW</senders_callsign>
    <grid_square>FN31</grid_square>
    <display_form>ICS213_Initial_Viewer.html</display_form>
    <reply_template>ICS213_SendReply.0</reply_template>
  </form_parameters>
  <variables>
    <msgsender>W1AW</msgsender>
    <isexercise>** THIS IS AN EXERCISE **</isexercise>
    <inc_name>ICE STORM</inc_name>
    <to_name>J SMITH, EOC</to_name>
    <fm_name>B BROWN</fm_name>
    <subjectline>Shelter status</subjectline>
    <mdate>2026-09-26</mdate>
    <mtime>14:05</mtime>
    <message>Shelter open.
Cots needed.</message>
    <templateversion>ICS 213  v.43.8</templateversion>
  </variables>
</RMS_Express_Form>
"""


def test_an_ics213_attachment_reads_into_the_shipped_form():
    parsed = form_xml.read(form_xml.parse(ICS213))
    assert parsed.form.id == "ics213"
    assert parsed.values["inc_name"] == "ICE STORM"
    assert parsed.values["To_Name"] == "J SMITH, EOC"  # names compared without case
    assert parsed.values["Message"] == "Shelter open.\nCots needed."
    assert parsed.values["IsExercise"] == "1"


def test_parameters_are_kept():
    found = form_xml.parse(ICS213)
    assert found.display_form == "ICS213_Initial_Viewer.html"
    assert found.parameters["senders_callsign"] == "W1AW"


def test_a_form_kissterm_does_not_ship_is_a_list_of_its_filled_variables():
    data = (b"<RMS_Express_Form><form_parameters><display_form>Hospital_Bed_Report_Viewer.html"
            b"</display_form></form_parameters><variables><msgisreply>False</msgisreply>"
            b"<beds>12</beds><notes>line one\nline two</notes><empty></empty>"
            b"</variables></RMS_Express_Form>")
    parsed = form_xml.read(form_xml.parse(data))
    assert parsed.form.title == "Winlink form: Hospital Bed Report"
    assert [f.id for f in parsed.form.fields] == ["beds", "notes"]
    assert parsed.form.field("notes").kind == "multiline"
    assert parsed.values == {"beds": "12", "notes": "line one\nline two"}


def test_rows_are_numbered_per_cell():
    form = get_form("ics213rr")
    found = form_xml.FormXml({}, {"Qty1": "2", "Item1": "Generator", "Qty3": "1", "Item3": "Cots"})
    assert form_xml.values(form, found)["order"] == [
        {"Qty": "2", "Kind": "", "Type": "", "Item": "Generator", "Cost": "", "ReqDateTime": "",
         "EstDateTime": ""},
        {"Qty": "1", "Kind": "", "Type": "", "Item": "Cots", "Cost": "", "ReqDateTime": "",
         "EstDateTime": ""},
    ]


@pytest.mark.parametrize("data", [
    b"<?xml version='1.0'?><!DOCTYPE x [<!ENTITY a 'aaaa'>]><RMS_Express_Form/>",
    b"<html><body/></html>",
    b"not xml at all",
    b"<RMS_Express_Form>" + b" " * form_xml.MAX_XML + b"</RMS_Express_Form>",
])
def test_anything_else_is_refused(data):
    with pytest.raises(ValueError):
        form_xml.parse(data)


def test_the_attachment_is_found_inside_a_raw_b2f_copy(tmp_path):
    message = build(sender="W1AW", to=["KC1JMH"], subject="ICS-213: Shelter status", body="text\n",
                    mid="ABCDEF123456", files=[("photo.jpg", b"\xff\xd8"),
                                               ("RMS_Express_Form_ICS213_Initial_Viewer.xml", ICS213)])
    raw = tmp_path / "m.b2f"
    raw.write_bytes(serialize(message))
    found = form_xml.from_raw([raw])
    assert found is not None and found.get("inc_name") == "ICE STORM"
    plain = tmp_path / "p.b2f"
    plain.write_bytes(serialize(build(sender="W1AW", to=["KC1JMH"], subject="Hi", body="Hi\n",
                                      mid="ABCDEF123457")))
    assert form_xml.from_raw([plain]) is None


def test_every_winlink_viewer_names_one_shipped_form():
    viewers = [f.winlink_viewer.lower() for f in load_forms() if f.winlink_viewer]
    assert viewers and len(viewers) == len(set(viewers))


# -- writing ---------------------------------------------------------------------

WHEN = datetime(2026, 9, 28, 14, 30, tzinfo=timezone.utc)


def _filled(form_id: str) -> tuple:
    form = get_form(form_id)
    values = defaults(form, mycall="KC1JMH-7", grid="FN43", now=WHEN)
    for f in form.fields:
        if f.kind in ("text", "multiline") and not values.get(f.id):
            values[f.id] = f"{f.id} value"
        if f.kind == "check":
            values[f.id] = "1"
    return form, values


def test_an_ics213_is_written_as_winlink_express_and_pat_write_it():
    form, values = _filled("ics213")
    values["Message"] = "Shelter open.\nCots needed."
    data = form_xml.build(form, values, callsign="KC1JMH-7", grid="FN43", now=WHEN)
    assert data.startswith(b'<?xml version="1.0" encoding="UTF-8"?>\n<RMS_Express_Form>')
    found = form_xml.parse(data)
    assert found.parameters == {
        "xml_file_version": "1.0", "rms_express_version": f"kissterm {__version__}",
        "submission_datetime": "20260928143000", "senders_callsign": "KC1JMH",
        "grid_square": "FN43", "display_form": "ICS213_Initial_Viewer.html",
        "reply_template": "ICS213_SendReply.0",
    }
    names = list(found.variables)
    assert names == sorted(names) and all(n == n.lower() for n in names)
    assert found.variables["message2"] == "Shelter open.\nCots needed."  # what the viewer shows
    assert found.variables["isexercise"] == "** THIS IS AN EXERCISE **"
    assert found.variables["templateversion"] == "ICS 213  v.43.8"
    assert found.variables["msgsender"] == "KC1JMH" and found.variables["msgisreply"] == "False"
    assert form_xml.attachment_name(form.winlink_viewer) == "RMS_Express_Form_ICS213_Initial_Viewer.xml"


@pytest.mark.parametrize("form_id", [f.id for f in load_forms() if f.winlink_viewer])
def test_every_viewer_variable_is_written_and_reads_back(form_id):
    form, values = _filled(form_id)
    found = form_xml.parse(form_xml.build(form, values, callsign="KC1JMH"))
    for name in form.winlink_viewer_vars:
        assert name.lower() in found.variables, name  # else the viewer shows {var name}
    back = form_xml.read(found)
    assert back.form.id == form_id
    for f in form.fields:
        if f.kind == "rows":
            assert back.values[f.id] == forms_filled_rows(f, values[f.id])
        else:
            assert back.values[f.id] == str(values[f.id]).strip(), f.id


def forms_filled_rows(f, rows):
    return [{c.id: str(r.get(c.id, "")).strip() for c in f.columns} for r in filled_rows(f, rows)]


def test_the_checkin_subject_is_computed_into_the_xml():
    form, values = _filled("winlink_checkin")
    found = form_xml.parse(form_xml.build(form, values, callsign="KC1JMH"))
    assert found.variables["newsubject"] == render(form, values)[0]
    assert found.variables["templateversion"] == "Winlink Check-in 5.1.3"


def test_a_reply_names_the_original_sender():
    form, values = _filled("ics213_reply")
    found = form_xml.parse(form_xml.build(form, values, callsign="KC1JMH", reply=True,
                                          extra={"theMsgSender": "W1AW"}))
    assert found.variables["themsgsender"] == "W1AW" and found.variables["msgisreply"] == "True"


def test_a_form_with_no_winlink_viewer_has_no_xml():
    with pytest.raises(ValueError):
        form_xml.build(get_form("pktnet_checkin"), {}, callsign="KC1JMH")
