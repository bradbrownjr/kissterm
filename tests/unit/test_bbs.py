"""BBS helper data is deliberately pure: no BBS reply parser and no I/O."""

from __future__ import annotations

import pytest

from kissterm.bbs import complete, profile, profiles


def test_bpqmail_covers_list_read_and_send_workflow():
    helper = profile("bpqmail")
    assert helper is not None
    assert {macro.id for macro in helper.macros} == {
        "list-new", "list-new-oldest", "list-mine", "list-new-status",
        "list-held", "list-killed", "list-forwarded", "list-delivered",
        "list-bulletins", "list-personal", "list-traffic", "list-categories",
        "list-last", "bye", "read", "send",
    }
    macros = {macro.id: macro for macro in helper.macros}
    assert macros["list-new"].render() == "L"
    assert macros["list-mine"].render() == "LM"
    assert macros["list-new-status"].render() == "LN"
    assert macros["list-bulletins"].render() == "LB"
    assert macros["list-delivered"].render() == "LD"
    assert macros["list-forwarded"].render() == "LF"
    assert macros["list-held"].render() == "LH"
    assert macros["list-killed"].render() == "LK"
    assert macros["list-last"].render(number="20") == "LL 20"
    assert macros["bye"].render() == "B"
    assert macros["read"].render(number="42") == "R 42"
    assert macros["send"].render(callsign="N1ABC-7") == "SP N1ABC-7"


def test_macro_parameters_cannot_inject_an_extra_bbs_command():
    helper = profiles()[0]
    read = next(macro for macro in helper.macros if macro.id == "read")
    send = next(macro for macro in helper.macros if macro.id == "send")
    with pytest.raises(ValueError, match="digits"):
        read.render(number="12; K 12")
    with pytest.raises(ValueError, match="control"):
        send.render(callsign="N1ABC\rBYE")


def test_unknown_profile_is_not_guessed():
    assert profile("some-new-bbs") is None


def test_list_macros_complete_with_their_operator_facing_descriptions():
    matches = complete("l")
    assert [(macro.name, macro.summary) for macro in matches] == [
        ("L", "List new messages"),
        ("LR", "List new messages, oldest first"),
        ("LM", "List Mine"),
        ("LN", "List messages with N status"),
        ("LH", "List Held messages"),
        ("LK", "List Killed messages"),
        ("LF", "List Forwarded messages"),
        ("LD", "List Delivered messages"),
        ("LB", "List Bulletins"),
        ("LP", "List Personal messages"),
        ("LT", "List Traffic (NTS messages)"),
        ("LC", "List active bulletin TO fields"),
        ("LL", "List the last N messages"),
    ]
    assert [(macro.name, macro.summary) for macro in complete("R")] == [
        ("R", "Read one numbered message"),
    ]
    assert [(macro.name, macro.summary) for macro in complete("BYE")] == [
        ("B", "BYE — disconnect from BBS")
    ]
