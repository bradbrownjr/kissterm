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
from kissterm.client.ui.shell import STATIONS, TERMINAL  # noqa: E402
from kissterm.client.ui.stations import LEFT, RIGHT, StationsView  # noqa: E402
from kissterm.client.ui.text import (  # noqa: E402
    FONTS, MONO_BOLD, OUTGOING, TEXT_COLOURS, Look, runs, split_lines, style_props)
from kissterm.client.ui.web import ASSETS  # noqa: E402
from kissterm.client.ui.web import (  # noqa: E402
    loopback_url, read_token, session_key, token_from_route)
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


class _Prefs:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = 0

    async def get(self, key):
        self.asked += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.mark.asyncio
async def test_a_browser_slow_to_give_its_token_is_asked_again_then_reported():
    # The station's log, 2026-10-06: SharedPreferences.get timed out and
    # left a dead page. A second ask can succeed; two failures are None
    # ("did not answer"), which the page tells apart from "never paired".
    late = RuntimeError("TimeoutException after 0:00:10")
    assert await read_token(_Prefs(late, "tok")) == "tok"
    assert await read_token(_Prefs(late, late)) is None
    assert await read_token(_Prefs(None)) == ""


def test_a_dropped_page_session_is_found_in_flets_registry():
    # A rejoined Flet session does not redraw, so a dropped one is deleted
    # (web.forget); this fails if a Flet upgrade renames the registry.
    from flet_web.fastapi.flet_app_manager import app_manager

    assert hasattr(app_manager, "_FletAppManager__sessions")
    mine, other = object(), object()

    class Manager:
        _FletAppManager__sessions = {"_a_1": other, "_b_2": mine}

    assert session_key(Manager(), mine) == "_b_2"
    assert session_key(Manager(), object()) is None


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


def test_kissterms_own_icons_replace_flets_splash_and_home_screen_icon():
    """Operator, 2026-10-06: the splash showed Flet's logo. The server
    looks in our assets first, so these names replace Flet's."""
    for name in ("icons/loading-animation.png", "icons/icon-192.png", "icons/icon-512.png",
                 "icons/icon-maskable-192.png", "icons/icon-maskable-512.png",
                 "icons/apple-touch-icon-192.png", "favicon.png"):
        assert (ASSETS / name).is_file(), f"{name} is missing: scripts/generate_web_icons.py"


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
    assert terminal.panel.bgcolor == Look("light").bgcolor
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
        self.status = "connected"

    async def answer(self, qid, value) -> None:
        self.answers.append((qid, value))


class FakeApp:
    def __init__(self) -> None:
        self.page = FakePage()
        self.conn = FakeConn()
        self.state = StationState()
        self.commands: list = []
        self.index = STATIONS
        self.follow_next_session = False
        self.look = Look()

    async def command(self, name, /, **args):
        self.commands.append((name, args))
        return None

    async def haptic(self) -> None:
        pass

    def go(self, index) -> None:
        self.index = index

    def start_connect(self, **args) -> None:
        self.follow_next_session = True
        self.go(TERMINAL)
        self.commands.append(("connect", args))

    def section_changed(self) -> None:
        self.sections_changed = getattr(self, "sections_changed", 0) + 1

    def paint_actions(self) -> None:
        pass


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
        if isinstance(control, (ft.FilledButton, ft.TextButton, ft.OutlinedButton)):
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
    assert app.index == TERMINAL, "Terminal comes to the front before the link is up"



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


@pytest.mark.asyncio
@pytest.mark.parametrize("label, answer", [("Newest 20", 20), ("All 72", 72), ("None", None)])
async def test_how_many_bulletins_answers_a_count(label, answer):
    app = FakeApp()
    questions = QuestionSheets(app)
    questions.show(Question("q1", "HowManyBulletins", {
        "bbs": "WS1EC", "count": 72, "categories": ["WX", "ARES"], "newest": 20,
        "radio": True}))
    sheet = app.page.dialogs[-1]
    assert any("72 new bulletins on WS1EC" in str(getattr(c, "value", "")) for c in _walk(sheet))
    await _button(sheet, label).on_click(None)
    assert app.conn.answers == [("q1", answer)]


def test_every_sheet_is_the_one_shape():
    page = FakePage()

    async def nothing() -> None:
        pass

    sheets.confirm(page, "Connect to W1AW?", "", "Connect", nothing)
    sheets.form(page, "Add contact", [ft.TextField(label="Station")], "Save", nothing)
    for sheet in page.dialogs:
        assert sheet.content.width == sheets.SHEET_WIDTH


# ----------------------------------------------------------------------
# Sessions: the connect in progress (operator, 2026-10-06)
# ----------------------------------------------------------------------


def test_the_station_says_which_sessions_are_still_connecting():
    state = StationState()
    seen = []
    state.subscribe(lambda kind, data: seen.append((kind, getattr(data, "key", data))))
    state.apply({"type": "event", "seq": 2, "name": "ConnectingChanged",
                 "data": {"keys": ["W1AW-7"]}})
    assert state.sessions["W1AW-7"].connecting
    state.apply({"type": "event", "seq": 3, "name": "ConnectingChanged", "data": {"keys": []}})
    assert "W1AW-7" not in state.sessions, "a cancelled attempt with nothing to show stays"
    assert seen[-1] == ("session_closed", "W1AW-7")


def test_a_session_being_dialled_shows_before_the_station_opens_it():
    """The station opens a radio session when its link is up; the client
    shows the attempt from the first ConnectingChanged."""
    state = StationState()
    state.apply({"type": "event", "seq": 1, "name": "ConnectingChanged",
                 "data": {"keys": ["K1ABC"]}})
    assert state.sessions["K1ABC"].connecting
    state.apply({"type": "event", "seq": 2, "name": "SessionOpened",
                 "data": {"key": "K1ABC", "peer": "K1ABC"}})
    # The station ends the attempt after the session opened, before any
    # text: the session stays.
    state.apply({"type": "event", "seq": 3, "name": "ConnectingChanged", "data": {"keys": []}})
    assert "K1ABC" in state.sessions and not state.sessions["K1ABC"].connecting


@pytest.mark.asyncio
async def test_a_connecting_session_shows_an_hourglass_and_cancel_needs_no_confirming():
    from kissterm.client.ui.sessions import SessionsView

    app = FakeApp()
    view = SessionsView(app)
    app.follow_next_session = True
    session = app.state.session("W1AW-7")
    session.connecting = True
    view.on_state("session", session)
    assert view.current == "W1AW-7" and not app.follow_next_session
    terminal = view.terminals["W1AW-7"]
    assert terminal.waiting.visible
    cancel = next(c for c in _walk(terminal.waiting) if isinstance(c, ft.OutlinedButton))
    await cancel.on_click(None)
    assert app.commands == [("disconnect", {"key": "W1AW-7"})]
    assert app.page.dialogs == [], "cancelling a connect never asks first"

    session.connecting, session.connected = False, True
    view.on_state("session", session)
    assert not terminal.waiting.visible


def test_the_terminal_has_no_header_row_above_it():
    from kissterm.client.ui.sessions import SessionsView

    app = FakeApp()
    view = SessionsView(app)
    view.on_state("session", app.state.session("W1AW-7"))
    assert view.control.controls == [view.pages, view.suggestions.column, view.send_row]


def test_contacts_come_before_heard():
    view = StationsView(FakeApp())
    bar = view.control.content.controls[0]
    assert [t.label for t in bar.tabs] == ["Contacts", "Heard"]


