"""The command registry: one table that the key bindings, the Footer, the F10
menu, the F1 help screen and the Ctrl+P palette are all generated from.

Why one table. Before this, each of those five read a different list: the
App's hand-written `BINDINGS`, a per-tab allowlist inside the Footer, a
category/priority table for the palette, and prose in README and DESIGN.md.
They drifted. The Footer advertised `^O` for a key bound to Ctrl+Shift+O (an
ordinary terminal delivers Ctrl+O, which was Transcripts); an action could be
shown on a tab where it only answered with "Open APRS to ...". Generating all
of them from `COMMANDS` means a key, a label or a context can only be wrong
in one place, and `tests/unit/test_key_standard.py` checks that one place.

The standard (docs/ROADMAP.md P0.2, DESIGN.md section 5) is IBM CUA as text
UIs adopted it -- Turbo Vision, Midnight Commander: F1 is Help, F10 is the
menu, **every command is in the menu**, and a key is only an accelerator. That
is what lets the key budget stay small enough to be terminal-safe: a command
with no key of its own (Send position, Object, Transcripts ...) is two or three
keystrokes away through F10 and its mnemonic letters, never unreachable.

Nothing here imports the App or touches a widget, so the registry, the Footer
fitting and the help text are plain pytest (`tests/unit/test_commands.py`),
the same reason `ax25/window.py` was pulled out of the state machine.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider

#: Tab ids in on-screen order. The ids never change when labels or keys do:
#: every `active == "aprs"` check addresses a pane by id.
TAB_ORDER = ("terminal", "aprs", "heard", "monitor", "settings")

TAB_TITLES = {
    "terminal": "Terminal",
    "aprs": "APRS",
    "heard": "Heard",
    "monitor": "Monitor",
    "settings": "Settings",
}

#: One plain paragraph per tab for the F1 screen: what the tab is for and the
#: first thing to do there. Keys are listed below it from the registry, so
#: these name a key only where the sentence needs it.
TAB_HELP = {
    "terminal": (
        "Talk to a node, a BBS or another station. Ctrl+N connects. Then type "
        "a command and press Enter to send it. While you type, the commands "
        "this node understands appear under the entry line with a short "
        "description: Up and Down choose one, Tab fills it in, and nothing is "
        "sent until you press Enter. Ctrl+R lists every command for the node "
        "you are on."
    ),
    "aprs": (
        "APRS messages, positions and objects. Put a callsign in To, type the "
        "message and press Enter. Each correspondent gets a tab. Ctrl+R picks "
        "a gateway service (SMS, email, weather) and fills in what to send. "
        "Position reports, objects, bulletins and the beacon are in the F10 "
        "menu under APRS."
    ),
    "heard": (
        "Every station heard on the channel, with when and how often. Nothing "
        "here transmits."
    ),
    "monitor": (
        "Every frame in both directions, as it went over the air. When a "
        "connect fails, look here: no reply at all is an RF problem, a DM "
        "reply means the far station refused."
    ),
    "settings": (
        "Your callsign, transports, beacons and appearance. Changes take "
        "effect when you press Save."
    ),
}

#: Menu bar order. Each command's `group` must be one of these.
MENU_GROUPS = ("Session", "APRS", "View", "Help")

#: Which menu opens first from each tab, so F10 then one letter reaches the
#: commands for the work in front of the operator.
MENU_GROUP_FOR_TAB = {"terminal": "Session", "aprs": "APRS"}


@dataclass(frozen=True)
class Command:
    #: A Textual action string, with arguments inline: "show_tab('aprs')".
    action: str
    #: Menu, help and palette text. Short: a verb or a noun, no sentence.
    label: str
    #: Menu heading, one of `MENU_GROUPS`; "" keeps it out of the menu (F10
    #: itself -- a menu entry that opens the menu is noise).
    group: str
    #: The letter that runs it while its menu is open. Unique per group.
    mnemonic: str
    #: One line for F1 and the palette: what it does, in plain words.
    help: str
    #: The bound key, as Textual names it; "" for a menu-only command.
    key: str = ""
    #: Tabs where it applies; empty means every tab. The key does nothing
    #: elsewhere (it falls through to the focused widget), and running it
    #: from the menu switches to the first of these tabs first.
    tabs: tuple[str, ...] = ()
    #: Tabs whose Footer shows it; ("*",) means everywhere it applies.
    footer: tuple[str, ...] = ()
    #: Footer text, where `label` is longer than the bar can afford.
    short: str = ""
    #: Bound with priority, so it wins over the focused widget's own use of
    #: the same key (Ctrl+D is the Input's delete-right; Delete does that).
    priority: bool = False

    @property
    def footer_label(self) -> str:
        return self.short or self.label

    def applies_on(self, tab: str) -> bool:
        return not self.tabs or tab in self.tabs

    def in_footer_on(self, tab: str) -> bool:
        return self.applies_on(tab) and ("*" in self.footer or tab in self.footer)


def _tab(tab: str, key: str, mnemonic: str) -> Command:
    title = TAB_TITLES[tab]
    return Command(
        f"show_tab('{tab}')", title, "View", mnemonic,
        f"Show the {title} tab", key=key,
    )


# Menu order is list order within a group. Keep each group's entries in the
# order an operator reaches for them, most common first.
COMMANDS: tuple[Command, ...] = (
    # --- Session: the connection and the transmitter -------------------
    Command("connect", "Connect", "Session", "C",
            "Connect to a station, node or BBS", key="ctrl+n",
            footer=("terminal",)),
    Command("disconnect", "Disconnect", "Session", "D",
            "End the session on the active Terminal tab", key="ctrl+d",
            tabs=("terminal",), footer=("terminal",), priority=True),
    Command("toggle_transmit", "Transmit on/off", "Session", "T",
            "The master transmit switch; nothing keys the radio while it is off",
            key="ctrl+t", footer=("*",), short="TX"),
    Command("beacon_now", "Send beacon", "Session", "B",
            "Send your beacon text once, now"),
    Command("file_transfer", "File transfer", "Session", "F",
            "Send or receive a file (YAPP or AutoBIN) on the connected session",
            tabs=("terminal",)),
    Command("show_transcripts", "Transcripts", "Session", "R",
            "Read saved session transcripts"),
    Command("set_callsign", "My callsign", "Session", "M",
            "Change the callsign this station uses"),
    Command("quit", "Quit", "Session", "Q", "Leave kissterm", key="ctrl+q",
            footer=("*",)),
    # --- APRS ----------------------------------------------------------
    Command("aprs_beacon_now", "Send position", "APRS", "P",
            "Transmit one position report now", tabs=("aprs",)),
    Command("toggle_aprs_beacon", "Position beacon on/off", "APRS", "B",
            "Start or stop the periodic position beacon", tabs=("aprs",)),
    Command("aprs_object", "Object", "APRS", "O",
            "Compose and send an object report", tabs=("aprs",)),
    Command("aprs_bulletin", "Bulletin", "APRS", "U",
            "Start a bulletin in the message box", tabs=("aprs",)),
    Command("command_reference", "Services", "APRS", "S",
            "Pick a gateway service (SMS, email, weather) and fill in the message",
            key="ctrl+r", tabs=("aprs",), footer=("aprs",)),
    Command("aprs_gateway_form", "Gateway form", "APRS", "G",
            "Fill in a form for a gateway service", tabs=("aprs",)),
    Command("toggle_contacts", "Contacts", "APRS", "C",
            "Show or hide the contacts list", key="ctrl+g", tabs=("aprs",),
            footer=("aprs",)),
    Command("aprs_is_watch", "Watch APRS-IS", "APRS", "W",
            "Watch APRS-IS for traffic to or from you (receive only)",
            tabs=("aprs",)),
    Command("toggle_aprs_ssid_filter", "SSID filter on/off", "APRS", "F",
            "Answer only messages to your exact callsign and SSID",
            tabs=("aprs",)),
    # --- View: tabs and what is shown ----------------------------------
    _tab("terminal", "f2", "T"),
    _tab("aprs", "f3", "A"),
    _tab("heard", "f4", "H"),
    _tab("monitor", "f5", "M"),
    _tab("settings", "f9", "S"),
    Command("toggle_contacts", "Address book", "View", "B",
            "Show or hide the Address Book", key="ctrl+g",
            tabs=("terminal",), footer=("terminal",), short="Book"),
    Command("toggle_known_nodes", "NET/ROM nodes", "View", "N",
            "Show or hide nodes heard in NET/ROM broadcasts",
            tabs=("terminal",)),
    Command("find_in_terminal", "Find", "View", "F",
            "Search the terminal scrollback", key="ctrl+f",
            tabs=("terminal",), footer=("terminal",)),
    Command("clear_log", "Clear", "View", "C",
            "Clear what this tab is showing", key="ctrl+l",
            tabs=("terminal", "aprs", "monitor"), footer=("aprs", "monitor")),
    # --- Help ----------------------------------------------------------
    Command("help", "Help", "Help", "H",
            "Help for this tab, with its keys", key="f1", footer=("*",)),
    Command("command_reference", "Node commands", "Help", "N",
            "Every command the node you are on understands", key="ctrl+r",
            tabs=("terminal",), footer=("terminal",), short="Commands"),
    Command("command_palette", "Search commands", "Help", "S",
            "Find any command by typing part of its name", key="ctrl+p"),
    # --- Not in the menu -----------------------------------------------
    Command("menu", "Menu", "", "", "Every command, grouped", key="f10",
            footer=("*",)),
)

#: The Footer's left-to-right order, which is also its keep-longest order as
#: the terminal narrows: `fit_footer` keeps a prefix. Menu is not listed; it
#: is pinned to the right edge and never dropped, because it is the way to
#: everything the bar had no room for.
FOOTER_ORDER = (
    "help",
    "toggle_transmit",
    "connect",
    "disconnect",
    "toggle_contacts",
    "command_reference",
    "find_in_terminal",
    "clear_log",
    "quit",
)

#: Keys that belong to Textual rather than to our `BINDINGS` (the palette is
#: bound by `App` itself). Listed so the registry can name them without the
#: App binding them twice.
TEXTUAL_BOUND_KEYS = frozenset({"ctrl+p"})

_KEY_NAMES = {
    "insert": "Ins",
    "delete": "Del",
    "escape": "Esc",
    "enter": "Enter",
    "pageup": "PgUp",
    "pagedown": "PgDn",
    "space": "Space",
}


def key_label(key: str, *, short: bool = True) -> str:
    """"ctrl+n" -> "^N" (Footer) or "Ctrl+N" (menu, help); "f10" -> "F10"."""
    if not key:
        return ""
    parts = key.split("+")
    base = parts[-1]
    name = _KEY_NAMES.get(base, base.upper() if len(base) <= 3 else base.capitalize())
    if parts[:-1] == ["ctrl"]:
        return f"^{name}" if short else f"Ctrl+{name}"
    mods = "+".join(p.capitalize() for p in parts[:-1])
    return f"{mods}+{name}" if mods else name


def action_base(action: str) -> str:
    """"show_tab('terminal')" -> "show_tab": Textual passes check_action the
    bare name and the arguments separately."""
    return action.split("(", 1)[0]


#: Built once at import: `check_action` runs for every binding on every
#: Footer render, and a linear scan of the registry there is work done
#: thousands of times a session for an answer that never changes.
_BY_ACTION: dict[str, tuple[Command, ...]] = {}
for _command in COMMANDS:
    for _key in {_command.action, action_base(_command.action)}:
        _BY_ACTION[_key] = _BY_ACTION.get(_key, ()) + (_command,)


def commands_for(action: str) -> list[Command]:
    """Every registry entry for an action. One action may have two entries
    that differ by tab -- Ctrl+R is Node commands on Terminal and Services
    on APRS -- so the label always says what it does where it is pressed."""
    return list(_BY_ACTION.get(action, ()))


def applies_on(action: str, tab: str) -> bool:
    """Whether an action's key does anything on this tab. Unknown actions
    (Textual's own, a widget's) are always allowed."""
    entries = _BY_ACTION.get(action, ())
    return not entries or any(c.applies_on(tab) for c in entries)


def command_for(action: str, tab: str) -> Command | None:
    for c in COMMANDS:
        if c.action == action and c.applies_on(tab):
            return c
    return None


def menu_groups() -> list[tuple[str, list[Command]]]:
    return [(g, [c for c in COMMANDS if c.group == g]) for g in MENU_GROUPS]


def app_bindings() -> list[Binding]:
    """The App's `BINDINGS`, generated. One binding per (key, action) -- the
    two Ctrl+R entries share one. `show=False` throughout: the Footer is
    drawn from the registry, not from `Binding.show`."""
    seen: set[tuple[str, str]] = set()
    bindings = []
    for c in COMMANDS:
        if not c.key or c.key in TEXTUAL_BOUND_KEYS or (c.key, c.action) in seen:
            continue
        seen.add((c.key, c.action))
        bindings.append(
            Binding(c.key, c.action, c.footer_label, show=False, priority=c.priority)
        )
    return bindings


def footer_commands(tab: str) -> list[Command]:
    """What the Footer shows on this tab, in `FOOTER_ORDER`, before state
    (connected or not) and width are taken into account."""
    chosen = []
    for action in FOOTER_ORDER:
        for c in COMMANDS:
            if action_base(c.action) == action and c.in_footer_on(tab):
                chosen.append(c)
                break
    return chosen


def chip_width(key_display: str, label: str) -> int:
    """Columns one Footer chip takes: `FooterKey`'s own CSS pads the key
    one column each side and the label one column on the right. Checked
    against a real render; recheck it if Textual's `FooterKey` CSS changes."""
    return len(key_display) + len(label) + 3


