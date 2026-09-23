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
  a form row is one consistent height regardless of which control it holds.
- **Never use Textual's default `border: tall`** on an interactive widget. It
  renders as a raised 3D bezel that belongs to a different design era than
  everything else here.

---

## 4. Layout and spacing

### The settings column grid

Every settings row is the same three columns, so the page aligns vertically
instead of each row finding its own edges:

```
|<--- 26 --->|<-------- 46 -------->|<--- 20 --->|
 Callsign      [ N1ABC-1          ]   next connection
 ^label        ^control               ^apply note
                ^help text hangs here (indent 27)
```

- Controls are a **fixed** width, not `1fr`. A control that stretches with the
  window makes the third column drift and the page lose its alignment.
- **Help text hangs under the control (indent 27 = label 26 + 1), not under the
  label.** Two numbers that must agree; Textual CSS has no arithmetic to tie
  them, so changing one means changing the other.

### Measure

**Body text is capped at 92 columns.** A help line spanning an ultrawide
terminal is technically readable and practically not — the eye loses the line
start on the way back. Applies to section notes, help text and banners.

### Vertical rhythm

- 1 blank row between fields, 2 above a section heading.
- **Section headings carry a rule** (`border-bottom: solid $panel`). With bold
  accent text alone, sections blur together while scrolling.
- Settings deliberately favors **readability over density** — it is a form the
  operator visits occasionally. The operational panes (Monitor, Heard) go the
  other way: those are dense on purpose, because scanning a lot of frames
  quickly is the entire job.

### Information order

**Identity first, then hardware, then tuning.** Settings opens with Station
(callsign, aliases) — the first thing a new operator sets and the most often
changed later — then Transports, then everything else.

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
   are Tab, Enter, Backspace, Esc and LF; Ctrl+C, Z and `\` are signals;
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
   restores from Deleted.
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
the Terminal pane's Address Book, the APRS pane's contacts list, Mail's own
contacts panel once that tab exists — is a collapsible column docked on the
**right** edge of its pane, not a tab and not a modal.

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

---

## 6. The bottom two rows

```
 ^T TX  ^N Connect  ^G Book  ^R Reconnect  ^F Find  ^Q Quit  F10 Menu            <- Terminal Footer
 kissterm 0.1  |  192.168.1.40:8001  |  N1ABC-1  |  heard 6                    <- status
```

Illustrative, not literal: which keys fit is a function of terminal width
(see section 5's Footer rules). `F10 Menu` is pinned to the right (F1 is
in the tab row, not here); the keys before it are dropped from the right as the
terminal narrows, and `^D Disconnect` joins them only while there is a
session to end.

- **Footer above, status below.** Keys you might press come first, reading top
  to bottom; the passive readout comes last.
- Both live in one bottom-docked container. Docking each separately lands them
  in the **same region** and the Footer paints over the status bar — `Footer`
  sets `dock: bottom` in its own default CSS regardless of yield order.
- **Status fields spread across the full width** (`Table.grid`, equal-ratio
  columns, first left-anchored, last right-anchored). A joined string bunches
  at the left and leaves a wide terminal mostly blank.

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

- **Say when a setting takes effect** — "takes effect now" / "next connection"
  / "needs a restart". "I changed paclen and nothing happened" is a support
  question worth pre-empting.
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
- **A placeholder must stand alone.** It is the only text some operators will
  ever see in that field, so "(type your own below)" next to an unlabeled
  blank box is not a placeholder, it's a puzzle. Every empty `Input` or
  `TextArea` says, by itself, what belongs in it, and does not require
  reading a sibling control to make sense.

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