def _walk(control) -> list:
    found, todo = [], [control]
    while todo:
        c = todo.pop()
        found.append(c)
        for name in ("content", "controls"):
            child = getattr(c, name, None)
            if isinstance(child, list):
                todo.extend(child)
            elif isinstance(child, ft.Control):
                todo.append(child)
    return found


# ----------------------------------------------------------------------
# Mail: a run shows it is going, and a second tap cancels it
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_running_send_receive_turns_counts_and_cancels_on_a_tap():
    from kissterm.client.ui.mail import MailView

    app = FakeApp()
    view = MailView(app)
    await view.button.on_click(None)
    assert app.commands == [] and len(app.page.dialogs) == 1, "a new run asks first"
    app.page.dialogs.clear()

    app.state.apply({"type": "event", "seq": 1, "name": "MailRunChanged", "data": {"running": True}})
    app.state.apply({"type": "event", "seq": 2, "name": "ActivityChanged",
                     "data": {"text": "Receiving 2 of 2"}})
    view.on_state("mail_running", True)
    assert app.page.tasks == [view._tick], "the icon starts turning"
    view._dots = 2
    view._paint_activity()
    assert view.activity.value == "Receiving 2 of 2.. "
    assert "cancel" in view.button.tooltip

    await view.button.on_click(None)
    assert app.commands == [("mail_cancel", {})], "a tap while running cancels"
    assert all(not isinstance(d, ft.BottomSheet) for d in app.page.dialogs), \
        "cancelling never asks"

    app.state.apply({"type": "event", "seq": 3, "name": "MailRunChanged", "data": {"running": False}})
    view._paint_activity()
    assert not view.activity.value.endswith(".")


def test_routing_is_one_small_line_with_the_lines_folded():
    from kissterm.client.ui.mail import routing_section

    assert routing_section([]) == []
    # One small line, the BBSes in travel order; a tap shows the lines
    # (operator, 2026-10-06: "one small tight small-font line under the date").
    routes = ["R:261002/1236Z 3098@WS1EC.#CUMB.ME.USA.NOAM LinBPQ6.0.25",
              "R:261002/1230Z 8243@W1BKW.#OXFO.ME.USA.NOAM BPQ6.0.25"]
    line, lines = routing_section(routes)
    assert line.content.controls[0].value == "Routing" and line.content.controls[0].size <= 12
    assert not lines.visible and "3098@WS1EC" in lines.value


# ----------------------------------------------------------------------
# Parity with the terminal: Get bulletins, Get files, By Internet (I),
# Send position (APRS > P), Send beacon (Session > B)
# ----------------------------------------------------------------------


async def _choose(app, label: str) -> None:
    [sheet] = app.page.dialogs
    await _button(sheet, label).on_click(None)
    assert app.page.dialogs == [], "the sheet stayed up"


@pytest.mark.asyncio
@pytest.mark.parametrize("folder, label, expected", [
    ("Mail/BBS/Inbox", "By radio", ("send_receive", {"folder": "Mail/BBS/Inbox"})),
    ("Mail/BBS/Inbox", "By Internet",
     ("send_receive", {"folder": "Mail/BBS/Inbox", "internet": True})),
    ("Bulletins/ALL", "By radio", ("get_bulletins", {})),
    ("Bulletins/ALL", "By Internet", ("get_bulletins", {"internet": True})),
    ("Files", "Get files", ("get_files", {})),
])
async def test_the_mail_button_does_what_g_and_i_do_for_the_folder(folder, label, expected):
    from kissterm.client.ui.mail import MailView

    app = FakeApp()
    view = MailView(app)
    view.folder = folder
    await view.button.on_click(None)
    assert app.commands == [], "the button sent before the sheet was answered"
    await _choose(app, label)
    assert app.commands == [expected]


@pytest.mark.asyncio
async def test_cancelling_the_mail_sheet_sends_nothing():
    from kissterm.client.ui.mail import MailView

    app = FakeApp()
    view = MailView(app)
    await view.button.on_click(None)
    await _choose(app, "Cancel")
    assert app.commands == []


@pytest.mark.asyncio
async def test_send_position_and_send_beacon_ask_first():
    from kissterm.client.ui.messages import MessagesView
    from kissterm.client.ui.more import MoreView

    app = FakeApp()
    messages = MessagesView(app)
    await messages.reload()
    position = next(c for c in messages.list.controls[0].content.controls
                    if c.content == "Position")
    await position.on_click(None)
    assert app.commands == [("aprs_conversations", {})], "Send position sent before asking"
    await _choose(app, "Send")
    assert app.commands[-1] == ("aprs_position", {})

    app.commands.clear()
    more = MoreView(app)
    await more._send_beacon(None)
    await _choose(app, "Cancel")
    assert app.commands == []
    # Beacon asks Packet or APRS (operator, 2026-10-06).
    await more._send_beacon(None)
    await _choose(app, "Packet beacon")
    assert app.commands == [("beacon_now", {})]
    await more._send_beacon(None)
    await _choose(app, "APRS position")
    assert app.commands[-1] == ("aprs_position", {})


# ----------------------------------------------------------------------
# Writing, replying and deleting mail from the phone (parity group 2)
# ----------------------------------------------------------------------


class MailApp(FakeApp):
    """A FakeApp whose commands answer from `answers` (a value, or a
    function of the arguments)."""

    def __init__(self, answers: dict) -> None:
        super().__init__()
        self.answers = answers

    async def command(self, name, /, **args):
        self.commands.append((name, args))
        answer = self.answers.get(name)
        return answer(**args) if callable(answer) else answer


class FakeDismiss:
    def __init__(self, control) -> None:
        self.control = control


def _icons(controls) -> list:
    return [c.tooltip for c in controls if isinstance(c, ft.IconButton)]


@pytest.mark.asyncio
async def test_a_swipe_deletes_with_undo_and_restores_in_deleted():
    from kissterm.client.ui.mail import MailView

    app = MailApp({"mail_folders": ["Mail/BBS/Inbox", "Mail/BBS/Deleted"],
                   "mail_list": [{"ref": "Mail/BBS/Inbox/a.msg", "subject": "Hi"}],
                   "mail_delete": "Mail/BBS/Deleted/a.msg",
                   "mail_restore": "Mail/BBS/Inbox/a.msg"})
    view = MailView(app)
    await view.reload()
    [row] = view.list.controls
    assert isinstance(row, ft.Dismissible) and row.data == "Mail/BBS/Inbox/a.msg"
    assert set(row.dismiss_thresholds.values()) == {0.5}, "a short drag springs back"
    assert row.on_confirm_dismiss is None, "the swipe acts: deleting transmits nothing"
    await view._swiped(FakeDismiss(row))
    assert row not in view.list.controls
    assert app.commands[-1] == ("mail_delete", {"ref": "Mail/BBS/Inbox/a.msg"})
    [note] = app.page.dialogs
    assert note.action == "Undo"
    await note.on_action(None)
    assert app.commands[-1] == ("mail_restore", {"ref": "Mail/BBS/Deleted/a.msg"})

    view.folder = "Mail/BBS/Deleted"
    app.page.dialogs.clear()
    await view.discard("Mail/BBS/Deleted/a.msg")
    assert app.commands[-1] == ("mail_restore", {"ref": "Mail/BBS/Deleted/a.msg"})
    assert "Restored to BBS/Inbox" in app.page.dialogs[-1].content.value


