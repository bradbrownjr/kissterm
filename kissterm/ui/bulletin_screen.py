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


def count_detail(count: int, categories: list[str], newest: int, radio: bool) -> str:
    """What the how-many question says, the same words on the phone."""
    where = "over the air" if radio else "over the Internet"
    return (f"{count} new bulletins in {', '.join(categories)}, read one by one "
            f"{where}. The newest {newest} leaves the older ones; the next run "
            "starts after the newest read.")


class BulletinCountScreen(ModalScreen["int | None"]):
    """Mid-run, more new bulletins than `newest`: read all, the newest, or
    none (`core.questions.HowManyBulletins`). Answer: how many; None reads
    none. Choosing transmits nothing new: the run is already connected,
    and each read is a command to the BBS it is already in."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, bbs: str, count: int, categories: list[str], newest: int,
                 *, radio: bool = False) -> None:
        super().__init__()
        self._bbs, self._count, self._newest = bbs, count, newest
        self._categories, self._radio = categories, radio

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-box"):
            yield Label(f"{self._count} new bulletins on {self._bbs}", id="connect-title")
            yield Static(count_detail(self._count, self._categories, self._newest,
                                      self._radio), id="reminder-detail")
            with Horizontal(id="connect-buttons"):
                yield Button(f"Newest {self._newest}", variant="primary", id="count-newest")
                yield Button(f"All {self._count}", id="count-all")
                yield Button("None", id="connect-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#count-newest", Button).focus()

    @on(Button.Pressed, "#count-newest")
    def _newest_only(self) -> None:
        self.dismiss(self._newest)

    @on(Button.Pressed, "#count-all")
    def _all(self) -> None:
        self.dismiss(self._count)

    @on(Button.Pressed, "#connect-cancel")
    def _none(self) -> None:
        self.dismiss(None)
