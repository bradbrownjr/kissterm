#!/usr/bin/env python3
"""Regenerate the phone screenshots of the remote control from invented
data. No radio, no phone.

`scripts/generate_screenshot.py` draws the terminal cell by cell; the
remote control is a Flutter page, so it needs a real browser. This runs a
loopback station with the remote server and the web client (the `web`
extra), opens it in headless Chrome at a phone's size, taps through it,
and writes the phone screens, two to an image, and the same station in a
desktop-sized window to `assets/`.

**The browser** is a browserless v2 server when `BROWSERLESS_WS` is set
(`ws://HOST:3000?token=...`, the URL Playwright's `connect_over_cdp`
takes; the token is a credential, so it lives in the environment, never
here), else a local Chromium (`playwright install chromium`). Either way
the station must be reachable from that browser: it listens on every
interface for the minute this runs, admits only a token made for the run,
and `KISSTERM_SHOT_HOST` overrides the address it is reached at.

**The phone's size is set over CDP before the page loads.** Playwright's
own viewport is applied to a browserless page only at the screenshot, so
the app first laid out at 800 px and was caught mid-resize, on the
wide-screen rail (2026-10-05).

**Taps are by name, through Flutter's accessibility tree.** Flutter draws
on a canvas, so until semantics is turned on there are no elements to
find; tapping by position on a timer missed whenever a sheet was slow to
rise (the tap went through to the bottom bar). With semantics on, every
tab, button and field is a named element Playwright waits for, and each
step waits for the text it should bring up. Renaming a button breaks
this script, loudly, rather than drawing a wrong picture.

Invented data, as in the terminal script: `isolate()` before any other
kissterm import, both stations on `tests/loopback.py`, and callsigns from
the W1AW/N1ABC range the tests use.

Needs: pip install -e ".[screenshots]"
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from kissterm._isolate import isolate  # noqa: E402

isolate()

import asyncio  # noqa: E402
import io  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import secrets  # noqa: E402
import socket  # noqa: E402
from urllib.parse import urlsplit  # noqa: E402

from PIL import Image  # noqa: E402
from playwright.async_api import async_playwright  # noqa: E402

from datetime import datetime, timezone  # noqa: E402

from kissterm.core.events import MailChanged  # noqa: E402
from kissterm.mail.message import Message  # noqa: E402
from kissterm.ax25 import AX25Address, AX25Path, AX25Station, LinkParams  # noqa: E402
from kissterm.ax25.frame import AX25Frame, UType  # noqa: E402
from kissterm.config import Config, ServeConfig  # noqa: E402
from kissterm.core import Core  # noqa: E402
from kissterm.geo.project import View  # noqa: E402
from kissterm.client.ui.web import available as web_available  # noqa: E402
from kissterm.serve.headless import HeadlessView  # noqa: E402
from kissterm.serve.server import RemoteServer  # noqa: E402
from tests.loopback import loopback_pair  # noqa: E402

ASSETS = REPO / "assets"
#: A phone in portrait, in CSS pixels, drawn at twice that. Not "mobile":
#: Flutter then takes text only from touch input, and these taps are
#: mouse clicks; the layout follows the width alone.
PHONE = {"width": 390, "height": 844, "deviceScaleFactor": 2, "mobile": False}
#: A laptop's browser window: wide enough for the side rail.
DESKTOP = {"width": 1000, "height": 560, "deviceScaleFactor": 2, "mobile": False}
#: Space between the phones in the composite, and its background.
GAP, BACKDROP = 48, (226, 226, 234)

MYCALL = AX25Address.parse("N1ABC-1")
#: (sender, to, subject, body, minute) for Mail, newest last.
MAIL = (
    ("W1AW", "N1ABC, K1XYZ, W1BKW", "Net tonight at 7",
     "Bring the go-kit and a spare battery.\nWe will start on 147.09.\n73, Hiram\n", 40),
    ("KC1UIX", "N1ABC", "Antenna party Saturday", "Coffee at 8, up the tower by 9.\n", 12),
)
NODE = AX25Address.parse("W1AW-7")

# --- invented content --------------------------------------------------------

NODE_BANNER = (b"Welcome to the W1AW packet node, N1ABC.\r"
               b"\x1b[32mBBS\x1b[0m for mail, \x1b[32mNODES\x1b[0m for the network.\r"
               b"W1AWND:W1AW-7} ")
NODE_HELP = (b"W1AWND:W1AW-7} BBS CHAT CONNECT INFO NODES PORTS ROUTES USERS MHEARD BYE\r"
             b"W1AWND:W1AW-7} ")
#: What the node was sent, so the script knows the session's line went out.
NODE_ASKED: list[bytes] = []
#: Stations heard, oldest first, as (callsign, what they sent).
HEARD = [("W1MRA-1", b"!4351.20N/07016.80W#W1MRA digi, Cumberland"),
         ("KB1QRP", b">On the air from FN43"),
         ("W1AW-2", b"Mail for: N1ABC KC1XYZ"),
         ("K1QRP-7", b"!4337.60N/07019.10W[hiking the Eastern Prom"),
         ("KC1XYZ-9", b"!4346.00N/07022.50W>mobile")]
#: Where W1MRA-1's beacon puts it, for the tap on the map.
W1MRA = (43 + 51.2 / 60, -(70 + 16.8 / 60))
#: An object with coordinates, reported by KC1XYZ-9, for the map.
OBJECT = b";SHELTER  *061830z4344.10N/07032.40WhShelter open, cots for 40"
#: This station's own position (Windham, Maine), so the map shows
#: distances and bearings.
HERE = (43.80, -70.42)
#: An APRS message to us, then the reply after ours.
APRS_IN = b":N1ABC-1  :Are you on the net tonight?{01"
APRS_REPLY = b":N1ABC-1  :Great, see you at 7{02"
OUR_REPLY = "Yes, checking in from home"

# --- the station -------------------------------------------------------------


async def ui(transport, source: str, info: bytes, dest: str = "APRS") -> None:
    frame = AX25Frame.u_frame(AX25Path(AX25Address.parse(dest), AX25Address.parse(source)),
                              UType.UI, info=info)
    await transport.send_frame(frame)


async def start_station():
    ta, tb = loopback_pair()
    await ta.open()
    await tb.open()
    params = LinkParams(t1=0.5, t2=0.05, t3=60.0)
    station = AX25Station(MYCALL, ta, params)
    node = AX25Station(NODE, tb, params, accept_incoming=True)

    def answer(link) -> None:
        asyncio.get_running_loop().call_later(0.3, lambda: asyncio.ensure_future(
            link.send(NODE_BANNER)))
        def asked(data: bytes) -> None:
            NODE_ASKED.append(data)
            asyncio.ensure_future(link.send(NODE_HELP))
        link.on_data.append(asked)
    node.on_incoming.append(answer)

    config = Config(mycall=str(MYCALL), serve=ServeConfig(listen="0.0.0.0", port=0))
    config.aprs.latitude, config.aprs.longitude = HERE
    core = Core(config, station)
    server = RemoteServer(core, token=secrets.token_urlsafe(32), standalone=True)
    core.operator = server.operator
    core.attach_view(HeadlessView(core))
    core.attach_station()
    core.aprs.start()
    core.addressbook.upsert(str(NODE), frequency="145.090", note="Club node")
    core.addressbook.upsert("W1AW-2", frequency="145.090", note="Club BBS")
    core.addressbook.save()
    await server.start()
    for call, info in HEARD:
        await ui(tb, call, info, dest="ID")
    await ui(tb, "KC1XYZ-9", OBJECT)
    return core, server, tb


def reachable_address(towards: str) -> str:
    """This machine's address on the route to the browser's host."""
    if os.environ.get("KISSTERM_SHOT_HOST"):
        return os.environ["KISSTERM_SHOT_HOST"]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect((towards, 9))
        return probe.getsockname()[0]


async def until(condition, timeout: float = 15.0) -> None:
    """Wait for the station to reach `condition`, for what the page cannot
    show the script: text that is selectable, which Flutter leaves out of
    the accessibility tree."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition():
        if loop.time() > deadline:
            raise TimeoutError(f"the station never got there: {condition.__doc__}")
        await asyncio.sleep(0.1)