@pytest.mark.asyncio
async def test_a_file_shows_its_size_and_opens_its_preview():
    from kissterm.client.ui.mail import MailView

    ref = "Files/Downloads/bulletin.html.zip"
    entry = {"ref": ref, "subject": "bulletin.html.zip", "size": 2286, "file": True,
             "date": "2026-10-07T04:37:13+00:00"}
    app = MailApp({"mail_folders": ["Files/Downloads"], "mail_list": [entry],
                   "mail_read": {**entry, "body": "      9,120  bulletin.html", "kind": "zip"}})
    view = MailView(app)
    view.set_section("Files")
    await view.reload()
    [row] = view.list.controls
    assert "2,286 bytes" in row.content.subtitle.value
    await view.open(ref)
    texts = [str(getattr(c, "value", "")) for c in _walk(view.reader)]
    assert any("Size: 2,286 bytes" in t for t in texts)
    assert any("bulletin.html" in t for t in texts)
    assert _icons(view.reader_actions(ref, {})) == ["Delete"], "no Reply on a file"


def test_the_reader_offers_reply_all_only_with_others_and_restore_in_deleted():
    from kissterm.client.ui.mail import MailView

    view = MailView(MailApp({}))
    assert _icons(view.reader_actions("r", {"reply_all": False})) == [
        "Reply", "Reply with quote", "Delete"]
    assert _icons(view.reader_actions("r", {"reply_all": True})) == [
        "Reply", "Reply all", "Reply with quote", "Delete"]
    view.folder = "Mail/Winlink/Deleted"
    assert _icons(view.reader_actions("r", {}))[-1] == "Restore"
    view.folder = "Files/Downloads"
    assert _icons(view.reader_actions("r", {})) == ["Delete"]


@pytest.mark.asyncio
async def test_writing_saves_to_the_outbox_or_shows_why_not():
    from kissterm.client.ui.mail import MailView

    results = [{"problems": ["To is empty."], "folder": ""},
               {"problems": [], "folder": "Mail/BBS/Outbox"}]
    app = MailApp({"mail_write": lambda **_: results.pop(0), "mail_list": [],
                   "mail_folders": ["Mail/BBS/Inbox"]})
    view = MailView(app)
    await view._write_new(None)
    writing = view._writing
    assert view.fab() is None and writing["kind"].value == "P"
    writing["title"].value, writing["body"].value = "Hi", "Hello"
    await writing["save"](None)
    assert writing["problems"].value == "To is empty." and view._writing is writing, \
        "a refused message stays open with the reason"
    writing["to"].value = "W1BKW"
    await writing["save"](None)
    assert app.commands[-3][0] == "mail_write" and app.commands[-3][1]["to"] == "W1BKW"
    assert view._writing is None and "Send/Receive sends it" in app.page.dialogs[-1].content.value


@pytest.mark.asyncio
async def test_a_reply_starts_from_the_station_and_closing_asks_first():
    from kissterm.client.ui.mail import MailView

    start = {"to": "W1AW, K1XYZ", "title": "Re:Net", "body": "", "send_type": "W",
             "by_number": False, "heading": "Reply from W1AW by Winlink", "note": ""}
    app = MailApp({"mail_reply_start": start, "mail_list": [], "mail_folders": []})
    view = MailView(app)
    await view.reply("Mail/Winlink/Inbox/x.msg", quoted=None, everyone=True)
    assert app.commands[-1] == ("mail_reply_start", {"ref": "Mail/Winlink/Inbox/x.msg",
                                                     "quoted": None, "all": True})
    writing = view._writing
    assert writing["to"].value == "W1AW, K1XYZ" and not writing["kind"].visible
    assert not writing["at"].visible, "Winlink has no @"
    writing["body"].value = "Yes"
    await writing["close"](None)
    assert view._writing is writing and isinstance(app.page.dialogs[-1], ft.BottomSheet), \
        "typed text is not thrown away without asking"


def test_a_date_reads_as_the_terminal_shows_it():
    from datetime import datetime, timezone

    from kissterm.client.ui.mail import when

    utc = datetime(2026, 10, 6, 18, 40, tzinfo=timezone.utc)
    assert when(utc.isoformat()) == utc.astimezone().strftime("%Y-%m-%d %H:%M")
    assert when(None) == "" and when("yesterday") == "yesterday"


# ----------------------------------------------------------------------
# Reconnect, bulletin categories, transcripts (parity group 3)
# ----------------------------------------------------------------------


def test_reconnect_shows_where_disconnect_was_once_the_session_drops():
    from kissterm.client.state import Session
    from kissterm.client.ui.shell import MAIL, TERMINAL, session_chips

    assert session_chips(TERMINAL, Session("W1AW-7", connected=True)) == (True, False)
    assert session_chips(TERMINAL, Session("W1AW-7")) == (False, True)
    assert session_chips(TERMINAL, Session("W1AW-7", connecting=True)) == (False, False), \
        "a connect under way has Cancel on its hourglass"
    assert session_chips(MAIL, Session("W1AW-7")) == (False, False)
    assert session_chips(TERMINAL, None) == (False, False)


@pytest.mark.asyncio
async def test_reconnect_asks_first_then_redials_that_session():
    from kissterm.client.ui.sessions import SessionsView

    app = MailApp({})
    view = SessionsView(app)
    view.keys, view.selected = ["W1AW-7"], 0
    await view.reconnect()
    assert app.commands == [], "Reconnect sent before the sheet was answered"
    [asked] = app.page.dialogs
    await _button(asked, "Reconnect").on_click(None)
    assert app.commands == [("reconnect", {"key": "W1AW-7"})]


def test_mail_is_titled_bbs_mail_and_write_is_a_pencil_over_send_receive():
    # Operator, 2026-10-06: "update the Mail section title to BBS Mail";
    # "move the pencil icon ... next to the send/receive button and drop
    # the text label".
    import flet as ft

    from kissterm.client.ui.mail import MailView
    from kissterm.client.ui.shell import TITLES

    assert TITLES["Mail"] == "BBS Mail"
    view = MailView(FakeApp())
    pencil = view.write_button
    assert isinstance(pencil, ft.FloatingActionButton) and pencil.mini
    assert pencil.icon == ft.Icons.EDIT and not pencil.content
    assert pencil in view.control.content.controls  # over the list, not in its toolbar


FOLDERS = ["Bulletins", "Bulletins/ARES", "Bulletins/Deleted", "Bulletins/WX", "Files", "Mail", "Mail/BBS",
           "Mail/BBS/Deleted", "Mail/BBS/Inbox", "Mail/BBS/Outbox", "Mail/Winlink",
           "Mail/Winlink/Inbox"]


def test_each_section_lists_only_its_own_folders():
    from kissterm.client.ui.mail import default_folder, folder_label, section_folders

    mail = section_folders(FOLDERS, "Mail")
    # All Inboxes first, and where Mail opens, as on the terminal's Mail tab
    # (operator, 2026-10-06: "All Inboxes is missing from the mail drop-down").
    assert mail == ["All Inboxes", "Mail/BBS/Inbox", "Mail/BBS/Outbox", "Mail/Winlink/Inbox",
                    "Mail/BBS/Deleted"]
    assert default_folder(mail, "Mail") == "All Inboxes"
    assert default_folder(mail[1:], "Mail") == "Mail/BBS/Inbox"
    bulletins = section_folders(FOLDERS, "Bulletins")
    assert bulletins == ["Bulletins/ARES", "Bulletins/WX", "Bulletins/Deleted"]
    assert default_folder(["Bulletins/Deleted", "Bulletins/WX"], "Bulletins") == "Bulletins/WX"
    assert section_folders(FOLDERS, "Files") == ["Files"]
    assert folder_label("Bulletins/WX", "Bulletins") == "WX"
    assert folder_label("Files", "Files") == "Files"


