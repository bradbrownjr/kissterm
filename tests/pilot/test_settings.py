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
from textual.widgets import Button, Input, Select, Static, TabbedContent  # noqa: E402

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

    # `outer_size`, not `size`: the latter is the CONTENT box while
    # `render_lines` paints the padded/bordered one, so a widget with
    # horizontal padding silently loses its right-hand edge here. See
    # `tests/pilot/test_terminal_ux.py::_plain`.
    size = widget.outer_size
    region = Region(0, 0, size.width or 200, size.height or 5)
    return "\n".join(strip.text for strip in widget.render_lines(region))


MYCALL = AX25Address.parse("N1ABC-1")

#: Config fields the Settings pane deliberately does not expose as form fields.
#: `transports` and `active_transport` get their own section; the rest are not
#: user-facing. Anything else missing from the schema is a gap, not a choice.
NOT_IN_SCHEMA = {
    "transports",
    "active_transport",
    "autoconnect",
    # Its own hand-built tab, like transports -- a list of dicts, not a
    # scalar or two, and Add/Edit/Forget need real widgets a schema entry
    # cannot generate.
    "credentials",
    # Same shape, same reason, separate tab -- see Config.scripts's
    # docstring for why this is a second list rather than folded into
    # credentials.
    "scripts",
    # Same shape and reason again -- a list of dicts with its own Add/Edit/
    # Forget UI in the APRS pane (F4), not a scalar this schema can render.
    # See kissterm/aprs_contacts.py.
    "aprs_contacts",
    # The operator's saved APRS messages -- another list of dicts with its
    # own Add/Edit/Forget UI, in the APRS pane's template picker rather than
    # Settings. See kissterm/aprs_contacts.py's CannedMessage.
    "aprs_templates",
    # Not a setting anyone types: it accumulates as a side effect of pressing
    # Delete on a built-in service row in the APRS pane. A Settings widget
    # for it would be a list of ids with no context.
    "aprs_hidden_services",
    "warnings",
    # Chosen before startup by the CLI. Exposing it here would create a live
    # profile switch, which must not change an established session.
    "profile_name",
    "aprs",
    # Nested dataclasses. Their fields ARE in the schema, as dotted paths --
    # covered field-by-field by the nested tests below, which is stricter
    # than this top-level check, not an exemption from it.
    "beacon",
    "custom_theme",
    "watched_callsigns",
}


async def _app(config=None):
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    # Transmit is disabled on a fresh app (kissterm/tx.py); these tests are
    # about other behaviour and would otherwise all fail at the gate. The
    # closed-by-default guarantee itself is asserted in
    # tests/pilot/test_transmit_gate.py.
    config = config or Config(mycall=str(MYCALL))
    config.tx_armed_at_start = True
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


def test_every_nested_beacon_field_is_editable():
    from kissterm.config import BeaconConfig

    paths = {f.path for s in SETTINGS_SCHEMA for f in s.fields}
    for f in dataclasses.fields(BeaconConfig):
        assert f"beacon.{f.name}" in paths, f"beacon.{f.name} has no Settings UI"


def test_every_nested_watched_callsign_field_is_editable():
    from kissterm.config import WatchedCallsignConfig

    paths = {f.path for s in SETTINGS_SCHEMA for f in s.fields}
    for f in dataclasses.fields(WatchedCallsignConfig):
        assert f"watched_callsigns.{f.name}" in paths, (
            f"watched_callsigns.{f.name} has no Settings UI"
        )


def test_every_nested_custom_theme_field_is_editable():
    from kissterm.config import CustomThemeConfig

    paths = {f.path for s in SETTINGS_SCHEMA for f in s.fields}
    for f in dataclasses.fields(CustomThemeConfig):
        assert f"custom_theme.{f.name}" in paths, f"custom_theme.{f.name} has no Settings UI"


