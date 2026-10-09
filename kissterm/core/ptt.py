"""Keying the radio for VARA, through the transmit gate (ROADMAP P3a M5).

VARA has no rig control of its own that kissterm can share: it tells the
application on its command port when to key, `PTT ON` and `PTT OFF` ("Order
for switching PTT ON", EA5HVK's "VARA Protocol Native TNC Commands"; Pat-Vara
hands both to its rig control the same way). So when the active transport is
VARA HF or VARA FM, its program's keying is "Through kissterm's rig control"
(`keying = "rigctld"`) and the transport names a rig, `PttKeyer` keys that
rig through its `rigctld` (`T 1`/`T 0`). Any other keying -- VOX, a SignaLink,
VARA's own CAT or RTS setting -- is VARA's business and nothing happens here:
keying is opt-in, as Pat's `ptt_ctrl` is. Mercury and Direwolf are given the
shared `rigctld` on their own command line instead, so each modem has exactly
one keying path. UNVERIFIED: which of VARA's own PTT settings make it send
`PTT ON` at all; its document does not say (ON-AIR-TESTS).

**The gate decides, at the moment of keying.** `PTT ON` keys only while the
transmit gate is open, checked when the order arrives and again just before
`T 1` is sent (AGENTS.md "Re-check at the moment of transmission"). A refused
key is logged `TX BLOCKED`, counted on the gate, and announced once per
refusal run: VARA asks again on every ARQ retry, and one notice says it. That
is what puts VARA's own transmissions -- answering while `LISTEN ON`, ARQ
acknowledgements -- behind the switch the operator can see.

**Unkey on every exit path**, because a stuck transmitter is the one failure
here that harms someone else's channel: `PTT OFF`; VARA's command socket
closing or the transport closing (`VaraTransport` passes False on both); the
gate closing while keyed; the `ptt_timeout` watchdog (the rig entry's, 120 s
by default); `shutdown` (Restart, Shut down, Quit); and, with no event loop
left, `unkey_all_now` from `atexit` and from a SIGTERM/SIGHUP that would
otherwise end the process without cleanup. `T 0` always goes through; only
`T 1` asks the gate. A watchdog unkey holds the radio off until VARA says
`PTT OFF`, so a modem stuck keyed cannot re-key it.

The state shows where the radio's reading does: `RigWatch.note_ptt` sets the
reading's PTT and publishes `RigStateChanged`, so the status bar and the
phone's More page show `PTT` beside the dial while kissterm holds it keyed.
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import logging
import os
import signal
import sys

from ..rig.rigctld import RigctldClient, RigError, unkey_now
from .events import ConfigChanged, GateChanged, TransportChanged
from .operator import Notice, Severity

log = logging.getLogger(__name__)

#: Transport kinds whose modem orders PTT over its command port.
KEYED_KINDS = frozenset({"vara", "varafm"})
DEFAULT_PTT_TIMEOUT = 120.0

#: (host, port) of every rigctld kissterm has keyed and not yet unkeyed, for
#: the synchronous last resort. Process-wide: a crash has no Core to ask.
_KEYED: set[tuple[str, int]] = set()
_INSTALLED = False


def unkey_all_now() -> None:
    """Synchronous last resort (`atexit`, a fatal signal): `T 0` to every
    rig still keyed. Idempotent; never raises."""
    for host, port in list(_KEYED):
        if unkey_now(host, port):
            _KEYED.discard((host, port))
        else:
            log.error("could not unkey the radio at %s:%d at exit", host, port)


def _fatal_signal(signum, _frame) -> None:
    unkey_all_now()
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def _install_last_resort() -> None:
    """Once per process. A signal whose handler is still the default would
    end the process with the radio keyed; one that someone else handles
    (asyncio's, Textual's) ends in a shutdown that unkeys anyway, and is
    left alone."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    atexit.register(unkey_all_now)
    if sys.platform.startswith("win"):
        return
    for name in ("SIGTERM", "SIGHUP"):
        signum = getattr(signal, name, None)
        if signum is None:
            continue
        with contextlib.suppress(ValueError, OSError):  # not the main thread
            if signal.getsignal(signum) is signal.SIG_DFL:
                signal.signal(signum, _fatal_signal)


