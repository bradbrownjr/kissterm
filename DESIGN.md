# DESIGN.md — kissterm's visual and interaction schema

The rules kissterm's interface follows, and why. This is the document to read
before changing how anything looks, and to point at when something looks
wrong. `AGENTS.md` carries the engineering rules; this one carries the design
rules. Where a rule exists because a real screenshot looked wrong, that is
recorded — the reasoning is the useful part, not the number.

Implementation lives in `kissterm/ui/styles.py` (all CSS, one file) and
`kissterm/ui/themes.py` (the color system). No pane file contains styling.

---

## 1. First principles

**This is a terminal for a radio, not a dashboard.** The operator is often
mid-net, sometimes under stress, occasionally elderly, and frequently reading
a screen in a car or a shelter. Clarity beats density; density beats
decoration; decoration is not a goal.

**Nothing decorative may cost airtime or attention during a contact.** No
animation, no spinner that implies progress it cannot measure, no toast for
anything that is not actionable.

**Every color is a theme variable.** Never a literal hex in CSS. This is what
let 21 themes (`themes.py`) land without touching a single style rule, and it
is why a new rule that hardcodes `#1A1B26` silently breaks in 20 of them.

**Say what is true, in the place the operator is already looking.** A status
that matters (`ANSWERING`, a link state, an unplugged TNC) belongs on screen,
not in a log they would have to go find.

---

## 2. Color

Colors come from Textual's theme system. Use the semantic token, never the
appearance:

| Token | Use for |
|---|---|
| `$background` | The app's own ground — tab bar, status bar |
| `$surface` | Panel interiors, dialog bodies |
| `$panel` | Header and Footer chrome |
| `$primary` | Structural borders (pane outlines) |
| `$accent` | The active/current thing: selected tab, section headings, and the border of whatever has focus (everything else is `$primary`) |
| `$text` / `$text-muted` | Body text / secondary text |
| `$error` `$warning` `$success` | State, and only state |

Rules:

- **Never hardcode a hex value in CSS.** If a needed color has no token, add it
  to the theme's `variables` dict, not to a rule.
- **`$error`/`$warning`/`$success` mean state, not emphasis.** A red border
  must mean something is wrong, or red stops meaning anything.
- **The map's legend is the one fixed palette** (APRS > Map, and the
  phone's Map): water blue, roads amber and object pins red, the same on
  both, as on any paper map. A theme's `$primary` may be purple, and
  `$warning` or `$error` on a road would say something is wrong. Lines
  are `$text` at three strengths (country, state, county), this
  station is `$accent`, stations `$primary`, and the cursor's point is
  reversed (`ui/map_screen.py` `LEGEND`).
- **Two surfaces that should read as "the same chrome" must use the same
  token.** The status bar uses `$background` to match the tab bar, not `$panel`
  which the Header uses — they were visibly different shades before that was
  noticed on a screenshot.

---

## 3. Shape and component sizing

**One shape language: flat, rounded, outlined.** Panels, inputs, dialogs and
buttons are all "a box with a rounded single-color border and no fill". A
widget that introduces a different shape reads as belonging to a different
application — which is exactly what a `variant="primary"` Button did before it
was restyled, and it was spotted immediately in a screenshot.

- **Buttons**: `border: round`, no fill, `height: 3`, `min-width: 10`. Variant
  classes (`-primary`, `-error`, ...) change **only** border and text color,
  never shape or fill.
- **Controls are all 3 rows tall** (`Input`, `Select`, `Switch`, `Button`), so
  a form row is one consistent height regardless of which control it holds
  -- in forms. A screen whose job is writing or reading text uses compact
  controls instead (next rule).
- **A dialog's buttons match its fields** (operator, 2026-09-29: "Inconsistency
  in UI is unprofessional and unpolished looking"). A dialog with compact
  fields has only compact buttons; a dialog with none has only bordered
  ones. Never mix the two in one dialog, and a dialog opened from another
  (the saved-login editor from an address-book entry) uses the same style as
  its parent. Enforced by `tests/unit/test_dialog_consistency.py`, which
  reads every `ModalScreen` in `ui/dialogs.py`.