def test_beacon_and_aprs_are_not_presented_as_the_same_feature():
    """The two beacons must never read as one setting with two spellings.

    They share the UI-frame machinery and nothing else: one sends a position
    in APRS format to APRS, the other free text to BEACON. An operator who
    enables one expecting the other is transmitting something they did not
    intend, under their own callsign.
    """
    sections = {s.title: s for s in SETTINGS_SCHEMA}
    assert "Beacon" in sections and "APRS" in sections
    assert "NOT APRS" in sections["Beacon"].note
    for section in (sections["Beacon"], sections["APRS"]):
        labels = [f.label for f in section.fields]
        assert len(labels) == len(set(labels)), "duplicate label within a section"
    # The two enable switches must not carry the same label either.
    enable = {
        f.path: f.label
        for s in SETTINGS_SCHEMA
        for f in s.fields
        if f.path in ("aprs.enabled", "beacon.enabled")
    }
    assert len(set(enable.values())) == 2, enable


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
async def test_a_bad_custom_theme_color_marks_the_swatch_and_saves_nothing():
    """The swatch is a live preview, not the enforcement point -- typing an
    incomplete hex value must not corrupt `Config`, and must be visibly
    flagged (the `-invalid` class, which switches its border to `$error` in
    styles.py) rather than silently keeping the last good fill."""
    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        app.action_show_tab("settings")
        await pilot.pause()
        wid = _widget_id("custom_theme.primary")
        before = app.config.custom_theme.primary

        app.query_one(f"#{wid}", Input).value = "#ff00ff"
        await pilot.pause()
        assert "-invalid" not in app.query_one(f"#{wid}-swatch").classes

        app.query_one(f"#{wid}", Input).value = "not-a-color"
        await pilot.pause()
        assert "-invalid" in app.query_one(f"#{wid}-swatch").classes

        app.query_one(SettingsPane)._save()
        await pilot.pause()
        assert app.config.custom_theme.primary == before, "invalid color must not be saved"
        err = app.query_one(f"#{wid}-error")
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
    config = Config(mycall=str(MYCALL), paclen=128)
    config.tx_armed_at_start = True  # this test needs a real link; see test_transmit_gate.py
    app = KissTermApp(config, a)
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


@pytest.mark.asyncio
async def test_new_transport_is_saved_and_becomes_active():
    """'Scan for hardware' can only find a KISS TNC or AGWPE engine it can
    identify by itself -- it never invents a Telnet/SSH login or a VARA
    modem's callsign. Before `TransportEntryScreen`, the only way to add one
    of those at all was hand-editing config.toml. Dismissing with a dict
    the way this test does stands in for filling the form -- what matters
    here is the SettingsPane side: validating through `build_transport`
    before saving, and applying the result to `config.transports`."""
    app, station = await _app(Config(mycall=str(MYCALL)))
    async with app.run_test(size=(120, 44)) as pilot:
        await _settings_tab(app, pilot)

        pane = app.query_one(SettingsPane)
        pane._new_transport()
        await pilot.pause()
        await asyncio.sleep(0.05)

        from kissterm.ui.dialogs import TransportEntryScreen

        assert isinstance(app.screen, TransportEntryScreen), type(app.screen).__name__
        await app.screen.dismiss(
            {"name": "ws1ec", "kind": "ssh", "host": "ws1ec.example.net",
             "username": "packet", "password": "hunter2", "port": 22,
             "script": "", "credential": ""}
        )
        await pilot.pause()

        assert [t["name"] for t in app.config.transports] == ["ws1ec"]
        # The very first transport ever configured becomes active on its
        # own, same as a hardware scan's result does.
        assert app.config.active_transport == "ws1ec"
        assert app.query_one("#set-active-transport", Select).value == "ws1ec"
    station.close()


@pytest.mark.asyncio
async def test_a_transport_that_fails_to_build_is_not_saved():
    """`build_transport` is the ONLY way a `Transport` is constructed from
    config (AGENTS.md); this dialog must prove a config entry actually
    builds before writing it, the same rule the first-run wizard follows --
    a config entry that looks right and fails at `open()` is worse than
    catching it here. A `tcp` entry with no `host` fails inside `TcpKissTransport.
    __init__` (a required positional argument), which is exactly the kind of
    entry a hand-typed form could otherwise produce."""
    app, station = await _app(Config(mycall=str(MYCALL)))
    async with app.run_test(size=(120, 44)) as pilot:
        await _settings_tab(app, pilot)

        pane = app.query_one(SettingsPane)
        pane._new_transport()
        await pilot.pause()
        await asyncio.sleep(0.05)

        await app.screen.dismiss({"name": "broken", "kind": "tcp"})
        await pilot.pause()

        assert app.config.transports == []
        assert app.config.active_transport == ""
    station.close()


@pytest.mark.asyncio
async def test_editing_a_transport_renames_it_without_leaving_a_duplicate():
    cfg = Config(
        mycall=str(MYCALL),
        transports=[{"name": "Old name", "kind": "tcp", "host": "10.0.0.2", "port": 8001}],
        active_transport="Old name",
    )
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 44)) as pilot:
        await _settings_tab(app, pilot)
        app.query_one("#set-active-transport", Select).value = "Old name"
        await pilot.pause()

        pane = app.query_one(SettingsPane)
        pane._edit_transport()
        await pilot.pause()
        await asyncio.sleep(0.05)

        from kissterm.ui.dialogs import TransportEntryScreen

        assert isinstance(app.screen, TransportEntryScreen), type(app.screen).__name__
        await app.screen.dismiss(
            {"name": "New name", "kind": "tcp", "host": "10.0.0.3", "port": 8002}
        )
        await pilot.pause()

        assert app.config.transports == [
            {"name": "New name", "kind": "tcp", "host": "10.0.0.3", "port": 8002}
        ]
        # The renamed entry was the active one -- the pointer must follow it,
        # or `active_transport` is left naming an entry that no longer exists.
        assert app.config.active_transport == "New name"
    station.close()


