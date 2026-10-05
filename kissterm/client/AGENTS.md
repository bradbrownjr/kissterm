# AGENTS.md — kissterm/client

The remote client (ROADMAP P7a M8): the other end of `docs/PROTOCOL.md`.

1. **Talks only the protocol.** Never import `kissterm.core`, `ui`,
   `serve`, `transport` or `ax25` (`tests/unit/test_client.py`): it runs
   on a phone with no station in it, and has no path around the gate.
2. **`connection.py` and `state.py` have no UI** and are tested against a
   real server on a loopback station. Widgets read `StationState`; they
   never hold station state of their own.
3. **Show what the station said, not what was asked**: a typed line
   appears when `LineSent` comes back. Never retry a command after a
   reconnect (a line sent twice is transmitted twice).
4. **`timer-recovery` is a connected link** (AGENTS.md section 3).
5. **A swipe never transmits** (DESIGN.md): a row's swipe opens a
   confirmation or an editor; only a button press in that sheet sends.
