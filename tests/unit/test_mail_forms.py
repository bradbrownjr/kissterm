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
    assert {"ics213", "ics213rr", "winlink_checkin", "pktnet_checkin", "fsr", "severe_wx",
            "damage_assessment", "incident_status"} <= set(shipped)
    for form in shipped.values():
        assert form.source.strip(), form.id


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


def test_winlink_checkin_follows_the_template_and_quotes_its_subject():
    form = forms.get_form("winlink_checkin")
    values = forms.defaults(form, mycall="KC1JMH-1", grid="FN43ln", now=datetime(2026, 9, 26, 14, 5, 9))
    values.update(MsgTo="KW6GB", ContactName="Brad", Location="Waterboro ME")
    subject, body = forms.render(form, values)
    assert subject == "Winlink Check-in EXERCISE - KC1JMH - Waterboro ME"
    assert "  0b: Subject: Winlink Check-in EXERCISE - KC1JMH - Waterboro ME\n" in body
    assert "  1a. Date/Time: 2026-09-26 14:05:09\n  1b. To: KW6GB\n  1c. From: KC1JMH\n" in body
    assert "  2c. Band: VHF\n  2d. Session: Packet\n" in body
    assert "  3e. Grid Square: FN43ln\n" in body and body.endswith("Winlink Check-in 5.1.3\n")


def test_pktnet_checkin_matches_vden_and_bpq_apps():
    form = forms.get_form("pktnet_checkin")
    assert (form.send_type, form.to, form.at) == ("B", "PKTNET", "USA")
    values = forms.defaults(form, mycall="KC1JMH", grid="FN43ln", now=NOW)
    values.update(contact="Brad Brown", town="Waterboro", state="ME", location="Home", comments="73")
    subject, body = forms.render(form, values)
    assert subject == "Brad Brown, KC1JMH, Waterboro, ME"
    # vden check_in.html v1.1, "&nbsp;" spacers as empty lines (bpq-apps netcheck).
    assert body == (
        "PACKET CHECK-IN\n\n1. STATION\n\na. Date/Time: 2026-09-26 14:05\n\nb. To: PKTNET@USA\n\n"
        "c. From: KC1JMH    d. Station Contact Name: Brad Brown    e. Initial Operator(s):\n\n\n"
        "2. SESSION\n\na. Type: EXERCISE    b. Service: AMATEUR    c. Band: VHF\n\n"
        "d. Session: AX25 Packet\n\n\n3. LOCATION\n\na. Location: Home\n\nb. GRID SQUARE: FN43ln\n\n\n"
        "4. COMMENTS: 73\n"
    )
    values["agency"] = "WSSM ECT"
    assert forms.render(form, values)[1].startswith("PACKET CHECK-IN\n\nWSSM ECT\n\n1. STATION\n")


def test_fsr_statuses_default_to_unknown_and_the_dtg_is_utc():
    from datetime import timezone
    form = forms.get_form("fsr")
    values = forms.defaults(form, mycall="KC1JMH", now=datetime(2026, 9, 26, 14, 5, 9, tzinfo=timezone.utc))
    values.update(MsgTo="KX1EMA", State="ME", k9="NO", Comm6="out since 0600")
    subject, body = forms.render(form, values)
    assert subject == "//WL2K R/ Routine/ Field Situation Report 2026-09-26 14:05:09Z"
    assert "DATE/TIME Group: 2026-09-26  14:05:09Z\n" in body
    assert "9a. Commercial Power functioning: [ NO ]  out since 0600\n" in body
    assert "4a. POTS landlines functioning: [ Unknown - N/A ]\n" in body
    assert body.endswith("BT\nNNNN\n")