def thread_has(core, text: str):
    def condition() -> bool:
        convo = core.aprs.conversations.conversations.get("KC1XYZ-9")
        return convo is not None and any(text in m.text for m in convo.messages)
    condition.__doc__ = f"KC1XYZ-9's thread has {text!r}"
    return condition


# --- the phone ---------------------------------------------------------------


class Phone:
    """One page at phone size, driven through Flutter's accessibility tree
    (module docstring)."""

    def __init__(self, page) -> None:
        self.page = page
        self.frames: list[Image.Image] = []

    async def accessible(self) -> None:
        """Turn on Flutter's semantics, which puts named DOM elements over
        the canvas: what a screen reader would announce."""
        page = self.page
        await page.wait_for_selector("flt-semantics-placeholder", state="attached", timeout=60000)
        await page.evaluate("document.querySelector('flt-semantics-placeholder').click()")
        # The transmit switch: in the top bar on every layout.
        await page.get_by_role("button", name=re.compile("^Transmit is")).first.wait_for()

    def button(self, name: str):
        """The last button so named: a sheet's is drawn over the page's.
        An icon button's name is its tooltip, which Flutter puts on a
        wrapper around the button rather than on the button."""
        page = self.page
        return (page.get_by_role("button", name=name)
                .or_(page.get_by_label(name, exact=True)).filter(visible=True).last)

    async def tap(self, target, settle: int = 600) -> None:
        await target.click()
        await self.page.wait_for_timeout(settle)

    async def tab(self, name: str) -> None:
        await self.tap(self.page.get_by_role("tab", name=name))

    async def shown(self, text: str) -> None:
        """Wait for `text` (or a control so named), then for whatever
        brought it to stop moving."""
        page = self.page
        await page.get_by_text(text).or_(page.get_by_label(text, exact=True)).last.wait_for()
        await self.page.wait_for_timeout(800)

    async def swipe(self, target) -> None:
        """Drag `target` to the right, as a thumb would."""
        box = await target.bounding_box()
        y, x = box["y"] + box["height"] / 2, box["x"] + 40
        mouse = self.page.mouse
        await mouse.move(x, y)
        await mouse.down()
        for step in range(1, 21):
            await mouse.move(x + 280 * step / 20, y)
            await self.page.wait_for_timeout(15)
        await mouse.up()

    async def enter(self, text: str) -> None:
        """Type into the page's one text field and send it.

        A tap while the page is still rebuilding (just after a connect
        brings the session forward) focuses nothing and the keys go
        nowhere, so tap until a field has focus, and check what it holds
        before Send. (After the send the element keeps the old value
        while the app shows it empty, so the caller waits on the station.)
        """
        page = self.page
        field = page.get_by_role("textbox").filter(visible=True).last
        for _attempt in range(10):
            await self.tap(field, settle=300)
            if await page.evaluate("document.activeElement?.tagName === 'INPUT'"):
                break
        await page.keyboard.type(text, delay=60)
        if await field.input_value() != text:
            raise RuntimeError(f"typed {text!r}, the field holds {await field.input_value()!r}")
        await self.tap(self.button("Send"))

    async def enter_field(self, label: str, text: str) -> None:
        """Type `text` into the field labelled `label`, without sending."""
        field = self.page.get_by_role("textbox", name=label).filter(visible=True).last
        for _attempt in range(10):
            await self.tap(field, settle=300)
            if await self.page.evaluate("document.activeElement?.tagName === 'TEXTAREA' "
                                        "|| document.activeElement?.tagName === 'INPUT'"):
                break
        await self.page.keyboard.type(text, delay=30)

    async def frame(self) -> None:
        # Off every control, so no tooltip is left showing.
        await self.page.mouse.move(195, 500)
        await self.page.wait_for_timeout(300)
        self.frames.append(Image.open(io.BytesIO(await self.page.screenshot())).convert("RGB"))


