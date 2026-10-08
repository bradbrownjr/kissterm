# AGENTS.md — kissterm/client

The remote client (ROADMAP P7a M8): the other end of `docs/PROTOCOL.md`.

1. **Talks only the protocol.** Never import `kissterm.core`, `ui`,
   `serve`, `transport` or `ax25` (`tests/unit/test_client.py`): it runs
   on a phone with no station in it, and has no path around the gate.
   `kissterm.geo` is allowed: the map's outlines and arithmetic, with
   no station in them (`tests/unit/test_map.py` keeps it that way).
2. **`connection.py` and `state.py` have no UI** and are tested against a
   real server on a loopback station. Widgets read `StationState`; they
   never hold station state of their own.
3. **Show what the station said, not what was asked**: a typed line
   appears when `LineSent` comes back. Never retry a command after a
   reconnect (a line sent twice is transmitted twice).
4. **`timer-recovery` is a connected link** (AGENTS.md section 3).
5. **Actions are one toolbar row, no floating buttons** (`ui/toolbar.py`,
   DESIGN.md 8a): tabs left, secondary actions, the primary last; words on
   every action from `WIDE` up, only on the primary below it. Never a
   second pattern for a new place.
6. **A swipe never transmits** (DESIGN.md): a row's swipe opens a
   confirmation or an editor; only a button press in that sheet sends.
7. **`ui/` is Flet 1.0** (DESIGN.md section 8a). One view per place
   (`sessions`, `messages`, `mail`, `stations`, `more`), each with
   `control`, `shown()` and `on_state(kind, data)`; `shell.py`
   owns the bar/rail, the gate button and question sheets. Every sheet
   comes from `sheets.sheet`. Flet traps, checked against 1.0.3:
   `RouteUrlStrategy` must be the enum (a string is a 500); buttons take
   `content=`; `Dropdown(on_select=)`; `TextField` sets its font through
   `text_style`; a `Dismissible` must `await confirm_dismiss(False)`.
8. **The token never stays in the address bar**: `web.py` stores it in
   the browser (`SharedPreferences`) and resets the route to `/`; a
   refused link drops it.
9. **Look at it.** A layout change is checked in a browser
   (Playwright's headless Chromium against a scratch station), not only
   by tests: sheets that shrank to their text and a centred terminal
   line both passed every test. `scripts/generate_phone_screenshots.py`
   (the `screenshots` extra; `BROWSERLESS_WS=ws://HOST:3000?token=...`
   for a browserless server, from the environment, never committed)
   makes `assets/screenshot-phone.png` and taps by name through
   Flutter's accessibility tree, so a renamed button or tooltip fails it.
   Selectable text (session lines, message bubbles) is not in that tree.
10. **The icons are kissterm's** (`scripts/generate_web_icons.py`, into
   `ui/assets/`): Flet's server looks there before its own web files, so
   `icons/loading-animation.png`, `icons/icon-*.png` and `favicon.png`
   replace Flet's by name. Re-run the script after changing the mark.
