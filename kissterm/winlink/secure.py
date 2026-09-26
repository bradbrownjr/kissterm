"""The Winlink secure login: answering the CMS's `;PQ:` challenge.

A Winlink gateway that wants a password sends `;PQ: <challenge>` (eight
digits) in its handshake, and the client answers `;PR: <response>`. The
password itself never goes over the air: the response is eight digits of
an MD5 over the challenge, the password and a fixed salt, so a listener
learns nothing they could replay against a different challenge.

Ported from wl2k-go `fbb/secure.go` (MIT, LA5NTA), itself a port of
paclink-unix's; tested against wl2k-go's own vectors
(`tests/unit/test_winlink_secure.py`). The password is case-sensitive
(the two vectors differ only in case) -- the CMS stores it as typed.
"""

from __future__ import annotations

import hashlib

#: The fixed salt, as in wl2k-go and paclink-unix.
_SALT = bytes((
    77, 197, 101, 206, 190, 249, 93, 200, 51, 243, 93, 237, 71, 94, 239, 138,
    68, 108, 70, 185, 225, 137, 217, 16, 51, 122, 193, 48, 194, 195, 198, 175,
    172, 169, 70, 84, 61, 62, 104, 186, 114, 52, 61, 168, 66, 129, 192, 208,
    187, 249, 232, 193, 41, 113, 41, 45, 240, 16, 29, 228, 208, 228, 61, 20,
))


def login_response(challenge: str, password: str) -> str:
    """The eight digits to send as `;PR:` for this `;PQ:` challenge."""
    digest = hashlib.md5(challenge.encode("latin-1") + password.encode("utf-8") + _SALT).digest()
    value = ((digest[3] & 0x3F) << 24) | (digest[2] << 16) | (digest[1] << 8) | digest[0]
    return f"{value:08d}"[-8:]
