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
from textual.widgets import Button, Input, Select, Static  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Station, LinkParams  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.settings_pane import SettingsPane  # noqa: E402
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
    "home_bbs",
    "winlink",
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


def test_every_nested_home_bbs_field_is_editable():
    from kissterm.config import HomeBbsConfig

    paths = {f.path for s in SETTINGS_SCHEMA for f in s.fields}
    for f in dataclasses.fields(HomeBbsConfig):
        if f.name == "internet_user":
            continue  # read from an older config.toml only; folded into the Node login
        assert f"home_bbs.{f.name}" in paths, f"home_bbs.{f.name} has no Settings UI"


def test_every_nested_winlink_field_is_editable():
    from kissterm.config import WinlinkConfig

    paths = {f.path for s in SETTINGS_SCHEMA for f in s.fields}
    for f in dataclasses.fields(WinlinkConfig):
        assert f"winlink.{f.name}" in paths, f"winlink.{f.name} has no Settings UI"


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
    beacon_switch = next(f for f in sections["Beacon"].fields if f.path == "beacon.enabled")
    assert "NOT APRS" in beacon_switch.help.upper()
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
        pane = app.query_one(SettingsPane)
        assert pane.field_value("paclen") == "64"
        assert pane.field_value("t1") == "12.5"
        assert pane.field_value("aprs.latitude") == "42.36"
        # And on screen: a row per field, its label then its value.
        assert pane.row_text("paclen").split() == ["Frame", "size", "(paclen)", "64"]
    station.close()


@pytest.mark.asyncio
async def test_saving_writes_config_and_applies_to_the_station():
    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        app.action_show_tab("settings")
        await pilot.pause()
        pane = app.query_one(SettingsPane)
        pane.set_field("paclen", "64")
        pane.set_field("t1", "12")
        pane.set_field("mycall", "W1AW-9")
        pane._save()
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
async def test_typing_in_the_editor_changes_the_row_and_saves():
    """The whole path by keys: highlight a row, Enter, type, Enter, Save."""
    app, station = await _app()
    async with app.run_test(size=(100, 33)) as pilot:
        app.action_show_tab("settings")
        await pilot.pause()
        pane = app.query_one(SettingsPane)
        pane.open_field("paclen")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.focused is app.query_one("#settings-edit-input", Input)
        await pilot.press("ctrl+u", "6", "4", "enter")
        await pilot.pause()
        assert pane.row_text("paclen").endswith(" 64  (unsaved)")
        assert app.focused is app.query_one("#settings-tab-link")
        assert app.config.paclen != 64, "nothing is saved before Save"
        pane._save()
        await pilot.pause()
        assert app.config.paclen == 64
    station.close()


@pytest.mark.asyncio
async def test_enter_flips_an_on_off_setting():
    app, station = await _app()
    async with app.run_test(size=(100, 33)) as pilot:
        app.action_show_tab("settings")
        await pilot.pause()
        pane = app.query_one(SettingsPane)
        pane.open_field("aprs.winlink_check")
        await pilot.pause()
        assert pane.row_text("aprs.winlink_check").endswith(" off")
        await pilot.press("enter")
        await pilot.pause()
        assert pane.row_text("aprs.winlink_check").endswith(" on  (unsaved)")
        assert app.query_one("#settings-edit-check").value is True
        pane._save()
        await pilot.pause()
        assert app.config.aprs.winlink_check is True
    station.close()


@pytest.mark.asyncio
async def test_moving_between_rows_never_carries_one_value_into_another():
    """One editor serves every field: loading the next field's value must
    not be read back as an edit of either."""
    cfg = Config(mycall="N1ABC-1", paclen=64, window=3)
    app, station = await _app(cfg)
    async with app.run_test(size=(100, 33)) as pilot:
        app.action_show_tab("settings")
        await pilot.pause()
        pane = app.query_one(SettingsPane)
        pane.open_field("paclen")
        await pilot.pause()
        for key in ("down", "up", "down", "down", "up", "up"):
            await pilot.press(key)
        await pilot.pause()
        await asyncio.sleep(0.05)
        await pilot.pause()
        assert pane.field_value("paclen") == "64"
        assert pane.field_value("window") == "3"
    station.close()