async def shot(name: str, frames: list[Image.Image]) -> None:
    """The screens side by side on a backdrop, at the browser's full
    resolution (a README column shows it at about one phone's width
    each, sharp on a high-density display), as `assets/<name>.png`."""
    w, h = frames[0].size
    sheet = Image.new("RGB", (len(frames) * w + (len(frames) + 1) * GAP, h + 2 * GAP), BACKDROP)
    for i, frame in enumerate(frames):
        sheet.paste(frame, (GAP + i * (w + GAP), GAP))
    path = ASSETS / f"{name}.png"
    sheet.save(path, optimize=True)
    print(f"wrote {path.relative_to(REPO)}")


async def open_page(browser, url: str, metrics: dict):
    """A page at `metrics` (CSS size and density), loaded from `url`."""
    # Both: the context's viewport, or Playwright's default replaces the
    # CDP override below.
    context = await browser.new_context(
        viewport={"width": metrics["width"], "height": metrics["height"]},
        device_scale_factor=metrics["deviceScaleFactor"])
    page = await context.new_page()
    cdp = await context.new_cdp_session(page)
    await cdp.send("Emulation.setDeviceMetricsOverride", metrics)
    # A remote browser's tab is not the focused window, and Flutter's text
    # field takes keys only once its hidden input has focus.
    await cdp.send("Emulation.setFocusEmulationEnabled", {"enabled": True})
    await page.bring_to_front()
    await page.goto(url)
    return page


