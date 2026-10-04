"""Which of the Home BBS's files to download (G on the Files tab, ROADMAP
P2 Files).

Asked mid-run, after `FILES` has listed them (`collect.BbsCollector`'s
files run). Each row shows the size and about how long it takes on the
air, and the total of what is ticked updates as rows are ticked, so the
cost is seen before anything is asked for (AGENTS.md, "Airtime is the
scarce resource"). Nothing is ticked at first: every download is the
operator's choice. A file already in Files > Downloads at the same size
says so; ticking it again saves a second copy (`yapp._destination`).
Names are shown as listed: `bbs_files.parse_files` offers only names of
letters, digits, `.`, `_` and `-`.

Cancel (or Download with nothing ticked) asks for nothing; the run then
disconnects.
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, SelectionList, Static

from ..mail.bbs_files import BbsFile, describe_airtime


class BbsFilesScreen(ModalScreen["list[str] | None"]):
    """A checklist of the BBS's files; the names ticked, or None."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, bbs: str, files: list[BbsFile], *, have: dict[str, int] | None = None,
                 baud: int = 1200) -> None:
        super().__init__()
        self._bbs = bbs
        self._files = files
        self._sizes = {f.name: f.size for f in files}
        self._have = have or {}
        self._baud = baud

    def _row(self, file: BbsFile) -> str:
        row = f"{file.name}  {file.size:,} bytes, {describe_airtime(file.size, self._baud)}"
        if self._have.get(file.name) == file.size:
            row += " (already in Downloads)"
        return row

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-box"):
            yield Label(f"Files on {self._bbs}", id="connect-title")
            yield Static("Tick the files to download into Files > Downloads. Each is sent "
                         f"by YAPP; times are estimates at {self._baud} baud.",
                         id="reminder-detail")
            yield SelectionList[str](
                *((self._row(f), f.name, False) for f in self._files), id="bbs-files-list")
            yield Static("", id="bbs-files-total")
            with Horizontal(id="connect-buttons"):
                yield Button("Download", variant="primary", id="connect-go")
                yield Button("Cancel", id="connect-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#bbs-files-list", SelectionList).focus()
        self._total()

    @on(SelectionList.SelectedChanged, "#bbs-files-list")
    def _total(self) -> None:
        picked = self.query_one("#bbs-files-list", SelectionList).selected
        size = sum(self._sizes[name] for name in picked)
        self.query_one("#bbs-files-total", Static).update(
            f"{len(picked)} ticked, {size:,} bytes, {describe_airtime(size, self._baud)}"
            if picked else "Nothing ticked.")

    @on(Button.Pressed, "#connect-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#connect-go")
    def _download(self) -> None:
        picked = set(self.query_one("#bbs-files-list", SelectionList).selected)
        self.dismiss([f.name for f in self._files if f.name in picked])
