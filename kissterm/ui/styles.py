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
   Scan for hardware, Forget, Close, Send, all of it. Textual's
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

/* Focus is shown by the border, and only by the border: whichever field,
   log, list or table has focus is drawn in $accent, and everything else in
   $primary (DESIGN.md section 2: $accent is "the active/current thing").
   Reported from a real station: the send box was orange permanently, so after
   clicking into the scrollback the operator typed and wondered why nothing
   reached the send line. Kept as type rules so no pane has to remember it --
   an ID rule that sets `border` would outrank these and pin one colour
   again, which is exactly the bug. Style a widget's size by ID; leave its
   border to this block. */
Input, TextArea, RichLog, DataTable, OptionList, ListView, Switch,
Select > SelectCurrent { border: round $primary; }
Input:focus, TextArea:focus, RichLog:focus, DataTable:focus, OptionList:focus,
ListView:focus, Switch:focus,
Select:focus > SelectCurrent { border: round $accent; }
/* Compact controls (`compact=True`): one row, no border, for screens where
   the text being written needs the height (DESIGN.md section 3, "Dense
   where the content is the point"). Focus is still shown in the same two
   colours, as a background tint instead of a border. */
Input.-textual-compact, Select.-textual-compact > SelectCurrent {
    border: none; height: 1; background: $primary 15%;
}
Input.-textual-compact:focus, Select.-textual-compact:focus > SelectCurrent {
    border: none; background: $accent 25%;
}
Button.-textual-compact {
    border: none; height: 1; min-width: 0; padding: 0 1; background: $primary 15%;
}
Button.-textual-compact:focus { background: $accent 25%; }
TextArea.-textual-compact { border: none; }
Button.-textual-compact.-primary { color: $primary; }
/* Exempt: chrome that is not a field. App CSS outranks every widget's own
   DEFAULT_CSS, so without these the Ctrl+P palette and the F10 menu's item
   list would grow boxes. Values are Textual's / menu.py's own defaults. */
CommandInput, CommandInput:focus { border: blank; }
CommandList {
    border-top: blank; border-bottom: hkey black;
    border-left: none; border-right: none;
}
CommandList:focus { border: blank; }
CommandList.--populating { border-bottom: none; }
MenuScreen #menu-items, MenuScreen #menu-items:focus { border: none; }

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
/* Starting value only; set on resize by `kissterm/ui/slideouts.py` -- see
   the note on `#aprs-contacts-column` below. */
#terminal-addressbook-column { width: 58%; border-left: solid $panel; }
/* The session tab strip -- one tab per simultaneous connection, hidden
   below two sessions (`TerminalPane._sync_strip_visibility`). Same
   subordinate-to-the-F-key-bar treatment as `#aprs-convo-tabs` above, for
   the identical reason: a second row of tabs that looked like the first
   would read as two competing navigations rather than a hierarchy. */
#terminal-session-row { height: auto; margin-bottom: 1; }
#terminal-session-tabs { height: 2; width: 1fr; }
#terminal-session-tabs Tab { color: $text-muted; }
#terminal-session-tabs Tab.-active { color: $accent; text-style: bold; }
#terminal-session-tabs Tab.-unread { color: $warning; text-style: bold; }
#terminal-session-tabs Underline > .underline--bar { color: $panel; }
/* Hidden until Ctrl+F -- see TerminalPane.open_find. */
#find-row { height: auto; display: none; }
#find-input { width: 1fr; }
#find-status { width: auto; padding: 1 1 0 1; color: $text-muted; }
#find-close { margin-left: 1; }
#session-log { height: 1fr; }
/* Hidden until there is something to suggest -- see
   `TerminalPane._update_suggestions`. Same subordinate, muted treatment as
   `#find-status`; the top candidate's own bold/dim spans (set in Python,
   not here) are what actually distinguish it from the rest of the row. */
