"""The Help tab (F1): keys, node commands, guides, glossary, and About.

Help used to be a modal screen over whatever tab was open, which kept it
context-sensitive but left F1 as the one function key missing from the tab
row -- an operator reading "F2 Terminal ... F9 Settings" looked for F1 there
and concluded it did not exist. It is a full-page tab now, first in the row,
and it has room for what a modal could not hold: the shipped node command
references, the built-in guides and the glossary, browsable without being
connected to anything, and an About page to quote in a bug report.

**Context survives the move.** F1 records the tab it was pressed from and
opens the Keys section on that tab's keys (`KissTermApp.action_help`), so
"what can I press here?" is still one key away. F1 again returns to that
tab: Help is somewhere you visit, and the way back should be the way in.

**Nothing here transmits, and nothing here fills the send line.** Browsing
a node's command list on this tab is reading. The one route from a
reference to the terminal stays Ctrl+R on the Terminal tab
(`CommandReferenceScreen`), which fills the send line and still does not
send -- see AGENTS.md, "Suggestions and completions fill the input; they
never send". A second, quieter route from here would be one more place to
audit for that rule, for no gain.

**Prose wraps.** Command descriptions and glossary definitions are rendered
as Rich tables into a `WrapLog`, not a `DataTable`, because a `DataTable`
keeps every cell on one line and a definition cut off at the right edge is
not a definition. The same call `CommandReferenceScreen` made for its
glossary view.
"""

from __future__ import annotations

import platform
from importlib import metadata

from rich.table import Column, Table
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Markdown, OptionList, Select, Static, TabbedContent, TabPane
from textual.widgets.option_list import Option

from . import commands as cmdreg
from .wraplog import WrapLog

#: Section ids, in strip order. Keys first: it is where F1 lands.
SECTIONS = ("help-keys", "help-nodes", "help-guides", "help-glossary", "help-about")

def _wraplog(id: str) -> WrapLog:
    return WrapLog(id=id, wrap=True, markup=False, highlight=False, auto_scroll=False)


def _prose_table(*columns: Column) -> Table:
    return Table(*columns, expand=True, header_style="bold", show_edge=False, pad_edge=False)


