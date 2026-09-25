#!/usr/bin/env python3
"""Regenerate the README screenshots from fabricated data. No radio required.

Runs the real `KissTermApp` under Textual's headless `run_test` pilot against a
loopback transport, feeds it a plausible packet session, and exports SVG (and
PNG, if `cairosvg` is installed) straight into `assets/`.

Everything shown is invented in this file. Nothing here touches a real config
directory, a real TNC, or the air:

* `isolate()` runs before any other kissterm import, so `platformdirs` points
  at a throwaway temp directory. `config.py` computes its paths at import time
  from the same "kissterm" app name the installed app uses -- patching after
  the import is too late, and the repo rule is to never `rmtree` a real
  `platformdirs` result. See `kissterm/_isolate.py`.
* The transport is `tests/loopback.py`, which is wired to a peer object, not to
  hardware. `LoopbackTransport.send_frame` cannot reach a radio.
* The callsigns below are deliberately drawn from the W1AW/N1ABC range used
  throughout this project's tests and docs, so a screenshot never advertises a
  real operator's traffic.

`cairosvg` is a dev-only convenience, not a project dependency -- install it
into the venv when you want PNGs (`\\.venv/bin/pip install cairosvg`). Its
published advisories concern parsing hostile SVG from external sources; this
script renders SVG that Textual just produced locally and fetches nothing.

Re-run this when the layout changes enough to make the committed images stale,
and always eyeball the result before committing: a Textual layout regression
can still "succeed" here while looking wrong.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from kissterm._isolate import isolate  # noqa: E402

isolate()

import asyncio  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams  # noqa: E402
from kissterm.ax25.frame import AX25Frame, UType  # noqa: E402
from kissterm.config import Config  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

ASSETS = REPO / "assets"
SIZE = (110, 32)  # wide enough that the footer bindings do not collide

MYCALL = AX25Address.parse("N1ABC-1")
NODE = AX25Address.parse("W1AW-7")

# --- fabricated content ----------------------------------------------------

SESSION = """*** Connecting to W1AW-7...
*** connected

[W1AW-7] BPQ32 Node  W1AW-7:W1AW-1
Welcome to the W1AW packet node, N1ABC.
Type ? for a list of commands, B to disconnect.

W1AW-7:W1AW-1} ?
Commands: BBS CHAT CONNECT INFO NODES PORTS ROUTES USERS
          MHEARD PING STATS TALK BYE

W1AW-7:W1AW-1} u
Users:
  N1ABC-1  connected 00:04  port 1 (144.390 1200b)
  KC1XYZ   connected 01:12  port 1 (144.390 1200b)

