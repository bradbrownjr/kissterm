"""The small `X` at the end of a tab row that closes the tab on screen.

Shared by the Terminal session strip and the APRS conversation strip, so the
two rows cannot drift into two looks for the same act.

Why a one-line marker and not a `Button`. The first version was a house-style
`Button` ("Close tab") beside each strip: three rows tall with its rounded
border, it made the tab row taller than the tabs and took a dozen columns
from a strip that is often narrow with a slide-out open. The operator's
verdict on a real screen: "an unnecessarily huge close tab button ... a
simple X at the end of the row of tabs like Notepad++ has would suffice".
So this is text, one row high, the height of a tab label, with the key
(Ctrl+W) and what it will do in its tooltip.

It only posts `Clicked`; the pane that owns the strip decides what closing
means (a live Terminal session is disconnected first).
"""

from __future__ import annotations

from textual.message import Message
from textual.widgets import Static


class CloseTabX(Static):
    """Click to close the tab on screen."""

    DEFAULT_CSS = """
    CloseTabX {
        width: 3;
        height: 1;
        content-align: center middle;
        color: $text-muted;
    }
    CloseTabX:hover { color: $error; text-style: bold; }
    CloseTabX.-disabled { color: $text-disabled; }
    CloseTabX.-disabled:hover { color: $text-disabled; text-style: none; }
    """

    class Clicked(Message):
        """The X was clicked while enabled."""

        def __init__(self, x: "CloseTabX") -> None:
            super().__init__()
            self.x = x

        @property
        def control(self) -> "CloseTabX":
            # What `@on(CloseTabX.Clicked, "#id")` matches its selector on.
            return self.x

    def __init__(self, *, id: str | None = None, tooltip: str = "Close tab (Ctrl+W)") -> None:
        super().__init__("X", id=id)
        self.tooltip = tooltip

    @property
    def enabled(self) -> bool:
        return not self.has_class("-disabled")

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self.set_class(not value, "-disabled")

    def on_click(self) -> None:
        if self.enabled:
            self.post_message(self.Clicked(self))
