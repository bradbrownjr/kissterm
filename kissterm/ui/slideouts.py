"""How wide a slide-out column gets, and whether it opens by itself.

Two panes have a collapsible right-hand column -- the Terminal pane's Address
Book and the APRS pane's contacts list (`DESIGN.md`'s "slide-out panels"
section). Both used to be a flat `width: 58%` in CSS and both started closed
on every launch, which wasted half a wide screen and cost a `Ctrl+G` every
time the app came up.

**Why the split cannot be expressed in CSS.** The rule the operator asked for
is "58%, but never leave the chat or terminal less than 40 columns" -- and
Textual CSS has no arithmetic to relate a width to a sibling's minimum. So the
width is computed here and applied to `styles.width`. Keeping it as pure
arithmetic in its own module, rather than inline in either pane, is the same
choice `aprs_pane._column_widths` already made: a layout rule you can test at
every terminal width from 20 to 240 without mounting a widget is a layout rule
that stays correct.

**The numbers, and where they come from.** 80 columns is the standard terminal
width and is the threshold for opening unasked; 40 columns is the floor for
the chat or terminal beside it, and also the width of the very old terminals
this still has to be usable on. Below 40 + 24 there is not enough room for
both, so the panel takes the pane instead of splitting it -- half a contact
list beside a two-character message box is worse than either one alone. The
contact table itself handles the squeeze by scrolling sideways, which is
`DataTable`'s own behaviour and was explicitly accepted rather than worked
around: "I would allow horizontal scroll for the contacts/addresses if below
its minimum width".
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.widget import Widget

#: A standard terminal. At or above this the slide-out opens on its own.
AUTO_OPEN_MIN = 80
#: The chat or terminal column never goes below this while both are shown.
MIN_MAIN = 40
#: Below this the panel is not worth splitting for -- it replaces the main
#: column for as long as it is open instead.
MIN_PANEL = 24
#: Past this the contact list has nothing more to show, so the extra width is
#: worth more to the conversation beside it.
MAX_PANEL = 74
#: The proportion the two slide-outs have always used, kept where it fits.
PREFERRED = 0.58


@dataclass(frozen=True, slots=True)
class Split:
    """How one pane's width divides between its main column and its panel."""

    #: Cells for the slide-out. Equal to the whole pane when `replaces_main`.
    panel: int
    #: Cells for the chat/terminal column. Zero when `replaces_main`.
    main: int
    #: Whether the panel takes the pane rather than sitting beside it.
    replaces_main: bool


def split(total: int) -> Split:
    """Divide `total` cells between the main column and an OPEN slide-out.

    Says nothing about whether it should be open -- that is `auto_open`.
    """
    if total <= 0:
        return Split(panel=0, main=0, replaces_main=False)
    panel = min(int(total * PREFERRED), MAX_PANEL, total - MIN_MAIN)
    if panel < MIN_PANEL:
        return Split(panel=total, main=0, replaces_main=True)
    return Split(panel=panel, main=total - panel, replaces_main=False)


def auto_open(total: int) -> bool:
    """Whether a slide-out should open without being asked, at `total` cells.

    Deliberately a plain width threshold rather than "whatever `split` leaves
    room for": `split` will happily divide a 64-column pane, but an operator
    who has chosen a 64-column window did not ask for half of it to become a
    contact list. 80 is where it stops being a surprise.
    """
    return total >= AUTO_OPEN_MIN


class SlideOut:
    """The open/closed state and width of one pane's slide-out column.

    Both panes own one of these rather than repeating the same dozen lines,
    because the two columns have to behave identically -- they are one key
    (`Ctrl+G`) and one rule in `DESIGN.md`, and two copies of that rule would
    drift the first time one pane was touched and the other was not.

    **`taken_over` is the whole reason this is a class and not a function.**
    A resize must never overrule the operator. Once they have opened or closed
    the panel themselves, the width rule stops deciding for that pane for the
    rest of the session; without that flag, dragging a window wider would
    re-open a panel someone had just closed on purpose.
    """

    def __init__(self, panel: Widget, main: Widget) -> None:
        self.panel = panel
        self.main = main
        #: Whether the panel is currently showing.
        self.open = False
        #: Whether the operator has opened or closed it by hand this session.
        self.taken_over = False
        #: Whether the panel we are showing was summoned rather than offered.
        #: A summoned panel closes when a row is picked; one that was already
        #: there when the operator arrived is furniture and stays put.
        self.summoned = False
        self._width = 0

    # -- what the operator does ------------------------------------------
    def toggle(self) -> bool:
        """Ctrl+G. Returns the new open state."""
        self.taken_over = True
        self.open = not self.open
        self.summoned = self.open
        self._apply()
        return self.open

    def close_by_hand(self) -> bool:
        """Escape, or picking a row. Returns whether anything actually closed."""
        if not self.open:
            return False
        self.taken_over = True
        self.open = False
        self.summoned = False
        self._apply()
        return True

    def closes_on_pick(self) -> bool:
        """Whether picking a row should close the panel.

        Only a summoned panel. DESIGN.md's close-on-pick rule exists because a
        panel the operator just called up is covering the thing they wanted to
        see; a panel that opened itself on a wide screen is part of the layout
        and closing it would be taking away something they never asked for.
        """
        return self.summoned

    # -- what the terminal does ------------------------------------------
    def resized(self, total: int, *, allowed: bool) -> None:
        """A new pane width. `allowed` is `Config.slideouts_auto_open`."""
        self._width = total
        if not self.taken_over:
            self.open = allowed and auto_open(total)
            self.summoned = False
        self._apply()

    # ---------------------------------------------------------------------
    def _apply(self) -> None:
        if not self.open:
            self.panel.display = False
            self.main.display = True
            return
        layout = split(self._width)
        self.panel.display = True
        self.main.display = not layout.replaces_main
        # A zero width means we have not been told a real one yet (nothing
        # has laid this pane out). Leave the stylesheet's own width alone
        # rather than pinning the panel to nothing.
        if layout.panel > 0:
            self.panel.styles.width = layout.panel
