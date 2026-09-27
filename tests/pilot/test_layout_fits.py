"""Nothing the operator can press is off the screen, at the sizes people run.

Three reports in two days were the same bug -- a button past the right edge
or below the bottom (Address Book at 100 columns; APRS contacts and the
Terminal tab's "Use node" at 80x24), and a centred dialog taller than an
80x24 screen -- and no test noticed, because each geometry test covered
the one widget someone had looked at. These walk every tab, with its
slide-out open, and the Send/Receive dialogs, and check every control.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm.addressbook import AddressBook  # noqa: E402
from kissterm.app import KissTermApp  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.mail import MessageStore  # noqa: E402
from kissterm.ui import dialogs  # noqa: E402

TABS = ("help", "mail", "bulletins", "files", "terminal", "aprs", "heard", "monitor", "settings")
CONTROLS = "Button, Input, Select, Checkbox"
NOTE = ("G on All Inboxes runs the Home BBS, then Winlink; Winlink needs this "
        "first, or Skip it to run the Home BBS alone.")


def _app(tmp_path) -> KissTermApp:
    config = Config(mycall="KC1JMH", start_tab="mail")
    config.transports = [{"name": "tnc", "kind": "tcp", "host": "127.0.0.1", "port": 8001}]
    app = KissTermApp(config)
    app.addressbook = AddressBook(tmp_path / "addressbook.json")
    for target in ("WS1EC-2", "CCEMA", "WS1EC-7", "WS1EC-15", "W1AW-7"):
        app.addressbook.record_attempt(target)
    app.mail_store = MessageStore(tmp_path / "mail")
    app.mail_store.ensure_default_tree()
    return app


def _off_screen(screen, size) -> list[str]:
    width, height = size
    bad = []
    for widget in screen.query(CONTROLS):
        r = widget.region
        if r.width and (r.x < 0 or r.y < 0 or r.right > width or r.bottom > height):
            bad.append(f"{type(widget).__name__}#{widget.id} at {r}")
    return bad


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(80, 24), (100, 33), (160, 40)])
async def test_every_tab_keeps_its_controls_on_screen(tmp_path, size):
    app = _app(tmp_path)
    async with app.run_test(size=size) as pilot:
        for tab in TABS:
            app.action_show_tab(tab)
            for _ in range(3):
                await pilot.pause()
            assert not _off_screen(app.screen, size), f"{tab} at {size}"
        # The Mail tab's Address Book is opened by hand (Ctrl+G).
        app.action_show_tab("mail")
        await pilot.pause()
        await pilot.press("ctrl+g")
        for _ in range(3):
            await pilot.pause()
        assert not _off_screen(app.screen, size), f"Mail with the Address Book at {size}"


def _setup_dialogs():
    yield dialogs.HomeBbsSetupScreen(["WS1EC-2", "WS1EC-10"], missing="WS1EC-10",
                                     winlink=True, all_note=NOTE, skip="Skip Winlink")
    yield dialogs.HomeBbsSetupScreen(["WS1EC-2"], all_note=NOTE, skip="Skip Home BBS")
    yield dialogs.HomeBbsSetupScreen([], internet=True)
    yield dialogs.HomeBbsSetupScreen(["ws1ec"], internet=True, all_note=NOTE, skip="Skip Home BBS")
    yield dialogs.LoginAskScreen(
        "Winlink password", "The Winlink password for KC1JMH. It never goes on the "
        "air: the gateway sends a challenge, and only the answer to it is sent.",
        "Winlink", all_note=NOTE, skip="Skip Winlink")
    yield dialogs.RadioReminderScreen("145.050", "tnc (tcp)", "a note")


@pytest.mark.asyncio
async def test_send_receive_dialogs_fit_80x24(tmp_path):
    size = (80, 24)
    app = _app(tmp_path)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        for screen in _setup_dialogs():
            app.push_screen(screen)
            for _ in range(3):
                await pilot.pause()
            assert not _off_screen(screen, size), type(screen).__name__
            buttons = screen.query_one("#connect-buttons").region
            box = screen.query_one("#connect-box").region
            assert box.y <= buttons.y and buttons.bottom <= box.bottom, (
                f"{type(screen).__name__}: buttons {buttons} outside the box {box}")
            screen.dismiss(None)
            for _ in range(2):
                await pilot.pause()