@pytest.mark.asyncio
async def test_an_invalid_field_saves_nothing_at_all():
    """A partial save leaves the operator unable to tell which values took."""
    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        app.action_show_tab("settings")
        await pilot.pause()
        before = app.config.paclen
        pane = app.query_one(SettingsPane)
        pane.set_field("paclen", "64")      # valid
        pane.set_field("retries", "banana")  # invalid
        pane._save()
        await pilot.pause()

        assert app.config.paclen == before, "a valid field was saved beside a bad one"
        assert pane.error_for("retries")
        # Under Link's Advanced: Save opened the section and put the cursor
        # on the field, so its error is in the help line.
        await pilot.pause()
        assert pane.current_section == "settings-tab-link"
        fields = app.query_one("#settings-tab-link")
        assert fields.highlighted_option.id == "retries"
        assert app.focused is fields
        help_line = app.query_one("#settings-help-line")
        assert "-error" in help_line.classes and "Retries" in str(help_line.render())
        # Correcting it clears the error.
        pane.set_field("retries", "10")
        assert not pane.error_for("retries")
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
        pane = app.query_one(SettingsPane)
        pane.set_field("theme", "custom")
        pane.open_field("custom_theme.primary")
        await pilot.pause()
        before = app.config.custom_theme.primary
        editor = app.query_one("#settings-edit-input", Input)
        swatch = app.query_one("#settings-edit-swatch")
        assert swatch.display

        editor.value = "#ff00ff"
        await pilot.pause()
        assert "-invalid" not in swatch.classes

        editor.value = "not-a-color"
        await pilot.pause()
        assert "-invalid" in swatch.classes

        pane._save()
        await pilot.pause()
        assert app.config.custom_theme.primary == before, "invalid color must not be saved"
        assert pane.error_for("custom_theme.primary")
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
        pane = app.query_one(SettingsPane)
        pane.set_field("paclen", "32")
        pane._save()
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
            {"name": "ws1ec", "kind": "vara", "host": "127.0.0.1", "mycall": "N1ABC-1",
             "cmd_port": 8300, "data_port": 8301, "script": "", "credential": ""}
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
        app.screen.query_one("#transport-kind", Select).value = "vara"
        await pilot.pause()
        await asyncio.sleep(0.05)
        assert app.screen.query_one("#transport-script-title").display is True
    station.close()


def test_telnet_and_ssh_are_not_radio_kinds():
    """Telnet and SSH are Address Book contacts now (ROADMAP P2); their
    fields, key and known-hosts included, are in the Address Book editor
    (`tests/pilot/test_addressbook_pane.py`)."""
    from kissterm.ui.dialogs import _TRANSPORT_KINDS

    assert "telnet" not in _TRANSPORT_KINDS and "ssh" not in _TRANSPORT_KINDS


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
            app.query_one(SettingsPane).show_section("Radio")
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
            assert host in status and f":{port_b}" not in status, status
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
            app.query_one(SettingsPane).show_section("Radio")
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
        app.query_one(SettingsPane).show_section("Logins")
        await pilot.pause()

        pane = app.query_one(SettingsPane)
        pane._new_credential()
        await pilot.pause()
        await asyncio.sleep(0.05)

        from textual.widgets import Input, TextArea

        from kissterm.ui.dialogs import CredentialScreen

        screen = app.screen
        assert isinstance(screen, CredentialScreen), type(screen).__name__
        # A username and a masked password, not a block of text (operator,
        # 2026-09-28).
        assert not screen.query(TextArea)
        assert screen.query_one("#credential-password", Input).password
        screen.query_one("#credential-name", Input).value = "Personal BBS login"
        screen.query_one("#credential-username", Input).value = "CLYDE"
        screen.query_one("#credential-password", Input).value = "MYPASS"
        await pilot.click("#credential-save")
        await pilot.pause()

        # No keyring in tests, so the password stays in config.
        assert app.config.credentials == [
            {"name": "Personal BBS login", "username": "CLYDE", "text": "MYPASS"}
        ]
        assert app.query_one("#set-credential", Select).value == "Personal BBS login"
        detail = _detail_text_of(app, "#settings-credential-detail")
        assert detail.startswith("Username CLYDE; password saved"), detail
        assert "MYPASS" not in detail
    station.close()


