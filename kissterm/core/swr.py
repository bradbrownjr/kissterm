"""The SWR watch and trip: stop transmitting into a broken antenna (ROADMAP
P3a M5b).

A wire antenna that comes down in a storm should not be fed for the rest of
an unattended mail session. While the active transport's radio is keyed,
this reads its SWR through `rigctld` (`l SWR`) a few times a second. Above
the rig's `swr_warn` it says so once per transmission; above `swr_trip` for
`CONSECUTIVE` readings in a row it **trips**:

1. the radio is unkeyed: by `core/ptt.py` when kissterm keyed it (VARA),
   else `T 0` (harmless if it was not keyed over CAT) and the modem program
   stopped if kissterm started it (stopping Direwolf or SoundModem drops its
   RTS); a modem kissterm cannot stop is named as still able to key;
2. the transmit gate is closed **and latched** (`TransmitGate.latch_closed`),
   so nothing of kissterm's transmits again -- beacon, answering, the
   tactical ID, a confirmed connect's `arm_for` -- and a VARA or Mercury
   modem is told `ABORT`, a local command, so it stops retrying;
3. the trip is saved (`swr_trip.json` in the state folder) and shown at the
   next launch: a restart does not clear it;
4. a notice, an `Alert` (a desktop notification; the phone's alert), the
   session transcripts and kissterm.log say so.

Only the operator clears it: turning transmit on (Ctrl+T, the phone's
switch) asks `SwrRearm` first, through the `Operator` port so either front
end answers it (`ask_rearm`).

**What Hamlib's number is** (Hamlib source, read 2026-10-09; cited in
docs/SOURCES.md): `RIG_LEVEL_SWR` is a float ratio, interpolated from the
backend's calibration table and clamped to its ends (`rig_raw2val_float`,
`src/cal.c`). The FT-991 backend reads the `RM6` meter through Yaesu's
default table, 1.0 to 5.0 (`newcat.c`); the IC-7300's table runs 1.0 to
6.0 (`ic7300.c`). A backend with no table returns the raw meter count
instead, which this cannot tell from a ratio: UNVERIFIED per rig, and the
on-air test sets `swr_trip` just under the antenna's real SWR to prove it.
A backend without the level answers `RPRT -4`/`-11`, and the watch says so
once and stops reading SWR.

**Not hardware protection**, and the setting's help says so: it reacts at
this polling rate, many rigs fold power back by themselves, and it works
only where the backend reads SWR while transmitting. What it adds is that
the station stops trying. Readings are ignored for `SETTLE` seconds after
key-up (the rig's own ramp, an ATU's first moments) and while `suspend` is
in force (an ATU cycle, M6b), and one high reading never trips.

**Knowing the radio is keyed.** When kissterm keyed it (`Core.ptt.keyed`) it
knows. Otherwise the rig is asked (`t`) once a second; whether a rig reports
PTT that another port keyed (an FT-991A's DATA jack keyed by RTS) is
UNVERIFIED per rig, and where it does not, the watch covers only
transmissions kissterm keys.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime

from ..rig.frequency import Tuning
from ..rig.rigctld import RigctldClient, RigError
from .events import Alert, ConfigChanged, TransportChanged
from .operator import Notice, Severity

log = logging.getLogger(__name__)

#: Seconds between SWR readings while keyed, and between PTT questions
#: (`t`) while kissterm has not keyed it.
SWR_POLL = 0.3
PTT_POLL = 1.0
#: Seconds after key-up when readings are ignored.
SETTLE = 1.0
#: Readings over the limit in a row that trip it.
CONSECUTIVE = 3
#: Hamlib's "not implemented" and "not available" (`rig.h`).
_NO_LEVEL = (-4, -11)
STATE_FILE = "swr_trip.json"


@dataclass(frozen=True)
class Trip:
    swr: float
    frequency: int
    mode: str
    rig: str
    at: str  # ISO 8601, local time

    def describe(self) -> str:
        when = datetime.fromisoformat(self.at).strftime("%H:%M")
        where = f" on {Tuning(self.frequency, self.mode).describe()}" if self.frequency else ""
        return f"SWR tripped at {self.swr:.1f}:1{where} at {when}"


def _state_file():
    from ..config import state_path

    return state_path() / STATE_FILE


def load_trip() -> Trip | None:
    try:
        return Trip(**json.loads(_state_file().read_text(encoding="utf-8")))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError) as exc:
        log.warning("could not read the saved SWR trip: %s", exc)
        return None


class SwrWatch:
    """`Core.swr`."""

    def __init__(self, core) -> None:
        self.core = core
        #: The trip holding transmit off, or None.
        self.trip: Trip | None = load_trip()
        #: The last reading while keyed, for status and `--doctor`.
        self.last: float | None = None
        #: Why SWR is not being watched, "" when it is (or there is no rig).
        self.problem = ""
        self.suspended_until = 0.0
        self._task: asyncio.Task | None = None
        self._key: tuple = ()
        self._unsubscribe = None
        self._said_trip = False
        if self.trip is not None:
            core.gate.latch_closed(self.trip.describe())

    # -- following the active radio --------------------------------------------
    def start(self) -> None:
        if self._unsubscribe is None:
            def changed(_seq, event) -> None:
                if isinstance(event, (TransportChanged, ConfigChanged)):
                    self.refresh()

            self._unsubscribe = self.core.events.subscribe(changed)
        if self.trip is not None and not self._said_trip:
            self._said_trip = True
            self._say(f"Transmit is held off: {self.trip.describe()} (before kissterm was "
                      "last closed). Check the antenna; turning transmit on asks first.",
                      Severity.ERROR)
        self.refresh()

    def _limits(self, rig: dict) -> tuple[float, float]:
        def number(key: str, default: float) -> float:
            try:
                return float(rig.get(key, default))
            except (TypeError, ValueError):
                return default
        return number("swr_warn", 2.0), number("swr_trip", 3.0)

    def refresh(self) -> None:
        rigwatch = self.core.rigwatch
        rig = rigwatch.active_rig()
        if rig is not None and (rigwatch.owns_cat_port() or not any(self._limits(rig))):
            rig = None
        key = (rig.get("name"), rig.get("host"), rig.get("port"), *self._limits(rig)) if rig else ()
        if key == self._key and (self._task is not None and not self._task.done()) == bool(key):
            return
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self._key, self.problem = key, ""
        if rig is None:
            return
        try:
            self._task = asyncio.get_running_loop().create_task(self._run(dict(rig)))
        except RuntimeError:
            self._key = ()

    async def shutdown(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    def suspend(self, seconds: float) -> None:
        """Ignore readings for `seconds` (an ATU tuning cycle)."""
        self.suspended_until = max(self.suspended_until, time.monotonic() + seconds)

    # -- the watch -------------------------------------------------------------
    async def _keyed(self, client: RigctldClient) -> bool:
        if self.core.ptt.keyed:
            return True
        try:
            return await client.get_ptt()
        except RigError:
            return False

    async def _run(self, rig: dict) -> None:
        warn, limit = self._limits(rig)
        client = RigctldClient.from_rig(rig)
        since: float | None = None
        over = 0
        warned = False
        try:
            while True:
                if not await self._keyed(client):
                    since, over, warned = None, 0, False
                    await asyncio.sleep(PTT_POLL)
                    continue
                now = time.monotonic()
                if since is None:
                    since = now
                if now - since < SETTLE or now < self.suspended_until:
                    await asyncio.sleep(SWR_POLL)
                    continue
                try:
                    swr = await client.get_swr()
                except RigError as exc:
                    if exc.code in _NO_LEVEL:
                        self.problem = f"{rig.get('name')} does not report SWR through Hamlib"
                        log.warning("%s: SWR is not watched", self.problem)
                        return
                    await asyncio.sleep(SWR_POLL)
                    continue
                self.last = swr
                if limit and swr > limit:
                    over += 1
                    if over >= CONSECUTIVE:
                        await self.trip_now(swr, rig, client)
                        since, over = None, 0
                        await asyncio.sleep(PTT_POLL)
                        continue
                else:
                    over = 0
                if warn and swr > warn and not warned:
                    warned = True
                    self._say(f"SWR {swr:.1f}:1 on {rig.get('name')} (warning above "
                              f"{warn:g}). Check the antenna.", Severity.WARNING)
                await asyncio.sleep(SWR_POLL)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - never raise out of a background task
            log.exception("the SWR watch stopped")
        finally:
            await client.close()

    # -- the trip --------------------------------------------------------------
    async def trip_now(self, swr: float, rig: dict, client: RigctldClient | None = None) -> None:
        core = self.core
        state = core.rigwatch.state
        trip = Trip(round(swr, 2), state.frequency if state else 0, state.mode if state else "",
                    str(rig.get("name", "")), datetime.now().isoformat(timespec="seconds"))
        self.trip = trip
        # 1. Unkey.
        still = ""
        if core.ptt.keyed:
            core.ptt.stop_for_trip()
        else:
            if client is not None:
                with contextlib.suppress(RigError):
                    await client.set_ptt(False)
            entry = core.rigwatch._entry() or {}
            program = str(entry.get("program") or "")
            status = core.supervisor.status(program) if program else {}
            if status.get("started_by_kissterm") and status.get("running"):
                with contextlib.suppress(Exception):
                    await core.supervisor.stop(program)
            elif program:
                still = f" {program} was not started by kissterm and may still be able to key it."
        # 2. Close and latch the gate; tell a VARA or Mercury modem to stop.
        core.gate.latch_closed(trip.describe())
        abort = getattr(core.session_transport, "abort", None)
        if abort is not None:
            with contextlib.suppress(Exception):
                await abort()
        # 3. Saved, so a restart does not clear it.
        try:
            path = _state_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(trip)), encoding="utf-8")
        except OSError as exc:
            log.error("could not save the SWR trip: %s", exc)
        # 4. Say so everywhere.
        text = (f"{trip.describe()} on {trip.rig}: transmit is off and stays off until you "
                f"turn it on again. Check the antenna.{still}")
        log.error("SWR TRIP: %s", text)
        self._say(text, Severity.ERROR)
        core.events.publish(Alert("SWR trip", text, True, topic="swr"))
        if core.sessions is not None:
            for key in list(core.sessions.by_key):
                with contextlib.suppress(Exception):
                    core.sessions.record(key, f"SWR TRIP: {text}")

    async def ask_rearm(self) -> bool:
        """Before transmit goes back on: True when it may (no trip, or the
        operator said so, which clears the trip)."""
        if not self.core.gate.latch:
            return True
        from .questions import SwrRearm

        text = self.core.gate.latch
        if not await self.core.operator.ask(SwrRearm(text)):
            return False
        self.trip = None
        with contextlib.suppress(FileNotFoundError, OSError):
            _state_file().unlink()
        self.core.gate.clear_latch()
        log.warning("SWR trip cleared by the operator: %s", text)
        return True

    def _say(self, text: str, severity: Severity) -> None:
        with contextlib.suppress(Exception):
            self.core.operator.notice(Notice(text, severity))