def test_the_folder_picker_is_a_tree_of_services():
    from kissterm.client.ui.mail import folder_tree, section_folders

    # Operator, 2026-10-07: "more of a tree folder view". Services hold
    # their folders, Deleted last in each; one-level folders stand alone.
    mail = section_folders(FOLDERS, "Mail")
    assert folder_tree(mail, "Mail") == [
        ("All Inboxes", "All Inboxes", []),
        ("BBS", "", [("Inbox", "Mail/BBS/Inbox"), ("Outbox", "Mail/BBS/Outbox"),
                     ("Deleted", "Mail/BBS/Deleted")]),
        ("Winlink", "", [("Inbox", "Mail/Winlink/Inbox")])]
    assert folder_tree(section_folders(FOLDERS, "Bulletins"), "Bulletins") == [
        ("ARES", "Bulletins/ARES", []), ("WX", "Bulletins/WX", []),
        ("Deleted", "Bulletins/Deleted", [])]
    assert folder_tree(["Files"], "Files") == [("Files", "Files", [])]


@pytest.mark.asyncio
async def test_the_folder_picker_opens_folds_and_picks():
    from kissterm.client.ui.mail import MailView

    app = MailApp({"mail_folders": FOLDERS, "mail_list": []})
    view = MailView(app)
    await view.reload()
    assert not view.panel.visible and view.folders.content.controls[0].value == "All Inboxes"

    view._toggle_picker(None)
    assert view.panel.visible and len(view.tree.controls) == 3, "services start folded"

    view._group_toggler("Winlink")(None)
    assert len(view.tree.controls) == 4  # the service's folders appear under it
    leaf = view.tree.controls[3]
    await leaf.on_click(None)
    assert view.folder == "Mail/Winlink/Inbox" and not view.panel.visible
    assert view.folders.content.controls[0].value == "Winlink / Inbox"
    assert ("mail_list", {"folder": "Mail/Winlink/Inbox"}) in app.commands

    view._toggle_picker(None)  # reopens on the service holding the folder
    assert len(view.tree.controls) == 4


@pytest.mark.asyncio
async def test_the_phone_switches_between_mail_bulletins_and_files():
    # Operator, 2026-10-06: bulletins and files on the phone; the desktop
    # has room for a place each.
    from kissterm.client.ui.mail import MailView

    app = MailApp({"mail_folders": FOLDERS, "mail_list": []})
    view = MailView(app)
    await view.reload()
    assert view.switch.visible and view.title() == "BBS Mail"
    assert view.folder == "All Inboxes" and view.write_button.visible

    view.switch.selected = ["Bulletins"]
    await view._switched(type("E", (), {"control": view.switch})())
    assert app.sections_changed == 1 and view.title() == "Bulletins"
    assert view.folder_list == ["Bulletins/ARES", "Bulletins/WX", "Bulletins/Deleted"]
    assert view.categories_button.visible and not view.write_button.visible
    assert view.button.tooltip == "Get bulletins"

    view.set_section("Files")
    await view.reload()
    assert view.folder == "Files" and view.button.tooltip == "Get files"
    view.set_section("Mail")
    await view.reload()
    assert view.folder == "All Inboxes", "a section forgot where it was"


def test_a_wide_screen_has_a_rail_place_per_section_and_no_switch():
    from kissterm.client.ui.mail import MailView
    from kissterm.client.ui.shell import DESTINATIONS, MAIL, RAIL, STATIONS, rail_index

    # Operator, 2026-10-06: "Mail, Messages, Terminal (renamed from
    # Sessions), Stations".
    assert [r[0] for r in RAIL] == ["Mail", "Bulletins", "Files", "Messages", "Terminal",
                                    "Stations", "More"]
    assert [d[0] for d in DESTINATIONS] == ["Mail", "Messages", "Terminal", "Stations", "More"]
    assert len(DESTINATIONS) == 5, "the phone's bar stays at five"
    assert rail_index(MAIL, "Files") == 2 and rail_index(STATIONS, "Mail") == 5
    app = FakeApp()
    app.wide = True
    view = MailView(app)
    assert not view.switch.visible


@pytest.mark.asyncio
async def test_categories_on_a_bulletins_folder_save_offline():
    from kissterm.client.ui.mail import MailView

    app = MailApp({"bulletin_categories": None, "mail_list": [], "mail_folders": []})
    view = MailView(app)
    view.set_section("Bulletins")
    view.folder = "Bulletins/WX"
    await view.reload()
    assert view.categories_button.visible and not view.write_button.visible
    await view._categories(None)
    assert "No categories yet" in app.page.dialogs[-1].content.value
    app.page.dialogs.clear()

    app.answers["bulletin_categories"] = {"bbs": "WS1EC", "seen": {"ARES": 2, "WX": 4},
                                          "chosen": ["WX"], "all": False}
    await view._categories(None)
    [sheet] = app.page.dialogs
    listing = sheet.content.content.controls[3]
    boxes = list(listing.controls)
    assert [(b.data, b.value) for b in boxes] == [("ARES", False), ("WX", True)]
    # Operator, 2026-10-07: 14 categories ran off the screen with Save.
    assert listing.scroll and listing.height, "the list scrolls in its own box"
    assert sheet.content.content.scroll, "a long form scrolls as a whole"
    boxes[0].value = True
    await _button(sheet, "Save").on_click(None)
    assert app.commands[-1] == ("bulletin_categories_save",
                                {"picked": ["ARES", "WX"], "all": False})


@pytest.mark.asyncio
async def test_transcripts_list_search_and_open_over_more():
    from kissterm.client.ui.more import MoreView

    app = MailApp({"transcripts": [{"name": "20261006-120000_N1ABC-1_W1AW-7.log",
                                    "peer": "W1AW-7", "started": "2026-10-06 12:00:00",
                                    "size": 2048}],
                   "transcript_read": "Welcome to W1AW\n"})
    more = MoreView(app)
    more.transcripts.search.value = "W1AW"
    await more.transcripts.load()
    assert app.commands[-1] == ("transcripts", {"needle": "W1AW"})
    [row] = more.transcripts.list.controls
    assert row.title.value == "W1AW-7" and "2.0 KB" in row.subtitle.value
    await row.on_click(None)
    assert app.commands[-1] == ("transcript_read",
                                {"file": "20261006-120000_N1ABC-1_W1AW-7.log"})
    assert more.control.content is not more.list
    back = more.control.content.controls[0].controls[0]
    await back.on_click(None)
    assert more.control.content is more.list


def test_all_inboxes_rows_say_which_service_each_came_by():
    from kissterm.client.ui.mail import ALL_INBOXES, MailView

    view = MailView(FakeApp())
    view.folder = ALL_INBOXES
    assert view._via({"source": "Winlink", "folder": "Mail/Winlink/Inbox"}) == "Winlink"
    assert view._via({"source": "", "folder": "Mail/BBS/Inbox"}) == "BBS"
    view.folder = "Mail/BBS/Inbox"
    assert view._via({"source": "BBS", "folder": "Mail/BBS/Inbox"}) == ""


# ----------------------------------------------------------------------
# NTS radiograms from the phone (operator, 2026-10-06: "New Message lacks NTS")
# ----------------------------------------------------------------------

RADIOGRAM_START = {"number": "3", "place": "WATERBORO ME", "origin": "KC1JMH",
                   "precedence": "R", "handling": "", "date": "OCT 6",
                   "precedences": [["R", "Routine"], ["P", "Priority"]],
                   "arl": [{"number": 46, "groups": "ARL FORTY SIX", "text": "Greetings"}]}


