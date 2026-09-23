"""Shipped command references, family detection, and the airtime arithmetic.

The reason this data ships instead of being asked for at runtime is airtime:
at 1200 baud half-duplex a couple of kilobytes of help text is roughly twenty
seconds during which nobody else on the frequency can transmit. These tests pin
that reasoning down so it does not get "optimised" away later.
"""

from __future__ import annotations

import re

import pytest

from kissterm.nodes import (
    Command,
    CommandReference,
    airtime_seconds,
    available_families,
    load_all,
    load_family,
)
from kissterm.nodes.reference import (
    CONFIDENCE_ORDER,
    application_named,
    describe_airtime,
    identify_family,
)


def test_shipped_references_load():
    families = load_all()
    assert families, "no command references shipped"
    assert "bpq32" in available_families()


def test_every_command_declares_a_summary_and_confidence():
    for family in load_all():
        assert family.commands, f"{family.id} ships no commands"
        for command in family.commands:
            assert command.summary, f"{family.id}:{command.name} has no summary"
            assert command.confidence in CONFIDENCE_ORDER, (
                f"{family.id}:{command.name} has confidence "
                f"{command.confidence!r}, not one of {CONFIDENCE_ORDER}"
            )


def test_bpq_prompt_is_recognised():
    """ALIAS:CALL} as WS1EC-15 sends it and G8BPQ documents it, and the
    CTEXT sign-off seen on WS1EC-15. The earlier fixture, "W1AW-7:CCEMA}",
    had the SSID on the alias side -- a shape no BPQ32 node sends -- and the
    pattern written to match it never matched the real node."""
    for prompt in ("CCEMA:WS1EC-15} ", "NOTTS:G8BPQ-3}", "de WS1EC-15>"):
        family = identify_family(prompt)
        assert family is not None and family.id == "bpq32", f"missed {prompt!r}"


def test_detection_does_not_guess_wildly():
    """A wrong family shown confidently is worse than 'unknown node'."""
    for text in ("hello world", "Connected to somewhere", "", "1234567890"):
        assert identify_family(text) is None, f"false match on {text!r}"


def test_tnc_command_prompt_is_recognised():
    family = identify_family("cmd:")
    assert family is not None and family.id == "tnc2"


def test_jnos_banner_is_recognised():
    family = identify_family("Welcome to W1AW JNOS 2.0k\n")
    assert family is not None and family.id == "jnos"


def test_jnos_ships_no_detect_prompt():
    """Deliberate: JNOS's stock prompt can be exactly tnc2.toml's 'cmd:'
    pattern, so detection here is banner-only -- see jnos.toml's header."""
    family = load_family("jnos")
    assert family is not None
    assert family.detect_prompt == ()


def test_thenet_x1j_loads_with_documented_commands():
    family = load_family("thenet-x1j")
    assert family is not None
    assert family.name == "TheNet X-1J"
    assert family.confidence == "documented"
    assert {command.name for command in family.commands} >= {
        "CONNECT", "INFO", "NODES", "ROUTES", "USERS", "MHEARD", "BYE",
    }
    assert all(command.confidence == "documented" for command in family.commands)


def test_thenet_x1j_is_deliberately_not_auto_detected():
    """The sourced guide has no unique prompt/banner; unknown is safer."""
    family = load_family("thenet-x1j")
    assert family is not None
    assert family.detect_prompt == ()
    assert family.detect_banner == ()
    assert identify_family("THENET:G8KBB-5>") is None
    assert identify_family("CCEMA:WS1EC-15}").id == "bpq32"
    assert identify_family("cmd:").id == "tnc2"
    assert identify_family("Welcome to W1AW JNOS 2.0k\n").id == "jnos"


def test_completion_needs_a_prefix():
    """An empty prefix must not dump the whole command set into a suggestion."""
    ref = CommandReference(family=load_family("bpq32"))
    assert ref.complete("") == ()
    assert ref.complete("   ") == ()


def test_completion_matches_names_and_aliases():
    ref = CommandReference(family=load_family("bpq32"))
    assert any(c.name == "N" for c in ref.complete("N"))
    assert any(c.name == "N" for c in ref.complete("nod")), "alias NODES not matched"
    assert ref.complete("ZZZZ") == ()


def test_learned_commands_supplement_but_never_replace_shipped_ones():
    """Local additions are real; shipped entries still win on a collision.

    A real BPQ32 node in the sibling bpq-apps repo adds CALENDAR, FORMS and
    WALL via APPLICATION lines -- no shipped table could know them.
    """
    ref = CommandReference(
        family=load_family("bpq32"),
        learned=(
            Command(name="CALENDAR", summary="local app", confidence="learned"),
            Command(name="B", summary="clobbered?", confidence="learned"),
        ),
    )
    names = [c.name for c in ref.commands]
    assert "CALENDAR" in names, "a learned local command was dropped"
    bye = next(c for c in ref.commands if c.name == "B")
    assert bye.confidence != "learned", "a learned entry overwrote a shipped one"
    assert names.count("B") == 1


def test_search_covers_summary_text():
    ref = CommandReference(family=load_family("bpq32"))
    assert any(c.name == "U" for c in ref.find("connected"))


def test_reference_works_with_no_family():
    """An unidentified node must not break the pane."""
    ref = CommandReference()
    assert ref.commands == ()
    assert ref.complete("N") == ()
    assert ref.find("anything") == ()


# ---------------------------------------------------------------------------
# Airtime -- the whole reason this data ships
# ---------------------------------------------------------------------------


