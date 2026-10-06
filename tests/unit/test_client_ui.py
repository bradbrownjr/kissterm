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

    def start_connect(self, **args) -> None:
        self.follow_next_session = True
        self.go(0)
        self.commands.append(("connect", args))

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
    assert app.index == 0, "Sessions comes to the front before the link is up"



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
    assert view.control.controls == [view.pages, view.send_row]


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


def test_routing_is_folded_away_and_says_it_is_not_the_sender():
    from kissterm.client.ui.mail import routing_section

    assert routing_section([]) == []
    [tile] = routing_section(["R:261002/1236Z 3098@WS1EC.#CUMB.ME.USA.NOAM LinBPQ6.0.25"])
    assert isinstance(tile, ft.ExpansionTile) and not tile.expanded
    assert "Not the sender" in tile.subtitle.value
    assert "3098@WS1EC" in tile.controls[0].value


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
                    if c.content == "Send position")
    await position.on_click(None)
    assert app.commands == [("aprs_conversations", {})], "Send position sent before asking"
    await _choose(app, "Send")
    assert app.commands[-1] == ("aprs_position", {})

    app.commands.clear()
    more = MoreView(app)
    await more._send_beacon(None)
    await _choose(app, "Cancel")
    assert app.commands == []
    await more._send_beacon(None)
    await _choose(app, "Send")
    assert app.commands == [("beacon_now", {})]


# ----------------------------------------------------------------------
# Writing, replying and deleting mail from the phone (parity group 2)
# ----------------------------------------------------------------------


class MailApp(FakeApp):
    """A FakeApp whose commands answer from `answers` (a value, or a
    function of the arguments)."""

    def __init__(self, answers: dict) -> None:
        super().__init__()
        self.answers = answers

    async def command(self, name, **args):
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
    from kissterm.client.ui.shell import session_chips

    assert session_chips(0, Session("W1AW-7", connected=True)) == (True, False)
    assert session_chips(0, Session("W1AW-7")) == (False, True)
    assert session_chips(0, Session("W1AW-7", connecting=True)) == (False, False), \
        "a connect under way has Cancel on its hourglass"
    assert session_chips(2, Session("W1AW-7")) == (False, False)
    assert session_chips(0, None) == (False, False)


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


@pytest.mark.asyncio
async def test_categories_on_a_bulletins_folder_save_offline():
    from kissterm.client.ui.mail import MailView

    app = MailApp({"bulletin_categories": None, "mail_list": [], "mail_folders": []})
    view = MailView(app)
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
    boxes = [c for c in sheet.content.content.controls[3].controls]
    assert [(b.data, b.value) for b in boxes] == [("ARES", False), ("WX", True)]
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
