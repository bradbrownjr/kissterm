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
    )
    config.aprs.latitude = 42.3601
    config.aprs.longitude = -71.0589
    config.aprs.comment = "kissterm test station"
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
        terminal.log(SESSION)
        terminal.set_placeholder("connected to W1AW-7")
        app._status = "192.168.1.40:8001"

        for src, dest, via, info in MONITOR:
            await tb.send_frame(_frame(src, dest, via, info))
        for call in HEARD:
            app.heard.record(_frame(call, "APRS", (), b"x"), 0)
        app._refresh_status()  # repaint after populating, not before
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()

        shots = {
            "terminal": "screenshot.svg",
            "monitor": "screenshot-monitor.svg",
            "heard": "screenshot-heard.svg",
            "settings": "screenshot-settings.svg",
        }
        written = []
        for tab, name in shots.items():
            app.action_show_tab(tab)
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()
            app.save_screenshot(str(ASSETS / name))
            written.append(ASSETS / name)

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