#suggestion-strip { height: auto; padding: 0 1; color: $text-muted; display: none; }
#session-send-row { height: auto; }
#session-input { width: 1fr; }
#session-send { margin-left: 1; }  /* shape comes from the base Button rule above */

/* BBS mail helpers are a compact parameter picker, not a second terminal.
   The returned command goes into #session-input and still needs its normal
   deliberate Send/Enter commit. */
#bbs-helper-box { width: 72; height: auto; max-height: 90%; padding: 1 2; border: thick $primary; background: $surface; }
#bbs-helper-title { color: $accent; text-style: bold; }
#bbs-helper-note, #bbs-helper-help { height: auto; color: $text-muted; margin-bottom: 1; }
#bbs-profile, #bbs-macro, #bbs-number, #bbs-callsign { width: 100%; margin-top: 1; }
#bbs-preview { height: auto; margin-top: 1; color: $success; }
#bbs-helper-error { height: auto; color: $warning; }

/* Monitor pane */
MonitorPane { layout: vertical; }
#monitor-filter { height: 3; }
/* Input's own default CSS is `width: 100%`, which inside a Horizontal means
   "the whole row" -- it left no room for the sibling button at all, pushing
   it off the right edge where nothing on screen hinted it existed. Confirmed
   against `screenshot-monitor.png` from before this fix: the button was
   already missing there, independent of anything else changed alongside it. */
#monitor-query { width: 1fr; }
#monitor-port { width: 16; margin-left: 1; }
#monitor-log { height: 1fr; }

/* Heard pane */
HeardPane { layout: vertical; }
.message-browser { height: 1fr; }
.mail-tree { width: 28; height: 1fr; border: round $primary; }
.mail-right { width: 1fr; height: 1fr; }
/* Ctrl+G's Address Book on the Mail, Bulletins and Files tabs: the same
   column as Terminal's; `slideouts.SlideOut` sets its width. */
.mail-addressbook-column { width: 58%; height: 1fr; border-left: solid $panel; }
.mail-list { height: 2fr; }
.mail-reader { height: 3fr; border: round $primary; padding: 0 1; }
#heard-radar { width: auto; margin-bottom: 1; }
#heard-table { height: 1fr; }
#heard-radar-view { height: 1fr; border: round $primary; padding: 0 1; color: $text-muted; }

/* Address Book pane. No note above the table and no key-hint line below
   the buttons -- Textual's Footer is the context-aware shortcut bar for
   `_AddressBookTable.BINDINGS` already (AGENTS.md), and dropping both
   Statics lines up this pane's button row with the Terminal pane's own
   input-and-Send row on the other side of the split. `AprsPane`'s contacts
   slide-out dropped its own matching caption the same way -- see that
   module's `compose`. */
AddressBookPane { layout: vertical; padding: 0 2; }
#addressbook-table { height: 1fr; }
#known-nodes-note { height: auto; margin-top: 1; color: $warning; }
#known-nodes-table { height: 10; }  /* 8 rows inside the focus border */
.addressbook-actions { height: auto; margin-top: 1; }
.addressbook-actions Button { margin-right: 1; }

/* APRS pane */
AprsPane { height: 1fr; }
#aprs-conversation-column { width: 1fr; padding: 0 2; }
/* The contacts slide-out -- hidden by default (AprsPane.on_mount), toggled
   by Ctrl+G. Same width/border treatment as the Terminal pane's Address
   Book slide-out -- see DESIGN.md's "slide-out panels" section. */
/* The width here is a STARTING value only -- `kissterm/ui/slideouts.py`
   overwrites it on every resize, because the rule ("58%, but never leave the
   column beside me less than 40 cells") cannot be written in CSS: there is no
   arithmetic to relate a width to a sibling's minimum. Read that module
   before changing this number; changing it alone changes nothing. */
