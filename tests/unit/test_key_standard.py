"""The keyboard standard, enforced (docs/ROADMAP.md P0.2, DESIGN.md 5).

Keys were chosen one at a time here, each against the collisions known that
day, and the result was a Footer advertising `^O` for a key bound to
Ctrl+Shift+O -- which an ordinary terminal delivers as Ctrl+O, a different
command. The underlying fact is that **Ctrl+Shift+letter and Ctrl+letter are
the same byte** unless the terminal and every layer between (tmux, ssh)
speak an enhanced keyboard protocol, and a ham station PC is usually reached
through exactly those layers.

So this walks every `BINDINGS` list in `kissterm/ui/` and fails on a key
outside the allowlist, on more global Ctrl keys than the budget allows, and
on a `key_display` that names a different chord from the one bound. It is
the enforcement; the prose is in DESIGN.md.

Plain pytest: importing the widget modules is enough, no event loop.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

from kissterm._isolate import isolate

isolate()

from textual.binding import Binding  # noqa: E402

import kissterm.ui  # noqa: E402
from kissterm.ui import commands as cmd  # noqa: E402

#: Keys any terminal delivers unambiguously, and that nothing between the
#: operator and this app is likely to eat.
ALLOWED_SPECIAL = {
    "escape", "enter", "tab", "shift+tab", "insert", "delete", "backspace",
    "space", "up", "down", "left", "right", "home", "end", "pageup", "pagedown",
}
ALLOWED_FUNCTION = {f"f{n}" for n in range(1, 11)}

#: Ctrl keys this app may take. Ctrl+I/M/H/[/J are Tab, Enter, Backspace,
#: Escape and LF; Ctrl+C/Z/\\ are signals; Ctrl+S is flow control; Ctrl+A and
#: Ctrl+B are the screen and tmux prefixes; Ctrl+A/E/K/U are line editing
#: in an input. What is left is the budget. Ctrl+W was line editing too,
#: until the operator asked for it as Close tab (2026-09-23); word-delete
#: moved to Ctrl+Backspace / Ctrl+Delete (`kissterm/ui/inputs.py`).
ALLOWED_CTRL = {
    "ctrl+q", "ctrl+n", "ctrl+d", "ctrl+t", "ctrl+f", "ctrl+l", "ctrl+g",
    "ctrl+r", "ctrl+p", "ctrl+w",
}

#: The only keys with a modifier that are not in the budget: aliases of
#: Enter that a legacy terminal already delivers as plain Enter, so they add
#: a key on terminals that distinguish them and cost nothing where they do
#: not. They are `show=False` and nothing depends on them.
ENTER_ALIASES = {"shift+enter", "ctrl+enter", "alt+enter"}

#: Word-delete in a text field (`kissterm/ui/inputs.py`), the same reasoning:
#: where a terminal cannot tell Ctrl+Backspace from Backspace, or Ctrl+Delete
#: from Delete, the key degrades to deleting one character, not to a
#: different command.
WORD_DELETE = {"ctrl+backspace", "ctrl+delete"}


def _binding_classes():
    """Every class in `kissterm.ui` that declares its own BINDINGS."""
    for info in pkgutil.iter_modules(kissterm.ui.__path__):
        module = importlib.import_module(f"kissterm.ui.{info.name}")
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ != module.__name__:
                continue
            if "BINDINGS" in vars(obj):
                yield obj


def _bindings(cls):
    for binding in vars(cls)["BINDINGS"]:
        if isinstance(binding, Binding):
            yield binding
        else:  # a (key, action, description) tuple
            yield Binding(*binding)


def _keys(binding: Binding):
    return [key.strip() for key in binding.key.split(",") if key.strip()]


def test_every_bound_key_is_terminal_safe():
    offenders = []
    for cls in _binding_classes():
        for binding in _bindings(cls):
            for key in _keys(binding):
                if key in ENTER_ALIASES or key in WORD_DELETE:
                    continue
                allowed = (
                    key in ALLOWED_SPECIAL
                    or key in ALLOWED_FUNCTION
                    or key in ALLOWED_CTRL
                    or (len(key) == 1 and key.isalnum())
                )
                if not allowed:
                    offenders.append(f"{cls.__module__}.{cls.__name__}: {key}")
    assert not offenders, (
        "keys outside the terminal-safe allowlist (DESIGN.md 5):\n  "
        + "\n  ".join(offenders)
    )


def test_a_plain_letter_is_only_bound_where_typing_is_not_the_point():
    """A bare printable key is swallowed by any focused text input, so it
    may only be bound on a list or table -- where it is the CUA convention
    (Midnight Commander, a dialing directory) and cannot eat a keystroke
    meant for a message."""
    for cls in _binding_classes():
        letters = [
            key for binding in _bindings(cls) for key in _keys(binding)
            if len(key) == 1 and key.isalnum()
        ]
        if not letters:
            continue
        bases = {base.__name__ for base in cls.__mro__}
        assert bases & {"DataTable", "OptionList", "ListView", "Tabs"}, (
            f"{cls.__name__} binds {letters} but is not a list widget"
        )


def test_the_app_stays_within_its_global_ctrl_budget():
    from kissterm.ui.app import KissTermApp

    ctrl = {
        key for binding in KissTermApp.BINDINGS for key in _keys(binding)
        if key.startswith("ctrl+")
    }
    assert ctrl <= ALLOWED_CTRL, f"outside the budget: {sorted(ctrl - ALLOWED_CTRL)}"
    assert len(ctrl) <= 9, f"{len(ctrl)} global Ctrl keys: {sorted(ctrl)}"


def test_the_footer_prints_exactly_what_to_press():
    """A `key_display` that names a different chord from the bound key is
    how `^O Object` came to mean Ctrl+Shift+O while Ctrl+O was Transcripts."""
    for cls in _binding_classes():
        for binding in _bindings(cls):
            if not binding.key_display:
                continue
            assert binding.key_display == cmd.key_label(binding.key), (
                f"{cls.__name__}: {binding.key} prints as {binding.key_display}"
            )


def test_every_registry_command_has_an_action_and_every_binding_a_command():
    from kissterm.ui.app import KissTermApp

    for command in cmd.COMMANDS:
        name = cmd.action_base(command.action)
        assert hasattr(KissTermApp, f"action_{name}"), f"no action_{name} for {command.label}"
    for binding in KissTermApp.BINDINGS:
        assert cmd.commands_for(binding.action), f"{binding.key} is not in the registry"


def test_every_tab_has_a_key_and_every_tab_key_is_a_function_key():
    keys = {
        c.action: c.key for c in cmd.COMMANDS if c.action.startswith("show_tab")
    }
    assert len(keys) == len(cmd.TAB_ORDER)
    for tab in cmd.TAB_ORDER:
        key = keys[f"show_tab('{tab}')"]
        assert key in ALLOWED_FUNCTION and key not in ("f1", "f10"), (
            f"{tab} is on {key}; F1 is Help and F10 is the menu"
        )
