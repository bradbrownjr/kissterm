"""`kissterm.monitor.aprs_message_matches` -- deciding whether an incoming
APRS message's addressee field is meant for THIS station, as opposed to
`callsign_matches`'s more general "is this callsign one of mine" question.
"""

from __future__ import annotations

from kissterm.monitor import aprs_message_matches


def test_strict_exact_identity_matches():
    assert aprs_message_matches(
        "KC1JMH-5", "KC1JMH", [], filter_by_ssid=True, active_identity="KC1JMH-5"
    )


def test_strict_rejects_the_bare_call_when_running_an_ssid():
    # Confirmed against a real LinBPQ station: this is real APRS behaviour,
    # not a hypothesis -- see the function's own docstring.
    assert not aprs_message_matches(
        "KC1JMH", "KC1JMH", [], filter_by_ssid=True, active_identity="KC1JMH-5"
    )


def test_strict_rejects_a_different_ssid_of_the_same_base_call():
    assert not aprs_message_matches(
        "KC1JMH-9", "KC1JMH", [], filter_by_ssid=True, active_identity="KC1JMH-5"
    )


def test_strict_matches_an_alias_verbatim():
    assert aprs_message_matches(
        "KC1JMH-1",
        "KC1JMH",
        ["KC1JMH-1"],
        filter_by_ssid=True,
        active_identity="KC1JMH-5",
    )


def test_strict_is_case_insensitive():
    assert aprs_message_matches(
        "kc1jmh-5", "KC1JMH", [], filter_by_ssid=True, active_identity="KC1JMH-5"
    )


def test_strict_rejects_empty_addressee():
    assert not aprs_message_matches(
        "", "KC1JMH", [], filter_by_ssid=True, active_identity="KC1JMH-5"
    )


def test_lenient_falls_back_to_ssid_agnostic_matching():
    # filter_by_ssid=False is the explicit opt-out for an operator who wants
    # every message to any SSID of their call answered from one session.
    assert aprs_message_matches(
        "KC1JMH", "KC1JMH", [], filter_by_ssid=False, active_identity="KC1JMH-5"
    )
    assert aprs_message_matches(
        "KC1JMH-9", "KC1JMH", [], filter_by_ssid=False, active_identity="KC1JMH-5"
    )


def test_lenient_still_rejects_someone_elses_callsign():
    assert not aprs_message_matches(
        "K1XYZ", "KC1JMH", [], filter_by_ssid=False, active_identity="KC1JMH-5"
    )