@pytest.mark.asyncio
async def test_editing_a_credential_renames_it_without_leaving_a_duplicate():
    cfg = Config(mycall=str(MYCALL))
    cfg.credentials = [{"name": "Old name", "text": "MYPASS"}]
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 44)) as pilot:
        await _settings_tab(app, pilot)
        app.query_one(SettingsPane).show_section("Logins")
        await pilot.pause()
        app.query_one("#set-credential", Select).value = "Old name"
        await pilot.pause()

        pane = app.query_one(SettingsPane)
        pane._edit_credential()
        await pilot.pause()
        await asyncio.sleep(0.05)

        from textual.widgets import Input

        screen = app.screen
        # The password is never shown back; left empty it is kept.
        assert screen.query_one("#credential-password", Input).value == ""
        screen.query_one("#credential-name", Input).value = "New name"
        screen.query_one("#credential-username", Input).value = "CLYDE"
        await pilot.click("#credential-save")
        await pilot.pause()

        assert app.config.credentials == [{"name": "New name", "username": "CLYDE", "text": "MYPASS"}]
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
        app.query_one(SettingsPane).show_section("Logins")
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


async def _edit(app, pilot, path):
    """Settings open on `path`, its editor loaded."""
    await _settings_tab(app, pilot)
    pane = app.query_one(SettingsPane)
    pane.open_field(path)
    await pilot.pause()
    return pane


@pytest.mark.asyncio
async def test_wide_path_preset_is_selected_and_the_custom_field_stays_hidden():
    cfg = Config(mycall=str(MYCALL))
    cfg.aprs.path = "WIDE2-2"
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 60)) as pilot:
        await _edit(app, pilot, "aprs.path")
        assert app.query_one("#settings-edit-select", Select).value == "WIDE2-2"
        assert app.query_one("#settings-edit-extra").display is False
    station.close()


@pytest.mark.asyncio
async def test_a_path_matching_no_preset_shows_custom_with_the_literal_text():
    """Disable, never clear: a hand-edited config.toml path must stay
    visible and still round-trip on Save, not be silently discarded."""
    cfg = Config(mycall=str(MYCALL))
    cfg.aprs.path = "W1AW-1,WIDE1-1"
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 60)) as pilot:
        pane = await _edit(app, pilot, "aprs.path")
        assert app.query_one("#settings-edit-select", Select).value == "__custom__"
        assert app.query_one("#settings-edit-extra").display is True
        assert app.query_one("#settings-edit-custom", Input).value == "W1AW-1,WIDE1-1"
        assert "W1AW-1,WIDE1-1 (custom)" in pane.row_text("aprs.path")
        pane._save()
        await pilot.pause()
        assert app.config.aprs.path == "W1AW-1,WIDE1-1"
    station.close()


@pytest.mark.asyncio
async def test_picking_custom_reveals_the_field_and_saving_it_persists():
    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        pane = await _edit(app, pilot, "aprs.path")
        app.query_one("#settings-edit-select", Select).value = "__custom__"
        await pilot.pause()
        assert app.query_one("#settings-edit-extra").display is True
        app.query_one("#settings-edit-custom", Input).value = "WIDE1-1,N1ABC-2"
        await pilot.pause()
        pane._save()
        await pilot.pause()
        assert app.config.aprs.path == "WIDE1-1,N1ABC-2"
    station.close()


@pytest.mark.asyncio
async def test_picking_a_preset_after_custom_saves_the_preset_not_the_old_text():
    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        pane = await _edit(app, pilot, "aprs.path")
        select = app.query_one("#settings-edit-select", Select)
        select.value = "__custom__"
        await pilot.pause()
        app.query_one("#settings-edit-custom", Input).value = "some custom text"
        await pilot.pause()
        select.value = "WIDE1-1"
        await pilot.pause()
        assert app.query_one("#settings-edit-extra").display is False
        pane._save()
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
        pane = await _edit(app, pilot, "aprs.path")
        select = app.query_one("#settings-edit-select", Select)
        assert select.value == "ARISS"
        assert app.query_one("#settings-edit-extra").display is False
        select.value = "WIDE1-1"
        await pilot.pause()
        select.value = "ARISS"
        await pilot.pause()
        pane._save()
        await pilot.pause()
        assert app.config.aprs.path == "ARISS"
    station.close()


# ---------------------------------------------------------------------------
# APRS symbol picker (filtered_choice)
# ---------------------------------------------------------------------------

SYMBOL = "#settings-edit-symbol-select"
SYMBOL_FILTER = "#settings-edit-symbol-select-filter"


@pytest.mark.asyncio
async def test_the_stored_symbol_is_preselected():
    cfg = Config(mycall=str(MYCALL))
    cfg.aprs.symbol = "\\!"
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 60)) as pilot:
        await _edit(app, pilot, "aprs.symbol")
        assert app.query_one(SYMBOL, Select).value == "\\!"
    station.close()


