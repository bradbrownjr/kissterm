"""Received forms: render, save, parse back (kissterm/mail/form_parse.py)."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402

from kissterm.mail import form_parse, forms  # noqa: E402
from kissterm.mail.compose import clean_text  # noqa: E402

NOW = datetime(2026, 9, 26, 14, 5)


def _sample(form: forms.FormDef) -> forms.Values:
    """A value in every field, two lines in every table."""
    values = forms.defaults(form, mycall="KC1JMH", now=NOW)
    for f in form.fields:
        if f.kind == "rows":
            values[f.id] = [
                {c.id: (c.choices[n % len(c.choices)] if c.choices else f"{c.id} {n}")
                 for c in f.columns if not c.sum_of and not c.format}
                for n in (1, 2)
            ]
        elif f.kind == "multiline":
            values[f.id] = f"First line of {f.id}\n\nSecond paragraph"
        elif f.kind == "choice":
            values[f.id] = f.choices[-1]
        elif f.kind == "check":
            values[f.id] = "1"
        elif f.derived:
            values[f.id] = "3"
        elif f.kind == "text" and not f.auto:
            values[f.id] = f"Value of {f.id}"
    return values


@pytest.mark.parametrize("form_id", [f.id for f in forms.load_forms()])
def test_every_form_reads_back_what_it_sent(form_id):
    form = forms.get_form(form_id)
    values = _sample(form)
    subject, body = forms.render(form, values)
    parsed = form_parse.recognize(subject, clean_text(body))
    assert parsed is not None and parsed.form.id == form_id, parsed and parsed.form.id
    joined = form_parse.ambiguous(form)
    for f in form.fields:
        if f.id.lower() in joined:
            continue  # given, with its line, to the variable before it
        if f.kind == "rows":
            got = [{k: v for k, v in r.items() if v} for r in parsed.values[f.id]]
            want = [{k: v for k, v in r.items() if v} for r in values[f.id]]
            assert got == want, f.id
        else:
            sent = str(values[f.id]).strip()
            # A field whose line also holds an ambiguous one keeps both.
            assert parsed.values[f.id] == sent or parsed.values[f.id].startswith(sent + " "), f.id


def test_the_form_header_decides_and_a_plain_message_is_no_form():
    form = forms.get_form("ics213")
    subject, body = forms.render(form, _sample(form))
    assert form_parse.recognize("anything", body, form_id="ics213").form.id == "ics213"
    assert form_parse.recognize("Meeting Thursday", "See you at 7 PM.\n73\n") is None
    assert form_parse.recognize("Re: Shelter", "4. Subject: shelter\nThanks.\n") is None


def test_a_winlink_express_ics213_is_read_with_its_extra_lines():
    body = (
        "GENERAL MESSAGE (ICS 213)\nCUMBERLAND COUNTY EMA\n\n"
        "1. Incident Name: ICE STORM       \n2. To (Name and Position): J SMITH, EOC\n"
        "3. From (Name and Position): B BROWN\n4. Subject: Shelter status\n"
        "5. Date: 2026-09-26\n6. Time: 14:05\n7. Message: \n\nShelter open.\nCots needed.\n\n"
        "8. Approved by: B BROWN\n8a. Position/Title: RADIO OP\n"
        "    [Sender: KC1JMH Lat: 43.5, Lon:-70.7, MGRS: ; Location source: GPS]\n"
        "------------------------------------\nExpress Sending Station: KC1JMH\n"
        "Senders Express Version: 1.7.20.0\nSenders Template Version: 43.8\n"
    )
    parsed = form_parse.recognize("ICS-213: Shelter status - 2026-09-26 14:05", body)
    assert parsed.form.id == "ics213"
    assert parsed.values["Message"] == "Shelter open.\nCots needed."
    assert parsed.values["Approved_PosTitle"] == "RADIO OP"


def test_a_gyx_strip_answer_is_recognised_by_its_title():
    form = forms.get_form("gyx_weather")
    values = forms.defaults(form, mycall="KC1JMH", now=NOW)
    values.update(s1="09-26-2026", s7="ME")
    subject, body = forms.render(form, values)
    parsed = form_parse.recognize("GYX WEATHER", "Report follows:\n" + body)
    assert parsed.form.id == "gyx_weather"
    assert (parsed.values["s1"], parsed.values["s3"], parsed.values["s4"]) == ("09-26-2026", "KC1JMH", "")


@pytest.mark.parametrize("form_id", [f.id for f in forms.load_forms()])
def test_a_form_with_only_what_is_required_is_still_recognised(form_id):
    form = forms.get_form(form_id)
    full = _sample(form)
    values = forms.defaults(form, mycall="KC1JMH", now=NOW)
    for f in form.fields:
        if f.required:
            values[f.id] = full[f.id]
    subject, body = forms.render(form, values)
    parsed = form_parse.recognize(subject, clean_text(body))
    assert parsed is not None and parsed.form.id == form_id
