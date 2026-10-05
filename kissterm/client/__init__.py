"""The remote client (ROADMAP P7a M8): a phone, desktop or browser
driving a station that runs `kissterm --serve` or Settings > Remote.

`connection` (the WebSocket, reconnects, commands) and `state` (what the
station said, as a model) have no UI and are tested on a loopback station;
`ui/` is the Flet app built on them. Talks to the station only through
the protocol (docs/PROTOCOL.md): never imports `kissterm.core` or
`kissterm.ui`, so it runs wherever the station is not
(`tests/unit/test_client.py`).
"""
