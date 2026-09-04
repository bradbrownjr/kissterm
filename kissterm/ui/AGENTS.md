# kissterm/ui — local contract

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
| `settings_pane.py` | Read-only config read-out |
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
11. No emoji anywhere.

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
