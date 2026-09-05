# kissterm/ui — local contract

**Read `DESIGN.md` at the repo root before changing how anything looks.** It
holds the color tokens, the settings column grid, spacing, the F-key/Ctrl
split, and the text style rules. The numbered rules below are the
implementation contract; DESIGN.md is the reasoning behind them.

The Textual layer. One file per pane, so changing the monitor means opening
`monitor_pane.py` and nothing else.

Read this file plus the one pane you are changing.

## File map

| File | What it owns |
|---|---|
| `app.py` | `KissTermApp`: bindings, `compose()`, tab actions, the frame fan-out, status bar. The **only** place that subscribes to the station. |
| `styles.py` | All CSS, as `APP_CSS`. Appearance changes go here, not inline. |
| `terminal_pane.py` | Session scrollback + input line + sending |
| `monitor_pane.py` | Channel log + filter bar |
| `heard_pane.py` | Heard `DataTable` |
| `aprs_pane.py` | Placeholder; the real pane is roadmap P4 |
| `themes.py` | Theme catalog: curated ids, custom-hex builder |
| `settings_schema.py` | **Declarative** list of every editable setting |
| `settings_pane.py` | The settings form, generated from that schema |
| `dialogs.py` | `ConnectScreen` and future modals |

`kissterm/app.py` one level up is a thin shim re-exporting `KissTermApp`, so
`from kissterm.app import KissTermApp` keeps working. Leave it alone.

## The rules that will bite you

1. **One shared frame fan-out.** The station, monitor, heard table and APRS
   decoder all hang off `FrameTransport.subscribe()` via `app.py`. A frame is
   decoded **once**, in `app.py`, and already-rendered text is handed to a
   pane. Adding a second place that turns an `AX25Frame` into text is the
   mistake this rule exists to prevent — add a subscriber instead.
2. **Anything remote-supplied goes through `monitor.sanitize()`** before it
   reaches a widget. Those bytes came off the air and can carry ANSI escapes
   that repaint the screen or set the window title; a corrupt frame produces
   the same bytes by accident. `TerminalPane.write_incoming` is the sanitized
   path; `TerminalPane.log` is for text kissterm generated itself. Do not add
   a path around either.
3. **Lines to a node are CR-terminated, not LF.** Sending LF makes a BPQ32 node
   echo a spurious blank line after every command.
4. **`KissTermApp(config, station)` is injected**, never constructed
   internally. That is what lets a headless test mount the app against a
   loopback with no hardware and no real config directory.
5. **Panes reach the app through documented attributes** (`self.app.link`,
   `self.app.monitor_filter`, `self.app.heard`), never by importing each other.
   Cross-imports between panes are how one file stops being editable alone.
6. **Do not bind single letters** while the input line has focus. This is a
   *terminal*: a key that does something other than type a character into a
   live BBS session is a bug the operator will hit at the worst moment.
7. **Two bottom-docked widgets land in the same region.** Textual's `Footer`
   docks bottom; anything else docked bottom is painted over, in either yield
   order. `#bottom-bar` is one docked container holding the status bar and the
   Footer as two rows. This bug shipped once and was invisible to the tests.
8. **A pane fed by a periodic refresh needs a `TabActivated` hook**
   (`_on_tab_activated`), or it shows empty or stale content for up to one
   interval every time the operator switches to it. Same for anything painted
   only by `set_interval` -- paint once on mount too.
9. **Callbacks from a link must tolerate a torn-down widget tree.** A link
   outlives the UI: shutdown exits the app and then closes the station, firing
   state callbacks at widgets that are gone. Use `self._to_terminal(...)`,
   which no-ops, not a bare `query_one`.
10. **Generate a screenshot after any layout change**
    (`.venv/bin/python scripts/generate_screenshot.py`). Three invisible layout
    bugs passed the full suite and were caught only by looking at the picture.
    When it shows something the assertions did not, add a geometry test.
11. **Never hand-write a settings widget.** `settings_pane.py` is generated
    from `SETTINGS_SCHEMA`. Adding a setting is one entry in
    `settings_schema.py` — label, kind, help, bounds, and when it takes
    effect. A hand-built form goes stale the first time someone adds a config
    option and forgets the UI, which already happened once here.
12. **Validate everything, then save; never save partially.** A half-applied
    save leaves the operator unable to tell which values took.
13. **Say when a change takes effect** (`Field.apply`: live / connect /
    restart). Link parameters must not change under an *established* link —
    they were negotiated when it came up.
14. **`TerminalPane.send_line` is the only transmit path.** Enter and the
    Send button both route through it. Suggestions use `suggest()`, which
    fills the input and cannot send. A test asserts there is exactly one
    `link.send(` in that module -- keep it that way.
15. **Never spend airtime to populate the UI.** Command references ship as
    data (`kissterm/nodes/data/`); asking a node costs ~19 s per 2 KB at 1200
    baud. Node detection is passive -- read the banner, ask nothing.
