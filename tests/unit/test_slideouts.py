"""The slide-out width rule, checked at every terminal width.

`kissterm/ui/slideouts.py` is deliberately pure arithmetic so this file can
exist: a layout rule that can only be checked by mounting an app and looking
at a screenshot is a layout rule that silently rots. The APRS contact table's
descriptions fell off the right-hand edge of the pane for a whole release with
the entire suite passing, which is what that module and this file are both an
answer to.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

from kissterm.ui.slideouts import (  # noqa: E402
    AUTO_OPEN_MIN,
    MAX_PANEL,
    MIN_MAIN,
    MIN_PANEL,
    auto_open,
    split,
)

#: The table in the plan this shipped from, reproduced as a test. If one of
#: these numbers has to change, that is a design decision and it belongs in
#: DESIGN.md, not in a quiet edit to the constants.
WORKED_EXAMPLES = (
    # (terminal width, main column, panel, panel replaces main)
    (40, 0, 40, True),
    (64, 40, 24, False),
    (80, 40, 40, False),
    (96, 41, 55, False),
    (110, 47, 63, False),
    (140, 66, 74, False),
    (200, 126, 74, False),
)


def test_the_worked_examples_hold():
    for total, main, panel, replaces in WORKED_EXAMPLES:
        layout = split(total)
        assert (layout.main, layout.panel, layout.replaces_main) == (
            main,
            panel,
            replaces,
        ), total


def test_the_main_column_never_loses_its_floor():
    """The operator's one hard number: the chat or terminal beside the panel
    keeps 40 columns. The panel takes the squeeze, and its table scrolls."""
    for total in range(1, 241):
        layout = split(total)
        if layout.replaces_main:
            # Nothing to share -- the panel has the pane to itself, which is
            # the honest answer on a 40-column terminal.
            assert layout.main == 0
            assert layout.panel == total
            continue
        assert layout.main >= MIN_MAIN, total
        assert layout.panel >= MIN_PANEL, total
        assert layout.main + layout.panel == total, total


def test_the_panel_never_bloats_past_what_it_can_use():
    for total in range(1, 241):
        assert split(total).panel <= max(total, MAX_PANEL)
    assert split(400).panel == MAX_PANEL


def test_a_wide_terminal_gives_the_extra_columns_to_the_conversation():
    """Past `MAX_PANEL` every further column belongs to the chat. A panel that
    keeps growing with the window is a contact list padded with blank space
    next to a conversation that could have used it."""
    assert split(140).panel == split(200).panel == MAX_PANEL
    assert split(200).main > split(140).main


def test_auto_open_starts_at_a_standard_terminal():
    """80 columns, because that is the width a terminal is unless someone
    changed it. Narrower than that, opening unasked would be a surprise --
    `split` would happily divide a 64-column pane, and should not be asked
    to."""
    assert AUTO_OPEN_MIN == 80
    assert not auto_open(79)
    assert auto_open(80)
    assert auto_open(200)
    for total in range(1, 80):
        assert not auto_open(total), total


def test_the_very_old_terminal_case_is_a_swap_not_a_split():
    """40 columns is the old-hardware floor the operator named. There is no
    useful split of it, so the panel replaces the main column while it is
    open rather than leaving a two-character message box beside it."""
    assert split(40).replaces_main
    assert split(63).replaces_main
    assert not split(64).replaces_main


def test_no_width_produces_a_negative_or_absurd_split():
    for total in range(0, 241):
        layout = split(total)
        assert layout.panel >= 0 and layout.main >= 0, total
        assert layout.panel <= total, total