def fit_footer(
    items: list[tuple[str, str]], budget: int
) -> list[tuple[str, str]]:
    """The longest prefix of `(key_display, label)` chips that fits `budget`
    columns. A prefix, not a best fit: the order is the priority, and a
    narrower terminal should lose the last keys, never a middle one."""
    fitted = []
    used = 0
    for key_display, label in items:
        width = chip_width(key_display, label)
        if used + width > budget:
            break
        used += width
        fitted.append((key_display, label))
    return fitted


def help_renderable(
    tab: str,
    list_keys: list[tuple[str, str, str]],
    *,
    unavailable: dict[str, str] | None = None,
):
    """The F1 screen for one tab: what it is for, then its keys.

    `list_keys` is `(where, key, label)` for keys that work only while a list
    or tab strip has focus -- read from those widgets' own `BINDINGS` by the
    caller, so this cannot drift from them either.

    Prose and key table are separate renderables rather than rows of one
    grid: a paragraph in a grid column makes that column as wide as the
    paragraph and squeezes the descriptions beside it down to nothing.
    """
    unavailable = unavailable or {}
    title = TAB_TITLES.get(tab, tab)

    def table(rows: list[tuple[str, str]]) -> Table:
        grid = Table.grid(padding=(0, 2))
        grid.add_column(no_wrap=True, justify="right")
        grid.add_column(overflow="fold")
        for key, text in rows:
            grid.add_row(Text(key, style="bold"), Text(text))
        return grid

    blocks: list = [
        Text(title, style="bold"),
        Text(TAB_HELP.get(tab, ""), overflow="fold"),
        Text(""),
        Text("Keys", style="bold"),
    ]
    rows = []
    for c in COMMANDS:
        if not c.key or not c.applies_on(tab) or c.action.startswith("show_tab"):
            continue
        note = f"  ({unavailable[c.action]})" if c.action in unavailable else ""
        rows.append((key_label(c.key, short=False), f"{c.label}: {c.help}{note}"))
    tab_keys = ", ".join(
        f"{key_label(c.key)} {c.label}" for c in COMMANDS if c.action.startswith("show_tab")
    )
    rows.append(("F2-F9", f"Tabs: {tab_keys}"))
    blocks.append(table(rows))
    if list_keys:
        blocks += [Text(""), Text("In lists", style="bold")]
        blocks.append(table([
            (key_label(key, short=False), f"{label} ({where})")
            for where, key, label in list_keys
        ]))
    blocks += [Text(""), Text("More", style="bold")]
    blocks.append(table([
        ("F10", "Everything else is in the menu: open it, then press the "
                "highlighted letter."),
        ("Ctrl+P", "Find a command by name."),
        ("Tab bar", "Left and Right also change tabs, and every key in the "
                    "bottom bar can be clicked."),
        ("F1, F10", "If these open your terminal program's own help or menu, "
                    "turn that shortcut off in its preferences (GNOME "
                    "Terminal: 'Enable the menu accelerator key')."),
    ]))
    return Group(*blocks)


class KeyBindingsProvider(Provider):
    """Every registry command, fuzzy-searchable from Ctrl+P, including the
    ones with no key. Running one goes through `KissTermApp.run_command`,
    the same path as the F10 menu, so it switches to the command's tab first.
    """

    async def discover(self) -> Hits:
        for command in self._commands():
            yield DiscoveryHit(self._name(command), self._run(command), help=command.help)

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for command in self._commands():
            name = self._name(command)
            score = matcher.match(f"{name} {command.help}")
            if score > 0:
                yield Hit(score, matcher.highlight(name), self._run(command), help=command.help)

    @staticmethod
    def _commands() -> list[Command]:
        return [c for c in COMMANDS if c.group and c.action != "command_palette"]

    @staticmethod
    def _name(command: Command) -> str:
        key = f" ({key_label(command.key, short=False)})" if command.key else ""
        return f"{command.group}: {command.label}{key}"

    def _run(self, command: Command):
        # A default argument, not a closure over the loop variable -- or
        # every hit would run whichever command came last.
        app = self.app
        return lambda command=command: app.run_command(command)
