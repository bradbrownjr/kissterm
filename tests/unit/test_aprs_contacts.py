"""`kissterm.aprs_contacts` -- contact shape and validation."""

from __future__ import annotations

from kissterm.aprs_contacts import (
    CannedMessage,
    canned_messages_for,
    validate_canned_message,
    Contact,
    build_message_body,
    normalize_contact,
    normalize_service,
    validate_contact,
)


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


# -- build_message_body --------------------------------------------------


def test_station_service_sends_text_unchanged():
    assert build_message_body("station", "", "hello there") == "hello there"


def test_sms_uses_the_default_template_when_none_is_configured():
    body = build_message_body("sms", "5551234567", "hello there")
    assert body == "@5551234567 hello there"


def test_email_uses_the_default_template_when_none_is_configured():
    body = build_message_body("email", "jim@example.com", "hello there")
    assert body == "jim@example.com hello there"


def test_a_configured_sms_template_overrides_the_default():
    body = build_message_body(
        "sms", "5551234567", "hi", sms_template="SMS TO {detail}: {text}"
    )
    assert body == "SMS TO 5551234567: hi"


def test_a_configured_email_template_overrides_the_default():
    body = build_message_body(
        "email", "jim@example.com", "hi", email_template="{text} -- for {detail}"
    )
    assert body == "hi -- for jim@example.com"


def test_a_malformed_template_falls_back_to_the_default_rather_than_raising():
    body = build_message_body("sms", "5551234567", "hi", sms_template="{bogus_field}")
    assert body == "@5551234567 hi"


def test_an_empty_configured_template_falls_back_to_the_default():
    body = build_message_body("sms", "5551234567", "hi", sms_template="")
    assert body == "@5551234567 hi"


# ---------------------------------------------------------------------------
# Contact.gateway -- the pointer into the shipped service directory
# ---------------------------------------------------------------------------


def test_gateway_defaults_to_empty_for_an_ordinary_person():
    assert Contact(name="Jim", callsign="K1ABC-9").gateway == ""


def test_gateway_round_trips_through_the_config_dict_shape():
    contact = Contact(name="Winlink", callsign="WLNK-1", gateway="winlink")
    assert Contact.from_dict(contact.to_dict()) == contact


def test_a_contact_saved_before_gateway_existed_still_loads():
    """Config files written by an older kissterm have no `gateway` key at
    all. Defaulting rather than raising is the whole reason the loader reads
    key by key instead of splatting the dict."""
    contact = Contact.from_dict({"name": "Jim", "callsign": "K1ABC-9"})
    assert contact.gateway == ""
    assert contact.name == "Jim"


def test_service_and_gateway_are_independent():
    """They answer different questions and must not collapse into one: one
    decides the bytes on the air, the other decides which help to show."""
    contact = Contact(
        name="Texting", callsign="SMSGTE", service="sms", detail="5551234567",
        gateway="smsgte",
    )
    assert contact.service == "sms"
    assert contact.gateway == "smsgte"
    # A gateway with plain-text service is a real combination, not a bug:
    # WXBOT takes plain text and has a command set.
    weather = Contact(name="Weather", callsign="WXBOT", gateway="wxbot")
    assert weather.service == "station"
    assert weather.gateway == "wxbot"


# ---------------------------------------------------------------------------
# CannedMessage -- the operator's own saved lines
# ---------------------------------------------------------------------------


def test_a_canned_message_needs_a_name_and_some_text():
    assert validate_canned_message("Net check-in", "QRV, monitoring") == ""
    assert validate_canned_message("", "QRV") != ""
    assert validate_canned_message("Net check-in", "   ") != ""


def test_canned_message_round_trips():
    message = CannedMessage(name="Check-in", text="CQ HOTG QRV", gateway="ansrvr")
    assert CannedMessage.from_dict(message.to_dict()) == message


def test_scoped_messages_come_before_global_ones():
    """Someone composing to WLNK-1 wants their Winlink line first. A picker
    that makes them scroll past the general case to reach the specific one
    has the priority backwards."""
    raw = [
        {"name": "Generic", "text": "QRV"},
        {"name": "Winlink SP", "text": "SP ", "gateway": "winlink"},
    ]
    got = canned_messages_for(raw, "winlink")
    assert [m.name for m in got] == ["Winlink SP", "Generic"]


def test_a_message_scoped_to_another_gateway_is_not_offered():
    raw = [{"name": "Winlink SP", "text": "SP ", "gateway": "winlink"}]
    assert canned_messages_for(raw, "wxbot") == []
    # And with no gateway at all, only the global ones show.
    assert canned_messages_for(raw, "") == []


def test_global_messages_show_for_every_recipient():
    raw = [{"name": "Generic", "text": "QRV"}]
    assert [m.name for m in canned_messages_for(raw, "winlink")] == ["Generic"]
    assert [m.name for m in canned_messages_for(raw, "")] == ["Generic"]


def test_an_empty_or_unnamed_saved_message_is_dropped_not_shown():
    """A hand-edited config file degrades one entry at a time rather than
    taking the whole list with it -- same rule as config.py's loader."""
    raw = [
        {"name": "", "text": "orphan"},
        {"name": "Blank", "text": "   "},
        {"name": "Good", "text": "QRV"},
    ]
    assert [m.name for m in canned_messages_for(raw, "")] == ["Good"]
