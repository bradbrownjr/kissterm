"""AX.25 v2.2 connected-mode data link -- kissterm's reason for existing.

KISS gives you a pipe that moves frames. It has no notion of a connection, an
acknowledgement, or a retransmission. Everything a packet *terminal* needs --
"connect to WS1EC-7", ordered delivery, recovery when a frame is lost to a
collision -- lives in the link layer defined by AX.25 2.2 section 6, and that
layer is what this module implements in userspace.

That is the whole difference between kissterm and linpac. linpac delegates this
to the Linux kernel's ``AF_AX25`` stack, which is why it needs a kernel with
AX.25 built in, `axports` configured, and root to set it up -- and why it
cannot talk to a KISS TNC sitting on another machine's TCP port at all. Owning
the state machine means kissterm runs unprivileged, on any OS, against any
transport that can move a frame.

The state machine
-----------------
States follow the spec's names so the code can be read next to it::

    DISCONNECTED  --connect()-->  AWAITING_CONNECTION  --UA-->  CONNECTED
                                          |  DM / N2 retries          |
                                          v                            | T1 expiry
                                     DISCONNECTED  <--N2 retries-- TIMER_RECOVERY
                                          ^                            |
                                          +----DISC/UA---- AWAITING_RELEASE

`TIMER_RECOVERY` is worth understanding before touching anything here: it is
not an error state. It is the link asking "are you still there, and what have
you actually received?" after T1 expired. A busy 1200-baud channel or a marginal
HF path spends real time in it and recovers fine. Treating it as a failure --
tearing the link down, or showing the operator a scary status -- is wrong, and
was the single most common bug in the terminals this project set out to replace.

Three timers, three different jobs
----------------------------------
* **T1** -- "I sent something and have not been acknowledged." Started whenever
  an unacknowledged I frame or a P-bit poll goes out; stopped when everything
  outstanding is acknowledged. Its expiry drives all retransmission. Must be
  longer than the worst-case round trip, or the link retransmits into its own
  echo forever: at 1200 baud a 256-byte frame alone is ~1.8 s on the air, and
  the reply has to wait for the channel.
* **T2** -- "wait before acknowledging." Deliberately delays a bare RR so an
  outgoing I frame can carry the acknowledgement instead. On a half-duplex
  radio channel every avoided transmission is avoided airtime and avoided
  collisions. Setting T2 to zero roughly doubles the frames on the air for a
  two-way conversation.
* **T3** -- "the link has been idle; is it still alive?" Only runs when nothing
  is outstanding. Without it, a link whose far end vanished stays "connected"
  in the UI forever, because a healthy idle link and a dead one look identical.

Modulo 8 vs modulo 128
----------------------
kissterm asks for modulo 128 with SABME only when configured to; the default
is SABM/modulo 8, because it is what every BPQ32, KA-Node and TNC2-class
station on the air actually implements. A station that does not understand
SABME answers DM or FRMR, and `_on_dm` falls back to SABM once before giving
up -- that fallback is why the default is safe to change.

Everything here is asyncio and single-threaded per link. No lock is taken and
none is needed; if you ever call into an `AX25Link` from a thread, that
invariant is gone and so is the state machine's consistency.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from ..transport.base import SessionState
from .address import AX25Address, AX25Path
from .timers import LinkTimers
from .window import SlidingWindow
from .frame import (
    DEFAULT_PACLEN,
    DEFAULT_WINDOW,
    MODULO8,
    MODULO128,
    PID_NO_LAYER3,
    AX25Frame,
    SType,
    UType,
)

log = logging.getLogger(__name__)

#: Spec default retry count (N2). Beyond this the link is declared failed.
DEFAULT_RETRIES = 10

FrameSender = Callable[[AX25Frame], Awaitable[None]]


@dataclass(slots=True)
class LinkParams:
    """Per-link tunables. Every one of these is negotiable in the field.

    The defaults suit 1200-baud VHF. HF wants a smaller `paclen` (a long frame
    is a bigger target for a fade) and a longer `t1`; a fast local link wants
    the opposite. `window` is capped at 7 by modulo-8 sequence numbers -- the
    dataclass enforces that rather than letting a config typo silently corrupt
    sequence arithmetic.
    """

    paclen: int = DEFAULT_PACLEN
    window: int = DEFAULT_WINDOW
    retries: int = DEFAULT_RETRIES
    t1: float = 8.0
    t2: float = 1.0
    t3: float = 180.0
    modulo: int = MODULO8
    pid: int = PID_NO_LAYER3

    def __post_init__(self) -> None:
        limit = 7 if self.modulo == MODULO8 else 63
        self.window = max(1, min(self.window, limit))
        self.paclen = max(1, min(self.paclen, 256))
        self.retries = max(1, self.retries)


@dataclass(slots=True)
class LinkStats:
    """Counters the status bar and `--doctor` read. Diagnostics, not state."""

    frames_sent: int = 0
    frames_received: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    retransmits: int = 0
    rej_received: int = 0
    rej_sent: int = 0
    t1_expiries: int = 0
    connected_at: float | None = None

    @property
    def uptime(self) -> float:
        return 0.0 if self.connected_at is None else time.monotonic() - self.connected_at


class AX25Link:
    """One connected-mode AX.25 link.

    Owns the sequence-number state for a single peer. A station talking to
    three nodes at once has three of these; they share a transport and share
    nothing else.
    """

    def __init__(
        self,
        path: AX25Path,
        send: FrameSender,
        params: LinkParams | None = None,
        *,
        port: int = 0,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.path = path
        self.port = port
        self.params = params or LinkParams()
        self._send_frame = send
        self._loop = loop or asyncio.get_event_loop()

        self.state = SessionState.DISCONNECTED
        self.stats = LinkStats()

        # Sequence state lives in SlidingWindow -- see that module for why
        # every comparison in it is a modular walk rather than a magnitude test.
        self._win = SlidingWindow(modulo=self.params.modulo, k=self.params.window)
        self.rc = 0  # retry count
        #: Why the link last failed, in operator-readable words. Empty until
        #: something goes wrong.
        self.last_error: str = ""

        self.peer_busy = False  # peer sent RNR
        self.own_busy = False  # we sent RNR
        self.reject_sent = False  # a REJ is outstanding; do not send another
        self.ack_pending = False  # T2 is running toward a bare RR

        #: Bytes waiting to become I frames.
        self._outbound = bytearray()
        #: Reassembled bytes for the UI.
        self._inbound: deque[bytes] = deque()

        self._timers = LinkTimers(
            self._on_t1, self._on_t2, self._on_t3,
            loop=self._loop, label=str(path.destination),
        )
        self._connect_result: asyncio.Future[bool] | None = None
        self._sabme_tried = False

        self.on_data: list[Callable[[bytes], None]] = []
        self.on_state: list[Callable[[SessionState], None]] = []
        self.on_error: list[Callable[[str], None]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def peer(self) -> AX25Address:
        return self.path.destination

    # The spec's variable names stay readable from outside -- the status bar,
    # the tests and `__repr__` all speak in V(S)/V(R)/V(A). They are read-only
    # here on purpose: mutating them without going through `SlidingWindow`
    # is how the modular arithmetic gets bypassed and the window jams.
    @property
    def vs(self) -> int:
        return self._win.vs

    @property
    def vr(self) -> int:
        return self._win.vr

    @property
    def va(self) -> int:
        return self._win.va

    @property
    def _sent(self) -> dict[int, bytes]:
        return self._win.sent

    @property
    def connected(self) -> bool:
        return self.state in (SessionState.CONNECTED, SessionState.TIMER_RECOVERY)

    async def connect(self, timeout: float | None = None) -> bool:
        """Send SABM(E) and wait for the link to come up.

        Returns False on refusal (DM) or after N2 retries. Never raises for an
        ordinary failure -- "the node did not answer" is a normal outcome on
        radio, not an exception.
        """
        if self.connected:
            return True
        self._reset_sequences()
        self.state = SessionState.CONNECTING
        self._emit_state()
        self._connect_result = self._loop.create_future()
        self.rc = 0
        self._sabme_tried = self.params.modulo == MODULO128
        await self._send_u(
            UType.SABME if self.params.modulo == MODULO128 else UType.SABM,
            pf=True,
            command=True,
        )
        self._start_t1()
        # One extra T1 of slack. N2 exhaustion happens at exactly
        # ``t1 * (retries + 1)``, so a deadline of the same length is a tie --
        # and when this guard won it replaced the state machine's own verdict
        # ("no answer from WS1EC-15 after 11 tries") with a bare "connect
        # timed out", losing the peer and the attempt count from the one line
        # the operator reads. This is a backstop for a link that never settles
        # at all, not a competitor to the retry budget.
        deadline = timeout or (self.params.t1 * (self.params.retries + 2))
        try:
            return await asyncio.wait_for(asyncio.shield(self._connect_result), deadline)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._fail(f"no answer from {self.peer}; connect timed out")
            return False

    async def disconnect(self) -> None:
        """Send DISC and wait briefly for the UA. Idempotent."""
        if self.state is SessionState.DISCONNECTED:
            return
        await self.flush()
        self.state = SessionState.DISCONNECTING
        self._emit_state()
        self.rc = 0
        await self._send_u(UType.DISC, pf=True, command=True)
        self._start_t1()

    async def send(self, data: bytes) -> None:
        """Queue bytes for transmission. Fragmented into I frames at `paclen`."""
        if not self.connected:
            raise ConnectionError(f"not connected to {self.peer}")
        self._outbound += data
        await self._pump()

    async def flush(self) -> None:
        """Push whatever the window allows onto the air right now."""
        await self._pump()

    def read_nowait(self) -> bytes:
        """Drain reassembled received bytes. Empty when nothing is pending."""
        if not self._inbound:
            return b""
        out = b"".join(self._inbound)
        self._inbound.clear()
        return out

    def close(self) -> None:
        """Tear down timers without transmitting. For app shutdown only.

        This deliberately does not send DISC: it is what runs when the process
        is going away and there may be no transport left to send on. Use
        `disconnect` for an orderly release that the far end will notice.
        """
        self._stop_all_timers()
        if self._connect_result is not None and not self._connect_result.done():
            self._connect_result.set_result(False)
        self.state = SessionState.DISCONNECTED
        self._emit_state()

    # ------------------------------------------------------------------
    # Inbound frame handling -- the spec's "receive" side
    # ------------------------------------------------------------------
    async def handle(self, frame: AX25Frame) -> None:
        """Feed one frame addressed to this link into the state machine."""
        self.stats.frames_received += 1
        self.stats.bytes_received += len(frame.info)
        try:
            if frame.kind == "U":
                await self._on_u(frame)
            elif frame.kind == "S":
                await self._on_s(frame)
            else:
                await self._on_i(frame)
        except Exception:  # a malformed frame must never kill the link
            log.exception("link %s: error handling %s", self.peer, frame.summary())

    async def _on_u(self, frame: AX25Frame) -> None:
        utype = frame.utype
        if utype is UType.UA:
            await self._on_ua(frame)
        elif utype is UType.DM:
            await self._on_dm(frame)
        elif utype in (UType.SABM, UType.SABME):
            # The peer is (re)establishing. Per spec this resets the link even
            # mid-session -- a node that restarted will do exactly this, and
            # answering UA is what lets the operator's session recover instead
            # of hanging until T3.
            self.params.modulo = MODULO128 if utype is UType.SABME else MODULO8
            self._reset_sequences()
            await self._send_u(UType.UA, pf=frame.pf, command=False)
            self._enter_connected()
        elif utype is UType.DISC:
            await self._send_u(UType.UA, pf=frame.pf, command=False)
            self._stop_all_timers()
            self.state = SessionState.DISCONNECTED
            self._emit_state()
        elif utype is UType.FRMR:
            # AX.25 2.2 deprecates FRMR in favour of just re-establishing.
            log.warning("link %s: FRMR received, re-establishing", self.peer)
            await self._reestablish()
        elif utype is UType.UI:
            self._deliver(frame.info)

    async def _on_ua(self, frame: AX25Frame) -> None:
        if self.state is SessionState.CONNECTING:
            self._enter_connected()
            if self._connect_result is not None and not self._connect_result.done():
                self._connect_result.set_result(True)
        elif self.state is SessionState.DISCONNECTING:
            self._stop_all_timers()
            self.state = SessionState.DISCONNECTED
            self._emit_state()
        elif self.connected:
            # A UA we did not ask for means the peer's idea of the link and
            # ours have diverged. Resynchronise rather than limp along.
            await self._reestablish()

    async def _on_dm(self, frame: AX25Frame) -> None:
        if self.state is SessionState.CONNECTING:
            # A DM answering SABME usually means "I do not speak modulo 128",
            # not "go away" -- retry once in modulo 8 before believing it.
            if self._sabme_tried and self.params.modulo == MODULO128:
                log.info("link %s: SABME refused, falling back to SABM", self.peer)
                self.params.modulo = MODULO8
                self._reset_sequences()
                self._sabme_tried = False
                await self._send_u(UType.SABM, pf=True, command=True)
                self._start_t1()
                return
            self._fail("connection refused (DM)")
        elif self.connected or self.state is SessionState.DISCONNECTING:
            self._stop_all_timers()
            self.state = SessionState.DISCONNECTED
            self._emit_state()

    async def _on_s(self, frame: AX25Frame) -> None:
        if not self.connected:
            # Supervisory traffic for a link we do not have. Tell them so; this
            # is what stops a peer retrying into a terminal that restarted.
            if frame.command and frame.pf:
                await self._send_u(UType.DM, pf=True, command=False)
            return

        self.peer_busy = frame.stype is SType.RNR
        self._ack_upto(frame.nr or 0)

        if frame.stype is SType.REJ:
            self.stats.rej_received += 1
            await self._retransmit_from(frame.nr or 0)
        elif frame.stype is SType.SREJ:
            await self._retransmit_one(frame.nr or 0)

        if frame.command and frame.pf:
            # A poll must be answered with F=1, always, even when busy.
            await self._send_s(
                SType.RNR if self.own_busy else SType.RR, pf=True, command=False
            )
        elif frame.response and frame.pf and self.state is SessionState.TIMER_RECOVERY:
            # The enquiry came back: we now know exactly what they have.
            await self._exit_timer_recovery()

        await self._pump()

    async def _on_i(self, frame: AX25Frame) -> None:
        if not self.connected:
            if frame.command and frame.pf:
                await self._send_u(UType.DM, pf=True, command=False)
            return

        self._ack_upto(frame.nr or 0)

        if self._win.accept(frame.ns or 0):
            self.reject_sent = False
            self._deliver(frame.info)
            if frame.pf:
                # A poll is answered immediately -- T2's piggyback optimisation
                # does not apply, because the peer is blocked waiting on us.
                await self._send_s(
                    SType.RNR if self.own_busy else SType.RR, pf=True, command=False
                )
            else:
                self._schedule_ack()
        else:
            # Out of sequence. One REJ, not one per frame: the peer is already
            # sending the rest of its window and every extra REJ is airtime
            # spent asking for something that is already on its way.
            if not self.reject_sent:
                self.reject_sent = True
                self.stats.rej_sent += 1
                await self._send_s(SType.REJ, nr=self.vr, pf=frame.pf, command=False)
            elif frame.pf:
                await self._send_s(SType.RR, pf=True, command=False)

        await self._pump()

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------
    async def _pump(self) -> None:
        """Fill the transmit window from the outbound buffer."""
        if not self.connected or self.peer_busy:
            return
        while self._outbound and self._win.is_open:
            chunk = bytes(self._outbound[: self.params.paclen])
            del self._outbound[: len(chunk)]
            await self._send_i(chunk)

    async def _send_i(self, info: bytes) -> None:
        ns = self._win.record_sent(info)
        frame = AX25Frame.i_frame(
            self.path,
            ns=ns,
            nr=self.vr,
            info=info,
            pid=self.params.pid,
            modulo=self.params.modulo,
        )
        self._cancel_t2()
        self.ack_pending = False
        await self._transmit(frame)
        self._start_t1()

    async def _send_s(
        self,
        stype: SType,
        *,
        nr: int | None = None,
        pf: bool = False,
        command: bool = False,
    ) -> None:
        self._cancel_t2()
        self.ack_pending = False
        await self._transmit(
            AX25Frame.s_frame(
                self.path,
                stype,
                nr=self.vr if nr is None else nr,
                pf=pf,
                command=command,
                modulo=self.params.modulo,
            )
        )

    async def _send_u(self, utype: UType, *, pf: bool, command: bool) -> None:
        await self._transmit(AX25Frame.u_frame(self.path, utype, pf=pf, command=command))

    async def _transmit(self, frame: AX25Frame) -> None:
        self.stats.frames_sent += 1
        self.stats.bytes_sent += len(frame.info)
        await self._send_frame(frame)

    async def _retransmit_from(self, nr: int) -> None:
        """Go-back-N: resend everything from N(R) forward."""
        for seq, info in list(self._win.pending_from(nr)):
            self.stats.retransmits += 1
            await self._transmit(
                AX25Frame.i_frame(
                    self.path,
                    ns=seq,
                    nr=self.vr,
                    info=info,
                    pid=self.params.pid,
                    modulo=self.params.modulo,
                )
            )
        self._start_t1()

    async def _retransmit_one(self, nr: int) -> None:
        info = self._win.pending_one(nr)
        if info is None:
            return
        self.stats.retransmits += 1
        await self._transmit(
            AX25Frame.i_frame(
                self.path,
                ns=nr % self.params.modulo,
                nr=self.vr,
                info=info,
                pid=self.params.pid,
                modulo=self.params.modulo,
            )
        )
        self._start_t1()

    def _ack_upto(self, nr: int) -> None:
        """Advance V(A) to N(R). The modular walk itself lives in `SlidingWindow`."""
        if self._win.ack_upto(nr):
            # DELIBERATE DEVIATION from the 2.2 SDL, which only clears RC on
            # leaving timer recovery. Any forward progress proves the peer is
            # alive and hearing us, so the retry budget starts over. Without
            # it, a link that is working -- just slowly, on a lossy channel --
            # accumulates T1 expiries across separate recovery episodes and
            # eventually hits N2 mid-transfer. Measured on the loopback at 40%
            # frame loss: strict-SDL behaviour tears the link down, this
            # carries the transfer to completion. Revert only with a test that
            # shows it causes a link to hang on to a genuinely dead peer.
            self.rc = 0
        if self._win.fully_acked:
            self._stop_t1()
            self._start_t3()
            if self.state is SessionState.TIMER_RECOVERY:
                self.state = SessionState.CONNECTED
                self.rc = 0
                self._emit_state()
        else:
            self._start_t1()

    def _deliver(self, data: bytes) -> None:
        if not data:
            return
        self._inbound.append(data)
        for cb in list(self.on_data):
            cb(data)

    # ------------------------------------------------------------------
    # Timers
    # ------------------------------------------------------------------
    def _start_t1(self) -> None:
        self._timers.start_t1(self.params.t1)

    def _stop_t1(self) -> None:
        self._timers.stop_t1()

    def _schedule_ack(self) -> None:
        """Start T2 so an outgoing I frame can carry the acknowledgement."""
        if self.ack_pending:
            return
        self.ack_pending = True
        self._timers.start_t2(self.params.t2)

    def _cancel_t2(self) -> None:
        self._timers.stop_t2()

    def _start_t3(self) -> None:
        self._timers.start_t3(self.params.t3)

    def _stop_t3(self) -> None:
        self._timers.stop_t3()

    def _stop_all_timers(self) -> None:
        self._timers.stop_all()

    async def _on_t1(self) -> None:
        self.stats.t1_expiries += 1
        log.debug(
            "T1 expiry %d in %s, rc=%d of %d",
            self.stats.t1_expiries,
            self.state.value,
            self.rc,
            self.params.retries,
        )

        if self.state is SessionState.CONNECTING:
            self.rc += 1
            if self.rc > self.params.retries:
                self._fail(f"no answer from {self.peer} after {self.rc} tries")
                return
            await self._send_u(
                UType.SABME if self.params.modulo == MODULO128 else UType.SABM,
                pf=True,
                command=True,
            )
            self._start_t1()
            return

        if self.state is SessionState.DISCONNECTING:
            self.rc += 1
            if self.rc > self.params.retries:
                # Give up gracefully: the operator asked to disconnect, and
                # from their side the link is gone whether or not the peer
                # ever acknowledges.
                self._stop_all_timers()
                self.state = SessionState.DISCONNECTED
                self._emit_state()
                return
            await self._send_u(UType.DISC, pf=True, command=True)
            self._start_t1()
            return

        if not self.connected:
            return

        if self.state is SessionState.CONNECTED:
            self.state = SessionState.TIMER_RECOVERY
            self.rc = 1
            self._emit_state()
        else:
            self.rc += 1
            if self.rc > self.params.retries:
                self._fail(f"link to {self.peer} failed after {self.rc} retries")
                await self._send_u(UType.DM, pf=False, command=False)
                return

        await self._transmit_enquiry()

    async def _on_t2(self) -> None:
        # T2 expired with no I frame to piggyback on: send the bare RR now.
        if self.ack_pending and self.connected:
            await self._send_s(
                SType.RNR if self.own_busy else SType.RR, pf=False, command=False
            )

    async def _on_t3(self) -> None:
        if self.connected:
            # Idle-link check. If this goes unanswered, T1 takes over and the
            # normal retry path eventually declares the link dead.
            await self._transmit_enquiry()

    async def _transmit_enquiry(self) -> None:
        await self._send_s(
            SType.RNR if self.own_busy else SType.RR, pf=True, command=True
        )
        self._start_t1()

    async def _exit_timer_recovery(self) -> None:
        self.state = SessionState.CONNECTED
        self.rc = 0
        self._emit_state()
        if self.va != self.vs:
            await self._retransmit_from(self.va)
        else:
            self._stop_t1()
            self._start_t3()

    async def _reestablish(self) -> None:
        self._reset_sequences()
        self.state = SessionState.CONNECTING
        self._emit_state()
        self.rc = 0
        await self._send_u(UType.SABM, pf=True, command=True)
        self._start_t1()

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------
    def _reset_sequences(self) -> None:
        # Re-read modulo and k from params every time: both can change between
        # link attempts (a SABME refused with DM falls back to modulo 8), and a
        # window still sized for the old mode corrupts every sequence number.
        self._win.modulo = self.params.modulo
        self._win.k = self.params.window
        self._win.reset()
        self.rc = 0
        self.peer_busy = self.own_busy = False
        self.reject_sent = self.ack_pending = False

    def _enter_connected(self) -> None:
        self._stop_all_timers()
        self.state = SessionState.CONNECTED
        self.stats.connected_at = time.monotonic()
        self.rc = 0
        self._emit_state()
        self._start_t3()

    def _fail(self, reason: str) -> None:
        # Kept on the link, not only handed to `on_error`: `AX25Station.connect`
        # creates the link itself, so the UI has no way to register a callback
        # before the SABM goes out and would otherwise be left saying only
        # "no connection" -- which reads the same whether the node refused us
        # (DM) or never heard us at all. Those need different actions from the
        # operator, so they must not look identical on screen.
        self.last_error = reason
        self._stop_all_timers()
        self.state = SessionState.FAILED
        self._emit_state()
        for cb in list(self.on_error):
            cb(reason)
        if self._connect_result is not None and not self._connect_result.done():
            self._connect_result.set_result(False)

    def _emit_state(self) -> None:
        # `__repr__` carries V(S)/V(R)/V(A) and the retry count, which is the
        # whole diagnosis of a stalled or retrying link. Logging it on every
        # transition gives a debug log that reads as the link's own history
        # rather than a pile of frames to reconstruct one from.
        log.debug("state -> %r", self)
        for cb in list(self.on_state):
            cb(self.state)

    def __repr__(self) -> str:
        return (
            f"<AX25Link {self.path} {self.state.value} "
            f"V(S)={self.vs} V(R)={self.vr} V(A)={self.va}>"
        )