16. **The tab bar is the ONLY place a tab-switching key is shown.** F1-F5
    (all five tabs, including Settings) are named in the tab label itself, key
    first (`F1 Terminal`, like a menu accelerator); `Binding(..., show=False)`
    keeps them registered without the Footer repeating the same word that is
    already in the tab strip above it. Only add a Footer-visible binding for
    something that is NOT a tab -- the command reference is F6, specifically
    NOT F5, because F1..F5 mapping onto "the five tabs" is the pattern an
    operator expects once F1..F4 exist, and a non-tab action squatting on the
    next number in sequence broke that the moment a fifth tab existed. If a
    sixth tab is ever added, F6 needs to move again, not the reverse.
17. **One `Button` style for the whole app** (`styles.py`, top of `APP_CSS`):
    a flat rounded border, no filled 3D bevel. Variant classes
    (`-primary`/`-error`/...) change only the border and text color, never the
    shape. A Connect, Save or Send button styled differently from the rest is
    the thing this rule exists to prevent -- it happened once already.
18. **The active tab gets bold accent text and the underline bar, never a
    solid fill.** Textual's default fills the focused tab strip's active tab
    with a "block cursor" background, which reads as a heavy rectangle next
    to the flat panels everywhere else. Overridden in `styles.py`.
19. **A widget's own `DEFAULT_CSS` can override yield order.** `Footer` docks
    itself to `bottom` no matter where it is written in `compose()` -- getting
    it to sit above the status bar took `#bottom-bar Footer { dock: top; }`,
    not reordering the `yield` statements. Check a widget's own default CSS
    before assuming compose-order controls layout.
20. **The status bar is a `rich.table.Table` grid, not a joined string.**
    `_status_row` in `app.py` builds one equal-ratio column per field so the
    content spreads across the full width and re-flows on resize; a hand-
    joined `"  |  ".join(parts)` string looks fine narrow and leaves most of a
    wide terminal blank. Add a field by appending to `parts` in
    `_refresh_status` -- the layout adapts on its own.
21. **A widget updated with a Rich renderable is not `str()`-able the way a
    plain string one is.** `Static.render()` returns a Textual `Visual`
    wrapper once the content is anything but a string; reaching into its
    private `_renderable` is exactly the internals-coupling that breaks on
    the next Textual upgrade. In tests, read `widget.render_lines(region)`
    instead -- the same strips the terminal itself would draw.
22. **Never invent a palette.** Every `THEME_CATALOG` entry in `themes.py`
    must be a real `textual.theme.BUILTIN_THEMES` key, checked by test. A
    family with no upstream light (or dark) variant simply does not offer
    one -- point at `SUGGESTED_LIGHT_ALTERNATIVES` instead of guessing hexes.
23. **A `Select` widget raises if set to a value outside its own options.**
    Any config-file value reaching a "choice" field in the Settings pane goes
    through `_set_select_value`, which falls back instead of crashing. This
    already broke once on a stale `theme` value.
24. **`write_incoming` has two filters and neither one is optional.**
    `remote_color` chooses between `ansi.to_text` (keeps allowlisted SGR) and
    `sanitize` (keeps nothing). It does NOT choose whether filtering happens.
    Both remove cursor movement, erase, OSC and DCS unconditionally. A future
    "just show the raw bytes" option is not a setting, it is a defect.
25. **`linkify` takes a `Text` as well as a `str`**, and applies the link
    style as a span so it does not flatten the colours underneath. The target
    is always the matched substring of `Text.plain` itself -- displayed text
    and destination cannot differ by construction. Never parse a link out of
    remote markup; OSC 8, the terminal hyperlink sequence, is exactly the
    "display one address, open another" attack and is stripped with the rest
    of OSC.
26. **`app.apply_runtime_settings()` is the one hook the Settings pane calls
    after a save.** Anything that needs *doing* rather than storing --
    restarting the beacon, pushing `remote_color` to the pane -- goes behind
    it. Do not add a second feature-specific call in `settings_pane.py`; that
    is how the pane starts knowing what the settings mean.
27. **Restart the beacon, never mutate a running one.** A live edit leaves a
    window where the interval and the text disagree about what goes out, and
    what goes out is transmitted under the operator's callsign.
28. **The transcript is owned by the app, not the pane.** It records what
    crossed the *link*; the pane is one of the things watching that. The
    terminal pane's only involvement is calling `app.log_sent` after
    `link.send` -- which is not a second transmit path, and rule 14 still
    holds.
29. No emoji anywhere.

## Testing

```bash
.venv/bin/python -m pytest tests/pilot/ -q
```

`tests/pilot/test_app_mounts.py` is the pattern: call
`kissterm._isolate.isolate()` **before any other kissterm import** (a hard repo
rule — see `kissterm/_isolate.py`), build a loopback transport from
`tests/loopback.py`, then `async with app.run_test(size=(120, 40)) as pilot`.
`app.save_screenshot(path)` inside `run_test` exports an SVG of the render,
which is the closest thing to eyeballing a live TTY.

Gotcha: after `pilot.press`, a `@work` action needs `await pilot.pause()` plus
a short `asyncio.sleep` before its result is observable.