#aprs-contacts-column { width: 58%; padding: 0 2; border-left: solid $panel; }
#aprs-contact-table { height: 1fr; }
#aprs-conversation-title { padding: 1 0 0 0; color: $text-muted; }
/* The conversation tab strip -- a SECOND row of tabs on the same screen as
   the F-key tab bar, which is the whole styling problem. The generic
   `Tabs Tab.-active` rule above plus Textual's own underline bar would make
   this look exactly like that bar, and two identical-looking navigations
   competing on one screen is not a hierarchy. So this one reads as
   subordinate: the underline bar is dimmed to the panel colour instead of
   the accent, inactive tabs are muted, and only the active tab keeps the
   accent. Same fact, one visual language -- see DESIGN.md. */
#aprs-convo-row { height: auto; margin-bottom: 1; }
#aprs-convo-tabs { height: 2; width: 1fr; }
#aprs-convo-tabs Tab { color: $text-muted; }
#aprs-convo-tabs Tab.-active { color: $accent; text-style: bold; }
/* Unread: `$warning`, the same colour the contacts table's `*` row uses, so
   the two markers for one fact read as one marker. The `*` in the label
   carries it on its own for anyone who cannot see the colour. An unread tab
   is never the active one -- activating it is what clears the mark -- so
   these two rules cannot fight over the same tab. */
#aprs-convo-tabs Tab.-unread { color: $warning; text-style: bold; }
#aprs-convo-tabs Underline > .underline--bar { color: $panel; }
#aprs-sensor-summary {
    display: none; height: auto; margin-bottom: 1; padding: 0 1;
    border: round $panel; color: $text-muted;
}
#aprs-conversation-log { height: 1fr; }
#aprs-compose-row { height: auto; margin-top: 1; }
#aprs-to-input { width: 8; margin-right: 1; }
#aprs-compose-input { width: 1fr; margin-right: 1; }
/* The service/template picker (Ctrl+R on this pane). Reuses #ref-box's
   geometry deliberately -- it is the APRS counterpart to the terminal's
   command reference and should not read as a different kind of screen. */
#aprs-service-table { height: 1fr; }
#aprs-service-search { margin-bottom: 1; }

/* APRS-IS Watch is a diagnostic, not an APRS compose route. */
AprsIsWatchScreen { align: center middle; }
#aprs-is-watch-box {
    width: 88; height: 85%; padding: 1 2;
    border: thick $primary; background: $surface;
}
#aprs-is-watch-status { color: $text-muted; width: 100%; height: auto; margin-top: 1; }
#aprs-is-watch-log { height: 1fr; margin-top: 1; }

/* The object composer uses the existing dialog shape and the same shared
   symbol picker as APRS Settings. Its coordinate fields read as one pair. */
#aprs-object-box {
    width: 72; height: auto; max-height: 90%; padding: 1 2;
    border: thick $primary; background: $surface;
}
#aprs-object-name, #aprs-object-comment { width: 100%; margin-top: 1; }
#aprs-object-alive, #aprs-object-scope, #aprs-object-coordinate-format { width: 100%; margin-top: 1; }
.aprs-object-coordinates { height: auto; margin-top: 1; }
.aprs-object-coordinates Input { width: 1fr; }
.aprs-object-coordinates Input:first-child { margin-right: 1; }
#aprs-object-reference { width: 100%; margin-top: 1; }
#aprs-object-hint { color: $text-muted; width: 100%; height: auto; margin-top: 1; }

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
#connect-script { height: 4; margin-top: 1; }

/* ComposeScreen: a dialog, but one with no empty rows in it -- one-row
   controls, the SR note beside the heading, the error beside the buttons,
   and every row left over goes to the text (DESIGN.md section 3). */
ComposeScreen { align: center middle; }
#compose-box {
    width: 100; max-width: 95%; height: 90%; padding: 0 1;
    border: thick $primary; background: $surface;
}
.compose-row { height: 1; }
#compose-heading { width: 1fr; text-style: bold; color: $text; }
#compose-type { width: 26; }
.compose-label { width: 7; color: $text-muted; }
.compose-at-label { width: 4; padding: 0 1; }
.compose-row Input { width: 1fr; }
#compose-note { width: 1fr; color: $text-muted; }
#compose-body { height: 1fr; }
#compose-foot { height: auto; }
#compose-error { width: 1fr; height: auto; color: $error; }
#compose-foot Button { margin-left: 1; }

