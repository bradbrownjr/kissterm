"""The keys the docs name are the keys the app binds (docs/ROADMAP.md P0.2).

README's key table is generated from `COMMANDS` (`scripts/sync_docs.py`);
the first test fails until the script has been run after a key change. Keys
named in running prose cannot be generated, so the other tests check each
mention against the registry instead. The hand-written copies had already
drifted: README sent operators to "Settings (F5)" in five places after
Settings moved to F9 and F5 became Monitor.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import re  # noqa: E402
from pathlib import Path  # noqa: E402

from kissterm.ui.commands import (  # noqa: E402
    COMMANDS,
    README_KEYS_END,
    README_KEYS_START,
    TAB_TITLES,
    action_base,
    key_label,
    markdown_key_table,
)

ROOT = Path(__file__).resolve().parents[2]
USER_DOCS = ("README.md", "SETUP.md")
ALL_DOCS = USER_DOCS + ("DESIGN.md",)

#: Tab title -> its key label, e.g. "Settings" -> "F9". Help is a tab too.
TAB_KEYS = {
    TAB_TITLES[c.action.split("'")[1]]: key_label(c.key)
    for c in COMMANDS
    if action_base(c.action) == "show_tab"
}
TAB_KEYS["Help"] = "F1"

#: Every Ctrl key the app answers to, as prose writes it ("Ctrl+N").
BOUND_CTRL = {key_label(c.key, short=False) for c in COMMANDS if c.key.startswith("ctrl+")}

#: Ctrl keys the user docs name on purpose although nothing binds them:
#: README explains that tmux's prefix is deliberately left alone.
NAMED_BUT_UNBOUND = {"Ctrl+B"}

_TITLES = "|".join(TAB_KEYS)
#: "Settings (`F9`)", "Settings tab (F9)", "`F9` Settings", "F9 Settings".
_TITLE_THEN_KEY = re.compile(rf"\b({_TITLES})(?: tab)? \(`?(F\d+)`?\)")
_KEY_THEN_TITLE = re.compile(rf"`?\b(F\d+)`? ({_TITLES})\b")
_CTRL = re.compile(r"\bCtrl\+([A-Za-z0-9]+)\b(?!\+)")


def test_readme_key_table_is_generated_from_the_registry():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    start = readme.index(README_KEYS_START) + len(README_KEYS_START)
    end = readme.index(README_KEYS_END)
    assert readme[start:end].strip() == markdown_key_table(), (
        "README.md's key table is stale: run .venv/bin/python scripts/sync_docs.py"
    )


def test_every_tab_key_named_in_the_docs_is_that_tabs_key():
    wrong = []
    for name in ALL_DOCS:
        for number, line in enumerate((ROOT / name).read_text(encoding="utf-8").splitlines(), 1):
            for title, key in _TITLE_THEN_KEY.findall(line):
                if TAB_KEYS[title] != key:
                    wrong.append(f"{name}:{number}: {title} ({key}) -- it is {TAB_KEYS[title]}")
            for key, title in _KEY_THEN_TITLE.findall(line):
                if TAB_KEYS[title] != key:
                    wrong.append(f"{name}:{number}: {key} {title} -- it is {TAB_KEYS[title]}")
    assert not wrong, "\n".join(wrong)


def test_every_ctrl_key_the_user_docs_name_is_bound():
    unknown = []
    for name in USER_DOCS:
        for number, line in enumerate((ROOT / name).read_text(encoding="utf-8").splitlines(), 1):
            for letter in _CTRL.findall(line):
                key = f"Ctrl+{letter.upper()}"
                if key not in BOUND_CTRL and key not in NAMED_BUT_UNBOUND:
                    unknown.append(f"{name}:{number}: {key}")
    assert not unknown, "keys named in the docs that nothing binds:\n" + "\n".join(unknown)
