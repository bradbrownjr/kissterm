"""Per-action metadata shared by the two halves of the same fix.

`docs/ROADMAP.md` used to carry "Footer overflow and a real, searchable Keys
reference" as one open item because they are one problem seen from two
places: at an ordinary terminal width the Footer's key list needs more
columns than it has (`KissTermFooter` in `app.py`), and until now nothing
told the command palette (`Ctrl+P`) that `kissterm/ui/app.py`'s own
`BINDINGS` even existed, so typing in its search box filtered Textual's tiny
built-in system-command list and nothing else -- not Ctrl+B/Ctrl+D's hidden
legacy fallbacks, not Ctrl+K, not anything the Footer had no room for.

`ACTION_META` is the one table both fixes read: a category for the palette
entry, and a priority for which bindings the Footer keeps as the terminal
narrows. An action missing from it is a bug that must fail loudly at test
time (`tests/pilot/test_app_mounts.py::test_every_visible_binding_action_has_
footer_and_palette_metadata`), not silently drop out of one of the two lists
-- the same discipline `AGENTS.md` already asks of `Config`/`SETTINGS_SCHEMA`.

Both `iter_binding_entries` and `fit_footer_bindings` below take plain lists
of `Binding`/tuples rather than a live `App` or `Screen`, on purpose: it is
what lets `tests/unit/test_commands.py` exercise the grouping and width-
fitting logic as ordinary, fast pytest functions, no event loop and no
isolated config directory required, the same reasoning `ax25/window.py` and
`ax25/timers.py` were pulled out of the state machine for.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider


@dataclass(frozen=True)
class ActionMeta:
    #: Command-palette grouping, shown as the hit's help text.
    category: str
    #: Lower sorts first, and is kept longer as the Footer narrows -- see
    #: `fit_footer_bindings`. Only meaningful relative to other entries; the
    #: numbers themselves are not a version or an ordinal to preserve.
    footer_priority: int


#: Ranked, not just listed: TX/Connect/Disconnect/Contacts are the cluster an
#: operator reaches for mid-contact and are what an 80-column Footer keeps;
#: Quit is reachable at any width and, once it exists, from Ctrl+P too, so it
#: is the first thing dropped. "show_tab" covers F1-F5 -- always `show=False`
#: today (rule 16 in `kissterm/ui/AGENTS.md`: the tab bar already prints the
#: key), so its footer_priority is never actually consulted, but the palette
#: still wants a category for it so "F1 Terminal" is Ctrl+P-searchable too.
ACTION_META: dict[str, ActionMeta] = {
    "toggle_transmit": ActionMeta("Transmit", 0),
    "connect": ActionMeta("Connection", 1),
    "disconnect": ActionMeta("Connection", 2),
    "toggle_contacts": ActionMeta("Contacts", 3),
    "command_reference": ActionMeta("Connection", 4),
    "beacon_now": ActionMeta("Transmit", 5),
    "aprs_beacon_now": ActionMeta("Transmit", 6),
    "aprs_object": ActionMeta("APRS", 6),
    "aprs_gateway_form": ActionMeta("APRS", 6),
    "aprs_bulletin": ActionMeta("APRS", 6),
    "aprs_is_watch": ActionMeta("APRS", 7),
    "set_callsign": ActionMeta("Connection", 7),
    "find_in_terminal": ActionMeta("Terminal", 8),
    "clear_log": ActionMeta("Terminal", 9),
    "show_transcripts": ActionMeta("Terminal", 10),
    "file_transfer": ActionMeta("Terminal", 14),
    "toggle_aprs_ssid_filter": ActionMeta("APRS", 11),
    "quit": ActionMeta("App", 12),
    "show_tab": ActionMeta("Panes", 13),
}

#: Used only as a runtime safety net (a crash rendering the Footer would take
#: the whole app down with it) -- the real enforcement is the completeness
#: test named above. Sorts and displays last either way.
_FALLBACK_META = ActionMeta("Other", 1_000)


def _action_base(action: str) -> str:
    """"show_tab('terminal')" and "show_tab" resolve to the same entry --
    Textual action strings carry their call arguments inline."""
    return action.split("(", 1)[0]


def _action_meta(action: str) -> ActionMeta:
    return ACTION_META.get(_action_base(action), _FALLBACK_META)


def _format_key(key: str) -> str:
    """"ctrl+shift+b" -> "Ctrl+Shift+B". Used in the command palette, which
    has room for the full word, unlike the Footer's "^B"-style abbreviation
    (`App.get_key_display`, used for that instead)."""
    return "+".join(part.capitalize() for part in key.split("+"))


@dataclass(frozen=True)
class BindingEntry:
    """One palette-searchable action, aggregated across every key bound to
    it -- a visible binding and its hidden legacy-terminal fallback (Beacon's
    Ctrl+Shift+B/Ctrl+B, Disconnect's Ctrl+Shift+D/Ctrl+D), or a tab's F-key
    and its Ctrl+n alias, are ONE entry, not two, so searching "disconnect"
    does not return a duplicate hit that differs only by which key is shown.
    """

    action: str
    description: str
    category: str
    keys: tuple[str, ...]

    @property
    def name(self) -> str:
        return f"{self.description} ({' / '.join(self.keys)})"


def iter_binding_entries(bindings: list[Binding]) -> list[BindingEntry]:
    """Collapse a raw `BINDINGS` list into one entry per action, in
    `ACTION_META` category/priority order.

    `bindings` is meant to be `KissTermApp.BINDINGS` itself -- the app's own
    list, not `Screen.active_bindings` (which also merges in whatever the
    currently-focused widget binds, and none of those need a palette entry;
    see `KissTermFooter` below for the one place that distinction matters).
    """
    order: list[str] = []
    grouped: dict[str, list[Binding]] = {}
    for binding in bindings:
        if binding.action not in grouped:
            order.append(binding.action)
        grouped.setdefault(binding.action, []).append(binding)

    entries = []
    for action in order:
        group = grouped[action]
        primary = next((b for b in group if b.show), group[0])
        meta = _action_meta(action)
        keys = tuple(dict.fromkeys(_format_key(b.key) for b in group))
        entries.append(
            BindingEntry(
                action=action,
                description=primary.description or _action_base(action),
                category=meta.category,
                keys=keys,
            )
        )
    entries.sort(key=lambda entry: (entry.category, _action_meta(entry.action).footer_priority))
    return entries


def fit_footer_bindings(
    items: list[tuple[str, str, str]],
    budget: int,
) -> list[tuple[str, str, str]]:
    """Return the highest-priority prefix of `items` -- `(action,
    key_display, description)` triples -- whose Footer chips fit in `budget`
    columns.

    Kept free of any Textual widget or App reference so the "does an 80-
    column terminal keep the essential five and drop the rest" behaviour is
    a plain, synchronous pytest (`tests/unit/test_commands.py`) rather than a
    pilot test that needs a real render.

    The width formula (`len(key_display) + len(description) + 3`) mirrors
    `FooterKey`'s own `DEFAULT_CSS`: 1 column of padding each side of the key
    chip, 1 column to the right of the description chip, none of the rest.
    Checked against a real render (`footer.children[i].size.width` at a wide
    terminal, once with the stock `Footer` and once with `KissTermFooter`) --
    recheck it the same way if `FooterKey`'s CSS ever changes upstream.
    """
    ordered = sorted(items, key=lambda item: _action_meta(item[0]).footer_priority)
    fitted: list[tuple[str, str, str]] = []
    used = 0
    for action, key_display, description in ordered:
        width = len(key_display) + len(description) + 3
        if used + width > budget:
            break
        used += width
        fitted.append((action, key_display, description))
    return fitted


class KeyBindingsProvider(Provider):
    """Every action in `KissTermApp.BINDINGS`, fuzzy-searchable from Ctrl+P.

    Deliberately scoped to the App's own bindings, not
    `Screen.active_bindings` -- a focused `Input`/`DataTable`'s own built-in
    bindings (cursor movement, cut/copy/paste, Insert/F2/Delete on the
    address-book and APRS-contacts tables) are either already documented on
    screen (the address-book pane's own hint text) or meaningless to invoke
    from the palette without the right widget focused first. Global,
    always-available actions are what a searchable *reference* is for.
    """

    async def discover(self) -> Hits:
        for entry in self._entries():
            yield DiscoveryHit(entry.name, self._command(entry), help=entry.category)

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for entry in self._entries():
            score = matcher.match(entry.name)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(entry.name),
                    self._command(entry),
                    help=entry.category,
                )

    def _entries(self) -> list[BindingEntry]:
        return iter_binding_entries(type(self.app).BINDINGS)

    def _command(self, entry: BindingEntry):
        # A default argument, not a closure over `entry` from the enclosing
        # loop -- otherwise every hit's command would run whichever entry
        # happened to be last by the time the palette actually calls it.
        app = self.app
        return lambda action=entry.action: app.run_action(action)
