"""The token that admits a remote client, and the link that carries it
(docs/PROTOCOL.md section 2).

**One token per machine, stable across launches** (operator, 2026-10-05:
a bookmark must keep working, and every machine's link must differ). Made
once with `secrets`, kept in the state folder -- not config.toml, which
people copy between machines and paste into bug reports -- readable by
this user only. **Rotate** replaces it: the old link stops working at
once, the answer to a leaked one.

**The link is a URL with the token in the fragment** (`#t=...`). A
browser never sends a fragment in an HTTP request, so the token stays out
of proxy and server logs. Behind a reverse proxy that adds TLS (Caddy),
`serve.public_url` is the address clients use; otherwise it is this
machine's own LAN address.

Holding the token is holding the station's transmitter, under the
operator's callsign. Never log it, never put it in a notice.

**Whether a device has paired** with the current link is kept beside it
(`mark_paired`, `has_paired`): a hash of the token a client last signed in
with, never the token. The terminal opens the pairing screen when remote
control is turned on only while nothing has paired yet (operator,
2026-10-06: a device already paired does not need it); a rotated link
starts unpaired.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import secrets
import socket
from pathlib import Path

#: 32 random bytes, URL-safe: what `secrets` recommends for a bearer token.
TOKEN_BYTES = 32


def token_path() -> Path:
    from ..config import state_path

    return state_path() / "remote-token"


def _write(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    # Created 0600, never widened: the token must not be readable by other
    # users on a shared machine, even for the moment before a chmod.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(token + "\n")
    os.replace(tmp, path)


def load_token(path: Path | None = None) -> str:
    """This machine's token, made on first use."""
    path = path or token_path()
    with contextlib.suppress(OSError):
        token = path.read_text(encoding="ascii").strip()
        if len(token) >= 32:
            return token
    token = secrets.token_urlsafe(TOKEN_BYTES)
    _write(path, token)
    return token


def rotate_token(path: Path | None = None) -> str:
    """A new token; the old one is no longer accepted."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    _write(path or token_path(), token)
    return token


def paired_path() -> Path:
    from ..config import state_path

    return state_path() / "remote-paired"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mark_paired(token: str, path: Path | None = None) -> None:
    """A client signed in with `token`. A file that cannot be written
    costs only an extra look at the pairing screen."""
    path = path or paired_path()
    with contextlib.suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_digest(token) + "\n", encoding="ascii")


def has_paired(token: str, path: Path | None = None) -> bool:
    """Whether any client has signed in with `token`, this link."""
    with contextlib.suppress(OSError):
        return (path or paired_path()).read_text(encoding="ascii").strip() == _digest(token)
    return False


def lan_address() -> str:
    """This machine's address on the network it routes by, or 127.0.0.1.

    A UDP "connect" picks the outgoing interface without sending a packet.
    """
    with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    return "127.0.0.1"


def base_url(serve) -> str:
    """Where a client reaches this server (`serve`: `config.ServeConfig`),
    without the token: the public URL, else this machine's address."""
    if serve.public_url:
        return serve.public_url.rstrip("/")
    scheme = "https" if serve.tls_cert else "http"
    host = "127.0.0.1" if serve.listen.startswith("127.") else lan_address()
    return f"{scheme}://{host}:{serve.port}"


def pairing_url(serve, token: str) -> str:
    return f"{base_url(serve)}/#t={token}"


def websocket_url(serve) -> str:
    """The `/v1` WebSocket address for `base_url`."""
    url = base_url(serve)
    return ("wss" + url[5:] if url.startswith("https") else "ws" + url[4:]) + "/v1"


#: Light modules around the code. The standard asks for 4; 2 scans
#: reliably off a screen and keeps the code inside an 80x24 terminal.
QR_BORDER = 2


def qr_lines(url: str) -> list[str]:
    """`url` as a QR code in half-block characters, two module rows per
    text row, light modules drawn: show it light-on-dark (`qr_text`, the
    pairing dialog) whatever the terminal's theme, or it will not scan.
    [] without segno."""
    try:
        import segno
    except ImportError:
        return []
    rows = [list(row) for row in segno.make(url, error="l").matrix_iter(border=QR_BORDER)]
    if len(rows) % 2:
        rows.append([0] * len(rows[0]))
    glyph = {(True, True): "\u2588", (True, False): "\u2580",
             (False, True): "\u2584", (False, False): " "}
    return ["".join(glyph[(not top, not bottom)] for top, bottom in zip(upper, lower))
            for upper, lower in zip(rows[0::2], rows[1::2])]


def qr_text(url: str) -> str:
    """`qr_lines` for a plain terminal: bright white on black, explicitly,
    so a light theme does not invert it. "" without segno."""
    return "".join(f"\x1b[97;40m{line}\x1b[0m\n" for line in qr_lines(url))
