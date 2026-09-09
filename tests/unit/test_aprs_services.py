"""The shipped APRS gateway directory: integrity, provenance, and lookup.

Most of this file is data-integrity assertions rather than logic tests, and
that is the point. The logic in `kissterm/aprs_services/directory.py` is
forty lines of `tomllib`; the risk lives in the seventeen data files, where
a missing source URL or a command marked "documented" that was actually
half-remembered is invisible until an operator spends airtime on it. See
AGENTS.md: "A reference that silently mixes documented fact with
half-remembered syntax is worse than none."
"""

from __future__ import annotations

import tomllib

import pytest

from kissterm._isolate import isolate

isolate()

from kissterm.aprs_services import (  # noqa: E402
    CONFIDENCE_ORDER,
    DATA_DIR,
    find,
    load_all,
    lookup,
    lookup_callsign,
)
from kissterm.aprs_services.directory import _parse  # noqa: E402


def test_the_directory_is_not_empty():
    """Guards the packaging trap AGENTS.md calls out: a missing
    `package-data` entry makes `DATA_DIR` absent in an installed wheel and
    the picker silently empty."""
    assert DATA_DIR.is_dir(), f"{DATA_DIR} is missing"
    assert len(load_all()) >= 15


def test_every_shipped_file_actually_loads():
    """`load_all` swallows a broken file on purpose so a bad reference can
    never stop the app from working as a terminal. That is right at runtime
    and useless in a test, so parse each file directly instead -- otherwise
    a malformed shipped file would show up only as a service quietly missing
    from the list."""
    on_disk = sorted(DATA_DIR.glob("*.toml"))
    assert on_disk, "no service data files found"
    for path in on_disk:
        _parse(path)  # raises on a missing required field
    assert len(load_all()) == len(on_disk)


@pytest.mark.parametrize("service", load_all(), ids=lambda s: s.id)
class TestEveryService:
    """One class per service so a failure names the culprit in its id."""

    def test_has_a_description_the_ui_can_show(self, service):
        """`summary` lands in a narrow table column next to a callsign like
        `MPAD` that means nothing on its own, and `note` is the header of the
        picker. A blank either way leaves the operator staring at a callsign
        with no way to find out what it is -- which is the problem this whole
        directory exists to fix."""
        assert service.summary.strip()
        assert service.note.strip()
        assert len(service.summary) <= 70, (
            f"{service.id}: summary is {len(service.summary)} chars and will be "
            f"truncated in the contacts table"
        )

    def test_says_where_its_commands_came_from(self, service):
        assert service.source.startswith("http"), f"{service.id}: no source URL"
        assert service.checked, f"{service.id}: no checked date"

    def test_confidence_values_are_from_the_shared_vocabulary(self, service):
        """Same scale as `nodes.reference`, deliberately -- an operator
        should learn one word list, not two."""
        assert service.confidence in CONFIDENCE_ORDER
        for command in service.commands:
            assert command.confidence in CONFIDENCE_ORDER, (
                f"{service.id}/{command.name}: {command.confidence!r} is not a "
                f"confidence level"
            )

    def test_has_at_least_one_command(self, service):
        """A service with nothing to say to it would render as an empty
        picker. `NTSGTE` ships exactly one command (`INFO`) on purpose --
        one is the floor, not zero."""
        assert service.commands

    def test_every_command_can_be_put_in_the_compose_box(self, service):
        for command in service.commands:
            assert command.name.strip()
            assert command.summary.strip(), f"{service.id}/{command.name}: no summary"
            assert command.insert_text.strip()

    def test_no_emoji_or_non_ascii(self, service):
        """AGENTS.md's global rule. The one carve-out is
        `aprs/symbols.py`'s cosmetic `emoji` field; nothing here is covered
        by it, and a non-ASCII byte in a template would go out on a
        byte-oriented, mostly-ASCII medium."""
        blob = " ".join(
            [service.name, service.summary, service.note, service.region]
            + [f"{c.name} {c.summary} {c.template} {c.detail}" for c in service.commands]
        )
        offenders = sorted({ch for ch in blob if ord(ch) > 127})
        assert not offenders, f"{service.id}: non-ASCII characters {offenders}"


def test_ids_and_callsigns_are_unique():
    """A duplicate callsign would make `lookup_callsign` return whichever
    file sorted first, silently, and show one service's commands under
    another's name."""
    services = load_all()
    ids = [s.id for s in services]
    assert len(ids) == len(set(ids))
    callsigns = [c for s in services for c in s.callsigns]
    assert len(callsigns) == len(set(callsigns)), "two services claim one addressee"


def test_the_id_matches_the_filename():
    """So a reader who sees `gateway = "wxbot"` in a config file can find
    the file without grepping."""
    for path in sorted(DATA_DIR.glob("*.toml")):
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
        assert raw["service"]["id"] == path.stem


