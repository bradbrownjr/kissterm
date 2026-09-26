"""The Mail, Bulletins and Files tabs (`kissterm/ui/mail_pane.py`)."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402
from textual.widgets import TabbedContent  # noqa: E402

from kissterm.config import Config  # noqa: E402
from kissterm.mail import KIND_BULLETIN, Message, MessageStore  # noqa: E402
from kissterm.mail.store import ALL_INBOXES  # noqa: E402
from kissterm.ui.app import KissTermApp  # noqa: E402
from kissterm.ui.mail_pane import FolderTree, MessageBrowser, MessageList  # noqa: E402
from kissterm.ui.wraplog import WrapLog  # noqa: E402

WHEN = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)


def _app(tmp_path) -> tuple[KissTermApp, MessageStore]:
    store = MessageStore(tmp_path / "mail")
    store.ensure_default_tree()
    store.add("Mail/BBS/Inbox", Message(sender="KC1JMH", to="WS1EC", subject="Net tonight",
                                        date=WHEN, source="BBS WS1EC", body="Hello\n"))
    store.add("Mail/Winlink/Inbox", Message(sender="W1AW", subject="Via Winlink",
                                            date=WHEN - timedelta(hours=1), body="Hi\n"))
    store.add("Bulletins/WX", Message(sender="N4SD", to="WX", subject="Tropical Storm Fay",
                                      date=WHEN, kind=KIND_BULLETIN, category="WX",
                                      body="\x1b[31mred\x1b[0m [b]not markup[/b]\n"))
    (store.root / "Files/Downloads/notes.txt").write_text("plain text file\n")
    # A saved transport keeps the first-run setup screen from opening on top.
    config = Config(mycall="KC1JMH", start_tab="mail")
    config.transports = [{"name": "tnc", "kind": "tcp", "host": "127.0.0.1", "port": 8001}]
    app = KissTermApp(config)
    app.mail_store = store
    return app, store


def _browser(app, tab: str) -> MessageBrowser:
    return app.query_one(f"#{tab}-browser", MessageBrowser)


def _reader_text(browser: MessageBrowser) -> str:
    return "\n".join(line.text for line in browser.query_one(WrapLog).lines)


@pytest.mark.asyncio
async def test_mail_is_the_launch_tab_with_all_inboxes_first(tmp_path):
    app, _store = _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.query_one("#main-tabs", TabbedContent).active == "mail"
        mail = _browser(app, "mail")
        assert mail.folder == ALL_INBOXES
        tree = mail.query_one(FolderTree)
        top = [str(n.label) for n in tree.root.children]
        assert top == ["All Inboxes (2)", "BBS", "Winlink"]
        assert [str(n.label) for n in tree.root.children[1].children] == [
            "Inbox (1)", "Outbox", "Sent", "Deleted"]
        assert not any("Local" in label for label in top)
        table = mail.query_one(MessageList)
        assert table.row_count == 2
        # Newest first; the Via column says where each came from.
        assert str(table.get_row_at(0)[4]) == "BBS WS1EC"


@pytest.mark.asyncio
async def test_enter_opens_and_marks_read_delete_and_restore(tmp_path):
    app, store = _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        mail = _browser(app, "mail")
        table = mail.query_one(MessageList)
        table.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert "Subject: Net tonight" in _reader_text(mail)
        assert "Hello" in _reader_text(mail)
        assert store.unread_count("Mail/BBS/Inbox") == 0
        assert str(mail.query_one(FolderTree).root.children[0].label) == "All Inboxes (1)"

        await pilot.press("delete")
        await pilot.pause()
        assert store.list("Mail/BBS/Inbox") == []
        assert len(store.list("Mail/BBS/Deleted")) == 1

        mail.show_folder("Mail/BBS/Deleted")
        await pilot.pause()
        assert mail.can_restore() and not mail.can_delete()
        table.focus()
        await pilot.press("u")
        await pilot.pause()
        assert len(store.list("Mail/BBS/Inbox")) == 1


@pytest.mark.asyncio
async def test_one_click_on_a_message_shows_it(tmp_path):
    app, store = _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        mail = _browser(app, "mail")
        table = mail.query_one(MessageList)
        assert "Net tonight" not in _reader_text(mail)
        # Below the list's top edge and header row: the first message.
        await pilot.click(MessageList, offset=(3, 2))
        await pilot.pause()
        assert "Subject: Net tonight" in _reader_text(mail)
        assert table.cursor_row == 0


@pytest.mark.asyncio
async def test_bulletins_by_category_and_remote_text_is_inert(tmp_path):
    app, _store = _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_show_tab("bulletins")
        await pilot.pause()
        bulletins = _browser(app, "bulletins")
        assert [str(n.label) for n in bulletins.query_one(FolderTree).root.children] == [
            "WX (1)", "Deleted"]
        bulletins.query_one(MessageList).focus()
        await pilot.press("enter")
        await pilot.pause()
        text = _reader_text(bulletins)
        assert "\x1b" not in text
        assert "[b]not markup[/b]" in text


@pytest.mark.asyncio
async def test_files_tab_lists_and_previews_text(tmp_path):
    app, _store = _app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_show_tab("files")
        await pilot.pause()
        files = _browser(app, "files")
        files.show_folder("Files/Downloads")
        await pilot.pause()
        table = files.query_one(MessageList)
        assert str(table.get_row_at(0)[0]) == "notes.txt"
        assert not files.can_delete()
        table.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert "plain text file" in _reader_text(files)


@pytest.mark.asyncio
async def test_a_received_ics213_reads_as_a_form_and_v_shows_its_text(tmp_path):
    app, store = _app(tmp_path)
    body = ("GENERAL MESSAGE (ICS 213)\n1. Incident Name: ICE STORM\n"
            "2. To (Name and Position): J SMITH, EOC\n3. From (Name and Position): B BROWN\n"
            "4. Subject: Shelter status\n5. Date: 2026-09-26\n6. Time: 14:05\n7. Message:\n\n"
            "Shelter open.\n\x1b[31mCots\x1b[0m needed.\n\n8. Approved by: B BROWN\n")
    store.add("Mail/BBS/Inbox", Message(sender="W1AW", to="KC1JMH", date=WHEN + timedelta(hours=1),
                                        subject="ICS-213: Shelter status - 2026-09-26 14:05",
                                        source="BBS WS1EC", body=body))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        mail = _browser(app, "mail")
        table = mail.query_one(MessageList)
        table.focus()
        await pilot.press("enter")
        await pilot.pause()
        shown = _reader_text(mail)
        assert "ICS-213 General Message" in shown and "V shows the text as received" in shown
        assert "1. Incident" in shown and "ICE STORM" in shown and "  Cots needed." in shown
        assert "\x1b" not in shown and "GENERAL MESSAGE (ICS 213)" not in shown
        assert "v" in app.screen.active_bindings  # in the Footer while it applies
        await pilot.press("v")
        await pilot.pause()
        assert "GENERAL MESSAGE (ICS 213)" in _reader_text(mail)
        await pilot.press("v")
        await pilot.pause()
        assert "GENERAL MESSAGE (ICS 213)" not in _reader_text(mail)
        # A plain message has no form view, and V does nothing there.
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        assert "Hello" in _reader_text(mail)
        assert table.check_action("toggle_form", ()) is False
