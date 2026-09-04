"""Transport abstractions -- the two tiers every kissterm backend falls into.

This split is the central architectural decision in kissterm, and getting it
wrong is what makes a packet terminal accrete special cases:

**Frame transports** (`FrameTransport`) move *AX.25 frames*. They have no idea
what a connection is. KISS over serial, KISS over TCP, KISS over Bluetooth, and
AGWPE raw mode all live here. Frames from these go into kissterm's own AX.25
state machine (`kissterm.ax25.session`), which is what makes kissterm work with
no kernel AX.25 stack -- the thing linpac cannot do.

**Session transports** (`SessionTransport`) hand back an *already-connected
byte stream*. VARA HF/FM, Mercury, AGWPE connected mode, and the Linux kernel's
own ``AF_AX25`` sockets live here. The modem or kernel already ran the link
layer; kissterm's state machine is bypassed entirely and would corrupt the link
if it were not.

Everything above this layer -- the terminal panes, logging, file transfer --
talks to `Session`, so it never needs to know which tier it is sitting on.
"""

from __future__ import annotations

import abc
import asyncio
import enum
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Deferred to type-checking only: kissterm.ax25 imports back from this
    # module (AX25Station and the link layer both hold a Session/transport
    # reference), so an eager import here would make `kissterm.ax25` and
    # `kissterm.transport.base` a hard import cycle -- whichever side
    # happens to be imported first would find the other only partially
    # initialized. Every use of AX25Path/AX25Frame below is in a type
    # annotation, which `from __future__ import annotations` (above) turns
    # into a string that is never evaluated at runtime, so no runtime
    # import of kissterm.ax25 is actually needed in this module.
    from ..ax25.address import AX25Path
    from ..ax25.frame import AX25Frame


class TransportState(enum.Enum):
    CLOSED = "closed"
    OPENING = "opening"
    OPEN = "open"
    ERROR = "error"


class SessionState(enum.Enum):
    """Link states, named after AX.25 2.2 section 6 where they correspond.

    `TIMER_RECOVERY` is not "an error" -- it is the normal state after a T1
    expiry while the link probes whether the other end is still there. A busy
    HF path can spend a lot of time here and still be perfectly healthy.
    """

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    TIMER_RECOVERY = "timer-recovery"
    DISCONNECTING = "disconnecting"
    FAILED = "failed"


class TransportError(Exception):
    """A transport could not be opened, or died while open."""


@dataclass(slots=True)
class TransportInfo:
    """What the setup wizard and the status bar show about a transport.

    `kind` is the config key (``"serial"``, ``"tcp"``, ``"vara"``); `detail` is
    the human string (``"/dev/ttyUSB0 @ 9600"``, ``"192.168.1.40:8001"``).
    """

    kind: str
    name: str
    detail: str = ""
    tier: str = "frame"  # "frame" | "session"


class Transport(abc.ABC):
    """Common lifecycle for both tiers."""

    def __init__(self, info: TransportInfo) -> None:
        self.info = info
        self.state = TransportState.CLOSED
        self._error: str = ""

    @property
    def error(self) -> str:
        return self._error

    @abc.abstractmethod
    async def open(self) -> None: ...

    @abc.abstractmethod
    async def close(self) -> None: ...

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.info.detail} {self.state.value}>"


FrameHandler = Callable[["AX25Frame", int], "Awaitable[None] | None"]


class FrameTransport(Transport):
    """A transport that carries whole AX.25 frames, in both directions.

    Subclasses implement `send_frame` and pump received frames into
    `dispatch`. ``port`` is the KISS/AGW port number -- a multi-port TNC such
    as Direwolf with two channels presents one transport with two ports, not
    two transports, because they share one link to the hardware.
    """

    def __init__(self, info: TransportInfo, ports: int = 1) -> None:
        super().__init__(info)
        self.ports = ports
        self._handlers: list[FrameHandler] = []

    def subscribe(self, handler: FrameHandler) -> Callable[[], None]:
        """Register a frame callback; returns an unsubscribe callable.

        Every subscriber sees every frame -- the monitor pane, the heard list,
        the APRS decoder, and each open session all sit on this one fan-out,
        so a frame is decoded once no matter how many things care about it.
        """
        self._handlers.append(handler)

        def _remove() -> None:
            try:
                self._handlers.remove(handler)
            except ValueError:
                pass

        return _remove

    async def dispatch(self, frame: AX25Frame, port: int = 0) -> None:
        for handler in list(self._handlers):
            result = handler(frame, port)
            if asyncio.iscoroutine(result):
                await result

    @abc.abstractmethod
    async def send_frame(self, frame: AX25Frame, port: int = 0) -> None: ...


class SessionTransport(Transport):
    """A transport that connects and disconnects on its own.

    `connect` returns a `Session` that is already up. There is no frame-level
    access -- these modems do not expose one, and pretending otherwise is how
    you end up with a KISS abstraction that lies about VARA.
    """

    @abc.abstractmethod
    async def connect(self, path: AX25Path) -> "Session": ...


@dataclass
class Session:
    """One connected conversation, whichever tier produced it.

    The UI reads `incoming` and writes with `send`; it never learns whether a
    state machine or a VARA modem is behind them.
    """

    path: AX25Path
    transport: Transport
    state: SessionState = SessionState.DISCONNECTED
    incoming: asyncio.Queue[bytes] = field(default_factory=asyncio.Queue)
    _on_state: list[Callable[["Session", SessionState], None]] = field(
        default_factory=list, repr=False
    )
    _sender: Callable[[bytes], Awaitable[None]] | None = field(default=None, repr=False)
    _closer: Callable[[], Awaitable[None]] | None = field(default=None, repr=False)

    @property
    def peer(self) -> str:
        return str(self.path.destination)

    def on_state_change(self, cb: Callable[["Session", SessionState], None]) -> None:
        self._on_state.append(cb)

    def set_state(self, state: SessionState) -> None:
        if state is self.state:
            return
        self.state = state
        for cb in list(self._on_state):
            cb(self, state)

    async def deliver(self, data: bytes) -> None:
        """Push received bytes toward the UI. Called by the owning transport."""
        await self.incoming.put(data)

    async def send(self, data: bytes) -> None:
        if self._sender is None:
            raise TransportError("session has no sender bound")
        await self._sender(data)

    async def close(self) -> None:
        if self._closer is not None:
            await self._closer()
