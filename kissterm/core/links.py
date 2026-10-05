"""`SessionLinkAdapter`: a session-tier `Session` in `AX25Link`'s shape.

AGENTS.md section 2a: logic that must work on both tiers extends this
adapter, never reshapes `Session` (that ripples into vara/mercury/
kernel_ax25 and `tests/unit/test_tx_gate.py`).
"""

from __future__ import annotations

import asyncio
import contextlib

from ..transport.base import SessionState


class SessionLinkAdapter:
    """Presents a session-tier `Session` (VARA, Mercury, kernel AX.25,
    Telnet, SSH) with the same shape `AX25Link` already has, so every piece
    of connect-flow logic written once against `AX25Link` -- the terminal UI's `_bind_link`,
    `Connector.hop_through`/`hop_to`, `run_connect_script`, `disconnect` --
    works unchanged for either tier, with no branch scattered through any
    of them.

    The two really do differ: `Session.on_state_change` is a registration
    *method*, `AX25Link.on_state` a plain callback list; `Session` has no
    `on_data` at all, only an `incoming` queue fed by `deliver()`, because
    `Session` predates any real caller -- nothing in this app constructed
    one through `SessionTransport.connect()` before this adapter existed.
    Adapting here rather than reshaping `Session` to match keeps
    `kernel_ax25.py`/`vara.py`/`mercury.py` and their existing tests
    (`tests/unit/test_tx_gate.py` included) untouched.

    `Session` also has no error-reporting channel to match `AX25Link.
    on_error` -- `self.on_error` exists so `_bind_link` can append to it
    without a branch, but nothing here ever calls what is in it. Session
    transports do not have a "why" beyond a plain disconnect yet.

    **The far end's echo is removed here.** BPQ's Telnet server answers
    IAC WILL ECHO and sends back every byte typed except the password
    (LinBPQ `TelnetV6.c`), and WS1EC's SSH account runs `telnet` into it,
    so each line showed twice: kissterm's own echo, then the node's
    (operator, 2026-10-02). What was sent is held as the expected echo;
    bytes that match it at the start of what comes back are dropped, CR LF
    standing for the CR sent. The moment anything differs -- a password the
    server does not echo, a far end that never echoes -- the held bytes are
    delivered after all and the expectation is dropped, so nothing the far
    end really said is lost. A partial match left waiting is delivered
    after `ECHO_WAIT` seconds. AX.25 nodes do not echo; this is the session
    tier only, the only place it happens.
    """

    #: How long a partial echo match waits for the rest before it is shown.
    ECHO_WAIT = 1.0

    def __init__(self, session, transport=None) -> None:
        self._session = session
        #: An Internet contact's own connection (`Connector.dial_internet`), closed
        #: with the session. None for the app's configured transport.
        self._transport = transport
        self._transport_closed = False
        self.peer = session.peer
        self.on_data: list = []
        self.on_state: list = []
        self.on_error: list = []
        #: The echo still expected, and the received bytes held while they
        #: match it (class docstring).
        self._echo = bytearray()
        self._held = bytearray()
        self._after_cr = False
        self._echo_timer: asyncio.TimerHandle | None = None
        session.on_state_change(lambda _session, state: self._emit_state(state))
        self._pump_task = asyncio.get_event_loop().create_task(
            self._pump(), name=f"session-adapter-pump:{session.peer}"
        )

    @property
    def connected(self) -> bool:
        return self._session.connected

    @property
    def internet(self) -> bool:
        """An Internet contact's session: it cannot reach the air, so the
        transmit gate is neither checked nor armed for it."""
        return self._transport is not None

    @property
    def carries_binary(self) -> bool:
        """Whether a file transfer (YAPP, AutoBIN) can run over this link.
        False over SSH: WS1EC's login runs `telnet` into BPQ in line mode on
        the server's terminal, which holds YAPP's two-byte answers until a
        line end and acts on its control bytes (Ctrl+C, Ctrl+D) itself. The
        operator's test, 2026-10-04: BPQ's header arrived only after the
        next line was typed. Changing the node's login would break other
        users' telnet clients, so the operator chose to mark it
        unsupported (the terminal UI's `refuse_line`). An `AX25Link` has no such
        property and carries binary."""
        transport = getattr(self._session, "transport", None)
        return getattr(getattr(transport, "info", None), "kind", "") != "ssh"

    @property
    def state(self):
        return self._session.state

    async def send(self, data: bytes) -> None:
        await self._session.send(data)
        self._echo += data.replace(b"\r\n", b"\r").replace(b"\n", b"\r")

    def _strip_echo(self, data: bytes) -> bytes:
        """`data` less the leading part that echoes what was sent; may hold
        bytes back while a match is incomplete (class docstring)."""
        if not self._echo and not self._after_cr:
            return data
        for i, byte in enumerate(data):
            if self._after_cr and byte == 0x0A:
                # The LF of a CR LF that echoed a CR.
                self._after_cr = False
                continue
            self._after_cr = False
            if self._echo and byte == self._echo[0]:
                del self._echo[0]
                self._held.append(byte)
                self._after_cr = byte == 0x0D
                if not self._echo:
                    # The whole echo arrived: drop it.
                    self._held.clear()
                continue
            # Past the echo, or not an echo at all: show what was held (if
            # anything), and stop expecting one.
            rest = bytes(self._held) + data[i:]
            self._echo.clear()
            self._held.clear()
            return rest
        if self._held:
            self._arm_echo_timer()
        return b""

    def _arm_echo_timer(self) -> None:
        if self._echo_timer is not None:
            self._echo_timer.cancel()
        self._echo_timer = asyncio.get_event_loop().call_later(self.ECHO_WAIT, self._release_echo)

    def _release_echo(self) -> None:
        """A partial match that never finished: the far end said it."""
        self._echo_timer = None
        held = bytes(self._held)
        self._echo.clear()
        self._held.clear()
        self._after_cr = False
        if held:
            self._deliver(held)

    def _deliver(self, data: bytes) -> None:
        for cb in list(self.on_data):
            cb(data)

    async def disconnect(self) -> None:
        """The session-tier equivalent of `AX25Link.disconnect()` -- there
        is no DISC to send, only the connection itself to close."""
        self._pump_task.cancel()
        await self._session.close()
        await self._close_transport()

    def close(self) -> None:
        self._pump_task.cancel()

    async def _close_transport(self) -> None:
        # Once: both a hang-up and Ctrl+D can get here.
        if self._transport is None or self._transport_closed:
            return
        self._transport_closed = True
        with contextlib.suppress(Exception):
            await self._transport.close()

    def _emit_state(self, state) -> None:
        for cb in list(self.on_state):
            cb(state)
        if state == SessionState.DISCONNECTED and self._transport is not None:
            # The far end hung up: its connection goes with it.
            asyncio.get_event_loop().create_task(self._close_transport())

    async def _pump(self) -> None:
        try:
            while True:
                data = self._strip_echo(await self._session.incoming.get())
                if data:
                    if self._echo_timer is not None:
                        self._echo_timer.cancel()
                        self._echo_timer = None
                    self._deliver(data)
        except asyncio.CancelledError:
            pass
