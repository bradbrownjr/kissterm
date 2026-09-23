"""Node-to-node hop chains and saved credentials, end to end.

The feature this pins down: for a station reachable only by connecting
through intermediate BPQ/NET-ROM nodes (no digipeater path exists), kissterm
sends "C <node>" over its one AX.25 link to the first node and watches for
that node's own CONNECTED reply before sending the next -- the same
send/wait-for-CONNECTED-or-BUSY loop the sibling `bpq-apps` project's
node-map crawler uses against real BPQ nodes. See `KissTermApp._hop_through`
and `_hop_to` in `kissterm/ui/app.py`.

The intermediate node is faked here as a second `AX25Station` on the loopback
peer transport, with an `on_data` relay that answers "C <node>" the way a
real BPQ node would -- kissterm never opens a second AX.25 link for this: the
whole chain rides the one link to the first node, exactly as it would on the
air.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402
import contextlib  # noqa: E402

import pytest  # noqa: E402

from kissterm.addressbook import AddressBook  # noqa: E402
from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.terminal_pane import TerminalPane  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")
#: The intermediate node kissterm connects to directly. Reusing a
#: recognisable call from the rest of the suite, not otherwise significant.
NODE = AX25Address.parse("WS1EC-7")


async def _app(config=None):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = config or Config(mycall=str(MYCALL))
    config.tx_armed_at_start = True
    # These tests are about the connect flow, not the layout. Left on, the
    # width rule opens the Address Book beside the session log, which halves
    # the column and soft-wraps the very lines being asserted on -- "*** No
    # connection to W1LH-6 -- no response within 0s" arrives as two rows and
    # a substring check for the phrase fails on a message that is on screen
    # and correct. Nothing here needs the panel open.
    config.slideouts_auto_open = False
    station = AX25Station(MYCALL, ta, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    return KissTermApp(config, station), station, tb


def _fresh_book(app, tmp_path) -> AddressBook:
    app.addressbook = AddressBook(tmp_path / "addressbook.json")
    return app.addressbook


def _install_relay(node: AX25Station, replies: dict[str, bytes], banner: bytes = b"") -> None:
    """Answer "C <NAME>" over the incoming link the way a real node would.

    `replies` maps an upper-cased command to the raw bytes to send back --
    a canned `*** CONNECTED to X` or `*** BUSY`, scripted per test.
    `banner`, when given, is sent the moment the link comes up, the way a
    real node greets a caller -- which is what kissterm's own passive node
    detection (`_sniff_node`) reads a family out of.
    """

    def _relay(data: bytes) -> None:
        cmd = data.decode("latin-1", "replace").strip().upper()
        reply = replies.get(cmd)
        if reply is None:
            return
        link = node.link_to(MYCALL)
        if link is not None:
            asyncio.get_event_loop().create_task(link.send(reply))

    def _greet(link) -> None:
        link.on_data.append(_relay)
        if not banner:
            return

        async def _send_banner() -> None:
            # A beat after the UA, not the same instant: the caller's link
            # object exists as soon as the UA lands, but the APP only
            # subscribes to it a moment later in `_bind_link`, and bytes
            # delivered in between reach no subscriber at all. A real node
            # composing and keying a greeting is not instant either.
            await asyncio.sleep(0.15)
            await link.send(banner)

        asyncio.get_event_loop().create_task(_send_banner())

    node.on_incoming.append(_greet)


async def _connect_via_history(app, pilot) -> None:
    """Open the Connect dialog and dial the one address-book entry every
    caller here has already recorded. Picks it from `#connect-address-book`
    directly rather than opening the dropdown's overlay and pressing Enter
    on it -- `ConnectScreen` no longer auto-highlights a "top" row the way
    the old `OptionList` did, and a `Select`'s overlay highlight is not
    something a pilot key press can rely on -- then clicks Connect exactly
    like an operator would, since picking a row now only fills the fields
    (see `ConnectScreen._pick_from_address_book`), it does not submit."""
    from textual.widgets import Select

    await pilot.press("ctrl+n")
    await pilot.pause()
    await asyncio.sleep(0.15)
    target = app.addressbook.entries[0].target
    app.screen.query_one("#connect-address-book", Select).value = target
    await pilot.pause()
    await pilot.click("#connect-go")
    await pilot.pause()


def _log_text(app) -> str:
    log = app.query_one(TerminalPane).query_one("#session-log")
    return "\n".join(str(line) for line in log.lines)


@pytest.mark.asyncio
async def test_a_two_hop_chain_reaches_the_target_then_logs_in(tmp_path):
    app, station, tb = await _app()
    book = _fresh_book(app, tmp_path)
    book.record_attempt("W1LH-6", script="MYPASS", hops="WS1EC-7")

    node = AX25Station(NODE, tb, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    _install_relay(node, {"C W1LH-6": b"*** CONNECTED to W1LH-6\r"})

    async with app.run_test(size=(120, 40)) as pilot:
        await _connect_via_history(app, pilot)
        await asyncio.sleep(1.5)  # first hop up, "C W1LH-6", reply, login line
        await pilot.pause()

        text = _log_text(app)
        assert "C W1LH-6" in text, text
        assert "CONNECTED to W1LH-6" in text, text
        assert "MYPASS" in text, text
        assert app.addressbook.entries[0].target == "W1LH-6"
        assert app.addressbook.entries[0].connects == 1
    node.close()
    station.close()


@pytest.mark.asyncio
async def test_a_hop_that_refuses_stops_the_chain_without_logging_in(tmp_path):
    """A BUSY from an intermediate node is a refusal, not silence -- the
    chain must stop immediately (never send the next hop's command into a
    link nothing confirmed is ready) and the login step must not run,
    since the actual target was never reached."""
    app, station, tb = await _app()
    book = _fresh_book(app, tmp_path)
    book.record_attempt("W1LH-6", script="MYPASS", hops="WS1EC-7")

    node = AX25Station(NODE, tb, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    _install_relay(node, {"C W1LH-6": b"*** BUSY\r"})

    async with app.run_test(size=(120, 40)) as pilot:
        await _connect_via_history(app, pilot)
        await asyncio.sleep(1.0)
        await pilot.pause()

        text = _log_text(app)
        assert "No connection to W1LH-6" in text, text
        assert "BUSY" in text, text
        assert "MYPASS" not in text, "logged in past a hop that refused"
        assert app.link is not None and app.link.connected, (
            "should still be connected to the first-hop node"
        )
        assert app.addressbook.entries[0].connects == 0, (
            "the target was never reached -- must not be recorded as connected"
        )
    node.close()
    station.close()


@pytest.mark.asyncio
async def test_a_refused_hop_leaves_the_node_we_are_still_on_identified(tmp_path):
    """A failed hop must cost nothing but the hop.

    The chain reporting failure is already covered above; what this pins
    down is the half found in live testing against a real BPQ32 node: the
    session is STILL talking to the first-hop node, so its identified
    family, its logical peer (which is what a later harvest is filed
    under), and its learned commands all have to survive the attempt
    untouched. Resetting detection when the command went out -- before
    anything confirmed the hop -- turned a correctly identified node into
    "unknown node" every time a hop was refused.
    """
    app, station, tb = await _app()
    book = _fresh_book(app, tmp_path)
    book.record_attempt("W1LH-6", hops="WS1EC-7")

    node = AX25Station(NODE, tb, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    _install_relay(
        node,
        {"C W1LH-6": b"*** BUSY\r"},
        banner=b"Welcome.\rCCEMA:WS1EC-15}\r",
    )

    async with app.run_test(size=(120, 40)) as pilot:
        await _connect_via_history(app, pilot)
        await asyncio.sleep(1.0)
        await pilot.pause()

        assert "No connection to W1LH-6" in _log_text(app)
        family = app.reference.family
        assert family is not None and family.id == "bpq32", (
            "a refused hop wiped the identification of the node we are still on"
        )
        assert app.current_node == str(NODE), (
            "a refused hop moved the logical peer -- a later harvest would be "
            "filed under a node that was never reached"
        )
    node.close()
    station.close()


@pytest.mark.asyncio
async def test_a_hop_that_stays_silent_times_out_distinctly_from_a_refusal(tmp_path):
    """Silence and an explicit refusal are different diagnoses (same
    reasoning as a DM versus an N2 timeout) and must not be reported with
    the same words."""
    from kissterm.ui import app as app_module

    app, station, tb = await _app()
    book = _fresh_book(app, tmp_path)
    book.record_attempt("W1LH-6", hops="WS1EC-7")
    node = AX25Station(NODE, tb, LinkParams(t1=0.3, t2=0.05, t3=5.0))
    # No relay installed at all -- the node hears "C W1LH-6" and says nothing.

    original_timeout = app_module.HOP_TIMEOUT
    app_module.HOP_TIMEOUT = 0.5
    try:
        async with app.run_test(size=(120, 40)) as pilot:
            await _connect_via_history(app, pilot)
            await asyncio.sleep(1.2)
            await pilot.pause()

            text = _log_text(app)
            assert "no response within" in text, text
            assert "BUSY" not in text and "FAILED" not in text, text
    finally:
        app_module.HOP_TIMEOUT = original_timeout
        node.close()
        station.close()


@pytest.mark.asyncio
async def test_a_saved_credential_is_looked_up_live_at_connect_time(tmp_path):
    """The point of a saved credential over a per-station script: change it
    once in Settings and every entry pointing at it uses the new text on its
    very next connect, with no per-entry re-save."""
    config = Config(mycall=str(MYCALL))
    config.credentials = [{"name": "Personal BBS login", "text": "OLDPASS"}]
    app, station, tb = await _app(config)
    book = _fresh_book(app, tmp_path)
    book.record_attempt("WS1EC-7", credential="Personal BBS login")

    peer = AX25Station(NODE, tb, LinkParams(t1=0.3, t2=0.05, t3=5.0))

    # Changed after the entry was saved -- proves the lookup is live, not a
    # copy taken when the entry was created.
    app.config.credentials[0]["text"] = "NEWPASS"

    async with app.run_test(size=(120, 40)) as pilot:
        await _connect_via_history(app, pilot)
        await asyncio.sleep(0.5)
        await pilot.pause()

        text = _log_text(app)
        assert "NEWPASS" in text, text
        assert "OLDPASS" not in text, text
    peer.close()
    station.close()


@pytest.mark.asyncio
async def test_a_plain_connect_announces_itself_clearly(tmp_path):
    """From a real report: connecting directly to a node with nothing to
    say until you type a command left NOTHING on screen resembling
    EasyTerm's "*** Connected to station X" -- `_on_link_state` cannot
    catch this particular transition, because `AX25Station.connect` only
    returns the link once it is already connected, which is after the one
    chance to register a callback on it. See the comment in
    `KissTermApp.action_connect` next to the fix.

    A second, real transcript pulled from this exact gap showed the
    durable ``* connected`` line arriving eleven seconds late -- timed to
    the NEXT state transition rather than the actual connect -- because
    the original fix wrote only to the terminal pane. This also asserts
    the transcript file itself carries the line, so that regression stays
    caught."""
    app, station, tb = await _app()
    book = _fresh_book(app, tmp_path)
    book.record_attempt("WS1EC-7")
    peer = AX25Station(NODE, tb, LinkParams(t1=0.3, t2=0.05, t3=5.0))

    async with app.run_test(size=(120, 40)) as pilot:
        await _connect_via_history(app, pilot)
        await asyncio.sleep(0.3)
        await pilot.pause()

        text = _log_text(app)
        assert "Connected to WS1EC-7" in text, text
        assert app.transcript is not None
        transcript_text = app.transcript.path.read_text()
        assert "Connected to WS1EC-7" in transcript_text, transcript_text
    peer.close()
    station.close()


@pytest.mark.asyncio
async def test_a_radio_reminder_blocks_the_connect_until_acknowledged(tmp_path):
    """kissterm cannot tune a radio or start a modem -- the reminder exists
    precisely so the operator sees the frequency/connection type BEFORE
    anything transmits, not after. Cancelling it must mean nothing goes
    out at all."""
    from kissterm.ui.dialogs import RadioReminderScreen

    app, station, tb = await _app()
    book = _fresh_book(app, tmp_path)
    book.upsert("WS1EC-7", frequency="146.520 MHz", connection_type="1200 AFSK")

    async with app.run_test(size=(120, 40)) as pilot:
        await _connect_via_history(app, pilot)
        await asyncio.sleep(0.1)
        await pilot.pause()

        assert isinstance(app.screen, RadioReminderScreen), type(app.screen).__name__

        await app.screen.dismiss(False)  # Cancel
        await pilot.pause()
        await asyncio.sleep(0.3)

        assert not station.transport.sent, "cancelling the reminder still transmitted"
        assert app.link is None
    station.close()


@pytest.mark.asyncio
async def test_acknowledging_the_radio_reminder_proceeds_with_the_connect(tmp_path):
    from kissterm.ui.dialogs import RadioReminderScreen

    app, station, tb = await _app()
    book = _fresh_book(app, tmp_path)
    book.upsert("WS1EC-7", frequency="146.520 MHz", connection_type="1200 AFSK")
    peer = AX25Station(NODE, tb, LinkParams(t1=0.3, t2=0.05, t3=5.0))

    async with app.run_test(size=(120, 40)) as pilot:
        await _connect_via_history(app, pilot)
        await asyncio.sleep(0.1)
        await pilot.pause()

        assert isinstance(app.screen, RadioReminderScreen)
        await pilot.click("#connect-go")
        await pilot.pause()
        await asyncio.sleep(0.5)

        assert not isinstance(app.screen, RadioReminderScreen)
        assert station.transport.sent, "acknowledging the reminder never transmitted"
        assert app.link is not None and app.link.connected
    peer.close()
    station.close()


@pytest.mark.asyncio
async def test_a_note_alone_also_triggers_the_reminder(tmp_path):
    """`Entry.note` is the same kind of thing as frequency/connection type --
    something the operator wrote down for next time -- so it must trigger
    the same pre-connect checkpoint even with no frequency or connection
    type set, and its text must actually be shown."""
    from kissterm.ui.dialogs import RadioReminderScreen

    app, station, tb = await _app()
    book = _fresh_book(app, tmp_path)
    book.upsert("WS1EC-7", note="BBS is on -2, chat needs a callsign")

    async with app.run_test(size=(120, 40)) as pilot:
        await _connect_via_history(app, pilot)
        await asyncio.sleep(0.1)
        await pilot.pause()

        assert isinstance(app.screen, RadioReminderScreen), type(app.screen).__name__
        assert app.screen._note == "BBS is on -2, chat needs a callsign"

        await app.screen.dismiss(False)  # Cancel
        await pilot.pause()
        await asyncio.sleep(0.3)

        assert not station.transport.sent, "cancelling the reminder still transmitted"
    station.close()


@pytest.mark.asyncio
async def test_no_reminder_when_neither_frequency_nor_connection_type_is_set(tmp_path):
    from kissterm.ui.dialogs import RadioReminderScreen

    app, station, tb = await _app()
    book = _fresh_book(app, tmp_path)
    book.record_attempt("WS1EC-7")
    peer = AX25Station(NODE, tb, LinkParams(t1=0.3, t2=0.05, t3=5.0))

    async with app.run_test(size=(120, 40)) as pilot:
        await _connect_via_history(app, pilot)
        await asyncio.sleep(0.5)
        await pilot.pause()

        assert not isinstance(app.screen, RadioReminderScreen)
        assert app.link is not None and app.link.connected
    peer.close()
    station.close()


@pytest.mark.asyncio
async def test_dialing_from_the_addressbook_pane_also_shows_the_reminder(tmp_path):
    """The reminder is a property of the connect flow itself, not of the
    Connect dialog -- dialing straight from the Address Book pane must not
    be a way to skip it."""
    from kissterm.ui.dialogs import RadioReminderScreen

    app, station, tb = await _app()
    book = _fresh_book(app, tmp_path)
    book.upsert("WS1EC-7", frequency="146.520 MHz", connection_type="1200 AFSK")

    async with app.run_test(size=(120, 40)) as pilot:
        entry = book.find("WS1EC-7")
        app.action_connect(prefill=entry)
        await asyncio.sleep(0.2)

        assert isinstance(app.screen, RadioReminderScreen), type(app.screen).__name__
        await pilot.pause()
        await pilot.click("#connect-go")
        await pilot.pause()
        await asyncio.sleep(0.1)

        assert not isinstance(app.screen, RadioReminderScreen)
        assert station.transport.sent
    station.close()


# ---------------------------------------------------------------------------
# Connect dialog transport picker -- same-tier only, see AGENTS.md 2a
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_transport_picker_is_hidden_with_only_one_transport():
    """The overwhelming common case: one TNC configured. A dropdown that
    can only ever show the transport already in use is not a control, it
    is decoration -- see `ConnectScreen`'s docstring."""
    from kissterm.ui.dialogs import ConnectScreen
    from textual.widgets import Select

    config = Config(mycall=str(MYCALL))
    config.transports = [{"kind": "tcp", "name": "only-one", "host": "10.0.0.2", "port": 8001}]
    config.active_transport = "only-one"
    app, station, tb = await _app(config)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("ctrl+n")
        await pilot.pause()
        assert isinstance(app.screen, ConnectScreen)
        assert len(app.screen.query("#connect-transport")) == 0
    station.close()