def test_winlink_ships_its_documented_command_set():
    """The entry that prompted the whole feature. Spot-checks the specific
    strings against <https://winlink.org/APRSLink> rather than just counting
    commands -- a transcription error here sends a malformed command to a
    real gateway."""
    winlink = lookup("winlink")
    assert winlink is not None
    assert winlink.callsign == "WLNK-1"
    names = {c.name for c in winlink.commands}
    assert {"L", "SP", "/EX", "SMS", "AL"} <= names
    listing = next(c for c in winlink.commands if c.name == "L")
    assert listing.insert_text == "L"
    compose = next(c for c in winlink.commands if c.name == "SP")
    assert compose.insert_text.startswith("SP ")


#: The `Nx\` line identifiers defined in the APRS Protocol Reference 1.0.1,
#: chapter 14, "NTS Radiograms" -- the whole published list, and nothing else.
_NTS_LINES_FROM_THE_SPEC = {
    "N#", "NA", "NP", "N1", "N2", "N3", "N4", "N5", "N6", "NS", "NR",
}


def test_ntsgte_radiogram_lines_are_the_documented_ones():
    """A malformed radiogram filed into the National Traffic System goes in
    under the operator's own callsign, so this entry is the one place in the
    directory where an invented field costs someone else real work.

    The `Nx\\` line set is therefore closed: exactly what chapter 14 of the
    APRS Protocol Reference defines, no more. A future session that wants to
    add a line identifier has to cite it, and if it is not in that chapter it
    belongs in the `recalled` set below instead.
    """
    ntsgte = lookup("ntsgte")
    assert ntsgte is not None
    lines = {c.name for c in ntsgte.commands if c.name.startswith("N") and c.name != "NE"}
    assert lines == _NTS_LINES_FROM_THE_SPEC


def test_ntsgte_labels_what_did_not_come_from_the_specification():
    """`QTC` and `NE` were transcribed from screenshots of one real NTSGTE
    session, not from a specification -- so they are honest to ship and
    dishonest to present at the same confidence as the rest."""
    ntsgte = lookup("ntsgte")
    assert ntsgte is not None
    by_name = {c.name: c for c in ntsgte.commands}
    assert by_name["QTC"].confidence == "recalled"
    assert by_name["NE"].confidence == "recalled"
    for name in _NTS_LINES_FROM_THE_SPEC | {"INFO"}:
        assert by_name[name].confidence == "documented", name


def test_ntsgte_radiogram_templates_fit_one_message_line():
    """Chapter 14: a line may be at most 67 characters INCLUDING the
    3-character identifier, and the gateway truncates rather than complains.
    A shipped template longer than that would silently lose its tail."""
    ntsgte = lookup("ntsgte")
    assert ntsgte is not None
    for command in ntsgte.commands:
        assert len(command.insert_text) <= 67, command.name


def test_lookup_by_callsign_including_aliases():
    assert lookup_callsign("WLNK-1") is lookup("winlink")
    assert lookup_callsign("wlnk-1") is lookup("winlink")
    # WHO-15 is the same service for clients that cannot type a non-AX.25
    # SSID, so a contact saved against either has to resolve to one entry.
    assert lookup_callsign("WHO-15") is lookup("whois")
    assert lookup_callsign("WHO-IS") is lookup("whois")


def test_lookup_of_an_ordinary_station_is_none():
    """A bare callsign that is nobody's gateway must not match anything --
    otherwise messaging a friend would offer them WXBOT's command set."""
    assert lookup_callsign("K1ABC-9") is None
    assert lookup_callsign("") is None
    assert lookup("") is None
    assert lookup("no-such-service") is None


def test_find_searches_names_callsigns_and_commands():
    assert lookup("winlink") in find("winlink")
    assert lookup("winlink") in find("WLNK")
    # Free text against a summary/note, not just an identifier.
    assert lookup("wxbot") in find("forecast")
    assert find("") == load_all()
    assert find("zzzznotathing") == ()


def test_command_search_within_one_service():
    wxbot = lookup("wxbot")
    assert wxbot is not None
    assert wxbot.find("") == wxbot.commands
    assert any(c.name == "metar" for c in wxbot.find("metar"))
    assert wxbot.find("zzzznotathing") == ()


def test_recalled_commands_exist_and_are_labelled():
    """Not every shipped command could be sourced to a fetched page, and the
    honest answer is to ship it marked rather than to drop it or to promote
    it. If this ever finds nothing, someone has quietly relabelled the
    unverified entries as documented."""
    recalled = [
        (s.id, c.name)
        for s in load_all()
        for c in s.commands
        if c.confidence == "recalled"
    ]
    assert recalled, "no command is marked 'recalled' -- did provenance get flattened?"
