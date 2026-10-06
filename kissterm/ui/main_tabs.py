"""The main tab row, which ignores a pane-focused message that arrives late.

Textual's `TabbedContent` re-activates a pane when a widget inside it
takes focus: the pane posts `TabPane.Focused` and the container handles
it by switching to that pane. The message is handled later, not at the
moment of focus, so it can arrive after the operator has already moved
on. At launch the Terminal's send line is focused; a tab key pressed
within the first frame or so (F9) switched to Settings and cleared
focus, and then the queued message switched back to Terminal. Found by
`tests/pilot/test_addressbook_pane.py::test_settings_is_f9_and_ctrl_g_
closes_and_reopens_the_addressbook` (ROADMAP P0.1, 2026-10-05). A slow
machine (a Pi) gives the operator the same window.

The message is acted on only if focus is still inside that pane when it
is handled. A deliberate focus into another pane (Ctrl+F switching to
the Terminal's find box) still holds focus there, so it still switches.
"""

from __future__ import annotations

from textual.widgets import TabbedContent, TabPane


class MainTabs(TabbedContent):
    def _on_tab_pane_focused(self, event: TabPane.Focused) -> None:
        # Textual calls this class's handler, then `TabbedContent`'s own,
        # unless `prevent_default` stops it; a current message falls
        # through to that one unchanged.
        focused = self.screen.focused
        if focused is None or event.tab_pane not in focused.ancestors_with_self:
            # Stale: focus left the pane before this was handled.
            event.stop()
            event.prevent_default()