/* First-run onboarding intentionally asks for one required fact before
   handing off to the established Settings transport editor.  It is a short
   guide, not a second settings page. */
OnboardingScreen { align: center middle; }
#onboarding-box {
    width: 72; height: auto; padding: 1 2;
    border: thick $primary; background: $surface;
}
#onboarding-intro, #onboarding-call-hint, #onboarding-aprs-note {
    color: $text-muted; width: 100%; height: auto;
}
#onboarding-call-label { margin-top: 1; color: $accent; }
#onboarding-callsign { width: 100%; }
#onboarding-aprs-note { margin-top: 1; }
#onboarding-error { color: $error; width: 100%; height: auto; }

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
/* AddressBookEntryScreen: labelled one-row fields, no empty rows (DESIGN.md
   section 3). Capped, with the fields scrolling inside, so Save/Cancel
   stay on screen on anything smaller than it needs (about 18 rows). */
AddressBookEntryScreen { align: center middle; }
AddressBookEntryScreen #connect-box { max-height: 90%; padding: 0 1; }
AddressBookEntryScreen #connect-title { text-style: bold; }
#addressbook-form { height: auto; max-height: 1fr; }
.ab-row { height: 1; }
.ab-row Input, .ab-row Select { width: 1fr; }
.ab-label { width: 8; color: $text-muted; }
.ab-label-2 { padding-left: 1; }
.ab-gap { width: 1; }
AddressBookEntryScreen #connect-script-title { width: auto; margin-top: 0; padding-right: 1; }
AddressBookEntryScreen #connect-script-hint { width: 1fr; height: 1; }
AddressBookEntryScreen #connect-credential { width: 1fr; }
AddressBookEntryScreen #connect-hops,
AddressBookEntryScreen #connect-script-name { margin-top: 0; width: 1fr; }
AddressBookEntryScreen #connect-script { height: 4; margin-top: 0; background: $primary 15%; }
AddressBookEntryScreen #connect-script:focus { background: $accent 25%; }
AddressBookEntryScreen #connect-buttons { height: auto; margin-top: 0; }
.ab-foot #connect-error { width: 1fr; height: auto; color: $error; }
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
#transport-script { height: 4; margin-top: 1; }
#transport-script:disabled { border: round $panel; }

.placeholder { padding: 1 2; color: $text-muted; }

#ref-box {
    /* 92%, not the 80% every other modal box here uses -- this is the one
       modal whose whole point is a scrollable list, and on a terminal short
       enough to matter (a real report: 90x24) the fixed note/mode-row/
       search chrome above the table already eats ~11 rows on its own,
       squishing the table to a single row at 80%. `overflow-y: auto` is
   the backstop: if a still-shorter terminal cannot fit the reference list's
       own `min-height` alongside everything else, the BOX scrolls instead
       of silently clipping the Learn-from-node/Close buttons outside its
       own border, which is what an unclamped Vertical did here. */
    width: 90%; height: 92%; padding: 1 2;
    border: thick $primary; background: $surface;
    overflow-y: auto;
}
#ref-title { text-style: bold; color: $accent; }
#ref-note, #ref-help { color: $text-muted; padding: 0 0 1 0; }
/* Commands and glossary are two views of one reference, so use the same
   compact subordinate tab treatment as the APRS conversation strip rather
   than a pair of action-looking buttons. */
