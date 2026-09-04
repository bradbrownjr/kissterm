"""Shipped command references, family detection, and the airtime arithmetic.

The reason this data ships instead of being asked for at runtime is airtime:
at 1200 baud half-duplex a couple of kilobytes of help text is roughly twenty
seconds during which nobody else on the frequency can transmit. These tests pin
that reasoning down so it does not get "optimised" away later.
"""

from __future__ import annotations

import pytest

from kissterm.nodes import (
    Command,
    CommandReference,
    airtime_seconds,
    available_families,
    load_all,
    load_family,
)
from kissterm.nodes.reference import CONFIDENCE_ORDER, describe_airtime, identify_family


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
    """Both prompt shapes seen on real BPQ nodes."""
    for prompt in ("W1AW-7:CCEMA}", "de WS1EC-15>"):
        family = identify_family(prompt)
        assert family is not None and family.id == "bpq32", f"missed {prompt!r}"


def test_detection_does_not_guess_wildly():
    """A wrong family shown confidently is worse than 'unknown node'."""
    for text in ("hello world", "Connected to somewhere", "", "1234567890"):
        assert identify_family(text) is None, f"false match on {text!r}"


def test_tnc_command_prompt_is_recognised():
    family = identify_family("cmd:")
    assert family is not None and family.id == "tnc2"


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
    assert airtime_seconds(8192) > 60, "8 KB should be over a minute"


def test_faster_link_is_cheaper():
    assert airtime_seconds(2048, baud=9600) < airtime_seconds(2048, baud=1200)


def test_describe_airtime_is_human():
    assert "second" in describe_airtime(2048)
    assert "minute" in describe_airtime(16384)
    assert airtime_seconds(0) == 0.0
