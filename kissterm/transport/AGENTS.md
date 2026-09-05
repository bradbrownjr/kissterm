# kissterm/transport — local contract

> **Implement `_send_frame`, never `send_frame`.** `FrameTransport.send_frame`
> is concrete: it checks the master transmit gate (`kissterm/tx.py`) and then
> calls your `_send_frame`. Overriding the public name bypasses the operator's
> TX switch, which means a backend that can key a radio the operator has
> switched off. `tests/unit/test_tx_gate.py` fails if any subclass does it.
> `Session.send` gates the session tier the same way.

Everything that moves bytes to and from a radio. Read this file plus the one
transport you are changing; you should not need the rest of the repo.

## The two tiers — pick the right one before writing anything

Ask one question: **does this thing connect on its own?**

- **No** → it moves AX.25 frames and knows nothing about connections.
  Subclass `FrameTransport`. Its frames feed kissterm's own AX.25 state
  machine. Examples: `serial_kiss.py`, `tcp_kiss.py`, `bluetooth.py`,
  `agwpe.py`.
- **Yes** → it hands back an already-connected byte stream because the modem
  or the kernel already ran the link layer. Subclass `SessionTransport` and
  return a wired-up `Session` from `connect()`. Examples: `vara.py`,
  `mercury.py`, `kernel_ax25.py`.

**Putting a session-tier device behind `FrameTransport` puts two AX.25
implementations on one link and corrupts it.** This is the mistake the tier
split exists to prevent.

## File map

| File | Tier | What it is |
|---|---|---|
| `base.py` | — | The ABCs, `Session`, `TransportInfo`, the state enums |
| `kiss.py` | — | KISS codec only, **no I/O**. Shared by every KISS transport |
| `serial_kiss.py` | frame | KISS over a serial port |
| `tcp_kiss.py` | frame | KISS over TCP (Direwolf et al.), auto-reconnecting |
| `agwpe.py` | frame | AGW Packet Engine raw-frame mode |
| `bluetooth.py` | frame | RFCOMM socket; `BleKissTransport` is a marked stub |
| `kernel_ax25.py` | session | Linux `AF_AX25` sockets |
| `vara.py` | session | VARA HF/FM — command port + data port |
| `mercury.py` | session | Honest stub; raises from `open()` |
| `__init__.py` | — | `build_transport(config)` factory, lazy imports |

## The rules that will bite you

1. **Never transmit anything the operator did not ask for.** Every send keys a
   transmitter on a shared channel under a licensed callsign. Discovery and
   probing listen only — nothing here may key a rig on its own.
2. **Never let a background task die.** A malformed frame, a dropped socket, a
   missing optional dependency: count it, log it, keep the read loop alive.
   Catch **both** `AX25FrameError` and `AX25AddressError` around
   `AX25Frame.decode` — they are distinct types and a corrupt address field
   raises the second one. This already killed read loops once.
3. **Import optional dependencies lazily, inside `open()`**, never at module
   import time, and raise `TransportError` with an actionable message
   (`pip install ...`). `import kissterm` must work with none of them present.
   `build_transport` imports the concrete modules lazily for the same reason.
4. **Guard platform-specific socket families** (`AF_AX25`, `AF_BLUETOOTH`) with
   `hasattr(socket, ...)` and fail from `open()`, never at import.
5. **The KISS codec has no I/O and must stay that way.** It is shared by
   serial, TCP and Bluetooth; a socket call in `kiss.py` forks it three ways.
6. **A silent TNC is indistinguishable from a wrong port.** Never report "not a
   TNC" — report "no traffic seen yet".
7. **Mark inferred protocol details** with `# UNVERIFIED:` or `# RESEARCH:`.
   An honest stub beats an invented wire format. `vara.py` and `mercury.py`
   both carry these; do not "finish" them by guessing.

## Adding a transport

1. Subclass the right tier in a new file here.
2. Add a branch to `build_transport()` in `__init__.py` (lazy import).
3. Add a worked example to `config.toml.example` at the repo root.
4. Add a heuristic to `kissterm/discovery.py` if the device is findable.
5. Add a `kissterm/doctor.py` check if it has a common misconfiguration.

## Testing

```bash
.venv/bin/python -m pytest tests/ -q
```

`tests/loopback.py` is a `FrameTransport` pair for testing without hardware.
There is no loopback for the session tier yet — a fake `SessionTransport`
returning a canned `Session` is the pattern to write when one is needed.