def test_severe_wx_computes_metric_as_the_template_does():
    form = forms.get_form("severe_wx")
    values = forms.defaults(form, mycall="KC1JMH", now=NOW)
    values.update(RepName="Brad", Region="ME", County="York", WindspeedI="45", RainI="1.5", SnowI="10")
    subject, body = forms.render(form, values)
    assert subject == "Severe WX Report ME York [First Report]"
    assert "High Wind Speed:  45 Mph | 72.42 KM/h\n" in body
    assert "Heavy Rain: 1.5 in. | 38.10 mm.\n" in body and "Snow:: 10 in. | 25.40 cm.\n" in body
    values["WindspeedI"] = "fast"
    assert "Wind speed, mph is a number." in forms.problems(form, values)


def test_damage_assessment_totals_and_money():
    form = forms.get_form("damage_assessment")
    values = forms.defaults(form, now=NOW)
    values.update(SurArea="Route 5", Jur="Waterboro", damage=[
        {"Category": "HOUSES", "Aff": "3", "Maj": "1", "Dollar": "25000"},
        {"Category": "ROADS", "Min": "2", "Dollar": "1500.50"}])
    subject, body = forms.render(form, values)
    assert subject == "Damage Assessment-Exercise-Waterboro-Route 5"
    assert "HOUSES - Counts\n\nAffected: 3\nMinor:\nMajor: 1\nTotaled:\nTotal number: 4\nCosts: $ 25,000\n\nROADS" in body
    assert "TOTAL DOLLAR Cost: $ 26,500.50\n" in body


def test_incident_status_prints_what_the_template_drops():
    form = forms.get_form("incident_status")
    values = forms.defaults(form, now=NOW)
    values.update(Title="YORK CTY EMA", incidentname="Ice storm", SitSummary="Power out.",
                  Submittedby="B BROWN", f2="1", EOCStatus="ACTIVATED",
                  Declaration="Local disaster declaration", DecDateTime="2026-09-26 12:00",
                  Evac="YES - Description:", Evacyes="Route 5 north")
    subject, body = forms.render(form, values)
    assert subject == "YORK CTY EMA INCIDENT STATUS - Ice storm, 2026-09-26 14:05:00"
    assert "Severe Winter Weather YES\n" in body and "Dam/Levee\n" in body
    assert "(Check one):\n  ACTIVATED\n" in body
    assert "Status\n  Local disaster declaration 2026-09-26 12:00\n" in body
    assert "    YES - Description:\n    Route 5 north\n" in body


def test_a_strip_splits_outside_parentheses_only():
    title, prompts = forms.split_strip(
        "MCF720 PRICE SURVEY/STATE (ST):/SOURCE (@0=Local/Regional Chain, @1=Walmart)://")
    assert title == "MCF720 PRICE SURVEY"
    assert prompts == ["STATE (ST):", "SOURCE (@0=Local/Regional Chain, @1=Walmart):"]
    # GYX's unmatched ")" must not swallow the rest of the strip.
    assert forms.split_strip("GYX WEATHER/LOCATION ROAD, TOWN)/STATE (AA)//")[1] == [
        "LOCATION ROAD, TOWN)", "STATE (AA)"]


def test_a_strip_answer_is_one_line_with_blanks_as_three_spaces():
    form = forms.get_form("gyx_weather")
    assert len(form.fields) == 16
    values = forms.defaults(form, mycall="KC1JMH-1", now=NOW)
    assert values["s3"] == "KC1JMH"  # CALL SIGN
    values.update(s1="09-26-2026", s2="1405L", s7="ME", s8="HEAVY  RAIN\nAND WIND")
    subject, body = forms.render(form, values)
    assert subject == "GYX WEATHER"
    assert body == ("GYX WEATHER/09-26-2026/1405L/KC1JMH/   /   /   /ME/HEAVY RAIN AND WIND"
                    + "/   " * 8 + "//\n")
    values["s6"] = "ROUTE 5/ROUTE 202"
    assert any("cannot contain /" in p for p in forms.problems(form, values))


