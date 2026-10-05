"""`kissterm/core/` imports nothing from Textual or the terminal UI.

The core is what a phone, desktop or browser client drives over the
WebSocket API (ROADMAP P7a); one widget import there ties every client to
the terminal UI again. Checked two ways: statically, so the failure names
the file and line, and at run time, so an indirect import (core -> some
module -> textual) is caught too.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[2] / "kissterm" / "core"
FORBIDDEN = ("textual", "kissterm.ui")


def _imports(path: Path) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                # Resolve `..ui` and `.x` against kissterm.core.
                base = ["kissterm", "core"][: 3 - node.level] if node.level <= 2 else []
                module = ".".join(base + ([module] if module else []))
            found.append((node.lineno, module))
    return found


def test_no_core_module_imports_textual_or_the_ui():
    offenders = [
        f"{path.name}:{line} imports {name}"
        for path in sorted(CORE.glob("*.py"))
        for line, name in _imports(path)
        if any(name == f or name.startswith(f + ".") for f in FORBIDDEN)
    ]
    assert not offenders, "core must stay UI-free: " + "; ".join(offenders)


def test_importing_the_core_loads_no_textual_module():
    code = (
        "import sys\n"
        "import kissterm.core\n"
        "bad = sorted(m for m in sys.modules if m == 'textual' or m.startswith('textual.')"
        " or m.startswith('kissterm.ui'))\n"
        "print(','.join(bad))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "", "kissterm.core pulled in: " + result.stdout.strip()