@pytest.mark.asyncio
async def test_typing_in_the_symbol_filter_narrows_the_options():
    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        await _edit(app, pilot, "aprs.symbol")
        select = app.query_one(SYMBOL, Select)
        full_count = len(select._options)
        app.query_one(SYMBOL_FILTER, Input).value = "ambulance"
        await pilot.pause()
        assert len(select._options) < full_count
        assert any(v == "/a" for _label, v in select._options)
    station.close()


@pytest.mark.asyncio
async def test_picking_a_filtered_symbol_and_saving_persists_it():
    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        pane = await _edit(app, pilot, "aprs.symbol")
        app.query_one(SYMBOL_FILTER, Input).value = "ambulance"
        await pilot.pause()
        app.query_one(SYMBOL, Select).value = "/a"
        await pilot.pause()
        pane._save()
        await pilot.pause()
        assert app.config.aprs.symbol == "/a"
    station.close()


# ---------------------------------------------------------------------------
# APRS position: decimal and grid square, three rows kept in step
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loading_a_saved_grid_square_does_not_corrupt_the_decimal_position_it_was_computed_from():
    """Opening Settings copies what config.toml has. Recomputing then would
    replace an exact stored position with the centre of its grid square."""
    cfg = Config(mycall=str(MYCALL))
    cfg.aprs.latitude = 41.7148
    cfg.aprs.longitude = -72.7273
    cfg.aprs.grid_square = "FN31pr"
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 60)) as pilot:
        pane = await _edit(app, pilot, "aprs.grid_square")
        await asyncio.sleep(0.05)
        await pilot.pause()
        assert pane.field_value("aprs.latitude") == "41.7148"
        assert pane.field_value("aprs.longitude") == "-72.7273"
        assert pane.field_value("aprs.grid_square") == "FN31pr"
        pane._save()
        await pilot.pause()
        assert (app.config.aprs.latitude, app.config.aprs.longitude) == (41.7148, -72.7273)
    station.close()


@pytest.mark.asyncio
async def test_typing_a_latitude_updates_the_grid_square():
    cfg = Config(mycall=str(MYCALL))
    cfg.aprs.latitude = 40.0
    cfg.aprs.longitude = -75.0
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 60)) as pilot:
        pane = await _edit(app, pilot, "aprs.latitude")
        assert pane.field_value("aprs.grid_square") == ""
        app.query_one("#settings-edit-input", Input).value = "40.0"
        pane.set_field("aprs.longitude", "-75.0")
        await pilot.pause()
        assert pane.field_value("aprs.grid_square") == "FN20ma"
    station.close()


@pytest.mark.asyncio
async def test_typing_a_new_grid_square_recomputes_the_decimal_position():
    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        pane = await _edit(app, pilot, "aprs.grid_square")
        app.query_one("#settings-edit-input", Input).value = "FN31pr"
        await pilot.pause()
        lat = float(pane.field_value("aprs.latitude"))
        lon = float(pane.field_value("aprs.longitude"))
        assert round(lat, 2) == 41.73
        assert round(lon, 2) == -72.71
        assert pane.row_text("aprs.latitude").split()[-2].startswith("41.72")
    station.close()


@pytest.mark.asyncio
async def test_position_round_trips_through_save_and_reload():
    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        pane = await _edit(app, pilot, "aprs.latitude")
        pane.set_field("aprs.latitude", "34.0522")
        pane.set_field("aprs.longitude", "-118.2437")
        await pilot.pause()
        pane._save()
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
        pane = await _edit(app, pilot, "aprs.winlink_check")
        check = app.query_one("#settings-edit-check")
        assert check.value is False
        check.value = True
        await pilot.pause()
        pane._save()
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
        pane = await _edit(app, pilot, "aprs.symbol")
        select = app.query_one(SYMBOL, Select)
        before = select.value
        for needle in ("car", "zzzznotasymbol", "house", ""):
            app.query_one(SYMBOL_FILTER, Input).value = needle
            await pilot.pause()
            await asyncio.sleep(0.05)
            assert select.value == before, f"filter {needle!r} lost the selection"
        assert pane.field_value("aprs.symbol") == before
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
        pane = await _edit(app, pilot, "aprs.symbol")
        select = app.query_one(SYMBOL, Select)
        select.value = "/>"
        await pilot.pause()

        # "boat" cannot match the car symbol, so the pinned current value is
        # the only thing keeping it selected.
        app.query_one(SYMBOL_FILTER, Input).value = "boat"
        await pilot.pause()
        await asyncio.sleep(0.05)
        assert select.value == "/>"
        assert "/>" in {value for _, value in select._options}
        assert pane.field_value("aprs.symbol") == "/>"
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