def test_a_strip_is_found_in_a_message_even_when_wrapped():
    body = ("Please answer:\n\nROSTER/HAM CALL SIGN/FIRST NAME/TOWN/LAT (e.g. 44.123N)/LON\n"
            "(e.g. 069.123W)/WINLINK (Y,N)//\n\n73, net control\n")
    strip = forms.find_strip(body)
    assert strip == "ROSTER/HAM CALL SIGN/FIRST NAME/TOWN/LAT (e.g. 44.123N)/LON (e.g. 069.123W)/WINLINK (Y,N)//"
    form = forms.strip_form(strip)
    assert [f.label for f in form.fields] == ["HAM CALL SIGN", "FIRST NAME", "TOWN", "LAT", "LON", "WINLINK"]
    assert forms.find_strip("See https://example.org/a/b for details.\n") == ""
    assert forms.problems(forms.PASTE_STRIP, {"strip": "hello there"})


def test_ics309_prints_one_block_per_logged_message():
    form = forms.get_form("ics309")
    values = forms.defaults(form, mycall="KC1JMH-1", now=NOW)
    values.update(Title="CUMBERLAND ARES", OpName="B BROWN", log=[
        {"Time": "2026-09-26 14:10", "From": "EOC", "To": "SHELTER1", "Sub": "Cots needed"},
        {"Time": "", "From": "", "To": "", "Sub": ""}])
    subject, body = forms.render(form, values)
    assert subject == "Form 309- CUMBERLAND ARES - B BROWN - KC1JMH - 2026-09-26 14:05"
    assert body.endswith("----------------------------\nTIME: 2026-09-26 14:10\nFROM: EOC\n"
                         "TO: SHELTER1\nSUBJECT:\n Cots needed\n")
    assert "STATION ID:\n" not in body


def test_ics214_numbers_prepared_by_as_fema_does():
    form = forms.get_form("ics214")
    values = forms.defaults(form, now=NOW)
    values.update(Incident_Name="ICE STORM", DateTimeTo="2026-09-26 20:00", Name="B BROWN",
                  ICS_Position="RADIO OPERATOR", Home_Agency="CUMBERLAND ARES", PreparedName="B BROWN",
                  activity=[{"ActTime": "2026-09-26 14:30", "Activity": "Net opened"}])
    assert forms.problems(form, values) == []
    subject, body = forms.render(form, values)
    assert subject == "214- ICE STORM - B BROWN-2026-09-26 14:05 - 2026-09-26 20:00"
    assert "DATE & TIME\tACTIVITY\n2026-09-26 14:30\tNet opened\n---" in body
    assert "8. PREPARED BY:\tB BROWN\n" in body and "\\" not in body


def test_ics205_channel_codes_are_femas():
    form = forms.get_form("ics205")
    values = forms.defaults(form, mycall="KC1JMH", now=NOW)
    values.update(Incident_Name="ICE STORM", DateTo="2026-09-27", PreparedName="B BROWN", IAP_Page="3",
                  channels=[{"Ch": "1", "Function": "Command", "RX": "147.090", "NWMode": "W",
                             "TX": "147.690", "Mode": "A"}])
    subject, body = forms.render(form, values)
    assert subject == "ICS 205 - ICE STORM - 2026-09-26 14:05"
    assert "\t1\tCommand\t\t\t147.090\tW\t\t147.690\t\t\tA\n" in body
    values["channels"][0]["Mode"] = "X"
    assert forms.problems(form, values)


def test_a_309_log_comes_from_mail_since_a_time():
    from datetime import timedelta

    form = forms.get_form("ics309")
    log = form.field("log")
    since = forms.parse_since("2026-09-26 14:00")
    entries = [forms.MailEntry(since + timedelta(minutes=30), "W1AW", "KC1JMH", "Cots"),
               forms.MailEntry(since - timedelta(minutes=1), "W1AW", "KC1JMH", "Too early"),
               forms.MailEntry(since + timedelta(minutes=5), "KC1JMH", "EOC", "Shelter open")]
    assert forms.mail_log_rows(log, entries, since) == [
        {"Time": "2026-09-26 14:05", "From": "KC1JMH", "To": "EOC", "Sub": "Shelter open"},
        {"Time": "2026-09-26 14:30", "From": "W1AW", "To": "KC1JMH", "Sub": "Cots"}]
    assert forms.parse_since("yesterday") is None
