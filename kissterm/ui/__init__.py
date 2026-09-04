"""Re-export `KissTermApp` from `kissterm.ui.app`.

Kept to this one line on purpose: this file is not where UI logic goes.
`kissterm/app.py` (one level up) is a thin backward-compatible shim that
imports from here, so `from kissterm.app import KissTermApp` -- what
`kissterm/__main__.py` uses -- keeps working. See `kissterm/ui/app.py`'s
module docstring for the file map, and `kissterm/ui/AGENTS.md` for the
rules that apply to editing anything in this package.
"""

from __future__ import annotations

from .app import KissTermApp

__all__ = ["KissTermApp"]
