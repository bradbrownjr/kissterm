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

**The second defect, and why it is fixed here too.** `RichLog.auto_scroll`
acts on `write` and nowhere else, so a log sitting exactly at the bottom stops
being at the bottom the moment something *takes rows away from it* -- and
nothing brings it back, because no new line arrives to trigger the scroll. On
the terminal pane the suggestion strip is seven rows tall when a command
prefix matches, the find bar is three more, and closing the Address Book
slide-out changes the wrap width; each one pushes the tail of the scrollback
under the fold while the widget still reports `auto_scroll`. Measured on an
80x24 terminal: 40 lines of node output ending in a prompt left `scroll_y=27`
against `max_scroll_y=34` once the strip appeared -- the last seven lines,
prompt included, simply gone from view.

That is the bug an operator reported four times ("the last line hides out of
view, often the node prompt ... so I'm sitting and waiting for more output
from the node not knowing it's actually waiting on me"). It was read as a
prompt-rendering problem and four fixes went into the *write* path, which is
the half that was already working. The general statement is "if the log was at
the bottom before the layout changed, it is at the bottom after".

`Widget.anchor()` is Textual's own name for exactly that, and it is re-applied
by the compositor on every arrange (`_compositor.py`), not on write -- so it
covers the resize, the strip, the find bar and the slide-out without any of
them having to know a scrollback exists. Scrolling up releases the anchor
(`_scroll_to` does it), so an operator reading back is never yanked to the
bottom, and scrolling back down restores it (`_check_anchor`). Do not
"simplify" this into a `scroll_end` in `on_resize`: that reads the state
*after* the resize, when what is at the bottom has already changed, and it
would fight the operator's own scrollback on every repaint.

**Text selection.** `RichLog` does not support Textual's mouse selection:
its lines are pre-rendered `Strip`s, `Widget.get_selection` finds no `Text`
to extract, and its strips carry no offsets for the screen to map the
pointer to. So a drag in the terminal pane, the Monitor or the mail reader
selected nothing, and with the mouse captured by the app the terminal's own
selection is unavailable too (reported 2026-09-24). `_render_line` below adds
the offsets and paints the selected span; `get_selection` returns the plain
text of the rows. Ctrl+C then copies it (Textual's `screen.copy_text`, sent
to the terminal as OSC 52).
"""

from __future__ import annotations

from rich.segment import Segment
from rich.style import Style
from textual.geometry import Size
from textual.selection import Selection
from textual.strip import Strip
from textual.widgets import RichLog


class WrapLog(RichLog):
    """`RichLog` that keeps `min_width` -- and the bottom -- in step with its
    own laid-out size.

    `follow=False` is for a document rather than a log (the Mail reader): it
    opens at the top and stays where the reader scrolls it, instead of
    following the last line written."""

    def __init__(self, *args, follow: bool = True, **kwargs) -> None:
        if not follow:
            kwargs["auto_scroll"] = False
        super().__init__(*args, **kwargs)
        self._follow = follow

    def on_mount(self) -> None:
        # Textual dispatches `on_mount` to every class in the MRO that
        # defines one, so this does not shadow `ScrollView.on_mount` and its
        # scrollbar refresh. Anchoring from here rather than at construction
        # because `anchor()` scrolls, and a widget has no geometry to scroll
        # within until it is mounted.
        if self._follow:
            self.anchor()

    def on_resize(self) -> None:
        width = self.scrollable_content_region.width
        if width > 0:
            self.min_width = width

    # -- Taking back the last write -------------------------------------
    #
    # The terminal pane shows a partial line (a prompt with no line end, or
    # the first half of a line whose second half is still on the air) after
    # a short idle, and must replace it in place when the rest arrives --
    # otherwise every frame boundary that outlasts the idle becomes a line
    # break, and a CR arriving a frame late becomes a blank line. RichLog
    # has no API for that, so these two methods are the only place that
    # reaches into its internals (`lines`, `_start_line`, `_line_cache`,
    # `_deferred_renders`, all as of Textual 8.2.8).

    def mark(self) -> tuple[int, int]:
        """A position to `drop_since` later: rows ever written, and writes
        still waiting for the widget to learn its size."""
        return (self._start_line + len(self.lines), len(self._deferred_renders))

    def drop_since(self, mark: tuple[int, int]) -> None:
        """Remove everything written after `mark`."""
        rows, deferred = mark
        while len(self._deferred_renders) > deferred:  # a deque: no slicing
            self._deferred_renders.pop()
        extra = self._start_line + len(self.lines) - rows
        if extra > 0:
            del self.lines[-extra:]
            self._line_cache.clear()
            self.virtual_size = Size(self._widest_line_width, len(self.lines))
            self.refresh()

    # -- Mouse selection (see the module docstring) -----------------------

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        text = "\n".join(strip.text.rstrip() for strip in self.lines)
        return selection.extract(text), "\n"

    def selection_updated(self, selection: Selection | None) -> None:
        self._line_cache.clear()
        self.refresh()

    def _render_line(self, y: int, scroll_x: int, width: int) -> Strip:
        selection = self.text_selection
        if selection is None or y >= len(self.lines):
            line = super()._render_line(y, scroll_x, width)
        else:
            line = self.lines[y]
            span = selection.get_span(y)
            if span is not None:
                start, end = span
                end = line.cell_length if end == -1 else end
                # The theme's selection style can resolve to one colour on
                # itself (tokyo-night: #6a5a8e on #6a5a8e), which hid the
                # selected text. Take its background; keep the text's colour.
                chosen_style = self.screen.get_component_rich_style("screen--selection")
                style = Style(
                    bgcolor=chosen_style.bgcolor,
                    color=None if chosen_style.color == chosen_style.bgcolor else chosen_style.color,
                )
                parts = line.divide([start, end, line.cell_length])
                if len(parts) >= 2:
                    # post_style: the selection colours win over the text's own.
                    chosen = Strip(
                        Segment.apply_style(parts[1], post_style=style), parts[1].cell_length
                    )
                    parts = [parts[0], chosen, *parts[2:]]
                    line = Strip.join(parts)
            line = line.crop_extend(scroll_x, scroll_x + width, self.rich_style)
        return line.apply_offsets(scroll_x, y)
