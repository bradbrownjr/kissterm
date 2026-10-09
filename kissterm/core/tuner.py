"""The antenna tuner, and handing a CAT port over to tune (ROADMAP P3a M6b).

**The ATU.** What a rig can do is asked once per rig, from `rigctld`: `U ?`
lists the functions it can set (`TUNER`: a built-in ATU that can be switched
in) and `G ?` its operations (`TUNE`: start a tuning cycle) -- Hamlib's
`rigctl_parse.c`, `set_func` and `vfo_op`, read 2026-10-09. The FT-991's
backend has both (`ft991.h`, `FT991_FUNCS`/`FT991_VFO_OPS`; `newcat.c` sends
`AC001;` and `AC002;`); a rig without them is never asked to.

- **ATU on after every tune** (`atu_on`): no carrier; most internal ATUs
  then recall the match stored for that frequency. HF and 6 m only (below
  54 MHz): the FT-991A's tuner covers those, and a VHF channel has none.
- **A tuning cycle before a connect** (`cycle`) is a TRANSMISSION: the rig
  keys a carrier for a few seconds on a channel a gateway may be using. So
  it is opt-in per band (the rig's `tune_bands`, operator decision 5: none
  by default), runs only inside a connect the operator confirmed after the
  reminder said so ("and tunes the ATU: a few seconds of carrier"), with the
  gate armed by that connect and checked again at the moment of `G TUNE`,
  the SWR watch suspended for the cycle, and logged. `G TUNE` returns at
  once and the rig tunes on its own; when it has finished is read from `t`
  where the rig reports it, else a fixed `TUNE_SECONDS`. UNVERIFIED: that
  the FT-991A reports PTT during its cycle.

**The CAT port hand-off** (`handoff`, "One owner per serial port", case 3).
When the transport's modem keys the radio through its only CAT port
(`keying = "cat"`), `rigctld` cannot open the port while the modem runs. So,
with no session up and only for a modem kissterm started (it cannot stop
one it does not own, and says so): stop the modem, start `rigctld`, tune and
switch the ATU in, stop `rigctld`, and reopen the transport, which starts the
modem again through the supervisor. The reopening is in a `finally`: the
modem comes back on every path, a `rigctld` that fails mid-tune included. It
costs the modem's startup time on every channel change, which is why it is
the last choice (SETUP.md).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from ..rig.frequency import Tuning, band_of
from ..rig.rigctld import RigctldClient, RigError
from .operator import Notice, Severity

log = logging.getLogger(__name__)

#: The ATU covers HF and 6 m; above this there is nothing to switch in.
ATU_LIMIT_HZ = 54_000_000
#: Seconds a cycle is assumed to take when the rig does not report PTT, and
#: the most one may take when it does.
TUNE_SECONDS = 5.0
TUNE_MAX = 15.0
#: Seconds to look for the rig reporting the cycle's carrier.
TUNE_SEEN = 3.0
POLL = 0.25


class Tuner:
    """`Core.tuner`."""

    def __init__(self, core) -> None:
        self.core = core
        #: Rig name -> (settable functions, operations), from `learn`.
        self.caps: dict[str, tuple[frozenset, frozenset]] = {}

    # -- what the rig can do ----------------------------------------------------
    async def learn(self, client: RigctldClient, rig: dict) -> None:
        """Ask once per rig (`U ?`, `G ?`); a read, nothing changes."""
        name = str(rig.get("name", ""))
        if name in self.caps:
            return
        funcs: set[str] = set()
        ops: set[str] = set()
        with contextlib.suppress(RigError):
            funcs = await client.set_functions()
        with contextlib.suppress(RigError):
            ops = await client.vfo_ops()
        self.caps[name] = (frozenset(funcs), frozenset(ops))
        log.info("%s: ATU %s, tuning cycle %s", name, "TUNER" in funcs, "TUNE" in ops)

    def has_atu(self, rig: dict | None) -> bool:
        return bool(rig) and "TUNER" in self.caps.get(str(rig.get("name", "")), ((), ()))[0]

    def can_cycle(self, rig: dict | None) -> bool:
        return bool(rig) and "TUNE" in self.caps.get(str(rig.get("name", "")), ((), ()))[1]

    def will_cycle(self, tuning: Tuning | None) -> bool:
        """Whether a confirmed connect tuned to `tuning` also runs an ATU
        cycle: the rig can, and the operator chose that band."""
        rig = self.core.rigwatch.active_rig()
        if tuning is None or rig is None or self.core.rigwatch.owns_cat_port():
            return False
        band = band_of(tuning.hz)
        return bool(band) and band in (rig.get("tune_bands") or []) and self.can_cycle(rig)

    # -- no carrier -------------------------------------------------------------
    async def atu_on(self, client: RigctldClient, rig: dict, tuning: Tuning) -> None:
        """Switch the ATU in after a tune (`U TUNER 1`). Silent; a refusal
        is logged, never raised."""
        if tuning.hz >= ATU_LIMIT_HZ or not self.has_atu(rig):
            return
        try:
            await client.set_tuner(True)
        except RigError as exc:
            log.warning("%s: could not switch the ATU in: %s", rig.get("name"), exc)

    # -- a carrier --------------------------------------------------------------
    async def cycle(self, tuning: Tuning) -> str:
        """Run one ATU tuning cycle: "" when done, else why not. KEYS THE
        RADIO. Only from a connect the operator confirmed, after it armed
        the gate."""
        core = self.core
        rig = core.rigwatch.active_rig()
        if rig is None:
            return "No radio is set up for this transport."
        name = str(rig.get("name", "the radio"))
        if not core.gate.allow():  # the moment of transmission
            log.warning("TX BLOCKED: ATU cycle on %s; transmit is off", name)
            return "transmit is off"
        client = RigctldClient.from_rig(rig)
        core.swr.suspend(TUNE_MAX + 2)
        try:
            log.info("ATU cycle on %s at %s: a few seconds of carrier", name, tuning.describe())
            self._say(f"Tuning {name}'s ATU on {tuning.describe()}: a few seconds of carrier.")
            await client.tune()
            started = time.monotonic()
            seen = False
            while True:
                await asyncio.sleep(POLL)
                elapsed = time.monotonic() - started
                if not core.gate.enabled:
                    with contextlib.suppress(RigError):
                        await client.set_ptt(False)
                    return "transmit was turned off during the ATU cycle"
                try:
                    keyed = await client.get_ptt()
                except RigError:
                    keyed = False
                if keyed:
                    seen = True
                elif seen or (elapsed >= TUNE_SEEN and elapsed >= TUNE_SECONDS):
                    break
                if elapsed >= TUNE_MAX:
                    with contextlib.suppress(RigError):
                        await client.set_ptt(False)
                    return f"the ATU was still tuning after {TUNE_MAX:g} s"
        except RigError as exc:
            return str(exc)
        finally:
            await client.close()
        log.info("ATU cycle on %s done", name)
        return ""

    # -- the hand-off -----------------------------------------------------------
    def handoff_problem(self) -> str:
        """Why the CAT port cannot be handed over now, "" when it can."""
        core = self.core
        entry = core.rigwatch._entry() or {}
        program = str(entry.get("program") or "")
        status = core.supervisor.status(program) if program else {}
        if not status.get("started_by_kissterm"):
            return (f"{program or 'The modem'} owns the radio's CAT port and was not started "
                    "by kissterm, so kissterm cannot hand the port over. Tune by hand.")
        if not status.get("running"):
            return f"{program} is not running: open its transport again first."
        sessions = core.sessions
        if sessions is not None and any(
                s.link is not None and s.link.connected for s in sessions.by_key.values()):
            return "Disconnect first: handing the CAT port over restarts the modem."
        return ""

    def describe_handoff(self) -> str:
        program = str((self.core.rigwatch._entry() or {}).get("program") or "the modem")
        return f"stops {program} to use the CAT port, then starts it again"

    async def handoff(self, tuning: Tuning) -> str:
        """Tune through a CAT port the modem owns: "" when tuned and the
        modem is back, else why not. No carrier."""
        core = self.core
        problem = self.handoff_problem()
        if problem:
            return problem
        rig = core.rigwatch.active_rig() or {}
        entry = dict(core.rigwatch._entry() or {})
        program, name = str(entry.get("program")), str(entry.get("name"))
        rigctld_name = f"rigctld {rig.get('name', '')}".strip()
        self._say(f"Handing the CAT port over: stopping {program}...")
        problem = ""
        try:
            await core.supervisor.stop(program)
            problem = await core.supervisor.ensure_rigctld(rig)
            if not problem:
                client = RigctldClient.from_rig(rig)
                try:
                    client.reset_backoff()
                    await self.learn(client, rig)
                    await client.set_frequency(tuning.hz)
                    if tuning.mode:
                        await client.set_mode(tuning.mode, 0)
                    await self.atu_on(client, rig, tuning)
                except RigError as exc:
                    problem = str(exc)
                finally:
                    await client.close()
        except Exception as exc:  # noqa: BLE001 - the modem still comes back
            problem = str(exc) or type(exc).__name__
        finally:
            with contextlib.suppress(Exception):
                await core.supervisor.stop(rigctld_name)
            self._say(f"Starting {program} again...")
            reopen = (core.switch_frame_transport if core.station is not None
                      else core.switch_session_transport)
            back = False
            with contextlib.suppress(Exception):
                back = await reopen(name)
            if not back:
                problem = problem or f"{program} did not come back; check Settings > Radio."
        if problem:
            return problem
        self._say(f"Tuned to {tuning.describe()}; {program} is back.")
        return ""

    def _say(self, text: str, severity: Severity = Severity.INFORMATION) -> None:
        with contextlib.suppress(Exception):
            self.core.operator.notice(Notice(text, severity))
