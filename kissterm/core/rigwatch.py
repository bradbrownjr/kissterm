"""The active transport's radio: read its dial frequency, tune it on a
confirmed connect (ROADMAP P3a M6).

A transport entry may name a Rigs entry (`rig`); this follows the active
transport's. While there is one it keeps a `rigctld` answering (starting it
on this computer if need be, `Supervisor.ensure_rigctld`) and polls it every
few seconds for the frequency and mode, publishing `RigStateChanged` for
every front end's status field. Everything here is local to the station: no
radio frequency is used, no network beyond `rigctld`'s own socket.

**Reading never keys; tuning is not transmitting.** `tune` sets the dial and
mode, which is silent. It is called only from a connect the operator has
confirmed (`Connector.connect`), after the confirmation that shows it
("Tunes IC-7300 to 7.101.500 USB-D"), never on selecting a contact. The
antenna tuner's carrier (`rig.tune()`) is not here: that is ROADMAP M6b.

**One owner per serial port.** A program whose `keying` is `cat` owns the
radio's CAT port, so kissterm neither starts `rigctld` nor reads the radio
while it is the transport's program (the hand-off is M6b); the field says so.

**The home channel** (ROADMAP P3a M6c). A transport entry may carry a
`frequency`: where its radio belongs. It is set once each time the transport
becomes the one in use (made "Radio in use", or at launch), on the first
reading, and not again while it stays in use, so moving the dial by hand is
not undone every few seconds. The session tier (VARA, Mercury) connects to
whatever station the operator dialled with no contact of its own on the
Ctrl+N path, so its connect falls back to this channel (`plan_session`).

A rig that cannot be reached is not an error to shout about: the status field
is hidden and the reason is in `problem`, for Settings and the log.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging

from ..rig.frequency import Tuning, parse_frequency
from ..rig.rigctld import RigctldClient, RigError, RigState
from .events import ConfigChanged, RigStateChanged, TransportChanged

log = logging.getLogger(__name__)

#: Seconds between readings, and between attempts while `rigctld` is silent.
POLL_SECONDS = 3.0
SILENT_SECONDS = 10.0


class RigWatch:
    """`Core.rigwatch`."""

    def __init__(self, core) -> None:
        self.core = core
        self.state: RigState | None = None
        #: Why the radio is not being read, "" when it is (or there is none).
        self.problem = ""
        self._client: RigctldClient | None = None
        self._task: asyncio.Task | None = None
        self._key: tuple = ()
        #: (transport name, frequency) last tuned home, so a reading loop
        #: restarted by a Settings save does not retune.
        self._homed: tuple = ()
        self._unsubscribe = None
        #: Seconds, overridable by tests.
        self.poll_seconds = POLL_SECONDS
        self.silent_seconds = SILENT_SECONDS

    # -- which radio ----------------------------------------------------------
    def _entry(self) -> dict | None:
        config = self.core.config
        name = config.active_transport
        entries = config.transports
        return next((t for t in entries if t.get("name") == name),
                    entries[0] if entries and not name else None)

    def active_rig(self) -> dict | None:
        """The Rigs entry the active transport names, or None."""
        entry = self._entry()
        name = str((entry or {}).get("rig") or "")
        return next((r for r in self.core.config.rigs if r.get("name") == name), None) if name else None

    def owns_cat_port(self) -> bool:
        """Whether the active transport's program owns the radio's CAT port
        (`keying = "cat"`), so kissterm must leave the radio alone."""
        entry = self._entry() or {}
        program = next((p for p in self.core.config.programs
                        if p.get("name") == entry.get("program")), None)
        return bool(program and program.get("keying") == "cat")

    # -- following the active transport ---------------------------------------
    def start(self) -> None:
        """Begin following the active transport's radio (needs a running loop)."""
        if self._unsubscribe is None:
            def changed(_seq, event) -> None:
                if isinstance(event, (TransportChanged, ConfigChanged)):
                    self.refresh()

            self._unsubscribe = self.core.events.subscribe(changed)
        self.refresh()

    def refresh(self) -> None:
        """Start, stop or restart the reading to match the active transport."""
        rig = self.active_rig()
        key = (rig.get("name"), rig.get("host"), rig.get("port"), rig.get("model"),
               rig.get("device"), self.owns_cat_port()) if rig else ()
        if key == self._key and (self._task is not None and not self._task.done()) == bool(key):
            return
        self._cancel()
        self._key = key
        if (self._entry() or {}).get("name") != (self._homed or ("",))[0]:
            self._homed = ()  # another transport: its own home, when it opens
        if rig is None:
            self._set(None, "")
            return
        try:
            self._task = asyncio.get_running_loop().create_task(self._run(dict(rig)))
        except RuntimeError:
            self._key = ()  # no loop yet; the next refresh tries again

    def _cancel(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self._client = None

    async def shutdown(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        client, self._client = self._client, None
        if client is not None:
            await client.close()

    # -- the reading ----------------------------------------------------------
    async def _run(self, rig: dict) -> None:
        name = str(rig.get("name", ""))
        try:
            if self.owns_cat_port():
                self._set(None, f"{name}: the modem program owns the radio's CAT port")
                return
            client = self._client = RigctldClient.from_rig(rig)
            while True:
                state = await client.poll()
                problem = ""
                if state is None:
                    # Nothing answered: start rigctld here if it is ours to
                    # start, and look again once.
                    problem = await self.core.supervisor.ensure_rigctld(rig)
                    if not problem:
                        client.reset_backoff()
                        state = await client.poll()
                if state is not None:
                    state = await self._go_home(client, state)
                    self._set(state, "", name)
                    await asyncio.sleep(self.poll_seconds)
                else:
                    self._set(None, problem or client.last_error or "no answer from rigctld", name)
                    await asyncio.sleep(self.silent_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - never raise out of a background task
            log.warning("reading the radio stopped: %s", exc)
            self._set(None, str(exc), name)

    def home(self) -> Tuning | None:
        """The active transport's home channel (its `frequency`), or None."""
        if self.active_rig() is None or self.owns_cat_port():
            return None
        return parse_frequency(str((self._entry() or {}).get("frequency") or ""))

    async def _go_home(self, client: RigctldClient, state: RigState) -> RigState:
        """Tune to the home channel once per opening; the reading after it.
        No carrier. A failure is logged and left: the status field shows
        where the radio really is."""
        tuning = self.home()
        mark = (str((self._entry() or {}).get("name", "")), tuning)
        if tuning is None or mark == self._homed:
            return state
        self._homed = mark
        try:
            await client.set_frequency(tuning.hz)
            if tuning.mode:
                await client.set_mode(tuning.mode, 0)
        except RigError as exc:
            log.warning("could not tune to the home channel %s: %s", tuning.describe(), exc)
            return state
        log.info("tuned to the home channel %s", tuning.describe())
        return await client.poll() or state

    def note_ptt(self, keyed: bool) -> None:
        """kissterm keyed or unkeyed the radio (`core/ptt.py`): shown at
        once, not at the next reading."""
        if self.state is not None:
            self._set(self.state, self.problem, str((self.active_rig() or {}).get("name", "")))

    def _set(self, state: RigState | None, problem: str, name: str = "") -> None:
        ptt = getattr(self.core, "ptt", None)
        if state is not None and ptt is not None and ptt.keyed and not state.ptt:
            # A rig that does not report PTT, or a reading taken before the
            # key: kissterm knows it is keyed.
            state = dataclasses.replace(state, ptt=True)
        elif state is not None and ptt is not None and not ptt.keyed and state.ptt \
                and self.state is state:
            state = dataclasses.replace(state, ptt=False)
        changed = (state != self.state)
        self.state, self.problem = state, problem
        if problem:
            log.debug("radio %s: %s", name, problem)
        if changed:
            self.core.events.publish(RigStateChanged(
                name, state.frequency if state else 0, state.mode if state else "",
                state.ptt if state else None))

    # -- tuning on a confirmed connect ----------------------------------------
    def plan(self, contact) -> Tuning | None:
        """Where the active radio would be tuned for `contact` (its
        `frequency`), or None: no radio, its modem owns the CAT port, or no
        number on file. Reading only; nothing is changed."""
        if contact is None or self.active_rig() is None or self.owns_cat_port():
            return None
        return parse_frequency(getattr(contact, "frequency", ""))

    def plan_session(self, contact=None) -> Tuning | None:
        """The session tier's connect: the contact's frequency, else the
        transport's home channel (`home`). Reading only."""
        return self.plan(contact) or self.home()

    def describe(self, tuning: Tuning) -> str:
        rig = self.active_rig() or {}
        return f"Tunes {rig.get('name', 'the radio')} to {tuning.describe()}"

    async def tune(self, tuning: Tuning) -> str:
        """Set the dial (and mode, when `tuning` names one); "" when done,
        else why not. No carrier. Call only after the operator confirmed."""
        rig = self.active_rig()
        if rig is None:
            return "No radio is set up for this transport."
        client = self._client or RigctldClient.from_rig(rig)
        try:
            problem = await self.core.supervisor.ensure_rigctld(rig)
            if problem:
                return problem
            await client.set_frequency(tuning.hz)
            if tuning.mode:
                await client.set_mode(tuning.mode, 0)
            state = await client.poll()
        except RigError as exc:
            return str(exc)
        finally:
            if client is not self._client:
                await client.close()
        if state is not None:
            self._set(state, "", str(rig.get("name", "")))
        return ""