@pytest.mark.asyncio
async def test_choosing_nts_in_a_new_message_opens_the_radiogram_form():
    from kissterm.client.ui.mail import RADIOGRAM, TYPES, MailView

    assert RADIOGRAM in [k for k, _ in TYPES]
    app = MailApp({"radiogram_start": RADIOGRAM_START})
    view = MailView(app)
    await view._write_new(None)
    view._writing["kind"].value = RADIOGRAM
    view._writing["kind"].on_select(None)
    assert view.show_radiogram in app.page.tasks
    await view.show_radiogram(False)
    form = view._writing["radiogram"]
    assert form.fields["number"].value == "3" and form.fields["origin"].value == "KC1JMH"
    assert app.commands[-1] == ("radiogram_start", {"ics213": False})
    assert view.fab() is None


@pytest.mark.asyncio
async def test_the_radiogram_text_converts_and_a_late_answer_is_not_applied():
    from kissterm.client.ui.mail import MailView
    from kissterm.client.ui.radiogram import RadiogramForm

    answer = {"check": "2", "route": "ST <zip> @ NTS<state>", "subject": "- -",
              "text": "HELLO X", "live": "HELLO X ", "arl_used": [], "warnings": [],
              "problems": []}
    app = MailApp({"radiogram_check": lambda **_: answer})
    form = RadiogramForm(MailView(app), RADIOGRAM_START, False)
    form.fields["text"].value = "hello. "
    await form.refresh(live=True)
    assert form.fields["text"].value == "HELLO X " and "Check 2" in form.check.value
    # Mid-word, nothing is replaced under the operator's thumb.
    form.fields["text"].value = "HELLO X wor"
    await form.refresh(live=True)
    assert form.fields["text"].value == "HELLO X wor"
    # Leaving the text converts all of it.
    await form.refresh(final=True)
    assert form.fields["text"].value == "HELLO X"


@pytest.mark.asyncio
async def test_saving_a_radiogram_shows_problems_or_files_it():
    from kissterm.client.ui.mail import MailView
    from kissterm.client.ui.radiogram import RadiogramForm

    app = MailApp({"radiogram_write": {"problems": ["ZIP: 5 or 9 digits."], "folder": ""}})
    view = MailView(app)
    form = RadiogramForm(view, RADIOGRAM_START, True)
    assert "ics_subject" in form.fields
    await form.save(None)
    assert "ZIP" in form.problems.value
    name, args = app.commands[-1]
    assert name == "radiogram_write" and args["ics213"] is True
    assert args["fields"]["number"] == "3" and args["fields"]["test"] is False
    app.answers["radiogram_write"] = {"problems": [], "folder": "Mail/BBS/Outbox"}
    await form.save(None)
    assert "Radiogram saved" in app.page.dialogs[-1].content.value


def test_the_place_in_front_loads_once_the_station_is_connected():
    # Opening on Mail asked for its folders before the connection was up,
    # and the page showed "Not connected to the station." (2026-10-06).
    from kissterm.client.ui.shell import MAIL, ClientApp

    conn = FakeConn()
    conn.status = "connecting"
    page = FakePage()
    page.appbar = ft.AppBar()
    app = ClientApp(page, conn, StationState())
    app.go(MAIL)
    assert page.tasks == [], "asked the station before it was connected"
    conn.status = "connected"
    app.on_status("connected")
    assert page.tasks == [app.views[MAIL].shown]


def test_mail_and_messages_reload_only_while_in_front():
    # A list rebuilt off screen came back with a row drawn twice (Flet
    # 1.0.3, reproduced 2026-10-06); `shown` reloads it on the way back.
    from kissterm.client.ui.mail import MailView
    from kissterm.client.ui.messages import MessagesView
    from kissterm.client.ui.shell import MAIL, MESSAGES

    app = FakeApp()
    mail, messages = MailView(app), MessagesView(app)
    app.index = STATIONS
    mail.on_state("stale", "mail")
    messages.on_state("stale", "aprs")
    assert app.page.tasks == []
    app.index = MAIL
    mail.on_state("stale", "mail")
    app.index = MESSAGES
    messages.on_state("stale", "aprs")
    assert app.page.tasks == [mail.reload, messages.reload]


# ----------------------------------------------------------------------
# The APRS map (operator, 2026-10-06)
# ----------------------------------------------------------------------

MAP_POINTS = [
    {"name": "N1ABC-1", "lat": 43.5354, "lon": -70.7153, "kind": "me", "symbol": "/-",
     "symbol_name": "House", "comment": "", "when": 0, "by": ""},
    {"name": "W1AW-9", "lat": 43.6591, "lon": -70.2568, "kind": "station", "symbol": "/>",
     "symbol_name": "Car", "comment": "QRV 147.09", "when": 1000.0, "by": "",
     "where": "24.5 mi 70\N{DEGREE SIGN} ENE"},
    {"name": "SHELTER", "lat": 43.58, "lon": -70.6, "kind": "object", "symbol": "/h",
     "symbol_name": "Hospital", "comment": "Red Cross", "when": 1000.0, "by": "W1AW-9"},
]


@pytest.mark.asyncio
async def test_map_opens_beside_send_position_and_never_transmits():
    from kissterm.client.ui.aprs_map import MapPage
    from kissterm.client.ui.messages import MessagesView

    app = MailApp({"map_points": MAP_POINTS})
    messages = MessagesView(app)
    await messages.reload()
    buttons = [c.content for c in messages.list.controls[0].content.controls]
    assert buttons == ["Position", "Map", "Object"]
    open_map = messages.list.controls[0].content.controls[1]
    await open_map.on_click(None)
    assert isinstance(messages.map, MapPage)
    assert messages.fab() is None
    assert [name for name, _ in app.commands] == ["aprs_conversations", "map_points"]
    assert messages.map.counts.value == "1 station, 1 object"
    # New traffic redraws it, while in front, at most every few seconds.
    from kissterm.client.ui.shell import MESSAGES

    app.index = MESSAGES
    messages.on_state("stale", "heard")
    messages.on_state("stale", "heard")
    assert len(app.page.tasks) == 1
    await messages._back(None)
    assert messages.map is None


def test_the_map_draws_outlines_points_and_finds_a_tap():
    from kissterm.client.ui.aprs_map import details, nearest, shapes
    from kissterm.geo.project import View

    view = View.fit([(p["lat"], p["lon"]) for p in MAP_POINTS], 400, 600)
    drawn = shapes(view, MAP_POINTS, selected="W1AW-9")
    paths = [s for s in drawn if isinstance(s, ft.canvas.Path)]
    assert paths, "no outlines around Portland, Maine"
    labels = [s.value for s in drawn if isinstance(s, ft.canvas.Text)]
    assert {"N1ABC-1", "W1AW-9", "SHELTER"} <= set(labels)
    assert any(label.endswith(" mi") for label in labels), "no scale bar"
    x, y = view.to_screen(43.6591, -70.2568)
    assert nearest(view, MAP_POINTS, x + 5, y - 5)["name"] == "W1AW-9"
    assert nearest(view, MAP_POINTS, 2, 2) is None
    station = details(MAP_POINTS[1], now=1000.0 + 600)
    assert station == ["Station, Car", "Reported 24.5 mi 70\N{DEGREE SIGN} ENE from here",
                       "Last heard 10 min ago", "QRV 147.09"]
    assert "Reported by W1AW-9" in details(MAP_POINTS[2], now=1000.0)


OBJECT_START = {"name": "", "latitude": 43.58, "longitude": -70.6, "symbol": "/h",
                "comment": "", "scopes": [["network", "Normal"], ["direct", "Direct"]],
                "symbols": [["/h", "Hospital"], ["/-", "House"]]}