#ref-mode-tabs { height: 2; margin-bottom: 1; }
#ref-mode-tabs Tab { color: $text-muted; }
#ref-mode-tabs Tab.-active { color: $accent; text-style: bold; }
#ref-mode-tabs Underline > .underline--bar { color: $panel; }
#ref-harvest-status { color: $text-muted; padding: 1 0 0 0; display: none; }
#ref-harvest-output { height: 8; min-height: 4; margin-top: 1; display: none; }
#ref-show-harvest { display: none; }
/* min-height, not just `1fr`: on a short terminal `1fr` still shrinks this
   to a single row once the fixed elements above and below it claim their
   own space -- see #ref-box's comment. Six rows is enough to see more than
   one command without scrolling on anything but the smallest terminals. */
#ref-table, #ref-glossary { height: 1fr; min-height: 6; }

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
#transcripts-preview { width: 60%; margin-left: 1; }
#transcripts-export-row { height: auto; margin-top: 1; }
#transcripts-export-row Input { width: 1fr; }
#transcripts-export-row Button { margin-left: 1; }

/* Help tab (F1). Its section strip is an inner strip, so it gets the same
   subordinate treatment as the other inner strips: muted inactive tabs, and
   the underline bar dimmed to $panel -- the accent bar belongs to the F-key
   row above it (DESIGN.md, "A second tab strip inside a pane"). */
HelpPane { layout: vertical; height: 1fr; }
#help-tabs { height: 1fr; }
#help-tabs Tab { color: $text-muted; }
#help-tabs Tab.-active { color: $accent; text-style: bold; }
#help-tabs Underline > .underline--bar { color: $panel; }
.help-toolbar { height: auto; padding: 0 1; }
.help-toolbar-label { width: auto; padding: 1 1 0 0; }
#help-keys-for, #help-node-family { width: 32; }
#help-node-search { width: 1fr; }
#help-node-note { padding: 0 1; color: $text-muted; }
#help-keys-scroll, #help-guide-scroll { height: 1fr; padding: 0 1; }
#help-guide-list { width: 30; height: 1fr; }
#help-node-table, #help-glossary-body { height: 1fr; padding: 0 1; }
#help-about-scroll { padding: 1 2; }
/* Settings (F9): a section list, one section's fields, and a bar that never
   scrolls. Generated from settings_schema, so these rules style whole
   classes of row rather than any particular field -- adding a setting must
   never mean adding CSS. See `SettingsPane`'s docstring for why a field is
   one row and its help is one line at the bottom (DESIGN.md section 3,
   "Dense where the content is the point"). */
SettingsPane { layout: vertical; }
#settings-body { height: 1fr; }
#settings-sections { width: 18; height: 1fr; border: round $primary; }
#settings-switcher { width: 1fr; height: 1fr; }
.settings-section { padding: 0 1; }
.settings-note { padding: 0 0 1 0; color: $text-muted; max-width: 92; }
.settings-row { height: auto; min-height: 1; }
.settings-label { width: 27; padding: 0 1 0 0; }
.settings-row.-invalid .settings-label { color: $error; text-style: bold; }
/* Up to 46 wide, narrower on a small screen rather than cut off. */
.settings-row Input, .settings-row Select { width: 1fr; max-width: 46; }
.settings-row Button { margin-left: 1; }
.settings-buttons { height: auto; margin: 0; }
.settings-buttons Button { margin: 0 1 0 0; }
.settings-detail { padding: 0 0 1 0; color: $text-muted; max-width: 92; }
/* A switch as one row: the track only, no box around it. */
.settings-row Checkbox { width: auto; }
/* A heading inside a section (Mail's Home BBS, the custom colours). */
.settings-rule-label {
    margin: 1 0 0 0; color: $text-muted; text-style: bold;
    border-bottom: solid $panel; max-width: 92;
}
.settings-conditional { height: auto; }
.settings-advanced { margin: 1 0 0 0; padding: 0; border: none; background: transparent; }
.settings-advanced > Contents { padding: 0; }
#settings-bar { height: auto; padding: 0 1; border-top: solid $panel; }
.settings-banner {
    padding: 0 1; margin: 0 0 1 0;
    background: $warning-darken-2; color: $text;
    max-width: 92;
}
#settings-help-line { height: auto; min-height: 2; max-height: 5; color: $text-muted; }
#settings-help-line.-error { color: $error; }
.settings-actions { height: auto; }
#settings-footer { width: 1fr; height: auto; }
.settings-actions Button { margin-left: 1; }
/* A hex value is short; the full 46-wide Input would be mostly empty. */
.settings-row Input.settings-color-input { width: 12; max-width: 12; }
/* The swatch's fill is the one legitimate exception to "never hardcode a
   hex value" (DESIGN.md#2): it renders an arbitrary color the operator
   typed, not a piece of kissterm's own chrome, so it is set at runtime from
   the field's value. An invalid value shows as an error-coloured block. */