class PttKeyer:
    """`Core.ptt`."""

    def __init__(self, core) -> None:
        self.core = core
        #: Whether kissterm holds the radio keyed now.
        self.keyed = False
        self._transport = None
        self._rig: dict | None = None
        self._client: RigctldClient | None = None
        self._want = False
        self._worker: asyncio.Task | None = None
        self._watchdog: asyncio.TimerHandle | None = None
        #: The watchdog unkeyed: stay off until VARA says PTT OFF.
        self._held_off = False
        #: A refusal was announced; the next is not, until a key succeeds
        #: or the gate opens.
        self._refusal_said = False
        self._unsubscribe = None

    # -- which radio, which modem ---------------------------------------------
    def _program(self, entry: dict) -> dict | None:
        return next((p for p in self.core.config.programs
                     if p.get("name") == entry.get("program")), None)

    def wanted(self) -> tuple[object, dict] | None:
        """(the VARA transport, its rig) when kissterm should key for it."""
        transport = self.core.session_transport
        if transport is None or getattr(transport.info, "kind", "") not in KEYED_KINDS:
            return None
        entry = self.core.rigwatch._entry() or {}
        program = self._program(entry)
        rig = self.core.rigwatch.active_rig()
        if program is None or program.get("keying") != "rigctld" or rig is None:
            return None
        return transport, rig

    # -- following the active transport ---------------------------------------
    def start(self) -> None:
        """Follow the active transport and the gate (needs a running loop)."""
        if self._unsubscribe is None:
            def changed(_seq, event) -> None:
                if isinstance(event, (TransportChanged, ConfigChanged)):
                    self.refresh()
                elif isinstance(event, GateChanged) and event.enabled:
                    self._refusal_said = False
                elif isinstance(event, GateChanged) and self.keyed:
                    self._say(f"Transmit turned off: unkeying {self._rig_name()}.",
                              Severity.WARNING)
                    self._order(False)

            self._unsubscribe = self.core.events.subscribe(changed)
        self.refresh()

    def refresh(self) -> None:
        wanted = self.wanted()
        transport, rig = wanted if wanted else (None, None)
        if transport is self._transport and rig == self._rig:
            return
        self._detach()
        if transport is None:
            return
        self._transport, self._rig = transport, dict(rig)
        self._client = RigctldClient.from_rig(self._rig)
        transport.ptt_listeners.append(self._on_ptt)
        log.info("keying %s for %s on VARA's PTT orders", rig.get("name"),
                 transport.info.detail)

    def _detach(self) -> None:
        if self._transport is not None:
            with contextlib.suppress(ValueError):
                self._transport.ptt_listeners.remove(self._on_ptt)
        if self.keyed:
            # Unkey with the client that keyed, whatever comes next.
            client, name = self._client, self._rig_name()
            self._cancel_watchdog()
            self.keyed = self._want = False
            try:
                asyncio.get_running_loop().create_task(self._release(client, name))
            except RuntimeError:
                unkey_all_now()
        self._transport = self._rig = self._client = None

    async def shutdown(self) -> None:
        """Unkey and stop following (Restart, Shut down, Quit)."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._transport is not None:
            with contextlib.suppress(ValueError):
                self._transport.ptt_listeners.remove(self._on_ptt)
        self._want = False
        worker, self._worker = self._worker, None
        if worker is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(worker, 3.0)
        if self.keyed:
            await self._unkey()
        if self._client is not None:
            await self._client.close()
        self._transport = self._rig = self._client = None
        unkey_all_now()  # anything a failed unkey left behind

    # -- VARA's orders --------------------------------------------------------
    def _on_ptt(self, on: bool) -> None:
        """From VARA's command read loop: never awaits, never raises."""
        if not on:
            self._held_off = False
        elif self._held_off:
            log.warning("VARA asked to key again after the PTT watchdog; holding off")
            return
        elif not self.core.gate.allow():
            self._refused()
            return
        self._order(on)

    def _order(self, on: bool) -> None:
        self._want = on
        if self._worker is None or self._worker.done():
            try:
                self._worker = asyncio.get_running_loop().create_task(self._apply())
            except RuntimeError:
                log.error("no event loop to %s the radio", "key" if on else "unkey")

    async def _apply(self) -> None:
        """Bring the radio to the last order, one command at a time."""
        try:
            while self.keyed != self._want:
                if self._want:
                    await self._key()
                    if not self.keyed:
                        return  # refused or failed: wait for the next order
                else:
                    await self._unkey()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - never raise out of a background task
            log.exception("PTT worker failed")

    async def _key(self) -> None:
        client, rig = self._client, self._rig
        if client is None or rig is None:
            return
        # The moment of transmission: the gate again, right before T 1.
        if not self.core.gate.allow():
            self._want = False
            self._refused()
            return
        try:
            await client.set_ptt(True)
        except RigError as exc:
            self._want = False
            self._say(f"Could not key {self._rig_name()}: {exc}", Severity.ERROR)
            return
        self.keyed = True
        _KEYED.add((client.host, client.port))
        _install_last_resort()
        self._refusal_said = False
        log.info("PTT on: %s keyed for VARA", self._rig_name())
        timeout = float(rig.get("ptt_timeout") or DEFAULT_PTT_TIMEOUT)
        self._watchdog = asyncio.get_running_loop().call_later(timeout, self._held_too_long,
                                                               timeout)
        self.core.rigwatch.note_ptt(True)

    def _cancel_watchdog(self) -> None:
        if self._watchdog is not None:
            self._watchdog.cancel()
            self._watchdog = None

    async def _unkey(self) -> None:
        self._cancel_watchdog()
        client, self.keyed = self._client, False
        if client is not None:
            await self._release(client, self._rig_name())

    async def _release(self, client: RigctldClient | None, name: str) -> None:
        """`T 0` on `client`, three tries. A radio that may still be keyed
        is said loudly and stays in the last-resort list, so exit tries
        again."""
        if client is None:
            return
        for attempt in range(3):
            try:
                await client.set_ptt(False)
                break
            except RigError as exc:
                log.error("PTT off failed (try %d): %s", attempt + 1, exc)
                client.reset_backoff()
        else:
            self._say(f"Could not unkey {name}: check the radio now.", Severity.ERROR)
            self.core.rigwatch.note_ptt(False)
            return
        _KEYED.discard((client.host, client.port))
        log.info("PTT off: %s unkeyed", name)
        self.core.rigwatch.note_ptt(False)

    def _held_too_long(self, timeout: float) -> None:
        self._watchdog = None
        self._held_off = True
        self._say(f"{self._rig_name()} was keyed for {timeout:g} s: unkeyed. VARA is not "
                  "re-keyed until it says PTT OFF.", Severity.ERROR)
        self._order(False)

    # -- saying so ------------------------------------------------------------
    def _refused(self) -> None:
        log.warning("TX BLOCKED: VARA asked to key %s; transmit is off", self._rig_name())
        if not self._refusal_said:
            self._refusal_said = True
            self._say(f"VARA asked to transmit, but transmit is off: {self._rig_name()} "
                      "was not keyed.", Severity.WARNING)

    def _rig_name(self) -> str:
        return str((self._rig or {}).get("name") or "the radio")

    def _say(self, text: str, severity: Severity) -> None:
        with contextlib.suppress(Exception):
            self.core.operator.notice(Notice(text, severity))