@pytest.mark.asyncio
async def test_a_long_press_places_an_object_and_only_send_after_asking_transmits():
    from kissterm.client.ui.messages import MessagesView

    sent = []

    def send(**args):
        sent.append(args)
        return {"problems": [], "sent": True}

    app = MailApp({"map_points": MAP_POINTS, "aprs_object_start": OBJECT_START,
                   "aprs_object": send})
    messages = MessagesView(app)
    await messages._open_map(None)
    page = messages.map
    page.map = __import__("kissterm.geo.project", fromlist=["View"]).View.fit(
        [(p["lat"], p["lon"]) for p in MAP_POINTS], 400, 600)
    x, y = page.map.to_screen(43.58, -70.6)
    await page._long_pressed(type("E", (), {"local_position": type("P", (), {"x": x, "y": y})()})())
    name, args = app.commands[-1]
    assert name == "aprs_object_start"
    assert args["latitude"] == pytest.approx(43.58) and args["name"] == ""
    form = messages.object_form
    assert form is not None and messages.fab() is None
    form.name.value = "drill"
    await form.send(None)
    assert sent == [], "Send transmitted before asking"
    await _button(app.page.dialogs[-1], "Send").on_click(None)  # then the snack bar
    assert sent[0]["name"] == "DRILL" and sent[0]["alive"] is True
    assert sent[0]["latitude"] == pytest.approx(43.58, abs=1e-5)
    # Back on the same map page, which reloads.
    assert messages.object_form is None and messages.control.content is page.root


@pytest.mark.asyncio
async def test_move_and_kill_are_offered_only_on_this_stations_objects():
    from kissterm.client.ui.messages import MessagesView

    mine = dict(MAP_POINTS[2], mine=True, by="N1ABC-1")
    sent = []
    app = MailApp({"map_points": [MAP_POINTS[0], MAP_POINTS[1], mine],
                   "aprs_object": lambda **a: sent.append(a) or {"problems": [], "sent": True}})
    messages = MessagesView(app)
    await messages._open_map(None)
    page = messages.map
    page.map = __import__("kissterm.geo.project", fromlist=["View"]).View.fit(
        [(p["lat"], p["lon"]) for p in page.points], 400, 600)
    for point, offered in ((MAP_POINTS[1], False), (mine, True)):
        x, y = page.map.to_screen(point["lat"], point["lon"])
        page._tapped(type("E", (), {"local_position": type("P", (), {"x": x, "y": y})()})())
        assert page.selected == point["name"]
        assert page.move.visible is offered and page.kill.visible is offered
    await page._kill(None)
    assert sent == [], "Kill transmitted before asking"
    await _button(app.page.dialogs[-1], "Kill").on_click(None)  # then the snack bar
    assert sent[0]["alive"] is False and sent[0]["name"] == "SHELTER"
    # Move waits for a long press, then opens the form for that object.
    page.selected = "SHELTER"
    page._move(None)
    assert page.banner.visible and page.moving == "SHELTER"


@pytest.mark.asyncio
@pytest.mark.parametrize("label, command", [("Restart", "restart"), ("Shut down", "shutdown")])
async def test_more_restarts_or_shuts_down_the_station_after_asking(label, command):
    from kissterm.client.ui.more import MoreView

    app = MailApp({"restart_plan": {"sessions": ["WS1EC-2"], "aprs_unacked": 0},
                   "restart": True, "shutdown": True})
    app.page.web = False
    more = MoreView(app)
    await (more._restart if command == "restart" else more._shutdown)(None)
    sheet = app.page.dialogs[-1]
    texts = " ".join(str(getattr(c, "value", "")) for c in _walk(sheet))
    assert "WS1EC-2" in texts
    assert ("reconnects by itself" in texts) == (command == "restart")
    assert app.commands[-1] == ("restart_plan", {}), "nothing happens before the button"
    await _button(sheet, label).on_click(None)
    assert app.commands[-1] == (command, {})


@pytest.mark.asyncio
@pytest.mark.parametrize("command, url", [("restart", "/restarting"),
                                          ("shutdown", "/restarting?shutdown")])
async def test_the_web_page_moves_to_the_waiting_page_when_the_station_stops(
        monkeypatch, command, url):
    """The page is the station's own: Flet's browser side cannot rejoin a
    session a new process never had (operator, 2026-10-07: "the page isn't
    reloading"), so the browser is sent to a page that waits and reloads."""
    from kissterm.client.ui.more import MoreView

    opened = []

    class Launcher:
        async def launch_url(self, target, **kw):
            opened.append((target, kw))

    monkeypatch.setattr(ft, "UrlLauncher", Launcher)
    app = MailApp({"restart_plan": {"sessions": [], "aprs_unacked": 0},
                   "restart": True, "shutdown": True})
    app.page.web = True
    more = MoreView(app)
    await (more._restart if command == "restart" else more._shutdown)(None)
    label = "Restart" if command == "restart" else "Shut down"
    await _button(app.page.dialogs[-1], label).on_click(None)
    assert opened == [(url, {"web_only_window_name": "_self"})]


TEMPLATES = {"addressee": "WLNK-1",
             "service": {"id": "winlink", "callsign": "WLNK-1", "name": "Winlink APRSLink",
                         "summary": "s", "note": "Mail by APRS.", "region": "", "source": "https://x",
                         "checked": "2026-09-01",
                         "commands": [{"name": "L", "summary": "List mail", "text": "L",
                                       "confidence": "recalled"},
                                      {"name": "SP", "summary": "Send", "text": "SP <to> <subject>",
                                       "confidence": "documented"}]},
             "saved": [{"name": "Mine", "text": "L 5", "gateway": "winlink"}]}


@pytest.mark.asyncio
async def test_a_template_fills_the_message_box_and_sends_nothing():
    from kissterm.client.ui.messages import MessagesView

    app = MailApp({"aprs_thread": [], "aprs_templates": TEMPLATES})
    messages = MessagesView(app)
    await messages.open("WLNK-1")
    await messages._templates(None)
    assert app.commands[-1] == ("aprs_templates", {"callsign": "WLNK-1"})
    sheet = app.page.dialogs[-1]
    titles = []
    todo = [sheet.content]
    tiles = []
    while todo:
        c = todo.pop()
        if isinstance(c, ft.ListTile):
            tiles.append(c)
        for name in ("content", "controls"):
            child = getattr(c, name, None)
            todo.extend(child if isinstance(child, list) else [child] if child is not None else [])
    assert [t.title.value for t in tiles][::-1] == ["Mine", "L", "SP"]
    sp = next(t for t in tiles if t.title.value == "SP")
    await sp.on_click(None)
    assert messages.compose.value == "SP <to> <subject>"
    assert [n for n, _ in app.commands if n.startswith("aprs_send")] == []


@pytest.mark.asyncio
async def test_a_saved_message_is_saved_and_forgotten_through_the_station():
    from kissterm.client.ui.templates import TemplatesSheet
    from kissterm.client.ui.messages import MessagesView

    app = MailApp({"aprs_thread": [], "aprs_templates": TEMPLATES,
                   "aprs_template_save": {"problems": [], "saved": True},
                   "aprs_template_forget": True})
    messages = MessagesView(app)
    await messages.open("WLNK-1")
    shown = TemplatesSheet(messages, "WLNK-1", TEMPLATES)
    shown.edit(None)
    form = app.page.dialogs[-1]
    fields = [c for c in form.content.content.controls if isinstance(c, ft.TextField)]
    fields[0].value, fields[1].value = "Hi", "QRV"
    await _button(form, "Save").on_click(None)
    assert ("aprs_template_save", {"name": "Hi", "text": "QRV", "gateway": "winlink"}) in app.commands
    await shown._forgetter(TEMPLATES["saved"][0])(None)
    assert app.commands[-2][0] == "aprs_template_forget"


