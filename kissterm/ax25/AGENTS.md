# kissterm/ax25 — local contract

The AX.25 protocol layer. **Nothing in this package does I/O.** Every byte
in or out goes through a `kissterm.transport` object. If you find yourself
importing `socket` or `serial` here, you are in the wrong package.

Read this file plus the one source file you are changing. You should not need
the rest of the repo.

## File map — what to edit for what

| Change | File | Size |
|---|---|---|
| Callsign/SSID encoding, digipeater paths, C/H bits | `address.py` | ~240 |
| Frame encode/decode, control-field bit layout, PIDs | `frame.py` | ~318 |
| Sequence numbers, window size, go-back-N selection | `window.py` | ~145 |
| T1/T2/T3 lifecycle, the sync-to-async timer bridge | `timers.py` | ~112 |
| Link state transitions, SABM/UA/DISC/REJ handling | `session.py` | ~700 |
| Routing frames to links, incoming connections | `station.py` | ~200 |

`session.py` is the one deliberately large file. It is a single state machine
and splitting the handlers apart creates a two-way dependency worse than the
size. The two genuinely separable concerns are already extracted into
`window.py` and `timers.py` — put new logic there when it fits.

## The rules that will bite you

1. **Sequence numbers wrap. Never compare them as magnitudes.** `while va < nr`
   is always wrong; use the modular walks in `window.py`. The symptom of
   getting this wrong is "the link stalls after exactly 8 frames".
2. **k must stay below modulo** (7 for modulo 8, 63/127 for modulo 128).
   At k == modulo a full window and an empty one are identical. Enforced in
   both `LinkParams` and `SlidingWindow._clamp_k` — keep both.
3. **`TIMER_RECOVERY` is not an error state.** It is a healthy link probing
   after a T1 expiry. Do not tear links down on it or surface it as a failure.
4. **T1 and T3 are mutually exclusive.** `LinkTimers.start_t1` stops T3.
5. **One REJ, not one per out-of-sequence frame** (`reject_sent` guards it).
   Every extra REJ is airtime asking for something already in flight.
6. **Answer a poll (P=1) with a response carrying F=1, always**, even when busy.
7. **Answer DM to traffic for a link you do not have**, so the caller stops
   retrying N2 times.
8. **Single-threaded, no locks.** `AX25Link` schedules `call_later` timers on
   the running loop. Calling into one from a thread breaks everything.
9. **Never raise out of a frame handler.** Line noise produces malformed frames
   constantly; log and continue.
10. `V(S)`/`V(R)`/`V(A)` are **read-only properties** on `AX25Link`, delegating
    to `SlidingWindow`. Mutate them through the window, never directly.

## Deliberate deviations from the spec

`_ack_upto` resets RC on *any* forward progress, not only on leaving timer
recovery. Rationale and the measurement behind it are in the comment there.
Do not revert it without a test showing it makes a link cling to a dead peer.

## Testing

```bash
.venv/bin/python -m pytest tests/unit/test_ax25_link.py tests/unit/test_window.py -q
```

`tests/loopback.py` wires two frame transports together with injectable frame
loss, so two real stations hold a full conversation with no radio. **Any change
to `session.py` needs a loopback test.** That file is the only conformance
check short of putting the code on the air.

Known trap: do not drain a lossy link with a "went quiet" heuristic — the gap
between chunks is a whole T1 recovery cycle. Use `_drain(link, expect=N)`.
