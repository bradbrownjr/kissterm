"""`mail_waiting_for` -- the passive "MAIL FOR" beacon matcher.

Unverified against a real captured beacon (see the function's own docstring),
so these tests pin down the *documented* W0RLI/FBB convention rather than a
sample off the air: a "MAIL FOR" phrase followed by a callsign list.
"""

from __future__ import annotations

from kissterm.monitor import mail_waiting_for


def test_matches_an_exact_callsign_in_the_list():
    assert mail_waiting_for("MAIL FOR: W1AW K1ABC N1XYZ", ["K1ABC"]) == "K1ABC"


def test_matches_on_base_call_regardless_of_the_operators_ssid():
    # The mailbox addresses the base call; the operator's own session may be
    # running under an SSID that never appears in the beacon at all.
    assert mail_waiting_for("MAIL FOR: W1AW-15", ["W1AW-7"]) == "W1AW-15"


def test_matches_when_the_beacon_carries_no_ssid_but_we_do():
    assert mail_waiting_for("MAIL FOR: W1AW", ["W1AW-7"]) == "W1AW"


def test_case_insensitive():
    assert mail_waiting_for("mail for w1aw", ["W1AW"]) == "W1AW"


def test_no_match_when_our_call_is_absent():
    assert mail_waiting_for("MAIL FOR: K1ABC N1XYZ", ["W1AW"]) is None


def test_no_match_without_the_phrase_at_all():
    assert mail_waiting_for("Just some ordinary bulletin text about W1AW", ["W1AW"]) is None


def test_no_match_with_no_callsigns_configured():
    assert mail_waiting_for("MAIL FOR: W1AW", []) is None
    assert mail_waiting_for("MAIL FOR: W1AW", [""]) is None


def test_a_match_far_outside_the_scan_window_is_not_found():
    far = "MAIL FOR: " + ("K1ABC " * 40) + "W1AW"
    assert mail_waiting_for(far, ["W1AW"]) is None
