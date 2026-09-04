"""Backward-compatible import path for `KissTermApp`.

The Textual app used to be defined entirely in this file. It moved into the
`kissterm.ui` package -- see `kissterm/ui/app.py`'s module docstring for why
and for the file map, and `kissterm/ui/AGENTS.md` for the rules that apply to
editing anything under `kissterm/ui/` -- so that each pane (terminal, monitor,
heard, APRS, settings) is a single file a smaller model can edit without
reading the rest of the app.

`kissterm/__main__.py` does `from .app import KissTermApp`; this shim exists
so that keeps working without the launcher needing to track where inside the
UI package the class currently lives.
"""

from __future__ import annotations

from .ui import KissTermApp

__all__ = ["KissTermApp"]
