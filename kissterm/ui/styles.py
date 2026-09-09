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
TerminalPane { layout: horizontal; }
#terminal-main-column { width: 1fr; layout: vertical; }
/* The Address Book slide-out -- hidden by default (TerminalPane.on_mount),
   toggled by Ctrl+G. See DESIGN.md's "slide-out panels" section: docked
   right, no animation, focus moves in on open. Same width and border
   treatment as AprsPane's own contacts slide-out below, so the two read as
   one pattern rather than two coincidentally similar panels. */
/* No padding here -- AddressBookPane already pads itself (0 2) so this
   column does not double it. */
#terminal-addressbook-column { width: 58%; border-left: solid $panel; }
#transcript-note { height: auto; padding: 0 1; color: $text-muted; }
/* Hidden until Ctrl+F -- see TerminalPane.open_find. */
#find-row { height: auto; display: none; }
#find-input { border: round $accent; width: 1fr; }
#find-status { width: auto; padding: 1 1 0 1; color: $text-muted; }
#find-close { margin-left: 1; }
#session-log { border: round $primary; height: 1fr; }
#session-send-row { height: auto; }
#session-input { border: round $accent; width: 1fr; }
#session-send { margin-left: 1; }  /* shape comes from the base Button rule above */

/* Monitor pane */
MonitorPane { layout: vertical; }
#monitor-filter { height: 3; }
/* Input's own default CSS is `width: 100%`, which inside a Horizontal means
   "the whole row" -- it left no room for the sibling button at all, pushing
   it off the right edge where nothing on screen hinted it existed. Confirmed
   against `screenshot-monitor.png` from before this fix: the button was
   already missing there, independent of anything else changed alongside it. */
#monitor-query { width: 1fr; }
#monitor-log { border: round $primary; height: 1fr; }

/* Heard pane */
HeardPane { layout: vertical; }
#heard-table { height: 1fr; }

/* Address Book pane */
AddressBookPane { layout: vertical; padding: 0 2; }
.addressbook-note { padding: 1 0; color: $text-muted; max-width: 100; }
#addressbook-table { height: 1fr; }
.addressbook-actions { height: auto; margin-top: 1; }
.addressbook-actions Button { margin-right: 1; }
.addressbook-hint { padding: 1 0; color: $text-muted; }

/* APRS pane */
AprsPane { height: 1fr; }
#aprs-conversation-column { width: 1fr; padding: 0 2; }
/* The contacts slide-out -- hidden by default (AprsPane.on_mount), toggled
   by Ctrl+G. Same width/border treatment as the Terminal pane's Address
   Book slide-out -- see DESIGN.md's "slide-out panels" section. */
#aprs-contacts-column { width: 58%; padding: 0 2; border-left: solid $panel; }
#aprs-contact-table { height: 1fr; }
#aprs-conversation-title { padding: 1 0; color: $text-muted; }
#aprs-conversation-log { height: 1fr; border: solid $panel; }
#aprs-compose-row { height: auto; margin-top: 1; }
#aprs-to-input { border: round $accent; width: 12; margin-right: 1; }
#aprs-compose-input { border: round $accent; width: 1fr; margin-right: 1; }

/* Connect dialog */
ConnectScreen { align: center middle; }
#connect-box {
    width: 72; height: auto; padding: 1 2;
    border: thick $primary; background: $surface;
}
#connect-transport { width: 100%; margin-top: 1; }
#connect-buttons { height: auto; align: right middle; margin-top: 1; }
#connect-buttons Button { margin-left: 1; }
/* The address book is a single-row dropdown, not a bordered list -- see
   ConnectScreen's docstring. Collapsing it from an always-visible,
   up-to-8-row OptionList (plus its own title and hint rows) to one row is
   most of what took the dialog from too tall to fit a normal terminal. */
#connect-address-book { width: 100%; margin-top: 1; }
/* `width: 100%` so this wraps inside the box instead of being clipped at its
   edge -- a `Label`'s default auto width sizes to fit the text on one line,
   which is longer than the dialog and was reading as cut off mid-sentence. */
#connect-hint { color: $text-muted; width: 100%; height: auto; }
#connect-script-title { color: $text-muted; width: 100%; height: auto; margin-top: 1; }
#connect-script-hint { color: $text-muted; width: 100%; height: auto; }
#connect-credential { width: 100%; }
/* Hidden by default (`ConnectScreen._sync_login_controls`) -- shown only
   for "+ Add new credential..." or a preview that already has one, same
   reasoning as #connect-hops below. */
#connect-credential-name { margin-top: 1; }
/* Fixed and short on purpose -- a login script is a handful of lines
   (callsign, password, maybe a mailbox command), not a document, and a
   box that grew with its content would push Connect/Cancel around. */
#connect-script { height: 4; border: round $primary; margin-top: 1; }

/* APRS contact dialog -- shares #connect-box/#connect-title/#connect-error/
   #connect-buttons with every other modal in this file (one screen visible
   at a time, so the shared ID is not a conflict). */
