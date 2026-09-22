"""Show what key names this terminal actually delivers to Textual.

Run it in the SAME terminal, tab and multiplexer you run kissterm in -- that
is the whole point. What a key resolves to is decided by the terminal
emulator, the keyboard protocol it negotiated, and anything in between
(tmux, ssh, a remote desktop), not by kissterm:

    .venv/bin/python scripts/keycheck.py

Why this exists. A binding is matched against a key NAME, so a key that
arrives under a name nothing is listening for does nothing at all and leaves
no trace -- there is no error, no log line, and the operator is left pressing
a key that "does not work". That is not hypothetical here: Enter failing to
send while the Send button worked has now been reported twice on a real
station, and the first attempt to fix it guessed at the cause and added
`shift+enter`/`ctrl+enter`/`alt+enter` bindings to `_SendInput` on the theory
that an enhanced keyboard protocol was attaching a modifier. The report came
back. This prints the answer instead of inferring it.

`kissterm/ui/commands.py` is the one table of key names the app binds (see
AGENTS.md), so whatever this prints has to match an entry there for the key
to do anything. The focused Input below is the same widget shape as the
terminal's send line, and it reports `Input.Submitted` separately, so
"Textual saw Enter" and "the Input turned it into a submit" can be told
apart -- they are different failures with different fixes.

Ctrl+C or Ctrl+Q quits.
"""

from __future__ import annotations

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, RichLog, Static


class _ProbeInput(Input):
    """Reports keys from inside the Input.

    An App-level `on_key` only sees what the focused widget did NOT consume,
    so an ordinary letter never reaches it and the log looks like the key was
    lost. Textual dispatches `on_key` to every class in the MRO that defines
    one, so this reports the keystroke and `Input`'s own handling still runs
    underneath it -- the same MRO property `WrapLog.on_mount` relies on.
    """

    def on_key(self, event) -> None:
        # `character` is what would be inserted as text; `aliases` is every
        # name this one keypress could match a binding under, which is the
        # detail that explains a key doing nothing.
        self.app.report(
            f"key={event.key!r}  character={event.character!r}  "
            f"name={event.name!r}  aliases={list(event.aliases)!r}"
        )


class KeyCheckApp(App):
    CSS = """
    Screen { background: $background; }
    #hint { padding: 1 2; color: $text-muted; }
    #keys { height: 1fr; border: round $primary; margin: 0 1; }
    Input { margin: 0 1; border: round $accent; }
    """

    BINDINGS = [("ctrl+q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(
                "Type in the box. Every key is reported below with the NAME "
                "Textual matched it under.\nPress Enter in the box: it must "
                "report key='enter' AND an Input.Submitted line.\n"
                "Ctrl+C or Ctrl+Q to quit.",
                id="hint",
            )
            yield RichLog(id="keys", markup=False)
            yield _ProbeInput(placeholder="press keys here", id="probe")

    def on_mount(self) -> None:
        self.query_one("#probe", Input).focus()

    def report(self, line: str) -> None:
        self.query_one("#keys", RichLog).write(line)

    @on(Input.Submitted, "#probe")
    def _submitted(self, event: Input.Submitted) -> None:
        self.query_one("#keys", RichLog).write(
            f"    -> Input.Submitted fired, value={event.value!r}"
        )


if __name__ == "__main__":
    KeyCheckApp().run()