@pytest.mark.asyncio
async def test_transport_dialog_switching_kind_resets_the_fields():
    """"host" means something different for every kind that has one -- a tcp
    KISS TNC's address is not a VARA modem's, and carrying it over silently
    would look filled-in for a field the operator never actually typed
    anything into for THIS kind."""
    from kissterm.ui.dialogs import TransportEntryScreen

    app, station = await _app(Config(mycall=str(MYCALL)))
    async with app.run_test(size=(120, 50)) as pilot:
        app.query_one(SettingsPane)._new_transport()
        await pilot.pause()
        await asyncio.sleep(0.05)
        assert isinstance(app.screen, TransportEntryScreen)

        app.screen.query_one("#transport-field-host", Input).value = "10.0.0.5"
        app.screen.query_one("#transport-kind", Select).value = "serial"
        await pilot.pause()
        await asyncio.sleep(0.05)

        assert len(app.screen.query("#transport-field-host")) == 0
        assert app.screen.query_one("#transport-field-device", Input).value == ""
    station.close()


@pytest.mark.asyncio
async def test_transport_dialog_hides_autologin_for_a_frame_transport():
    """`Transport.script`/`credential` are meaningful only to a
    `SessionTransport` -- showing the section for a plain TCP KISS TNC would
    invite an operator to type a login nothing ever reads."""
    from kissterm.ui.dialogs import TransportEntryScreen

    app, station = await _app(Config(mycall=str(MYCALL)))
    async with app.run_test(size=(120, 50)) as pilot:
        app.query_one(SettingsPane)._new_transport()
        await pilot.pause()
        await asyncio.sleep(0.05)
        assert isinstance(app.screen, TransportEntryScreen)

        assert app.screen.query_one("#transport-script-title").display is False
        app.screen.query_one("#transport-kind", Select).value = "ssh"
        await pilot.pause()
        await asyncio.sleep(0.05)
        assert app.screen.query_one("#transport-script-title").display is True
    station.close()


@pytest.mark.asyncio
async def test_ssh_transport_dialog_offers_explicit_key_and_host_verification_fields():
    """SSH identities and the trusted server key must be named explicitly."""
    from kissterm.ui.dialogs import TransportEntryScreen

    app, station = await _app(Config(mycall=str(MYCALL)))
    async with app.run_test(size=(120, 50)) as pilot:
        app.query_one(SettingsPane)._new_transport()
        await pilot.pause()
        await asyncio.sleep(0.05)
        assert isinstance(app.screen, TransportEntryScreen)

        app.screen.query_one("#transport-kind", Select).value = "ssh"
        await pilot.pause()
        await asyncio.sleep(0.05)

        assert app.screen.query_one("#transport-field-client_key", Input).value == ""
        passphrase = app.screen.query_one("#transport-field-key_passphrase", Input)
        assert passphrase.value == ""
        assert passphrase.password is True
        known_hosts = app.screen.query_one("#transport-field-known_hosts", Input)
        assert known_hosts.value == ""
        assert known_hosts.password is False
    station.close()


@pytest.mark.asyncio
async def test_transport_dialog_requires_a_name():
    from kissterm.ui.dialogs import TransportEntryScreen

    app, station = await _app(Config(mycall=str(MYCALL)))
    async with app.run_test(size=(120, 50)) as pilot:
        app.query_one(SettingsPane)._new_transport()
        await pilot.pause()
        await asyncio.sleep(0.05)
        assert isinstance(app.screen, TransportEntryScreen)

        app.screen.query_one("#transport-field-host", Input).value = "10.0.0.5"
        app.screen.query_one("#transport-save", Button).press()
        await pilot.pause()

        assert isinstance(app.screen, TransportEntryScreen), "an invalid save must not dismiss"
        assert "Name" in str(app.screen.query_one("#transport-error").content)
    station.close()


