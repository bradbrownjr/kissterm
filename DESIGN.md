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
| `$accent` | The active/current thing: selected tab, section headings |
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

**Function keys are tabs. Ctrl sequences are actions and modals.** No
exceptions; the one time a modal took a function key (the command reference on
F5, then F6), it broke the "F*n* is the *n*-th tab" pattern the moment another
tab existed to expect it.

- **A tab's key is printed in its label, key first** — `F1 Terminal`, the way a
  menu shows an accelerator. Never `Terminal (F1)`.
- **Tabs are ordered by how often an operator visits them, not by when they
  were built**: `F1 Terminal  F2 APRS  F3 Heard  F4 Monitor  F5 Settings`.
  Terminal and APRS are where the work happens; Monitor is a diagnostic and
  Settings is a place you leave again, so both sit to the right — requested
  directly, "putting useful stuff to the left of Monitor and Settings". The
  `TabPane` **ids never move with the labels** (`terminal`, `aprs`, `heard`,
  `monitor`, `settings`): every `active == "aprs"` check and every
  `action_show_tab` caller addresses a pane by id, so a future reordering is
  three labels and three bindings, not a search through the app.
- **A tab's key never also appears in the Footer.** That put the same words on
  screen twice, in two different corners. Register the binding with
  `show=False`.
- **The Footer is for non-tab actions only** — TX, Connect, Disconnect,
  Contacts, Commands, Beacon, Callsign, Find, Clear, Transcripts, Quit,
  palette.
- **`Ctrl+1..5` are unlabelled fallback aliases** for terminals that intercept
  function keys.
- **A panel's own keys go in the Footer too, never in a hint line under its
  buttons.** Textual's `Footer` renders whatever the *focused* widget binds
  with `show=True` and repaints as focus moves, so a table that binds
  Insert/F2/Delete/Enter already has a context-aware shortcut bar — printing
  the same four keys as a `Static` beneath the buttons is the duplication the
  first rule in this section exists to prevent, in a different corner again.
  It also pushed those buttons a row lower than every other pane's, which is
  what got it reported: the buttons should line up across the Terminal, APRS
  and Address Book panes. A modal screen has to `yield Footer()` itself to
  get this.
- **The Footer shows the highest-priority prefix of that list that fits the
  terminal width, not all of it truncated.** Textual's own `Footer` is a
  horizontally-scrollable container with its scrollbar suppressed — at an
  ordinary 80-column terminal the full list above needs about 140 columns, so
  roughly a third of it used to be scrolled off past the right edge with no
  on-screen sign anything was missing (reported directly from a real
  session). `KissTermFooter` (`kissterm/ui/app.py`) keeps the essential
  mid-contact cluster — TX, Connect, Disconnect, Contacts — and drops the rest
  in priority order as the terminal narrows, ranked by
  `kissterm/ui/commands.py`'s `ACTION_META`. A narrower terminal means fewer
  keys shown, never a key silently unreachable: the full list is always one
  `Ctrl+P` away regardless of width.
- **`Ctrl+P` is a real, searchable key reference, not just Textual's small
  built-in System Commands.** `commands.KeyBindingsProvider` walks every
  action in `KissTermApp.BINDINGS` — visible and `show=False` alike, so
  Ctrl+B/Ctrl+D's hidden legacy-terminal fallbacks and anything the Footer
  currently has no room for are still one search away — and offers them
  fuzzy-searchable, grouped by the same `ACTION_META` categories (Connection,
  Transmit, Terminal, Contacts, Panes, App).
- **`Ctrl+Shift+B` is context-aware by active tab, same dispatch shape as
  `Ctrl+G`'s slide-outs.** On the Terminal pane (or any tab but APRS) it is
  unchanged from before: send one BTEXT beacon right now. On the APRS pane
  it instead toggles `config.aprs.enabled` -- the quick-access equivalent
  of the Settings checkbox plus Save, so an operator does not have to open
  Settings just to turn position beaconing on. It never arms the transmit
  gate (a bare keystroke with no confirmation and no named target must
  not, per AGENTS.md's transmit-gate rules -- this is architecturally the
  same case as the manual BTEXT send it shares a key with) and, per
  AGENTS.md's beaconing section, turns the plain-text timer off if it was
  running when APRS beaconing is turned on this way -- the two are not
  meant to run at once. The Footer label stays "Beacon" on every tab, the
  same as `Ctrl+G` stays labelled "Contacts" everywhere even where it has
  nothing to do.
- **`Ctrl+R` is context-aware by active tab, third use of the same dispatch
  shape.** The key asks one question — "what can I say to the thing I am
  talking to?" — and only the source of the answer changes. On the Terminal
  pane (and every tab but APRS) it is unchanged: the shipped node command
  reference from `kissterm/nodes/`. On the APRS pane it opens the gateway
  service picker from `kissterm/aprs_services/`, scoped to whoever is in the
  "To:" field. Both fill an input and **neither sends** — the same rule that
  has always governed the terminal's reference. The Footer label stays
  "Commands" on every tab, like `Ctrl+G`'s "Contacts" and `Ctrl+Shift+B`'s
  "Beacon".
- **Ceiling: F1–F10.** Originally set at F8 (some terminals were assumed
  unreliable past it), raised once F9/F10 were confirmed working in practice
  — see `docs/ROADMAP.md` P10. Five tabs exist, three more are planned
  (Mail, Bulletins, Files) — an eleventh needs a different scheme entirely,
  not an eleventh function key, since F11 is "toggle fullscreen" in enough
  terminals and window managers to rarely reach the application at all.
- **Never bind a bare printable key globally.** A focused `Input` swallows it,
  so the binding works inconsistently depending on focus — and this is a
  terminal, where typing a character must always just type that character.

### Slide-out panels

A contact list that a pane needs but does not want permanently on screen —
the Terminal pane's Address Book, the APRS pane's contacts list, Mail's own
contacts panel once that tab exists — is a collapsible column docked on the
**right** edge of its pane, not a tab and not a modal.

- **One key opens or closes whichever slide-out belongs to the active
  pane**: `Ctrl+G`. The key's meaning does not change tab to tab; a tab with
  no slide-out (Monitor, Heard, Settings) just has nothing for it to do.
  Picked only after checking every existing binding —
  `kissterm/ui/app.py`'s `Binding("ctrl+g", ...)` records the full check —
  because `Input`'s own built-in bindings already claim more of the alphabet
  (`ctrl+a`, `ctrl+shift+a`, `ctrl+e/w/u/k/x/c/v/d`) than is obvious until
  you look, and a key silently shadowed by a focused `Input` is worse than
  an unfamiliar one, per the `Select.BLANK` lesson in `AGENTS.md`.
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
  that pane (the Terminal pane's find bar goes first) so the key's meaning
  stays unambiguous: close whichever thing is actually open.
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
- **Closing a tab is `Delete` on the focused strip**, shown in the Footer
  like every other panel key. Not `Ctrl+W` — `Input` already claims that for
  delete-word and the compose box is right there.

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
 ^t TX  ^n Connect  ^D Disconnect  ^G Contacts  ^r Commands  ^B Beacon  ^k Callsign ...  <- Footer (80 cols)
 kissterm 0.1  |  192.168.1.40:8001  |  N1ABC-1  |  heard 6                             <- status
```

The Footer row above is illustrative, not literal — which keys actually fit
is a function of terminal width; see the new bullet above. At 80 columns
that is roughly the prefix shown; a wider terminal keeps adding Find, Clear,
Transcripts, Quit and the `^p` command-palette chip in the same priority
order.

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