def _headings(fields) -> list[str]:
    return [str(o.prompt) for o in fields.options if o.disabled and str(o.prompt)]


@pytest.mark.asyncio
async def test_headings_set_off_groups_and_the_help_line_says_when_it_applies():
    """Mail's Home BBS and its optional fields are set off by headings, and
    a field's help line says "next connection" only where that matters."""
    app, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _settings_tab(app, pilot)
        pane = app.query_one(SettingsPane)
        headings = _headings(app.query_one("#settings-tab-mail"))
        assert headings[0].startswith("Home BBS")
        assert "Advanced: Only if the BBS software is not recognised" in headings
        # Under Advanced, Winlink's grid square is under Winlink, not the BBS.
        options = app.query_one("#settings-tab-mail").options
        locator = [o.id for o in options].index("winlink.locator")
        above = [str(o.prompt) for o in options[:locator] if o.disabled and str(o.prompt)]
        assert above[-1] == "Advanced: Winlink (G on a Winlink folder)"
        help_line = app.query_one("#settings-help-line")
        pane.open_field("paclen")
        await pilot.pause()
        assert "next connection" in str(help_line.render())
        pane.open_field("mycall_aliases")
        await pilot.pause()
        text = str(help_line.render())
        assert text.startswith("Also answer to") and "takes effect now" not in text
    station.close()


@pytest.mark.asyncio
async def test_every_section_is_listed_and_fits_80x24_one_row_per_field():
    """All sections in a list that fits, one row per field with tuning
    under "Advanced" after the rest, and no control running off the right
    edge of an 80-column screen."""
    from textual.widgets import OptionList

    from kissterm.ui.settings_pane import section_titles

    app, station = await _app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _settings_tab(app, pilot)
        pane = app.query_one(SettingsPane)
        sections = app.query_one("#settings-sections", OptionList)
        assert [sections.get_option_at_index(i).prompt for i in range(sections.option_count)] == section_titles()
        assert sections.region.height >= len(section_titles()) + 2  # all visible, no scrolling
        for title in section_titles():
            pane.show_section(title)
            await pilot.pause()
            shown = pane.query_one(f"#{pane.current_section}")
            assert shown.region.height >= 5, (title, shown.region)
            for widget in pane.query("#settings-editor *"):
                if widget.region.width:
                    assert widget.region.right <= 80, (title, widget)
        link = app.query_one("#settings-tab-link", OptionList)
        ids = [o.id for o in link.options]
        # The basics first, then the Advanced heading, then tuning.
        advanced = next(i for i, o in enumerate(link.options) if o.disabled and str(o.prompt) == "Advanced")
        assert ids.index("paclen") < advanced < ids.index("t1")
    station.close()


@pytest.mark.asyncio
async def test_custom_colours_show_only_for_the_custom_theme():
    app, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        pane = await _edit(app, pilot, "theme")
        fields = app.query_one("#settings-tab-appearance")
        assert "custom_theme.primary" not in [o.id for o in fields.options]
        app.query_one("#settings-edit-select", Select).value = "custom"
        await pilot.pause()
        assert "custom_theme.primary" in [o.id for o in fields.options]
        assert fields.highlighted_option.id == "theme", "the cursor stays where it was"
        assert pane.field_value("theme") == "custom"
    station.close()


@pytest.mark.asyncio
async def test_a_password_field_is_masked_and_saves_under_a_fixed_name():
    from kissterm.config import find_credential

    app, station = await _app()
    async with app.run_test(size=(120, 60)) as pilot:
        pane = await _edit(app, pilot, "winlink.credential")
        field = app.query_one("#settings-edit-input", Input)
        assert field.password and field.value == "" and field.placeholder == "not set"
        assert pane.row_text("winlink.credential").endswith("not set")
        field.value = "SECRET123"
        await pilot.pause()
        assert "SECRET123" not in pane.row_text("winlink.credential")
        pane._save()
        await pilot.pause()
        assert app.config.winlink.credential == "Winlink"
        assert find_credential(app.config, "Winlink") == "SECRET123"
        assert field.value == "" and "SECRET123" not in field.placeholder
        pane.render_settings(app.config)
        await pilot.pause()
        assert field.value == "" and field.placeholder.startswith("saved in")
        assert "saved in" in pane.row_text("winlink.credential")
        # Moving off and back does not show it either.
        pane.open_field("winlink.account")
        pane.open_field("winlink.credential")
        await pilot.pause()
        assert field.password and field.value == ""
        # Empty keeps what is saved.
        pane._save()
        await pilot.pause()
        assert find_credential(app.config, "Winlink") == "SECRET123"
    station.close()