@pytest.mark.asyncio
async def test_forgetting_with_nothing_selected_is_a_no_op():
    """Regression: an unselected Select's value is `Select.NULL`, not
    `Select.BLANK` (which this Textual version defines as plain `False` --
    a different object `Select.NULL` never equals). Comparing against the
    wrong one made `not name or name == Select.BLANK` fail to recognise a
    blank selection at all, so this used to fall through and filter
    `config.transports` against a `Select.NULL` sentinel instead of
    returning early."""
    cfg = Config(
        mycall="N1ABC-1",
        transports=[{"name": "Direwolf", "kind": "tcp", "host": "10.0.0.2", "port": 8001}],
        active_transport="Direwolf",
    )
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 60)) as pilot:
        app.action_show_tab("settings")
        await pilot.pause()
        app.query_one("#set-active-transport", Select).value = Select.NULL
        app.query_one(SettingsPane)._forget()
        await pilot.pause()
        assert [t["name"] for t in app.config.transports] == ["Direwolf"]
        assert app.config.active_transport == "Direwolf"
    station.close()


@pytest.mark.asyncio
async def test_saving_with_no_transport_selected_does_not_corrupt_active_transport():
    """Same sentinel bug, the save side: `selected != Select.BLANK` was
    always true (`Select.NULL != False`), so a blank Active dropdown wrote
    `str(Select.NULL)` into `config.active_transport` on every save."""
    cfg = Config(mycall="N1ABC-1")
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 60)) as pilot:
        app.action_show_tab("settings")
        await pilot.pause()
        assert app.query_one("#set-active-transport", Select).value is Select.NULL
        app.query_one(SettingsPane)._save()
        await pilot.pause()
        assert app.config.active_transport == "", app.config.active_transport
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
    # An unattended station arms transmit at startup, or a restart silently
    # takes it off the air -- which is exactly what tx_armed_at_start is for.
    config.tx_armed_at_start = True
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


# ---------------------------------------------------------------------------
# "Test selected" -- is my TNC actually there, and is it what the config says?
# ---------------------------------------------------------------------------


def _detail_text(app) -> str:
    """The full text of the transport-detail line.

    Not `_plain`: that renders only what fits the widget's current width, and
    a verdict sentence wraps -- clipping the very words the assertion is
    about. `Static.renderable` is what the pane was actually told to say.
    """
    return str(app.query_one("#settings-transport-detail").content)


async def _settings_tab(app, pilot):
    app.action_show_tab("settings")
    await pilot.pause()
    await asyncio.sleep(0.1)
    await pilot.pause()


@pytest.mark.asyncio
async def test_test_button_names_a_web_service_for_what_it_is():
    """The whole point of the button: a scan that matched on port number
    alone put a self-hosted web app in the transport list, and the operator
    had no way to find that out except by trying to connect to a station and
    misreading the silence as a dead RF path."""

    async def handler(reader, writer):
        await reader.read(64)
        writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]

    config = Config(mycall=str(MYCALL))
    config.transports = [{"kind": "tcp", "name": "suspect", "host": host, "port": port}]
    config.active_transport = "suspect"
    app, station = await _app(config)
    try:
        async with app.run_test(size=(120, 44)) as pilot:
            await _settings_tab(app, pilot)
            app.query_one(SettingsPane)._test_transport()
            await pilot.pause()
            await asyncio.sleep(0.8)
            await pilot.pause()
            detail = _detail_text(app)
            assert "Not a TNC" in detail, detail
            assert "web server" in detail, detail
    finally:
        station.close()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_test_button_does_not_call_a_silent_tnc_broken():
    """An idle KISS TNC on a quiet channel says nothing, which is what a
    working station looks like. Reporting that as a failure would send an
    operator chasing a fault that is not there."""

    async def handler(reader, writer):
        await reader.read(64)
        await asyncio.sleep(3.0)

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]

    config = Config(mycall=str(MYCALL))
    config.transports = [{"kind": "tcp", "name": "quiet", "host": host, "port": port}]
    config.active_transport = "quiet"
    app, station = await _app(config)
    try:
        async with app.run_test(size=(120, 44)) as pilot:
            await _settings_tab(app, pilot)
            app.query_one(SettingsPane)._test_transport()
            await pilot.pause()
            await asyncio.sleep(2.6)
            await pilot.pause()
            detail = _detail_text(app)
            assert "Not a TNC" not in detail, detail
            assert "silent" in detail.lower(), detail
    finally:
        station.close()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_switching_the_active_transport_and_saving_reopens_it():
    """The bug: picking a different entry from Active and hitting Save
    changed `config.active_transport` and nothing else. The station kept
    talking to its original transport object, so the status bar kept
    reporting the OLD TNC no matter how many times the operator saved."""

    async def handler(reader, writer):
        await reader.read(64)
        await asyncio.sleep(5.0)

    server_a = await asyncio.start_server(handler, "127.0.0.1", 0)
    server_b = await asyncio.start_server(handler, "127.0.0.1", 0)
    host, port_a = server_a.sockets[0].getsockname()[:2]
    _, port_b = server_b.sockets[0].getsockname()[:2]

    config = Config(mycall=str(MYCALL))
    config.transports = [
        {"kind": "tcp", "name": "first", "host": host, "port": port_a},
        {"kind": "tcp", "name": "second", "host": host, "port": port_b},
    ]
    config.active_transport = "first"
    app, station = await _app(config)
    try:
        async with app.run_test(size=(120, 44)) as pilot:
            await _settings_tab(app, pilot)
            app.query_one("#settings-tabs", TabbedContent).active = "settings-tab-transports"
            await pilot.pause()

            app.query_one("#set-active-transport", Select).value = "second"
            await pilot.pause()

            app.query_one(SettingsPane)._save()
            await pilot.pause()
            await asyncio.sleep(0.3)
            await pilot.pause()

            assert app.station.transport.info.detail == f"{host}:{port_b}", (
                app.station.transport.info.detail
            )
            status = _plain(app.query_one("#status-bar"))
            assert f"{host}:{port_b}" in status, status
    finally:
        station.close()
        # The rebind leaves a SECOND live transport behind (`station.
        # transport`, now "second") on top of the original loopback --
        # `station.close()` never touches `.transport` (see its docstring),
        # so this is the caller's job, same fix as `__main__.py`'s shutdown.
        await station.transport.close()
        server_a.close()
        server_b.close()
        await server_a.wait_closed()
        await server_b.wait_closed()