async def drive(phone: Phone, core, tb) -> None:
    await phone.accessible()

    # Stations > Heard: a swipe right on a heard station asks; it does not
    # connect.
    await phone.tab("Stations")
    await phone.tab("Heard")
    await phone.swipe(phone.button("W1AW-2"))
    await phone.shown("Connect to W1AW-2?")
    await phone.frame()
    await phone.tap(phone.button("Cancel"))

    # Contacts > the node: the confirm sheet, then the station's own
    # radio reminder, which is the frame shown.
    await phone.tab("Contacts")
    await phone.tap(phone.button("W1AW-7"))
    await phone.shown("Connect to W1AW-7?")
    await phone.tap(phone.button("Connect"))
    await phone.shown("Check the radio before connecting")
    await phone.frame()
    await phone.tap(phone.button("Connect"))

    # The session, with transmit now on, after asking the node for help.
    await phone.shown("Disconnect")
    await phone.enter("?")
    await until(lambda: NODE_ASKED)
    await phone.page.wait_for_timeout(1500)
    await phone.frame()

    # An APRS message arrives now that transmit is on, so its ack goes out
    # (with transmit off, the station says it could not ack: a true notice,
    # but not this picture).
    await ui(tb, "KC1XYZ-9", APRS_IN)
    await until(thread_has(core, "net tonight"))

    # Messages: the conversation, our reply and theirs.
    await phone.tab("Messages")
    await phone.tap(phone.button("KC1XYZ-9"))
    await phone.enter(OUR_REPLY)
    await until(thread_has(core, OUR_REPLY))
    await ui(tb, "KC1XYZ-9", APRS_REPLY)
    await until(thread_has(core, "see you at 7"))
    await phone.page.wait_for_timeout(1500)
    await phone.frame()

    # The APRS map, from Map beside Position: the heard stations with
    # a position, the shelter object, this station, over the offline
    # outlines; then a tapped station's panel.
    await phone.tap(phone.button("All messages"))
    await phone.page.wait_for_timeout(800)
    await phone.tap(phone.button("Map"))
    await phone.shown("Zoom in")
    await phone.page.wait_for_timeout(2500)
    await phone.frame()
    # The canvas starts under the bar and the map's own row, and fills the
    # width down to the navigation bar. With semantics on, a click on the
    # canvas is its accessible tap, delivered at its centre, while a drag
    # still pans: so W1MRA-1 is dragged to the centre, then tapped.
    top, bottom = 96, PHONE["height"] - 80
    view = View.fit([(p["lat"], p["lon"]) for p in core.aprs.map_points()],
                    PHONE["width"], bottom - top)
    x, y = view.to_screen(*W1MRA)
    centre = (PHONE["width"] / 2, top + (bottom - top) / 2)
    mouse = phone.page.mouse
    await mouse.move(x, top + y)
    await mouse.down()
    for step in range(1, 21):
        await mouse.move(x + (centre[0] - x) * step / 20, top + y + (centre[1] - top - y) * step / 20)
        await phone.page.wait_for_timeout(15)
    await mouse.up()
    await phone.page.wait_for_timeout(500)
    await mouse.click(*centre)
    await phone.shown("Close")  # the panel's; its text is selectable, not in the tree
    await phone.page.wait_for_timeout(800)
    await phone.frame()
    # A long press places an object there: the form, filled in.
    await phone.tap(phone.button("Close"))
    spot = (PHONE["width"] * 0.3, top + (bottom - top) * 0.3)
    await mouse.move(*spot)
    await mouse.down()
    await phone.page.wait_for_timeout(900)
    await mouse.up()
    await phone.shown("APRS object")
    await phone.enter_field("Name", "STAGING")
    await phone.enter_field("Comment", "Net control staging area")
    await phone.frame()

    # BBS Mail: the folder with Write's pencil over Send/Receive, the folder
    # tree opened, a Winlink
    # message in the reader with its actions, then Reply all, written and
    # not yet saved (nothing transmits until Send/Receive).
    for sender, to, subject, body, minutes in MAIL:
        core.mail.store.add("Mail/BBS/Inbox", Message(
            sender=sender, to=to, subject=subject, source="Winlink", body=body,
            date=datetime(2026, 10, 6, 18, minutes, tzinfo=timezone.utc)))
    core.events.publish(MailChanged())  # as a Send/Receive filing it would
    await phone.tab("Mail")
    await phone.shown(MAIL[0][2])
    await phone.frame()
    # The folder tree, opened from the row that shows where you are.
    await phone.tap(phone.page.get_by_text("All Inboxes").first)
    await phone.shown("Inbox")
    await phone.frame()
    await phone.tap(phone.page.get_by_text("All Inboxes").last)
    await phone.shown(MAIL[0][2])
    await phone.tap(phone.button(MAIL[0][2]))
    await phone.shown("Reply all")
    await phone.frame()
    await phone.tap(phone.button("Reply all"))
    await phone.shown("Save to Outbox")
    await phone.enter_field("Message", "I'll be there, with the 2 m rig.")
    await phone.frame()


