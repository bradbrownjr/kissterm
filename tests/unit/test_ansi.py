"""The allowlist has to be tested from the attacker's side, not the sender's.

A test that only checks "red text stays red" would pass with a completely
broken filter. The cases that matter are the ones where a remote station tries
to do something to the operator's terminal, so most of this file is escape
sequences that must NOT survive -- and, just as important, must not survive as
their own payload spilled into the text, which is how this class of filter
usually fails.
"""

from __future__ import annotations

import pytest

from kissterm.ansi import SAFE_SGR, filter_ansi, strip_ansi, to_text


def esc(text: str) -> bytes:
    """Write escape sequences readably. "ESC" and "BEL" become their bytes."""
    return text.replace("ESC", "\x1b").replace("BEL", "\x07").encode("latin-1")


# ---------------------------------------------------------------------------
# What must survive
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        b"plain ascii",
        b"a\tb",
        b"line one\nline two",
        bytes(range(0x20, 0x7F)),
    ],
)
def test_ordinary_text_is_untouched(raw):
    assert filter_ansi(raw) == raw


@pytest.mark.parametrize(
    "sequence",
    [
        "ESC[0m",
        "ESC[1m",
        "ESC[31m",
        "ESC[1;31;47m",
        "ESC[90m",
        "ESC[107m",
        "ESC[38;5;208m",
        "ESC[48;2;10;20;30m",
    ],
)
def test_allowlisted_sgr_survives(sequence):
    raw = esc(sequence + "text" + "ESC[0m")
    assert filter_ansi(raw) == raw
    assert strip_ansi(raw) == "text"


def test_colour_reaches_the_rendered_text():
    """Not just "the bytes survived" -- Rich must actually apply the style."""
    text = to_text(esc("ESC[31mred ESC[0mplain"))
    assert text.plain == "red plain"
    assert len(text.spans) == 1, text.spans
    span = text.spans[0]
    # Colour applies to "red " and stops at the reset -- not to the whole
    # string, which is what a filter that dropped the reset would produce.
    assert (span.start, span.end) == (0, 4)
    assert span.style.color is not None and span.style.color.number == 1


def test_bare_csi_m_is_a_reset_not_a_deletion():
    """`CSI m` with no parameters means reset. Dropping it would leave the
    previous style applied to everything after it."""
    assert filter_ansi(esc("boldESC[m")) == esc("boldESC[0m")


# ---------------------------------------------------------------------------
# What must not survive -- and must not leak its payload as text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sequence",
    [
        "ESC[2J",  # erase display
        "ESC[H",  # cursor home
        "ESC[10;20H",  # cursor position
        "ESC[?25l",  # hide cursor (private parameter)
        "ESC[?1049h",  # alternate screen buffer
        "ESC[6n",  # device status report -- the reply is typed as input
        "ESC[3J",  # erase scrollback
        "ESC[1;40r",  # scroll region
        "ESC[2K",  # erase line
        "ESCc",  # full reset
        "ESC7",  # save cursor
        "ESC(0",  # line-drawing charset
        "ESC]0;window titleBEL",
        "ESC]52;c;cGVybmljaW91cwo=BEL",  # clipboard write
        "ESC]8;;http://example.invalid/ESC\\",  # hyperlink
        "ESCPqsixel dataESC\\",  # DCS
        "ESC_application programESC\\",  # APC
        "ESC^privacy messageESC\\",  # PM
    ],
)
def test_dangerous_sequences_are_removed_entirely(sequence):
    raw = esc("before" + sequence + "after")
    out = filter_ansi(raw)
    assert b"\x1b" not in out, out
    # The whole sequence is consumed. Leaving its payload behind as literal
    # text is how this filter usually fails -- it looks like it worked.
    assert out == b"beforeafter", out


@pytest.mark.parametrize("blink", ["ESC[5m", "ESC[6m"])
def test_blink_is_not_allowlisted(blink):
    """A remote station does not get to impose a photosensitivity hazard."""
    assert filter_ansi(esc(blink + "x")) == b"x"


def test_conceal_is_not_allowlisted():
    """Text that renders invisible is a spoofing primitive, not formatting."""
    assert filter_ansi(esc("ESC[8mhidden")) == b"hidden"


def test_a_rejected_parameter_is_dropped_but_its_neighbours_survive():
    assert filter_ansi(esc("ESC[1;5;31mx")) == esc("ESC[1;31mx")


def test_an_sgr_with_nothing_allowlisted_left_vanishes_rather_than_resetting():
    """`CSI 5 m` must not become `CSI m` -- that is a reset the sender never
    asked for, and it would clear styling the operator's own UI applied."""
    assert filter_ansi(esc("ESC[5mx")) == b"x"


def test_c1_control_bytes_are_stripped():
    """0x9B is CSI on a terminal in 8-bit mode -- an escape sequence with no
    ESC byte in front of it, which a parser looking only for 0x1B sails past."""
    out = filter_ansi(b"\x9b2J")
    assert b"\x9b" not in out


@pytest.mark.parametrize(
    "raw",
    [
        b"\x1b",
        b"\x1b[",
        b"\x1b[38;5",
        b"\x1b]0;unterminated",
        b"\x1bP",
        b"\x1b[999",
    ],
)
def test_a_truncated_sequence_is_discarded_not_held_over(raw):
    """The next chunk is a separate frame, possibly from another station.
    Splicing them would let one station's partial sequence be completed by
    another's payload."""
    out = filter_ansi(raw)
    assert b"\x1b" not in out


def test_an_unterminated_osc_does_not_eat_the_rest_of_the_session():
    out = filter_ansi(esc("ESC]0;titleESC[31mred text"))
    assert b"red text" in out


def test_malformed_extended_colour_drops_the_whole_sequence():
    """Without knowing where its parameters end there is no safe place to
    resume, so the sequence goes rather than being partly reinterpreted."""
    assert filter_ansi(esc("ESC[38;9;1mx")) == b"x"
    assert filter_ansi(esc("ESC[38;2;1;2mx")) == b"x"


def test_out_of_range_colour_components_are_rejected():
    assert filter_ansi(esc("ESC[38;5;999mx")) == b"x"


def test_absurdly_long_parameter_list_is_dropped():
    params = ";".join(["1"] * 200)
    assert filter_ansi(esc(f"ESC[{params}mx")) == b"x"


def test_colon_subparameter_form_is_rejected():
    """The ITU colon form changes how the parameter list is read; not
    supporting it is fine, misreading it is not."""
    assert filter_ansi(esc("ESC[38:2::1:2:3mx")) == b"x"


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


def test_line_endings_match_sanitize():
    """Both filters must agree about where a line ends, or the terminal pane
    and the monitor pane disagree about the same frame."""
    from kissterm.monitor import sanitize

    raw = b"a\r\nb\rc\nd"
    assert strip_ansi(raw) == sanitize(raw)


def test_high_bytes_decode_rather_than_raising():
    """latin-1 is total. A corrupt frame must not lose its readable part."""
    assert strip_ansi(b"caf\xe9 \xff\xfe ok").endswith(" ok")


def test_nul_and_other_c0_are_stripped():
    assert strip_ansi(b"a\x00b\x07c\x1fd") == "abcd"


def test_safe_sgr_excludes_the_ones_that_matter():
    for code in (5, 6, 8, 58, 59):
        assert code not in SAFE_SGR
