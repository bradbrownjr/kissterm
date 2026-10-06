"""The Flet client's views (`kissterm/client/ui/`) with no Flutter: the
text layout, the pairing link, and the rules a phone must keep.

**A swipe never transmits** (DESIGN.md): swiping a station row opens a
sheet and sends no command; only the sheet's own button does. **A
dismissed question is a cancel**, answered once, and a question the
station closed is never answered from here. The views run against a fake
page that records what was shown.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

ft = pytest.importorskip("flet")

from kissterm.client.connection import parse_link  # noqa: E402
from kissterm.client.state import Chunk, Question, Session, StationState  # noqa: E402
from kissterm.client.ui import sheets  # noqa: E402
from kissterm.client.ui.questions import QuestionSheets  # noqa: E402
from kissterm.client.ui.sessions import Terminal, line_control  # noqa: E402
from kissterm.client.ui.stations import LEFT, RIGHT, StationsView  # noqa: E402
from kissterm.client.ui.text import (  # noqa: E402
    FONTS, MONO_BOLD, OUTGOING, TEXT_COLOURS, Look, runs, split_lines, style_props)
from kissterm.client.ui.web import ASSETS  # noqa: E402
from kissterm.client.ui.web import loopback_url, token_from_route  # noqa: E402
from kissterm.config import ServeConfig  # noqa: E402

# ----------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------


def test_style_props_reads_rich_styles():
    assert style_props("bold red on blue") == {"bold": True, "color": "#cd0000",
                                               "bgcolor": "#0000ee"}
    assert style_props("on blue") == {"bgcolor": "#0000ee"}
    assert style_props("color(196)") == {"color": "#ff0000"}
    assert style_props("blink frobnicate") == {}, "an unknown style is dropped, not guessed"


def test_split_lines_keeps_spans_per_line_and_drops_cr():
    lines = split_lines("ab\r\ncd\nef", [[1, 5, "red"]])
    assert lines == [("ab", [[1, 2, "red"]]), ("cd", [[0, 1, "red"]]), ("ef", [])]
    assert split_lines("ab\n", [])[-1] == ("", []), "the tail is empty after a newline"


def test_runs_cut_where_the_style_changes():
    assert runs("green and", [[0, 5, "green"]]) == [("green", {"color": "#00cd00"}),
                                                     (" and", {})]


def test_a_pairing_link_becomes_the_socket_and_token():
    assert parse_link("http://10.6.26.3:7425/#t=abc") == ("ws://10.6.26.3:7425/v1", "abc")
    assert parse_link("https://kissterm.example/#t=abc") == ("wss://kissterm.example/v1", "abc")
    with pytest.raises(ValueError):
        parse_link("http://10.6.26.3:7425/")


def test_the_token_comes_from_the_route():
    assert token_from_route("t=abc") == "abc"
    assert token_from_route("/t=abc") == "abc"
    assert token_from_route("/") == ""


def test_the_web_app_reaches_its_own_station_on_the_loopback():
    assert loopback_url(ServeConfig(listen="0.0.0.0"), 7425) == ("ws://127.0.0.1:7425/v1", None)
    url, context = loopback_url(ServeConfig(listen="::", tls_cert="c.pem", tls_key="k.pem"), 7425)
    assert url == "wss://127.0.0.1:7425/v1" and context is not None


def test_the_terminal_appends_only_what_is_new_and_joins_a_split_line():
    session = Session(key="WS1EC-7")
    terminal = Terminal("WS1EC-7")
    session.add(Chunk("Welcome to the no"))
    terminal.sync(session)
    session.add(Chunk("de\nprompt> "))
    terminal.sync(session)
    terminal.sync(session)  # nothing new: nothing added
    texts = [c.spans[0].text if c.spans else c.value for c in terminal.list.controls]
    assert texts == ["Welcome to the node", "prompt> "]


def test_both_weights_of_the_terminal_font_are_bundled():
    for path in FONTS.values():
        assert (ASSETS / path).is_file(), f"{path} is not in the client's assets"


def test_the_terminal_is_dark_with_grey_text_unless_chosen_otherwise():
    assert Look() == Look("dark", "grey")
    assert Look("purple", "plaid") == Look(), "an unknown choice is the default, not an error"
    assert Look().color == TEXT_COLOURS["grey"][0]
    assert Look("light", "green").color == TEXT_COLOURS["green"][1]
    assert Look("light").outgoing == OUTGOING["light"]


def test_a_light_panel_darkens_the_colours_a_node_meant_for_a_dark_screen():
    assert Look("light").ansi("#ffff00") != "#ffff00"
    assert Look("dark").ansi("#ffff00") == "#ffff00"
    assert Look("light").ansi("#cd0000") == "#cd0000", "a readable colour is left alone"


def test_bold_text_is_the_bold_font_not_a_thickened_regular():
    line = line_control("BBS here", [[0, 3, "bold green"]], Look())
    assert line.spans[0].style.font_family == MONO_BOLD
    assert line.spans[1].style.font_family is None
    assert line_control("BBS", [], Look(), outgoing=True).font_family == MONO_BOLD


def test_a_new_look_redraws_the_session_on_its_new_panel():
    session = Session(key="W1AW-7")
    session.add(Chunk("hello\nprompt> "))
    terminal = Terminal("W1AW-7")
    terminal.sync(session)
    terminal.restyle(Look("light", "amber"), session)
    assert terminal.control.bgcolor == Look("light").bgcolor
    assert [c.color for c in terminal.list.controls] == [Look("light", "amber").color] * 2
    assert len(terminal.list.controls) == 2, "restyling must not duplicate lines"


# ----------------------------------------------------------------------
# Views on a fake page
# ----------------------------------------------------------------------


class FakePage:
    def __init__(self) -> None:
        self.dialogs: list = []
        self.tasks: list = []

    def show_dialog(self, dialog) -> None:
        self.dialogs.append(dialog)

    def pop_dialog(self) -> None:
        if self.dialogs:
            self.dialogs.pop()

    def update(self) -> None:
        pass

    def run_task(self, fn, *args) -> None:
        self.tasks.append(fn)


class FakeConn:
    def __init__(self) -> None:
        self.answers: list = []

    async def answer(self, qid, value) -> None:
        self.answers.append((qid, value))


class FakeApp:
    def __init__(self) -> None:
        self.page = FakePage()
        self.conn = FakeConn()
        self.state = StationState()
        self.commands: list = []
        self.index = 3
        self.follow_next_session = False
        self.look = Look()

    async def command(self, name, **args):
        self.commands.append((name, args))
        return None

    async def haptic(self) -> None:
        pass

    def go(self, index) -> None:
        self.index = index


class FakeSwipe:
    """A Dismissible's confirm-dismiss event."""

    def __init__(self, row, direction) -> None:
        self.control = self
        self.data = row.data
        self.direction = direction
        self.kept: list = []

    async def confirm_dismiss(self, dismiss: bool) -> None:
        self.kept.append(dismiss)


