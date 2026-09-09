"""A `RichLog` that wraps to the width it is actually being shown at.

Three panes keep a scrollback -- the terminal session, the channel monitor,
and the APRS conversation view -- and all three had the same defect, which is
why the fix is one class rather than three copies.

**What goes wrong with a plain `RichLog`.** `RichLog.write` measures the
renderable, shrinks it to the visible column, and then does
`render_width = max(render_width, self.min_width)` -- `min_width` defaults to
78. So in any column narrower than 78 every line is rendered 78 cells wide,
is *not* wrapped, and has its tail left off the right-hand edge behind a
horizontal scrollbar. That is not hypothetical: on an 80-column terminal, and
at any width at all with a Ctrl+G slide-out open beside it, a node's `?`
listing arrived cut off mid-word ("`B to disconn`") and the APRS merged view
lost the `[ack]`/`[no ack]` status that is the whole reason those lines carry
one. It was found by looking at a generated screenshot, which is the argument
for AGENTS.md sec. 6's rule about generating one.

**Why `min_width=0` is NOT the fix, even though it looks like it.** A widget
on an inactive `TabPane` has a content width of *zero*. With `min_width=0`
the shrink clamps to 0 and the line renders as an empty strip -- so anything
arriving while the operator is looking at another tab is written into the
scrollback as a blank line and is gone for good. That is far worse than a
truncated line: node output that scrolls past while you are on the Monitor
tab simply disappears. It shipped for exactly one test run and was caught by
`tests/pilot/test_aprs_send.py::test_an_unacked_message_is_retried`, which
reads the terminal log while the APRS tab is the active one.

**So the fallback is the last width this log was really laid out at**,
remembered on resize. Visible, it wraps to the column it is in; hidden, it
uses the width it had when it was last on screen, which is the closest thing
to a right answer available. A log that has never been visible keeps
`RichLog`'s own 78, which is no worse than before.

This only affects lines written *after* the resize -- `RichLog` never re-wraps
what it has already rendered, and reflowing the whole scrollback on every
resize is not worth it for a log an operator scrolls back through rarely.
"""

from __future__ import annotations

from textual.widgets import RichLog


class WrapLog(RichLog):
    """`RichLog` that keeps `min_width` in step with its own laid-out width."""

    def on_resize(self) -> None:
        width = self.scrollable_content_region.width
        if width > 0:
            self.min_width = width