@pytest.mark.asyncio
async def test_an_object_placed_by_grid_square_sends_the_reference_for_the_station_to_convert():
    from kissterm.client.ui.aprs_object import ObjectForm
    from kissterm.client.ui.messages import MessagesView

    sent = []
    app = MailApp({"aprs_object": lambda **a: sent.append(a) or {"problems": [], "sent": True}})
    messages = MessagesView(app)
    form = ObjectForm(messages, dict(OBJECT_START, formats=[["decimal", "Decimal"], ["grid", "Grid"]]))
    form.name.value = "drill"
    form.place_format.value = "grid"
    await form._format_picked(None)
    assert form.reference.visible and not form.latitude.visible
    form.reference.value = "FN43"
    await form.send(None)
    await _button(app.page.dialogs[-1], "Send").on_click(None)
    assert sent[0]["format"] == "grid" and sent[0]["reference"] == "FN43"
    assert "latitude" not in sent[0] and sent[0]["name"] == "DRILL"


REFERENCE = {
    "sections": [
        {"title": "BPQ32 / LinBPQ node", "note": "Node commands.",
         "commands": [{"name": "N", "aliases": ["NODES"], "usage": "N | N C", "summary": "List nodes",
                       "detail": "", "context": "node", "sysop": False, "source": "published"},
                      {"name": "PASSWORD", "aliases": [], "usage": "PASSWORD", "summary": "Sysop login",
                       "detail": "", "context": "node", "sysop": True, "source": "recalled, unverified"}]}],
    "can_harvest": True, "peer": "WS1EC-15", "context": "node", "learned": 3,
    "learned_node": "WS1EC-15", "airtime": ["4 seconds", "1.2 minutes"]}


@pytest.mark.asyncio
async def test_a_command_fills_the_message_box_and_nothing_is_sent():
    from kissterm.client.ui.sessions import SessionsView

    app = MailApp({"session_reference": REFERENCE})
    view = SessionsView(app)
    view.keys, view.selected = ["WS1EC-15"], 0
    await view._commands(None)
    assert app.commands == [("session_reference", {"key": "WS1EC-15"})]
    sheet = app.page.dialogs[-1]
    tiles = [c for c in _walk(sheet.content) if isinstance(c, ft.ListTile)][::-1]
    assert [t.title.value for t in tiles] == ["N / NODES", "PASSWORD"]
    assert "sysop" in tiles[1].trailing.value and "recalled" in tiles[1].trailing.value
    await tiles[0].on_click(None)
    assert view.input.value == "N"
    assert [n for n, _ in app.commands if n == "send_line"] == []


@pytest.mark.asyncio
async def test_learning_from_the_node_shows_the_airtime_and_asks_only_from_its_own_button():
    from kissterm.client.ui.reference import ReferenceSheet
    from kissterm.client.ui.sessions import SessionsView

    app = MailApp({"session_reference": REFERENCE, "glossary": [],
                   "session_harvest": {"learned": ["X"], "captured": 40, "text": "..."},
                   "session_forget_learned": 3})
    view = SessionsView(app)
    view.keys, view.selected = ["WS1EC-15"], 0
    sheet = ReferenceSheet(view, "WS1EC-15", REFERENCE)
    await sheet._paint()
    await sheet._learn(None)
    asked = app.page.dialogs[-1]
    text = " ".join(c.value for c in _walk(asked.content) if isinstance(c, ft.Text) and c.value)
    assert "1.2 minutes" in text and "WS1EC-15" in text
    assert [n for n, _ in app.commands if n == "session_harvest"] == [], "asked before Ask"
    await _button(asked, "Ask").on_click(None)
    assert ("session_harvest", {"key": "WS1EC-15", "context": "node"}) in app.commands
    await sheet._forget(None)
    await _button(app.page.dialogs[-1], "Forget").on_click(None)
    assert ("session_forget_learned", {"key": "WS1EC-15"}) in app.commands


@pytest.mark.asyncio
async def test_suggestions_follow_the_typing_and_a_tap_fills_the_box():
    from kissterm.client.ui.sessions import SessionsView

    app = MailApp({"session_suggest": [{"name": "NODES", "summary": "List nodes", "usage": "N"}]})
    view = SessionsView(app)
    view.keys, view.selected = ["WS1EC-15"], 0
    view.input.value = "nod"
    await view._typed(type("E", (), {"control": view.input})())
    assert app.commands[-1] == ("session_suggest", {"key": "WS1EC-15", "text": "nod"})
    [tile] = view.suggestions.column.controls
    assert view.suggestions.column.visible
    await tile.on_click(None)
    assert view.input.value == "NODES" and not view.suggestions.column.visible
    # An answer for text that has since changed is dropped.
    view.input.value = "x"
    await view.suggestions.typed("nod")
    assert not view.suggestions.column.visible


@pytest.mark.asyncio
async def test_a_zip_opens_a_member_a_level_deeper_and_back_goes_up_one_level():
    from kissterm.client.ui.files import FileViewer

    zipped = {"name": "pack.zip", "size": 9, "kind": "zip", "members": [["a.md", 3]],
              "markdown": "", "text": "", "problem": "", "form": ""}
    inner = {"name": "a.md", "size": 3, "kind": "markdown", "members": [],
             "markdown": "# A", "text": "", "problem": "", "form": ""}
    app = MailApp({"file_open": lambda ref, member: inner if member else zipped})
    closed = []

    async def close() -> None:
        closed.append(True)

    viewer = FileViewer(type("V", (), {"app": app})(), "Files/Downloads/pack.zip", close)
    await viewer.show()
    [tile] = [c for c in _walk(viewer.control) if isinstance(c, ft.ListTile)]
    await tile.on_click(None)
    assert app.commands[-1] == ("file_open", {"ref": "Files/Downloads/pack.zip", "member": ["a.md"]})
    md = [c for c in _walk(viewer.control) if isinstance(c, ft.Markdown)]
    assert md and md[0].auto_follow_links is False and md[0].value == "# A"
    await viewer._back(None)
    assert viewer.path == [] and closed == []
    await viewer._back(None)
    assert closed == [True]


@pytest.mark.asyncio
async def test_a_gateway_is_used_only_after_asking_and_sends_nothing_on_the_air():
    from kissterm.client.ui.gateways import GatewaysSheet

    listed = {"channels": [{"callsign": "W1AW-10", "frequency": "145.050 MHz", "frequency_hz": 145050000,
                            "modes": "Packet 1200", "grid": "FN31pr", "hours": "", "distance": "12 mi N"}],
              "note": "From winlink.org, fetched 2 days ago; 1 shown.", "can_refresh": False,
              "modes": [["Packet", "packet"], ["All modes", ""]]}
    app = MailApp({"rms_gateways": listed, "rms_use": "ok"})
    sheet = GatewaysSheet(type("V", (), {"app": app})())
    await sheet.show()
    assert sheet.refresh.disabled and sheet.note.value.startswith("From winlink.org")
    [tile] = sheet.rows.controls
    await tile.on_click(None)
    assert [n for n, _ in app.commands if n == "rms_use"] == [], "used before asking"
    await _button(app.page.dialogs[-1], "Use").on_click(None)
    assert app.commands[-1] == ("rms_use", {"callsign": "W1AW-10", "frequency": "145.050 MHz",
                                            "modes": "Packet 1200", "grid": "FN31pr"})


