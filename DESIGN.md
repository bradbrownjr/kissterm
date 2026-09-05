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
- **A tab's key never also appears in the Footer.** That put the same words on
  screen twice, in two different corners. Register the binding with
  `show=False`.
- **The Footer is for non-tab actions only** — Connect, Disconnect, Callsign,
  Commands, Quit, palette.
- **`Ctrl+1..5` are unlabelled fallback aliases** for terminals that intercept
  function keys.
- **Ceiling: F1–F8.** F9+ are not reliably delivered by every terminal, so
  **eight tabs is the practical maximum**. Five exist, three are planned
  (Mail, Bulletins, Files) — a ninth needs a different scheme, not a ninth
  function key.
- **Never bind a bare printable key globally.** A focused `Input` swallows it,
  so the binding works inconsistently depending on focus — and this is a
  terminal, where typing a character must always just type that character.

---

## 6. The bottom two rows

```
 ^q Quit  ^n Connect  ^d Disconnect  ^k Callsign  ^r Commands   <- Footer
 kissterm 0.1  |  192.168.1.40:8001  |  N1ABC-1  |  heard 6     <- status
```

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
