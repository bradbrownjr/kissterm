"""The remote-control server (ROADMAP P7a M7; docs/PROTOCOL.md).

`pairing` (the token and the link), `wire` (the JSON forms), `operator`
(questions and notices for remote clients), `server` (the WebSocket
server), `headless` (`kissterm --serve` with no terminal UI). Needs the
`[serve]` extra (`websockets`, `segno`); nothing else in kissterm imports
this package unless serving is asked for.
"""