@pytest.mark.asyncio
async def test_sending_a_file_asks_first_and_names_the_session_and_protocol():
    from kissterm.client.ui import transfer

    app = MailApp({"transfer_start": True})
    session = app.state.session("WS1EC-2")
    session.connected = True
    transfer.ask(app, ref="Files/Downloads/notes.md", name="notes.md", current="WS1EC-2")
    asked = app.page.dialogs[-1]
    assert [n for n, _ in app.commands if n == "transfer_start"] == []
    await _button(asked, "Send").on_click(None)
    assert app.commands[-1] == ("transfer_start", {
        "key": "WS1EC-2", "protocol": "yapp", "mode": "upload", "ref": "Files/Downloads/notes.md"})
    # No connected session: nothing to ask, and nothing started.
    quiet = MailApp({})
    transfer.ask(quiet, ref="Files/x", name="x")
    assert quiet.commands == [] and all(isinstance(d, ft.SnackBar) for d in quiet.page.dialogs)


def _every_form_start():
    from kissterm.config import Config
    from kissterm.core import Core
    from kissterm.serve import wire

    core = Core(Config(mycall="KC1JMH-7"), None)
    return [wire.jsonable(core.mail.form_start(f["id"])) for f in core.mail.forms_list()]


def test_every_shipped_form_lays_out_without_a_missing_key():
    from kissterm.client.ui.forms import FormPage

    starts = _every_form_start()
    assert len(starts) >= 10
    for start in starts:
        page = FormPage(type("V", (), {"app": FakeApp()})(), start, None)
        assert page.body, start["form"]["id"]
        assert page.collect().keys() >= {f["id"] for f in start["form"]["fields"]
                                         if f["kind"] == "rows"}


@pytest.mark.asyncio
async def test_next_checks_the_form_and_opens_the_writer_filled_in_and_saving_writes_the_form():
    from kissterm.client.ui.mail import MailView

    start = next(s for s in _every_form_start() if s["form"]["id"] == "ics213")
    made = {"problems": [], "to": "W1AW", "at": "", "title": "ICS-213: x", "body": "GENERAL MESSAGE\n",
            "send_type": "P"}
    app = MailApp({"form_start": start, "form_check": made,
                   "form_write": {"problems": [], "folder": "Mail/BBS/Outbox", "note": ""},
                   "mail_folders": [], "mail_list": [], "forms": []})
    view = MailView(app)
    await view.show_form("ics213")
    page = view._writing["form"]
    first = next(iter(page.inputs.values()))
    await first.on_change(type("E", (), {"control": type("C", (), {"value": "hello"})()})())
    await page._next(None)
    assert app.commands[-1][0] == "form_check" and app.commands[-1][1]["form"] == "ics213"
    writer = view._writing
    assert writer["title"].value == "ICS-213: x" and writer["to"].value == "W1AW"
    assert writer["body"].value == "GENERAL MESSAGE\n"
    await writer["save"](None)
    [args] = [a for n, a in app.commands if n == "form_write"]
    assert args["form"] == "ics213" and args["title"] == "ICS-213: x"
    assert args["values"]  # the form's own values travel for its XML


@pytest.mark.asyncio
async def test_a_form_with_problems_stays_on_its_page_and_says_what_is_needed():
    from kissterm.client.ui.mail import MailView

    start = next(s for s in _every_form_start() if s["form"]["id"] == "ics213")
    app = MailApp({"form_start": start, "forms": [],
                   "form_check": {"problems": ["Subject is needed.", "To is needed."]}})
    view = MailView(app)
    await view.show_form("ics213")
    page = view._writing["form"]
    await page._next(None)
    assert "Subject is needed." in page.problems.value and view._writing == {"form": page}


@pytest.mark.asyncio
async def test_an_answered_strip_opens_the_writer_as_a_reply_and_saves_it_as_one():
    from kissterm.client.ui.mail import MailView

    key = "strip:GYX WEATHER/Location/Sky//"
    start = {"form": {"id": "strip", "title": "GYX WEATHER (strip)", "fields": [
        {"id": "f0", "kind": "text", "label": "Location"}]}, "values": {"f0": ""}, "key": key}
    made = {"problems": [], "to": "", "at": "", "title": "GYX WEATHER", "body": "GYX WEATHER/x//",
            "send_type": "P"}
    reply = {"to": "W1BKW", "title": "Re:Wx request", "body": "", "send_type": "P",
             "by_number": True, "heading": "Reply to #3105 from W1BKW", "note": "Sent as SR 3105"}
    app = MailApp({"form_start": start, "form_check": made, "mail_reply_start": reply,
                   "form_write": {"problems": [], "folder": "Mail/BBS/Outbox", "note": ""},
                   "mail_folders": [], "mail_list": [], "forms": []})
    view = MailView(app)
    await view.show_form(key, reply_to="Mail/BBS/Inbox/1")
    assert app.commands[0][1]["reply_to"] == "", "a strip is not a reply form"
    await view._writing["form"]._next(None)
    assert app.commands[1][1]["form"] == key, "the station checks it by its strip"
    writer = view._writing
    assert writer["to"].value == "W1BKW" and writer["title"].value == "Re:Wx request"
    assert not writer["kind"].visible, "an answer is a reply: no Type"
    await writer["save"](None)
    [args] = [a for n, a in app.commands if n == "form_write"]
    assert args["form"] == key and args["reply_to"] == "Mail/BBS/Inbox/1"


@pytest.mark.asyncio
async def test_a_pasted_strip_goes_on_to_its_questions():
    from kissterm.client.ui.mail import MailView

    paste = {"form": {"id": "paste_strip", "title": "Paste a strip", "fields": [
        {"id": "strip", "kind": "strip", "label": "Strip"}]}, "values": {"strip": ""},
        "key": "paste_strip"}
    questions = {"form": {"id": "strip", "title": "X (strip)", "fields": [
        {"id": "f0", "kind": "text", "label": "Q"}]}, "values": {"f0": ""}, "key": "strip:X/Q//"}
    app = MailApp({"form_start": lambda **a: questions if a["form"].startswith("strip:") else paste,
                   "form_check": {"problems": [], "next_form": "strip:X/Q//"},
                   "mail_folders": [], "mail_list": [], "forms": []})
    view = MailView(app)
    await view.show_form("paste_strip")
    await view._writing["form"]._next(None)
    assert view._writing["form"].key == "strip:X/Q//"


@pytest.mark.asyncio
async def test_a_bbs_command_fills_the_message_box_and_sends_nothing():
    from kissterm.client.ui.reference import BbsHelper
    from kissterm.client.ui.sessions import SessionsView

    helpers = [{"id": "bpqmail", "name": "BPQMail", "note": "Check the prompt.",
                "macros": [{"id": "read", "label": "Read a message", "summary": "R n",
                            "fields": ["number"], "confidence": "documented"}]}]
    app = MailApp({"bbs_helpers": helpers, "bbs_render": lambda **a: {
        "text": f"R {a['values']['number']}", "error": ""} if a["values"]["number"] else
        {"text": "", "error": "number is required"}})
    view = SessionsView(app)
    helper = BbsHelper(view)
    await helper.show()
    assert helper.number.visible and not helper.callsign.visible
    assert helper.preview.value == "number is required"
    helper.number.value = "42"
    await helper._edited(None)
    assert helper.preview.value.endswith("R 42")
    await helper._use(None)
    assert view.input.value == "R 42"
    assert [n for n, _ in app.commands if n == "send_line"] == []