@pytest.mark.asyncio
async def test_switching_transport_while_connected_is_refused_not_silent():
    """The other half of the guarantee: Settings already tells the operator to
    disconnect first. This is what makes that true rather than aspirational --
    without the refusal in `AX25Station.rebind_transport`, saving a new Active
    selection mid-conversation would silently reroute a live link's frames
    onto hardware that has never heard of it."""

    async def handler(reader, writer):
        await reader.read(64)
        await asyncio.sleep(5.0)

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]

    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    peer = AX25Station(
        AX25Address.parse("W1AW-7"), tb, LinkParams(t1=0.2, t2=0.05, t3=5.0)
    )

    config = Config(mycall=str(MYCALL))
    config.tx_armed_at_start = True
    config.transports = [{"kind": "tcp", "name": "other", "host": host, "port": port}]
    config.active_transport = ""
    station = AX25Station(MYCALL, ta, LinkParams(t1=0.2, t2=0.05, t3=5.0))
    app = KissTermApp(config, station)
    try:
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.press("ctrl+n")
            await pilot.pause()
            await asyncio.sleep(0.1)
            for key in "W1AW-7":
                await pilot.press(key if key != "-" else "minus")
            await pilot.press("enter")
            await pilot.pause()
            await asyncio.sleep(0.3)
            assert app.link is not None and app.link.connected, "setup: link never came up"

            await _settings_tab(app, pilot)
            app.query_one("#settings-tabs", TabbedContent).active = "settings-tab-transports"
            await pilot.pause()
            app.query_one("#set-active-transport", Select).value = "other"
            await pilot.pause()

            app.query_one(SettingsPane)._save()
            await pilot.pause()
            await asyncio.sleep(0.2)

            assert app.station.transport is ta, "the transport changed while a link was up"
    finally:
        station.close()
        peer.close()
        server.close()
        await server.wait_closed()


# ---------------------------------------------------------------------------
# Credentials -- reusable logins, referenced by name from a Connect entry.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_credential_is_saved_and_selectable():
    app, station = await _app(Config(mycall=str(MYCALL)))
    async with app.run_test(size=(120, 44)) as pilot:
        await _settings_tab(app, pilot)
        app.query_one("#settings-tabs", TabbedContent).active = "settings-tab-credentials"
        await pilot.pause()

        pane = app.query_one(SettingsPane)
        pane._new_credential()
        await pilot.pause()
        await asyncio.sleep(0.05)

        from kissterm.ui.dialogs import Credential, CredentialScreen

        assert isinstance(app.screen, CredentialScreen), type(app.screen).__name__
        await app.screen.dismiss(Credential("Personal BBS login", "CLYDE\nMYPASS"))
        await pilot.pause()

        assert app.config.credentials == [
            {"name": "Personal BBS login", "text": "CLYDE\nMYPASS"}
        ]
        assert app.query_one("#set-credential", Select).value == "Personal BBS login"
        detail = _detail_text_of(app, "#settings-credential-detail")
        assert "2 line" in detail, detail
    station.close()


