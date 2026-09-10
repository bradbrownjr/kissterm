"""Multiple simultaneous connections, one tab each, on the Terminal pane.

`AX25Station` has always been able to hold more than one link at once --
`self.links` is a dict keyed by peer, not a single slot. What was missing was
the UI: `KissTermApp.link`/`.reference`/`.transcript` used to be one slot
apiece, so a second connection silently clobbered the view of the first (see
`kissterm/ui/app.py` and `kissterm/ui/terminal_pane.py`'s module docstrings).
These tests are the guarantee that fix actually holds: two sessions really do
stay independent -- their scrollback, their unread marker, their node
reference -- and the cap that stops a third is real.

`_bare_app()` builds a station with NOBODY on the other end of its
transport -- `LoopbackTransport.peer` is left `None`, so a UA this station
sends goes nowhere and nothing can react to it unexpectedly. Incoming SABMs
are crafted by hand and fed straight into `station._on_frame`, the same
technique `tests/unit/test_station_max_links.py` uses at the station layer --
here it drives the UI layer on top of it instead.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402

import pytest  # noqa: E402
from textual.widgets import Input, Static  # noqa: E402

from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams  # noqa: E402
from kissterm.ax25.frame import AX25Frame, UType  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.nodes import CommandReference, load_family  # noqa: E402
from kissterm.ui.app import KissTermApp  # noqa: E402
from kissterm.ui.terminal_pane import MAX_TERMINAL_TABS, TerminalPane  # noqa: E402
from tests.loopback import LoopbackTransport  # noqa: E402

MYCALL = AX25Address.parse("N1ABC-1")


def _caller(n: int) -> AX25Address:
    return AX25Address.parse(f"W1AW-{n}")


def _sabm(peer: AX25Address) -> AX25Frame:
    return AX25Frame.u_frame(AX25Path(MYCALL, peer), UType.SABM, pf=True, command=True)


async def _bare_app(max_links: int = MAX_TERMINAL_TABS):
    ta = LoopbackTransport("A")
    await ta.open()
    station = AX25Station(
        MYCALL, ta, LinkParams(t1=0.3, t2=0.05, t3=5.0), max_links=max_links
    )
    config = Config(mycall=str(MYCALL))
    config.tx_armed_at_start = True
    app = KissTermApp(config, station)
    return app, station, ta


@pytest.mark.asyncio
async def test_a_single_session_shows_no_tab_strip():
    """Today's exact look, untouched -- the strip only earns its place once
    there is something for it to distinguish."""
    app, station, ta = await _bare_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await station._on_frame(_sabm(_caller(1)), 0)
        await pilot.pause()

        pane = app.query_one(TerminalPane)
        assert pane.session_count == 1
        assert pane._tabs().display is False
    station.close()


@pytest.mark.asyncio
async def test_a_second_incoming_call_opens_a_tab_without_stealing_the_view():
    app, station, ta = await _bare_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await station._on_frame(_sabm(_caller(1)), 0)
        await pilot.pause()
        await station._on_frame(_sabm(_caller(2)), 0)
        await pilot.pause()

        pane = app.query_one(TerminalPane)
        assert pane.session_count == 2
        assert pane._tabs().display is True
        assert pane.active_session_key == "W1AW-1", (
            "the second caller must not move the screen out from under the first"
        )
        assert "W1AW-2" in pane._unread
    station.close()


@pytest.mark.asyncio
async def test_each_sessions_scrollback_stays_independent():
    """The bug this whole feature exists to fix: a second connection must
    not overwrite -- or bleed into -- the first one's transcript on screen.
    """
    app, station, ta = await _bare_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await station._on_frame(_sabm(_caller(1)), 0)
        await pilot.pause()
        app._on_link_data("W1AW-1", b"hello from station one\r")
        await asyncio.sleep(0.3)
        await pilot.pause()

        await station._on_frame(_sabm(_caller(2)), 0)
        await pilot.pause()
        # Still on the first tab -- writes to the SECOND session must not
        # land on screen, only in its own (background) buffer.
        app._on_link_data("W1AW-2", b"hello from station two\r")
        await asyncio.sleep(0.3)
        await pilot.pause()

        pane = app.query_one(TerminalPane)
        log = pane.query_one("#session-log")
        shown = "\n".join(str(line) for line in log.lines)
        assert "hello from station one" in shown
        assert "hello from station two" not in shown

        pane.activate_tab("W1AW-2")
        await pilot.pause()
        log = pane.query_one("#session-log")
        shown = "\n".join(str(line) for line in log.lines)
        assert "hello from station two" in shown
        assert "hello from station one" not in shown
        assert "W1AW-2" not in pane._unread, "activating a tab must clear its unread mark"
    station.close()


@pytest.mark.asyncio
async def test_the_cap_dms_a_caller_past_max_terminal_tabs():
    """Station-level enforcement is `tests/unit/test_station_max_links.py`'s
    job; this is the UI-visible half -- the extra tab simply never appears.
    """
    app, station, ta = await _bare_app(max_links=2)
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        for n in (1, 2):
            await station._on_frame(_sabm(_caller(n)), 0)
            await pilot.pause()

        pane = app.query_one(TerminalPane)
        assert pane.session_count == 2

        await station._on_frame(_sabm(_caller(3)), 0)
        await pilot.pause()

        assert pane.session_count == 2, "a third caller must not get a tab"
        assert ta.sent[-1].utype is UType.DM
    station.close()


@pytest.mark.asyncio
async def test_delete_disconnects_first_then_closes_the_tab():
    app, station, ta = await _bare_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await station._on_frame(_sabm(_caller(1)), 0)
        await pilot.pause()
        await station._on_frame(_sabm(_caller(2)), 0)
        await pilot.pause()

        pane = app.query_one(TerminalPane)
        pane.activate_tab("W1AW-2")
        await pilot.pause()
        assert pane.session_count == 2

        pane._tabs().focus()
        await pilot.press("delete")
        await asyncio.sleep(0.2)
        await pilot.pause()

        # First Delete: a DISC went out, the tab is still there reading the
        # disconnect note.
        assert pane.session_count == 2, "the first Delete must disconnect, not close"
        log = pane.query_one("#session-log")
        shown = "\n".join(str(line) for line in log.lines)
        assert "Disconnecting" in shown

        await asyncio.sleep(0.3)
        await pilot.pause()
        pane._tabs().focus()
        await pilot.press("delete")
        await pilot.pause()

        assert pane.session_count == 1, "the second Delete must close the tab"
        assert pane.active_session_key == "W1AW-1"
    station.close()


@pytest.mark.asyncio
async def test_two_outgoing_connects_stay_on_separate_tabs():
    """Drives `AX25Station.connect` directly for two different peers (the
    same shortcut `test_terminal_ux.py` uses to reach a connected link
    without the Connect dialog), completing each by hand-feeding its UA --
    there is no second real station on the other end of this loopback, so
    nothing else could answer it. Proves `KissTermApp._bind_link` keeps two
    concurrently-connecting sessions apart by key rather than by "whichever
    connect finishes last".
    """
    app, station, ta = await _bare_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()

        peer1, peer2 = _caller(1), _caller(2)
        task1 = asyncio.ensure_future(station.connect(AX25Path(peer1, MYCALL)))
        await asyncio.sleep(0.05)
        await station._on_frame(
            AX25Frame.u_frame(AX25Path(MYCALL, peer1), UType.UA, pf=True, command=False), 0
        )
        link1 = await task1
        assert link1 is not None and link1.connected
        app._bind_link(link1)
        await pilot.pause()

        task2 = asyncio.ensure_future(station.connect(AX25Path(peer2, MYCALL)))
        await asyncio.sleep(0.05)
        await station._on_frame(
            AX25Frame.u_frame(AX25Path(MYCALL, peer2), UType.UA, pf=True, command=False), 0
        )
        link2 = await task2
        assert link2 is not None and link2.connected
        app._bind_link(link2)
        await pilot.pause()

        pane = app.query_one(TerminalPane)
        assert pane.session_count == 2
        assert pane.active_session_key == "W1AW-2", "binding a link activates its own tab"
        assert app.link is link2

        pane.activate_tab("W1AW-1")
        await pilot.pause()
        assert app.link is link1, "app.link must follow the tab on screen, not the last bind"
    station.close()


@pytest.mark.asyncio
async def test_the_suggestion_strip_follows_the_active_sessions_reference():
    """`self.app.reference` is session-scoped (see the module docstring);
    the suggestion strip must be recomputed on every tab switch or it would
    keep suggesting the previous tab's node's commands -- see
    `TerminalPane._update_suggestions`'s call from `activate_tab`.
    """
    app, station, ta = await _bare_app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        await station._on_frame(_sabm(_caller(1)), 0)
        await station._on_frame(_sabm(_caller(2)), 0)
        await pilot.pause()

        pane = app.query_one(TerminalPane)
        strip = pane.query_one("#suggestion-strip", Static)
        field = pane.query_one("#session-input", Input)

        pane.activate_tab("W1AW-1")
        await pilot.pause()
        app.reference = CommandReference(family=load_family("bpq32"))
        field.value = "c"
        await pilot.pause()
        assert strip.display is True, "W1AW-1's own reference should match 'c'"

        pane.activate_tab("W1AW-2")
        await pilot.pause()
        assert strip.display is False, (
            "W1AW-2 has no reference of its own -- the strip must not keep "
            "showing W1AW-1's matches for it"
        )

        pane.activate_tab("W1AW-1")
        await pilot.pause()
        assert strip.display is True, "switching back must recompute from the input still there"
    station.close()