async def main() -> int:
    if not web_available():
        print("needs the web client: pip install -e '.[screenshots]'", file=sys.stderr)
        return 2
    endpoint = os.environ.get("BROWSERLESS_WS", "")
    core, server, tb = await start_station()
    host = reachable_address(urlsplit(endpoint).hostname if endpoint else "127.0.0.1")
    url = f"http://{host}:{server.port}/#t={server.token}"
    try:
        async with async_playwright() as p:
            if endpoint:
                browser = await p.chromium.connect_over_cdp(endpoint)
            else:
                browser = await p.chromium.launch()
            phone = Phone(await open_page(browser, url, PHONE))
            await drive(phone, core, tb)
            # The same station in a desktop browser, joining late: the
            # session and conversation arrive as the server's replay.
            desktop = Phone(await open_page(browser, url, DESKTOP))
            await desktop.accessible()
            # It opens on Mail; Terminal is the rail's fifth place (Mail,
            # Bulletins, Files, Messages, Terminal), whose labels are not
            # in the accessibility tree: tapped where it is drawn.
            await desktop.shown("Bulletins")
            await desktop.page.mouse.click(40, 80 + 4 * 64)
            await desktop.shown("Disconnect")
            await desktop.frame()
            await browser.close()
        await shot("screenshot-phone-connect", phone.frames[:2])
        await shot("screenshot-phone", phone.frames[2:4])
        await shot("screenshot-phone-map", phone.frames[4:7])
        await shot("screenshot-phone-mail", phone.frames[7:11])
        await shot("screenshot-desktop", desktop.frames)
    finally:
        await server.stop()
        core.aprs.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
