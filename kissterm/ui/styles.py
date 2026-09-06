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

/* One flat button style for the whole app -- Connect, Cancel, Save, Reload,
   Scan for hardware, Forget selected, Close, Send, all of it. Textual's
   default Button has a two-tone "tall" border that reads as a raised, chunky
   3D bezel; combined with the bright solid fill `variant="primary"` applies,
   it looked like it belonged to a different, more skeuomorphic app than the
   rounded, outlined panels everywhere else (`#session-log`, `#session-input`,
   `#connect-box`, `#ref-box`). A rounded single-color border with no fill
   makes a button read as "the same kind of box" as an Input or a RichLog,
   which is the whole visual language this app otherwise uses. Variant classes
   (`-primary`, `-error`, ...) still change ONLY the border/text color, never
   the shape or the fill, so a Save button and a destructive action still read
   as different without either one becoming a different kind of widget. */
Button {
    border: round $primary;
    background: $surface;
    color: $text;
    text-style: bold;
    height: 3;
    min-width: 10;
}
Button:hover { background: $primary 15%; }
Button:focus { background: $primary 25%; }
Button.-primary { border: round $primary; color: $primary; }
Button.-primary:hover { background: $primary 20%; }
Button.-success { border: round $success; color: $success; }
Button.-warning { border: round $warning; color: $warning; }
Button.-error { border: round $error; color: $error; }
Button.-error:hover { background: $error 20%; }

/* Active tab: bold accent-colored text plus the underline bar below it,
   nothing else. Textual's default fills the active tab with a solid
   "block cursor" background as soon as the tab strip has focus (its normal
   behaviour for a keyboard-navigable list), which reads as a heavy, jarring
   rectangle next to the flat outlined panels everywhere else in this app --
   flagged from a real screenshot as "looking funny". The underline bar is the
   indicator; the tab text just needs to stand out, not sit in a filled box. */
Tabs Tab.-active { background: transparent; text-style: bold; color: $accent; }
Tabs:focus Tab.-active { background: transparent; text-style: bold; color: $accent; }
Underline > .underline--bar { color: $accent; }

/* The status bar and the Footer live inside ONE bottom-docked container.
   Docking each of them separately lands both in the same region -- the Footer
   paints over the status bar and it is invisible, in either yield order. That
   bug shipped in the first cut and was only caught by generating a
   screenshot, which is a good argument for keeping scripts/generate_screenshot.py
   working.

   Order within the container is deliberate too, and yield order alone does
   NOT control it: `Footer`'s own DEFAULT_CSS docks it to "bottom" no matter
   where it is yielded, so it would pin itself under the status bar even
   when written second. It has to be told to dock to the TOP of this
   container instead, which is what `#bottom-bar Footer` below overrides. The
   keys you might press read above the passive transport/link/heard-count
   summary, top to bottom, matching what a user actually does with each row. */
#bottom-bar { dock: bottom; height: 2; }
#bottom-bar Footer { dock: top; }
/* $background, not $panel -- matches the near-black the tab bar and the
   Screen itself already use (measured: $background #121212 vs $panel
   #242F38, the slate-blue the Header and Footer keep). Requested directly:
   the status readout should look like the same black chrome as the row
   above the panes, not like the Header/Footer's own shade. */
#status-bar {
    height: 1; width: 100%; padding: 0 1;
    background: $background; color: $text-muted;
}

/* Terminal pane */
TerminalPane { layout: vertical; }
#session-log { border: round $primary; height: 1fr; }
#session-send-row { height: auto; }
#session-input { border: round $accent; width: 1fr; }
#session-send { margin-left: 1; }  /* shape comes from the base Button rule above */

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
    width: 72; height: auto; padding: 1 2;
    border: thick $primary; background: $surface;
}
#connect-hops { margin-top: 1; }
#connect-buttons { height: auto; align: right middle; margin-top: 1; }
#connect-buttons Button { margin-left: 1; }
/* The address book. A visible border and its own title, because "no border,
   same background as the dialog" made a first-time operator unable to tell
   the history apart from the rest of the box -- it read as decoration, not
   as a list of anything. `max-height` rather than a fixed height so a first
   run with no history does not reserve a blank hole in the middle of the
   box, and a long list scrolls instead of pushing the buttons off screen. */
