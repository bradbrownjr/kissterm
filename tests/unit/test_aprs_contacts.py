"""`kissterm.aprs_contacts` -- contact shape and validation."""

from __future__ import annotations

from kissterm.aprs_contacts import Contact, normalize_contact, normalize_service, validate_contact


def test_a_valid_station_contact_has_no_problem():
    assert validate_contact("Jim", "K1ABC-9", "station", "") == ""


def test_a_blank_name_is_rejected():
    assert validate_contact("", "K1ABC-9", "station", "") != ""


def test_a_callsign_over_nine_characters_is_rejected():
    assert validate_contact("Jim", "TOOLONGCALL", "station", "") != ""


def test_an_sms_contact_needs_a_detail():
    assert validate_contact("Mom", "SMSGTE", "sms", "") != ""
    assert validate_contact("Mom", "SMSGTE", "sms", "5551234567") == ""


def test_an_email_contact_needs_a_detail():
    assert validate_contact("Jim", "EMAIL2", "email", "") != ""
    assert validate_contact("Jim", "EMAIL2", "email", "jim@example.com") == ""


def test_normalize_service_falls_back_to_station():
    assert normalize_service("bogus") == "station"
    assert normalize_service("SMS") == "sms"


def test_contact_round_trips_through_dict():
    c = Contact(name="Jim", callsign="K1ABC-9", service="sms", detail="5551234567")
    again = Contact.from_dict(c.to_dict())
    assert again == c


def test_normalize_contact_drops_entries_with_neither_name_nor_callsign():
    assert normalize_contact({}) is None
    assert normalize_contact({"notes": "orphaned note"}) is None


def test_normalize_contact_keeps_a_partial_but_identifiable_entry():
    contact = normalize_contact({"name": "Jim"})
    assert contact is not None
    assert contact.name == "Jim"
    assert contact.service == "station"
