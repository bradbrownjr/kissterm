"""What the app recorded about its sessions (`KissTermApp._record`).

Notes go to a session's transcript or kissterm.log, never the Terminal
(DESIGN.md section 6). A test spies on `_record` -- the real one still
runs -- to see them without reading files.
"""

from __future__ import annotations


def spy_records(app) -> list[str]:
    """Every note `app` records from now on, as written (no `***`)."""
    seen: list[str] = []
    real = app._record

    def spy(session_key: str, text: str) -> None:
        seen.append(text.strip().lstrip("* "))
        real(session_key, text)

    app._record = spy
    return seen


def terminal_text(app) -> str:
    """Everything in the Terminal pane's on-screen session log."""
    from kissterm.ui.terminal_pane import TerminalPane

    log = app.query_one(TerminalPane).query_one("#session-log")
    return "\n".join(str(line) for line in log.lines)


async def monitor_text(app, pilot) -> str:
    """Everything in the Monitor tab's log: every frame sent and heard.
    Shows the tab first: a `RichLog` holds its lines until it has a size."""
    app.action_show_tab("monitor")
    await pilot.pause()
    log = app.query_one("#monitor-log")
    return "\n".join(str(line) for line in log.lines)