#connect-history-title { color: $text-muted; margin-top: 1; }
#connect-history { max-height: 8; border: round $primary; background: $surface; }
/* `width: 100%` so this wraps inside the box instead of being clipped at its
   edge -- a `Label`'s default auto width sizes to fit the text on one line,
   which is longer than the dialog and was reading as cut off mid-sentence. */
#connect-hint { color: $text-muted; width: 100%; height: auto; }
#connect-script-title { color: $text-muted; width: 100%; height: auto; margin-top: 1; }
#connect-credential { width: 100%; }
/* Fixed and short on purpose -- a login script is a handful of lines
   (callsign, password, maybe a mailbox command), not a document, and a
   box that grew with its content would push Connect/Cancel around. */
#connect-script { height: 4; border: round $primary; margin-top: 1; }
#connect-script:disabled { border: round $panel; }

.placeholder { padding: 1 2; color: $text-muted; }

#ref-box {
    width: 90%; height: 80%; padding: 1 2;
    border: thick $primary; background: $surface;
}
#ref-title { text-style: bold; color: $accent; }
#ref-note, #ref-help { color: $text-muted; padding: 0 0 1 0; }
#ref-table { height: 1fr; }

/* Settings form. Generated from settings_schema, so these rules style whole
   classes of row rather than any particular field -- adding a setting must
   never mean adding CSS.

   THE COLUMN GRID. Every row is the same three columns, so labels, controls
   and apply-notes line up down the whole page instead of each row finding its
   own edges:

       |<-- 26 -->|<------- 46 ------->|<-- 20 -->|
        Callsign    [ N1ABC-1        ]   next connection
        ^label      ^control             ^apply note

   The help/error indent (27) is the label width plus its right padding, so
   help text hangs under the CONTROL, not under the label. If you change
   --label width, change the help indent by the same amount; they are two
   numbers that have to agree and Textual CSS has no arithmetic to tie them.

   Body text is capped at 92 columns (`max-width` on notes and help). A help
   line running the full width of an ultrawide terminal is technically
   readable and practically not -- the eye loses the line start on the way
   back. The form column itself is ~92 wide, so the two agree. */
/* Settings is now a TabbedContent (one tab per schema section) over a bar
   that never scrolls. `#settings-tabs` takes all the vertical space the tab
   content is given; `#settings-bar` is sized to its own content so Save
   stays reachable in one click regardless of which tab is open or how far
   down its list the operator has scrolled -- the single long page this
   replaced put Save at the bottom of several screens' worth of fields. */
SettingsPane { layout: vertical; }
#settings-tabs { height: 1fr; }
.settings-tab-scroll { padding: 0 2; }
#settings-bar { height: auto; padding: 1 2 0 2; border-top: solid $panel; }
/* Tall enough to show several stations without scrolling on an ordinary
   terminal, short enough that the buttons and hint below it stay on
   screen too -- fixed, not 1fr, since this tab's VerticalScroll wrapper
   already handles anything longer than that. */
#settings-addressbook-table { height: 14; margin-top: 1; }
.settings-banner {
    padding: 1 2; margin: 0 0 1 0;
    background: $warning-darken-2; color: $text;
    max-width: 92;
}
.settings-note { padding: 0 1 1 1; color: $text-muted; max-width: 92; }
.settings-row { height: auto; padding: 0 1; margin-top: 1; }
.settings-label { width: 26; padding: 1 1 0 0; }
.settings-apply { width: 20; padding: 1 0 0 2; color: $text-muted; }
.settings-help { padding: 0 1 0 27; color: $text-muted; max-width: 92; }
.settings-error { padding: 0 1 0 27; color: $error; display: none; }
/* Fixed, not 1fr: a control that stretches with the window makes the
   apply-note column drift and the page lose its vertical alignment. */
.settings-row Input { width: 46; }
.settings-row Select { width: 46; }
.settings-row Button { margin-right: 1; }
/* Its own bar now, not the last row of a field column -- no label-column
   indent to match, just enough top margin to separate it from the banner. */
.settings-actions { margin-top: 1; }
"""