AprsContactScreen { align: center middle; }
#aprs-contact-service { width: 100%; margin-top: 1; }
#aprs-contact-detail-hint { color: $text-muted; width: 100%; height: auto; }
#connect-script:disabled { border: round $panel; }
#connect-script-name { width: 100%; margin-top: 1; }
/* Hidden by default -- almost no connect uses node hops, and a field that
   is blank 99% of the time does not earn a permanent row. Shown only for
   "+ Node hops (advanced)..." or a preview that already has some (see
   ConnectScreen._sync_login_controls, which is also why this is not just
   `display: none` in CSS -- the visibility rule depends on live state). */
#connect-hops { margin-top: 1; }
/* AddressBookEntryScreen's frequency/connection-type row -- two short
   fields side by side rather than stacked, since both together are still
   shorter than the target line above them. */
#addressbook-radio-row { height: auto; margin-top: 1; }
#addressbook-radio-row Input, #addressbook-radio-row Select { width: 1fr; }
#addressbook-radio-row Input:first-child { margin-right: 1; }
/* RadioReminderScreen -- a checkpoint, not a form; sized to its short
   fixed content rather than the wider #connect-box default. */
#reminder-detail { color: $text; padding: 0 0 1 0; }
/* TransportEntryScreen. Reuses #connect-title/#connect-buttons; the box
   itself gets its own id and a capped height with an internal scroll --
   SSH's four fields plus name/kind/error/auto-login is taller than a
   typical terminal, and an un-capped `#connect-box` (every shorter dialog's
   choice) pushed Save/Cancel off the bottom, unreachable. */
TransportEntryScreen { align: center middle; }
#transport-box {
    width: 72; height: auto; max-height: 90%; padding: 1 2;
    border: thick $primary; background: $surface;
}
#transport-form { height: 1fr; }
#transport-kind { margin-top: 1; width: 100%; }
#transport-fields { margin-top: 1; height: auto; }
#transport-script-title { color: $text-muted; width: 100%; height: auto; margin-top: 1; }
#transport-script-hint { color: $text-muted; width: 100%; height: auto; }
#transport-credential { width: 100%; }
#transport-script-name { width: 100%; margin-top: 1; }
#transport-script { height: 4; border: round $primary; margin-top: 1; }
#transport-script:disabled { border: round $panel; }

.placeholder { padding: 1 2; color: $text-muted; }

#ref-box {
    width: 90%; height: 80%; padding: 1 2;
    border: thick $primary; background: $surface;
}
#ref-title { text-style: bold; color: $accent; }
#ref-note, #ref-help { color: $text-muted; padding: 0 0 1 0; }
#ref-table { height: 1fr; }

TranscriptsScreen { align: center middle; }
#transcripts-box {
    width: 90%; height: 85%; padding: 1 2;
    border: thick $primary; background: $surface;
}
#transcripts-title { text-style: bold; color: $accent; }
#transcripts-note { color: $text-muted; padding: 0 0 1 0; }
/* Table and preview side by side -- a callsign/date alone rarely says
   enough to pick the right session; seeing the text next to the list does. */
#transcripts-body { height: 1fr; }
#transcripts-table { width: 40%; }
#transcripts-preview { width: 60%; border: round $primary; margin-left: 1; }
#transcripts-export-row { height: auto; margin-top: 1; }
#transcripts-export-row Input { width: 1fr; }
#transcripts-export-row Button { margin-left: 1; }

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
/* A hex value is short; the full 46-wide Input would be mostly empty and
   would crowd the swatch out of the row. */
.settings-row Input.settings-color-input { width: 20; }
/* The swatch's fill is the one legitimate exception to "never hardcode a
   hex value" (DESIGN.md#2): it renders an arbitrary color the operator
   typed, not a piece of kissterm's own chrome, so it is set at runtime from
   the field's value rather than from a theme token. Only its border --
   which IS kissterm's own chrome -- uses one, and switches to $error the
   moment the typed value stops being a color Theme can accept. */
.settings-swatch { width: 4; height: 1; margin: 1 0 0 1; border: round $panel; }
.settings-swatch.-invalid { border: round $error; }
/* Its own bar now, not the last row of a field column -- no label-column
   indent to match, just enough top margin to separate it from the banner. */
.settings-actions { margin-top: 1; }
/* custom_choice / filtered_choice: a Select stacked over its companion
   Input inside one field's widget column, rather than a second settings-row
   -- keeps the preset/custom (or filter/pick) pair visually grouped as one
   control instead of reading as two unrelated fields. */
.settings-custom-choice, .settings-filtered-choice { height: auto; width: 46; }
.settings-custom-choice-input, .settings-filtered-choice-filter { margin-top: 1; }
/* Position entry: latitude and longitude side by side, narrower than the
   default 46 so the pair fits the same column a single field would. */
.settings-decimal-pair { height: auto; }
.settings-decimal-pair Input { width: 22; margin-right: 1; }
"""
