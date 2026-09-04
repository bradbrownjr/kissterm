"""Watching for serial TNCs appearing and disappearing, and nothing else.

The rule this module encodes is an asymmetry, and it is deliberate:

**Serial ports are watched automatically. The network is never scanned
automatically.**

That is not an arbitrary preference, it is a cost difference of four orders of
magnitude, measured rather than assumed:

* Enumerating serial ports (`list_ports.comports()`) takes about **0.4 ms** and
  reads nothing but the local `/sys` tree. Polling it every few seconds is a
  duty cycle of roughly 0.01% and touches no other machine. Plugging in a TNC
  and having the app notice is worth vastly more than that.
* A network sweep is 254 hosts times six well-known ports -- about **1,500 TCP
  connection attempts**. On a timer that is indistinguishable from a port
  scanner, will trip intrusion detection on any managed network, and is plain
  rude on a club or shared link. It happens only when a human asks for it:
  `kissterm --discover`, the setup wizard, or the Settings pane's "Scan for
  hardware" button.

A configured TCP transport that goes away does not need a scan to come back
either -- `TcpKissTransport` already reconnects to its *known* host with
exponential backoff. Re-scanning the whole subnet to rediscover a host whose
address you already have would be pure waste.

Bluetooth is polled only lazily and only for *paired* devices, because that
enumeration shells out to `bluetoothctl`; kissterm never initiates pairing or a
discovery scan, both of which are system-level actions the operator should take
deliberately.

Nothing here transmits. Watching a port is not opening it, and this module
never opens one.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

#: How often to re-enumerate serial ports. Three seconds is well below the time
#: it takes a person to plug in a cable and look at the screen, and at 0.4 ms a
#: call it costs nothing worth measuring.
DEFAULT_POLL_SECONDS = 3.0


@dataclass(slots=True)
class PortEvent:
    """A serial port appeared or disappeared.

    `device` is the path (`/dev/ttyUSB0`). `confidence` and `note` come from
    the same scorer `discovery.py` uses, so a hotplugged device is described to
    the operator exactly as a scanned one would be -- there is one opinion
    about what looks like a TNC, not two.
    """

    action: str  # "added" | "removed"
    device: str
    label: str = ""
    detail: str = ""
    confidence: float = 0.0
    note: str = ""

    @property
    def likely_tnc(self) -> bool:
        """Worth interrupting the operator about.

        0.5 is the generic-bridge-chip score (FTDI, CP210x, CH340): the class
        of adapter nearly every TNC uses. Below that is "unrecognized", which
        is not worth a toast every time somebody plugs in a mouse dongle.
        """
        return self.confidence >= 0.5


class SerialPortWatcher:
    """Polls the local serial port list and reports changes.

    Deliberately poll-based rather than udev-based. `pyudev` would give
    event-driven hotplug with no polling at all, but it is Linux-only and an
    extra dependency, and at 0.4 ms a call the thing it would save is not worth
    either cost. If this ever moves to udev, keep the same event shape so
    nothing above has to change.
    """

    def __init__(
        self,
        interval: float = DEFAULT_POLL_SECONDS,
        on_event: Callable[[PortEvent], None] | None = None,
    ) -> None:
        self.interval = interval
        self._handlers: list[Callable[[PortEvent], None]] = []
        if on_event is not None:
            self._handlers.append(on_event)
        self._known: dict[str, PortEvent] = {}
        self._task: asyncio.Task | None = None
        self.polls = 0

    def subscribe(self, handler: Callable[[PortEvent], None]) -> Callable[[], None]:
        self._handlers.append(handler)

        def _remove() -> None:
            try:
                self._handlers.remove(handler)
            except ValueError:
                pass

        return _remove

    # ------------------------------------------------------------------
    async def prime(self) -> None:
        """Record what is already plugged in, without reporting any of it.

        Called once at startup so the operator is not handed a toast for every
        port that was present before the app launched -- those are not news.
        """
        self._known = {e.device: e for e in await self._snapshot()}

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_event_loop().create_task(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.interval)
                await self.poll()
            except asyncio.CancelledError:
                raise
            except Exception:
                # A watcher that dies on one bad enumeration stops noticing
                # hardware for the rest of the session, silently. Log and
                # keep going.
                logger.exception("serial watcher poll failed")

    async def poll(self) -> list[PortEvent]:
        """One enumeration. Returns the changes and notifies subscribers."""
        self.polls += 1
        current = {e.device: e for e in await self._snapshot()}
        events: list[PortEvent] = []

        for device, entry in current.items():
            if device not in self._known:
                events.append(entry)
        for device, entry in self._known.items():
            if device not in current:
                events.append(
                    PortEvent(
                        action="removed",
                        device=device,
                        label=entry.label,
                        detail=entry.detail,
                        confidence=entry.confidence,
                        note=entry.note,
                    )
                )

        self._known = current
        for event in events:
            for handler in list(self._handlers):
                try:
                    handler(event)
                except Exception:
                    logger.exception("serial watcher handler failed")
        return events

    async def _snapshot(self) -> list[PortEvent]:
        """Current ports, scored. Empty (never raising) if pyserial is absent."""
        try:
            from serial.tools import list_ports  # type: ignore[import-untyped]
        except ImportError:
            return []
        try:
            ports = await asyncio.to_thread(list_ports.comports)
        except Exception as exc:  # noqa: BLE001 -- watching must never raise
            logger.debug("serial watcher: comports() failed: %s", exc)
            return []

        from .discovery import _score_serial_port

        out: list[PortEvent] = []
        for port in ports:
            description = port.description or ""
            manufacturer = getattr(port, "manufacturer", "") or ""
            confidence, note = _score_serial_port(
                description, manufacturer, getattr(port, "vid", None),
                getattr(port, "pid", None),
            )
            out.append(
                PortEvent(
                    action="added",
                    device=port.device,
                    label=port.device,
                    detail=description.strip() or "serial port",
                    confidence=confidence,
                    note=note,
                )
            )
        return out
