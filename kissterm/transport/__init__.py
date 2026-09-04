"""The transport package: tier ABCs, `Session`, and a config-driven factory.

`build_transport` is the one place that knows how a config dict turns into a
concrete transport instance, so the setup wizard and any config-file loader
share exactly one mapping from ``kind`` string to class -- add a transport
here once and every caller gets it, instead of each call site growing its own
copy of the dispatch table that drifts out of sync with the others.

Every concrete transport module is imported *inside* `build_transport`, not
at the top of this file. Several of them depend on optional third-party
packages (`pyserial`/`pyserial-asyncio-fast` for serial, nothing extra for
TCP/AGWPE, platform-specific socket families for Bluetooth and kernel AX.25)
or are only meaningful on Linux. If this package imported all of them eagerly,
`import kissterm.transport` -- which plenty of code needs just to reach
`Transport`/`Session`/`TransportError` -- would fail on any machine missing
one optional dependency, even for a user who only ever wants plain TCP KISS.
Lazy imports keep the base ABCs importable everywhere and push the "is this
optional dependency installed" question to the moment a transport of that
specific kind is actually requested.
"""

from __future__ import annotations

from typing import Any

from .base import (
    FrameHandler,
    FrameTransport,
    Session,
    SessionState,
    SessionTransport,
    Transport,
    TransportError,
    TransportInfo,
    TransportState,
)

__all__ = [
    "FrameHandler",
    "FrameTransport",
    "Session",
    "SessionState",
    "SessionTransport",
    "Transport",
    "TransportError",
    "TransportInfo",
    "TransportState",
    "build_transport",
]

#: Config ``kind`` values `build_transport` accepts, kept as a tuple (rather
#: than derived from a dict of already-imported classes) precisely so this
#: list can exist without importing anything optional.
_VALID_KINDS = (
    "serial",
    "tcp",
    "agwpe",
    "bluetooth",
    "kernel",
    "vara",
    "varafm",
    "mercury",
)


def build_transport(config: dict[str, Any]) -> Transport:
    """Build a transport from a plain config dict.

    ``config["kind"]`` selects the transport; every other key is passed
    through as keyword arguments to that transport's constructor, so the
    accepted keys are whatever each transport class's ``__init__`` declares
    (see that class's docstring). Raises `TransportError` for an unknown or
    missing ``kind`` rather than letting a typo surface as a `KeyError` deep
    inside a dispatch dict.
    """
    kind = config.get("kind")
    if kind not in _VALID_KINDS:
        raise TransportError(
            f"unknown transport kind {kind!r}; valid kinds are: "
            + ", ".join(_VALID_KINDS)
        )

    kwargs = {k: v for k, v in config.items() if k != "kind"}

    if kind == "serial":
        from .serial_kiss import SerialKissTransport

        return SerialKissTransport(**kwargs)

    if kind == "tcp":
        from .tcp_kiss import TcpKissTransport

        return TcpKissTransport(**kwargs)

    if kind == "agwpe":
        from .agwpe import AgwpeTransport

        return AgwpeTransport(**kwargs)

    if kind == "bluetooth":
        from .bluetooth import BluetoothKissTransport

        return BluetoothKissTransport(**kwargs)

    if kind == "kernel":
        from .kernel_ax25 import KernelAx25Transport

        return KernelAx25Transport(**kwargs)

    if kind == "vara":
        from .vara import VaraHfTransport

        return VaraHfTransport(**kwargs)

    if kind == "varafm":
        from .vara import VaraFmTransport

        return VaraFmTransport(**kwargs)

    if kind == "mercury":
        from .mercury import MercuryTransport

        return MercuryTransport(**kwargs)

    # Unreachable: _VALID_KINDS and the branches above are kept in sync, but
    # fail loudly rather than falling through to `None` if they ever drift.
    raise AssertionError(f"transport kind {kind!r} listed as valid but not dispatched")