- **A dialog shows its action as a button**, not only as Enter on a list
  (operator, 2026-10-04, on the file picker: "There is no upload button.
  Thankfully, enter worked"). A dialog built around a list has a button
  that does what Enter on the highlighted row does, beside Cancel or
  Close. A full-screen viewer and the menu, which show their keys in the
  Footer, are the exceptions. `tests/unit/test_dialog_consistency.py`.
- **Dense where the content is the point** (2026-09-25). Rows are scarce
  in a terminal; a screen for writing or reading text gives them to the
  text, not to chrome. The compose screen is the reference:
  - **Compact controls** (`compact=True`): one row, no border. Focus shows
    as a tint, `$primary 15%` at rest and `$accent 25%` focused
    (`styles.py`), so the one-colour-for-focus rule still holds.
  - **No empty rows inside the dialog**: fields sit on consecutive rows; a
    note shares the heading's row; the error shares the buttons' row and
    grows only while there is an error.
  - **The text area takes every row left over** (`height: 1fr`) in a box
    sized to the screen (`height: 90%`), never a fixed or content-sized
    height. Two rows to write a message in was the bug that set this rule.
  - **A dialog form that would not fit 80x24 in the roomy style goes
    compact too, with a label at the start of every row**: a placeholder
    names an empty field only, so a filled-in compact field needs its
    label. The Address Book entry dialog is the reference (2026-09-25).
    Its fields still scroll inside a box capped at 90% of the screen, so
    Save and Cancel are never below the bottom edge.
  - A short checkpoint dialog (a reminder, a confirm) keeps the roomier
    3-row form style: there the space is the readability.
- **Never use Textual's default `border: tall`** on an interactive widget. It
  renders as a raised 3D bezel that belongs to a different design era than
  everything else here.

---

## 4. Layout and spacing

### The settings column grid

Every settings row is the same two columns, so the page aligns vertically
instead of each row finding its own edges, and the editor under the list
uses the same first column:

```
|<--- 26 --->| |<------ value ------>|
 Callsign       N1ABC-1                  a row in the section's list
 Callsign      [ N1ABC-1          ]      the same row while Enter edits it
```

- The editor's controls are up to 46 wide, narrower on a small screen.
- A value longer than 60 characters is cut short in its row; the editor
  shows it whole.

### Nothing above the box

**A pane, section or dialog never has a caption above its box.** Its title
names it: the tab label, the Settings sidebar entry, the heading. What a
setting or control does is said once, for the highlighted one, in the
help line at the bottom (section 6). This is how desktop settings windows
work, with a page title and the control's own help and no introductory
paragraph.

A caption above a box does two kinds of harm:
- it pushes the box down, out of line with the list beside it;
- it says again what the title or the help line already says.

A safety statement that matters ("nothing is sent until...", "a callsign
is a claim") goes in the help of the field it is about. The operator
decided this for the APRS pane and the Address Book on 2026-09-10 ("a
caption stating the obvious"), and for Settings on 2026-09-28: "wordy
slop ... duplicated below".

### Measure

**Body text is capped at 92 columns.** A help line spanning an ultrawide
terminal is technically readable and practically not — the eye loses the line
start on the way back. Applies to help text and banners.

### Vertical rhythm

- 1 blank row between fields, 2 above a section heading.
- **Section headings carry a rule** (`border-bottom: solid $panel`). With bold
  accent text alone, sections blur together while scrolling.
- **Settings is one row per field** (operator, 2026-09-25: "new user
  approachable, not overwhelming ... KISS"): its sections listed down the
  left, each section one list of label and value, and the highlighted
  field's help, when it takes effect and any error in one line at the
  bottom. **One editor, laid over the row, changes the highlighted field**
  (2026-09-27, for startup time: a control per field was two thirds of the
  app's widgets; on the row itself because below the list it went
  unnoticed). What is not saved says "(unsaved)" on its row, stars its
  section, and is counted beside Save, which sits at the left under the
  list. Tuning the defaults already get right is listed last,
  under an **Advanced** heading that names its group ("Advanced: Winlink
  ...", `Field.advanced`), every heading with a rule under it and every
  section in the same box; a field that only
  matters for another's value is shown only then (`Field.only_when`). A
  new setting chooses one of the two before it ships. **A label is plain
  words for what the value is** ("Node username", not "Telnet user"), and
  a setting that names an Address Book contact is chosen from the book
  (`kind="contact"`), never typed.

### Information order

**Identity first, then hardware, then tuning.** Settings opens with Station
(callsign, aliases) — the first thing a new operator sets and the most often
changed later — then Radio (the TNC or modem), then everything else.

---

## 5. Keys

**The standard is IBM CUA, as character terminals adopted it** — Turbo
Vision, Midnight Commander, a BIOS setup screen. Its central idea: **every
command is in the menu, and a key is only an accelerator**, so the key budget
can stay inside what a terminal can actually deliver.

**One table, `kissterm/ui/commands.py`'s `COMMANDS`, generates all of it**:
the App's `BINDINGS`, the Footer, the F10 menu, the Keys page of the F1 Help tab and the
Ctrl+P palette. Adding a `Binding` by hand, or a per-tab list inside a
widget, puts the same fact in two places again. `tests/unit/test_key_standard.py`
is the enforcement.

### The rules

1. **F1 is Help. F10 is the menu.** Permanently, on every tab. Help is a
   tab (`F1 Help`, first in the row) that opens on the keys of the tab you
   pressed it from, and F1 again goes back there; the menu is every command, grouped (Session, APRS,
   View, Help), each with its key beside it. Inside the menu, plain letters
   are the mnemonics — the underlined letter runs that entry — so no Alt
   chord is needed anywhere.
2. **Only terminal-safe keys may be bound.** Allowed: F1–F10, Enter, Esc,
   Tab/Shift+Tab, arrows, Home/End, PgUp/PgDn, Insert, Delete, the Ctrl keys
   in rule 3, and plain letters while a **list** has focus. Never bound:
   Ctrl+Shift+anything, Ctrl+digit, Ctrl+Alt+anything, Alt+anything,
   Ctrl+PgUp/PgDn, Ctrl+Tab, F11, F12. **Ctrl+Shift+letter and Ctrl+letter
   are the same byte** unless the terminal, and every layer between (tmux,
   ssh), speak an enhanced keyboard protocol. **kissterm switches that
   protocol off outright** (`kissterm/__init__.py` says why). Ctrl+I, M, H,
   `[` and J
   are Tab, Enter, Backspace, Esc and LF; Ctrl+C, Z and `\` are signals
   (Ctrl+C is left to Textual's own "copy the selection", never rebound);
   Ctrl+S is flow control; Ctrl+A and Ctrl+B are the screen and tmux
   prefixes; Ctrl+A, E, K and U are line editing inside an input.
3. **Ten global Ctrl keys, and that is the whole budget**, each with a
   mnemonic that holds in other software: `Ctrl+Q` Quit, `Ctrl+N` New
   connection, `Ctrl+D` Disconnect, `Ctrl+T` Transmit on/off, `Ctrl+F` Find,
   `Ctrl+L` Clear, `Ctrl+G` side panel, `Ctrl+R` Reconnect (Services on
   APRS), `Ctrl+P`
   palette, `Ctrl+W` close tab. The lines typed into all day (`WordInput`)
   delete a word with Ctrl+Backspace and Ctrl+Delete; inside a dialog Ctrl+W
   is still delete-word. Ctrl+D is bound with `priority=True` so it wins over an `Input`'s
   own delete-right (the Delete key still does that), and only while there is
   something to disconnect. Everything else — send beacon, send position,
   object, bulletin, gateway form, Watch APRS-IS, SSID filter, file transfer,
   NET/ROM panel, callsign, transcripts — lives in the F10 menu and Ctrl+P.
4. **Context keys are plain keys on a focused list.** Enter is the default
   action, Insert is New, Delete is Delete, and anything else is one letter
   shown in the Footer (the Address Book and the APRS contacts table both use
   `E` for Edit). In a text input, typing is typing: no plain-letter binding.
   Edit is not F2, because F2 is a tab.
   Mail, Bulletins and Files: Enter opens, Delete moves to Deleted, U
   restores from Deleted; on Mail, G sends and receives -- with Winlink on
   a Winlink folder, the Home BBS on a BBS folder, and on All Inboxes
   each one that is set up, the Home BBS first, the Footer saying which
   (operator, 2026-09-26); I does the same over the Internet (the Home
   BBS by its Telnet or SSH connection, Winlink by the CMS) -- and Insert
   writes a new message; on Bulletins, G gets bulletins from the Home BBS,
   I the same over the Internet, and S chooses the categories; on Files,
   Delete and U work on files too (Files > Deleted), G gets files from
   the Home BBS by radio (a checklist of what it lists, then a YAPP
   download of each ticked), S sends the
   highlighted file over the connected session, and Enter opens the file
   full screen in the viewer (a click previews it in the reader), where Enter
   fills in a recognised PKTNET form; on Mail and
   Bulletins, V switches a message
   received as a form between the form and its text; while a Send/Receive,
   Get bulletins or Get files is running, G cancels it instead (the Footer
   says "Cancel run"), as the phone's turning button does; T shows or folds
   away a BBS message's routing (its `R:` lines, folded by default as on
   the phone), R replies, A replies to all (a Winlink message with other
   recipients only) and Q replies with the original quoted. None of them transmits; Files' S
   only opens the transfer dialog, which transmits on Start.
   On the APRS map's list (F10 > APRS > Map) I zooms in, O out, F shows
   everything and Enter centres the highlighted point; Insert places a
   new object at the map's centre (the `x`), and on one of this
   station's objects M moves it there and Delete kills it, each through
   the object form, whose Send is the only transmit. Tab moves to the
   map itself, a widget rather than a list, so no letters there: the
   arrows pan and PgUp and PgDn zoom.
5. **The Footer shows only what works right now.** An action that does not
   apply on this tab, or in this state, is absent — not shown and then
   answered with a toast. `KissTermApp.check_action` is where that decision
   lives, and it does both halves at once: the key is left out of the Footer
   *and* falls through to the focused widget, so Ctrl+D is delete-right in
   the send line until there is a session to end.
6. **What the Footer prints is exactly what to press.** No `key_display`
   naming a different chord from the bound key.

### The tab bar

| Key | Tab |
|---|---|
| F1 | Help: keys, node commands, guides, glossary, About |
| F2 | Mail (the launch tab) |
| F3 | Bulletins |
| F4 | Files |
| F5 | Terminal |
| F6 | APRS |
| F7 | Heard |
| F8 | Monitor |
| F9 | Settings |
| F10 | Menu |

- **A tab's key is printed in its label, key first** — `F5 Terminal`, the way
  a menu shows an accelerator. Never `Terminal (F5)`, and never in the Footer
  as well: that put the same words on screen twice, in two corners.
- **Tabs are ordered by what the product is for**, not by when they were
  built. Mail, Bulletins and Files took F2–F4 on 2026-09-23 and Mail is
  the launch tab; Terminal, APRS, Heard and Monitor moved to F5–F8. Help,
  Settings and Menu never move.
- **Help was a modal and is a tab now**, first in the row so the labels
  read F1 to F9 left to right. Requested directly: reading the tab row
  across the top, the operator looked for F1 there, did not
  find it, and reported it missing. As a tab it has room for what a modal
  could not hold -- the shipped node command lists, the guides, the
  glossary, About -- and like every tab key, F1 is not in the Footer too.
- **A tab opened by a click is focused as one opened by its key**: the
  list on Mail, Bulletins and Files, so their keys are in the Footer at
  once; the line to type in on Terminal, APRS and Monitor (operator,
  2026-10-04: a click on Bulletins left G and I out of the Footer).
  `KissTermApp._focus_tab_target`; `tests/pilot/test_tab_focus.py`.
- **The `TabPane` ids never move with the labels** (`help`, `mail`,
  `bulletins`, `files`, `terminal`, `aprs`, `heard`, `monitor`, `settings`): every `active == "aprs"` check addresses a
  pane by id, so a reordering is a table edit, not a search through the app.
- **F1 and F10 are the two keys a terminal emulator may steal** — GNOME
  Terminal opens its own help on F1 and its menu bar on F10 unless the menu
  accelerator is turned off. The Help tab says so. Help can be clicked in
  the tab row and Menu in the Footer, with Ctrl+P as the third way in.

### The Footer

- **It is a context bar, not an inventory**, drawn from the registry rather
  than from `Binding.show`, and it keeps the longest prefix of
  `commands.FOOTER_ORDER` that fits the terminal width. Textual's own
  `Footer` scrolls the overflow off the right edge with no sign anything is
  missing; at 80 columns that was about a third of the keys. `F10 Menu` is
  pinned to the right and never dropped, because it reaches everything that
  was.
- **A focused list's own keys appear there too**, right after Help, and only
  while that widget has focus — never as a hint line under its buttons. A
  modal screen has to `yield Footer()` itself to get this.
- **Dialogs are centred** by one `ModalScreen` rule in `styles.py`; only
  the F10 menu and the Ctrl+P palette sit elsewhere. **A dialog that sends
  the operator somewhere has a button that goes there** ("Winlink
  settings", "Add a connection"), not just the path in words.
- **`Ctrl+P` is a searchable reference for every command**, including those
  with no key at all, grouped by the same headings as the menu.

### Context by tab, not a key per pane

`Ctrl+G` asks one question whose answer depends on where you are, and the
registry gives each tab its own label for it: the Address Book on Terminal
and the contacts list on APRS. The command reference does the same without
a Terminal key: Node commands on Terminal (F10 > Help, or read-only under
F1) and the gateway service picker on APRS (`Ctrl+R`). Both fill an input;
**neither sends**.

`Ctrl+R` is two commands, each scoped to its tab: Reconnect on Terminal and
Services on APRS. Reconnect redials the tab's last request through the
ordinary connect flow, so it arms the transmit gate visibly, like dialing
from the Address Book.

### Everything else about keys

- **Never bind a bare printable key globally.** A focused `Input` swallows
  it, so the binding works inconsistently depending on focus — and this is a
  terminal, where typing a character must always just type that character.
- **Send-line suggestions are a stacked list, not ghost text**
  (`kissterm/ui/terminal_pane.py`): several commands often share a prefix,
  and ghost text can show only one. Each row is a command and its short
  description, from the reference for the current context. Up/Down choose,
  Tab fills without sending, Esc hides the list until the line changes, and
  Enter sends only what is in the line. Tab with nothing suggested moves
  focus as usual.

### Slide-out panels

A contact list that a pane needs but does not want permanently on screen —
the Terminal pane's Address Book, the APRS pane's contacts list, the
Address Book again on Mail, Bulletins and Files (to pick a BBS and dial it)
— is a collapsible column docked on the **right** edge of its pane, not a
tab and not a modal.

- **On the mail tabs it never opens by itself**, shows stations only (the
  NET/ROM claims stay on Terminal), and splits only what is right of the
  folder tree: the list and reader give way, down to the panel taking their
  place on a narrow screen. A dial from it closes it and goes to Terminal.

- **One key opens or closes whichever slide-out belongs to the active
  pane**: `Ctrl+G`. The key's meaning does not change tab to tab; a tab with
  no slide-out (Monitor, Heard, Settings) just has nothing for it to do.
- **No animation, ever, on any slide-out.** "Slides out" describes where the
  panel ends up — docked at the right edge, over nothing else — not a motion
  effect. Sec. 1's rule holds here exactly as everywhere else: nothing
  decorative may cost airtime or attention during a contact. It is an
  instant `display: none` / `display: block` toggle.
- **Opening moves focus into the panel; closing returns it — unless the panel
  opened itself.** The operator summoned the panel to do something in it,
  usually pick a row, so it should be immediately keyboard-navigable, the same
  reasoning `Ctrl+F`'s find bar already uses. A panel that opened on the width
  rule below was not summoned by anyone, and taking the cursor out of the box
  someone is typing in because a window got wider is a different thing
  entirely: that one appears without touching focus.
- **On a terminal at least 80 columns wide, the panel opens itself.** 80 is
  what a terminal is unless someone changed it, and a wide screen with half of
  it blank and a `Ctrl+G` to press on every launch is waste. The split is
  "58%, but never leave the column beside me less than 40 columns", capped at
  74 because past that a contact list is padding while the conversation next
  to it could use the space. Below 40 + 24 there is no useful split and the
  panel takes the pane instead — on a 40-column terminal you cannot have both,
  and half a contact list beside a two-character message box is worse than
  either alone. **CSS cannot express any of that** (there is no arithmetic to
  relate a width to a sibling's minimum), so it lives in
  `kissterm/ui/slideouts.py` and is applied on resize; the `width` in
  `styles.py` is a starting value only. `Config.slideouts_auto_open` turns the
  whole behaviour off.
- **Once the operator has opened or closed it by hand, the width rule stops
  deciding.** Otherwise dragging a window wider re-opens a panel someone just
  closed on purpose.
- **Escape closes it**, checked after anything else already using Escape on
  that pane (on the Terminal pane the suggestion list goes first, then the
  find bar) so the key's meaning stays unambiguous: close whichever thing is
  actually open, one per press.
- **Picking a row from the panel closes it — but only a panel that was
  summoned.** When the pane's whole point is to show something *else* once a
  contact is chosen, a panel the operator just called up is covering the
  thing they wanted to see, so it gets out of the way. A panel that opened
  itself on a wide terminal is part of the layout instead, and closing that
  on a pick would be taking away something they never asked for. One flag
  (`SlideOut.summoned`) decides which, so the two panes cannot disagree.

### A second tab strip inside a pane

The APRS pane carries one conversation per tab, plus an "All" tab
(`#aprs-convo-tabs`). That puts two rows of tabs on one screen, which is the
whole design problem: two navigations that look identical are not a
hierarchy.

- **The inner strip reads as subordinate to the F-key bar.** Muted text for
  its inactive tabs, the accent kept for the active one, and its underline
  bar dimmed to `$panel` — the accent-coloured bar stays the property of the
  tab bar at the top of the screen. Textual's generic `Tabs Tab.-active`
  rule would otherwise make the two identical.
- **The always-available view is left-most and active at launch.** "All" is
  where the pane opens, so an operator who has picked nothing is not looking
  at an empty viewer, and it is where closing the last conversation lands.
  It cannot be closed.
- **Tabs open on demand, never on a schedule and never at launch**: picking
  a contact, sending to a callsign, or receiving a message **addressed to
  this station**. A message between two other stations opens nothing — it is
  still recorded and still visible in "All", which doubles as a channel
  message monitor, but it is not mail anybody here has to answer.
- **A tab that opens itself does not steal the view**, the same rule the
  slide-outs follow: an arriving message must not move the screen out from
  under someone part-way through a reply to a third station.
- **Unread is marked twice, on purpose**: `*` in front of the callsign, and
  `$warning` colour. The asterisk is what makes it readable for anyone who
  cannot see the colour, and the colour is what makes it findable across a
  dozen tabs; either alone is half a notification. The same pair marks the
  callsign in the contacts table, so the two markers for one fact read as
  one marker. Activating the tab clears both.
- **Closing a tab is `Ctrl+W` from anywhere on the pane, the small `X` at
  the end of the tab row, or `Delete` on the focused strip** (shown in the
  Footer like every other panel key). The `X` is one text cell, not a
  `Button`: a bordered button beside the strip was three rows tall and was
  called "unnecessarily huge" on a real screen. The row, `X` included, is
  hidden until there is a second Terminal session.

**The Terminal pane's session strip (`#terminal-session-tabs`) is the same
recipe, requested directly ("we'll be doing that with the packet terminal
soon") for multiple simultaneous connections, with three deliberate
differences from the APRS strip above** — see `kissterm/ui/terminal_pane.py`'s
module docstring for the full reasoning:

- **No "All"-equivalent, and no strip at all below two sessions.** A
  conversation strip always has somewhere useful to land; a terminal with
  one connection (or none) looks exactly like it always has — there is no
  channel-monitor view for a private, point-to-point session to fall back
  to, so a lone session simply has no tab shown at all.
- **A tab is never evicted to make room for a new one.** APRS's cap discards
  the least recently read conversation, which is fine — the history is still
  in `ConversationStore`. A terminal tab owns a LIVE link with a transcript
  file and timers still running; silently disconnecting it to free a slot
  would throw away an open conversation, so the cap (`MAX_TERMINAL_TABS`)
  refuses a new connection instead of evicting an old one.
- **Closing a connected tab is two `Delete`s, not one.** The first sends the
  disconnect and leaves the tab showing it happened; the second, once the
  tab reads DISCONNECTED, removes it. A single keystroke that did both would
  erase the "*** Disconnecting" note before anyone could read it — the same
  reasoning that keeps a beacon or a disconnect from ever being silent
  elsewhere in this app.

- **The menu headings are always on the top row** (Session, APRS, View,
  Help), as Midnight Commander's are, right of Textual's palette icon. A
  click opens that heading; F10 opens the one for the tab in front. The open
  menu draws its own bar at the same columns, so nothing moves. Esc, F10 or
  a click anywhere outside the open list closes it: an operator who opened
  it with the mouse has a hand on the mouse (2026-09-24).
- **A click opens what is safe to open; a click never transmits.** One
  click on a message shows it in the reader, as Enter does. One click on
  an Address Book entry only selects it, because opening it dials:
  double click or Enter (2026-09-25).
- **Send/Receive (G) does not move the operator.** It stays on the Mail
  tab: a toast when it starts, its progress in green in the status bar
  while it runs ("Sending 1 of 2", "Receiving 2 of 4"), a toast with the
  outcome. The session itself is in the Terminal tab for
  anyone who wants to watch (section 6, "Where a message goes").

---

## 6. The bottom two rows

```
 ^T TX  ^N Connect  ^G Book  ^R Reconnect  ^F Find  ^Q Quit  F10 Menu            <- Terminal Footer
 192.168.1.40       N1ABC-1       disconnected       LOGGING             <- status
```

Illustrative, not literal: which keys fit is a function of terminal width
(see section 5's Footer rules). `F10 Menu` is pinned to the right (F1 is
in the tab row, not here); the keys before it are dropped from the right as the
terminal narrows, and `^D Disconnect` joins them only while there is a
session to end. `^T TX` leads on the tabs where a key can transmit (Mail,
Bulletins, Files, Terminal, APRS) and is left out on Heard, Monitor and
Settings, where nothing does; Ctrl+T still works there, and `TX OFF` in
the status bar is always in view (`commands.TRANSMITTING_TABS`).

- **Footer above, status below.** Keys you might press come first, reading top
  to bottom; the passive readout comes last.
- Both live in one bottom-docked container. Docking each separately lands them
  in the **same region** and the Footer paints over the status bar — `Footer`
  sets `dock: bottom` in its own default CSS regardless of yield order.
- **Status fields spread across the full width** (`Table.grid`, first
  left-anchored, last right-anchored). A joined string bunches at the left
  and leaves a wide terminal mostly blank. **Each field is as wide as its
  text; only the spare room is shared out.** Equal shares cut a long field
  short while short ones sat in space ("Checking for" without "mail",
  operator 2026-10-02); a field that still does not fit ends in an
  ellipsis, never a hidden second line.
- **Only what changes, or what the operator must not miss.** No TCP port
  on the transport (the host says which TNC), no heard count (the Heard
  tab has it), no app name (the title bar has it): every field taken away
  is room for a job's progress (operator, 2026-10-02).

### Where a message goes

Every message the app raises on its own goes to exactly one of three
places, chosen by how long it stays true. **Never insert a line above or
inside a pane's content to report status**: it pushes the content down
while it shows and pulls it back when it goes, and the operator loses
their place (Send/Receive's line above the message list, removed 2026-09-25).

| What it is | Where | Examples |
|---|---|---|
| A state that lasts (seconds or more) | Status bar field, removed when it ends | `TX OFF`, `ANSWERING`, `BEACON`, `REMOTE 1`; in green, `Receiving 2 of 4` |
| An event: something started, finished or failed | Toast (`notify`); `warning` or `error` severity for a problem | "Connecting to WS1EC-2 to send and receive mail...", "No new mail", "Send/Receive stopped: ..." |
| The record of a session | The session's transcript (Session > Transcripts); kissterm.log when there is none | `Mail: Reading 1 of 3: #2578 ...`, `Connecting to WS1EC-2`, `Transmit enabled automatically for: ...` |

- **The Terminal holds only the session itself:** what the far end sent
  and what was sent to it (typed lines, login-script and hop lines,
  Send/Receive's commands). Nothing kissterm says about itself -- no
  banner, no `***` notes (operator, 2026-10-02: "I again don't want
  anything in there that didn't come from the node";
  `tests/pilot/test_app_mounts.py`). A fact a note used to carry goes to
  the status bar, a toast, or the transcript, by the table above.
- **No redundancy between them.** A state is in the status bar *or* a
  toast, not both: a job's start and outcome are toasts, its progress is
  the status-bar field. The transcript may repeat either, because it is
  the record, not a notice.
- **Status-bar fields are a few words.** A standing mode is one upper-case
  word or two (`TX OFF`, `BEACON`). **A job the operator started shows its
  progress in words, in bold `$success` green** (`Sending 1 of 2`,
  `Receiving 2 of 4`, `Checking for mail`): a count says how far it has
  got, where a label like `GET MAIL` said only that something was running
  (operator, 2026-09-25). A sentence belongs in a toast or the log; a long
  field is truncated in its share of the row.
- **A toast says what to do next when there is something to do** ("the
  Monitor tab (F8) shows what went out and what came back"), and is not raised for anything the operator
  cannot act on or would not miss (section 1).
- **One event, one toast.** When a job drives another part of the app
  (Send/Receive dialing through the connect path), the job owns the
  toasts: the part it drives hands back its reason (`report`) and folds
  its own news in (`announce`: "Connecting... Transmit ENABLED") instead
  of raising a second toast beside the job's (operator, 2026-10-02: "I got
  two each time something happened";
  `tests/pilot/test_get_mail.py::test_a_failed_g_is_one_toast_at_each_end`).
- **A toast stays up at least 10 seconds** (`KissTermApp.NOTIFICATION_TIMEOUT`;
  pass `timeout` only to make one longer). A job's start and outcome often
  arrive as a pair, and at 4 seconds they went by before they could be
  read (operator, 2026-10-02; `tests/unit/test_toast_dwell.py`).
- **The Terminal record is for sessions only.** Something the app learns
  on its own that is not about a session (a newer version on GitHub) is a
  toast, never a Terminal line: an operator who stays on Mail never sees
  the terminal (operator, 2026-10-02: "I don't want extra noise in the
  terminal").
- **Pane-owned text is not status.** A field's validation error beside the
  field, a Settings banner listing config.toml problems, and a pane's own
  summary strip (APRS weather) are content of that pane, laid out with it,
  and may stay.

---

## 7. Text and typography

- **ASCII for kissterm's own chrome.** No emoji anywhere, ever.
- **Sentence case** for labels and help; not Title Case, not ALL CAPS. Caps are
  reserved for things that are literally uppercase on the air (callsigns,
  `ANSWERING`, node commands).
- **Dates are ISO 8601** (`2026-09-05`), never locale order. `03/04` is March
  4th to an American and April 3rd to nearly everyone else, and packet is an
  international medium.
- **UTC is always marked** — `Z` on a 24-hour clock, `UTC` on a 12-hour one.
  Local time is unmarked, the convention a paper log already uses.
- **Independent things get independent controls.** Local time, UTC time and
  the date are three toggles, not an either/or enum with the date bolted on
  beside it. The first cut modelled them the second way and made "show
  nothing" and "show only the date" unreachable — if two settings are the same
  *kind* of choice, they get the same *kind* of control.
- **Never print one value where it could belong to two things.** With both
  clocks shown, a single date belongs to only one of them, so on the nights
  they disagree each reading carries its own. The display gets wider exactly
  where the ambiguity exists.
- **Remote text is never trusted.** Everything from the air goes through
  `monitor.sanitize()` before it reaches a widget. See `AGENTS.md`.
- **Never word a callsign as if it were verified.** AX.25 authenticates
  nothing, so every callsign on screen is asserted by whoever transmitted it.
  "from W1AW" reads as fact; where it matters -- a file's uploader, a
  message's sender -- say "claimed". The heard list and monitor are read as
  observations, which is honest; anything that looks like attribution is not.

---

## 8. Writing the words

The interface text is part of the design, and it does the same job the
docstrings do: explain *why*, at the moment it matters.

- **Say when a setting takes effect, if not on Save** — "next connection" /
  "needs a restart". "I changed paclen and nothing happened" is a support
  question worth pre-empting. Nothing is printed for a field that applies on
  Save: "takes effect now" beside every field was noise (2026-09-24).
- **Explain the trade-off, not just the field.** "A shorter frame gives QRM
  and fading less to hit" tells an operator how to choose; "Maximum frame
  length" does not.
- **Never overstate what is known.** "no traffic seen yet", never "not a TNC" —
  a silent TNC and a wrong port look identical until a frame arrives.
- **Warn where the cost is paid.** Airtime, unattended transmission and
  network scanning all get told to the operator at the point of the action.
- **A dialog is not a docstring.** Settings is a page the operator visits
  occasionally and can afford to read; a modal (Connect, Address book entry)
  sits between the operator and a task already in progress and must be
  readable in one glance. Keep dialog labels and placeholders to what fills
  the field correctly — one short example, not a parenthetical essay:
  "Node hops, e.g. N1QFY, AB1KI-15 (optional)", not "N1QFY, AB1KI-15
  (optional -- node hops, when no digipeater reaches it)". The fuller
  explanation belongs in this file, in AGENTS.md, or in a docstring — never
  squeezed into a widget the operator has to read under time pressure.
- **A dialog's title names what the operator started**, not the part
  being asked about. A question that interrupts G on All Inboxes is titled
  "Send and Receive All Inboxes" and says in one sentence why it is asking;
  "Winlink gateway" there left the operator guessing why Winlink came up
  at all (2026-09-27).
- **A list of saved things ends with New.** Every dropdown of Address Book
  contacts, saved logins or saved scripts has "New radio contact...",
  "New Telnet/SSH contact...", "New login..." or "New script..." as its
  last choice. It opens that thing's own editor over the current screen;
  saving selects what was made, cancelling puts the old choice back. The
  operator never has to leave a form to create what it asks for
  (2026-09-27: "I can't go to the address book to set it up from here").
- **A login is one thing: a username and a password.** Anywhere a remote
  system signs in (a BBS prompt, a node's user: and password:, SSH), the
  form offers one saved-login list, never a username box beside a
  password box, and never a text area the password is typed into. The
  login editor asks Name, Username and a masked Password, and says where
  the password is kept (the system keyring, else config.toml). Only
  Winlink's account password, which has no username of its own, is a
  masked field by itself (2026-09-28: "I want to save a username and a
  password, and have the password securely saved").
- **A placeholder must stand alone.** It is the only text some operators will
  ever see in that field, so "(type your own below)" next to an unlabeled
  blank box is not a placeholder, it's a puzzle. Every empty `Input` or
  `TextArea` says, by itself, what belongs in it, and does not require
  reading a sibling control to make sense.

---

## 8a. Phone and browser (the remote control)

The Flet client in `kissterm/client/ui/` follows the platform, not the
terminal: Material 3, touch first. Sections 2-6 are about the terminal
and do not apply there; these do.

- **A swipe never transmits.** A swipe on a station's row (`stations.py`)
  opens a sheet saying what would happen ("Connect to W1AW-7?") and the
  row springs back; only the sheet's own button acts. **A swipe on a
  message deletes it** (restores it in Deleted), since nothing transmits
  (operator, 2026-10-06): it takes half the row's width, sliding back
  before letting go cancels, and the note after it has **Undo**. Swiping between pages
  changes the page and nothing else. A phone in a pocket swipes by
  accident; the radio must not key because of it
  (`tests/unit/test_client_ui.py`).
- **Anything that puts a frame on the air asks first** in a sheet:
  connect, disconnect, Send/Receive, Get bulletins and files, Send
  position, Send beacon (which asks Packet or APRS). **Where there is more than one way, the sheet
  offers each** (By Internet, By radio: `sheets.choose`), the usual one
  last and filled, never a second screen. Typing a line and pressing Send is
  already the deliberate commit, as Enter is in the terminal.
- **The transmit switch is always in the top-right corner**, outlined
  "TX OFF", filled red "TX ON". Turning it off never asks; turning it on
  does, with a heavy haptic. Same rule as the terminal: the gate is never
  silent.
- **Five places**, in this order: Mail, Messages, Terminal (once
  Sessions), Stations, More (operator, 2026-10-06); the app opens on
  the first. Code names them (`shell.MAIL` ...), never by number. A bottom
  NavigationBar below 720 px wide, a NavigationRail from 720 up. The one
  difference: Mail's sections (Mail, Bulletins, Files, the terminal's
  three tabs) are a switch at the top of the Mail page on the phone and
  a rail place each from 720 up, where there is room (operator,
  2026-10-06). A section opens where it was left, else on All Inboxes
  (Mail, as the terminal's tab does), its Inbox or first folder, never
  on Deleted, which is listed last.
- **One sheet shape** (`sheets.sheet`): drag handle, title, body,
  buttons at the right with the commitment last and filled. Dragging a
  sheet away is Cancel. A question from the station is the same sheet.
- **Notices are floating snack bars**, red for an error, never a dialog
  that blocks the page.
- **Session text is the 0xProto mono font**, Regular and its own Bold
  (two families, never a thickened Regular), bundled; the station has
  already filtered it (`serve/wire.py`), and the client only lays it out.
- **The session is a terminal panel**, dark with grey text by default
  whatever the app's theme. More > Terminal chooses Dark or Light and a
  text colour (Grey, Contrast, Green, Amber, Cyan, each with a shade for
  either background) for this device only, kept in its preferences
  (`text.Look`). On a light panel the colours a node meant for a dark
  screen are drawn darker. The operator's own lines are bold, in a blue
  accent that is none of the text colours.
- **The terminal gets the height** (operator, 2026-10-06). Nothing above
  the session repeats its name: the tab strip names each session with an
  icon for its state (linked, unlinked, hourglass) and ends in Connect,
  never a floating button, which would sit on Send where the thumb
  already is. **Disconnect is a chip beside the transmit switch**, on
  Terminal while the session shown is connected, and **Reconnect** takes
  its place once that session has dropped (not while it is still
  connecting: Cancel is on its hourglass).
- **A connect shows at once.** Terminal comes to the front as soon as it
  is asked for, and while the station is dialling, an hourglass lies
  over that session with Cancel. Cancel needs no confirming: it only
  stops transmitting. Nothing waits on the station's answer with the
  screen frozen.
- **A long job shows it is still going**: Mail's Send/Receive button
  turns and its progress line counts dots while a run is under way, and
  a tap on the turning button cancels it without a sheet (stopping is
  always safe).
- **A reader's actions are icons on one row under its title**: Reply,
  Reply all (only when there is someone else), Reply with quote, then
  Delete (Restore in Deleted), last as the one that removes. Writing is
  a full page with the commitment, Save to Outbox, filled, at the top
  right and close at the top left, which asks before throwing typed
  text away.
- **A message's routing is one small line under the date**, "Routed
  W1BKW > WS1EC" (the BBSes in travel order, no explanation: operator,
  2026-10-06, "Routing takes more space than the message"); a tap (T in
  the terminal) shows the `R:` lines under it. The lines stay folded
  because a recipient once took one for the sender's address.
- **A title names the place, not the station**: "APRS messages", not
  "KC1JMH Messages"; the callsign is in More. Where a place's label is
  ambiguous on its own, the title says which kind: Mail is titled "BBS
  Mail" (operator, 2026-10-06).
- **A place's second action is a mini button stacked above its main
  one**, icon only, right edges in line so both hug the screen's edge (Mail's Write pencil over
  Send/Receive; operator, 2026-10-06: "drop the text label"), never a
  labelled button in the toolbar.
- **What the operator acts on comes first**: Stations opens on Contacts,
  Heard second.
- **The map is a page of Messages** (Map beside Send position; operator,
  2026-10-06), not a sixth place: drag pans, pinch and the wheel zoom,
  with +, - and show-everything buttons stacked at the top right for a
  hand without a second finger. A tap on a point opens a panel at the
  bottom (what it reported, distance and bearing, last heard, comment,
  Message for a station); nothing on it transmits. This station's name
  is the one label never crowded out. **A long press places an object**
  (operator, 2026-10-06): the object form at that spot, a full page like
  Write; one of this station's objects has Move (a banner, then a long
  press where it goes) and Kill on its panel. Send and Kill ask first.
- **The app's own icon**: a `>_` prompt and an antenna on the dark
  terminal panel (`scripts/generate_web_icons.py`), for the loading
  splash, the browser tab and the home screen, never Flet's.

---

## 9. Changing any of this

1. Edit `kissterm/ui/styles.py` — never inline `styles.` assignments in a pane,
   which are invisible from the stylesheet and produce half-applied themes.
2. Run `.venv/bin/python scripts/generate_screenshot.py` and **look at the
   result.** Every design bug in this project's history — an invisible status
   bar, a Footer painting over it, an empty heard table, a 3D button, duplicate
   F-key labels — passed the entire test suite and was caught by looking at a
   picture.
3. Add a geometry or binding regression test for anything structural
   (`tests/pilot/test_app_mounts.py` has the existing examples: region
   comparisons, binding-visibility checks, background-token comparisons).
4. Update this file if the rule itself changed.
