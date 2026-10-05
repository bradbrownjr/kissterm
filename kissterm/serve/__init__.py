"""The remote-control server (ROADMAP P7a M7; docs/PROTOCOL.md).

`pairing` (the token and the link), `wire` (the JSON forms), `operator`
(questions and notices for remote clients), `server` (the WebSocket
server), `headless` (`kissterm --serve` with no terminal UI). Needs the
`[serve]` extra (uvicorn, Starlette, `websockets`, `segno`; `http.py`
holds the listener); nothing else in kissterm imports this package unless
serving is asked for.
"""

#: The `serve` extra's modules (pyproject.toml).
EXTRA_MODULES = ("starlette", "uvicorn", "websockets", "segno")


def available() -> bool:
    """Whether the `serve` extra is installed."""
    import importlib.util

    return all(importlib.util.find_spec(name) is not None for name in EXTRA_MODULES)
