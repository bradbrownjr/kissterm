"""A row of buttons that goes two by two when it does not fit.

Four buttons need 44 columns at DESIGN.md's `min-width: 10`, and a
slide-out beside another pane often has fewer: the Address Book on the
Mail tab at 100 columns had 27 (reported 2026-09-26, "Buttons are getting
cut off on the address book"), the APRS contacts at 80 had the same
trouble. Shrinking the buttons breaks the one button shape; wrapping them
keeps it. Textual has no flex-wrap, so the row measures what it needs on
every resize and switches to a two-column grid (`.-narrow`, `styles.py`).
"""

from __future__ import annotations

from rich.cells import cell_len
from textual import events
from textual.containers import Horizontal
from textual.widgets import Button


class ButtonRow(Horizontal):
    def on_resize(self, event: events.Resize) -> None:
        self.refit()

    def refit(self) -> None:
        # Each button: its label, 2 of padding, 2 of border, at least 10;
        # plus the 1-column gap after it.
        need = sum(max(10, cell_len(str(b.label)) + 4) + 1 for b in self.query(Button))
        self.set_class(self.size.width < need, "-narrow")