@pytest.mark.asyncio
async def test_a_contact_list_ends_with_new_contact(tmp_path):
    """Operator, 2026-09-27: "I can't go to the address book to set it up
    from here. Add new should be an option." The Address Book editor opens
    over Settings, preset to Telnet; what it saves fills the field."""
    import asyncio

    from kissterm.addressbook import AddressBook
    from kissterm.ui.dialogs import AddressBookEdit, AddressBookEntryScreen

    cfg = Config(mycall=str(MYCALL))
    app, station = await _app(cfg)
    app.addressbook = AddressBook(tmp_path / "addressbook.json")
    async with app.run_test(size=(120, 40)) as pilot:
        pane = await _edit(app, pilot, "home_bbs.internet")
        select = app.query_one("#settings-edit-select", Select)
        label, value = select._options[-1]
        assert str(label) == "New Telnet/SSH contact..."
        select.value = value
        await pilot.pause()
        await asyncio.sleep(0.05)
        assert isinstance(app.screen, AddressBookEntryScreen)
        assert app.screen._connect_by() == "telnet"
        await app.screen.dismiss(AddressBookEdit(
            "WS1EC by Telnet", internet={"connect_by": "telnet", "host": "ws1ec.example",
                                         "port": "8010"}))
        await pilot.pause()
        assert app.addressbook.find("WS1EC by Telnet").is_internet
        assert pane.field_value("home_bbs.internet") == "WS1EC by Telnet"
        assert "(unsaved)" in pane.row_text("home_bbs.internet")
        # Cancelled, the field keeps what it had.
        pane.open_field("home_bbs.route")
        await pilot.pause()
        select.value = select._options[-1][1]
        await pilot.pause()
        await asyncio.sleep(0.05)
        assert isinstance(app.screen, AddressBookEntryScreen)
        assert app.screen._connect_by() == ""
        await app.screen.dismiss(None)
        await pilot.pause()
        assert pane.field_value("home_bbs.route") == ""
    station.close()


@pytest.mark.asyncio
async def test_a_node_login_is_a_saved_login_ending_with_new_login():
    """Operator, 2026-09-28: "I want to save a username and a password".
    The node's username and password are one saved login, chosen from the
    list; New login... makes one, saved at once, chosen unsaved."""
    import asyncio

    from textual.widgets import Input

    from kissterm.config import login_text
    from kissterm.ui.dialogs import CredentialScreen

    cfg = Config(mycall=str(MYCALL))
    cfg.credentials = [{"name": "Old node", "username": "KC1JMH", "text": "x"}]
    app, station = await _app(cfg)
    async with app.run_test(size=(120, 40)) as pilot:
        pane = await _edit(app, pilot, "home_bbs.internet_credential")
        assert "home_bbs.internet_user" not in pane._draft
        select = app.query_one("#settings-edit-select", Select)
        assert [str(label) for label, _v in select._options] == [
            "(none)", "Old node", "New login..."]
        select.value = select._options[-1][1]
        await pilot.pause()
        await asyncio.sleep(0.05)
        assert isinstance(app.screen, CredentialScreen)
        app.screen.query_one("#credential-name", Input).value = "WS1EC node"
        app.screen.query_one("#credential-username", Input).value = "KC1JMH"
        app.screen.query_one("#credential-password", Input).value = "pw"
        await pilot.pause()
        await pilot.click("#credential-save")
        await pilot.pause()
        await asyncio.sleep(0.05)
        assert login_text(app.config, "WS1EC node") == "KC1JMH\npw"
        assert pane.field_value("home_bbs.internet_credential") == "WS1EC node"
        assert "(unsaved)" in pane.row_text("home_bbs.internet_credential")
        pane._save()
        await pilot.pause()
        assert app.config.home_bbs.internet_credential == "WS1EC node"
    station.close()


