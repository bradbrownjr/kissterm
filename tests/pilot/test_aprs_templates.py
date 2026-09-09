"""The APRS service/template picker: it fills the compose box, it never sends.

The assertion this file exists for is `test_choosing_a_template_from_every_
shipped_service_transmits_nothing`, backed by the static
`test_the_picker_has_no_transmit_path_at_all`. kissterm ships seventeen
gateway services with well over a hundred command templates between them,
several of which do something real
and public when they arrive -- APSPOT posts a spot the world can see, SMSGTE
texts a phone. A picker that could transmit on selection would turn browsing
into acting, which AGENTS.md already forbids for the terminal's command
reference ("a completion that transmits on its own is a defect on a shared
channel"). The rest of the file is the surrounding behaviour.

Same loopback shape as `test_aprs_send.py`; see that module's docstring.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402
from textual.widgets import DataTable, Input  # noqa: E402

from kissterm import aprs_services  # noqa: E402
from kissterm.app import KissTermApp  # noqa: E402
from kissterm.aprs_conversations import ConversationStore  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.aprs_pane import AprsPane  # noqa: E402
from kissterm.ui.dialogs import AprsServiceScreen  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
PEER = AX25Address.parse("WS1EC-15")


async def _app(tmp_path, config=None):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = config or Config(mycall=str(MYCALL))
    config.mycall = str(MYCALL)
    # Transmit ARMED on purpose. A picker that cannot transmit because the
    # gate is shut would prove nothing about the picker -- the point is that
    # it sends nothing even when it could.
    config.tx_armed_at_start = True
    params = LinkParams(t1=0.3, t2=0.05, t3=5.0, retries=2)
    mine = AX25Station(MYCALL, ta, params)
    AX25Station(PEER, tb, params)
    app = KissTermApp(config, mine)
    app.aprs_conversations = ConversationStore(tmp_path / "aprs_messages.json")
    return app, mine, ta


async def _aprs_tab(app, pilot):
    app.action_show_tab("aprs")
    await pilot.pause()
    await asyncio.sleep(0.05)


async def _open_picker(app, pilot, addressee):
    pane = app.query_one(AprsPane)
    app.query_one("#aprs-to-input", Input).value = addressee
    pane.show_templates()
    await pilot.pause()
    await asyncio.sleep(0.05)
    return pane


# ---------------------------------------------------------------------------
# The one that matters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_choosing_a_template_from_every_shipped_service_transmits_nothing(tmp_path):
    """Open the picker for each of the seventeen services, select a real row
    through the table's own selection handler, and confirm the transmitter
    never keyed.

    Driven through `on_data_table_row_selected` -- what a click or Enter
    actually reaches -- rather than by assigning to the input, which would
    prove only that assignment works. The gate is OPEN throughout: the point
    is that browsing sends nothing even when sending is possible.
    """
    app, station, transport = await _app(tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        await _aprs_tab(app, pilot)
        compose = app.query_one("#aprs-compose-input", Input)

        checked = 0
        for service in aprs_services.load_all():
            compose.value = ""
            await _open_picker(app, pilot, service.callsign)
            screen = app.screen
            assert isinstance(screen, AprsServiceScreen), type(screen).__name__

            table = screen.query_one("#aprs-service-table", DataTable)
            assert table.row_count, f"{service.id} rendered no rows"
            row_key, _ = table.coordinate_to_cell_key((0, 0))
            expected = screen._rows[str(row_key.value)]

            screen.on_data_table_row_selected(
                DataTable.RowSelected(table, 0, row_key)
            )
            await pilot.pause()
            await asyncio.sleep(0.05)

            assert compose.value == expected, f"{service.id} did not fill the box"
            assert transport.sent == [], f"{service.id} transmitted on selection"
            checked += 1

        assert checked == len(aprs_services.load_all()) >= 15
    station.close()


def test_the_picker_has_no_transmit_path_at_all():
    """Asserted against the source, like
    `test_send_line_is_the_only_transmit_path_in_the_pane` -- the failure
    guarded against is someone later wiring selection straight to the send
    path, which would look perfectly ordinary in a diff.

    `AprsPane` may transmit; that is its job. The screen may not, and the
    pane's template handler must only ever fill the input.
    """
    import ast
    import inspect
    import textwrap

    from kissterm.ui import dialogs

    def code_only(obj) -> str:
        """The source with docstrings and comments removed.

        Both of these modules explain in prose exactly which send path they
        are NOT on, so a naive substring search matches the documentation
        that exists to prevent the bug. Strip it and look at what runs.
        """
        tree = ast.parse(textwrap.dedent(inspect.getsource(obj)))
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if not isinstance(body, list) or not body:
                continue
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                if isinstance(first.value.value, str):
                    del body[0]
        return ast.unparse(tree)

    screen = code_only(dialogs.AprsServiceScreen)
    for forbidden in ("_send_aprs_message", "send_frame", "send_line", "link.send"):
        assert forbidden not in screen, (
            f"AprsServiceScreen calls {forbidden!r} -- the picker must fill "
            f"the compose input and nothing else"
        )

    handler = code_only(AprsPane.show_templates)
    assert "_send_aprs_message" not in handler
    assert "field.value = chosen" in handler


@pytest.mark.asyncio
async def test_picking_a_template_fills_the_compose_box_and_sends_nothing(tmp_path):
    """The real end-to-end path: open the picker, dismiss it with a template,
    and confirm the text landed in the input with nothing on the air."""
    app, station, transport = await _app(tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        await _aprs_tab(app, pilot)
        await _open_picker(app, pilot, "WLNK-1")

        assert isinstance(app.screen, AprsServiceScreen), type(app.screen).__name__
        await app.screen.dismiss("SP <email/callsign/alias> <subject>")
        await pilot.pause()
        await asyncio.sleep(0.05)

        assert app.query_one("#aprs-compose-input", Input).value == (
            "SP <email/callsign/alias> <subject>"
        )
        assert transport.sent == []
    station.close()


# ---------------------------------------------------------------------------
# Which service the picker resolves to
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_picker_resolves_the_service_from_the_addressee(tmp_path):
    app, station, _ = await _app(tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        await _aprs_tab(app, pilot)
        await _open_picker(app, pilot, "WXBOT")

        screen = app.screen
        assert isinstance(screen, AprsServiceScreen)
        assert screen._service is not None
        assert screen._service.id == "wxbot"
        # The description is on screen, not just in the data file.
        assert screen._service.summary in screen._title() or screen._note()
        await screen.dismiss(None)
    station.close()


@pytest.mark.asyncio
async def test_a_contacts_own_gateway_wins_over_the_callsign_table(tmp_path):
    """An operator who deliberately said "this contact is WXBOT" is more
    authoritative than the shipped callsign table -- and this is also how a
    gateway reachable at an unlisted callsign gets its commands."""
    config = Config(
        mycall=str(MYCALL),
        aprs_contacts=[
            {"name": "Local weather", "callsign": "N0AAA-3", "gateway": "wxbot"}
        ],
    )
    app, station, _ = await _app(tmp_path, config)
    async with app.run_test(size=(140, 45)) as pilot:
        await _aprs_tab(app, pilot)
        await _open_picker(app, pilot, "N0AAA-3")

        screen = app.screen
        assert isinstance(screen, AprsServiceScreen)
        assert screen._service is not None and screen._service.id == "wxbot"
        await screen.dismiss(None)
    station.close()


@pytest.mark.asyncio
async def test_an_unknown_addressee_still_offers_the_operators_own_messages(tmp_path):
    """Messaging a friend is not a reason to have no picker -- the operator's
    global saved lines apply to everyone."""
    config = Config(
        mycall=str(MYCALL),
        aprs_templates=[{"name": "Check-in", "text": "QRV, monitoring 146.520"}],
    )
    app, station, _ = await _app(tmp_path, config)
    async with app.run_test(size=(140, 45)) as pilot:
        await _aprs_tab(app, pilot)
        await _open_picker(app, pilot, "K1ABC-9")

        screen = app.screen
        assert isinstance(screen, AprsServiceScreen)
        assert screen._service is None
        assert [m.name for m in screen._saved] == ["Check-in"]
        # And it says WHY there are no command templates, rather than just
        # showing an empty table.
        assert "kissterm ships" in screen._note()
        await screen.dismiss(None)
    station.close()


@pytest.mark.asyncio
async def test_a_scoped_saved_message_only_shows_for_its_own_service(tmp_path):
    config = Config(
        mycall=str(MYCALL),
        aprs_templates=[
            {"name": "My SP line", "text": "SP me@example.com hi", "gateway": "winlink"},
            {"name": "Global", "text": "QRV"},
        ],
    )
    app, station, _ = await _app(tmp_path, config)
    async with app.run_test(size=(140, 45)) as pilot:
        await _aprs_tab(app, pilot)

        await _open_picker(app, pilot, "WLNK-1")
        screen = app.screen
        # Scoped first, then global -- someone composing to WLNK-1 wants
        # their Winlink line before their generic check-in.
        assert [m.name for m in screen._saved] == ["My SP line", "Global"]
        await screen.dismiss(None)
        await pilot.pause()

        await _open_picker(app, pilot, "WXBOT")
        screen = app.screen
        assert [m.name for m in screen._saved] == ["Global"]
        await screen.dismiss(None)
    station.close()


# ---------------------------------------------------------------------------
# The table itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_table_shows_provenance_for_every_shipped_command(tmp_path):
    """`confidence` is the honest answer to "can I trust this enough to spend
    airtime on it?" -- several shipped lines are `recalled`, not
    `documented`, and hiding that would make the picker worse than none."""
    app, station, _ = await _app(tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        await _aprs_tab(app, pilot)
        await _open_picker(app, pilot, "QRX")

        table = app.screen.query_one("#aprs-service-table", DataTable)
        assert table.row_count > 0
        sources = {str(table.get_cell_at((r, 4))) for r in range(table.row_count)}
        assert sources <= set(aprs_services.CONFIDENCE_ORDER) | {"saved"}
        # QRX ships a mix on purpose; if this ever collapses to one value,
        # provenance got flattened.
        assert "recalled" in sources
        await app.screen.dismiss(None)
    station.close()


@pytest.mark.asyncio
async def test_the_search_box_narrows_the_table(tmp_path):
    app, station, _ = await _app(tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        await _aprs_tab(app, pilot)
        await _open_picker(app, pilot, "WXBOT")

        screen = app.screen
        table = screen.query_one("#aprs-service-table", DataTable)
        everything = table.row_count

        screen.query_one("#aprs-service-search", Input).value = "metar"
        await pilot.pause()
        assert 0 < table.row_count < everything

        screen.query_one("#aprs-service-search", Input).value = ""
        await pilot.pause()
        assert table.row_count == everything
        await screen.dismiss(None)
    station.close()


@pytest.mark.asyncio
async def test_the_operators_own_messages_sort_above_the_shipped_commands(tmp_path):
    """Someone who took the trouble to save a line wants it more often than
    any one shipped command."""
    config = Config(
        mycall=str(MYCALL),
        aprs_templates=[{"name": "Mine", "text": "L", "gateway": "winlink"}],
    )
    app, station, _ = await _app(tmp_path, config)
    async with app.run_test(size=(140, 45)) as pilot:
        await _aprs_tab(app, pilot)
        await _open_picker(app, pilot, "WLNK-1")

        table = app.screen.query_one("#aprs-service-table", DataTable)
        assert str(table.get_cell_at((0, 1))) == "Mine"
        assert str(table.get_cell_at((0, 4))) == "saved"
        await app.screen.dismiss(None)
    station.close()


# ---------------------------------------------------------------------------
# Ctrl+R dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ctrl_r_opens_the_service_picker_on_the_aprs_tab(tmp_path):
    app, station, _ = await _app(tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        await _aprs_tab(app, pilot)
        app.query_one("#aprs-to-input", Input).value = "WLNK-1"

        app.action_command_reference()
        await pilot.pause()
        await asyncio.sleep(0.1)

        assert isinstance(app.screen, AprsServiceScreen), type(app.screen).__name__
        await app.screen.dismiss(None)
    station.close()


@pytest.mark.asyncio
async def test_ctrl_r_on_the_terminal_tab_is_unchanged(tmp_path):
    """The whole point of reusing the key is that the terminal's own command
    reference keeps working exactly as before."""
    from kissterm.ui.dialogs import CommandReferenceScreen

    app, station, _ = await _app(tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        app.action_show_tab("terminal")
        await pilot.pause()

        app.action_command_reference()
        await pilot.pause()
        await asyncio.sleep(0.1)

        assert isinstance(app.screen, CommandReferenceScreen), type(app.screen).__name__
        await app.screen.dismiss(None)
    station.close()


@pytest.mark.asyncio
async def test_ctrl_r_on_another_tab_still_shows_the_node_reference(tmp_path):
    """Only the APRS tab diverts it. Monitor, Heard and Settings keep the
    old behaviour rather than becoming dead keys."""
    from kissterm.ui.dialogs import CommandReferenceScreen

    app, station, _ = await _app(tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        app.action_show_tab("monitor")
        await pilot.pause()

        app.action_command_reference()
        await pilot.pause()
        await asyncio.sleep(0.1)

        assert isinstance(app.screen, CommandReferenceScreen), type(app.screen).__name__
        await app.screen.dismiss(None)
    station.close()


# ---------------------------------------------------------------------------
# Saving the operator's own messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_saving_a_message_persists_it_and_shows_it_in_the_picker(tmp_path):
    from kissterm.aprs_contacts import CannedMessage
    from kissterm.ui.dialogs import AprsCannedMessageScreen

    app, station, transport = await _app(tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        await _aprs_tab(app, pilot)
        await _open_picker(app, pilot, "WLNK-1")
        screen = app.screen

        screen.action_new_message()
        await pilot.pause()
        await asyncio.sleep(0.05)
        assert isinstance(app.screen, AprsCannedMessageScreen), type(app.screen).__name__
        # A new message defaults to the service being viewed -- that is the
        # "attach it to the contact" half of the request.
        assert app.screen._gateway == "winlink"
        await app.screen.dismiss(CannedMessage(name="Mine", text="L", gateway="winlink"))
        await pilot.pause()
        await asyncio.sleep(0.05)

        assert app.config.aprs_templates == [
            {"name": "Mine", "text": "L", "gateway": "winlink"}
        ]
        table = screen.query_one("#aprs-service-table", DataTable)
        assert str(table.get_cell_at((0, 1))) == "Mine"
        assert transport.sent == []
        await screen.dismiss(None)
    station.close()


@pytest.mark.asyncio
async def test_forgetting_a_saved_message_removes_the_right_one(tmp_path):
    """Matched on content, not on a row index. The picker shows a filtered,
    re-ordered view (scoped before global, saved before shipped), so a
    position in it is not a position in the config list -- using one as the
    other is how an edit silently rewrites the wrong entry."""
    config = Config(
        mycall=str(MYCALL),
        aprs_templates=[
            {"name": "Global", "text": "QRV", "gateway": ""},
            {"name": "Winlink", "text": "L", "gateway": "winlink"},
        ],
    )
    app, station, _ = await _app(tmp_path, config)
    async with app.run_test(size=(140, 45)) as pilot:
        await _aprs_tab(app, pilot)
        await _open_picker(app, pilot, "WLNK-1")
        screen = app.screen

        # Row 0 of the VIEW is "Winlink" (scoped sorts first), which is
        # index 1 of the config list.
        table = screen.query_one("#aprs-service-table", DataTable)
        table.cursor_coordinate = (0, 0)
        assert str(table.get_cell_at((0, 1))) == "Winlink"

        screen.action_forget_message()
        await pilot.pause()

        assert app.config.aprs_templates == [
            {"name": "Global", "text": "QRV", "gateway": ""}
        ]
        await screen.dismiss(None)
    station.close()


@pytest.mark.asyncio
async def test_a_shipped_command_cannot_be_edited_or_forgotten(tmp_path):
    """Shipped data is not the operator's to change from here, and Delete on
    one must not silently eat a saved message instead."""
    config = Config(
        mycall=str(MYCALL),
        aprs_templates=[{"name": "Mine", "text": "L", "gateway": "winlink"}],
    )
    app, station, _ = await _app(tmp_path, config)
    async with app.run_test(size=(140, 45)) as pilot:
        await _aprs_tab(app, pilot)
        await _open_picker(app, pilot, "WLNK-1")
        screen = app.screen

        table = screen.query_one("#aprs-service-table", DataTable)
        # Row 1 is the first shipped command -- row 0 is the saved message.
        table.cursor_coordinate = (1, 0)
        assert screen._selected_saved_index() is None

        screen.action_forget_message()
        await pilot.pause()
        assert app.config.aprs_templates == [
            {"name": "Mine", "text": "L", "gateway": "winlink"}
        ]
        await screen.dismiss(None)
    station.close()
