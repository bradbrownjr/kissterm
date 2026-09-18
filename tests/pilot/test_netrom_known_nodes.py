"""The NET/ROM picker is a passive suggestion, never a dial or send action."""

from kissterm._isolate import isolate

isolate()

import pytest
from textual.widgets import DataTable, Input

from kissterm.app import KissTermApp
from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams
from kissterm.ax25.frame import AX25Frame, PID_NETROM, UType
from kissterm.config import Config
from kissterm.ui.addressbook_pane import AddressBookPane
from kissterm.ui.dialogs import ConnectScreen
from tests.loopback import loopback_pair


def _broadcast() -> AX25Frame:
    address = lambda text: AX25Address.parse(text).encode()
    info = b"\xffSOURCE" + address("W1AW-1") + b"ARRL  " + address("N1ABC") + bytes([200])
    return AX25Frame.u_frame(
        AX25Path(AX25Address.parse("NODES"), AX25Address.parse("N1ABC")),
        UType.UI, pid=PID_NETROM, info=info,
    )


@pytest.mark.asyncio
async def test_received_broadcast_prefills_connect_dialog_without_dialing():
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    station = AX25Station(AX25Address.parse("N0CALL"), ta, LinkParams())
    app = KissTermApp(Config(mycall="N0CALL"), station)
    async with app.run_test(size=(120, 40)) as pilot:
        app._on_received_frame(_broadcast())
        await pilot.pause()
        await pilot.press("ctrl+g")
        await pilot.pause()
        table = app.query_one("#known-nodes-table", DataTable)
        assert table.row_count == 1
        send_input = app.query_one("#session-input", Input)
        send_input.value = "unrelated session text"
        app.query_one(AddressBookPane)._use_claimed_node()
        await pilot.pause()
        assert isinstance(app.screen, ConnectScreen)
        assert app.screen.query_one("#connect-target", Input).value == "W1AW-1"
        assert send_input.value == "unrelated session text"
        assert app.link is None
        assert not app.gate.enabled
        assert ta.sent == []
    station.close()