.settings-swatch { width: 4; height: 1; margin: 0 0 0 1; }
.settings-swatch.-invalid { background: $error 40%; }
/* custom_choice / filtered_choice: a Select stacked over its companion
   Input inside one field's control column, so the pair reads as one
   control rather than two unrelated fields. */
.settings-custom-choice, .settings-filtered-choice { height: auto; width: 1fr; max-width: 46; }
/* Position entry: latitude and longitude side by side in one column. */
.settings-decimal-pair { height: auto; width: 1fr; max-width: 46; }
.settings-decimal-pair Input { width: 1fr; margin-right: 1; }

/* ASCII-safe mode is deliberately a stylesheet concern: unlike mutating
   Textual's global border table it cannot leak into another mounted app or a
   parallel test. The application-owned glyph inventory is: round/solid/thick
   panel borders -> +, -, |; tab underline -> no glyph (the bold accent label
   remains the selected-tab marker); header icon -> * (clock.py); and APRS
   picker emoji -> no glyph (symbols.py). These are the application's bordered
   controls and panels; remote text still reaches them through the existing
   sanitizer. Textual's Unicode-only Bar is hidden rather than patched. */
.-ascii-safe Button,
.-ascii-safe Input,
.-ascii-safe TextArea,
.-ascii-safe Select > SelectCurrent,
.-ascii-safe RichLog,
.-ascii-safe DataTable,
.-ascii-safe OptionList,
.-ascii-safe ListView,
.-ascii-safe Switch,
.-ascii-safe #terminal-addressbook-column,
.-ascii-safe .mail-addressbook-column,
.-ascii-safe #aprs-contacts-column,
.-ascii-safe #aprs-sensor-summary,
.-ascii-safe #connect-box,
.-ascii-safe #onboarding-box,
.-ascii-safe #transport-box,
.-ascii-safe #ref-box,
.-ascii-safe #transcripts-box,
.-ascii-safe #settings-sections {
    border: ascii $primary;
}
/* The focus rule above, in ASCII. */
.-ascii-safe Input:focus,
.-ascii-safe TextArea:focus,
.-ascii-safe Select:focus > SelectCurrent,
.-ascii-safe RichLog:focus,
.-ascii-safe DataTable:focus,
.-ascii-safe OptionList:focus,
.-ascii-safe ListView:focus,
.-ascii-safe Switch:focus { border: ascii $accent; }
.-ascii-safe CommandInput, .-ascii-safe CommandInput:focus,
.-ascii-safe CommandList, .-ascii-safe CommandList:focus { border: blank; }
.-ascii-safe #menu-items, .-ascii-safe #menu-items:focus { border: none; }
/* Disabled scripts deliberately use the muted panel colour. Their
   ID-plus-pseudo-class rules outrank the enabled override above. */
.-ascii-safe #connect-script:disabled,
.-ascii-safe #transport-script:disabled { border: ascii $panel; }
.-ascii-safe #settings-bar { border-top: ascii $panel; }
.-ascii-safe .settings-rule-label { border-bottom: ascii $panel; }
.-ascii-safe Underline { display: none; }
.-ascii-safe WrapLog,
.-ascii-safe .settings-section,
.-ascii-safe #ref-box,
.-ascii-safe #transcripts-box { scrollbar-visibility: hidden; }

"""
