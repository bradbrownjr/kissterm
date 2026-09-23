"""`WordInput`: an `Input` whose word-delete keys are Ctrl+Backspace and
Ctrl+Delete.

Ctrl+W closes the tab on screen (the operator's choice, 2026-09-23), bound
with priority, so it can no longer be the Input's delete-previous-word.
Textual 8.2.8 then leaves no sensible word-delete: it binds Ctrl+Backspace
to delete the word to the RIGHT (Alt+Backspace too) and Ctrl+Delete to
nothing. The operator uses Ctrl+Backspace / Ctrl+Delete for the words left
and right, as most desktop editors do, so this class binds them that way.

Used for the lines people type into all day: the Terminal send line and the
APRS compose row. Whether Ctrl+Backspace reaches the app as its own key
depends on the terminal -- many send the same byte as Backspace -- so
`scripts/keycheck.py` is the way to see what arrives.
"""

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import Input


class WordInput(Input):
    BINDINGS = [
        Binding("ctrl+backspace", "delete_left_word", "Delete word left", show=False),
        Binding("ctrl+delete", "delete_right_word", "Delete word right", show=False),
    ]
