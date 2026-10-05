"""`kissterm --serve`: the station with no terminal UI, driven only by
remote clients (ROADMAP P7a M7).

The same core as the terminal UI, started the same way (`ui/app.py`'s
`on_mount`: sessions, station wiring, APRS, runtime settings) and shut
down the same way (`on_unmount`), so a headless station behaves exactly
like one with a screen. **Nothing transmits at startup**: the gate opens
only as configured (`tx_armed_at_start`, default closed) and beacons wait
a full interval, as always.

Questions go only to connected clients; with none connected a question is
cancelled, and a cancelled flow sends nothing (`operator.RemoteOperator`).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys

from ..core import MAX_LINKS, Core
from . import pairing
from .server import RemoteServer

log = logging.getLogger(__name__)


class HeadlessView:
    """`connect.SessionView` with no screen: remembers which session was
    opened last, so "the session in front" means something to the core."""

    def __init__(self, core) -> None:
        self.core = core
        self.active = ""

    def active_key(self) -> str:
        return self.active

    def has_room_for(self, key: str) -> bool:
        sessions = self.core.sessions
        if sessions is None or key in sessions.by_key:
            return True
        return len([k for k in sessions.by_key if k]) < MAX_LINKS

    def open_session(self, key: str, *, kind: str, focus: bool) -> None:
        if focus:
            self.active = key

    def is_active(self, key: str) -> bool:
        return key == self.active

    def focus_input(self) -> None:
        pass


def pairing_text(serve, token: str) -> str:
    """What `--serve` prints: the link, and its QR code when segno is there."""
    url = pairing.pairing_url(serve, token)
    qr = pairing.qr_text(url)
    lines = ["Pair a client with this link (it admits whoever holds it -- keep it private):",
             "", f"  {url}", ""]
    if qr:
        lines += [qr]
    lines += [f"WebSocket: {pairing.websocket_url(serve)}",
              "Rotate it with 'kissterm --serve --rotate-token' if it leaks.", ""]
    return "\n".join(lines)


async def run(config, station=None, session_transport=None, transport_problem=None,
              *, stream=None) -> int:
    """Serve until interrupted (Ctrl+C, SIGTERM)."""
    stream = stream or sys.stdout
    core = Core(config, station, session_transport=session_transport,
                transport_problem=transport_problem)
    server = RemoteServer(core, standalone=True)
    core.operator = server.operator
    core.attach_view(HeadlessView(core))
    core.attach_station()
    core.aprs.start()
    core.settings.apply_runtime()
    try:
        await server.start()
    except OSError as exc:
        print(f"Could not listen on {config.serve.listen}:{config.serve.port}: {exc}",
              file=sys.stderr)
        await _shutdown(core, server)
        return 3
    print(pairing_text(config.serve, server.token), file=stream, flush=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        await _shutdown(core, server)
        await _close_opened_here(core, station, session_transport)
    return 0


async def _close_opened_here(core, station, session_transport) -> None:
    """A transport a client opened from Settings (none would open at
    launch): the launcher closes only what it built itself."""
    with contextlib.suppress(Exception):
        if core.station is not None and core.station is not station:
            await core.station.disconnect_all()
            core.station.close()
            await core.station.transport.close()
        elif core.session_transport is not None and core.session_transport is not session_transport:
            await core.session_transport.close()


async def _shutdown(core, server) -> None:
    """`KissTermApp.on_unmount`'s order: beacons off first, so nothing keys
    the radio while the station is going away."""
    core.aprs.shutdown()
    core.transfers.shutdown()
    core.detach_transport()
    core.connector.cancel_tasks()
    core.sessions.shutdown()
    await server.stop()
    for session in core.sessions.by_key.values():
        link = session.link
        if getattr(link, "internet", False):
            link.close()
            with contextlib.suppress(Exception):
                await link._close_transport()