@pytest.mark.asyncio
async def test_a_contact_setting_is_chosen_from_the_address_book(tmp_path):
    """"Internet contact" read like a host name (operator, 2026-09-27: "Is
    that the hostname?"). It is a contact: chosen from the Address Book,
    Telnet/SSH ones for the Internet, radio ones for the routes."""
    from kissterm.addressbook import AddressBook

    cfg = Config(mycall=str(MYCALL))
    cfg.home_bbs.internet = "Old node"  # no longer in the book
    app, station = await _app(cfg)
    app.addressbook = AddressBook(tmp_path / "addressbook.json")
    app.addressbook.upsert("WS1EC-2")
    app.addressbook.upsert("WS1EC SSH", connect_by="ssh", host="ws1ec.example", port="22")
    async with app.run_test(size=(120, 40)) as pilot:
        pane = await _edit(app, pilot, "home_bbs.internet")
        pane.render_settings(app.config)
        pane.open_field("home_bbs.internet")
        await pilot.pause()
        select = app.query_one("#settings-edit-select", Select)
        assert [v for _l, v in select._options][:-1] == ["", "WS1EC SSH", "Old node"]
        assert select.value == "Old node", "a contact gone from the book is kept"
        assert "Old node (not in the Address Book)" in pane.row_text("home_bbs.internet")
        select.value = "WS1EC SSH"
        await pilot.pause()
        pane.open_field("home_bbs.route")
        await pilot.pause()
        assert [v for _l, v in select._options][:-1] == ["", "WS1EC-2"]
        pane._save()
        await pilot.pause()
        assert app.config.home_bbs.internet == "WS1EC SSH"
        assert app.config.home_bbs.route == ""
    station.close()


@pytest.mark.asyncio
async def test_headings_have_a_rule_under_them_except_in_ascii_safe_mode():
    """The line across the page under each heading (operator, 2026-09-27:
    without it, Mail is "hard to understand really what's going on")."""
    for ascii_safe in (False, True):
        cfg = Config(mycall=str(MYCALL))
        cfg.ascii_safe = ascii_safe
        app, station = await _app(cfg)
        async with app.run_test(size=(120, 40)) as pilot:
            await _settings_tab(app, pilot)
            app.query_one(SettingsPane).show_section("Mail")
            await pilot.pause()
            mail = app.query_one("#settings-tab-mail")
            prompts = [str(o.prompt) for o in mail.options]
            heading = prompts.index("Home BBS by radio (G on the Mail tab)")
            shot = app.export_screenshot()
            if ascii_safe:
                assert "─" * 20 not in shot
            else:
                assert "─" * 20 in shot, "no rule under the headings"
            assert heading > 0
        station.close()


@pytest.mark.asyncio
async def test_radio_is_boxed_like_every_other_section():
    app, station = await _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _settings_tab(app, pilot)
        pane = app.query_one(SettingsPane)
        pane.show_section("Radio")
        await pilot.pause()
        radio = app.query_one("#settings-tab-radio")
        link = app.query_one("#settings-tab-link")
        assert radio.styles.border_top[0] == link.styles.border_top[0] == "round"
    station.close()


@pytest.mark.asyncio
async def test_the_editor_opens_on_the_row_itself():
    """Operator, 2026-09-27: "The prompts aren't inline, they're below the
    window". Enter lays the editor over the row, control on the value."""
    app, station = await _app()
    async with app.run_test(size=(160, 40)) as pilot:
        pane = await _edit(app, pilot, "home_bbs.ready_text")
        editor = app.query_one("#settings-editor")
        assert not editor.display, "no editor until Enter"
        app.query_one("#settings-tab-mail").focus()
        await pilot.press("enter")
        await pilot.pause()
        fields = app.query_one("#settings-tab-mail")
        line = fields._index_to_line[fields.highlighted]
        row_y = fields.content_region.y + line - round(fields.scroll_offset.y)
        field = app.query_one("#settings-edit-input")
        assert editor.display and field.region.y == row_y, (field.region, row_y)
        assert field.region.x == fields.content_region.x + 27
        assert app.focused is field
        await pilot.press("x", "y", "enter")
        await pilot.pause()
        assert not editor.display and app.focused is fields
        assert pane.field_value("home_bbs.ready_text") == "xy"
    station.close()