class HelpPane(Vertical):
    """The body of the Help tab. See the module docstring."""

    def compose(self) -> ComposeResult:
        from .. import guides
        from ..nodes.reference import load_all

        with TabbedContent(id="help-tabs", initial="help-keys"):
            with TabPane("Keys", id="help-keys"):
                with Horizontal(classes="help-toolbar"):
                    yield Static("Keys for", classes="help-toolbar-label")
                    yield Select(
                        [(cmdreg.TAB_TITLES[t], t) for t in cmdreg.TAB_ORDER],
                        value=cmdreg.TAB_ORDER[0],
                        allow_blank=False,
                        id="help-keys-for",
                    )
                with VerticalScroll(id="help-keys-scroll"):
                    yield Static(id="help-keys-body")
            with TabPane("Node commands", id="help-nodes"):
                families = load_all()
                with Horizontal(classes="help-toolbar"):
                    yield Static("Node type", classes="help-toolbar-label")
                    yield Select(
                        [(f.name, f.id) for f in families] or [("none shipped", "")],
                        value=families[0].id if families else "",
                        allow_blank=False,
                        id="help-node-family",
                    )
                    yield Input(placeholder="search commands", id="help-node-search")
                yield Static(id="help-node-note")
                yield _wraplog("help-node-table")
            with TabPane("Guides", id="help-guides"):
                with Horizontal():
                    yield OptionList(
                        *(Option(g.title, id=str(i)) for i, g in enumerate(guides.GUIDES)),
                        id="help-guide-list",
                    )
                    with VerticalScroll(id="help-guide-scroll"):
                        yield Markdown(id="help-guide-body")
            with TabPane("Glossary", id="help-glossary"):
                yield Input(placeholder="search glossary", id="help-glossary-search")
                yield _wraplog("help-glossary-body")
            with TabPane("About", id="help-about"):
                with VerticalScroll(id="help-about-scroll"):
                    yield Static(id="help-about-body")

    def on_mount(self) -> None:
        self.show_keys(cmdreg.TAB_ORDER[0])
        self._render_nodes()
        self._render_glossary("")
        self.query_one("#help-about-body", Static).update(self.about_renderable())
        guide_list = self.query_one("#help-guide-list", OptionList)
        if guide_list.option_count:
            guide_list.highlighted = 0
            self._show_guide(0)

    # -- Keys -----------------------------------------------------------
    def show_keys(self, tab: str) -> None:
        """Show `tab`'s keys and select it in the picker. Called by F1 with
        the tab it was pressed from, and by the picker itself."""
        if tab not in cmdreg.TAB_ORDER:
            tab = cmdreg.TAB_ORDER[0]
        picker = self.query_one("#help-keys-for", Select)
        if picker.value != tab:
            with picker.prevent(Select.Changed):
                picker.value = tab
        self.query_one("#help-keys-body", Static).update(
            self.app.help_renderable(tab)  # type: ignore[attr-defined]
        )

    @on(Select.Changed, "#help-keys-for")
    def _keys_for_changed(self, event: Select.Changed) -> None:
        if isinstance(event.value, str):
            self.show_keys(event.value)

    # -- Node commands --------------------------------------------------
    def select_family(self, family_id: str) -> None:
        """Preselect the node type the operator is connected to, if known."""
        from ..nodes.reference import available_families

        # Setting a value outside the options raises (AGENTS.md, the Select
        # traps), so check against the shipped list first.
        if family_id in available_families():
            self.query_one("#help-node-family", Select).value = family_id

    @on(Select.Changed, "#help-node-family")
    @on(Input.Changed, "#help-node-search")
    def _nodes_changed(self) -> None:
        self._render_nodes()

    def _render_nodes(self) -> None:
        from ..nodes.reference import CommandReference, load_family, source_tier

        family_id = self.query_one("#help-node-family", Select).value
        family = load_family(family_id) if isinstance(family_id, str) else None
        needle = self.query_one("#help-node-search", Input).value
        note = self.query_one("#help-node-note", Static)
        log = self.query_one("#help-node-table", WrapLog)
        log.clear()
        if family is None:
            note.update("No command references are installed.")
            return
        parts = [family.note.replace("\n", " ").strip()]
        if family.confidence == "recalled":
            parts.append("This reference is unverified; check a command before spending airtime on it.")
        parts.append("On the Terminal tab, Ctrl+R puts a command in the send line.")
        note.update(" ".join(p for p in parts if p))
        table = _prose_table(
            Column("Command", style="bold", no_wrap=True),
            Column("Usage", no_wrap=True),
            Column("What it does", ratio=1, overflow="fold"),
            Column("Source", no_wrap=True),
        )
        for command in CommandReference(family).find(needle):
            names = " / ".join(command.names)
            what = command.summary
            if command.detail:
                # Summaries are written as fragments, without a full stop.
                if what and what[-1] not in ".!?":
                    what += "."
                what = f"{what} {command.detail}".strip()
            table.add_row(names, command.usage or command.name, what, source_tier(command))
        self._write_from_top(log, table)

    # -- Guides ---------------------------------------------------------
    @on(OptionList.OptionHighlighted, "#help-guide-list")
    def _guide_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id is not None:
            self._show_guide(int(event.option.id))

    def _show_guide(self, index: int) -> None:
        from .. import guides

        guide = guides.GUIDES[index]
        body = f"# {guide.title}\n\n*{guide.summary}*\n\n{guides.render(guide)}"
        self.query_one("#help-guide-body", Markdown).update(body)
        self.query_one("#help-guide-scroll", VerticalScroll).scroll_home(animate=False)

    # -- Glossary -------------------------------------------------------
    @on(Input.Changed, "#help-glossary-search")
    def _glossary_search(self, event: Input.Changed) -> None:
        self._render_glossary(event.value)

    def _render_glossary(self, needle: str) -> None:
        from .. import glossary

        log = self.query_one("#help-glossary-body", WrapLog)
        log.clear()
        table = _prose_table(
            Column("Term", style="bold", no_wrap=True),
            Column("Definition", ratio=1, overflow="fold"),
        )
        for term in glossary.search(needle):
            table.add_row(term.name, term.definition)
        self._write_from_top(log, table)

    @staticmethod
    def _write_from_top(log: WrapLog, table: Table) -> None:
        """Replace `log`'s content and show it from the first row. A reference
        opened at its last row reads as if the top were missing."""
        log.write(table, expand=True, scroll_end=False)
        log.call_after_refresh(log.scroll_home, animate=False)

    # -- About ----------------------------------------------------------
    def about_renderable(self) -> Table:
        """Version, project links and where this station keeps its files --
        what a bug report needs, readable without a shell."""
        from .. import __version__
        from ..config import config_path

        app = self.app
        config = getattr(app, "config", None)
        profile = getattr(config, "profile_name", None)
        try:
            config_file = str(config_path(profile) if profile else config_path())
        except Exception:  # noqa: BLE001 -- About must render whatever breaks
            config_file = "(unknown)"
        try:
            logs = str(app._transcript_directory())  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            logs = "(unknown)"
        try:
            textual_version = metadata.version("textual")
        except metadata.PackageNotFoundError:
            textual_version = "(unknown)"
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="bold", no_wrap=True)
        grid.add_column(overflow="fold")
        for key, value in (
            ("kissterm", __version__),
            ("", "A terminal for KISS TNCs, packet nodes and HF modems."),
            ("License", "MIT"),
            ("Project", "https://github.com/bradbrownjr/kissterm"),
            ("Report a bug", "https://github.com/bradbrownjr/kissterm/issues"),
            ("", ""),
            ("Config file", config_file),
            ("Logs, transcripts", logs),
            ("", ""),
            ("Python", platform.python_version()),
            ("Textual", textual_version),
            ("System", f"{platform.system()} {platform.release()}"),
            ("", ""),
            ("Diagnostics", "Run 'kissterm --doctor' in a shell and paste its output "
                            "into a bug report."),
        ):
            grid.add_row(key, value)
        return grid
