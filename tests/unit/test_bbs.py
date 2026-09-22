"""BBS helper data is deliberately pure: no BBS reply parser and no I/O."""

from __future__ import annotations

import pytest

from kissterm.bbs import profile, profiles


def test_bpqmail_covers_list_read_and_send_workflow():
    helper = profile("bpqmail")
    assert helper is not None
    assert {macro.id for macro in helper.macros} == {"list-mine", "list-new", "read", "send"}
    macros = {macro.id: macro for macro in helper.macros}
    assert macros["list-mine"].render() == "LM"
    assert macros["list-new"].render() == "LN"
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