@pytest.mark.asyncio
async def test_picking_a_different_transport_switches_before_dialing():
    """Two configured KISS TNCs -- the case a real report asked for
    directly ("in case I have different modems"). Picking the OTHER one in
    the Connect dialog must actually open it and rebind the station before
    the SABM for the typed target goes anywhere, exactly like Settings'
    own Active-transport switch (`KissTermApp._switch_frame_transport`,
    shared by both)."""
    from kissterm.ui.dialogs import ConnectScreen
    from textual.widgets import Select

    async def handler(reader, writer):
        await reader.read(64)
        await asyncio.sleep(5.0)

    server_a = await asyncio.start_server(handler, "127.0.0.1", 0)
    server_b = await asyncio.start_server(handler, "127.0.0.1", 0)
    host, port_a = server_a.sockets[0].getsockname()[:2]
    _, port_b = server_b.sockets[0].getsockname()[:2]

    config = Config(mycall=str(MYCALL))
    config.tx_armed_at_start = True
    config.transports = [
        {"kind": "tcp", "name": "first", "host": host, "port": port_a},
        {"kind": "tcp", "name": "second", "host": host, "port": port_b},
    ]
    config.active_transport = "first"
    app, station, tb = await _app(config)

    try:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("ctrl+n")
            await pilot.pause()
            assert isinstance(app.screen, ConnectScreen)

            select = app.screen.query_one("#connect-transport", Select)
            assert select.value == "first"
            select.value = "second"

            for key in "WS1EC-7":
                await pilot.press(key if key != "-" else "minus")
            await pilot.press("enter")
            await asyncio.sleep(0.3)
            await pilot.pause()

            assert app.config.active_transport == "second"
            assert app.station.transport.info.detail == f"{host}:{port_b}", (
                app.station.transport.info.detail
            )
    finally:
        station.close()
        # The rebind leaves a second live transport behind -- see the
        # matching cleanup note in test_settings.py's version of this test.
        with contextlib.suppress(Exception):
            await app.station.transport.close()
        server_a.close()
        server_b.close()
        await server_a.wait_closed()
        await server_b.wait_closed()
