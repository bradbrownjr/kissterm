"""Pure logic behind the Footer's width-fitting and the Ctrl+P key reference.

No Textual event loop and no isolated config directory needed -- both
functions under test take plain `Binding`/tuple lists, exactly so this stays
an ordinary pytest module. See `kissterm/ui/commands.py`'s module docstring
for why.
"""

from __future__ import annotations

from textual.binding import Binding

from kissterm.ui.commands import (
    ACTION_META,
    fit_footer_bindings,
    iter_binding_entries,
)


def test_beacon_and_its_hidden_legacy_fallback_are_one_entry():
    bindings = [
        Binding("ctrl+shift+b", "beacon_now", "Beacon", key_display="^B"),
        Binding("ctrl+b", "beacon_now", "Beacon", show=False),
    ]
    entries = iter_binding_entries(bindings)
    assert len(entries) == 1
    assert entries[0].keys == ("Ctrl+Shift+B", "Ctrl+B")


def test_tab_switching_aliases_collapse_to_one_entry():
    bindings = [
        Binding("f1", "show_tab('terminal')", "Terminal", show=False),
        Binding("ctrl+1", "show_tab('terminal')", "Terminal", show=False),
    ]
    entries = iter_binding_entries(bindings)
    assert len(entries) == 1
    assert entries[0].category == "Panes"
    assert entries[0].keys == ("F1", "Ctrl+1")


def test_entries_are_ordered_by_category_then_footer_priority():
    bindings = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+t", "toggle_transmit", "TX"),
        Binding("ctrl+n", "connect", "Connect"),
    ]
    entries = iter_binding_entries(bindings)
    # "App" < "Connection" < "Transmit" alphabetically, so Quit sorts first
    # by category even though it is the lowest footer priority of the three.
    assert [e.action for e in entries] == ["quit", "connect", "toggle_transmit"]


def test_an_action_missing_from_action_meta_falls_back_instead_of_crashing():
    bindings = [Binding("ctrl+z", "some_future_action", "Future")]
    entries = iter_binding_entries(bindings)
    assert entries[0].category == "Other"


def test_fit_footer_bindings_keeps_the_highest_priority_items_that_fit():
    # Widths: TX = 2+2+3=7, Connect = 2+7+3=12, Disconnect = 2+10+3=15.
    items = [
        ("toggle_transmit", "^t", "TX"),
        ("connect", "^n", "Connect"),
        ("disconnect", "^D", "Disconnect"),
    ]
    assert fit_footer_bindings(items, budget=100) == items
    # Only TX (7) fits in a 10-column budget; Connect (12) alone would not.
    assert fit_footer_bindings(items, budget=10) == [items[0]]
    assert fit_footer_bindings(items, budget=0) == []


def test_fit_footer_bindings_stops_at_the_first_that_does_not_fit():
    # "quit" (lowest priority, width 5) would easily fit a 20-column budget
    # on its own, but only after skipping "connect" (mid priority, width
    # 94) -- and fitting is a strict priority-ordered prefix, not a bin-
    # packing search, so it never gets the chance.
    items = [
        ("toggle_transmit", "x", "y" * 14),  # priority 0, width 18
        ("connect", "a", "b" * 90),  # priority 1, width 94
        ("quit", "c", "d"),  # priority 10, width 5
    ]
    assert fit_footer_bindings(items, budget=20) == [items[0]]


def test_every_footer_priority_is_unique():
    priorities = [meta.footer_priority for meta in ACTION_META.values()]
    assert len(priorities) == len(set(priorities)), (
        "two actions competing for the same footer_priority makes the "
        "Footer's fit order depend on dict iteration order"
    )
