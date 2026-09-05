"""The Settings pane: everything setup asks for must be editable in-app.

The pane is generated from `settings_schema.SETTINGS_SCHEMA`, so the most
valuable test here is the coverage one -- it fails when someone adds a config
option and forgets the UI, which is exactly how the first version of this pane
went stale on the day it shipped.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import asyncio  # noqa: E402
import dataclasses  # noqa: E402

import pytest  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.settings_pane import SettingsPane, _widget_id  # noqa: E402
from kissterm.ui.settings_schema import (  # noqa: E402
    SETTINGS_SCHEMA,
    Field,
    ValidationError,
    coerce,
    cross_check,
)
from tests.loopback import loopback_pair  # noqa: E402


def _plain(widget) -> str:
    """The text currently visible in `widget`, read from its rendered strips.

    `#status-bar` holds a `rich.table.Table` (see `kissterm.ui.app._status_row`),
    not a plain string, so `str(widget.render())` stopped containing the
    visible text the moment that changed -- `render()` returns a Textual
    `Visual` wrapper, and reaching into its private `_renderable` attribute is
    exactly the kind of internals-coupling that breaks on the next Textual
    upgrade. Rendering the actual strips is what the terminal itself would
    show, so it cannot drift from the display.
    """
    from textual.geometry import Region

    region = Region(0, 0, widget.size.width or 200, widget.size.height or 5)
    return "\n".join(strip.text for strip in widget.render_lines(region))


MYCALL = AX25Address.parse("N1ABC-1")

#: Config fields the Settings pane deliberately does not expose as form fields.
#: `transports` and `active_transport` get their own section; the rest are not
#: user-facing. Anything else missing from the schema is a gap, not a choice.
NOT_IN_SCHEMA = {
    "transports",
    "active_transport",
    "autoconnect",
    "warnings",
    "aprs",
    "theme",
}


async def _app(config=None):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = config or Config(mycall=str(MYCALL))
    station = AX25Station(MYCALL, ta, LinkParams())
    return KissTermApp(config, station), station


# ---------------------------------------------------------------------------
# Schema coverage -- the test that catches the pane going stale
# ---------------------------------------------------------------------------


def test_every_config_field_is_editable_or_deliberately_excluded():
    paths = {f.path for s in SETTINGS_SCHEMA for f in s.fields}
    top_level = {f.name for f in dataclasses.fields(Config)}
    missing = top_level - NOT_IN_SCHEMA - paths
    assert not missing, (
        f"config fields with no Settings UI: {sorted(missing)}. Add a schema "
        f"entry in settings_schema.py, or to NOT_IN_SCHEMA with a reason."
    )


def test_every_nested_aprs_field_is_editable():
    from kissterm.config import AprsConfig

    paths = {f.path for s in SETTINGS_SCHEMA for f in s.fields}
    for f in dataclasses.fields(AprsConfig):
        assert f"aprs.{f.name}" in paths, f"aprs.{f.name} has no Settings UI"


def test_everything_the_setup_wizard_asks_for_is_changeable_in_app():
    """The wizard collects a callsign and a transport. Both must be editable.

    This is the question that prompted the pane: it used to be read-only, so
    changing either meant re-running the whole wizard.
    """
    paths = {f.path for s in SETTINGS_SCHEMA for f in s.fields}
    assert "mycall" in paths
    # The transport is not a schema field; assert its controls exist instead.
    source = (
        __import__("pathlib").Path("kissterm/ui/settings_pane.py").read_text()
    )
    for control in ("set-active-transport", "settings-scan", "settings-forget"):
        assert control in source, f"no transport control {control!r}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_numeric_bounds_are_enforced():
    spec = Field("paclen", "Frame size", "int", minimum=1, maximum=256)
    assert coerce(spec, "128") == 128
    for bad in ("0", "257", "abc", ""):
        with pytest.raises(ValidationError):
            coerce(spec, bad)


def test_callsign_validation_matches_the_wire_encoder():
    spec = Field("mycall", "Callsign", "callsign")
    assert coerce(spec, " n1abc-1 ") == "N1ABC-1"
    for bad in ("", "not a call", "TOOLONGCALL-1", "N1ABC-99"):
        with pytest.raises(ValidationError):
            coerce(spec, bad)


def test_callsign_list_round_trip():
    spec = Field("mycall_aliases", "Aliases", "calllist")
    assert coerce(spec, "n1abc-1, n1abc-2") == ["N1ABC-1", "N1ABC-2"]
    assert coerce(spec, "") == []
    with pytest.raises(ValidationError):
        coerce(spec, "N1ABC-1, ???")


def test_cross_check_flags_a_window_too_big_for_the_sequence_mode():
    cfg = Config(mycall="N1ABC-1", modulo=8, window=8)
    problems = cross_check(cfg)
    assert any("Window" in p for p in problems)
    assert not any("Window" in p for p in cross_check(Config(modulo=128, window=8)))


def test_cross_check_flags_t1_not_exceeding_t2():
    assert any("T1" in p for p in cross_check(Config(t1=1.0, t2=3.0)))
    assert not any("T1" in p for p in cross_check(Config(t1=8.0, t2=1.0)))


# ---------------------------------------------------------------------------
# The pane itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pane_shows_current_values():
    cfg = Config(mycall="N1ABC-1", paclen=64, t1=12.5, window=2)
    cfg.aprs.latitude = 42.36
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 60)) as pilot:
        app.action_show_tab("settings")
        await pilot.pause()
        assert app.query_one(f"#{_widget_id('paclen')}").value == "64"
        assert app.query_one(f"#{_widget_id('t1')}").value == "12.5"
        assert app.query_one(f"#{_widget_id('aprs.latitude')}").value == "42.36"
    station.close()


@pytest.mark.asyncio
async def test_saving_writes_config_and_applies_to_the_station():
    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        app.action_show_tab("settings")
        await pilot.pause()
        app.query_one(f"#{_widget_id('paclen')}").value = "64"
        app.query_one(f"#{_widget_id('t1')}").value = "12"
        app.query_one(f"#{_widget_id('mycall')}").value = "W1AW-9"
        app.query_one(SettingsPane)._save()
        await pilot.pause()
        await asyncio.sleep(0.1)

        assert app.config.paclen == 64
        assert app.config.t1 == 12.0
        assert app.config.mycall == "W1AW-9"
        # Applied to the live station, not just stored.
        assert station.params.paclen == 64
        assert str(station.mycall) == "W1AW-9"

        from kissterm.config import load_config

        assert load_config().paclen == 64, "not persisted to config.toml"
    station.close()


@pytest.mark.asyncio
async def test_an_invalid_field_saves_nothing_at_all():
    """A partial save leaves the operator unable to tell which values took."""
    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        app.action_show_tab("settings")
        await pilot.pause()
        before = app.config.paclen
        app.query_one(f"#{_widget_id('paclen')}").value = "64"      # valid
        app.query_one(f"#{_widget_id('retries')}").value = "banana"  # invalid
        app.query_one(SettingsPane)._save()
        await pilot.pause()

        assert app.config.paclen == before, "a valid field was saved beside a bad one"
        err = app.query_one(f"#{_widget_id('retries')}-error")
        assert err.display and str(err.render()).strip()
    station.close()


@pytest.mark.asyncio
async def test_link_params_do_not_change_under_an_established_link():
    """Changing paclen mid-conversation would corrupt an established link."""
    from kissterm.ax25 import AX25Path

    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    peer = AX25Address.parse("WS1EC-7")
    a = AX25Station(MYCALL, ta, LinkParams(t1=0.3, paclen=128))
    b = AX25Station(peer, tb, LinkParams(t1=0.3))
    app = KissTermApp(Config(mycall=str(MYCALL), paclen=128), a)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        link = await a.connect(AX25Path(peer, MYCALL))
        assert link is not None and link.connected
        app.action_show_tab("settings")
        await pilot.pause()
        app.query_one(f"#{_widget_id('paclen')}").value = "32"
        app.query_one(SettingsPane)._save()
        await pilot.pause()

        assert link.params.paclen == 128, "established link had its paclen changed"
        assert a.params.paclen == 32, "new links should pick up the new value"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_forgetting_a_transport():
    cfg = Config(
        mycall="N1ABC-1",
        transports=[
            {"name": "Direwolf", "kind": "tcp", "host": "10.0.0.2", "port": 8001},
            {"name": "USB TNC", "kind": "serial", "device": "/dev/ttyUSB0"},
        ],
        active_transport="Direwolf",
    )
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 60)) as pilot:
        app.action_show_tab("settings")
        await pilot.pause()
        app.query_one(SettingsPane)._forget()
        await pilot.pause()
        names = [t["name"] for t in app.config.transports]
        assert names == ["USB TNC"]
        assert app.config.active_transport == "USB TNC", "active must not dangle"
    station.close()


# ---------------------------------------------------------------------------
# Answering incoming calls. This is unattended transmission under the
# operator's callsign, so the defaults matter more than the mechanics.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_station_that_is_not_answering_refuses_cleanly():
    """Refusal must be a DM, not silence, so the caller stops retrying."""
    from kissterm.ax25 import AX25Path
    from kissterm.ax25.frame import UType

    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    peer = AX25Address.parse("WS1EC-7")
    a = AX25Station(MYCALL, ta, LinkParams(t1=0.2, retries=1), accept_incoming=False)
    caller = AX25Station(peer, tb, LinkParams(t1=0.2, retries=1))

    link = await caller.connect(AX25Path(MYCALL, peer), timeout=1.0)
    assert link is None, "a station with answering off must not connect"
    assert any(
        f.kind == "U" and f.utype is UType.DM for f in ta.sent
    ), "refusal must be an explicit DM, not silence"
    a.close()
    caller.close()


@pytest.mark.asyncio
async def test_answering_sends_the_banner_so_the_link_is_not_silent():
    from kissterm.ax25 import AX25Path

    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    peer = AX25Address.parse("WS1EC-7")
    banner = "Welcome to the test station. 73"
    config = Config(mycall=str(MYCALL), accept_incoming=True, connect_banner=banner)
    a = AX25Station(MYCALL, ta, LinkParams(t1=0.3), accept_incoming=True)
    caller = AX25Station(peer, tb, LinkParams(t1=0.3))
    app = KissTermApp(config, a)

    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        link = await caller.connect(AX25Path(MYCALL, peer), timeout=2.0)
        assert link is not None, "station should have answered"
        received = b""
        for _ in range(40):
            await asyncio.sleep(0.05)
            received += link.read_nowait()
            if banner.encode() in received:
                break
        assert banner.encode() in received, (
            f"caller got no banner -- the link opened into silence: {received!r}"
        )
    a.close()
    caller.close()


@pytest.mark.asyncio
async def test_no_banner_is_sent_when_answering_is_off():
    """Nothing transmits without the operator's explicit opt-in."""
    app, station = await _app(Config(mycall=str(MYCALL), accept_incoming=False))
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()

        class _Fake:
            peer = "WS1EC-7"
            sent: list = []

            async def send(self, data):
                self.sent.append(data)

        fake = _Fake()
        app._send_banner(fake)
        await pilot.pause()
        await asyncio.sleep(0.15)
        assert fake.sent == [], "banner transmitted with answering disabled"
    station.close()


@pytest.mark.asyncio
async def test_status_bar_says_when_the_station_will_answer_unattended():
    app, station = await _app(Config(mycall=str(MYCALL), accept_incoming=True))
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        assert "ANSWERING" in _plain(app.query_one("#status-bar"))
    station.close()

    app2, station2 = await _app(Config(mycall=str(MYCALL), accept_incoming=False))
    async with app2.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        assert "ANSWERING" not in _plain(app2.query_one("#status-bar"))
    station2.close()
