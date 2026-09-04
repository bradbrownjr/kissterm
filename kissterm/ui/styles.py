"""All of the app's Textual CSS, in one place.

Kept as a module-level string rather than an external `.tcss` file so that
appearance is one import away from every pane and cannot drift out of sync with
a packaged data file that setuptools forgot to include.

The point of this file is that changing how kissterm *looks* never means
opening a pane's logic, and changing what a pane *does* never means scrolling
past a stylesheet. If you are adding a widget, add its rule here and give it an
id -- do not reach for inline `styles.` assignments in a pane, which are
invisible from this file and are how a theme ends up half-applied.
"""

from __future__ import annotations

APP_CSS = """
Screen { layout: vertical; }

/* The status bar and the Footer live inside ONE bottom-docked container.
   Docking each of them separately lands both in the same region -- the Footer
   paints over the status bar and it is invisible, in either yield order. That
   bug shipped in the first cut and was only caught by generating a
   screenshot, which is a good argument for keeping scripts/generate_screenshot.py
   working. */
#bottom-bar { dock: bottom; height: 2; }
#status-bar {
    height: 1; width: 100%; padding: 0 1;
    background: $panel; color: $text-muted;
}

/* Terminal pane */
TerminalPane { layout: vertical; }
#session-log { border: round $primary; height: 1fr; }
#session-input { border: round $accent; }

/* Monitor pane */
MonitorPane { layout: vertical; }
#monitor-filter { height: 3; }
#monitor-log { border: round $primary; height: 1fr; }

/* Heard pane */
HeardPane { layout: vertical; }
#heard-table { height: 1fr; }

/* Connect dialog */
ConnectScreen { align: center middle; }
#connect-box {
    width: 60; height: auto; padding: 1 2;
    border: thick $primary; background: $surface;
}
#connect-buttons { height: auto; align: right middle; margin-top: 1; }
#connect-buttons Button { margin-left: 1; }

.placeholder { padding: 1 2; color: $text-muted; }
"""