@pytest.mark.asyncio
async def test_the_editor_moves_with_its_row_when_the_list_scrolls():
    """Operator, 2026-10-02: click a field, scroll, and the editor stayed
    put over other rows. It follows its row, and closes (keeping its value)
    once the row has scrolled out of sight."""
    app, station = await _app()
    async with app.run_test(size=(120, 24)) as pilot:
        pane = await _edit(app, pilot, "winlink.account")
        fields = app.query_one("#settings-tab-mail")
        fields.focus()
        await pilot.press("enter")
        await pilot.pause()
        editor = app.query_one("#settings-editor")
        field = app.query_one("#settings-edit-input")
        assert editor.display

        def row_y() -> int:
            line = fields._index_to_line[fields.highlighted]
            return fields.content_region.y + line - round(fields.scroll_offset.y)

        assert field.region.y == row_y()
        line = fields._index_to_line[fields.highlighted]
        # The row three lines from the top: the editor goes with it.
        fields.scroll_to(y=max(0, line - 3), animate=False)
        await pilot.pause()
        await pilot.pause()
        assert editor.display and field.region.y == row_y(), (field.region, row_y())
        # The row below the bottom: the edit closes.
        assert line >= fields.content_region.height, "the row must be able to leave the view"
        fields.scroll_to(y=0, animate=False)
        await pilot.pause()
        await pilot.pause()
        assert not editor.display, "an editor left floating over other rows"
        assert pane.field_value("winlink.account") is not None
    station.close()


@pytest.mark.asyncio
async def test_escape_puts_the_old_value_back():
    cfg = Config(mycall=str(MYCALL), paclen=128)
    app, station = await _app(cfg)
    async with app.run_test(size=(100, 33)) as pilot:
        pane = await _edit(app, pilot, "paclen")
        await pilot.press("enter", "ctrl+u", "3", "2")
        await pilot.pause()
        assert pane.field_value("paclen") == "32"
        await pilot.press("escape")
        await pilot.pause()
        assert pane.field_value("paclen") == "128"
        assert not app.query_one("#settings-editor").display
        assert "unsaved" not in pane.row_text("paclen")
    station.close()


@pytest.mark.asyncio
async def test_unsaved_changes_show_and_discard_puts_them_back():
    """Operator, 2026-09-27: "on a widescreen, I barely noticed the Save
    and Cancel buttons". What is not saved says so beside them, in the row
    and in the section list; Save is at the left, under the list."""
    from textual.widgets import OptionList

    cfg = Config(mycall=str(MYCALL), paclen=128)
    app, station = await _app(cfg)
    async with app.run_test(size=(200, 40)) as pilot:
        app._save_config()  # Discard changes reads back what is saved
        pane = await _edit(app, pilot, "paclen")
        discard = app.query_one("#settings-reload", Button)
        assert discard.disabled
        pane.set_field("paclen", "64")
        await pilot.pause()
        assert pane.row_text("paclen").endswith("64  (unsaved)")
        sections = app.query_one("#settings-sections", OptionList)
        assert str(sections.get_option(pane.current_section).prompt) == "Link  *"
        assert "1 unsaved change." in str(app.query_one("#settings-footer").render())
        assert not discard.disabled
        save = app.query_one("#settings-save", Button)
        assert save.region.x < 40, "Save sits at the left, not across a wide screen"
        await pilot.click("#settings-reload")
        await pilot.pause()
        assert pane.field_value("paclen") == "128" and discard.disabled
        assert str(sections.get_option(pane.current_section).prompt) == "Link"
        pane.set_field("paclen", "64")
        pane._save()
        await pilot.pause()
        assert app.config.paclen == 64 and "unsaved" not in pane.row_text("paclen")
        assert "Settings saved." in str(app.query_one("#settings-footer").render())
    station.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("section", ["Mail", "Radio", "Logins"])
async def test_nothing_above_the_box(section):
    """DESIGN.md section 4, "Nothing above the box" (operator, 2026-09-28:
    a note above the box "squishes the box down, losing symmetry and
    alignment"): each section's box starts level with the section list."""
    app, station = await _app(Config(mycall=str(MYCALL)))
    try:
        async with app.run_test(size=(120, 40)) as pilot:
            await _settings_tab(app, pilot)
            pane = app.query_one(SettingsPane)
            pane.show_section(section)
            await pilot.pause()
            listing = app.query_one("#settings-sections").region
            switcher = app.query_one("#settings-switcher")
            box = switcher.query_one(f"#{switcher.current}").region
            assert box.y == listing.y
            assert not app.query("#settings-note")
    finally:
        station.close()