@pytest.mark.asyncio
async def test_editing_a_credential_renames_it_without_leaving_a_duplicate():
    cfg = Config(mycall=str(MYCALL))
    cfg.credentials = [{"name": "Old name", "text": "MYPASS"}]
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 44)) as pilot:
        await _settings_tab(app, pilot)
        app.query_one("#settings-tabs", TabbedContent).active = "settings-tab-credentials"
        await pilot.pause()
        app.query_one("#set-credential", Select).value = "Old name"
        await pilot.pause()

        pane = app.query_one(SettingsPane)
        pane._edit_credential()
        await pilot.pause()
        await asyncio.sleep(0.05)

        from kissterm.ui.dialogs import Credential

        await app.screen.dismiss(Credential("New name", "NEWPASS"))
        await pilot.pause()

        assert app.config.credentials == [{"name": "New name", "text": "NEWPASS"}]
    station.close()


@pytest.mark.asyncio
async def test_forgetting_a_credential():
    cfg = Config(mycall=str(MYCALL))
    cfg.credentials = [
        {"name": "Keep me", "text": "A"},
        {"name": "Drop me", "text": "B"},
    ]
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 44)) as pilot:
        await _settings_tab(app, pilot)
        app.query_one("#settings-tabs", TabbedContent).active = "settings-tab-credentials"
        await pilot.pause()
        app.query_one("#set-credential", Select).value = "Drop me"
        await pilot.pause()

        app.query_one(SettingsPane)._forget_credential()
        await pilot.pause()

        assert [c["name"] for c in app.config.credentials] == ["Keep me"]
    station.close()


def _detail_text_of(app, selector: str) -> str:
    return str(app.query_one(selector).content)


# ---------------------------------------------------------------------------
# APRS WIDE-path picker (custom_choice)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wide_path_preset_is_selected_and_the_custom_field_stays_hidden():
    cfg = Config(mycall=str(MYCALL))
    cfg.aprs.path = "WIDE2-2"
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 60)) as pilot:
        await _settings_tab(app, pilot)
        select = app.query_one("#set-aprs-path", Select)
        custom = app.query_one("#set-aprs-path-custom", Input)
        assert select.value == "WIDE2-2"
        assert custom.display is False
    station.close()


@pytest.mark.asyncio
async def test_a_path_matching_no_preset_shows_custom_with_the_literal_text():
    """Disable, never clear: a hand-edited config.toml path must stay
    visible and still round-trip on Save, not be silently discarded."""
    cfg = Config(mycall=str(MYCALL))
    cfg.aprs.path = "W1AW-1,WIDE1-1"
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 60)) as pilot:
        await _settings_tab(app, pilot)
        select = app.query_one("#set-aprs-path", Select)
        custom = app.query_one("#set-aprs-path-custom", Input)
        assert select.value == "__custom__"
        assert custom.display is True
        assert custom.value == "W1AW-1,WIDE1-1"
    station.close()


@pytest.mark.asyncio
async def test_picking_custom_reveals_the_field_and_saving_it_persists():
    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        await _settings_tab(app, pilot)
        select = app.query_one("#set-aprs-path", Select)
        custom = app.query_one("#set-aprs-path-custom", Input)
        select.value = "__custom__"
        await pilot.pause()
        assert custom.display is True
        custom.value = "WIDE1-1,N1ABC-2"
        app.query_one(SettingsPane)._save()
        await pilot.pause()
        assert app.config.aprs.path == "WIDE1-1,N1ABC-2"
    station.close()


@pytest.mark.asyncio
async def test_picking_a_preset_after_custom_saves_the_preset_not_the_old_text():
    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        await _settings_tab(app, pilot)
        select = app.query_one("#set-aprs-path", Select)
        select.value = "__custom__"
        await pilot.pause()
        app.query_one("#set-aprs-path-custom", Input).value = "some custom text"
        select.value = "WIDE1-1"
        await pilot.pause()
        assert app.query_one("#set-aprs-path-custom", Input).display is False
        app.query_one(SettingsPane)._save()
        await pilot.pause()
        assert app.config.aprs.path == "WIDE1-1"
    station.close()


