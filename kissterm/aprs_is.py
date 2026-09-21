"""A small APRS-IS stream client for operator-visible diagnostics.

This stays outside :mod:`kissterm.aprs`: APRS parsing is pure and works on RF
frames, while APRS-IS is a TCP text protocol.  The UI uses an unverified
``pass -1`` login.  ``AprsIsAccess`` also represents a verified login, so a
future authorised gateway can reuse the connection/authentication seam
without weakening the watcher's safety contract.  This module has no
packet-publish method.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .monitor import sanitize

DEFAULT_HOST = "rotate.aprs2.net"
DEFAULT_PORT = 14580


class AprsIsMode(str, Enum):
    RECEIVE_ONLY = "receive-only"
    VERIFIED = "verified"


@dataclass(frozen=True, slots=True)
class AprsIsAccess:
    """Login authority for one APRS-IS connection, not a send policy."""

    mode: AprsIsMode = AprsIsMode.RECEIVE_ONLY
    passcode: str | None = None

    def login_pass(self) -> str:
        if self.mode is AprsIsMode.RECEIVE_ONLY:
            return "-1"
        if not self.passcode or not self.passcode.strip():
            raise ValueError("a verified APRS-IS login needs a passcode")
        return self.passcode.strip()


def callsign_filter(callsign: str) -> str:
    """Subscribe to traffic from, and messages addressed to, ``callsign``."""
    call = callsign.strip().upper()
    if not call:
        raise ValueError("an APRS-IS watch needs a callsign")
    return f"b/{call} g/{call}"


def login_line(callsign: str, access: AprsIsAccess, *, filter_text: str) -> bytes:
    """Build the only bytes this client writes: its APRS-IS login."""
    call = callsign.strip().upper()
    if not call:
        raise ValueError("an APRS-IS login needs a callsign")
    return (
        f"user {call} pass {access.login_pass()} vers kissterm watch filter {filter_text}\r\n"
    ).encode("ascii")


class AprsIsWatch:
    """A bounded raw APRS-IS observer with no packet-publish capability."""

    def __init__(self, *, max_lines: int = 500) -> None:
        self.lines: deque[str] = deque(maxlen=max_lines)
        self.status = "Stopped"
        self._task: asyncio.Task[None] | None = None
        self._listeners: list[Callable[[], None]] = []

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                self._listeners.remove(listener)

        return unsubscribe

    def _changed(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    def start(
        self, *, callsign: str, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
        access: AprsIsAccess = AprsIsAccess(),
    ) -> None:
        if self.running:
            return
        filter_text = callsign_filter(callsign)
        self.lines.clear()
        self.status = f"Connecting to {host}:{port} ({access.mode.value})"
        self._changed()
        self._task = asyncio.create_task(
            self._run(callsign, host, port, access, filter_text), name="aprs-is-watch"
        )

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
        self.status = "Stopped"
        self._changed()

    async def _run(
        self, callsign: str, host: str, port: int, access: AprsIsAccess, filter_text: str
    ) -> None:
        writer: asyncio.StreamWriter | None = None
        try:
            reader, writer = await asyncio.open_connection(host, port)
            writer.write(login_line(callsign, access, filter_text=filter_text))
            await writer.drain()
            self.status = f"Watching {host}:{port} ({access.mode.value})"
            self._changed()
            while line := await reader.readline():
                clean = sanitize(line, keep_newlines=False).rstrip()
                if clean:
                    self.lines.append(clean)
                    self._changed()
            self.status = "Disconnected by APRS-IS"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.status = f"APRS-IS error: {exc}"
        finally:
            if writer is not None:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
            self._changed()
