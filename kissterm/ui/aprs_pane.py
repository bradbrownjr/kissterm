"""The APRS pane -- today a placeholder, roadmapped as P4.

APRS decoding already runs: every UI frame goes through the frame fan-out in
`app.py` like anything else, and position/message traffic already shows up
in the Monitor pane's text. What does not exist yet is a *dedicated* view --
a station map or list, message traffic with ack/retry, beaconing -- and this
module is where that pane belongs once it is built. It is split out now,
ahead of that work, specifically so building it means opening this one file:
add a subscriber to the existing fan-out (never a second decode path -- see
`app.py`'s docstring), keep the widget self-contained, and leave `app.py`'s
bindings and other panes untouched.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static


class AprsPane(Container):
    """Placeholder body for the APRS tab. Replace `compose()` when the real
    pane (station list/map, messaging, beaconing) is built; nothing else in
    the app should need to change.
    """

    def compose(self) -> ComposeResult:
        yield Static(
            "APRS decoding is wired into the frame fan-out; the pane\n"
            "itself is P4 on the roadmap. Position and message traffic\n"
            "already shows in the Monitor tab.",
            classes="placeholder",
        )
