"""Message forms (`kissterm/mail/forms.py`): the shipped form files load,
and their text matches the Winlink standard templates they copy."""

from kissterm import _isolate

_isolate.isolate()

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402

from kissterm.mail import forms  # noqa: E402

NOW = datetime(2026, 9, 26, 14, 5)


def _ics213(**values):
    form = forms.get_form("ics213")
    filled = forms.defaults(form, mycall="kc1jmh-1", now=NOW)
    filled.update({"To_Name": "J SMITH, EOC MANAGER", "fm_name": "B BROWN, RADIO OPERATOR",
                   "Subjectline": "Shelter status", "Message": "Shelter open.\n40 cots.",
                   "Approved_Name": "B BROWN", **values})
    return form, filled


def test_every_shipped_form_loads_and_names_its_source():
    shipped = {f.id: f for f in forms.load_forms()}
    assert {"ics213", "ics213rr"} <= set(shipped)
    for form in shipped.values():
        assert "Winlink Standard Forms" in form.source, form.id


def test_ics213_follows_the_winlink_template():
    form, values = _ics213(inc_name="Ice storm", Approved_PosTitle="RADIO OPERATOR")
    subject, body = forms.render(form, values)
    assert subject == "ICS-213: Shelter status - 2026-09-26 14:05"
    assert body == (
        "GENERAL MESSAGE (ICS 213)\n"
        "1. Incident Name: Ice storm\n"
        "2. To (Name and Position): J SMITH, EOC MANAGER\n"
        "3. From (Name and Position): B BROWN, RADIO OPERATOR\n"
        "4. Subject: Shelter status\n"
        "5. Date: 2026-09-26\n"
        "6. Time: 14:05\n"
        "7. Message:\n\nShelter open.\n40 cots.\n\n"
        "8. Approved by: B BROWN\n"
        "8a. Position/Title: RADIO OPERATOR\n"
    )
    assert forms.problems(form, values) == []


def test_the_exercise_banner_appears_only_when_ticked():
    form, values = _ics213(IsExercise="1")
    assert "\n** THIS IS AN EXERCISE **\n1. Incident Name:" in forms.render(form, values)[1]


def test_problems_name_the_field():
    form, values = _ics213(To_Name="", Subjectline="x" * 51)
    found = " ".join(forms.problems(form, values))
    assert "2. To is needed" in found and "4. Subject is at most 50" in found


def test_213rr_writes_one_block_per_filled_line():
    form = forms.get_form("ics213rr")
    values = forms.defaults(form, now=NOW)
    values.update(IncName="Ice storm", ReqNum="7", ReqName="B BROWN", order=[
        {"Qty": "40", "Kind": "Cots", "Item": "Folding cots"}, {}, {"Qty": "2", "Item": "Generators"}])
    subject, body = forms.render(form, values)
    assert subject == "ICS 213RR- Ice storm- Request #:7"
    assert body.count("QTY:") == 2 and "QTY: 40 Kind: Cots Type:" in body
    assert body.count("PRIORITY: [Low]") == 2
    assert "LOGISTICS" not in body and "FINANCE" not in body
    values["order"] = [{}]
    assert "4. Order: add at least one line." in forms.problems(form, values)


def test_defaults_fill_dates_and_remembered_fields(tmp_path):
    form = forms.get_form("ics213")
    path = tmp_path / "forms.json"
    assert forms.load_remembered(path, "ics213") == {}
    forms.save_remembered(path, "ics213", {"fm_name": "B BROWN", "Approved_Name": "B BROWN"})
    values = forms.defaults(form, now=NOW, remembered=forms.load_remembered(path, "ics213"))
    assert (values["Mdate"], values["Mtime"], values["fm_name"]) == ("2026-09-26", "14:05", "B BROWN")
    assert values["Message"] == ""  # the message half is never remembered
    path.write_text("not json")
    assert forms.load_remembered(path, "ics213") == {}


def test_a_template_naming_an_unknown_field_is_refused():
    bad = 'id="x"\ntitle="X"\nsource="s"\nsubject="<var nope>"\nbody=""\n[[fields]]\nid="a"\nlabel="A"\n'
    with pytest.raises(ValueError, match="nope"):
        forms.parse_form(bad)