W1AW-7:W1AW-1} """

# (source, dest, via, control text, payload) -- rendered into the monitor pane.
MONITOR = [
    ("KC1XYZ-9", "APRS", ("WIDE1-1",), b"!4221.70N/07107.32W>Mobile, 73"),
    ("W1AW-7", "N1ABC-1", (), b""),
    ("N1ABC-1", "W1AW-7", (), b"u\r"),
    ("W1AW-7", "N1ABC-1", (), b"Users:\r"),
    ("KB1QRP", "BEACON", ("WIDE2-1",), b"W1AW ARES net Thursdays 1930 local on 145.230"),
    ("KC1XYZ-9", "APRS", ("WIDE1-1",), b"=4221.70N/07107.32W>073/019/A=000148"),
]

HEARD = ["KC1XYZ-9", "W1AW-7", "KB1QRP", "N1XYZ-2", "W1MRA-1"]


async def _build():
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    config = Config(
        mycall=str(MYCALL),
        transports=[
            {"name": "Direwolf (LAN)", "kind": "tcp", "host": "192.168.1.40", "port": 8001},
            {"name": "Mobilinkd TNC3", "kind": "serial", "device": "/dev/rfcomm0", "baud": 38400},
        ],
        active_transport="Direwolf (LAN)",
        paclen=256,
        window=4,
        credentials=[{"name": "Personal BBS login", "text": "CLYDE\nMYPASS"}],
    )
    # The screenshots show a live session, so transmit has to be armed --
    # otherwise the README shows a connected link above a "TX OFF" status
    # bar, which is a state that cannot happen and would teach the wrong
    # thing about the gate. See kissterm/tx.py.
    config.tx_armed_at_start = True
    # Show the clock doing something worth seeing: an operator running
    # local+UTC with the date, which is the realistic net-control setup.
    config.show_local_time = True
    config.show_utc_time = True
    config.show_date = True
    config.aprs.latitude = 42.3601
    config.aprs.longitude = -71.0589
    config.aprs.comment = "kissterm test station"
    config.aprs_contacts = [
        {"name": "Jim", "callsign": "K1ABC-9", "service": "station", "notes": ""},
        {"name": "Mom (SMS)", "callsign": "SMSGTE", "service": "sms", "detail": "5551234567"},
    ]
    station = AX25Station(MYCALL, ta, LinkParams(t1=8.0, t2=1.0, t3=180.0))
    station.transport.info.detail = "192.168.1.40:8001"
    return KissTermApp(config, station), ta, tb, station


def _frame(src: str, dest: str, via: tuple[str, ...], info: bytes) -> AX25Frame:
    path = AX25Path(
        AX25Address.parse(dest),
        AX25Address.parse(src),
        tuple(AX25Address.parse(v) for v in via),
    )
    return AX25Frame.u_frame(path, UType.UI, info=info)


async def main() -> int:
    ASSETS.mkdir(exist_ok=True)
    app, ta, tb, station = await _build()

    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()

        # Populate every pane before capturing any of them.
        from kissterm.ui.terminal_pane import TerminalPane

        terminal = app.query_one(TerminalPane)
        terminal.write_note("", SESSION)
        terminal.set_placeholder("", "connected to W1AW-7")
        app._status = "192.168.1.40:8001"

        for src, dest, via, info in MONITOR:
            frame = _frame(src, dest, via, info)
            if src == str(MYCALL):
                # Our own transmission. Sending it from the far end would put
                # it in the monitor with an incoming marker, and the picture
                # would be teaching that we heard ourselves on the air.
                await ta.send_frame(frame)
            else:
                await tb.send_frame(frame)
        for call in HEARD:
            app.heard.record(_frame(call, "APRS", (), b"x"), 0)

        app.aprs_conversations.record_incoming("K1ABC-9", "on the road, ETA 20 min", number="1")
        app.aprs_conversations.record_outgoing("K1ABC-9", "ack1", number=None)
        # A numbered message that came back acked, so the picture shows the
        # delivery status the operator actually cares about rather than only
        # the unackable auto-ack above it.
        app.aprs_conversations.record_outgoing("K1ABC-9", "roger, see you at the site", number="2")
        app.aprs_conversations.mark_acked("K1ABC-9", "2")
        # A second correspondent, so the conversation tab strip has something
        # to be a strip of, and a third station chatting with somebody else
        # entirely so the "All" tab's channel-monitor half is in the picture
        # too. `note_incoming` below turns the second one into the unread
        # marker -- the `*` on the tab and beside the callsign in the list.
        app.aprs_conversations.record_incoming("WS1EC-15", "net starts in 5", number="7")
        app.aprs_conversations.record_incoming("KC1XYZ-9", "K1ABC-9 morning Jim", number="3")

        book = app.addressbook
        book.record_attempt("W1AW-1")
        book.record_connect("W1AW-1")
        book.record_attempt("KB1QRP-15", script="CLYDE\nMYPASS")
        book.record_connect("KB1QRP-15")
        book.record_attempt("N1XYZ-2")
        book.upsert(
            "N1XYZ-2",
            hops="KC1XYZ-9",
            credential="Personal BBS login",
            frequency="146.520 MHz",
            connection_type="Direwolf (LAN)",
            original_target="N1XYZ-2",
        )

        # Mail: invented messages in the same W1AW/N1ABC range as the rest.
        from datetime import datetime, timedelta, timezone

        from kissterm.mail import KIND_BULLETIN, Message

        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        store = app.mail_store
        for folder, msg in (
            ("Mail/BBS/Inbox", Message(sender="N1ABC", to=str(MYCALL), subject="Net control tonight?",
                                       date=now - timedelta(hours=2), source="BBS N1XYZ",
                                       body="Can you take net control at 1900?\n73 de N1ABC\n")),
            ("Mail/BBS/Inbox", Message(sender="KB1QRP", to=str(MYCALL), subject="Antenna party Saturday",
                                       date=now - timedelta(days=1), source="BBS N1XYZ", status="read",
                                       body="Bring a ladder.\n")),
            ("Mail/Winlink/Inbox", Message(sender="W1AW", to=str(MYCALL), subject="ICS-213 exercise",
                                           date=now - timedelta(hours=5), source="Winlink",
                                           body="Exercise traffic.\n")),
            ("Bulletins/WX", Message(sender="N1ABC", to="WX", subject="Coastal flood watch",
                                     date=now - timedelta(hours=3), kind=KIND_BULLETIN,
                                     category="WX", body="Coastal flood watch until 6 PM.\n")),
        ):
            store.add(folder, msg)

        app._refresh_status()  # repaint after populating, not before
        # The slide-outs opened themselves at mount, which was BEFORE any of
        # the above existed, so the tables they painted then were empty.
        # Nothing repaints them again on its own -- opening one by hand used
        # to be what did. Without this every shot with a panel in it is a
        # picture of an empty table.
        from kissterm.ui.addressbook_pane import AddressBookPane
        from kissterm.ui.aprs_pane import AprsPane as _Aprs

        app.query_one(AddressBookPane).refresh_from(app.addressbook)
        app.query_one(_Aprs).refresh_from(app.config.aprs_contacts)
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()

        shots = {
            "mail": "screenshot-mail.svg",
            "terminal": "screenshot.svg",
            "monitor": "screenshot-monitor.svg",
            "heard": "screenshot-heard.svg",
            "heard-radar": "screenshot-heard-radar.svg",
            "aprs": "screenshot-aprs.svg",
            "settings": "screenshot-settings.svg",
        }
        written = []
        for tab, name in shots.items():
            app.action_show_tab("heard" if tab == "heard-radar" else tab)
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()
            if tab == "mail":
                from kissterm.ui.mail_pane import MessageBrowser, MessageList

                browser = app.query_one("#mail-browser", MessageBrowser)
                browser.reload()
                await pilot.pause()
                browser.query_one(MessageList).focus()
                browser.open_selected()
                await pilot.pause()
            if tab == "heard-radar":
                from kissterm.ui.heard_pane import HeardPane

                app.query_one(HeardPane)._toggle_radar()
                await pilot.pause()
            if tab == "aprs":
                from kissterm.ui.aprs_pane import AprsPane

                pane = app.query_one(AprsPane)
                # An unread tab first, then the one being read -- in that
                # order, so the picture shows a `*` tab sitting NEXT TO the
                # active conversation rather than the marker landing on the
                # tab we then open and clear.
                pane.note_incoming("WS1EC-15", to_me=True)
                pane._show_conversation(0)
                await pilot.pause()
            app.save_screenshot(str(ASSETS / name))
            written.append(ASSETS / name)

        # Capture both states of the passive watchlist controls.  The normal
        # Settings screenshot shows the rest of the form; these focused shots
        # make the off-by-default and configured wording reviewable without
        # any desktop-notification endpoint or received-frame activity.
        from kissterm.ui.settings_pane import SettingsPane

        app.action_show_tab("settings")
        settings = app.query_one(SettingsPane)
        settings.show_section("Alerts")
        await pilot.pause()
        watch_disabled = ASSETS / "screenshot-watched-callsigns-disabled.svg"
        app.save_screenshot(str(watch_disabled))
        written.append(watch_disabled)

        app.config.watched_callsigns.enabled = True
        app.config.watched_callsigns.callsigns = ["W1AW-2", "N1ABC"]
        app.config.watched_callsigns.cooldown_minutes = 30
        app.config.watched_callsigns.hourly_cap = 6
        app.config.watched_callsigns.quiet_start_hour = 22
        app.config.watched_callsigns.quiet_end_hour = 7
        app.config.watched_callsigns.active_suppression_seconds = 90
        settings.render_settings(app.config)
        settings.show_section("Alerts")
        from textual.widgets import Collapsible

        settings.query_one("#settings-tab-alerts-advanced", Collapsible).collapsed = False
        await pilot.pause()
        watch_configured = ASSETS / "screenshot-watched-callsigns-configured.svg"
        app.save_screenshot(str(watch_configured))
        written.append(watch_configured)

        # The APRS contacts slide-out, where the shipped gateway directory is
        # actually read. Captured on its own because that list -- saved
        # contacts, then every gateway service with its description -- is the
        # part of this pane most likely to break a layout, and it is invisible
        # in the shot above.
        from kissterm.ui.aprs_pane import AprsPane as _AprsPane

        app.action_show_tab("aprs")
        await pilot.pause()
        # ENSURE open, never toggle: at this width the width rule
        # (`kissterm/ui/slideouts.py`) has already opened it, so a blind
        # toggle here would close the panel this shot exists to show.
        _aprs_pane = app.query_one(_AprsPane)
        if not app.query_one("#aprs-contacts-column").display:
            _aprs_pane.toggle_contacts()
        # On the "All" tab, so this shot carries the merged view as well as
        # the directory. Since the contact list opens itself at this width it
        # would otherwise be the same picture as the one above.
        app.query_one("#aprs-convo-tabs").active = "convo-ALL"
        await pilot.pause()
        await asyncio.sleep(0.15)
        await pilot.pause()
        contacts_shot = ASSETS / "screenshot-aprs-contacts.svg"
        app.save_screenshot(str(contacts_shot))
        written.append(contacts_shot)

        # The Address Book is now a Ctrl+G slide-out on the Terminal pane,
        # not its own tab -- open it here for its own screenshot rather than
        # switching to a tab that no longer exists.
        app.action_show_tab("terminal")
        await pilot.pause()
        if not app.query_one("#terminal-addressbook-column").display:
            terminal.toggle_addressbook()  # ensure open -- see the note above
        await pilot.pause()
        await asyncio.sleep(0.15)
        await pilot.pause()
        addressbook_shot = ASSETS / "screenshot-addressbook.svg"
        app.save_screenshot(str(addressbook_shot))
        written.append(addressbook_shot)

    station.close()

    for svg in written:
        print(f"wrote {svg.relative_to(REPO)}")
        try:
            import cairosvg
        except ImportError:
            continue
        png = svg.with_suffix(".png")
        cairosvg.svg2png(url=str(svg), write_to=str(png), output_width=1400)
        print(f"wrote {png.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
