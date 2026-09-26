"""Saved logins in the operator's OS keyring, when there is one.

A saved credential (`Config.credentials`, Settings > Logins; the Winlink
password) is a secret, and config.toml is a plain file people copy between
machines and paste into bug reports. So when the system has a keyring --
GNOME Keyring or KWallet through the Secret Service, macOS Keychain,
Windows Credential Locker -- the text lives there, under the service name
"kissterm" and the credential's name, and config.toml keeps only
`{"name": ..., "store": "keyring"}`. Uses the `keyring` package
(pypi.org/project/keyring), which picks the platform's backend.

**Where there is no keyring** -- a headless Linux session over SSH, a
container, a Raspberry Pi without a desktop -- `keyring` returns its "fail"
backend and the text stays in config.toml as before, and Settings says
which store holds it. Never a crash, never a silently dropped password
(AGENTS.md: a missing optional dependency never raises out of a task).

A keyring that stops answering later (locked, or the session changed) makes
`get` return None: the caller treats that as "no text" and says so, since
sending nothing at a login prompt is a smaller problem than crashing the
connect.

Tests never touch the real keyring: `kissterm._isolate.isolate()` points
`keyring` at its fail backend before anything imports it, and the keyring
tests install an in-memory backend of their own.
"""

from __future__ import annotations

import logging

SERVICE = "kissterm"

log = logging.getLogger(__name__)


def _keyring():
    """The `keyring` module with a usable backend, or None."""
    try:
        import keyring
        from keyring.backends import fail
    except ImportError:
        return None
    try:
        backend = keyring.get_keyring()
    except Exception:  # noqa: BLE001 - a broken backend is "no keyring"
        return None
    if isinstance(backend, fail.Keyring) or type(backend).__module__.endswith(".null"):
        return None
    return keyring


def available() -> bool:
    """True when saved logins can go to an OS keyring."""
    return _keyring() is not None


def get(name: str) -> str | None:
    """The text stored under `name`, or None if there is no keyring or no
    such entry, or the keyring would not answer."""
    keyring = _keyring()
    if keyring is None:
        return None
    try:
        return keyring.get_password(SERVICE, name)
    except Exception as exc:  # noqa: BLE001
        log.warning("keyring: could not read %r: %s", name, exc)
        return None


def put(name: str, text: str) -> bool:
    """Store `text` under `name`. False if it could not be stored (the
    caller then keeps it in config.toml)."""
    keyring = _keyring()
    if keyring is None:
        return False
    try:
        keyring.set_password(SERVICE, name, text)
    except Exception as exc:  # noqa: BLE001
        log.warning("keyring: could not store %r: %s", name, exc)
        return False
    return True


def delete(name: str) -> None:
    """Remove `name` from the keyring, if it is there."""
    keyring = _keyring()
    if keyring is None:
        return
    try:
        keyring.delete_password(SERVICE, name)
    except Exception:  # noqa: BLE001 - not there is fine
        pass
