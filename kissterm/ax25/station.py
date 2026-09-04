"""`AX25Station` -- one callsign on one frame transport, owning its links.

A frame transport is a shared medium: every frame the TNC hears arrives on the
same callback, addressed to whoever it is addressed to. This class is the
demultiplexer. It decides, for each inbound frame, whether it belongs to an
existing link, starts a new one, or belongs to nobody and should be handed to
the monitor pane only.

Matching is on the **peer** address plus port, and deliberately ignores SSID-
insensitive matching: ``WS1EC-7`` and ``WS1EC-1`` are different stations, and a
terminal that conflates them will deliver one node's output into another's
window. Callsign comparison is on ``(callsign, ssid)``, never on the display
string, so a stray ``*`` or whitespace cannot create a second link to the same
peer.

`accept_incoming` exists because a packet terminal is also a *server*: other
stations connect to you, which is how a personal mailbox or a keyboard-to-
keyboard chat starts. Refusing cleanly with DM is important -- a silent drop
makes the caller retry N2 times and waste a minute of channel time.
"""

from __future__ import annotations

import asyncio
import logging
import dataclasses
from collections.abc import Callable

from ..transport.base import FrameTransport, Session, SessionState
from .address import AX25Address, AX25Path
from .frame import AX25Frame, UType
from .session import AX25Link, LinkParams

log = logging.getLogger(__name__)

LinkKey = tuple[str, int, int]  # (callsign, ssid, port)


def _key(addr: AX25Address, port: int) -> LinkKey:
    return (addr.callsign, addr.ssid, port)


class AX25Station:
    """Binds a callsign to a `FrameTransport` and manages its links."""

    def __init__(
        self,
        mycall: AX25Address,
        transport: FrameTransport,
        params: LinkParams | None = None,
        *,
        aliases: tuple[AX25Address, ...] = (),
        accept_incoming: bool = True,
    ) -> None:
        self.mycall = mycall
        self.transport = transport
        self.params = params or LinkParams()
        self.aliases = aliases
        self.accept_incoming = accept_incoming

        self.links: dict[LinkKey, AX25Link] = {}
        self.on_incoming: list[Callable[[AX25Link], None]] = []
        #: Frames not belonging to any link, for the monitor pane and APRS.
        self.on_unhandled: list[Callable[[AX25Frame, int], None]] = []

        self._unsubscribe = transport.subscribe(self._on_frame)

    # ------------------------------------------------------------------
    def _is_mine(self, addr: AX25Address) -> bool:
        mine = (self.mycall, *self.aliases)
        return any(a.callsign == addr.callsign and a.ssid == addr.ssid for a in mine)

    def _path_to(self, peer: AX25Path) -> AX25Path:
        """Build our outbound path to a peer, substituting our own callsign."""
        return AX25Path(peer.destination, self.mycall, peer.repeaters)

    # ------------------------------------------------------------------
    async def connect(
        self, target: AX25Path, *, port: int = 0, timeout: float | None = None
    ) -> AX25Link | None:
        """Connect to ``target``. Returns the link, or None if it did not come up.

        A link object is created before the SABM goes out and kept even on
        failure until the caller drops it, so the UI can show why it failed
        rather than having the object vanish out from under the pane.
        """
        path = self._path_to(target)
        key = _key(path.destination, port)
        link = self.links.get(key)
        if link is not None and link.connected:
            return link

        link = AX25Link(
            path,
            send=lambda frame: self.transport.send_frame(frame, port),
            params=dataclasses.replace(self.params),
            port=port,
        )
        self.links[key] = link
        ok = await link.connect(timeout=timeout)
        return link if ok else None

    async def disconnect_all(self) -> None:
        await asyncio.gather(
            *(link.disconnect() for link in list(self.links.values())),
            return_exceptions=True,
        )

    def close(self) -> None:
        """Drop the transport subscription and tear every link's timers down."""
        self._unsubscribe()
        for link in list(self.links.values()):
            link.close()
        self.links.clear()

    # ------------------------------------------------------------------
    async def _on_frame(self, frame: AX25Frame, port: int = 0) -> None:
        if not self._is_mine(frame.path.destination):
            # Not addressed to us. Still useful: this is the entire input to
            # the monitor pane, the heard list, and the APRS decoder.
            self._unhandled(frame, port)
            return

        # A frame still working its way down a digipeater path has not reached
        # us yet, even though our callsign is in the destination field.
        if frame.path.next_repeater is not None:
            self._unhandled(frame, port)
            return

        key = _key(frame.path.source, port)
        link = self.links.get(key)

        if link is None:
            if frame.kind == "U" and frame.utype in (UType.SABM, UType.SABME):
                await self._on_incoming_connect(frame, port, key)
                return
            if frame.kind == "U" and frame.utype is UType.UI:
                self._unhandled(frame, port)
                return
            # Traffic for a link we do not have. DM tells the peer to stop
            # retrying instead of hammering the channel for N2 attempts.
            if frame.command and frame.pf:
                await self.transport.send_frame(
                    AX25Frame.u_frame(
                        frame.path.reply(command=False), UType.DM, pf=True, command=False
                    ),
                    port,
                )
            self._unhandled(frame, port)
            return

        await link.handle(frame)

    async def _on_incoming_connect(
        self, frame: AX25Frame, port: int, key: LinkKey
    ) -> None:
        if not self.accept_incoming:
            await self.transport.send_frame(
                AX25Frame.u_frame(
                    frame.path.reply(command=False), UType.DM, pf=frame.pf, command=False
                ),
                port,
            )
            return

        path = frame.path.reply(command=True)
        link = AX25Link(
            path,
            send=lambda f: self.transport.send_frame(f, port),
            params=dataclasses.replace(self.params),
            port=port,
        )
        self.links[key] = link
        await link.handle(frame)  # sends the UA and enters CONNECTED
        log.info("incoming connection from %s", path.destination)
        for cb in list(self.on_incoming):
            cb(link)

    def _unhandled(self, frame: AX25Frame, port: int) -> None:
        for cb in list(self.on_unhandled):
            cb(frame, port)

    # ------------------------------------------------------------------
    def session_for(self, link: AX25Link) -> Session:
        """Wrap a link in the transport-agnostic `Session` the UI consumes.

        This is the seam that lets a VARA session and a KISS session render in
        the same pane: above here, nothing knows which tier it is talking to.
        """
        session = Session(path=link.path, transport=self.transport, state=link.state)
        session._sender = link.send
        session._closer = link.disconnect
        link.on_data.append(
            lambda data: session.incoming.put_nowait(data)
        )
        link.on_state.append(lambda state: session.set_state(state))
        return session
