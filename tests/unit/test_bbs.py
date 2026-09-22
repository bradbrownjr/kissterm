"""BBS helper data is deliberately pure: no BBS reply parser and no I/O."""

from __future__ import annotations

import pytest

from kissterm.bbs import complete, profile, profiles


def test_bpqmail_covers_list_read_and_send_workflow():
    helper = profile("bpqmail")
    assert helper is not None
    assert {macro.id for macro in helper.macros} == {"list-mine", "list-new", "list-bulletins", "read", "send"}
    macros = {macro.id: macro for macro in helper.macros}
    assert macros["list-mine"].render() == "LM"
    assert macros["list-new"].render() == "LN"
    assert macros["list-bulletins"].render() == "LB"
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
        ("LM", "List Mine"),
        ("LN", "List unread/new messages"),
        ("LB", "List Bulletins"),
    ]
    assert complete("R") == (), "read needs a message number and belongs in the picker"
