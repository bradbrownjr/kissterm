#!/usr/bin/env python3
"""Regenerate the README screenshots from invented data. No radio required.

Runs the real `KissTermApp` under Textual's headless `run_test` pilot against a
loopback transport, fills it with a plausible station's mail, bulletins,
files, a node session and APRS traffic, and captures one screen per tab as
SVG. The SVGs are then rendered to PNG in `assets/` by headless Chrome.

Why Chrome, not cairosvg (operator, 2026-09-29: "the screenshots have broken
lines in the rendering"): Textual's SVG names the Fira Code web font. cairosvg
cannot load a web font, falls back to a system font whose box-drawing
characters are shorter than a row, and every border comes out dashed. An SVG
put straight into the README fails the same way, because GitHub serves it as
an image and an image cannot load fonts either. A real browser loads the font
and the borders join.

Set `KISSTERM_SHOT_RENDERER` to a browserless-compatible `/screenshot`
endpoint, token included, for example
`http://host:3000/screenshot?token=...`. It is read from the environment so
no address or token is ever committed. Without it the SVGs are written to a
temporary folder, `assets/` is left alone, and the script says so.

Everything shown is invented here. Nothing touches a real config directory,
a real TNC, or the air:

* `isolate()` runs before any other kissterm import, so `platformdirs` points
  at a throwaway temp directory (`kissterm/_isolate.py`).
* Both stations are on `tests/loopback.py`, wired to each other, not to
  hardware.
* Callsigns are from the W1AW/N1ABC range used throughout the tests, so a
  screenshot never shows a real operator's traffic.

Look at every image before committing: a layout regression still "succeeds"
here.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from kissterm._isolate import isolate  # noqa: E402

isolate()

import asyncio  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

from kissterm.app import KissTermApp  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams  # noqa: E402
from kissterm.ax25.frame import AX25Frame, UType  # noqa: E402
from kissterm.config import Config, set_credential  # noqa: E402
from kissterm.mail import KIND_BULLETIN, Message  # noqa: E402
from kissterm.mail.forms import defaults, get_form, render  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

ASSETS = REPO / "assets"
SIZE = (110, 32)  # wide enough that the footer's keys do not collide
#: Chrome's pixels per SVG pixel: sharp on a high-density screen, and the
#: README shows it scaled down anyway.
SCALE = 1.25

MYCALL = AX25Address.parse("N1ABC-1")
NODE = AX25Address.parse("W1AW-7")

# --- invented content --------------------------------------------------------

#: The node, then its BBS, as a BPQ32 node and BPQMail word them, so the
#: terminal recognises both and suggests the BBS's commands.
NODE_BANNER = (b"Welcome to the W1AW packet node, N1ABC.\r"
               b"Type ? for a list of commands.\r"
               b"W1AWND:W1AW-7} ")
NODE_HELP = (b"W1AWND:W1AW-7} BBS CHAT CONNECT INFO NODES PORTS ROUTES USERS MHEARD BYE\r"
             b"W1AWND:W1AW-7} ")
BBS_GREETING = (b"W1AWND:W1AW-7} Connected to BBS\r"
                b"[BPQ-6.0.24.1-B2FWIHJM$]\r"
                b"Hello Alex. Welcome back to W1AW-2 BBS.\r"
                b"You have 2 messages waiting for you.\r"
                b"de W1AW>\r")

MONITOR = [
    ("KC1XYZ-9", "APRS", ("WIDE1-1",), b"!4348.10N/07025.80W>Mobile, 73"),
    ("KB1QRP", "BEACON", ("WIDE2-1",), b"ARES net Thursdays 1930 local on 145.230"),
    ("W1AW-2", "MAIL", (), b"Mail for: N1ABC KC1XYZ"),
    ("KC1XYZ-9", "APRS", ("WIDE1-1",), b"=4347.60N/07026.40W>073/019/A=000148"),
    ("W1AW-7", "ID", (), b"W1AWND:W1AW-7 FN43rs"),
]

HEARD = ["KC1XYZ-9", "W1AW-7", "W1AW-2", "KB1QRP", "N1XYZ-2", "W1MRA-1"]

#: Files: the shapes a new operator meets -- a Winlink attachment, a
#: downloaded net roster, a received file.
FILES = {
    "Files/Attachments": {
        "shelter-status.txt": "Shelter at Town Hall: open, 42 cots, generator on.\n",
        "damage-photo.jpg": b"\xff\xd8\xff\xe0" + b"\x00" * 2048,
    },
    "Files/Downloads": {
        "ares-net-roster.txt": ("Cumberland ARES net roster\n\nN1ABC  Alex   Windham\n"
                                "KC1XYZ Jim    Gray\nKB1QRP Pat    Standish\n"),
        "net-preamble.txt": ("This is the ARES training net. Stations with emergency or "
                             "priority traffic, call now.\n"),
    },
    "Files/Received": {
        "repeater-coverage.txt": "147.090 coverage notes from the Saturday drive test.\n",
    },
}


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
    )
    set_credential(config, "W1AW-2 BBS", "not-a-real-password", username="N1ABC")
    config.home_bbs.route = "W1AW-2"
    config.winlink.route = "W1AW-10"
    # A connected link above "TX OFF" cannot happen; the pictures show a
    # live station (kissterm/tx.py).
    config.tx_armed_at_start = True
    config.show_local_time = True
    config.show_utc_time = True
    config.show_date = True
    config.aprs.latitude = 43.7442
    config.aprs.longitude = -70.4495
    config.aprs.comment = "kissterm test station"
    config.aprs_contacts = [
        {"name": "Jim", "callsign": "KC1XYZ-9", "service": "station", "notes": ""},
        {"name": "Net control", "callsign": "W1AW-7", "service": "station", "notes": ""},
    ]
    station = AX25Station(MYCALL, ta, LinkParams(t1=8.0, t2=0.2, t3=180.0))
    station.transport.info.detail = "192.168.1.40:8001"
    node = AX25Station(NODE, tb, LinkParams(t1=8.0, t2=0.2, t3=180.0))
    return KissTermApp(config, station), ta, tb, station, node


def _frame(src: str, dest: str, via: tuple[str, ...], info: bytes) -> AX25Frame:
    path = AX25Path(
        AX25Address.parse(dest),
        AX25Address.parse(src),
        tuple(AX25Address.parse(v) for v in via),
    )
    return AX25Frame.u_frame(path, UType.UI, info=info)


def _fill_mail(app) -> None:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    store = app.mail_store
    form = get_form("ics213")
    values = defaults(form, mycall="W1AW", grid="FN43", now=now - timedelta(hours=5))
    values.update({
        "inc_name": "SHELTER DRILL", "To_Name": "N1ABC, EOC RADIO", "fm_name": "W1AW, TOWN HALL",
        "Subjectline": "Shelter status", "Message": "Shelter open at Town Hall.\n"
        "42 cots in place, generator running.\nRequest 20 more blankets by 1800.",
        "Approved_Name": "J SMITH", "Approved_PosTitle": "SHELTER MANAGER",
    })
    subject, body = render(form, values)
    for folder, msg in (
        ("Mail/BBS/Inbox", Message(
            sender="KC1XYZ", to="N1ABC", subject="Net control Thursday?",
            date=now - timedelta(hours=2), source="W1AW-2",
            body="Alex,\n\nCan you take net control Thursday at 1930? I will be at the\n"
                 "hospital drill until 2000.\n\nThe preamble is in the Files tab if you\n"
                 "need it.\n\n73 de Jim KC1XYZ\n")),
        ("Mail/BBS/Inbox", Message(
            sender="KB1QRP", to="N1ABC", subject="Antenna party Saturday",
            date=now - timedelta(days=1), source="W1AW-2", status="read",
            body="Bring a ladder and a thermos.\n")),
        ("Mail/Winlink/Inbox", Message(
            sender="W1AW", to="N1ABC", subject=subject, date=now - timedelta(hours=5),
            source="Winlink", body=body)),
        ("Mail/Winlink/Inbox", Message(
            sender="N1XYZ", to="N1ABC", subject="Winlink check-in received",
            date=now - timedelta(days=2), source="Winlink", status="read",
            body="Your check-in was logged. Thanks for joining the exercise.\n")),
        ("Mail/BBS/Sent", Message(
            sender="N1ABC", to="KC1XYZ", subject="Re: Antenna party Saturday",
            date=now - timedelta(hours=20), source="W1AW-2", status="read",
            body="I'll be there with the ladder.\n")),
    ):
        store.add(folder, msg)
    for category, sender, subject, hours, text in (
        ("WX", "W1AW", "Coastal flood watch until 1800", 3,
         "Coastal flood watch for Cumberland and York counties until 6 PM.\n"
         "Splash-over possible at the evening high tide.\n"),
        ("WX", "KB1QRP", "Skywarn activation tonight", 6,
         "Skywarn nets activate at 1900 on 147.090. Spotters please check in.\n"),
        ("ARES", "KC1XYZ", "ARES training net Thursday", 26,
         "Thursday 1930 local on 145.230. Topic: passing an ICS-213 by packet.\n"),
        ("ALL", "W1AW", "New digipeater on Mount Agamenticus", 50,
         "W1AW-3 is on the air as a WIDE digipeater. Reports welcome.\n"),
    ):
        store.add(f"Bulletins/{category}", Message(
            sender=sender, to=category, subject=subject, date=now - timedelta(hours=hours),
            kind=KIND_BULLETIN, category=category, source="W1AW-2", body=text,
            status="read" if hours > 24 else "new"))
    for folder, files in FILES.items():
        directory = store.root.joinpath(*folder.split("/"))
        directory.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            path = directory / name
            if isinstance(data, bytes):
                path.write_bytes(data)
            else:
                path.write_text(data)


async def _pause(pilot, seconds: float = 0.15) -> None:
    await pilot.pause()
    await asyncio.sleep(seconds)
    await pilot.pause()


async def _show(app, pilot, browser_id: str, folder: str, row: int = 0) -> None:
    """Open `folder` in a browser, with row `row` selected and read."""
    from kissterm.ui.mail_pane import MessageBrowser, MessageList

    # A tab shown for the first time highlights its first folder; let that
    # land before choosing, or it replaces the folder chosen here.
    await _pause(pilot, 0.3)
    browser = app.query_one(f"#{browser_id}", MessageBrowser)
    browser.reload()
    browser.show_folder(folder)
    browser._select_tree_node()  # the tree shows the folder the list does
    await _pause(pilot)
    listing = browser.query_one(MessageList)
    listing.focus()
    listing.move_cursor(row=row)
    browser.open_selected()
    await _pause(pilot)


async def _node_session(app, pilot, node) -> None:
    """A real link to the invented node: its banner, then its BBS, with the
    BBS's send commands suggested for "S" -- what a newcomer sees at a
    prompt. The Address Book panel is shut so the session has the width."""
    from kissterm.ui.terminal_pane import TerminalPane

    def answer(link) -> None:
        def heard(data: bytes) -> None:
            command = data.decode("latin-1").strip().upper()
            reply = {"?": NODE_HELP, "BBS": BBS_GREETING}.get(command)
            if reply:
                asyncio.get_event_loop().create_task(link.send(reply))

        link.on_data.append(heard)

        async def banner() -> None:
            await asyncio.sleep(0.3)  # after the terminal has bound the link
            await link.send(NODE_BANNER)

        asyncio.get_event_loop().create_task(banner())

    node.on_incoming.append(answer)
    app.action_show_tab("terminal")
    await _pause(pilot)
    pane = app.query_one(TerminalPane)
    if app.query_one("#terminal-addressbook-column").display:
        pane.toggle_addressbook()
    link = await app.station.connect(AX25Path(NODE, MYCALL))
    app._bind_link(link)
    await _pause(pilot, 1.0)
    for command in ("?", "BBS"):
        await pane.send_line(command)
        await _pause(pilot, 1.0)
    field = pane.query_one("#session-input")
    field.value = "S"
    pane._update_suggestions("S")
    field.focus()
    await _pause(pilot)


async def main() -> int:
    renderer = os.environ.get("KISSTERM_SHOT_RENDERER", "")
    out = Path(tempfile.mkdtemp(prefix="kissterm-shots-"))
    app, ta, tb, station, node = await _build()
    shots: list[str] = []

    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()

        async def shot(name: str) -> None:
            app.save_screenshot(f"{name}.svg", str(out))
            shots.append(name)

        for src, dest, via, info in MONITOR:
            await tb.send_frame(_frame(src, dest, via, info))
        for call in HEARD:
            app.heard.record(_frame(call, "APRS", (), b"x"), 0)
        app.aprs_conversations.record_incoming("KC1XYZ-9", "on the road, ETA 20 min", number="1")
        app.aprs_conversations.record_outgoing("KC1XYZ-9", "roger, see you at the site",
                                               number="2")
        app.aprs_conversations.mark_acked("KC1XYZ-9", "2")
        app.aprs_conversations.record_incoming("W1AW-7", "net starts in 5", number="7")
        book = app.addressbook
        for target, kwargs in (
            ("W1AW-7", {"note": "the local node"}),
            ("W1AW-2", {"credential": "W1AW-2 BBS", "note": "home BBS"}),
            ("W1AW-10", {"note": "Winlink RMS gateway"}),
            ("N1XYZ-2", {"hops": "W1AW-7", "frequency": "145.050 MHz",
                         "connection_type": "Direwolf (LAN)"}),
        ):
            book.record_attempt(target)
            book.record_connect(target)
            book.upsert(target, original_target=target, **kwargs)
        _fill_mail(app)
        app._refresh_status()
        await _pause(pilot)

        # 1. Mail: every inbox at once, a BBS message open.
        app.action_show_tab("mail")
        await _show(app, pilot, "mail-browser", "All Inboxes")
        await shot("screenshot-mail")
        # 2. A received ICS-213, shown as the form it is.
        await _show(app, pilot, "mail-browser", "Mail/Winlink/Inbox")
        await shot("screenshot-mail-form")
        # 3. Filling one in.
        from kissterm.ui.form_screen import FormScreen

        app.push_screen(FormScreen(get_form("ics213"), mycall="N1ABC", grid="FN43",
                                   values={"inc_name": "SHELTER DRILL",
                                           "To_Name": "W1AW, TOWN HALL",
                                           "fm_name": "N1ABC, EOC RADIO",
                                           "Subjectline": "Blankets on the way",
                                           "Message": "20 blankets leave the EOC at 1630.\n"
                                                      "ETA Town Hall 1700."}))
        await _pause(pilot, 0.3)
        await shot("screenshot-form")
        app.pop_screen()
        await _pause(pilot)
        # 4. Bulletins by category.
        app.action_show_tab("bulletins")
        await _show(app, pilot, "bulletins-browser", "Bulletins/WX")
        await shot("screenshot-bulletins")
        # 5. Files.
        app.action_show_tab("files")
        await _show(app, pilot, "files-browser", "Files/Attachments", row=1)
        await shot("screenshot-files")
        # 6. The terminal at a BBS prompt, its commands suggested.
        await _node_session(app, pilot, node)
        await shot("screenshot-terminal")
        # 7. APRS.
        from kissterm.ui.aprs_pane import AprsPane

        app.action_show_tab("aprs")
        pane = app.query_one(AprsPane)
        pane.refresh_from(app.config.aprs_contacts)
        pane.note_incoming("W1AW-7", to_me=True)
        pane._show_conversation(0)
        await _pause(pilot)
        await shot("screenshot-aprs")
        # 8. Heard, Monitor, Settings.
        for tab in ("heard", "monitor"):
            app.action_show_tab(tab)
            await _pause(pilot)
            await shot(f"screenshot-{tab}")
        from kissterm.ui.settings_pane import SettingsPane

        app.action_show_tab("settings")
        app.query_one(SettingsPane).show_section("Mail")
        await _pause(pilot)
        await shot("screenshot-settings")

    station.close()
    node.close()

    if not renderer:
        print(f"SVGs in {out}. assets/ unchanged: set KISSTERM_SHOT_RENDERER to a "
              "browserless-compatible /screenshot URL to render PNGs (see the docstring).")
        return 1
    for name in shots:
        png = ASSETS / f"{name}.png"
        png.write_bytes(_render(renderer, (out / f"{name}.svg").read_text()))
        print(f"wrote {png.relative_to(REPO)}")
    return 0


def _render(renderer: str, svg: str) -> bytes:
    """One SVG as PNG, by headless Chrome (see the module docstring)."""
    box = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    width, height = (int(float(box[1])) + 1, int(float(box[2])) + 1) if box else (1400, 900)
    body = json.dumps({
        "html": f'<!doctype html><html><body style="margin:0">{svg}</body></html>',
        "viewport": {"width": width, "height": height, "deviceScaleFactor": SCALE},
        "options": {"type": "png"},
        # The font comes from a CDN; give it time to arrive.
        "waitForTimeout": 1500,
    }).encode()
    request = urllib.request.Request(renderer, data=body,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