def _buttons(sheet) -> list:
    found, todo = [], [sheet.content]
    while todo:
        control = todo.pop()
        if isinstance(control, (ft.FilledButton, ft.TextButton)):
            found.append(control)
        for name in ("content", "controls"):
            child = getattr(control, name, None)
            if isinstance(child, list):
                todo.extend(child)
            elif isinstance(child, ft.Control):
                todo.append(child)
    return found


def _button(sheet, label: str):
    return next(b for b in _buttons(sheet) if b.content == label)


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", [RIGHT, LEFT])
async def test_a_swipe_opens_a_sheet_and_transmits_nothing(direction):
    app = FakeApp()
    view = StationsView(app)
    row = view.row("W1AW", "just now", False)
    swipe = FakeSwipe(row, direction)

    await view.on_swipe(swipe)

    assert swipe.kept == [False], "the row must spring back, not be dismissed"
    assert app.commands == [], "a swipe sent a command"
    assert len(app.page.dialogs) == 1, "a swipe must open a sheet"


@pytest.mark.asyncio
async def test_only_the_sheets_own_button_connects():
    app = FakeApp()
    view = StationsView(app)
    await view.on_swipe(FakeSwipe(view.row("W1AW", "", False), RIGHT))
    sheet = app.page.dialogs[-1]

    await _button(sheet, "Cancel").on_click(None)
    assert app.commands == [] and app.page.dialogs == []

    view.ask_connect("W1AW")
    await _button(app.page.dialogs[-1], "Connect").on_click(None)
    assert app.commands == [("connect", {"target": "W1AW"})]
    assert app.follow_next_session, "the new session should come to the front"


def _question(qid: str = "q1") -> Question:
    return Question(qid, "RadioReminder", {"frequency": "145.090"})


@pytest.mark.asyncio
async def test_a_dismissed_question_is_a_cancel_answered_once():
    app = FakeApp()
    questions = QuestionSheets(app)
    questions.show(_question())
    sheet = app.page.dialogs[-1]

    await sheet.on_dismiss(None)
    await sheet.on_dismiss(None)
    assert app.conn.answers == [("q1", None)]


@pytest.mark.asyncio
async def test_an_answered_question_is_not_cancelled_by_its_sheet_closing():
    app = FakeApp()
    questions = QuestionSheets(app)
    questions.show(_question())
    sheet = app.page.dialogs[-1]

    await _button(sheet, "Connect").on_click(None)
    await sheet.on_dismiss(None)
    assert app.conn.answers == [("q1", True)]


@pytest.mark.asyncio
async def test_a_question_the_station_closed_is_never_answered_here():
    app = FakeApp()
    questions = QuestionSheets(app)
    questions.show(_question())
    sheet = app.page.dialogs[-1]

    questions.closed("q1")
    assert sheet.open is False
    await sheet.on_dismiss(None)
    assert app.conn.answers == []


def test_every_sheet_is_the_one_shape():
    page = FakePage()

    async def nothing() -> None:
        pass

    sheets.confirm(page, "Connect to W1AW?", "", "Connect", nothing)
    sheets.form(page, "Add contact", [ft.TextField(label="Station")], "Save", nothing)
    for sheet in page.dialogs:
        assert sheet.content.width == sheets.SHEET_WIDTH