@pytest.mark.asyncio
async def test_ariss_is_a_selectable_preset_not_a_custom_entry():
    """ISS/ARISS is a digipeat path, not a contact -- docs/ROADMAP.md's P4
    item on this. A satellite pass wants a preset, not hand-typed text."""
    cfg = Config(mycall=str(MYCALL))
    cfg.aprs.path = "ARISS"
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 60)) as pilot:
        await _settings_tab(app, pilot)
        select = app.query_one("#set-aprs-path", Select)
        custom = app.query_one("#set-aprs-path-custom", Input)
        assert select.value == "ARISS"
        assert custom.display is False
        select.value = "WIDE1-1"
        await pilot.pause()
        select.value = "ARISS"
        await pilot.pause()
        app.query_one(SettingsPane)._save()
        await pilot.pause()
        assert app.config.aprs.path == "ARISS"
    station.close()


# ---------------------------------------------------------------------------
# APRS symbol picker (filtered_choice)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_stored_symbol_is_preselected():
    cfg = Config(mycall=str(MYCALL))
    cfg.aprs.symbol = "\\!"
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 60)) as pilot:
        await _settings_tab(app, pilot)
        assert app.query_one("#set-aprs-symbol", Select).value == "\\!"
    station.close()


@pytest.mark.asyncio
async def test_typing_in_the_symbol_filter_narrows_the_options():
    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        await _settings_tab(app, pilot)
        filter_input = app.query_one("#set-aprs-symbol-filter", Input)
        select = app.query_one("#set-aprs-symbol", Select)
        full_count = len(select._options)
        filter_input.value = "ambulance"
        await pilot.pause()
        assert len(select._options) < full_count
        assert any(v == "/a" for _label, v in select._options)
    station.close()


@pytest.mark.asyncio
async def test_picking_a_filtered_symbol_and_saving_persists_it():
    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        await _settings_tab(app, pilot)
        app.query_one("#set-aprs-symbol-filter", Input).value = "car"
        await pilot.pause()
        app.query_one("#set-aprs-symbol", Select).value = "/>"
        app.query_one(SettingsPane)._save()
        await pilot.pause()
        assert app.config.aprs.symbol == "/>"
    station.close()


# ---------------------------------------------------------------------------
# APRS position: decimal / grid square
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loading_a_saved_grid_square_does_not_corrupt_the_decimal_position_it_was_computed_from():
    """Regression: bulk-populating the position widgets from `render_settings`
    used to fire each Input's own Changed handler, and one of those could be
    processed (asynchronously) after the mode Select had already flipped to
    "grid" -- silently overwriting an exact stored decimal with the CENTER
    of its own grid square the moment Settings was merely opened."""
    cfg = Config(mycall=str(MYCALL))
    cfg.aprs.latitude = 41.7148
    cfg.aprs.longitude = -72.7273
    cfg.aprs.grid_square = "FN31pr"
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 60)) as pilot:
        await _settings_tab(app, pilot)
        assert app.query_one("#aprs-position-mode", Select).value == "grid"
        assert app.query_one("#set-aprs-latitude", Input).value == "41.7148"
        assert app.query_one("#set-aprs-longitude", Input).value == "-72.7273"
        assert app.query_one("#set-aprs-grid_square", Input).value == "FN31pr"
    station.close()


@pytest.mark.asyncio
async def test_decimal_only_config_defaults_to_decimal_mode_with_a_blank_grid_field():
    cfg = Config(mycall=str(MYCALL))
    cfg.aprs.latitude = 40.0
    cfg.aprs.longitude = -75.0
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 60)) as pilot:
        await _settings_tab(app, pilot)
        assert app.query_one("#aprs-position-mode", Select).value == "decimal"
        assert app.query_one("#aprs-decimal-row").display is True
        assert app.query_one("#aprs-grid-row").display is False
        assert app.query_one("#set-aprs-grid_square", Input).value == ""
    station.close()


@pytest.mark.asyncio
async def test_switching_to_grid_from_blank_autofills_it_from_the_decimal_position():
    cfg = Config(mycall=str(MYCALL))
    cfg.aprs.latitude = 40.0
    cfg.aprs.longitude = -75.0
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 60)) as pilot:
        await _settings_tab(app, pilot)
        app.query_one("#aprs-position-mode", Select).value = "grid"
        await pilot.pause()
        assert app.query_one("#set-aprs-grid_square", Input).value == "FN20ma"
    station.close()


@pytest.mark.asyncio
async def test_switching_modes_never_overwrites_an_already_populated_field():
    """A bare mode switch with nothing newly typed must be a pure view
    toggle -- looking at the grid tab and back must not quietly discard the
    decimal precision that was already loaded."""
    cfg = Config(mycall=str(MYCALL))
    cfg.aprs.latitude = 41.7148
    cfg.aprs.longitude = -72.7273
    cfg.aprs.grid_square = "FN31pr"
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 60)) as pilot:
        await _settings_tab(app, pilot)
        mode = app.query_one("#aprs-position-mode", Select)
        assert mode.value == "grid"
        mode.value = "decimal"
        await pilot.pause()
        assert app.query_one("#set-aprs-latitude", Input).value == "41.7148"
        assert app.query_one("#set-aprs-longitude", Input).value == "-72.7273"
        mode.value = "grid"
        await pilot.pause()
        assert app.query_one("#set-aprs-grid_square", Input).value == "FN31pr"
    station.close()


