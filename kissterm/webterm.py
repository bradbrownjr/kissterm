"""`kissterm --web-terminal`: this terminal UI, keys and all, on a web page.

**This is not the remote control.** The remote control (`kissterm --serve`,
`kissterm/serve/`) is the supported way to reach a station from a browser:
a pairing link that is a key, checked on every connection. The web
terminal is Textual's `textual-serve` running kissterm as it is, and it
has **no pairing and no login**: anyone who can open its address can key
the radio under the operator's callsign. It stays because it costs nothing
and shows the whole terminal, but only as a deliberate opt-in, with that
warning printed where it is started (operator, 2026-10-06: "it should be a
toggle for web based terminal, vs the actual web UI, with the warning in
the command line"). It listens on localhost unless told otherwise.

`textual-serve` sets `TEXTUAL_DRIVER` for the kissterm it runs, which is
how that kissterm knows there is no terminal to ask "start anyway?" on
(`__main__._offer_start_anyway`).
"""

from __future__ import annotations

import shlex
import sys

DEFAULT_ADDRESS = "127.0.0.1:8765"
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def available() -> bool:
    try:
        import textual_serve  # noqa: F401
    except ImportError:
        return False
    return True


def parse_address(text: str) -> tuple[str, int]:
    """`HOST:PORT`, `PORT` or `HOST` (on the default port)."""
    default_host, default_port = DEFAULT_ADDRESS.rsplit(":", 1)
    text = text.strip()
    if text.isdigit():
        return default_host, int(text)
    if ":" in text:
        host, port = text.rsplit(":", 1)
        return host or default_host, int(port)
    return text or default_host, int(default_port)


def warning(host: str, port: int) -> str:
    where = (f"anyone on this machine who opens http://{host}:{port}"
             if host in _LOOPBACK else
             f"ANYONE ON THE NETWORK who opens http://{host}:{port}")
    return (
        "WARNING: the web terminal has no pairing link and no login.\n"
        f"{where} can key your radio under your callsign.\n"
        "For a browser or phone, use the remote control instead: kissterm --serve,\n"
        "or Settings > Remote, which admits only a paired device."
    )


def command(args) -> str:
    """The kissterm each browser session runs: this one, with the options
    that choose its station passed through."""
    argv = [sys.executable, "-m", "kissterm"]
    if args.profile and args.profile != "default":
        argv += ["--profile", args.profile]
    if args.transport:
        argv += ["--transport", args.transport]
    if args.no_update_check:
        argv.append("--no-update-check")
    argv += ["--log-level", args.log_level]
    return shlex.join(argv)


def run(args) -> int:
    if not available():
        print("The web terminal needs its extra: pip install 'kissterm[webterm]'",
              file=sys.stderr)
        return 2
    try:
        host, port = parse_address(args.web_terminal)
    except ValueError:
        print(f"Not an address: {args.web_terminal!r} (use HOST:PORT)", file=sys.stderr)
        return 2
    print(warning(host, port), file=sys.stderr, flush=True)
    from textual_serve.server import Server

    Server(command(args), host=host, port=port, title="kissterm").serve()
    return 0
