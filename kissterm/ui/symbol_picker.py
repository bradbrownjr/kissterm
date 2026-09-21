"""One filterable APRS-symbol picker shared by Settings and composition.

The APRS symbol table is sourced UI data, not a free-text wire field.  Keeping
the filtering behaviour in one widget prevents a composer from accepting a
table/code pair the established Settings picker would not offer.
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Select

from ..aprs import symbols


class SymbolPicker(Vertical):
    """Filterable selection over the established APRS symbol table."""

    def __init__(
        self, *, picker_id: str, select_id: str | None = None, ascii_safe: bool, value: str = "/>"
    ) -> None:
        super().__init__(id=picker_id, classes="settings-filtered-choice")
        self._ascii_safe = ascii_safe
        self._value = value
        self._select_id = select_id or f"{picker_id}-select"

    @property
    def select_id(self) -> str:
        return self._select_id

    @property
    def _filter_id(self) -> str:
        """Keep the filter paired with its Select, including Settings' IDs."""
        return f"{self._select_id}-filter"

    def compose(self) -> ComposeResult:
        yield Input(id=self._filter_id, placeholder="Filter by name...", classes="settings-filtered-choice-filter")
        yield Select(
            [(s.display_label(ascii_safe=self._ascii_safe), s.key) for s in symbols.SYMBOLS],
            id=self.select_id,
            allow_blank=False,
            value=self._value if self._value in {s.key for s in symbols.SYMBOLS} else symbols.SYMBOLS[0].key,
        )

    @property
    def value(self) -> str:
        value = self.query_one(f"#{self.select_id}", Select).value
        return value if isinstance(value, str) else ""

    def set_value(self, value: str) -> None:
        select = self.query_one(f"#{self.select_id}", Select)
        select.value = value if value in {s.key for s in symbols.SYMBOLS} else symbols.SYMBOLS[0].key

    @on(Input.Changed)
    def _filter(self, event: Input.Changed) -> None:
        if event.input.id != self._filter_id:
            return
        select = self.query_one(f"#{self.select_id}", Select)
        current = select.value if isinstance(select.value, str) else ""
        matches = list(symbols.filter_symbols(event.value))
        if current and current not in {s.key for s in matches}:
            pinned = symbols.lookup(current[0], current[1:]) if len(current) == 2 else None
            if pinned is not None:
                matches.insert(0, pinned)
        if not matches:
            matches = list(symbols.SYMBOLS)
        select.set_options([(s.display_label(ascii_safe=self._ascii_safe), s.key) for s in matches])
        if current in {s.key for s in matches}:
            select.value = current