@pytest.mark.asyncio
async def test_typing_a_new_grid_square_recomputes_the_decimal_position():
    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        await _settings_tab(app, pilot)
        app.query_one("#aprs-position-mode", Select).value = "grid"
        await pilot.pause()
        app.query_one("#set-aprs-grid_square", Input).value = "FN31pr"
        await pilot.pause()
        lat = float(app.query_one("#set-aprs-latitude", Input).value)
        lon = float(app.query_one("#set-aprs-longitude", Input).value)
        assert round(lat, 2) == 41.73
        assert round(lon, 2) == -72.71
    station.close()


@pytest.mark.asyncio
async def test_position_round_trips_through_save_and_reload():
    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        await _settings_tab(app, pilot)
        app.query_one("#set-aprs-latitude", Input).value = "34.0522"
        app.query_one("#set-aprs-longitude", Input).value = "-118.2437"
        await pilot.pause()
        app.query_one(SettingsPane)._save()
        await pilot.pause()
        assert app.config.aprs.latitude == 34.0522
        assert app.config.aprs.longitude == -118.2437

        from kissterm.config import load_config

        reloaded = load_config()
        assert reloaded.aprs.latitude == 34.0522
        assert reloaded.aprs.longitude == -118.2437
        assert reloaded.aprs.grid_square  # kept in sync, not left stale/empty
    station.close()


# ---------------------------------------------------------------------------
# Winlink notify checkbox
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_winlink_check_toggles_and_saves():
    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        await _settings_tab(app, pilot)
        assert app.query_one("#set-aprs-winlink_check").value is False
        app.query_one("#set-aprs-winlink_check").value = True
        app.query_one(SettingsPane)._save()
        await pilot.pause()
        assert app.config.aprs.winlink_check is True
    station.close()




@pytest.mark.asyncio
async def test_a_symbol_filter_matching_nothing_does_not_crash():
    """This crashed the whole app. `set_options([])` on a `Select` built with
    `allow_blank=False` raises `EmptySelectError` out of a message handler,
    and typing any word not in the symbol table was enough to hit it.
    Third distinct way this project has been bitten by `Select`'s
    value/option invariants -- see AGENTS.md sec. 7.
    """
    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        await _settings_tab(app, pilot)
        select = app.query_one("#set-aprs-symbol", Select)
        before = select.value
        for needle in ("car", "zzzznotasymbol", "house", ""):
            app.query_one("#set-aprs-symbol-filter", Input).value = needle
            await pilot.pause()
            await asyncio.sleep(0.05)
            assert select.value == before, f"filter {needle!r} lost the selection"
    station.close()


@pytest.mark.asyncio
async def test_filtering_past_your_own_symbol_keeps_it_selected():
    """The quieter half of the same bug: `set_options` resets `.value`, and
    the old code restored it only when it survived the filter -- so narrowing
    past your own symbol blanked it and saving wrote an empty symbol. Losing
    a setting by typing in a search box is not something an operator would
    ever expect."""
    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        await _settings_tab(app, pilot)
        select = app.query_one("#set-aprs-symbol", Select)
        select.value = "/>"
        await pilot.pause()

        # "boat" cannot match the car symbol, so the pinned current value is
        # the only thing keeping it selected.
        app.query_one("#set-aprs-symbol-filter", Input).value = "boat"
        await pilot.pause()
        await asyncio.sleep(0.05)
        assert select.value == "/>"
        assert "/>" in {value for _, value in select._options}
    station.close()


@pytest.mark.asyncio
async def test_a_successful_save_says_so_in_the_footer_not_a_toast():
    """Requested 2026-09-22: no toast for something already on screen. The
    Settings footer already reads "Settings saved.", so a toast saying the
    same thing in another corner is noise (DESIGN.md section 1)."""
    app, station = await _app()
    async with app.run_test(size=(120, 44)) as pilot:
        await _settings_tab(app, pilot)
        before = len(app._notifications)
        app.query_one(SettingsPane)._save()
        await pilot.pause()
        footer = str(app.query_one("#settings-footer", Static).render())
        assert "Settings saved." in footer, footer
        assert len(app._notifications) == before, [
            n.message for n in app._notifications
        ]
    station.close()
