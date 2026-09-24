"""The command registry's pure logic: the Footer fit, the menu grouping and
the help text.

No Textual event loop and no isolated config directory needed -- everything
here is a plain function over `kissterm.ui.commands.COMMANDS`, which is why
that module holds no App or widget reference. See its docstring.
"""

from __future__ import annotations

from kissterm.ui import commands as cmd


def test_every_command_is_in_a_menu_group_or_deliberately_not():
    for command in cmd.COMMANDS:
        assert command.group in cmd.MENU_GROUPS or command.group == "", command.label
        if command.group:
            assert command.mnemonic, f"{command.label} has no menu mnemonic"


def test_mnemonics_are_unique_within_a_group():
    """Two entries on the same letter means one of them is unreachable from
    the keyboard once its menu is open."""
    for group, entries in cmd.menu_groups():
        letters = [c.mnemonic for c in entries]
        assert len(letters) == len(set(letters)), f"{group}: {letters}"


def test_every_mnemonic_is_a_letter_of_its_own_label():
    """The menu underlines the mnemonic in the label; a letter that is not
    in the label has nothing to underline and nothing to learn from."""
    for command in cmd.COMMANDS:
        if command.mnemonic:
            assert command.mnemonic in command.label.upper(), command.label


def test_key_labels_are_the_short_form_the_footer_uses():
    assert cmd.key_label("ctrl+n") == "^N"
    assert cmd.key_label("ctrl+n", short=False) == "Ctrl+N"
    assert cmd.key_label("f10") == "F10"
    assert cmd.key_label("insert") == "Ins"
    assert cmd.key_label("e") == "E"
    assert cmd.key_label("") == ""


def test_a_key_does_nothing_on_a_tab_it_does_not_apply_to():
    # Find is a Terminal action; Ctrl+F on APRS falls through rather than
    # switching tabs out from under the operator.
    assert cmd.applies_on("find_in_terminal", "terminal")
    assert not cmd.applies_on("find_in_terminal", "aprs")
    # Transmit applies everywhere, and so does anything not in the registry
    # (a widget's own binding, or one of Textual's).
    assert cmd.applies_on("toggle_transmit", "settings")
    assert cmd.applies_on("focus_next", "heard")


def test_one_action_can_carry_a_different_label_per_tab():
    """The command reference asks the same question on both tabs -- "what
    can I say to the thing I am talking to?" -- and the label has to say
    which answer."""
    assert cmd.command_for("command_reference", "terminal").label == "Node commands"
    assert cmd.command_for("command_reference", "aprs").label == "Services"
    assert cmd.command_for("command_reference", "heard") is None


def test_the_footer_shows_only_what_applies_to_the_tab():
    terminal = [c.action for c in cmd.footer_commands("terminal")]
    assert "connect" in terminal
    assert "find_in_terminal" in terminal
    aprs = [c.action for c in cmd.footer_commands("aprs")]
    assert "connect" not in aprs
    assert "clear_log" in aprs
    for tab in cmd.TAB_ORDER:
        actions = [c.action for c in cmd.footer_commands(tab)]
        # Transmit leads: it is the one switch every tab needs in view. Help
        # is not here at all -- it is a tab, printed in the tab row.
        assert actions[0] == "toggle_transmit", tab
        assert "help" not in actions, tab
        assert len(set(actions)) == len(actions), f"{tab} repeats a key: {actions}"


def test_the_footer_keeps_a_prefix_that_fits_and_drops_the_rest():
    items = [("F1", "Help"), ("^T", "TX"), ("^N", "Connect")]
    assert cmd.fit_footer(items, budget=100) == items
    # Help is 2+4+3 = 9 columns, TX is 7, Connect is 12.
    assert cmd.fit_footer(items, budget=16) == items[:2]
    assert cmd.fit_footer(items, budget=15) == items[:1]
    assert cmd.fit_footer(items, budget=0) == []


def test_fitting_is_a_prefix_not_a_best_fit():
    """A later, smaller chip must not jump the queue: the order is the
    priority, so a narrow terminal loses the last keys, never a middle one."""
    items = [("^T", "TX"), ("^N", "X" * 90), ("^Q", "Quit")]
    assert cmd.fit_footer(items, budget=20) == items[:1]


def test_help_names_the_tab_and_its_keys():
    from rich.console import Console

    console = Console(width=100, record=True)
    console.print(cmd.help_renderable("terminal", [("Address Book", "insert", "New")]))
    body = console.export_text()
    assert "Terminal" in body
    assert "Ctrl+N" in body and "Connect" in body
    assert "Ins" in body and "Address Book" in body
    assert "highlighted letter" in body
    # An APRS-only command has no business in Terminal's key list.
    assert "Send position" not in body


def test_a_list_key_shows_beside_its_menu_entry_but_is_not_an_app_binding():
    from kissterm.ui.menu import _entry_text

    get_mail = next(c for c in cmd.COMMANDS if c.action == "get_mail")
    assert get_mail.list_key == "g" and not get_mail.key
    assert _entry_text(get_mail, "", 30).plain.rstrip().endswith("G")
    assert all(b.action != "get_mail" for b in cmd.app_bindings())
