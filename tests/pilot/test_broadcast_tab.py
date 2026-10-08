"""The Terminal's Broadcast tab: the first tab, what was heard and sent
with no connection, a typed line broadcast, and a clicked callsign opening
the Connect dialog (never dialling)."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402
from textual.widgets import Input  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams  # noqa: E402
from kissterm.ax25.frame import AX25Frame, UType  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.dialogs import ConnectScreen  # noqa: E402
from kissterm.ui.terminal_pane import BROADCAST_TAB, TerminalPane  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402
from tests.pilot._wait import wait_for  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")


def _ui(to: str, text: bytes, source: str = "W1BKW") -> AX25Frame:
    return AX25Frame.u_frame(AX25Path(AX25Address.parse(to), AX25Address.parse(source), ()),
                             UType.UI, command=False, info=text)


async def _app():
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    station = AX25Station(MYCALL, ta, LinkParams())
    return KissTermApp(Config(mycall=str(MYCALL), log_sessions=False), station), ta, tb


def _log_text(pane) -> str:
    return "\n".join(str(r) for r, _expand in pane._buffers[""])


@pytest.mark.asyncio
async def test_broadcast_is_the_first_tab_and_shows_what_is_heard():
    app, ta, tb = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        assert pane._tabs().active == BROADCAST_TAB and pane.active_session_key == ""
        await tb.send_frame(_ui("MAIL", b"MAIL FOR: N1ABC KC1XYZ"))
        await wait_for(lambda: "MAIL FOR: N1ABC" in _log_text(pane), "the mail-for beacon")
        assert "W1BKW > MAIL" in _log_text(pane)


@pytest.mark.asyncio
async def test_a_typed_line_is_broadcast_on_enter_and_a_prefix_picks_the_address():
    app, ta, tb = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        field = pane.query_one("#session-input", Input)
        field.value = "Net check, 7 PM"
        await pilot.pause()
        assert ta.sent == [], "typing transmits nothing"
        field.focus()
        await pilot.press("enter")
        await wait_for(lambda: len([f for f in ta.sent if f.utype is UType.UI]) == 1, "the broadcast")
        assert str(ta.sent[0].path.destination) == "CQ" and ta.sent[0].info == b"Net check, 7 PM"
        assert field.value == "" and app.gate.enabled
        field.value = "QST: Net at 7"
        await pilot.press("enter")
        await wait_for(lambda: len(ta.sent) == 2, "the second broadcast")
        assert str(ta.sent[1].path.destination) == "QST" and ta.sent[1].info == b"Net at 7"
        await wait_for(lambda: "you > QST: Net at 7" in _log_text(pane), "it listed as sent")


@pytest.mark.asyncio
async def test_clicking_a_heard_callsign_opens_the_connect_dialog_and_dials_nothing():
    app, ta, tb = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        pane = app.query_one(TerminalPane)
        app.action_show_tab("terminal")
        await pilot.pause()
        await tb.send_frame(_ui("CQ", b"anyone on?", source="W1BKW"))
        await wait_for(lambda: "anyone on?" in _log_text(pane), "the broadcast")
        await pilot.pause()
        await pilot.click("#session-log", offset=(8, 1))  # "HH:MM " is 6 cells, then W1BKW
        await wait_for(lambda: isinstance(app.screen, ConnectScreen), "the Connect dialog")
        assert "W1BKW" in str(app.screen.query_one("#connect-target", Input).value).upper()
        assert [f for f in ta.sent if f.utype is not UType.UI] == [], "nothing was dialled"
