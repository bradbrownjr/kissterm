# AGENTS.md — kissterm/serve

`kissterm --serve` and the server inside the terminal UI: the core
(`kissterm/core/`) on a WebSocket for phone, desktop and browser clients.
The protocol is `docs/PROTOCOL.md`; `tests/unit/test_serve.py` holds it to
its word.

1. **A command is one core method** (`server.COMMANDS`, the `cmd_`
   methods). Never send on a transport here, never open the gate except
   through the core's own flow (`Connector.arm_for`) or the `transmit`
   switch, which is reported to every screen.
2. **The token admits a client, nothing else.** Checked with
   `hmac.compare_digest` in the hello, never in a URL path or query (proxy
   logs). Never log it or put it in a notice. Stored 0600 in the state
   folder (`pairing.py`), never in config.toml.
3. **Remote bytes are filtered on the station** (`wire.py`): session text
   through `ansi.to_text`, colour as spans; other off-air text through
   `wire.clean`. A client never parses escape codes from the air.
4. **Nobody to ask is never a yes.** Headless, a question with no client
   is a cancel (`RemoteOperator`); inside the terminal the screen and the
   clients race and the first answer wins (`FanOutOperator`).
5. **The event bus is synchronous**: never await in `_on_event` or
   between building a welcome and registering the client (the replay
   would have a gap). Each client has its own queue and writer.
6. Optional dependencies (`websockets`, `segno`) are imported only here,
   and only when serving is asked for.
