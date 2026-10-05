"""The core's words name no key and no tab (`kissterm/core/wording.py`).

A phone has no Ctrl+T and no F8. The core writes tokens; the terminal
renders them as its keys and tabs, every other client neutrally. This
fails if a key name creeps back into a core string, or a token is used
that a renderer does not know.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import ast  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402

from kissterm.core import wording  # noqa: E402
from kissterm.ui.operator import render  # noqa: E402

CORE = Path(__file__).resolve().parents[2] / "kissterm" / "core"
#: Help text the schema still carries for the terminal (core/AGENTS.md rule
#: 1, known gap), until it is tokenized.
_NOT_YET = {"settings_schema.py"}
_KEY_NAME = re.compile(r"\bCtrl\+|\((?:F\d+)\)|\bF(?:[1-9]|1[0-2])\b")


def _strings(path: Path):
    """Every string constant that is not a docstring."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant):
            docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in docstrings:
            yield node.lineno, node.value


def test_no_core_string_names_a_key_or_tab():
    found = [
        f"{path.name}:{line}: {text!r}"
        for path in sorted(CORE.glob("*.py")) if path.name not in _NOT_YET
        for line, text in _strings(path) if _KEY_NAME.search(text)
    ]
    assert not found, "write a wording token instead:\n" + "\n".join(found)


def test_every_token_in_the_core_renders_both_ways():
    tokens = {
        match.group(0)
        for path in CORE.glob("*.py")
        for _line, text in _strings(path)
        for match in wording.TOKEN.finditer(text)
    }
    assert tokens, "no tokens found: the scan is broken"
    for token in sorted(tokens):
        neutral, terminal = wording.neutral(token), render(token)
        assert "{" not in neutral and "{" not in terminal, token
        kind, name = token[1:-1].split(":")
        if kind == "key":
            assert name in wording.KEYS, f"{token}: no neutral name in wording.KEYS"
            assert terminal != neutral, f"{token}: the terminal has no key for it"


def test_the_terminal_keeps_its_words():
    assert render(wording.TRANSMIT_DISABLED) == "Transmit is disabled -- press Ctrl+T to enable it."
    assert render("The {view:monitor} shows") == "The Monitor tab (F8) shows"
    assert wording.neutral("The {view:monitor} shows") == "The Monitor shows"
    assert render("{view:settings/Radio} > Test") == "Settings (F9) > Radio > Test"