def test_airtime_grows_with_size():
    small = airtime_seconds(512)
    medium = airtime_seconds(2048)
    large = airtime_seconds(8192)
    assert small < medium < large


def test_airtime_includes_framing_not_just_baud():
    """Dividing by the baud rate alone understates a real transfer.

    At 2 KB with a 256-byte paclen that is eight frames, so eight keyups and
    eight turnarounds on top of the bits themselves -- measured at roughly
    1.37x the naive figure. The threshold below is deliberately under that so
    the test checks the overhead is *modelled*, not that it equals today's
    constants, which are tunable.
    """
    naive = 2048 * 8 / 1200
    assert airtime_seconds(2048) > naive * 1.2, (
        "estimate ignores framing, keyup and turnaround"
    )


def test_a_verbose_help_text_is_expensive_enough_to_warn_about():
    """The number that justifies shipping references instead of asking."""
    assert airtime_seconds(2048) > 10, "2 KB should be well over ten seconds"


# ---------------------------------------------------------------------------
# Harvesting -- turning a raw '?' reply into candidate command names
# ---------------------------------------------------------------------------


def test_parse_harvested_finds_the_bpq_apps_example():
    """The exact roadmap example: a stock BPQ32 with local APPLICATION
    additions, none of which any shipped table could know about."""
    from kissterm.nodes.reference import parse_harvested

    text = (
        "Valid commands are:\n"
        "CALENDAR FORMS WALL GOPHER PREDICT\n"
    )
    names = parse_harvested(text)
    for expected in ("CALENDAR", "FORMS", "WALL", "GOPHER", "PREDICT"):
        assert expected in names


def test_parse_harvested_excludes_single_letter_tokens():
    """Single-letter commands (C, B, D...) are already covered by the
    shipped references -- see the function's own docstring for why
    catching them here would just be matching ordinary prose."""
    from kissterm.nodes.reference import parse_harvested

    assert parse_harvested("C B D I") == ()


def test_parse_harvested_filters_ordinary_prose():
    from kissterm.nodes.reference import parse_harvested

    text = "Welcome to the node. Please enter your callsign to continue."
    names = parse_harvested(text)
    assert "WELCOME" not in names
    assert "PLEASE" not in names
    assert "CALLSIGN" not in names


def test_parse_harvested_deduplicates_and_uppercases():
    from kissterm.nodes.reference import parse_harvested

    names = parse_harvested("stats STATS Stats")
    assert names == ("STATS",)


def test_parse_harvested_caps_the_result():
    from kissterm.nodes.reference import HARVEST_MAX_NAMES, parse_harvested

    text = " ".join(f"cmd{i}" for i in range(HARVEST_MAX_NAMES + 20))
    assert len(parse_harvested(text)) == HARVEST_MAX_NAMES


def test_parse_harvested_empty_text_yields_nothing():
    from kissterm.nodes.reference import parse_harvested

    assert parse_harvested("") == ()
    assert airtime_seconds(8192) > 60, "8 KB should be over a minute"


def test_faster_link_is_cheaper():
    assert airtime_seconds(2048, baud=9600) < airtime_seconds(2048, baud=1200)


def test_describe_airtime_is_human():
    assert "second" in describe_airtime(2048)
    assert "minute" in describe_airtime(16384)
    assert airtime_seconds(0) == 0.0


def test_bpq_application_banners_are_the_applications_not_the_node():
    """BPQMail's SID and prompt name the BBS; nothing there is a node command."""
    for text in ("[BPQ-6.0.23.1-B2FWIHJM$]", "de WS1EC#>"):
        family = identify_family(text)
        assert family is not None and family.id == "bpqmail", f"missed {text!r}"


def test_a_node_names_the_application_it_hands_over_to():
    bpq = load_family("bpq32")
    match = re.search(bpq.enter_pattern, "CCEMA:WS1EC-15} Connected to BBS", re.MULTILINE)
    assert match is not None
    assert application_named(match.group(1)).id == "bpqmail"
    assert application_named("CHAT").id == "bpqchat"
    # A sysop's own application has no shipped reference, and none is guessed.
    assert application_named("CALENDAR") is None


def test_every_command_names_its_source():
    """Every shipped entry can be checked against where it came from."""
    for family in load_all():
        for command in family.commands:
            if command.confidence in ("documented", "verified") and family.source:
                assert command.source, f"{family.id}:{command.name} has no source"


def test_applications_carry_their_own_context():
    assert {c.context for c in load_family("bpqmail").commands} == {"bbs"}
    assert {c.context for c in load_family("bpqchat").commands} == {"application"}
    assert {c.context for c in load_family("bpq32").commands} == {"node"}


def test_sysop_commands_are_marked():
    assert next(c for c in load_family("bpq32").commands if c.name == "PASSWORD").sysop
    assert next(c for c in load_family("bpqmail").commands if c.name == "KH").sysop
    assert not next(c for c in load_family("bpqmail").commands if c.name == "LH").sysop


def test_a_harvest_marks_shipped_commands_and_never_describes_its_own():
    ref = CommandReference(
        family=load_family("bpq32"),
        learned=(Command("BYE", confidence="learned"), Command("WALL", confidence="learned")),
    )
    by_name = {c.name: c for c in ref.commands}
    assert "BYE" not in by_name, "an alias of B must mark B, not add a row"
    assert ref.offered == {"B"}
    assert ref.tier(by_name["B"]) == "verified on air, offered here"
    assert ref.tier(by_name["NRR"]) == "published"
    assert ref.tier(by_name["WALL"]) == "harvested only"
    assert by_name["WALL"].summary == ""
