"""The Files tab's viewer: Enter on a file opens it full screen.

A zip lists its files, and Enter on one opens it in another viewer on top
(Esc goes back a level); Markdown is shown formatted; HTML is shown
formatted after `files_view.html_to_markdown`; any other text is shown as
text, and a binary file is named with its size and nothing more. The
reading rules -- in memory, size-capped, nothing run or fetched -- are
`kissterm/files_view.py`'s.

Full screen rather than in the reader column (operator, 2026-10-03): a
zip's list and a long page need the width. Clicking a file still shows
the plain preview in the reader; Enter is the deliberate "open".

Links are shown but never followed (`open_links=False`): a page from the
air does not get to open a browser.
"""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Label, Markdown, Static

from ..files_view import html_to_markdown, kind_of, text_of, zip_members, zip_read
from .wraplog import WrapLog

#: The most of a file on disk the viewer reads.
MAX_FILE = 16 * 1024 * 1024


def read_for_viewer(path: Path) -> bytes:
    """A file's bytes, at most `MAX_FILE`."""
    with open(path, "rb") as handle:
        return handle.read(MAX_FILE)


class FileViewerScreen(ModalScreen[None]):
    """One file, or one member of a zip, shown by its kind."""

    DEFAULT_CSS = """
    FileViewerScreen { align: center middle; }
    FileViewerScreen > #viewer-box {
        width: 100%; height: 100%; background: $surface; padding: 0 1;
    }
    FileViewerScreen #viewer-title { text-style: bold; color: $accent; height: 1; }
    FileViewerScreen #viewer-body { height: 1fr; }
    FileViewerScreen #viewer-members { height: 1fr; }
    """

    BINDINGS = [Binding("escape", "dismiss(None)", "Close")]

    def __init__(self, name: str, data: bytes) -> None:
        super().__init__()
        self._name = name
        self._data = data
        self.kind = kind_of(name, data)
        self._members: list[tuple[str, int]] = []
        self._problem = ""
        if self.kind == "zip":
            try:
                self._members = zip_members(data)
            except ValueError as exc:
                self._problem = str(exc)

    def compose(self) -> ComposeResult:
        with Vertical(id="viewer-box"):
            yield Label(Text(f"{text_of(self._name.encode())}  ({len(self._data):,} bytes)"),
                        id="viewer-title")
            if self.kind == "zip" and not self._problem:
                yield DataTable(id="viewer-members", cursor_type="row")
            elif self.kind in ("markdown", "html"):
                source = (text_of(self._data) if self.kind == "markdown"
                          else html_to_markdown(self._data))
                with VerticalScroll(id="viewer-body"):
                    yield Markdown(source, open_links=False, id="viewer-markdown")
            elif self.kind == "text":
                yield WrapLog(id="viewer-body", wrap=True)
            else:
                yield Static(self._problem or "Not a text file; the viewer does not open it.",
                             id="viewer-body")
        yield Footer()

    def on_mount(self) -> None:
        if self.kind == "zip" and not self._problem:
            table = self.query_one("#viewer-members", DataTable)
            table.add_columns("Name", "Size")
            for name, size in self._members:
                table.add_row(Text(text_of(name.encode())), f"{size:,}", key=name)
            table.focus()
        elif self.kind == "text":
            log = self.query_one("#viewer-body", WrapLog)
            log.write(Text(text_of(self._data)))
            log.focus()
        elif self.kind in ("markdown", "html"):
            self.query_one("#viewer-body").focus()

    @on(DataTable.RowSelected, "#viewer-members")
    def _open_member(self, event: DataTable.RowSelected) -> None:
        name = str(event.row_key.value)
        try:
            data = zip_read(self._data, name)
        except ValueError as exc:
            self.notify(str(exc), severity="warning")
            return
        self.app.push_screen(FileViewerScreen(f"{self._name} / {name}", data))

