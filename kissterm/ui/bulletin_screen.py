"""Which bulletin categories to collect (ROADMAP P2, bulletin collection).

Shown three ways, one screen: on the first collection from a BBS (every
category it lists), when a later check finds a category not offered
before (only the new ones), and from S on the Bulletins tab (every
category last seen, the current choice ticked). Each row shows the BBS's
own count, so 310 WX bulletins look like what they are before anything is
listed. "All" takes every category, new ones included, without asking
again (`mail/bulletins.py`).

Choosing transmits nothing: the run that asked is already connected, and
S works offline from the categories last seen.
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Footer, Label, SelectionList, Static

#: What the screen hands back: the categories ticked, and whether All was.
CategoryChoice = tuple[list[str], bool]


class BulletinCategoriesScreen(ModalScreen["CategoryChoice | None"]):
    """A checklist of categories with their counts; None if cancelled."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(
        self,
        bbs: str,
        categories: dict[str, int],
        *,
        ticked: list[str] = (),
        all_: bool = False,
        new_only: bool = False,
    ) -> None:
        super().__init__()
        self._bbs = bbs
        self._categories = dict(sorted(categories.items()))
        self._ticked = {c.upper() for c in ticked}
        self._all = all_
        self._new_only = new_only

    def compose(self) -> ComposeResult:
        if self._new_only:
            title = f"New bulletin categories on {self._bbs}"
            detail = ("Tick any to collect from now on. The rest are not offered "
                      "again; S on the Bulletins tab changes your choice later.")
        else:
            title = f"Bulletin categories on {self._bbs}"
            detail = ("Each ticked category is listed on every G, and its first "
                      "collection reads back as far as Settings > Mail > First "
                      "collection (days). The count is how many the BBS holds now.")
        with Vertical(id="connect-box"):
            yield Label(title, id="connect-title")
            yield Static(detail, id="reminder-detail")
            yield SelectionList[str](
                *((f"{name} ({count})", name, name in self._ticked)
                  for name, count in self._categories.items()),
                id="categories-list",
            )
            if not self._new_only:
                yield Checkbox("All, and new ones as they appear", self._all,
                               id="categories-all")
            with Horizontal(id="connect-buttons"):
                yield Button("Save", variant="primary", id="connect-go")
                yield Button("Cancel", id="connect-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#categories-list", SelectionList).focus()
        self._follow_all()

    @on(Checkbox.Changed, "#categories-all")
    def _follow_all(self) -> None:
        """All ticks every row and holds them: the list is what All means."""
        boxes = self.query("#categories-all")
        listing = self.query_one("#categories-list", SelectionList)
        if boxes and boxes.first(Checkbox).value:
            listing.select_all()
            listing.disabled = True
        else:
            listing.disabled = False

    @on(Button.Pressed, "#connect-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#connect-go")
    def _save(self) -> None:
        boxes = self.query("#categories-all")
        all_ = bool(boxes) and boxes.first(Checkbox).value
        picked = list(self.query_one("#categories-list", SelectionList).selected)
        self.dismiss((sorted(picked), all_))
